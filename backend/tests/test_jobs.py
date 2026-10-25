"""Job queue: outbox semantics, tenant scoping, retries, and SKIP LOCKED between workers."""

import asyncio
import uuid
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import jobs
from app.db import SessionLocal, set_tenant
from tests.conftest import MakeTenant

pytestmark = pytest.mark.anyio


def kind() -> str:
    """Unique per test, so run_once never claims another test's leftover jobs."""
    return f"test_{uuid.uuid4().hex[:8]}"


async def in_tenant(tenant_id: UUID, sql: str, **params: Any) -> Any:
    async with SessionLocal() as session, session.begin():
        await set_tenant(session, tenant_id)
        return (await session.execute(text(sql), params)).one_or_none()


async def enqueue(tenant_id: UUID, k: str, payload: dict[str, Any]) -> UUID:
    async with SessionLocal() as session, session.begin():
        await set_tenant(session, tenant_id)
        return await jobs.enqueue(session, k, payload)


async def test_rolled_back_transaction_enqueues_nothing(make_tenant: MakeTenant) -> None:
    tenant, k = await make_tenant(), kind()
    with pytest.raises(RuntimeError):
        async with SessionLocal() as session, session.begin():
            await set_tenant(session, tenant)
            await jobs.enqueue(session, k, {})
            raise RuntimeError("state change failed")
    assert await jobs.run_once([k]) is None


async def test_handler_runs_in_jobs_tenant(make_tenant: MakeTenant) -> None:
    tenant, k = await make_tenant(), kind()
    seen: list[tuple[dict[str, Any], str]] = []

    @jobs.job(k)
    async def handler(session: AsyncSession, payload: dict[str, Any]) -> None:
        tid = await session.scalar(text("SELECT current_setting('app.tenant_id')"))
        seen.append((payload, tid))

    job_id = await enqueue(tenant, k, {"receipt_id": "r1"})
    assert await jobs.run_once([k]) == job_id
    assert seen == [({"receipt_id": "r1"}, str(tenant))]
    row = await in_tenant(tenant, "SELECT status, attempts FROM jobs WHERE id = :id", id=job_id)
    assert tuple(row) == ("done", 1)
    assert await jobs.run_once([k]) is None  # done jobs are never claimed again


async def test_failure_rolls_back_handler_and_retries(make_tenant: MakeTenant) -> None:
    tenant, k = await make_tenant(), kind()

    @jobs.job(k)
    async def flaky(session: AsyncSession, payload: dict[str, Any]) -> None:
        await session.execute(text("INSERT INTO suppliers (name) VALUES ('half-done work')"))
        raise ValueError("Claude timed out")

    job_id = await enqueue(tenant, k, {})
    await in_tenant(
        tenant, "UPDATE jobs SET max_attempts = 2 WHERE id = :id RETURNING id", id=job_id
    )

    await jobs.run_once([k])
    row = await in_tenant(
        tenant,
        "SELECT status, attempts, last_error, run_after > now() FROM jobs WHERE id = :id",
        id=job_id,
    )
    assert tuple(row) == ("queued", 1, "ValueError: Claude timed out", True)
    assert await jobs.run_once([k]) is None  # backing off: not ready yet
    assert (await in_tenant(tenant, "SELECT count(*) FROM suppliers"))[0] == 0  # savepoint undo

    await in_tenant(
        tenant, "UPDATE jobs SET run_after = now() WHERE id = :id RETURNING id", id=job_id
    )
    await jobs.run_once([k])
    row = await in_tenant(tenant, "SELECT status, attempts FROM jobs WHERE id = :id", id=job_id)
    assert tuple(row) == ("failed", 2)  # dead-lettered, kept for inspection


async def test_concurrent_workers_claim_different_jobs(make_tenant: MakeTenant) -> None:
    """Both handlers block until released. If claiming didn't SKIP LOCKED rows, the second
    worker would wait on the first job's lock and never start: the test would time out."""
    tenant, k = await make_tenant(), kind()
    started: list[str] = []
    release, both_started = asyncio.Event(), asyncio.Event()

    @jobs.job(k)
    async def slow(session: AsyncSession, payload: dict[str, Any]) -> None:
        started.append(payload["n"])
        if len(started) == 2:
            both_started.set()
        await release.wait()

    await enqueue(tenant, k, {"n": "first"})
    await enqueue(tenant, k, {"n": "second"})
    workers = [asyncio.create_task(jobs.run_once([k])) for _ in range(2)]
    try:
        async with asyncio.timeout(15):
            await both_started.wait()
    finally:
        release.set()  # on failure too: otherwise the held row lock blocks fixture cleanup
    assert sorted(started) == ["first", "second"]
    assert len(set(await asyncio.gather(*workers))) == 2


def test_backoff_doubles_and_caps() -> None:
    assert [jobs.backoff_seconds(n) for n in (1, 2, 3)] == [2, 4, 8]
    assert jobs.backoff_seconds(30) == 600
