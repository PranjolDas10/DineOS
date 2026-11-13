"""Menu engineering (Kasavana and Smith, 1982): sort dishes by two questions. Does it sell?
Does a plate earn? Pure functions: no DB, no I/O.

- Popular = at least 70% of an even share of plates. With 10 dishes an even share is 10%,
  so the bar is 7%. The 70% is the method's convention: "not far below average" counts.
- Profitable = margin per plate at or above the menu's average margin per plate sold
  (weighted by sales, so a rarely sold dish doesn't drag the bar around).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal
from uuid import UUID

Kind = Literal["star", "plowhorse", "puzzle", "dog"]
POPULARITY_FACTOR = Decimal("0.7")


@dataclass(frozen=True)
class Dish:
    menu_item_id: UUID
    units: Decimal  # plates sold in the period
    margin: Decimal  # cents kept per plate after food cost


@dataclass(frozen=True)
class Matrix:
    popularity_bar: Decimal  # plates
    margin_bar: Decimal  # cents per plate
    kinds: dict[UUID, Kind]


def classify(dishes: Sequence[Dish]) -> Matrix | None:
    """None when nothing sold: there is no average to compare against."""
    total = sum((d.units for d in dishes), Decimal(0))
    if total <= 0:
        return None
    popularity_bar = total / len(dishes) * POPULARITY_FACTOR
    margin_bar = sum((d.units * d.margin for d in dishes), Decimal(0)) / total
    names: dict[tuple[bool, bool], Kind] = {
        (True, True): "star",
        (True, False): "plowhorse",
        (False, True): "puzzle",
        (False, False): "dog",
    }
    return Matrix(
        popularity_bar,
        margin_bar,
        {d.menu_item_id: names[d.units >= popularity_bar, d.margin >= margin_bar] for d in dishes},
    )
