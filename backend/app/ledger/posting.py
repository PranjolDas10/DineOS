"""Double-entry postings for a sale. Pure functions: an order in, balanced entries out.

Sign convention: amount > 0 is a debit, < 0 a credit; a transaction's entries sum to zero.
A dine-in order of $50 food + $4 tax + $8 tip, food costing $14:

    cash            +6200    (we received 62.00)
    revenue         -5000    (earned 50.00 from food, split per dish)
    tax_payable      -400    (owed to the government)
    tips_payable     -800    (owed to staff)
    food_cost       +1400    (expense: what the food cost us, per dish)
    inventory       -1400    (stock used up)
                    -----
                        0

A delivery order also has platform_commission (+) and less cash (the platform keeps it).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class Entry:
    account: str
    amount_cents: int
    menu_item_id: UUID | None = None


def _round(amount: Decimal) -> int:
    return int(amount.quantize(Decimal(1), ROUND_HALF_EVEN))


def sale_entries(
    order: Mapping[str, Any],
    commission_bps: int,
    portion_costs: Mapping[UUID, Decimal | None],
) -> tuple[list[Entry], bool]:
    """Entries for one order, and whether every item's food cost was known. Commission is
    charged on food (subtotal), not on tax or tip. Unknown food cost is left out, never
    guessed, and flagged so reports can say "food cost incomplete"."""
    commission = _round(Decimal(order["subtotal_cents"]) * commission_bps / 10_000)
    entries = [
        Entry("cash", order["total_cents"] - commission),
        Entry("platform_commission", commission),
        Entry("tax_payable", -order["tax_cents"]),
        Entry("tips_payable", -order["tip_cents"]),
    ]
    complete = True
    for item in order["items"]:
        menu_item_id = item["menu_item_id"]
        entries.append(Entry("revenue", -item["line_total_cents"], menu_item_id))
        cost = portion_costs.get(menu_item_id) if menu_item_id else None
        if cost is None:
            complete = False
            continue
        food = _round(Decimal(item["quantity"]) * cost)
        entries += [Entry("food_cost", food, menu_item_id), Entry("inventory", -food, menu_item_id)]
    entries = [e for e in entries if e.amount_cents != 0]
    assert sum(e.amount_cents for e in entries) == 0, "unbalanced sale"  # the DB checks too
    return entries, complete


def reversal_entries(entries: list[Entry]) -> list[Entry]:
    """Exactly cancels a transaction. Corrections never edit the books, they add to them."""
    return [Entry(e.account, -e.amount_cents, e.menu_item_id) for e in entries]


def allocate(total: int, weights: list[int]) -> list[int]:
    """Split integer cents in proportion to weights so the parts add up to exactly `total`
    (largest remainder: the leftover cents go to the largest fractional parts)."""
    whole = sum(weights)
    if whole <= 0:
        return [0] * len(weights)
    exact = [Decimal(total) * w / whole for w in weights]
    parts = [int(x) for x in exact]
    by_remainder = sorted(range(len(weights)), key=lambda i: exact[i] - parts[i], reverse=True)
    for i in by_remainder[: total - sum(parts)]:
        parts[i] += 1
    return parts
