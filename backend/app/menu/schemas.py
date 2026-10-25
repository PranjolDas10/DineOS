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
