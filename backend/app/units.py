"""Units shared by inventory (ingredients) and menu (recipe yields)."""

from enum import StrEnum

from sqlalchemy.dialects.postgresql import ENUM


class BaseUnit(StrEnum):
    g = "g"
    ml = "ml"
    each = "each"


# Named PG enum so binds are cast to base_unit (a plain varchar bind would be rejected).
base_unit_type = ENUM(BaseUnit, name="base_unit", create_type=False)
