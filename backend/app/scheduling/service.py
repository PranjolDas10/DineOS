"""Staff schedule and labor cost. The no-overlap rule is not checked here: the shifts table's
exclusion constraint enforces it atomically, even for concurrent edits (see migration 0008)."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud
from app.api import Problem
from app.money import cents
from app.scheduling.models import Shift, Staff
from app.scheduling.schemas import ShiftCreate, ShiftUpdate

MAX_RANGE = timedelta(days=31)


def _range(starts_at: datetime, ends_at: datetime) -> Range[datetime]:
    return Range(starts_at, ends_at, bounds="[)")  # half-open: back-to-back shifts don't clash


async def create_shift(session: AsyncSession, body: ShiftCreate) -> Shift:
    staff = await session.get(Staff, body.staff_id)
    if staff is None or not staff.active:
        raise Problem(422, "staff_id must be an active staff member.")
    values: dict[str, Any] = {
        "staff_id": staff.id,
        "during": _range(body.starts_at, body.ends_at),
        "hourly_rate_cents": staff.hourly_rate_cents,
        "note": body.note,
    }
    if body.id is not None:
        values["id"] = body.id
    return await crud.create(session, Shift, values)


async def move_shift(
    session: AsyncSession, shift_id: UUID, version: int, body: ShiftUpdate
) -> Shift:
    values = {"during": _range(body.starts_at, body.ends_at), "note": body.note}
    return await crud.update_versioned(session, Shift, shift_id, version, values)


async def list_shifts(session: AsyncSession, start: datetime, end: datetime) -> list[Shift]:
    """Shifts overlapping [start, end): the week view. Bounded instead of paginated."""
    if not timedelta(0) < end - start <= MAX_RANGE:
        raise Problem(422, "end must be after start, at most 31 days later.")
    stmt = (
        select(Shift)
        .where(Shift.during.overlaps(_range(start, end)))
        .order_by(func.lower(Shift.during), Shift.id)
    )
    return list(await session.scalars(stmt))


async def labor_report(session: AsyncSession, first: date, last: date) -> dict[str, Any]:
    """Hours and labor cost per business day, in the restaurant's timezone. A shift counts
    for the local day it starts on, so a 17:00-01:00 closing shift is that evening's labor."""
    if not timedelta(0) <= last - first <= MAX_RANGE:
        raise Problem(422, "to must be on or after from, at most 31 days later.")
    timezone = await session.scalar(text("SELECT timezone FROM tenants"))  # RLS: own row only
    rows = await session.execute(
        text(
            """
            SELECT (lower(during) AT TIME ZONE :tz)::date AS day,
                   sum(extract(epoch FROM upper(during) - lower(during)) / 3600) AS hours,
                   sum(extract(epoch FROM upper(during) - lower(during)) / 3600
                       * hourly_rate_cents) AS labor
            FROM shifts
            WHERE (lower(during) AT TIME ZONE :tz)::date BETWEEN :first AND :last
            GROUP BY day ORDER BY day
            """
        ),
        {"tz": timezone, "first": first, "last": last},
    )
    days = [
        {"date": day, "hours": hours.quantize(Decimal("0.01")), "labor_cents": cents(labor)}
        for day, hours, labor in rows
    ]
    return {
        "timezone": timezone,
        "days": days,
        "total_hours": sum((d["hours"] for d in days), Decimal(0)),
        # Sum of the rounded days, so the total the owner sees matches the rows above it.
        "total_labor_cents": sum(d["labor_cents"] for d in days),
    }
