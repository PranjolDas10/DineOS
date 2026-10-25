"""Public interface of the inventory module. Other modules import only this file."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import insert, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.inventory.models import IngredientPrice


async def latest_unit_costs(session: AsyncSession) -> dict[UUID, Decimal]:
    """Cents per base unit for every priced ingredient, from its latest price by observed_at
    (not insertion order: a backdated receipt entered today must not become "current")."""
    p = IngredientPrice
    stmt = (
        select(p.ingredient_id, p.pack_price_cents, p.pack_qty)
        .ext(distinct_on(p.ingredient_id))  # first row per ingredient, in ORDER BY order
        .order_by(p.ingredient_id, p.observed_at.desc(), p.id.desc())
    )
    return {ing: Decimal(cents) / qty for ing, cents, qty in await session.execute(stmt)}


async def record_price(
    session: AsyncSession,
    ingredient_id: UUID,
    supplier_id: UUID | None,
    pack_qty: Decimal,
    pack_price_cents: int,
    observed_at: datetime,
) -> None:
    """Append a price observation (e.g. from a confirmed receipt). The composite FKs reject
    an ingredient or supplier from another tenant."""
    await session.execute(
        insert(IngredientPrice).values(
            ingredient_id=ingredient_id,
            supplier_id=supplier_id,
            pack_qty=pack_qty,
            pack_price_cents=pack_price_cents,
            observed_at=observed_at,
        )
    )
