from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Mapped, mapped_column

from app.db import Entity, Versioned
from app.units import BaseUnit, base_unit_type


class Recipe(Versioned):
    __tablename__ = "recipes"
    name: Mapped[str]
    yield_qty: Mapped[Decimal]
    yield_unit: Mapped[BaseUnit] = mapped_column(base_unit_type)


class RecipeLine(Entity):
    __tablename__ = "recipe_lines"
    recipe_id: Mapped[UUID]
    ingredient_id: Mapped[UUID | None]
    sub_recipe_id: Mapped[UUID | None]
    qty: Mapped[Decimal]


class MenuItem(Versioned):
    __tablename__ = "menu_items"
    name: Mapped[str]
    price_cents: Mapped[int]
    recipe_id: Mapped[UUID | None]
    portion_qty: Mapped[Decimal]
