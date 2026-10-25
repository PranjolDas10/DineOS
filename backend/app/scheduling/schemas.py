from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
MAX_SHIFT = timedelta(hours=16)  # same limit as the DB CHECK; here for a readable error


class StaffCreate(BaseModel):
    id: UUID | None = None
    name: Name
    hourly_rate_cents: Annotated[int, Field(ge=0)]


class StaffUpdate(BaseModel):
    name: Name | None = None
    hourly_rate_cents: Annotated[int, Field(ge=0)] | None = None
    active: bool | None = None


class StaffOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    hourly_rate_cents: int
    active: bool
    version: int
    created_at: datetime
    updated_at: datetime


class ShiftTimes(BaseModel):
    starts_at: AwareDatetime
    ends_at: AwareDatetime

    @model_validator(mode="after")
    def sane_length(self) -> Self:
        if not timedelta(0) < self.ends_at - self.starts_at <= MAX_SHIFT:
            raise ValueError("a shift must end after it starts and last at most 16 hours")
        return self


class ShiftCreate(ShiftTimes):
    id: UUID | None = None
    staff_id: UUID
    note: Note | None = None


class ShiftUpdate(ShiftTimes):
    """Moving a shift. To give it to someone else, delete it and create a new one
    (the new person's rate must be snapshotted)."""

    note: Note | None = None


class ShiftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    staff_id: UUID
    starts_at: datetime
    ends_at: datetime
    hourly_rate_cents: int
    note: str | None
    version: int


class ShiftList(BaseModel):
    items: list[ShiftOut]


class LaborDay(BaseModel):
    date: date
    hours: Decimal
    labor_cents: int


class LaborReport(BaseModel):
    timezone: str
    days: list[LaborDay]
    total_hours: Decimal
    total_labor_cents: int
