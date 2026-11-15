"""Food cost: the pure costing walk (no DB) and the API end to end, against the mock menu."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import MigrationSettings
from app.db import SessionLocal, set_tenant
from app.menu.costing import Line, cost_drivers, cost_recipes, ingredient_quantities
from app.money import cents, percent
from app.orders import service as orders
from tests import mock_menu
from tests.conftest import MakeTenant, auth_headers

pytestmark = pytest.mark.anyio


def test_cost_recipes_pure() -> None:
    ids = {name: uuid.uuid4() for name in [*mock_menu.INGREDIENTS, *mock_menu.RECIPES]}
    unit_costs = {
        ids[name]: Decimal(cents) / pack_qty
        for name, (_, pack_qty, cents) in mock_menu.INGREDIENTS.items()
        if pack_qty is not None and cents is not None
    }
    yields = {ids[name]: Decimal(y) for name, (y, _, _) in mock_menu.RECIPES.items()}
    lines = {
        ids[name]: [
            Line(
                ingredient_id=ids[t] if t in mock_menu.INGREDIENTS else None,
                sub_recipe_id=ids[t] if t in mock_menu.RECIPES else None,
                qty=Decimal(q),
            )
            for t, q in recipe_lines
        ]
        for name, (_, _, recipe_lines) in mock_menu.RECIPES.items()
    }

    costs = cost_recipes(yields, lines, unit_costs)

    assert {name: cents(costs[ids[name]].total) for name in mock_menu.RECIPES} == (
        mock_menu.EXPECTED_RECIPE_TOTALS
    )
    # Unknowns propagate up with the reason, so the owner knows what to fix.
    assert costs[ids["Veg thali"]].unpriced == {ids["Saffron"]}
    assert costs[ids["Mango kulfi"]].empty == {ids["Mango kulfi"]}

    # Flattening is the same walk seen from the other side: pricing a recipe's raw
    # ingredients must give its cost, through shared and nested sub-recipes alike.
    flat = ingredient_quantities(yields, lines)
    paste, gravy = ids["Onion masala paste"], ids["Makhani gravy"]
    # 1000 g of paste holds 1200 g onion; a 5000 g gravy batch uses 1000 g of paste.
    assert flat[paste][ids["Onion"]] == Decimal("1.2")
    assert flat[gravy][ids["Onion"]] == Decimal("0.24")
    for recipe_id, cost in costs.items():
        if cost.per_unit is not None:
            priced = sum((q * unit_costs[i] for i, q in flat[recipe_id].items()), Decimal(0))
            assert abs(priced - cost.per_unit) < Decimal("1e-18")


def test_rounding_is_half_even_and_once() -> None:
    assert cents(Decimal("2.5")) == 2
    assert cents(Decimal("3.5")) == 4
    assert cents(None) is None
    assert percent(Decimal(1), 0) is None  # free item: no percentage, not a crash


@pytest.fixture
async def menu(
    client: AsyncClient, make_tenant: MakeTenant
) -> tuple[dict[str, str], dict[str, str]]:
    headers = auth_headers(await make_tenant())
    return headers, await mock_menu.load(client, headers)


async def test_food_cost_report(
    client: AsyncClient, menu: tuple[dict[str, str], dict[str, str]]
) -> None:
    headers, ids = menu
    resp = await client.get("/v1/reports/food-cost", headers=headers)
    assert resp.status_code == 200
    items = {i["name"]: i for i in resp.json()["items"]}

    got = {n: (i["cost_cents"], i["margin_cents"], i["food_cost_pct"]) for n, i in items.items()}
    assert got == mock_menu.EXPECTED_MENU
    assert items["Veg Thali"]["unpriced_ingredient_ids"] == [ids["Saffron"]]
    assert items["Mango Kulfi"]["empty_recipe_ids"] == [ids["Mango kulfi"]]
    assert items["Mango Lassi"]["recipe_id"] is None


async def test_recipe_cost_breakdown(
    client: AsyncClient, menu: tuple[dict[str, str], dict[str, str]]
) -> None:
    headers, ids = menu
    resp = await client.get(f"/v1/recipes/{ids['Makhani gravy']}/cost", headers=headers)
    body = resp.json()
    assert body["total_cents"] == 1200
    assert body["per_unit_cents"] == "0.2400"
    assert [line["cost_cents"] for line in body["lines"]] == [280, 450, 200, 250, 20]


async def test_latest_price_is_by_observed_at(
    client: AsyncClient, menu: tuple[dict[str, str], dict[str, str]]
) -> None:
    headers, ids = menu
    prices = f"/v1/ingredients/{ids['Onion']}/prices"
    paste_cost = f"/v1/recipes/{ids['Onion masala paste']}/cost"
    month_ago = (datetime.now(UTC) - timedelta(days=30)).isoformat()

    # An old receipt entered today must not replace the current price.
    old = {"pack_qty": 20000, "pack_price_cents": 5000, "observed_at": month_ago}
    await client.post(prices, json=old, headers=headers)
    assert (await client.get(paste_cost, headers=headers)).json()["total_cents"] == 280

    # A newer price does: onion 0.10 -> 0.20 c/g adds 1200 g * 0.10 = 120 c to the paste.
    await client.post(prices, json={"pack_qty": 20000, "pack_price_cents": 4000}, headers=headers)
    assert (await client.get(paste_cost, headers=headers)).json()["total_cents"] == 400


async def test_dish_cost_flattens_a_plate_to_raw_ingredients(
    client: AsyncClient, menu: tuple[dict[str, str], dict[str, str]]
) -> None:
    headers, ids = menu

    async def dish(name: str) -> Any:
        return (await client.get(f"/v1/menu-items/{ids[name]}/cost", headers=headers)).json()

    body = await dish("Butter Chicken")
    assert (body["cost_cents"], body["margin_cents"], body["food_cost_pct"]) == (147, 1652, "8.2")
    rows = {(r["name"], r["via"]): r for r in body["ingredients"]}
    # 350 g plate of a 6000 g batch holding 3000 g chicken: 175 g x 0.60 = 105; 105/147.23 = 71.3%
    chicken = rows["Chicken thigh", None]
    assert (chicken["qty"], chicken["cost_cents"], chicken["share_pct"]) == ("175.00", 105, "71.3")
    assert body["ingredients"][0] == chicken  # most expensive first
    # Tomato reaches the plate twice inside the gravy (directly and through the paste):
    # 145.83 g gravy x (3000 + 1000 x 0.4) / 5000 = 99.17 g x 0.15 = 14.9
    tomato = rows["Tomato puree", "Makhani gravy"]
    assert (tomato["qty"], tomato["cost_cents"]) == ("99.17", 15)
    # The same ingredient is listed per route: butter directly, and butter in the gravy.
    assert rows["Butter", None]["cost_cents"] == 2
    assert ("Butter", "Makhani gravy") in rows
    # Every route is accounted for: the shares cover the whole plate.
    shares = sum((Decimal(r["share_pct"]) for r in body["ingredients"]), Decimal(0))
    assert abs(shares - 100) <= Decimal("0.5")

    thali = await dish("Veg Thali")
    assert thali["cost_cents"] is None
    saffron = thali["ingredients"][0]  # unpriced first: the thing to fix
    assert (saffron["name"], saffron["via"], saffron["cost_cents"]) == (
        "Saffron",
        "Saffron rice",
        None,
    )
    assert all(r["share_pct"] is None for r in thali["ingredients"])

    kulfi = await dish("Mango Kulfi")
    assert (kulfi["empty_recipes"], kulfi["ingredients"]) == (["Mango kulfi"], [])
    lassi = await dish("Mango Lassi")
    assert (lassi["recipe_name"], lassi["cost_cents"], lassi["ingredients"]) == (None, None, [])
    missing = await client.get(f"/v1/menu-items/{UUID(int=0)}/cost", headers=headers)
    assert missing.status_code == 404


async def test_unknown_recipe_cost_is_404(client: AsyncClient, make_tenant: MakeTenant) -> None:
    headers = auth_headers(await make_tenant())
    resp = await client.get(f"/v1/recipes/{UUID(int=0)}/cost", headers=headers)
    assert resp.status_code == 404


def test_cost_drivers_split_a_move_exactly() -> None:
    """Cost is linear in prices, so per-ingredient shares add up to the whole change, even
    through a shared sub-recipe, and an untouched recipe has no drivers."""
    onion, butter, salt = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    paste, curry, rice = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    yields = {paste: Decimal(1000), curry: Decimal(4), rice: Decimal(1)}
    lines = {
        paste: [Line(onion, None, Decimal(1200)), Line(butter, None, Decimal(50))],
        # The curry uses butter directly and again through the paste.
        curry: [Line(None, paste, Decimal(600)), Line(butter, None, Decimal(30))],
        rice: [Line(salt, None, Decimal(2))],
    }
    before = {onion: Decimal("0.10"), butter: Decimal("0.80"), salt: Decimal("0.05")}
    after = {**before, onion: Decimal("0.13"), butter: Decimal("1.00")}

    drivers = cost_drivers(yields, lines, before, after)

    was, now = cost_recipes(yields, lines, before), cost_recipes(yields, lines, after)
    for recipe in (paste, curry):
        change = now[recipe].per_unit - was[recipe].per_unit  # type: ignore[operator]
        assert sum(drivers[recipe].values()) == change
    # Butter in one curry portion: (600 g paste * 50/1000 + 30 g) / 4 = 15 g, at +0.20 c/g.
    assert drivers[curry][butter] == Decimal("3.00")
    assert rice not in drivers
    # A first-ever price is not a change.
    assert cost_drivers(yields, lines, {}, after) == {}


async def test_margin_watch_reports_what_a_price_rise_did(
    client: AsyncClient, make_tenant: MakeTenant
) -> None:
    tenant = await make_tenant()
    headers = auth_headers(tenant)
    ids = await mock_menu.load(client, headers)
    # The menu's prices become "40 days ago" (as the owner role: the app role can't edit prices).
    owner = create_async_engine(MigrationSettings().migration_database_url)
    async with owner.begin() as conn:
        await conn.execute(
            text(
                "UPDATE ingredient_prices SET observed_at = now() - interval '40 days'"
                " WHERE tenant_id = :t"
            ),
            {"t": tenant},
        )
    await owner.dispose()
    # Butter goes from 0.80 to 1.00 c/g today. 28 Butter Chickens sold in the last 28 days.
    await client.post(
        f"/v1/ingredients/{ids['Butter']}/prices",
        json={"pack_qty": 1000, "pack_price_cents": 1000},
        headers=headers,
    )
    async with SessionLocal() as session, session.begin():
        await set_tenant(session, tenant)
        menu_ids = await menu_service_ids(session)
        await orders.ingest(
            session,
            "dineos",
            {
                "external_id": "1",
                "channel": "dine_in",
                "placed_at": (datetime.now(UTC) - timedelta(days=3)).isoformat(),
                "tax_cents": 0,
                "tip_cents": 0,
                "items": [
                    {
                        "name": "Butter Chicken",
                        "quantity": "28",
                        "unit_price_cents": 1799,
                        "line_total_cents": 28 * 1799,
                    }
                ],
            },
            None,
            menu_ids,
        )

    report = (await client.get("/v1/reports/margin-watch", headers=headers)).json()

    assert [
        (i["name"], i["unit_cents_before"], i["unit_cents_after"], i["change_pct"])
        for i in report["ingredients"]
    ] == [("Butter", "0.8000", "1.0000", "25.0")]
    assert report["ingredients"][0]["dishes_affected"] == 2
    dishes = {d["name"]: d for d in report["dishes"]}
    assert set(dishes) == {"Butter Chicken", "Garlic Naan"}  # Chana Masala has no butter
    bc = dishes["Butter Chicken"]
    # A 6000 g batch holds 50 g butter + 2500 g gravy * 250/5000 = 175 g; a 350 g portion
    # holds 10.2083 g, so +0.20 c/g adds 2.0417 c: 147.233 -> 149.275.
    assert (bc["cost_before_cents"], bc["cost_after_cents"]) == (147, 149)
    assert (bc["food_cost_pct_before"], bc["food_cost_pct_after"]) == ("8.2", "8.3")
    assert bc["drivers"] == [{"ingredient_id": ids["Butter"], "name": "Butter", "delta_cents": 2}]
    # 2.0417 c * 28 plates * 7/28 days = 14.29 -> 14 c a week.
    assert (bc["units_sold"], bc["weekly_impact_cents"]) == ("28", 14)
    assert dishes["Garlic Naan"]["weekly_impact_cents"] == 0  # none sold
    assert report["weekly_impact_cents"] == 14


async def menu_service_ids(session: Any) -> dict[str, UUID]:
    from app.menu import service as menu

    return await menu.menu_item_ids_by_name(session, {"Butter Chicken"})


def test_menu_matrix_sorts_dishes_into_four_kinds() -> None:
    from app.menu.matrix import Dish, classify

    star, plow, puzzle, dog = (uuid.uuid4() for _ in range(4))
    matrix = classify(
        [
            Dish(star, Decimal(40), Decimal(1200)),
            Dish(plow, Decimal(50), Decimal(300)),
            Dish(puzzle, Decimal(5), Decimal(1500)),
            Dish(dog, Decimal(5), Decimal(200)),
        ]
    )
    assert matrix is not None
    # 100 plates over 4 dishes: an even share is 25, the bar is 70% of it.
    assert matrix.popularity_bar == Decimal("17.5")
    # (40*1200 + 50*300 + 5*1500 + 5*200) / 100 = 715 c per plate sold.
    assert matrix.margin_bar == Decimal(715)
    assert matrix.kinds == {star: "star", plow: "plowhorse", puzzle: "puzzle", dog: "dog"}
    assert classify([Dish(star, Decimal(0), Decimal(1200))]) is None  # nothing sold


async def test_menu_matrix_report_leaves_uncosted_dishes_unplaced(
    client: AsyncClient, menu: tuple[dict[str, str], dict[str, str]]
) -> None:
    headers, _ = menu
    report = (await client.get("/v1/reports/menu-matrix", headers=headers)).json()
    # Nothing sold in this tenant: no bars, no kinds, but every dish is listed.
    assert (report["popularity_bar"], report["margin_bar_cents"]) == (None, None)
    kinds = {d["name"]: (d["margin_cents"], d["kind"]) for d in report["dishes"]}
    assert kinds["Butter Chicken"] == (1652, None)
    assert kinds["Mango Lassi"] == (None, None)
