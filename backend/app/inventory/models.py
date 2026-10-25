from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Entity, Versioned


class BaseUnit(StrEnum):
    g = "g"
    ml = "ml"
    each = "each"


class Supplier(Versioned):
    __tablename__ = "suppliers"
    name: Mapped[str]
    phone: Mapped[str | None]


class Ingredient(Versioned):
    __tablename__ = "ingredients"
    name: Mapped[str]
    # Named PG enum so binds are cast to base_unit (a plain varchar bind would be rejected).
    base_unit: Mapped[BaseUnit] = mapped_column(ENUM(BaseUnit, name="base_unit", create_type=False))
    default_supplier_id: Mapped[UUID | None]


class IngredientPrice(Entity):
    __tablename__ = "ingredient_prices"
    ingredient_id: Mapped[UUID]
    supplier_id: Mapped[UUID | None]
    pack_qty: Mapped[Decimal]
    pack_price_cents: Mapped[int]
    observed_at: Mapped[datetime]
    created_at: Mapped[datetime]
