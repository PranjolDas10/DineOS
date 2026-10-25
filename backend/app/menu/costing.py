"""Food cost of recipes and menu items. Pure functions: no DB, no I/O.

All amounts are exact Decimal cents. Round only when presenting (see app.money.cents)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True)
class Line:
    ingredient_id: UUID | None
    sub_recipe_id: UUID | None
    qty: Decimal  # ingredient base unit, or the sub-recipe's yield unit


@dataclass(frozen=True)
class RecipeCost:
    total: Decimal | None  # one full batch (yield_qty); None if anything below is unknown
    per_unit: Decimal | None  # per yield unit
    unpriced: frozenset[UUID]  # ingredients with no price, anywhere below this recipe
    empty: frozenset[UUID]  # recipes with no lines yet, anywhere below (or this one)


def cost_recipes(
    yields: Mapping[UUID, Decimal],
    lines: Mapping[UUID, Sequence[Line]],
    unit_costs: Mapping[UUID, Decimal],
) -> dict[UUID, RecipeCost]:
    """Cost every recipe. Memoized depth-first walk: each recipe is costed once, so the whole
    graph is O(recipes + lines) even when sub-recipes are shared. Assumes no cycles (the
    recipe_lines trigger guarantees it)."""
    memo: dict[UUID, RecipeCost] = {}

    def visit(recipe_id: UUID) -> RecipeCost:
        if recipe_id in memo:
            return memo[recipe_id]
        recipe_lines = lines.get(recipe_id, ())
        total = Decimal(0)
        unpriced: set[UUID] = set()
        empty: set[UUID] = set() if recipe_lines else {recipe_id}
        for line in recipe_lines:
            if line.sub_recipe_id is not None:
                sub = visit(line.sub_recipe_id)
                unpriced |= sub.unpriced
                empty |= sub.empty
            unit = line_unit_cost(line, unit_costs, memo)
            if unit is None:
                if line.ingredient_id is not None:
                    unpriced.add(line.ingredient_id)
                continue
            total += line.qty * unit
        known = not unpriced and not empty
        memo[recipe_id] = RecipeCost(
            total=total if known else None,
            per_unit=total / yields[recipe_id] if known else None,
            unpriced=frozenset(unpriced),
            empty=frozenset(empty),
        )
        return memo[recipe_id]

    for recipe_id in yields:
        visit(recipe_id)
    return memo


def line_unit_cost(
    line: Line, unit_costs: Mapping[UUID, Decimal], costs: Mapping[UUID, RecipeCost]
) -> Decimal | None:
    """Cents per unit of what the line uses, or None if unknown."""
    if line.ingredient_id is not None:
        return unit_costs.get(line.ingredient_id)
    assert line.sub_recipe_id is not None
    return costs[line.sub_recipe_id].per_unit
