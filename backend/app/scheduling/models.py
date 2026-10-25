from datetime import datetime
from uuid import UUID

from sqlalchemy.dialects.postgresql import TSTZRANGE, Range
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Versioned


class Staff(Versioned):
    __tablename__ = "staff"
    name: Mapped[str]
    hourly_rate_cents: Mapped[int]
    active: Mapped[bool]


class Shift(Versioned):
    __tablename__ = "shifts"
    staff_id: Mapped[UUID]
    during: Mapped[Range[datetime]] = mapped_column(TSTZRANGE)
    hourly_rate_cents: Mapped[int]  # snapshot of the staff rate when the shift was created
    note: Mapped[str | None]

    # The API speaks start/end; the database stores one range so it can index "overlaps".
    @property
    def starts_at(self) -> datetime | None:
        return self.during.lower

    @property
    def ends_at(self) -> datetime | None:
        return self.during.upper
