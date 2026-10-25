from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Mapped

from app.db import Entity, Versioned


class Receipt(Versioned):
    __tablename__ = "receipts"
    object_key: Mapped[str]
    status: Mapped[str]
    supplier_name: Mapped[str | None]
    receipt_date: Mapped[date | None]
    total_cents: Mapped[int | None]
    model: Mapped[str | None]
    prompt_version: Mapped[str | None]
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    failure_reason: Mapped[str | None]


class ReceiptLine(Entity):
    __tablename__ = "receipt_lines"
    receipt_id: Mapped[UUID]
    position: Mapped[int]
    description: Mapped[str]
    quantity: Mapped[Decimal]
    unit: Mapped[str]
    unit_price_cents: Mapped[int | None]
    line_total_cents: Mapped[int]
    confidence: Mapped[Decimal]
    ingredient_id: Mapped[UUID | None]
