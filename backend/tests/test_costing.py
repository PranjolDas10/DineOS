"""Food cost: the pure costing walk (no DB) and the API end to end, against the mock menu."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from httpx import AsyncClient

from app.menu.costing import Line, cents, cost_recipes, percent
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


async def test_unknown_recipe_cost_is_404(client: AsyncClient, make_tenant: MakeTenant) -> None:
    headers = auth_headers(await make_tenant())
    resp = await client.get(f"/v1/recipes/{UUID(int=0)}/cost", headers=headers)
    assert resp.status_code == 404
