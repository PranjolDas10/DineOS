"""Owner review of a parsed receipt: the human-in-the-loop step between the model and the books.

Confirming does three things in one transaction, under the receipt's ETag:
1. Saves the owner's corrected values on the receipt and its lines.
2. Appends an ingredient price for every line mapped to an ingredient.
3. Stores the model's output next to the confirmed truth as an eval label.
"""

import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any, Self
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, model_validator
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud
from app.alerts import service as alerts
from app.api import Problem
from app.inventory import service as inventory
from app.receipts.models import Receipt, ReceiptLine

# Lines below this are flagged for an explicit check in the UI.
# ponytail: a guess until the eval harness calibrates it against real receipts.
CONFIDENCE_THRESHOLD = Decimal("0.80")

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]

# A price that moved at least this much against the last one raises an alert.
# ponytail: fixed threshold; make it owner-editable if 5% turns out noisy or deaf.
PRICE_ALERT_PCT = Decimal(5)


class ConfirmLine(BaseModel):
    line_id: UUID
    # None = not an ingredient (napkins, cleaning supplies): kept on the receipt, no price.
    ingredient_id: UUID | None
    description: Text
    quantity: Annotated[Decimal, Field(gt=0)]
    unit: Text
    line_total_cents: Annotated[int, Field(ge=0)]
    # The line's quantity in the ingredient's base unit (g/ml/each). The UI converts
    # "1 sack, 50 lb" -> 22680 g, since only the owner knows what a "sack" is here.
    base_qty: Annotated[Decimal, Field(gt=0)] | None = None

    @model_validator(mode="after")
    def base_qty_iff_mapped(self) -> Self:
        if (self.ingredient_id is None) != (self.base_qty is None):
            raise ValueError("base_qty is required exactly when ingredient_id is set")
        return self


class ConfirmIn(BaseModel):
    supplier_id: UUID | None = None
    supplier_name: Text | None = None
    receipt_date: date | None = None
    total_cents: Annotated[int, Field(ge=0)] | None = None
    lines: list[ConfirmLine]


async def confirm(
    session: AsyncSession, receipt_id: UUID, version: int, body: ConfirmIn
) -> Receipt:
    receipt = await crud.get_or_404(session, Receipt, receipt_id)
    if receipt.status != "parsed":
        raise Problem(
            409, f"Only a parsed receipt can be confirmed (this one is {receipt.status})."
        )
    stmt = select(ReceiptLine).where(ReceiptLine.receipt_id == receipt_id)
    lines = {line.id: line for line in await session.scalars(stmt.order_by(ReceiptLine.position))}
    # Nothing is accepted by default: every extracted line needs an explicit decision.
    decided = [line.line_id for line in body.lines]
    if len(decided) != len(set(decided)) or set(decided) != set(lines):
        raise Problem(422, "Confirm or skip every extracted line exactly once.")

    model_output = _snapshot(receipt, lines.values())
    receipt = await crud.update_versioned(
        session,
        Receipt,
        receipt_id,
        version,
        {
            "status": "confirmed",
            "supplier_name": body.supplier_name,
            "receipt_date": body.receipt_date,
            "total_cents": body.total_cents,
        },
    )
    observed_at = (
        datetime(body.receipt_date.year, body.receipt_date.month, body.receipt_date.day, tzinfo=UTC)
        if body.receipt_date
        else datetime.now(UTC)
    )
    moved: list[tuple[UUID, Decimal]] = []  # ingredients whose current price changed
    for decision in body.lines:
        line = lines[decision.line_id]
        line.ingredient_id = decision.ingredient_id
        line.description, line.quantity = decision.description, decision.quantity
        line.unit, line.line_total_cents = decision.unit, decision.line_total_cents
        if decision.ingredient_id is not None and decision.base_qty is not None:
            replaced = await inventory.record_price(
                session,
                decision.ingredient_id,
                body.supplier_id,
                pack_qty=decision.base_qty,
                pack_price_cents=decision.line_total_cents,
                observed_at=observed_at,
            )
            if replaced:
                change = (decision.line_total_cents / decision.base_qty - replaced) * 100 / replaced
                if abs(change) >= PRICE_ALERT_PCT:
                    moved.append((decision.ingredient_id, change))
    if moved:
        labels = await inventory.ingredient_labels(session)
        for ingredient_id, change in moved:
            await alerts.notify(
                session,
                "price_change",
                f"{labels[ingredient_id][0]} is {'up' if change > 0 else 'down'}"
                f" {abs(change):.0f}%",
                f"From the {body.supplier_name or 'supplier'} receipt you just checked."
                " Menu costs shows which dishes it changes.",
            )

    await session.execute(
        text(
            "INSERT INTO receipt_labels"
            " (receipt_id, model, prompt_version, model_output, confirmed)"
            " VALUES (:r, :m, :v, CAST(:o AS jsonb), CAST(:c AS jsonb))"
        ),
        {
            "r": receipt_id,
            "m": receipt.model or "unknown",
            "v": receipt.prompt_version or "unknown",
            "o": json.dumps(model_output, default=str),
            "c": json.dumps(_snapshot(receipt, lines.values()), default=str),
        },
    )
    # Surface constraint errors (e.g. another tenant's ingredient id) here as a 4xx,
    # not later at commit.
    await session.flush()
    return receipt


def _snapshot(receipt: Receipt, lines: Iterable[ReceiptLine]) -> dict[str, Any]:
    """Same shape as the extractor's output, so the eval harness can diff field by field."""
    return {
        "supplier_name": receipt.supplier_name,
        "receipt_date": receipt.receipt_date.isoformat() if receipt.receipt_date else None,
        "total_cents": receipt.total_cents,
        "lines": [
            {
                "description": line.description,
                "quantity": str(line.quantity),
                "unit": line.unit,
                "line_total_cents": line.line_total_cents,
                "ingredient_id": str(line.ingredient_id) if line.ingredient_id else None,
            }
            for line in lines
        ],
    }
