"""Profitability ledger: balanced postings, reversals for corrections, profit by channel/dish."""

import uuid
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import MigrationSettings
from app.db import SessionLocal, set_tenant
from app.ledger import service as ledger
from app.ledger.posting import Entry, allocate, reversal_entries, sale_entries
from app.menu import service as menu
from app.orders import service as orders
from tests.conftest import MakeTenant, auth_headers

pytestmark = pytest.mark.anyio
A, B = uuid.uuid4(), uuid.uuid4()


def test_dine_in_sale_balances() -> None:
    order = {
        "subtotal_cents": 5000,
        "tax_cents": 400,
        "tip_cents": 800,
        "total_cents": 6200,
        "items": [
            {"menu_item_id": A, "quantity": Decimal(2), "line_total_cents": 3000},
            {"menu_item_id": B, "quantity": Decimal(1), "line_total_cents": 2000},
        ],
    }
    entries, complete = sale_entries(order, 0, {A: Decimal(450), B: Decimal(500)})
    assert complete
    assert entries == [
        Entry("cash", 6200),
        Entry("tax_payable", -400),
        Entry("tips_payable", -800),
        Entry("revenue", -3000, A),
        Entry("food_cost", 900, A),
        Entry("inventory", -900, A),
        Entry("revenue", -2000, B),
        Entry("food_cost", 500, B),
        Entry("inventory", -500, B),
    ]
    assert sum(e.amount_cents for e in reversal_entries(entries)) == 0


def test_delivery_commission_and_unknown_cost() -> None:
    order = {
        "subtotal_cents": 1799,
        "tax_cents": 157,
        "tip_cents": 0,
        "total_cents": 1956,
        "items": [{"menu_item_id": None, "quantity": Decimal(1), "line_total_cents": 1799}],
    }
    entries, complete = sale_entries(order, 3000, {})  # 30% on food, not on tax
    assert not complete  # unmapped item: food cost unknown, flagged, never guessed as 0
    assert Entry("platform_commission", 540) in entries  # 1799 * 0.30 = 539.7
    assert Entry("cash", 1956 - 540) in entries


def test_allocate_adds_up_exactly() -> None:
    assert allocate(1000, [1, 1, 1]) == [334, 333, 333]
    assert sum(allocate(12000, [4795, 1799])) == 12000
    assert allocate(500, [0, 0]) == [0, 0]


async def test_database_refuses_unbalanced_or_edited_books(make_tenant: MakeTenant) -> None:
    tenant = await make_tenant()
    with pytest.raises(IntegrityError, match="unbalanced by 100 cents"):
        async with SessionLocal() as session, session.begin():
            await set_tenant(session, tenant)
            txn = await session.scalar(
                text(
                    "INSERT INTO ledger_transactions (kind, idempotency_key, business_date)"
                    " VALUES ('sale', 'manual', '2026-10-20') RETURNING id"
                )
            )
            await session.execute(
                text(
                    "INSERT INTO ledger_entries (transaction_id, account, amount_cents, channel)"
                    " VALUES (:t, 'cash', 100, 'dine_in')"
                ),
                {"t": txn},
            )
        # ^ the deferred trigger fires at COMMIT, when the transaction is known to be complete
    with pytest.raises(DBAPIError, match="permission denied"):
        async with SessionLocal() as session, session.begin():
            await set_tenant(session, tenant)
            await session.execute(text("UPDATE ledger_entries SET amount_cents = 1"))


