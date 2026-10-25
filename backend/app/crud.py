"""Generic data access for tenant-scoped tables. RLS already filters every query to the tenant."""

from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import Problem
from app.db import Entity, Versioned


async def create[M: Entity](session: AsyncSession, model: type[M], values: dict[str, Any]) -> M:
    """Insert. A retry with the same client-generated id returns the existing row (idempotent)."""
    stmt = (
        insert(model)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["id"])
        .returning(model)
    )
    row = (await session.scalars(stmt)).one_or_none()
    if row is not None:
        return row
    # The id exists. Not visible under RLS means another tenant owns it.
    existing = await session.get(model, values["id"])
    if existing is None:
        raise Problem(409, "This id is already in use.")
    return existing


async def get_or_404[M: Entity](session: AsyncSession, model: type[M], id: UUID) -> M:
    row = await session.get(model, id)
    if row is None:
        raise Problem(404, f"{model.__name__} not found.")
    return row


async def page[M: Entity](
    session: AsyncSession,
    model: type[M],
    cursor: UUID | None,
    limit: int,
    *where: ColumnElement[bool],
) -> dict[str, Any]:
    """Keyset pagination on id. UUIDv7 ids are time-ordered, so this is creation order."""
    # ponytail: id order only; add a (name, id) cursor if the UI needs server-side A-Z paging.
    stmt = select(model).where(*where).order_by(model.id).limit(limit + 1)
    if cursor is not None:
        stmt = stmt.where(model.id > cursor)
    rows = list(await session.scalars(stmt))
    has_more = len(rows) > limit
    return {"items": rows[:limit], "next_cursor": rows[limit - 1].id if has_more else None}


async def update_versioned[M: Versioned](
    session: AsyncSession, model: type[M], id: UUID, version: int, values: dict[str, Any]
) -> M:
    """Optimistic locking in one statement: zero rows updated means stale version (or missing)."""
    stmt = (
        update(model)
        .where(model.id == id, model.version == version)
        .values(**values, version=model.version + 1, updated_at=func.now())
        .returning(model)
    )
    row = (await session.scalars(stmt)).one_or_none()
    if row is None:
        await get_or_404(session, model, id)
        raise Problem(412, "This record changed since you read it. Refetch and retry.")
    return row
