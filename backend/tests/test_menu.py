"""Menu API: recipe lines as one versioned aggregate, sub-recipe lines, menu items."""

from typing import Any

import pytest
from httpx import AsyncClient

from tests.conftest import MakeTenant

pytestmark = pytest.mark.anyio


@pytest.fixture
async def tenant(make_tenant: MakeTenant) -> dict[str, str]:
    return {"X-Tenant-Id": str(await make_tenant())}


async def post(client: AsyncClient, url: str, body: dict[str, Any], h: dict[str, str]) -> Any:
    resp = await client.post(url, json=body, headers=h)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_replace_lines_with_ingredient_and_sub_recipe(
    client: AsyncClient, tenant: dict[str, str]
) -> None:
    onion = await post(client, "/v1/ingredients", {"name": "Onion", "base_unit": "g"}, tenant)
    gravy = await post(
        client,
        "/v1/recipes",
        {"name": "Makhani gravy", "yield_qty": 5000, "yield_unit": "g"},
        tenant,
    )
    dish = await post(
        client,
        "/v1/recipes",
        {"name": "Butter chicken", "yield_qty": 1, "yield_unit": "each"},
        tenant,
    )
    url = f"/v1/recipes/{dish['id']}/lines"
    lines = [
        {"ingredient_id": onion["id"], "qty": "50"},
        {"sub_recipe_id": gravy["id"], "qty": "200"},
    ]

    put = await client.put(url, json={"lines": lines}, headers={**tenant, "If-Match": '"1"'})
    assert put.status_code == 200, put.text
    assert put.headers["etag"] == '"2"'

    got = await client.get(url, headers=tenant)
    assert got.headers["etag"] == '"2"'
    assert [(x["ingredient_id"], x["sub_recipe_id"]) for x in got.json()["lines"]] == [
        (onion["id"], None),
        (None, gravy["id"]),
    ]

    # Replace, not append; and the old ETag is now stale.
    stale = await client.put(url, json={"lines": []}, headers={**tenant, "If-Match": '"1"'})
    assert stale.status_code == 412
    cleared = await client.put(url, json={"lines": []}, headers={**tenant, "If-Match": '"2"'})
    assert cleared.json() == {"lines": []}


async def test_line_needs_exactly_one_target(client: AsyncClient, tenant: dict[str, str]) -> None:
    dish = await post(
        client, "/v1/recipes", {"name": "Dal", "yield_qty": 1, "yield_unit": "each"}, tenant
    )
    url = f"/v1/recipes/{dish['id']}/lines"
    resp = await client.put(
        url, json={"lines": [{"qty": "1"}]}, headers={**tenant, "If-Match": '"1"'}
    )
    assert resp.status_code == 422
    # The failed PUT rolled back: version unchanged.
    assert (await client.get(url, headers=tenant)).headers["etag"] == '"1"'


async def test_line_cannot_use_other_tenants_ingredient(
    client: AsyncClient, make_tenant: MakeTenant
) -> None:
    a = {"X-Tenant-Id": str(await make_tenant())}
    b = {"X-Tenant-Id": str(await make_tenant())}
    onion_b = await post(client, "/v1/ingredients", {"name": "Onion", "base_unit": "g"}, b)
    dish_a = await post(
        client, "/v1/recipes", {"name": "Dal", "yield_qty": 1, "yield_unit": "each"}, a
    )
    resp = await client.put(
        f"/v1/recipes/{dish_a['id']}/lines",
        json={"lines": [{"ingredient_id": onion_b["id"], "qty": "1"}]},
        headers={**a, "If-Match": '"1"'},
    )
    assert resp.status_code == 422


async def test_menu_item_links_recipe_portion(client: AsyncClient, tenant: dict[str, str]) -> None:
    batch = await post(
        client,
        "/v1/recipes",
        {"name": "Chana masala", "yield_qty": 8000, "yield_unit": "g"},
        tenant,
    )
    item = await post(
        client,
        "/v1/menu-items",
        {
            "name": "Chana masala (lunch)",
            "price_cents": 1299,
            "recipe_id": batch["id"],
            "portion_qty": "300",
        },
        tenant,
    )
    assert item["portion_qty"] == "300"
    no_recipe = await post(
        client, "/v1/menu-items", {"name": "Mango lassi", "price_cents": 499}, tenant
    )
    assert no_recipe["recipe_id"] is None
    assert no_recipe["portion_qty"] == "1"
