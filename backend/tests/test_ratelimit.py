"""Rate limits: token bucket in Redis (real Redis, like the real Postgres in other tests)."""

import asyncio
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app import ratelimit
from app.api import Problem
from app.auth.service import hash_password
from app.config import MigrationSettings
from tests.conftest import MakeTenant, auth_headers

pytestmark = pytest.mark.anyio


async def test_bucket_allows_a_burst_then_refills(client: AsyncClient) -> None:
    fast = ratelimit.Limit("test", capacity=2, per_second=20)
    key = uuid.uuid4().hex
    await ratelimit.check(fast, key)
    await ratelimit.check(fast, key)
    with pytest.raises(Problem) as denied:
        await ratelimit.check(fast, key)
    assert denied.value.status == 429
    assert denied.value.headers == {"Retry-After": "1"}  # never rounds down to 0
    await asyncio.sleep(0.1)  # 20 tokens/s: about 2 back
    await ratelimit.check(fast, key)


async def test_login_locks_out_an_account_after_five_tries(
    client: AsyncClient, make_tenant: MakeTenant
) -> None:
    tenant_id, email = await make_tenant(), f"owner-{uuid.uuid4().hex[:8]}@example.com"
    owner = create_async_engine(MigrationSettings().migration_database_url)
    async with owner.begin() as conn:
        await conn.execute(
            text("INSERT INTO users (tenant_id, email, password_hash) VALUES (:t, :e, :h)"),
            {"t": tenant_id, "e": email, "h": hash_password("right-password")},
        )
    await owner.dispose()

    async def login(password: str, who: str = email) -> Any:
        return await client.post("/v1/auth/login", json={"email": who, "password": password})

    assert [(await login("guess")).status_code for _ in range(5)] == [401] * 5
    locked = await login("right-password")  # even the right password waits now
    assert locked.status_code == 429
    assert int(locked.headers["retry-after"]) > 0
    assert locked.headers["content-type"] == "application/problem+json"
    # Same IP, another account: still has its own tries.
    assert (await login("guess", who=email.upper().replace("OWNER", "other"))).status_code == 401


async def test_each_restaurant_has_its_own_bucket(
    client: AsyncClient, make_tenant: MakeTenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ratelimit, "TENANT", ratelimit.Limit("tenant", capacity=3, per_second=0.01))
    busy, quiet = auth_headers(await make_tenant()), auth_headers(await make_tenant())
    codes = [(await client.get("/v1/suppliers", headers=busy)).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    assert (await client.get("/v1/suppliers", headers=quiet)).status_code == 200


async def test_redis_outage_fails_open(
    client: AsyncClient, make_tenant: MakeTenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def down(**_: Any) -> int:
        raise RedisConnectionError("connection refused")

    monkeypatch.setattr(ratelimit, "_BUCKET", down)
    headers = auth_headers(await make_tenant())
    assert (await client.get("/v1/suppliers", headers=headers)).status_code == 200