def order_payload(
    external_id: str, channel: str, items: list[tuple[str, int, int]], tax: int, tip: int
) -> dict[str, Any]:
    return {
        "external_id": external_id,
        "channel": channel,
        "placed_at": "2026-10-20T22:45:00+00:00",  # 18:45 in New York, business day Oct 20
        "tax_cents": tax,
        "tip_cents": tip,
        "items": [
            {"name": n, "quantity": str(q), "unit_price_cents": t // q, "line_total_cents": t}
            for n, q, t in items
        ],
    }


async def test_profit_by_channel_and_dish_with_a_correction(
    client: AsyncClient, make_tenant: MakeTenant
) -> None:
    tenant = await make_tenant()
    owner = create_async_engine(MigrationSettings().migration_database_url)
    async with owner.begin() as conn:
        await conn.execute(
            text("UPDATE tenants SET timezone = 'America/New_York' WHERE id = :t"), {"t": tenant}
        )
    await owner.dispose()
    h = auth_headers(tenant)

    async def post(url: str, body: dict[str, Any], **headers: str) -> Any:
        resp = await client.post(url, json=body, headers={**h, **headers})
        assert resp.status_code < 300, resp.text
        return resp.json()

    # Butter Chicken costs 150c a plate: 250 g of chicken at 0.6 c/g.
    chicken = await post("/v1/ingredients", {"name": "Chicken", "base_unit": "g"})
    await post(
        f"/v1/ingredients/{chicken['id']}/prices", {"pack_qty": 10000, "pack_price_cents": 6000}
    )
    recipe = await post("/v1/recipes", {"name": "BC plate", "yield_qty": 1, "yield_unit": "each"})
    resp = await client.put(
        f"/v1/recipes/{recipe['id']}/lines",
        json={"lines": [{"ingredient_id": chicken["id"], "qty": "250"}]},
        headers={**h, "If-Match": '"1"'},
    )
    assert resp.status_code == 200
    await post(
        "/v1/menu-items", {"name": "Butter Chicken", "price_cents": 1799, "recipe_id": recipe["id"]}
    )
    assert (
        await client.put("/v1/channel-fees/UberEats", json={"commission_bps": 3000}, headers=h)
    ).status_code == 200
    # Labor on Oct 20: one 8 h shift at $15/h, 16:00-24:00 New York = 20:00Z-04:00Z.
    cook = await post("/v1/staff", {"name": "Raj", "hourly_rate_cents": 1500})
    await post(
        "/v1/shifts",
        {"staff_id": cook["id"], "starts_at": "2026-10-20T20:00Z", "ends_at": "2026-10-21T04:00Z"},
    )

    async def ingest_and_post(payload: dict[str, Any]) -> None:
        async with SessionLocal() as session, session.begin():
            await set_tenant(session, tenant)
            names = {i["name"] for i in payload["items"]}
            ids = await menu.menu_item_ids_by_name(session, names)
            await orders.ingest(session, "dineos", payload, None, ids)
            order_id = await session.scalar(
                text("SELECT id FROM orders WHERE external_id = :e"), {"e": payload["external_id"]}
            )
            await ledger.post_order(session, {"order_id": str(order_id)})  # the outboxed job
            await ledger.post_order(session, {"order_id": str(order_id)})  # ...run twice

    await ingest_and_post(
        order_payload(
            "1001", "dine_in", [("Butter Chicken", 2, 3598), ("Garlic Naan", 3, 1197)], 315, 600
        )
    )
    await ingest_and_post(order_payload("1002", "ubereats", [("Butter Chicken", 1, 1799)], 157, 0))
    # The export is corrected later: order 1002 got a $3 tip. Reverse + repost, never edit.
    await ingest_and_post(
        order_payload("1002", "ubereats", [("Butter Chicken", 1, 1799)], 157, 300)
    )

    report = (
        await client.get(
            "/v1/reports/profit", params={"from": "2026-10-20", "to": "2026-10-20"}, headers=h
        )
    ).json()
    assert report["labor_cents"] == 12000
    assert report["sales_with_unknown_food_cost"] == 1  # 1001's naan isn't on the menu yet
    # 12000 labor split by revenue 4795 : 1799 -> 8726.1 : 3273.9 -> 8726 + 3274.
    assert report["channels"] == [
        {
            "channel": "dine_in",
            "revenue_cents": 4795,
            "commission_cents": 0,
            "food_cost_cents": 300,
            "gross_profit_cents": 4495,
            "labor_cents": 8726,
            "profit_cents": -4231,
        },
        {
            "channel": "ubereats",
            "revenue_cents": 1799,
            "commission_cents": 540,
            "food_cost_cents": 150,
            "gross_profit_cents": 1109,
            "labor_cents": 3274,
            "profit_cents": -2165,
        },
    ]
    assert [(d["name"], d["revenue_cents"], d["food_cost_cents"]) for d in report["dishes"]] == [
        ("Butter Chicken", 5397, 450),
        ("Unmapped items", 1197, 0),
    ]

    async with SessionLocal() as session, session.begin():
        await set_tenant(session, tenant)
        kinds = (
            (
                await session.execute(
                    text(
                        "SELECT t.kind FROM ledger_transactions t"
                        " JOIN orders o ON o.id = t.order_id"
                        " WHERE o.external_id = '1002' ORDER BY t.id"
                    )
                )
            )
            .scalars()
            .all()
        )
        tips = await session.scalar(
            text(
                "SELECT sum(e.amount_cents) FROM ledger_entries e"
                " JOIN ledger_transactions t ON t.id = e.transaction_id"
                " JOIN orders o ON o.id = t.order_id"
                " WHERE o.external_id = '1002' AND e.account = 'tips_payable'"
            )
        )
    assert kinds == ["sale", "reversal", "sale"]  # each version posted once, despite double runs
    assert tips == -300  # the books net to the latest version
