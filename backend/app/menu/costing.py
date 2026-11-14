"""Food cost of recipes and menu items. Pure functions: no DB, no I/O.

All amounts are exact Decimal cents. Round only when presenting (see app.money.cents)."""

from collections import defaultdict
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


def ingredient_quantities(
    yields: Mapping[UUID, Decimal], lines: Mapping[UUID, Sequence[Line]]
) -> dict[UUID, dict[UUID, Decimal]]:
    """Flatten every recipe to raw ingredients: recipe -> {ingredient -> quantity in ONE yield
    unit of that recipe}, with sub-recipes multiplied through. Answers "how much onion is in
    a gram of gravy", however deep the onion sits. Memoized like cost_recipes; assumes no
    cycles."""
    memo: dict[UUID, dict[UUID, Decimal]] = {}

    def visit(recipe_id: UUID) -> dict[UUID, Decimal]:
        if recipe_id in memo:
            return memo[recipe_id]
        batch: dict[UUID, Decimal] = defaultdict(Decimal)
        for line in lines.get(recipe_id, ()):
            if line.ingredient_id is not None:
                batch[line.ingredient_id] += line.qty
            else:
                assert line.sub_recipe_id is not None
                for ingredient_id, per_unit in visit(line.sub_recipe_id).items():
                    batch[ingredient_id] += line.qty * per_unit
        memo[recipe_id] = {i: qty / yields[recipe_id] for i, qty in batch.items()}
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


def cost_drivers(
    yields: Mapping[UUID, Decimal],
    lines: Mapping[UUID, Sequence[Line]],
    before: Mapping[UUID, Decimal],
    after: Mapping[UUID, Decimal],
) -> dict[UUID, dict[UUID, Decimal]]:
    """Which ingredient moved which recipe's cost, and by how much: recipe -> {ingredient ->
    change in cents per yield unit} between two sets of prices.

    A recipe's cost is a sum of quantity x price, so it is linear in every price. That makes
    the split exact: change one price at a time, measure the difference, and the differences
    add up to the whole move. No estimate and no ordering effects (unlike costs that multiply).

    Only ingredients priced in both sets count; a first-ever price turns "unknown" into a
    number, which is not a change.
    ponytail: one full re-cost per changed ingredient. Fine for tens of price changes; if it
    ever matters, flatten each recipe to ingredient quantities once and take dot products."""
    base = cost_recipes(yields, lines, before)
    drivers: dict[UUID, dict[UUID, Decimal]] = {}
    for ingredient_id, price in after.items():
        if before.get(ingredient_id, price) == price:
            continue
        moved = cost_recipes(yields, lines, {**before, ingredient_id: price})
        for recipe_id, cost in moved.items():
            was = base[recipe_id].per_unit
            if cost.per_unit is not None and was is not None and cost.per_unit != was:
                drivers.setdefault(recipe_id, {})[ingredient_id] = cost.per_unit - was
    return drivers
