"""Tenant isolation is enforced by Postgres (RLS + composite FKs + grants), not by app code.
Setup runs as the owner role; every assertion runs as the API's dineos_app role."""

import uuid
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import MigrationSettings
from app.db import SessionLocal, set_tenant

pytestmark = pytest.mark.anyio


@pytest.fixture
async def tenants() -> AsyncIterator[tuple[UUID, UUID, UUID]]:
    """Tenants A and B with one supplier each. Yields (a, b, b's supplier id)."""
    owner = create_async_engine(MigrationSettings().migration_database_url)
    a, b, b_supplier = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    ids = {"a": a, "b": b}
    async with owner.begin() as conn:
        await conn.execute(text("INSERT INTO tenants (id, name) VALUES (:a, 'A'), (:b, 'B')"), ids)
        await conn.execute(
            text("INSERT INTO suppliers (tenant_id, name) VALUES (:a, 'Sysco')"), ids
        )
        await conn.execute(
            text("INSERT INTO suppliers (id, tenant_id, name) VALUES (:s, :b, 'Restaurant Depot')"),
            {**ids, "s": b_supplier},
        )
    yield a, b, b_supplier
    async with owner.begin() as conn:
        for table in ("ingredients", "suppliers"):
            await conn.execute(text(f"DELETE FROM {table} WHERE tenant_id IN (:a, :b)"), ids)
        await conn.execute(text("DELETE FROM tenants WHERE id IN (:a, :b)"), ids)
    await owner.dispose()


async def as_app(tenant_id: UUID | None, sql: str, **params: object) -> list[Any]:
    """Run one row-returning statement as dineos_app in its own transaction, scoped to tenant_id."""
    async with SessionLocal() as session, session.begin():
        if tenant_id:
            await set_tenant(session, tenant_id)
        result = await session.execute(text(sql), params)
        return list(result.scalars().all())


async def test_reads_only_own_tenant(tenants: tuple[UUID, UUID, UUID]) -> None:
    a, _, _ = tenants
    assert await as_app(a, "SELECT name FROM suppliers") == ["Sysco"]


async def test_no_tenant_set_sees_nothing(tenants: tuple[UUID, UUID, UUID]) -> None:
    assert await as_app(None, "SELECT count(*) FROM suppliers") == [0]
    assert await as_app(None, "SELECT count(*) FROM tenants") == [0]


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
