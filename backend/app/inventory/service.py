"""Public interface of the inventory module. Other modules import only this file."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import insert, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.inventory.models import Ingredient, IngredientPrice


async def latest_unit_costs(
    session: AsyncSession, as_of: datetime | None = None
) -> dict[UUID, Decimal]:
    """Cents per base unit for every priced ingredient, from its latest price by observed_at
    (not insertion order: a backdated receipt entered today must not become "current").
    With as_of, the price that was current at that moment: prices are append-only, so the
    past is a filter, not a second table."""
    p = IngredientPrice
    stmt = (
        select(p.ingredient_id, p.pack_price_cents, p.pack_qty)
        .ext(distinct_on(p.ingredient_id))  # first row per ingredient, in ORDER BY order
        .order_by(p.ingredient_id, p.observed_at.desc(), p.id.desc())
    )
    if as_of is not None:
        stmt = stmt.where(p.observed_at <= as_of)
    return {ing: Decimal(cents) / qty for ing, cents, qty in await session.execute(stmt)}


async def ingredient_labels(session: AsyncSession) -> dict[UUID, tuple[str, str]]:
    """Ingredient id -> (name, base unit), for reports that name ingredients."""
    rows = await session.execute(select(Ingredient.id, Ingredient.name, Ingredient.base_unit))
    return {ingredient_id: (name, unit) for ingredient_id, name, unit in rows}


async def record_price(
    session: AsyncSession,
    ingredient_id: UUID,
    supplier_id: UUID | None,
    pack_qty: Decimal,
    pack_price_cents: int,
    observed_at: datetime,
) -> Decimal | None:
    """Append a price observation (e.g. from a confirmed receipt). The composite FKs reject
    an ingredient or supplier from another tenant.

    Returns the unit cost this observation replaces as the current one, or None if there was
    no earlier price or a newer one already exists (a backdated receipt changes history, not
    today's cost, so there is nothing to tell the owner)."""
    p = IngredientPrice
    current = (
        await session.execute(
            select(p.pack_price_cents, p.pack_qty, p.observed_at)
            .where(p.ingredient_id == ingredient_id)
            .order_by(p.observed_at.desc(), p.id.desc())
            .limit(1)
        )
    ).one_or_none()
    await session.execute(
        insert(IngredientPrice).values(
            ingredient_id=ingredient_id,
            supplier_id=supplier_id,
            pack_qty=pack_qty,
            pack_price_cents=pack_price_cents,
            observed_at=observed_at,
        )
    )
    if current is None or current.observed_at > observed_at:
        return None
    return Decimal(current.pack_price_cents) / current.pack_qty
