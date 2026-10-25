from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

from app.inventory.models import BaseUnit

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Phone = Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)]


class SupplierCreate(BaseModel):
    id: UUID | None = None
    name: Name
    phone: Phone | None = None


class SupplierUpdate(BaseModel):
    name: Name | None = None
    phone: Phone | None = None


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    phone: str | None
    version: int
    created_at: datetime
    updated_at: datetime


class IngredientCreate(BaseModel):
    id: UUID | None = None
    name: Name
    base_unit: BaseUnit
    default_supplier_id: UUID | None = None


class IngredientUpdate(BaseModel):
    # No base_unit: existing prices' pack_qty (and later recipe quantities) are in the old unit.
    name: Name | None = None
    default_supplier_id: UUID | None = None


class IngredientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    base_unit: BaseUnit
    default_supplier_id: UUID | None
    version: int
    created_at: datetime
    updated_at: datetime


class PriceCreate(BaseModel):
    id: UUID | None = None
    supplier_id: UUID | None = None
    pack_qty: Annotated[Decimal, Field(gt=0, description="Pack size in the ingredient's base unit")]
    pack_price_cents: Annotated[int, Field(ge=0)]
    observed_at: AwareDatetime | None = None


class PriceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    ingredient_id: UUID
    supplier_id: UUID | None
    pack_qty: Decimal
    pack_price_cents: int
    observed_at: datetime
    created_at: datetime
