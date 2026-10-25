"""Request ids (HTTP and into jobs), JSON log lines, and route-template metrics."""

import json
import logging
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from prometheus_client import REGISTRY
from sqlalchemy.ext.asyncio import AsyncSession

from app import jobs
from app.db import SessionLocal, set_tenant
from app.observability import JsonFormatter, request_id
from tests.conftest import MakeTenant, auth_headers

pytestmark = pytest.mark.anyio


async def test_every_response_carries_a_request_id(client: AsyncClient) -> None:
    fresh = (await client.get("/healthz")).headers["x-request-id"]
    assert len(fresh) == 32 and int(fresh, 16) >= 0  # a new uuid4 hex

    # A caller's own id is kept, so a phone's logs and ours line up...
    kept = await client.get("/healthz", headers={"X-Request-ID": "android-7f3a.2"})
    assert kept.headers["x-request-id"] == "android-7f3a.2"
    # ...unless it could be abused (log injection, huge values): then we mint our own.
    unsafe = await client.get("/healthz", headers={"X-Request-ID": "x\r\nlevel: ERROR"})
    assert unsafe.headers["x-request-id"] != "x\r\nlevel: ERROR"


def test_log_lines_are_json_with_the_request_id() -> None:
    token = request_id.set("req-123")
    try:
        record = logging.LogRecord(
            "app.test", logging.INFO, __file__, 1, "parsed %s", ("r1",), None
        )
        record.fields = {"tokens": 1500}
        line = json.loads(JsonFormatter().format(record))
    finally:
        request_id.reset(token)
    assert {k: line[k] for k in ("level", "msg", "request_id", "tokens")} == {
        "level": "INFO",
        "msg": "parsed r1",
        "request_id": "req-123",
        "tokens": 1500,
    }


async def test_metrics_are_labeled_by_route_template(
    client: AsyncClient, make_tenant: MakeTenant
) -> None:
    labels = {"method": "GET", "route": "/v1/suppliers/{supplier_id}", "status": "404"}
    before = REGISTRY.get_sample_value("http_requests_total", labels) or 0
    headers = auth_headers(await make_tenant())
    for _ in range(2):  # two different ids, one time series
        await client.get(f"/v1/suppliers/{uuid.uuid4()}", headers=headers)
    assert REGISTRY.get_sample_value("http_requests_total", labels) == before + 2


async def test_jobs_inherit_the_enqueuing_request_id(make_tenant: MakeTenant) -> None:
    tenant, kind = await make_tenant(), f"test_{uuid.uuid4().hex[:8]}"
    seen: list[str | None] = []

    @jobs.job(kind)
    async def handler(session: AsyncSession, payload: dict[str, Any]) -> None:
        seen.append(request_id.get())

    token = request_id.set("req-from-phone")  # as if inside an HTTP request
    try:
        async with SessionLocal() as session, session.begin():
            await set_tenant(session, tenant)
            await jobs.enqueue(session, kind, {})
    finally:
        request_id.reset(token)

    await jobs.run_once([kind])  # later, in the worker, outside any request
    assert seen == ["req-from-phone"]
    assert request_id.get() is None  # restored after the job
    assert REGISTRY.get_sample_value("jobs_total", {"kind": kind, "outcome": "done"}) == 1
