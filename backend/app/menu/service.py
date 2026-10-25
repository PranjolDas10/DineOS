from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud
from app.api import Problem
from app.inventory import service as inventory
from app.menu.costing import Line, RecipeCost, cents, cost_recipes, line_unit_cost, percent
from app.menu.models import MenuItem, Recipe, RecipeLine


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


async def _cost_all(
    session: AsyncSession,
) -> tuple[dict[UUID, RecipeCost], dict[UUID, list[Line]], dict[UUID, Decimal]]:
    """Load the tenant's recipe graph and latest prices (3 queries), then cost it in memory."""
    # ponytail: loads every recipe even for one; restrict to the subtree if menus get huge.
    yields = {rid: y for rid, y in await session.execute(select(Recipe.id, Recipe.yield_qty))}
    lines: dict[UUID, list[Line]] = defaultdict(list)
    rl = RecipeLine
    stmt = select(rl.recipe_id, rl.ingredient_id, rl.sub_recipe_id, rl.qty).order_by(rl.id)
    for recipe_id, ingredient_id, sub_recipe_id, qty in await session.execute(stmt):
        lines[recipe_id].append(Line(ingredient_id, sub_recipe_id, qty))
    unit_costs = await inventory.latest_unit_costs(session)
    return cost_recipes(yields, lines, unit_costs), lines, unit_costs


async def recipe_cost(session: AsyncSession, recipe_id: UUID) -> dict[str, Any]:
    costs, lines, unit_costs = await _cost_all(session)
    if recipe_id not in costs:
        raise Problem(404, "Recipe not found.")
    breakdown = []
    for line in lines[recipe_id]:
        unit = line_unit_cost(line, unit_costs, costs)
        line_cost = None if unit is None else line.qty * unit
        breakdown.append({**vars(line), "cost_cents": cents(line_cost)})
    cost = costs[recipe_id]
    per_unit = cost.per_unit
    return {
        "recipe_id": recipe_id,
        "total_cents": cents(cost.total),
        # Per gram/ml costs are fractions of a cent, so keep 4 decimals here.
        "per_unit_cents": None if per_unit is None else per_unit.quantize(Decimal("0.0001")),
        "unpriced_ingredient_ids": sorted(cost.unpriced),
        "empty_recipe_ids": sorted(cost.empty),
        "lines": breakdown,
    }


async def food_cost_report(session: AsyncSession) -> list[dict[str, Any]]:
    """Every menu item with cost, margin and food cost %. Unknown cost stays null, never 0."""
    # ponytail: unpaginated; a menu is ~100 items. Cursor-paginate if that stops being true.
    costs, _, _ = await _cost_all(session)
    report = []
    for item in await session.scalars(select(MenuItem).order_by(MenuItem.name)):
        recipe = costs.get(item.recipe_id) if item.recipe_id else None
        per_unit = recipe.per_unit if recipe else None
        cost = None if per_unit is None else item.portion_qty * per_unit
        cost_cents = cents(cost)
        report.append(
            {
                "menu_item_id": item.id,
                "name": item.name,
                "recipe_id": item.recipe_id,
                "price_cents": item.price_cents,
                "cost_cents": cost_cents,
                # Rounded cost + margin always add up to the price the owner sees.
                "margin_cents": None if cost_cents is None else item.price_cents - cost_cents,
                "food_cost_pct": percent(cost, item.price_cents),
                "unpriced_ingredient_ids": sorted(recipe.unpriced) if recipe else [],
                "empty_recipe_ids": sorted(recipe.empty) if recipe else [],
            }
        )
    return report
