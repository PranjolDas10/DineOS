"""Order inbox: CSV parsing, idempotent imports, versioned orders, replay from the event log."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app import storage
from app.config import MigrationSettings
from app.db import SessionLocal, set_tenant
from app.orders import parsing, service
from tests.conftest import MakeTenant, auth_headers

pytestmark = pytest.mark.anyio
NY = ZoneInfo("America/New_York")

EXPORT = """order_id,placed_at,channel,item,quantity,unit_price,line_total,tax,tip
1001,2026-10-20 18:45,Dine_In,Butter Chicken,2,$17.99,$35.98,$3.15,$6.00
1001,2026-10-20 18:45,Dine_In,Garlic Naan,3,,"$11.97",$3.15,$6.00
1002,2026-10-20 19:10,ubereats,Butter Chicken,1,17.99,17.99,1.57,
"""


def test_parse_groups_rows_into_orders_in_utc() -> None:
    first, second = parsing.parse_sales(EXPORT, "dineos", NY)
    assert first.external_id == "1001"
    assert first.channel == "dine_in"
    # 18:45 in New York (EDT) = 22:45 UTC.
    assert first.placed_at == datetime(2026, 10, 20, 22, 45, tzinfo=UTC)
    assert [(i.name, i.quantity, i.unit_price_cents, i.line_total_cents) for i in first.items] == [
        ("Butter Chicken", Decimal(2), 1799, 3598),
        ("Garlic Naan", Decimal(3), 399, 1197),  # unit price derived from total / quantity
    ]
    assert (first.subtotal_cents, first.tax_cents, first.tip_cents) == (4795, 315, 600)
    assert second.tip_cents == 0  # blank = none


def test_parse_reports_problems_by_line() -> None:
    with pytest.raises(parsing.SalesFileError, match="missing columns: line_total"):
        parsing.parse_sales("order_id,placed_at,channel,item,quantity\n", "dineos", NY)
    bad = (
        EXPORT
        + "1003,2026-10-20 20:00,dine_in,Dal,1,,$9.995,,\n1004,not-a-date,dine_in,Dal,1,,9,,\n"
    )
    with pytest.raises(parsing.SalesFileError) as err:
        parsing.parse_sales(bad, "dineos", NY)
    assert "line 5: '$9.995' has more than 2 decimals" in str(err.value)
    assert "line 6:" in str(err.value)


@pytest.fixture
async def restaurant(make_tenant: MakeTenant) -> tuple[UUID, dict[str, str]]:
    tenant_id = await make_tenant()
    owner = create_async_engine(MigrationSettings().migration_database_url)
    async with owner.begin() as conn:
        await conn.execute(
            text("UPDATE tenants SET timezone = 'America/New_York' WHERE id = :t"), {"t": tenant_id}
        )
    await owner.dispose()
    return tenant_id, auth_headers(tenant_id)


@pytest.fixture
def files(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """Fake storage: object key -> uploaded bytes."""
    uploaded: dict[str, bytes] = {}
    monkeypatch.setattr(storage, "get_bytes", lambda key: uploaded[key])
    return uploaded


async def run_import(
    client: AsyncClient,
    restaurant: tuple[UUID, dict[str, str]],
    files: dict[str, bytes],
    csv_text: str,
) -> Any:
    tenant_id, h = restaurant
    key = (await client.post("/v1/imports/upload-url", headers=h)).json()["object_key"]
    files[key] = ("﻿" + csv_text).encode()  # with a BOM, like a file saved from Excel
    created = await client.post(
        "/v1/imports", json={"source": "dineos", "object_key": key}, headers=h
    )
    assert created.status_code == 201, created.text
    async with SessionLocal() as session, session.begin():  # the job, run directly
        await set_tenant(session, tenant_id)
        await service.import_sales(session, {"import_id": created.json()["id"]})
    return (await client.get(f"/v1/imports/{created.json()['id']}", headers=h)).json()


async def orders(client: AsyncClient, h: dict[str, str]) -> list[Any]:
    window = {"start": "2026-10-20T00:00:00Z", "end": "2026-10-22T00:00:00Z"}
    listed = (await client.get("/v1/orders", params=window, headers=h)).json()["items"]
    return [(await client.get(f"/v1/orders/{o['id']}", headers=h)).json() for o in listed]


async def test_import_is_idempotent_and_versions_changed_orders(
    client: AsyncClient, restaurant: tuple[UUID, dict[str, str]], files: dict[str, bytes]
) -> None:
    _, h = restaurant
    butter = (
        await client.post(
            "/v1/menu-items", json={"name": "butter chicken", "price_cents": 1799}, headers=h
        )
    ).json()["id"]

    first = await run_import(client, restaurant, files, EXPORT)
    assert (first["status"], first["orders_new"], first["duplicates"]) == ("imported", 2, 0)
    [_, early] = await orders(client, h)  # newest first
    assert (early["external_id"], early["total_cents"]) == ("1001", 4795 + 315 + 600)
    # Sold items map to menu items by name (case-insensitive); unknown names stay unmapped.
    assert [(i["name"], i["menu_item_id"]) for i in early["items"]] == [
        ("Butter Chicken", butter),
        ("Garlic Naan", None),
    ]

    # The same export imported again (the owner clicked twice): nothing changes.
    again = await run_import(client, restaurant, files, EXPORT)
    assert (again["orders_new"], again["orders_updated"], again["duplicates"]) == (0, 0, 2)
    assert len(await orders(client, h)) == 2

    # A later export where order 1001's tip was corrected: one new version, one duplicate.
    fixed = await run_import(client, restaurant, files, EXPORT.replace("$6.00", "$8.00"))
    assert (fixed["orders_new"], fixed["orders_updated"], fixed["duplicates"]) == (0, 1, 1)
    [_, corrected] = await orders(client, h)
    assert (corrected["id"], corrected["tip_cents"]) == (early["id"], 800)  # same order, new data


async def test_projection_never_moves_backwards_and_replay_rebuilds(
    client: AsyncClient, restaurant: tuple[UUID, dict[str, str]], files: dict[str, bytes]
) -> None:
    tenant_id, h = restaurant
    await run_import(client, restaurant, files, EXPORT)
    await run_import(client, restaurant, files, EXPORT.replace("$6.00", "$8.00"))
    before = await orders(client, h)

    async with SessionLocal() as session, session.begin():
        await set_tenant(session, tenant_id)
        oldest = (
            await session.execute(
                text(
                    "SELECT id, payload FROM order_events"
                    " WHERE external_id = '1001' ORDER BY id LIMIT 1"
                )
            )
        ).one()
        # Applying the older version again (a delayed or re-run job) is refused.
        assert (
            await service.project(session, "dineos", dict(oldest.payload), oldest.id, {}) == "stale"
        )

    # Garlic Naan gets added to the menu later; replay re-maps old sales to it.
    naan = (
        await client.post(
            "/v1/menu-items", json={"name": "Garlic Naan", "price_cents": 399}, headers=h
        )
    ).json()["id"]
    async with SessionLocal() as session, session.begin():
        await set_tenant(session, tenant_id)
        await service.replay_orders(session, {})
    after = await orders(client, h)
    assert [o["id"] for o in after] == [o["id"] for o in before]  # ids stable across replay
    assert after[1]["tip_cents"] == 800  # rebuilt from the latest version
    assert after[1]["items"][1]["menu_item_id"] == naan


async def test_bad_files_and_foreign_keys_are_rejected(
    client: AsyncClient, restaurant: tuple[UUID, dict[str, str]], files: dict[str, bytes]
) -> None:
    _, h = restaurant
    failed = await run_import(client, restaurant, files, "order_id,item\n1,Dal\n")
    assert failed["status"] == "failed"
    assert failed["error"].startswith("missing columns:")

    stolen = {"source": "dineos", "object_key": "someone-else/imports/x.csv"}
    assert (await client.post("/v1/imports", json=stolen, headers=h)).status_code == 422
    key = (await client.post("/v1/imports/upload-url", headers=h)).json()["object_key"]
    unknown = {"source": "toast", "object_key": key}
    assert (await client.post("/v1/imports", json=unknown, headers=h)).status_code == 422
