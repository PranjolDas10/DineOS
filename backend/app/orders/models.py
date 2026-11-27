from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Entity, Versioned


class SalesImport(Versioned):
    __tablename__ = "sales_imports"
    source: Mapped[str]
    object_key: Mapped[str]
    status: Mapped[str]
    orders_new: Mapped[int | None]
    orders_updated: Mapped[int | None]
    duplicates: Mapped[int | None]
    error: Mapped[str | None]


class OrderEvent(Entity):
    __tablename__ = "order_events"
    source: Mapped[str]
    external_id: Mapped[str]
    content_sha256: Mapped[bytes]
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    import_id: Mapped[UUID | None]
    received_at: Mapped[datetime]


class Order(Entity):
    __tablename__ = "orders"
    source: Mapped[str]
    external_id: Mapped[str]
    channel: Mapped[str]
    status: Mapped[str]
    placed_at: Mapped[datetime]
    subtotal_cents: Mapped[int]
    tax_cents: Mapped[int]
    tip_cents: Mapped[int]
    total_cents: Mapped[int]
    event_id: Mapped[UUID]
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class OrderItem(Entity):
    __tablename__ = "order_items"
    order_id: Mapped[UUID]
    position: Mapped[int]
    name: Mapped[str]
    menu_item_id: Mapped[UUID | None]
    quantity: Mapped[Decimal]
    unit_price_cents: Mapped[int]
    line_total_cents: Mapped[int]
