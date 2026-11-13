from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud
from app.api import Problem
from app.inventory import service as inventory
from app.menu.costing import Line, RecipeCost, cost_drivers, cost_recipes, line_unit_cost
from app.menu.models import MenuItem, Recipe, RecipeLine
from app.money import cents, percent


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


async def _graph(session: AsyncSession) -> tuple[dict[UUID, Decimal], dict[UUID, list[Line]]]:
    """The tenant's whole recipe graph: yields and lines (2 queries)."""
    # ponytail: loads every recipe even for one; restrict to the subtree if menus get huge.
    yields = {rid: y for rid, y in await session.execute(select(Recipe.id, Recipe.yield_qty))}
    lines: dict[UUID, list[Line]] = defaultdict(list)
    rl = RecipeLine
    stmt = select(rl.recipe_id, rl.ingredient_id, rl.sub_recipe_id, rl.qty).order_by(rl.id)
    for recipe_id, ingredient_id, sub_recipe_id, qty in await session.execute(stmt):
        lines[recipe_id].append(Line(ingredient_id, sub_recipe_id, qty))
    return yields, lines


async def _cost_all(
    session: AsyncSession,
) -> tuple[dict[UUID, RecipeCost], dict[UUID, list[Line]], dict[UUID, Decimal]]:
    """Load the recipe graph and latest prices (3 queries), then cost it in memory."""
    yields, lines = await _graph(session)
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


async def menu_item_ids_by_name(session: AsyncSession, names: set[str]) -> dict[str, UUID]:
    """Map sold item names (as the POS prints them) to menu items, case-insensitively.
    Names without a match are simply absent: those sales stay unmapped until the owner
    adds or renames the menu item."""
    if not names:
        return {}
    lowered = {n.lower() for n in names}
    rows = await session.execute(
        select(MenuItem.name, MenuItem.id).where(func.lower(MenuItem.name).in_(lowered))
    )
    return {name.lower(): item_id for name, item_id in rows}


async def portion_costs(session: AsyncSession) -> dict[UUID, Decimal | None]:
    """Exact food cost (cents) of one sale of each menu item, at today's prices; None if
    unknown. The ledger snapshots this when it posts a sale, so later price changes never
    rewrite the cost of past sales."""
    costs, _, _ = await _cost_all(session)
    result: dict[UUID, Decimal | None] = {}
    for item in await session.scalars(select(MenuItem)):
        recipe = costs.get(item.recipe_id) if item.recipe_id else None
        per_unit = recipe.per_unit if recipe else None
        result[item.id] = None if per_unit is None else item.portion_qty * per_unit
    return result


async def menu_item_names(session: AsyncSession) -> dict[UUID, str]:
    return {
        item_id: name for item_id, name in await session.execute(select(MenuItem.id, MenuItem.name))
    }


def _change_pct(was: Decimal, now: Decimal) -> Decimal | None:
    """Percent change to one decimal; None from a free ingredient (no percentage of zero)."""
    return ((now - was) * 100 / was).quantize(Decimal("0.1")) if was else None


async def margin_watch(
    session: AsyncSession, since: datetime, days: int, units_sold: Mapping[UUID, Decimal]
) -> dict[str, Any]:
    """What ingredient price changes since `since` did to each dish: cost and food cost %
    then and now, which ingredients drove it, and what it costs per week at the pace the dish
    sold over those days. The recipes are today's in both columns, so the difference is prices
    alone. Dishes whose cost was unknown then or is unknown now are left out."""
    yields, lines = await _graph(session)
    before = await inventory.latest_unit_costs(session, as_of=since)
    after = await inventory.latest_unit_costs(session)
    was, now = cost_recipes(yields, lines, before), cost_recipes(yields, lines, after)
    drivers = cost_drivers(yields, lines, before, after)
    labels = await inventory.ingredient_labels(session)

    dishes = []
    affected: dict[UUID, int] = defaultdict(int)
    for item in await session.scalars(select(MenuItem).order_by(MenuItem.name)):
        moved = drivers.get(item.recipe_id) if item.recipe_id else None
        if not moved or item.recipe_id is None:
            continue
        per_before, per_after = was[item.recipe_id].per_unit, now[item.recipe_id].per_unit
        if per_before is None or per_after is None:
            continue
        cost_before, cost_after = item.portion_qty * per_before, item.portion_qty * per_after
        sold = units_sold.get(item.id, Decimal(0))
        for ingredient_id in moved:
            affected[ingredient_id] += 1
        dishes.append(
            {
                "menu_item_id": item.id,
                "name": item.name,
                "price_cents": item.price_cents,
                "cost_before_cents": cents(cost_before),
                "cost_after_cents": cents(cost_after),
                "food_cost_pct_before": percent(cost_before, item.price_cents),
                "food_cost_pct_after": percent(cost_after, item.price_cents),
                "units_sold": sold,
                # Exact change x plates sold, scaled to a week, rounded once.
                "weekly_impact_cents": cents((cost_after - cost_before) * sold * 7 / days),
                "drivers": sorted(
                    (
                        {
                            "ingredient_id": ingredient_id,
                            "name": labels[ingredient_id][0],
                            "delta_cents": cents(item.portion_qty * delta),
                        }
                        for ingredient_id, delta in moved.items()
                    ),
                    key=lambda d: -abs(d["delta_cents"] or 0),
                ),
            }
        )
    return {
        "days": days,
        "weekly_impact_cents": sum(d["weekly_impact_cents"] for d in dishes),
        "ingredients": sorted(
            (
                {
                    "ingredient_id": ingredient_id,
                    "name": labels[ingredient_id][0],
                    "base_unit": labels[ingredient_id][1],
                    # Per gram/ml prices are fractions of a cent, so keep 4 decimals.
                    "unit_cents_before": before[ingredient_id].quantize(Decimal("0.0001")),
                    "unit_cents_after": price.quantize(Decimal("0.0001")),
                    "change_pct": _change_pct(before[ingredient_id], price),
                    "dishes_affected": affected[ingredient_id],
                }
                for ingredient_id, price in after.items()
                if before.get(ingredient_id, price) != price
            ),
            key=lambda i: -abs(i["change_pct"] or 0),
        ),
        "dishes": sorted(dishes, key=lambda d: -d["weekly_impact_cents"]),
    }
