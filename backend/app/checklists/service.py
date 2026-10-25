"""Closing checklists: recurring templates become one run per business day, staff tick items
off (online or offline), and an alert fires if a run isn't finished by its due time.

Scheduling uses the job queue only:
- checklist_day(D) creates D's runs, then enqueues checklist_day(D+1) for local midnight.
  dedupe_key "checklist_day:<date>" makes each day's job at-most-once, so the chain can't fork;
  ensure_schedule() re-seeds it if it ever breaks (it runs on every "today" request).
- Creating a run enqueues checklist_overdue(run) for the run's due time.
"""

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import any_, select, text
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud, jobs
from app.alerts import service as alerts
from app.api import Problem
from app.checklists.models import Check, Run, Template


async def tenant_tz(session: AsyncSession) -> ZoneInfo:
    return ZoneInfo(await session.scalar(text("SELECT timezone FROM tenants")))  # RLS: own row


def local_midnight(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time(0), tz)


async def local_today(session: AsyncSession) -> date:
    return datetime.now(await tenant_tz(session)).date()


async def materialize(session: AsyncSession, day: date) -> None:
    """Create the day's runs from active templates. Idempotent (one run per template per day)."""
    tz = await tenant_tz(session)
    templates = await session.scalars(
        select(Template).where(Template.active, any_(Template.days_of_week) == day.weekday())
    )
    for t in templates:
        # Wall-clock arithmetic on an aware datetime: "due 23:30" stays 23:30 across DST.
        due_at = local_midnight(day, tz) + timedelta(minutes=t.due_minutes)
        run_id = await session.scalar(
            insert(Run)
            .values(template_id=t.id, name=t.name, business_date=day, due_at=due_at, items=t.items)
            .on_conflict_do_nothing(index_elements=["template_id", "business_date"])
            .returning(Run.id)
        )
        if run_id is not None:
            await jobs.enqueue(
                session,
                "checklist_overdue",
                {"run_id": str(run_id)},
                run_after=due_at,
                dedupe_key=f"checklist_overdue:{run_id}",
            )


async def _schedule_day(session: AsyncSession, day: date, run_after: datetime | None) -> None:
    await jobs.enqueue(
        session,
        "checklist_day",
        {"date": day.isoformat()},
        run_after=run_after,
        dedupe_key=f"checklist_day:{day}",  # at most one job per day: the chain can't fork
    )


async def ensure_schedule(session: AsyncSession, today: date) -> None:
    """Seed (or re-seed) the daily chain: today's job now, tomorrow's at local midnight."""
    tomorrow = today + timedelta(days=1)
    await _schedule_day(session, today, None)
    await _schedule_day(session, tomorrow, local_midnight(tomorrow, await tenant_tz(session)))


@jobs.job("checklist_day")
async def checklist_day(session: AsyncSession, payload: dict[str, Any]) -> None:
    day = date.fromisoformat(payload["date"])
    await materialize(session, day)
    tomorrow = day + timedelta(days=1)
    await _schedule_day(session, tomorrow, local_midnight(tomorrow, await tenant_tz(session)))


@jobs.job("checklist_overdue")
async def checklist_overdue(session: AsyncSession, payload: dict[str, Any]) -> None:
    """Idempotent: alerted_at makes a retried job a no-op."""
    run = await session.get(Run, UUID(payload["run_id"]))
    if run is None or run.completed_at is not None or run.alerted_at is not None:
        return
    state = await run_state(session, run)
    due = run.due_at.astimezone(await tenant_tz(session)).strftime("%H:%M")
    await alerts.notify(
        session,
        "checklist_overdue",
        f"{run.name} not finished",
        f"{state['done']} of {state['total']} items done; it was due at {due}.",
    )
    run.alerted_at = datetime.now(UTC)


async def run_state(session: AsyncSession, run: Run) -> dict[str, Any]:
    """Each item's state is its check event with the latest checked_at (tie: highest id).
    Arrival order doesn't matter, so offline phones syncing late can't flip newer state."""
    latest = await session.execute(
        select(Check.item_id, Check.checked)
        .where(Check.run_id == run.id)
        .ext(distinct_on(Check.item_id))
        .order_by(Check.item_id, Check.checked_at.desc(), Check.id.desc())
    )
    checked = {item_id: is_checked for item_id, is_checked in latest}
    items = [{**i, "checked": checked.get(UUID(i["id"]), False)} for i in run.items]
    return {
        "id": run.id,
        "template_id": run.template_id,
        "name": run.name,
        "business_date": run.business_date,
        "due_at": run.due_at,
        "completed_at": run.completed_at,
        "items": items,
        "done": sum(i["checked"] for i in items),
        "total": len(items),
    }


async def runs_for(session: AsyncSession, day: date) -> list[dict[str, Any]]:
    runs = await session.scalars(select(Run).where(Run.business_date == day).order_by(Run.due_at))
    return [await run_state(session, run) for run in runs]


async def record_checks(
    session: AsyncSession, run_id: UUID, checks: list[dict[str, Any]]
) -> dict[str, Any]:
    """Apply a batch of check/uncheck ops from a phone's sync queue. Ops carry client ids,
    so replaying a batch after a timeout changes nothing."""
    run = await crud.get_or_404(session, Run, run_id)
    known = {UUID(i["id"]) for i in run.items}
    if any(c["item_id"] not in known for c in checks):
        raise Problem(422, "item_id is not on this checklist.")
    if checks:
        await session.execute(
            insert(Check)
            .values([{**c, "run_id": run_id} for c in checks])
            .on_conflict_do_nothing(index_elements=["id"])
        )
    state = await run_state(session, run)
    finished = state["done"] == state["total"]
    if finished and run.completed_at is None:
        run.completed_at = datetime.now(UTC)
    elif not finished:
        run.completed_at = None  # an item was unchecked after completion
    state["completed_at"] = run.completed_at
    return state
