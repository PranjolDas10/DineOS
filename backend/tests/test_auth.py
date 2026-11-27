"""Auth: login, bearer tokens, refresh rotation with reuse detection, logout."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.auth.service import hash_password
from app.config import MigrationSettings, settings
from tests.conftest import MakeTenant, auth_headers

pytestmark = pytest.mark.anyio
PASSWORD = "correct horse battery staple"


@pytest.fixture
async def owner_email(make_tenant: MakeTenant) -> str:
    """An owner account in a fresh tenant (created as the owner DB role, like the CLI does)."""
    tenant_id, email = await make_tenant(), f"owner-{uuid.uuid4().hex[:8]}@example.com"
    engine = create_async_engine(MigrationSettings().migration_database_url)
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO users (tenant_id, email, password_hash) VALUES (:t, :e, :h)"),
            {"t": tenant_id, "e": email, "h": hash_password(PASSWORD)},
        )
    await engine.dispose()
    return email


async def login(client: AsyncClient, email: str, password: str = PASSWORD) -> dict[str, str]:
    resp = await client.post("/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    tokens: dict[str, str] = resp.json()
    return tokens


async def refresh_status(client: AsyncClient, token: str) -> int:
    return (await client.post("/v1/auth/refresh", json={"refresh_token": token})).status_code


async def test_login_then_access_token_works(client: AsyncClient, owner_email: str) -> None:
    tokens = await login(client, owner_email.upper())  # email match is case-insensitive
    bearer = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert (await client.get("/v1/suppliers", headers=bearer)).status_code == 200


async def test_me_names_the_restaurant_and_its_local_date(
    client: AsyncClient, owner_email: str
) -> None:
    tokens = await login(client, owner_email)
    resp = await client.get(
        "/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert (body["restaurant"], body["timezone"], body["email"]) == ("test", "UTC", owner_email)
    assert body["today"] == datetime.now(UTC).date().isoformat()


async def test_me_is_401_once_the_tenant_is_gone(client: AsyncClient) -> None:
    """A still-valid token for a deleted restaurant means "sign in again", not a server error."""
    resp = await client.get("/v1/auth/me", headers=auth_headers(uuid.uuid4()))
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"


async def test_bad_credentials_look_identical(client: AsyncClient, owner_email: str) -> None:
    wrong_pw = await client.post("/v1/auth/login", json={"email": owner_email, "password": "nope"})
    no_user = await client.post(
        "/v1/auth/login", json={"email": "nobody@example.com", "password": "nope"}
    )
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json() == no_user.json()  # no hint about which emails exist
    assert wrong_pw.headers["www-authenticate"] == "Bearer"


async def test_bad_tokens_are_401(client: AsyncClient) -> None:
    claims = {"sub": str(uuid.uuid4()), "tid": str(uuid.uuid4()), "role": "owner"}
    expired = jwt.encode(
        {**claims, "exp": datetime.now(UTC) - timedelta(seconds=1)}, settings.jwt_secret
    )
    forged = jwt.encode(
        {**claims, "exp": datetime.now(UTC) + timedelta(minutes=5)}, "x" * 32 + "wrong-key"
    )
    for headers in (
        {},
        {"Authorization": "Bearer junk"},
        *({"Authorization": f"Bearer {t}"} for t in (expired, forged)),
    ):
        resp = await client.get("/v1/suppliers", headers=headers)
        assert resp.status_code == 401, headers
        assert resp.headers["content-type"] == "application/problem+json"


async def test_refresh_rotates_and_reuse_revokes_family(
    client: AsyncClient, owner_email: str
) -> None:
    first = (await login(client, owner_email))["refresh_token"]
    resp = await client.post("/v1/auth/refresh", json={"refresh_token": first})
    assert resp.status_code == 200
    second = resp.json()["refresh_token"]
    assert second != first

    # Replaying the used token = it was stolen. Refuse it AND kill the attacker's/victim's chain.
    assert await refresh_status(client, first) == 401
    assert await refresh_status(client, second) == 401


async def test_logout_revokes_refresh(client: AsyncClient, owner_email: str) -> None:
    token = (await login(client, owner_email))["refresh_token"]
    resp = await client.post("/v1/auth/logout", json={"refresh_token": token})
    assert resp.status_code == 204
    assert await refresh_status(client, token) == 401
