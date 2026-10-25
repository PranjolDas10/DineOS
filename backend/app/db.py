from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, ClassVar
from uuid import UUID

from sqlalchemy import DateTime, FetchedValue, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    # All timestamps are timestamptz, so aware datetimes bind correctly.
    type_annotation_map: ClassVar[dict[Any, Any]] = {datetime: DateTime(timezone=True)}


class Entity(Base):
    """id is uuidv7() in the DB, or client-generated (offline clients). tenant_id is not mapped:
    the DB fills it from the session's tenant, so app code can't set it wrong."""

    __abstract__ = True
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=FetchedValue())


class Versioned(Entity):
    """Editable record with an optimistic-locking version (exposed as the ETag)."""

    __abstract__ = True
    version: Mapped[int]
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def set_tenant(session: AsyncSession, tenant_id: UUID) -> None:
    """Scope RLS to one tenant for the current transaction only (is_local=true, like SET LOCAL),
    so the setting can't leak to the next request on a pooled connection."""
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
    )
