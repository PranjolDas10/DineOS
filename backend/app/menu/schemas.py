from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.units import BaseUnit

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Qty = Annotated[Decimal, Field(gt=0)]


class RecipeCreate(BaseModel):
    id: UUID | None = None
    name: Name
    yield_qty: Qty
    yield_unit: BaseUnit


class RecipeUpdate(BaseModel):
    # No yield_unit: lines that use this recipe as a sub-recipe are measured in it.
    name: Name | None = None
    yield_qty: Qty | None = None


class RecipeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    yield_qty: Decimal
    yield_unit: BaseUnit
    version: int
    created_at: datetime
    updated_at: datetime


class LineIn(BaseModel):
    # Exactly one of ingredient_id / sub_recipe_id: enforced by a DB CHECK (422 if violated).
    ingredient_id: UUID | None = None
    sub_recipe_id: UUID | None = None
    qty: Qty


class LineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    ingredient_id: UUID | None
    sub_recipe_id: UUID | None
    qty: Decimal


class Lines[T](BaseModel):
    lines: Annotated[list[T], Field(max_length=200)]


class MenuItemCreate(BaseModel):
    id: UUID | None = None
    name: Name
    price_cents: Annotated[int, Field(ge=0)]
    recipe_id: UUID | None = None
    portion_qty: Qty = Decimal(1)


class MenuItemUpdate(BaseModel):
    name: Name | None = None
    price_cents: Annotated[int, Field(ge=0)] | None = None
    recipe_id: UUID | None = None
    portion_qty: Qty | None = None


class MenuItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    price_cents: int
    recipe_id: UUID | None
    portion_qty: Decimal
    version: int
    created_at: datetime
    updated_at: datetime


class LineCostOut(BaseModel):
    ingredient_id: UUID | None
    sub_recipe_id: UUID | None
    qty: Decimal
    cost_cents: int | None


class RecipeCostOut(BaseModel):
    """Null cost means unknown: see unpriced_ingredient_ids / empty_recipe_ids for why."""

    recipe_id: UUID
    total_cents: int | None
    per_unit_cents: Decimal | None
    unpriced_ingredient_ids: list[UUID]
    empty_recipe_ids: list[UUID]
    lines: list[LineCostOut]


class FoodCostItem(BaseModel):
    menu_item_id: UUID
    name: str
    recipe_id: UUID | None
    price_cents: int
    cost_cents: int | None
    margin_cents: int | None
    food_cost_pct: Decimal | None
    unpriced_ingredient_ids: list[UUID]
    empty_recipe_ids: list[UUID]


class FoodCostReport(BaseModel):
    items: list[FoodCostItem]


class PriceChange(BaseModel):
    ingredient_id: UUID
    name: str
    base_unit: BaseUnit
    unit_cents_before: Decimal
    unit_cents_after: Decimal
    change_pct: Decimal | None
    dishes_affected: int


class CostDriver(BaseModel):
    ingredient_id: UUID
    name: str
    delta_cents: int


class DishImpact(BaseModel):
    menu_item_id: UUID
    name: str
    price_cents: int
    cost_before_cents: int
    cost_after_cents: int
    food_cost_pct_before: Decimal | None
    food_cost_pct_after: Decimal | None
    units_sold: Decimal
    weekly_impact_cents: int
    drivers: list[CostDriver]


class MarginWatch(BaseModel):
    """Ingredient price changes over the last `days` days and what they did to each dish."""

    days: int
    weekly_impact_cents: int
    ingredients: list[PriceChange]
    dishes: list[DishImpact]
