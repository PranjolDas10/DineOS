from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Mapped, mapped_column

from app.db import Entity, Versioned
from app.units import BaseUnit, base_unit_type


class Supplier(Versioned):
    __tablename__ = "suppliers"
    name: Mapped[str]
    phone: Mapped[str | None]


class Ingredient(Versioned):
    __tablename__ = "ingredients"
    name: Mapped[str]
    base_unit: Mapped[BaseUnit] = mapped_column(base_unit_type)
    default_supplier_id: Mapped[UUID | None]


class IngredientPrice(Entity):
    __tablename__ = "ingredient_prices"
    ingredient_id: Mapped[UUID]
    supplier_id: Mapped[UUID | None]
    pack_qty: Mapped[Decimal]
    pack_price_cents: Mapped[int]
    observed_at: Mapped[datetime]
    created_at: Mapped[datetime]
