from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient

from app.db import get_session
from app.main import app

pytestmark = pytest.mark.anyio


async def test_healthz(client: AsyncClient) -> None:
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_readyz_real_postgres(client: AsyncClient) -> None:
    resp = await client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


class _DeadSession:
    async def execute(self, *_: object) -> None:
        raise OSError("connection refused")


async def test_readyz_db_down(client: AsyncClient) -> None:
    async def dead_session() -> AsyncIterator[_DeadSession]:
        yield _DeadSession()

    app.dependency_overrides[get_session] = dead_session
    try:
        resp = await client.get("/readyz")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 503
    assert resp.json() == {"status": "unavailable"}
