"""Sub-recipe cycles are rejected by a DB trigger, including under concurrent edits."""

import asyncio
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal, set_tenant
from tests.conftest import MakeTenant

pytestmark = pytest.mark.anyio


@pytest.fixture
async def tenant(make_tenant: MakeTenant) -> dict[str, str]:
    return {"X-Tenant-Id": str(await make_tenant())}


async def recipe(client: AsyncClient, name: str, h: dict[str, str]) -> str:
    body = {"name": name, "yield_qty": 1000, "yield_unit": "g"}
    resp = await client.post("/v1/recipes", json=body, headers=h)
    assert resp.status_code == 201
    rid: str = resp.json()["id"]
    return rid


async def put_subs(client: AsyncClient, rid: str, subs: list[str], h: dict[str, str]) -> Any:
    """Set a recipe's lines to the given sub-recipes. Each recipe is edited once, so If-Match 1."""
    lines = [{"sub_recipe_id": s, "qty": "100"} for s in subs]
    return await client.put(
        f"/v1/recipes/{rid}/lines", json={"lines": lines}, headers={**h, "If-Match": '"1"'}
    )


async def test_recipe_cannot_use_itself(client: AsyncClient, tenant: dict[str, str]) -> None:
    a = await recipe(client, "A", tenant)
    resp = await put_subs(client, a, [a], tenant)
    assert resp.status_code == 409
    assert "can't use itself" in resp.json()["detail"]


async def test_indirect_cycle_rejected(client: AsyncClient, tenant: dict[str, str]) -> None:
    a, b, c = [await recipe(client, n, tenant) for n in ("A", "B", "C")]
    assert (await put_subs(client, a, [b], tenant)).status_code == 200
    assert (await put_subs(client, b, [c], tenant)).status_code == 200
    assert (await put_subs(client, c, [a], tenant)).status_code == 409  # C -> A closes A->B->C->A


async def test_shared_sub_recipe_is_not_a_cycle(
    client: AsyncClient, tenant: dict[str, str]
) -> None:
    # Diamond: dish uses two gravies that both use the same base paste. Reached twice, no loop.
    dish, gravy1, gravy2, paste = [await recipe(client, n, tenant) for n in "WXYZ"]
    assert (await put_subs(client, gravy1, [paste], tenant)).status_code == 200
    assert (await put_subs(client, gravy2, [paste], tenant)).status_code == 200
    assert (await put_subs(client, dish, [gravy1, gravy2], tenant)).status_code == 200


async def test_concurrent_edits_cannot_both_close_a_cycle(
    client: AsyncClient, tenant: dict[str, str]
) -> None:
    """Tx1 adds A -> B and stays open. Tx2 adds B -> A: without the lock it wouldn't see A -> B
    and both would commit. With it, Tx2 waits for Tx1's commit, then sees the edge and fails."""
    a, b = await recipe(client, "A", tenant), await recipe(client, "B", tenant)
    tenant_id = UUID(tenant["X-Tenant-Id"])
    add_line = text("INSERT INTO recipe_lines (recipe_id, sub_recipe_id, qty) VALUES (:r, :s, 1)")

    async with SessionLocal() as tx1, SessionLocal() as tx2:
        # Connect both first, so "Tx2 not done" below means blocked, not still connecting.
        for tx in (tx1, tx2):
            await tx.begin()
            await set_tenant(tx, tenant_id)

        await tx1.execute(add_line, {"r": a, "s": b})
        task = asyncio.create_task(tx2.execute(add_line, {"r": b, "s": a}))
        await asyncio.sleep(0.5)
        assert not task.done(), "Tx2 should be blocked on the per-tenant advisory lock"
        await tx1.commit()

        with pytest.raises(IntegrityError, match="would use itself"):
            await task
