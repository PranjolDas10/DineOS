"""Closing checklists: daily runs, offline-safe check-offs, overdue alerts, the daily job chain."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.checklists import service
from app.config import MigrationSettings
from app.db import SessionLocal, set_tenant
from tests.conftest import MakeTenant, auth_headers

pytestmark = pytest.mark.anyio
TUESDAY = "2026-10-20"
CLOSE = {
    "name": "Close",
    "days_of_week": [0, 1, 2, 3, 4, 5, 6],
    "due_minutes": 23 * 60 + 30,  # 23:30 local
    "items": [
        {"label": "Fryer off"},
        {"label": "Walk-in at 38F or below"},
        {"label": "Cash counted"},
    ],
}


@pytest.fixture
async def tenant(make_tenant: MakeTenant) -> tuple[UUID, dict[str, str]]:
    tenant_id = await make_tenant()
    owner = create_async_engine(MigrationSettings().migration_database_url)
    async with owner.begin() as conn:
        await conn.execute(
            text("UPDATE tenants SET timezone = 'America/New_York' WHERE id = :t"), {"t": tenant_id}
        )
    await owner.dispose()
    return tenant_id, auth_headers(tenant_id)


@asynccontextmanager
async def as_tenant(tenant_id: UUID) -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session, session.begin():
        await set_tenant(session, tenant_id)
        yield session


async def today(client: AsyncClient, h: dict[str, str], day: str = TUESDAY) -> Any:
    resp = await client.get("/v1/checklists/today", params={"day": day}, headers=h)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def make_template(client: AsyncClient, h: dict[str, str], **overrides: Any) -> Any:
    resp = await client.post("/v1/checklists/templates", json={**CLOSE, **overrides}, headers=h)
    assert resp.status_code == 201, resp.text
    return resp.json()


def op(item_id: str, at: str, checked: bool = True) -> dict[str, Any]:
    return {"id": str(uuid.uuid4()), "item_id": item_id, "checked": checked, "checked_at": at}


async def test_runs_are_created_once_with_an_overdue_job(
    client: AsyncClient, tenant: tuple[UUID, dict[str, str]]
) -> None:
    tenant_id, h = tenant
    await make_template(client, h)
    first, again = await today(client, h), await today(client, h)
    [run] = first["runs"]
    assert again["runs"][0]["id"] == run["id"]  # idempotent: one run per template per day
    assert (run["done"], run["total"]) == (0, 3)
    # 23:30 New York (EDT, UTC-4) on Oct 20 = 03:30 UTC on Oct 21.
    assert run["due_at"].startswith("2026-10-21T03:30")

    async with as_tenant(tenant_id) as session:
        overdue = await session.scalar(
            text("SELECT run_after FROM jobs WHERE dedupe_key = :k"),
            {"k": f"checklist_overdue:{run['id']}"},
        )
        chain = await session.scalar(text("SELECT count(*) FROM jobs WHERE kind = 'checklist_day'"))
    assert overdue == datetime(2026, 10, 21, 3, 30, tzinfo=UTC)
    assert chain == 2  # today + tomorrow, despite three calls that seed the chain


async def test_templates_only_run_on_their_weekdays(
    client: AsyncClient, tenant: tuple[UUID, dict[str, str]]
) -> None:
    _, h = tenant
    await make_template(client, h, days_of_week=[0])  # Mondays only
    assert (await today(client, h, TUESDAY))["runs"] == []
    assert len((await today(client, h, "2026-10-19"))["runs"]) == 1


async def test_checks_are_idempotent_and_order_independent(
    client: AsyncClient, tenant: tuple[UUID, dict[str, str]]
) -> None:
    _, h = tenant
    await make_template(client, h)
    [run] = (await today(client, h))["runs"]
    fryer, walk_in, cash = (i["id"] for i in run["items"])
    url = f"/v1/checklists/runs/{run['id']}/checks"
    batch = {"checks": [op(i, "2026-10-21T03:00Z") for i in (fryer, walk_in, cash)]}

    done = (await client.post(url, json=batch, headers=h)).json()
    replay = (await client.post(url, json=batch, headers=h)).json()  # sync retried
    assert done["done"] == replay["done"] == 3
    assert done["completed_at"] is not None

    # An older uncheck that only now arrives from an offline phone doesn't undo the newer check.
    late = {"checks": [op(fryer, "2026-10-21T02:00Z", checked=False)]}
    assert (await client.post(url, json=late, headers=h)).json()["done"] == 3
    # A newer uncheck does, and the run is no longer complete.
    newer = (
        await client.post(
            url, json={"checks": [op(fryer, "2026-10-21T03:10Z", checked=False)]}, headers=h
        )
    ).json()
    assert (newer["done"], newer["completed_at"]) == (2, None)

    stranger = {"checks": [op(str(uuid.uuid4()), "2026-10-21T03:00Z")]}
    assert (await client.post(url, json=stranger, headers=h)).status_code == 422


async def test_overdue_alert_fires_once_and_not_for_finished_runs(
    client: AsyncClient, tenant: tuple[UUID, dict[str, str]]
) -> None:
    tenant_id, h = tenant
    await make_template(client, h)
    [run] = (await today(client, h))["runs"]
    url = f"/v1/checklists/runs/{run['id']}/checks"
    await client.post(
        url, json={"checks": [op(run["items"][0]["id"], "2026-10-21T03:00Z")]}, headers=h
    )

    for _ in range(2):  # the job ran twice (at-least-once delivery): still one alert
        async with as_tenant(tenant_id) as session:
            await service.checklist_overdue(session, {"run_id": run["id"]})
    alerts = (await client.get("/v1/alerts", headers=h)).json()["items"]
    assert [(a["title"], a["body"]) for a in alerts] == [
        ("Close not finished", "1 of 3 items done; it was due at 23:30.")
    ]

    # Monday's run gets finished in time: its overdue job finds nothing to say.
    [monday] = (await today(client, h, "2026-10-19"))["runs"]
    checks = [op(i["id"], "2026-10-20T03:00Z") for i in monday["items"]]
    await client.post(
        f"/v1/checklists/runs/{monday['id']}/checks", json={"checks": checks}, headers=h
    )
    async with as_tenant(tenant_id) as session:
        await service.checklist_overdue(session, {"run_id": monday["id"]})
    assert len((await client.get("/v1/alerts", headers=h)).json()["items"]) == 1


async def test_daily_job_creates_runs_and_schedules_next_day_once(
    client: AsyncClient, tenant: tuple[UUID, dict[str, str]]
) -> None:
    tenant_id, h = tenant
    await make_template(client, h)
    for _ in range(2):  # retried job: no duplicate runs, no forked chain
        async with as_tenant(tenant_id) as session:
            await service.checklist_day(session, {"date": "2026-11-05"})
    async with as_tenant(tenant_id) as session:
        runs = await session.scalar(
            text("SELECT count(*) FROM checklist_runs WHERE business_date = '2026-11-05'")
        )
        next_day = (
            await session.execute(
                text("SELECT run_after FROM jobs WHERE dedupe_key = 'checklist_day:2026-11-06'")
            )
        ).all()
    assert runs == 1
    # Nov 6 00:00 New York is EST (UTC-5) after the Nov 1 DST change: 05:00 UTC.
    assert next_day == [(datetime(2026, 11, 6, 5, 0, tzinfo=UTC),)]


async def test_editing_a_template_leaves_todays_run_alone(
    client: AsyncClient, tenant: tuple[UUID, dict[str, str]]
) -> None:
    _, h = tenant
    template = await make_template(client, h)
    [run] = (await today(client, h))["runs"]
    resp = await client.patch(
        f"/v1/checklists/templates/{template['id']}",
        json={"items": [{"label": "Only this now"}]},
        headers={**h, "If-Match": '"1"'},
    )
    assert resp.status_code == 200
    [same] = (await today(client, h))["runs"]
    assert [i["label"] for i in same["items"]] == [i["label"] for i in run["items"]]
