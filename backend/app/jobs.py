"""Postgres job queue (see docs/adr/0001-postgres-job-queue.md).

- enqueue() inserts in the caller's transaction: the queue is the outbox.
- run_once() claims one job with FOR UPDATE SKIP LOCKED and runs its handler in the same
  transaction, under the job's tenant. Success commits the handler's writes and marks the job
  done atomically; failure rolls back only the handler (savepoint) and records the retry.
- Delivery is at-least-once, so every handler must be safe to run twice.
"""

import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal, set_tenant

Handler = Callable[[AsyncSession, dict[str, Any]], Awaitable[None]]
_handlers: dict[str, Handler] = {}
log = logging.getLogger(__name__)


def job(kind: str) -> Callable[[Handler], Handler]:
    """Register a handler: @job("parse_receipt") async def parse(session, payload): ..."""

    def register(fn: Handler) -> Handler:
        _handlers[kind] = fn
        return fn

    return register


async def enqueue(
    session: AsyncSession,
    kind: str,
    payload: dict[str, Any],
    run_after: datetime | None = None,
    dedupe_key: str | None = None,
) -> UUID | None:
    """Insert a job in the caller's transaction. run_after delays it (scheduled work).
    dedupe_key makes it at-most-once per tenant: a second enqueue with the same key is a
    no-op and returns None (e.g. "checklist_day:2026-10-20")."""
    job_id: UUID | None = await session.scalar(
        text(
            "INSERT INTO jobs (kind, payload, run_after, dedupe_key)"
            " VALUES (:k, CAST(:p AS jsonb), coalesce(:r, now()), :d)"
            " ON CONFLICT (tenant_id, dedupe_key) DO NOTHING RETURNING id"
        ),
        {"k": kind, "p": json.dumps(payload), "r": run_after, "d": dedupe_key},
    )
    return job_id


def backoff_seconds(attempts: int) -> int:
    """2, 4, 8, ... seconds, capped at 10 minutes."""
    return int(min(2**attempts, 600))


async def run_once(kinds: Sequence[str] | None = None) -> UUID | None:
    """Claim and run one ready job. Returns its id, or None if nothing was ready.
    Only claims kinds this process has handlers for (or the given subset)."""
    kinds = list(kinds) if kinds is not None else list(_handlers)
    async with SessionLocal() as session, session.begin():
        row = (
            await session.execute(text("SELECT * FROM claim_job(:k)"), {"k": kinds})
        ).one_or_none()
        if row is None:
            return None
        await set_tenant(session, row.tenant_id)
        try:
            async with session.begin_nested():  # savepoint: a failure undoes only the handler
                await _handlers[row.kind](session, json.loads(row.payload))
        except Exception as exc:  # any handler failure is retried, never lost
            attempts = row.attempts + 1
            final = attempts >= row.max_attempts
            log.exception("job %s (%s) failed, attempt %d", row.id, row.kind, attempts)
            await session.execute(
                text(
                    "UPDATE jobs SET attempts = :a, last_error = :e, status = :s,"
                    " run_after = now() + make_interval(secs => :d), updated_at = now()"
                    " WHERE id = :id"
                ),
                {
                    "a": attempts,
                    "e": f"{type(exc).__name__}: {exc}"[:2000],
                    "s": "failed" if final else "queued",
                    "d": backoff_seconds(attempts),
                    "id": row.id,
                },
            )
        else:
            await session.execute(
                text(
                    "UPDATE jobs SET status = 'done', attempts = attempts + 1, updated_at = now()"
                    " WHERE id = :id"
                ),
                {"id": row.id},
            )
        job_id: UUID = row.id
        return job_id
