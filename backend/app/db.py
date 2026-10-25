from collections.abc import AsyncIterator
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def set_tenant(session: AsyncSession, tenant_id: UUID) -> None:
    """Scope RLS to one tenant for the current transaction only (is_local=true, like SET LOCAL),
    so the setting can't leak to the next request on a pooled connection."""
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
    )
