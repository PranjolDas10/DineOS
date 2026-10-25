"""Scheduling: no overlapping shifts per person (DB exclusion constraint), labor cost."""

import asyncio
from datetime import datetime
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import MigrationSettings
from app.db import SessionLocal, set_tenant
from tests.conftest import MakeTenant, auth_headers

pytestmark = pytest.mark.anyio
at = datetime.fromisoformat


@pytest.fixture
async def tenant(make_tenant: MakeTenant) -> tuple[UUID, dict[str, str]]:
    """A restaurant in New York (tenants.timezone can only be set by the owner DB role)."""
    tenant_id = await make_tenant()
    owner = create_async_engine(MigrationSettings().migration_database_url)
    async with owner.begin() as conn:
        await conn.execute(
            text("UPDATE tenants SET timezone = 'America/New_York' WHERE id = :t"), {"t": tenant_id}
        )
    await owner.dispose()
    return tenant_id, auth_headers(tenant_id)


async def staff(client: AsyncClient, h: dict[str, str], name: str, rate: int = 1800) -> Any:
    resp = await client.post("/v1/staff", json={"name": name, "hourly_rate_cents": rate}, headers=h)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def shift(client: AsyncClient, h: dict[str, str], staff_id: str, start: str, end: str) -> Any:
    body = {"staff_id": staff_id, "starts_at": start, "ends_at": end}
    return await client.post("/v1/shifts", json=body, headers=h)


async def test_overlap_rejected_back_to_back_allowed(
    client: AsyncClient, tenant: tuple[UUID, dict[str, str]]
) -> None:
    _, h = tenant
    raj, mei = (await staff(client, h, "Raj"))["id"], (await staff(client, h, "Mei"))["id"]
    assert (
        await shift(client, h, raj, "2026-10-20T09:00Z", "2026-10-20T17:00Z")
    ).status_code == 201
    # Half-open ranges: ending at 17:00 and starting at 17:00 is not an overlap.
    assert (
        await shift(client, h, raj, "2026-10-20T17:00Z", "2026-10-20T22:00Z")
    ).status_code == 201

    clash = await shift(client, h, raj, "2026-10-20T16:00Z", "2026-10-20T18:00Z")
    assert clash.status_code == 409
    assert "overlaps" in clash.json()["detail"]
    # The rule is per person: someone else can work those hours.
    assert (
        await shift(client, h, mei, "2026-10-20T16:00Z", "2026-10-20T18:00Z")
    ).status_code == 201


async def test_concurrent_overlapping_shifts_cannot_both_commit(
    client: AsyncClient, tenant: tuple[UUID, dict[str, str]]
) -> None:
    """The race an app-level "check, then insert" loses: both requests see no overlap.
    The exclusion constraint makes the second insert wait for the first, then fail."""
    tenant_id, h = tenant
    raj = (await staff(client, h, "Raj"))["id"]
    insert = text(
        "INSERT INTO shifts (staff_id, during, hourly_rate_cents)"
        " VALUES (:s, tstzrange(:a, :b, '[)'), 1800)"
    )
    async with SessionLocal() as tx1, SessionLocal() as tx2:
        for tx in (tx1, tx2):  # connect both first, so "not done" below means blocked
            await tx.begin()
            await set_tenant(tx, tenant_id)
        await tx1.execute(
            insert, {"s": raj, "a": at("2026-10-20T09:00Z"), "b": at("2026-10-20T17:00Z")}
        )
        second = asyncio.create_task(
            tx2.execute(
                insert, {"s": raj, "a": at("2026-10-20T12:00Z"), "b": at("2026-10-20T20:00Z")}
            )
        )
        await asyncio.sleep(0.5)
        assert not second.done(), "tx2 should wait on tx1's uncommitted conflicting row"
        await tx1.commit()
        with pytest.raises(IntegrityError, match="shifts_no_overlap"):
            await second


async def test_move_and_delete_require_current_etag(
    client: AsyncClient, tenant: tuple[UUID, dict[str, str]]
) -> None:
    _, h = tenant
    raj = (await staff(client, h, "Raj"))["id"]
    created = (await shift(client, h, raj, "2026-10-20T09:00Z", "2026-10-20T17:00Z")).json()
    url = f"/v1/shifts/{created['id']}"

    moved = await client.patch(
        url,
        json={"starts_at": "2026-10-20T10:00Z", "ends_at": "2026-10-20T18:00Z"},
        headers={**h, "If-Match": '"1"'},
    )
    assert moved.status_code == 200
    assert moved.json()["starts_at"].startswith("2026-10-20T10:00")

    assert (await client.delete(url, headers={**h, "If-Match": '"1"'})).status_code == 412
    assert (await client.delete(url, headers={**h, "If-Match": '"2"'})).status_code == 204
    week = await client.get(
        "/v1/shifts",
        params={"start": "2026-10-19T00:00:00Z", "end": "2026-10-26T00:00:00Z"},
        headers=h,
    )
    assert week.json() == {"items": []}


async def test_labor_report_uses_local_business_day_and_rate_snapshot(
    client: AsyncClient, tenant: tuple[UUID, dict[str, str]]
) -> None:
    _, h = tenant
    raj = await staff(client, h, "Raj", rate=1800)  # $18/h
    # Closing shift 17:00-01:00 New York time (EDT, UTC-4) on Oct 20: ends on Oct 21 UTC and
    # local, but it is Oct 20's labor. 8 h * $18 = $144.
    await shift(client, h, raj["id"], "2026-10-20T21:00Z", "2026-10-21T05:00Z")
    # A raise only affects shifts created afterwards. 4.5 h * $25 = $112.50.
    await client.patch(
        f"/v1/staff/{raj['id']}", json={"hourly_rate_cents": 2500}, headers={**h, "If-Match": '"1"'}
    )
    await shift(client, h, raj["id"], "2026-10-21T14:00Z", "2026-10-21T18:30Z")

    report = (
        await client.get(
            "/v1/reports/labor-cost", params={"from": "2026-10-20", "to": "2026-10-21"}, headers=h
        )
    ).json()
    assert report["timezone"] == "America/New_York"
    assert [(d["date"], d["hours"], d["labor_cents"]) for d in report["days"]] == [
        ("2026-10-20", "8.00", 14400),
        ("2026-10-21", "4.50", 11250),
    ]
    assert (report["total_hours"], report["total_labor_cents"]) == ("12.50", 25650)


async def test_invalid_shifts_are_rejected(
    client: AsyncClient, tenant: tuple[UUID, dict[str, str]]
) -> None:
    _, h = tenant
    raj = (await staff(client, h, "Raj"))["id"]
    backwards = await shift(client, h, raj, "2026-10-20T17:00Z", "2026-10-20T09:00Z")
    too_long = await shift(client, h, raj, "2026-10-20T00:00Z", "2026-10-20T17:00Z")
    naive = await shift(client, h, raj, "2026-10-20T09:00", "2026-10-20T17:00")  # no timezone
    assert backwards.status_code == too_long.status_code == naive.status_code == 422

    await client.patch(f"/v1/staff/{raj}", json={"active": False}, headers={**h, "If-Match": '"1"'})
    inactive = await shift(client, h, raj, "2026-10-21T09:00Z", "2026-10-21T17:00Z")
    assert inactive.status_code == 422
