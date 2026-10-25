"""Inventory API contract: ETag/If-Match, idempotent create, cursor pages, problem+json."""

import uuid
from uuid import UUID

import pytest
from httpx import AsyncClient

from tests.conftest import MakeTenant, auth_headers

pytestmark = pytest.mark.anyio


@pytest.fixture
async def tenant(make_tenant: MakeTenant) -> dict[str, str]:
    return auth_headers(await make_tenant())


async def test_update_requires_current_etag(client: AsyncClient, tenant: dict[str, str]) -> None:
    created = await client.post("/v1/suppliers", json={"name": " Sysco "}, headers=tenant)
    assert created.status_code == 201
    assert created.headers["etag"] == '"1"'
    assert created.json()["name"] == "Sysco"
    url = f"/v1/suppliers/{created.json()['id']}"

    missing = await client.patch(url, json={"phone": "555"}, headers=tenant)
    assert missing.status_code == 428

    ok = await client.patch(url, json={"phone": "555"}, headers={**tenant, "If-Match": '"1"'})
    assert ok.status_code == 200
    assert ok.headers["etag"] == '"2"'
    assert ok.json()["phone"] == "555"

    stale = await client.patch(url, json={"phone": "666"}, headers={**tenant, "If-Match": '"1"'})
    assert stale.status_code == 412
    assert stale.headers["content-type"] == "application/problem+json"
    assert (await client.get(url, headers=tenant)).json()["phone"] == "555"


async def test_create_retry_with_same_id_is_idempotent(
    client: AsyncClient, tenant: dict[str, str]
) -> None:
    body = {"id": str(uuid.uuid4()), "name": "Restaurant Depot"}
    first = await client.post("/v1/suppliers", json=body, headers=tenant)
    retry = await client.post("/v1/suppliers", json=body, headers=tenant)
    assert first.status_code == retry.status_code == 201
    assert first.json() == retry.json()
    assert len((await client.get("/v1/suppliers", headers=tenant)).json()["items"]) == 1


async def test_duplicate_name_is_409(client: AsyncClient, tenant: dict[str, str]) -> None:
    await client.post("/v1/suppliers", json={"name": "Sysco"}, headers=tenant)
    dup = await client.post("/v1/suppliers", json={"name": "sysco"}, headers=tenant)
    assert dup.status_code == 409


async def test_cursor_pagination(client: AsyncClient, tenant: dict[str, str]) -> None:
    for name in ("A", "B", "C"):
        await client.post("/v1/suppliers", json={"name": name}, headers=tenant)
    first = (await client.get("/v1/suppliers?limit=2", headers=tenant)).json()
    assert [s["name"] for s in first["items"]] == ["A", "B"]
    cursor = first["next_cursor"]
    second = (await client.get(f"/v1/suppliers?limit=2&cursor={cursor}", headers=tenant)).json()
    assert [s["name"] for s in second["items"]] == ["C"]
    assert second["next_cursor"] is None


async def test_prices(client: AsyncClient, tenant: dict[str, str]) -> None:
    onion = await client.post(
        "/v1/ingredients", json={"name": "Onion", "base_unit": "g"}, headers=tenant
    )
    url = f"/v1/ingredients/{onion.json()['id']}/prices"
    # 50 lb sack in grams, $34.99.
    price = await client.post(
        url, json={"pack_qty": "22679.6", "pack_price_cents": 3499}, headers=tenant
    )
    assert price.status_code == 201
    assert (await client.get(url, headers=tenant)).json()["items"][0]["pack_qty"] == "22679.6"

    negative = await client.post(url, json={"pack_qty": 1, "pack_price_cents": -1}, headers=tenant)
    assert negative.status_code == 422
    assert negative.headers["content-type"] == "application/problem+json"

    unknown = f"/v1/ingredients/{uuid.uuid4()}/prices"
    resp = await client.post(unknown, json={"pack_qty": 1, "pack_price_cents": 1}, headers=tenant)
    assert resp.status_code == 404


async def test_other_tenant_gets_404(client: AsyncClient, make_tenant: MakeTenant) -> None:
    a: dict[str, str] = auth_headers(await make_tenant())
    b: dict[str, str] = auth_headers(await make_tenant())
    supplier_id: UUID = (await client.post("/v1/suppliers", json={"name": "S"}, headers=a)).json()[
        "id"
    ]
    assert (await client.get(f"/v1/suppliers/{supplier_id}", headers=b)).status_code == 404
