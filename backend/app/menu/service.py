from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud
from app.menu.models import Recipe, RecipeLine


async def get_lines(session: AsyncSession, recipe_id: UUID) -> tuple[Recipe, Sequence[RecipeLine]]:
    recipe = await crud.get_or_404(session, Recipe, recipe_id)
    stmt = select(RecipeLine).where(RecipeLine.recipe_id == recipe_id).order_by(RecipeLine.id)
    return recipe, (await session.scalars(stmt)).all()


async def replace_lines(
    session: AsyncSession, recipe_id: UUID, version: int, lines: list[dict[str, Any]]
) -> tuple[Recipe, Sequence[RecipeLine]]:
    """Replace a recipe's lines as one unit. Bumping the recipe version first row-locks the recipe,
    so concurrent edits of the same recipe serialize and the loser gets 412."""
    recipe = await crud.update_versioned(session, Recipe, recipe_id, version, {})
    await session.execute(delete(RecipeLine).where(RecipeLine.recipe_id == recipe_id))
    if not lines:
        return recipe, []
    rows = [{**line, "recipe_id": recipe_id} for line in lines]
    return recipe, (await session.scalars(insert(RecipeLine).returning(RecipeLine), rows)).all()
