"""Sales export (CSV) -> orders. Pure: text in, orders out, or row-numbered errors.

One row per sold item; rows with the same order_id form one order. Order-level fields
(placed_at, channel, tax, tip) are read from the order's first row.

Canonical DineOS format (columns; unit_price, tax, tip optional):
    order_id, placed_at, channel, item, quantity, unit_price, line_total, tax, tip
placed_at is restaurant-local time ("2026-10-20 18:45") or ISO 8601 with an offset.
Money may include "$" and thousands separators: "$1,234.50".
"""

import csv
import io
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

# Source -> {canonical column: column name in that source's export}.
# ponytail: only the canonical format so far. Maitre'D (offline) gets an entry built from a
# real export file; its column names are not guessed.
PROFILES: dict[str, dict[str, str]] = {
    "dineos": {
        c: c
        for c in (
            "order_id",
            "placed_at",
            "channel",
            "item",
            "quantity",
            "unit_price",
            "line_total",
            "tax",
            "tip",
        )
    },
}
REQUIRED = ("order_id", "placed_at", "channel", "item", "quantity", "line_total")
MAX_ERRORS = 20


class SalesFileError(ValueError):
    """The file can't be imported; the message lists the first problems by row number."""


@dataclass(frozen=True)
class Item:
    name: str
    quantity: Decimal
    unit_price_cents: int
    line_total_cents: int


@dataclass
class Order:
    external_id: str
    channel: str
    placed_at: datetime
    tax_cents: int
    tip_cents: int
    items: list[Item]

    @property
    def subtotal_cents(self) -> int:
        return sum(i.line_total_cents for i in self.items)

    def payload(self) -> dict[str, Any]:
        """Canonical, JSON-ready form: stored as the event, and hashed to detect changes."""
        return {
            "external_id": self.external_id,
            "channel": self.channel,
            "placed_at": self.placed_at.isoformat(),
            "tax_cents": self.tax_cents,
            "tip_cents": self.tip_cents,
            "items": [
                {
                    "name": i.name,
                    "quantity": str(i.quantity),
                    "unit_price_cents": i.unit_price_cents,
                    "line_total_cents": i.line_total_cents,
                }
                for i in self.items
            ],
        }


def parse_cents(raw: str | None, required: bool = False) -> int:
    text = (raw or "").strip().replace("$", "").replace(",", "")
    if not text:
        if required:
            raise ValueError("missing amount")
        return 0
    cents = Decimal(text) * 100
    if cents != cents.to_integral_value():
        raise ValueError(f"{raw!r} has more than 2 decimals")
    return int(cents)


def parse_time(raw: str, tz: ZoneInfo) -> datetime:
    value = datetime.fromisoformat(raw.strip())
    if value.tzinfo is None:
        value = value.replace(tzinfo=tz)  # POS exports are in restaurant-local time
    return value.astimezone(UTC)


def parse_sales(text: str, source: str, tz: ZoneInfo) -> list[Order]:
    columns = PROFILES[source]
    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in REQUIRED if columns[c] not in (reader.fieldnames or [])]
    if missing:
        raise SalesFileError(f"missing columns: {', '.join(columns[c] for c in missing)}")

    orders: dict[str, Order] = {}
    errors: list[str] = []
    for line_no, row in enumerate(reader, start=2):  # line 1 is the header

        def col(name: str, row: dict[str, str] = row) -> str:
            return (row.get(columns[name]) or "").strip()

        try:
            external_id, name = col("order_id"), col("item")
            if not external_id or not name:
                raise ValueError("order_id and item are required")
            quantity = Decimal(col("quantity"))
            line_total = parse_cents(col("line_total"), required=True)
            unit_price = (
                parse_cents(col("unit_price"))
                if col("unit_price")
                else int((Decimal(line_total) / quantity).to_integral_value())
            )
            if external_id not in orders:
                orders[external_id] = Order(
                    external_id=external_id,
                    channel=col("channel").lower() or "unknown",
                    placed_at=parse_time(col("placed_at"), tz),
                    tax_cents=parse_cents(col("tax")),
                    tip_cents=parse_cents(col("tip")),
                    items=[],
                )
            orders[external_id].items.append(Item(name, quantity, unit_price, line_total))
        except (ValueError, ArithmeticError) as exc:  # decimal errors are ArithmeticErrors
            errors.append(f"line {line_no}: {exc or 'invalid number'}")
            if len(errors) == MAX_ERRORS:
                break
    if errors:
        raise SalesFileError("; ".join(errors))
    return list(orders.values())
