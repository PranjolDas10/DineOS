"""Money rounding shared by food cost and labor cost. All math stays in exact Decimal cents;
round once, when presenting."""

from decimal import ROUND_HALF_EVEN, Decimal


def cents(amount: Decimal | None) -> int | None:
    """Round once, at the presentation boundary. Half-even avoids an upward bias over many sums."""
    return None if amount is None else int(amount.quantize(Decimal(1), ROUND_HALF_EVEN))


def percent(part: Decimal | None, whole: int) -> Decimal | None:
    if part is None or whole == 0:
        return None
    return (part * 100 / whole).quantize(Decimal("0.1"), ROUND_HALF_EVEN)
