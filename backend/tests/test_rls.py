"""Tenant isolation is enforced by Postgres (RLS + composite FKs + grants), not by app code.
Tenants are created as the owner role; everything else runs as the API's dineos_app role."""

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.db import SessionLocal, set_tenant
from tests.conftest import MakeTenant

pytestmark = pytest.mark.anyio


async def as_app(tenant_id: UUID | None, sql: str, **params: object) -> list[Any]:
    """Run one row-returning statement as dineos_app in its own transaction, scoped to tenant_id."""
    async with SessionLocal() as session, session.begin():
        if tenant_id:
            await set_tenant(session, tenant_id)
        result = await session.execute(text(sql), params)
        return list(result.scalars().all())


@pytest.fixture
async def tenants(make_tenant: MakeTenant) -> tuple[UUID, UUID, UUID]:
    """Tenants A and B with one supplier each. Returns (a, b, b's supplier id)."""
    a, b = await make_tenant(), await make_tenant()
    await as_app(a, "INSERT INTO suppliers (name) VALUES ('Sysco') RETURNING id")
    [b_supplier] = await as_app(
        b, "INSERT INTO suppliers (name) VALUES ('Restaurant Depot') RETURNING id"
    )
    return a, b, b_supplier


async def test_reads_only_own_tenant(tenants: tuple[UUID, UUID, UUID]) -> None:
    a, _, _ = tenants
    assert await as_app(a, "SELECT name FROM suppliers") == ["Sysco"]


async def test_no_tenant_set_sees_nothing(tenants: tuple[UUID, UUID, UUID]) -> None:
    assert await as_app(None, "SELECT count(*) FROM suppliers") == [0]
    assert await as_app(None, "SELECT count(*) FROM tenants") == [0]
    assert await as_app(None, "SELECT count(*) FROM users") == [0]


async def test_cannot_write_into_other_tenant(tenants: tuple[UUID, UUID, UUID]) -> None:
    a, b, _ = tenants
    with pytest.raises(DBAPIError, match="row-level security"):
        await as_app(
            a, "INSERT INTO suppliers (tenant_id, name) VALUES (:b, 'x') RETURNING id", b=b
        )


async def test_cannot_reference_other_tenants_row(tenants: tuple[UUID, UUID, UUID]) -> None:
    a, _, b_supplier = tenants
    with pytest.raises(IntegrityError, match="foreign key"):
        await as_app(
            a,
            "INSERT INTO ingredients (name, base_unit, default_supplier_id)"
            " VALUES ('Onion', 'g', :s) RETURNING id",
            s=b_supplier,
        )


async def test_prices_are_append_only(tenants: tuple[UUID, UUID, UUID]) -> None:
    a, _, _ = tenants
    with pytest.raises(DBAPIError, match="permission denied"):
        await as_app(a, "UPDATE ingredient_prices SET pack_price_cents = 0 RETURNING id")
