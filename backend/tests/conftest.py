import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.auth.tokens import issue_access
from app.config import MigrationSettings
from app.db import engine
from app.main import app

MakeTenant = Callable[[], Awaitable[UUID]]


def auth_headers(tenant_id: UUID, role: str = "owner") -> dict[str, str]:
    """Bearer header for a tenant. Access tokens are stateless, so no user row is needed."""
    return {"Authorization": f"Bearer {issue_access(uuid.uuid4(), tenant_id, role)}"}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def _dispose_pool() -> AsyncIterator[None]:
    """Each test runs on a new event loop; pooled asyncpg connections are bound to the old one.
    Requested by the DB fixtures below (not autouse, so pure sync tests need no event loop)."""
    yield
    await engine.dispose()


@pytest.fixture
async def client(_dispose_pool: None) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def make_tenant(_dispose_pool: None) -> AsyncIterator[MakeTenant]:
    """Create tenants as the owner role (the app role can't); delete them and their rows after."""
    owner = create_async_engine(MigrationSettings().migration_database_url)
    created: list[UUID] = []

    async def make() -> UUID:
        tenant_id = uuid.uuid4()
        async with owner.begin() as conn:
            await conn.execute(
                text("INSERT INTO tenants (id, name) VALUES (:id, 'test')"), {"id": tenant_id}
            )
        created.append(tenant_id)
        return tenant_id

    yield make
    async with owner.begin() as conn:
        # Children before parents (FK order).
        for table in (
            "jobs",
            "extraction_cache",
            "receipt_labels",
            "receipt_lines",
            "receipts",
            "menu_items",
            "recipe_lines",
            "recipes",
            "ingredient_prices",
            "ingredients",
            "suppliers",
            "refresh_tokens",
            "users",
        ):
            await conn.execute(
                text(f"DELETE FROM {table} WHERE tenant_id = ANY(:ids)"), {"ids": created}
            )
        await conn.execute(text("DELETE FROM tenants WHERE id = ANY(:ids)"), {"ids": created})
    await owner.dispose()
