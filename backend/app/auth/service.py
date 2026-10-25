"""Public interface of the auth module: login/refresh/logout and the request dependencies
every other module uses to get a tenant-scoped session."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import Problem
from app.auth.tokens import (
    ACCESS_TTL,
    REFRESH_TTL,
    decode_access,
    hash_refresh,
    issue_access,
    new_refresh,
)
from app.db import SessionLocal, set_tenant

_hasher = PasswordHasher()  # argon2id with the library's OWASP-aligned defaults
# Verified against when the email is unknown, so both paths take the same time
# (otherwise response time reveals which emails have accounts).
_DUMMY_HASH = _hasher.hash("not-a-real-password")
_UNAUTHORIZED = {"WWW-Authenticate": "Bearer"}
_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def _verify(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerificationError:
        return False


async def login(email: str, password: str) -> dict[str, Any]:
    async with SessionLocal() as session, session.begin():
        row = (
            await session.execute(text("SELECT * FROM auth_user_by_email(:e)"), {"e": email})
        ).one_or_none()
        # argon2 is deliberately slow (~50 ms of CPU). Off the event loop, so other requests
        # keep being served while one login hashes.
        ok = await asyncio.to_thread(_verify, row.password_hash if row else _DUMMY_HASH, password)
        if row is None or not ok:
            raise Problem(401, "Wrong email or password.", _UNAUTHORIZED)
        await set_tenant(session, row.tenant_id)
        return await _issue_pair(session, row.id, row.tenant_id, row.role, family_id=uuid.uuid4())


async def refresh(token: str) -> dict[str, Any]:
    """Rotate: each refresh token works once. Presenting a used one means it was copied,
    so the whole family (every token from that login) is revoked."""
    async with SessionLocal() as session:
        async with session.begin():
            row = (
                await session.execute(
                    text("SELECT * FROM auth_refresh_token(:h)"), {"h": hash_refresh(token)}
                )
            ).one_or_none()
            if row is None:
                raise Problem(401, "Invalid refresh token.", _UNAUTHORIZED)
            await set_tenant(session, row.tenant_id)
            # Atomic claim. Two concurrent refreshes with one token: the second waits on the
            # row lock, re-checks WHERE, matches nothing, and is treated as reuse.
            claimed = await session.scalar(
                text(
                    "UPDATE refresh_tokens SET used_at = now() WHERE id = :id"
                    " AND used_at IS NULL AND revoked_at IS NULL AND expires_at > now()"
                    " RETURNING id"
                ),
                {"id": row.id},
            )
            if claimed is not None:
                role = await session.scalar(
                    text("SELECT role FROM users WHERE id = :u"), {"u": row.user_id}
                )
                return await _issue_pair(session, row.user_id, row.tenant_id, role, row.family_id)
            reused = await session.scalar(
                text(
                    "SELECT used_at IS NOT NULL AND revoked_at IS NULL"
                    " FROM refresh_tokens WHERE id = :id"
                ),
                {"id": row.id},
            )
            if reused:
                await _revoke_family(session, row.family_id)
        # Committed above: the revocation must persist even though this request fails.
        raise Problem(401, "Refresh token expired, revoked or already used.", _UNAUTHORIZED)


async def logout(token: str) -> None:
    """Idempotent: an unknown or already-revoked token is not an error."""
    async with SessionLocal() as session, session.begin():
        row = (
            await session.execute(
                text("SELECT * FROM auth_refresh_token(:h)"), {"h": hash_refresh(token)}
            )
        ).one_or_none()
        if row is not None:
            await set_tenant(session, row.tenant_id)
            await _revoke_family(session, row.family_id)


async def _revoke_family(session: AsyncSession, family_id: UUID) -> None:
    await session.execute(
        text(
            "UPDATE refresh_tokens SET revoked_at = now()"
            " WHERE family_id = :f AND revoked_at IS NULL"
        ),
        {"f": family_id},
    )


async def _issue_pair(
    session: AsyncSession, user_id: UUID, tenant_id: UUID, role: str, family_id: UUID
) -> dict[str, Any]:
    token, token_hash = new_refresh()
    await session.execute(
        text(
            "INSERT INTO refresh_tokens (user_id, family_id, token_hash, expires_at)"
            " VALUES (:u, :f, :h, :e)"
        ),
        {"u": user_id, "f": family_id, "h": token_hash, "e": datetime.now(UTC) + REFRESH_TTL},
    )
    return {
        "access_token": issue_access(user_id, tenant_id, role),
        "refresh_token": token,
        "token_type": "bearer",
        "expires_in": int(ACCESS_TTL.total_seconds()),
    }


def current_claims(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> dict[str, Any]:
    if credentials is None:
        raise Problem(401, "Missing bearer token.", _UNAUTHORIZED)
    try:
        return decode_access(credentials.credentials)
    except jwt.InvalidTokenError:
        raise Problem(401, "Invalid or expired token.", _UNAUTHORIZED) from None


Claims = Annotated[dict[str, Any], Depends(current_claims)]


async def tenant_session(claims: Claims) -> AsyncIterator[AsyncSession]:
    """One transaction per request, scoped to the token's tenant. Commit on success,
    rollback on error."""
    async with SessionLocal() as session, session.begin():
        await set_tenant(session, UUID(claims["tid"]))
        yield session


# scope="function": commit before the response is sent, so a failed commit is never a 2xx.
TenantSession = Annotated[AsyncSession, Depends(tenant_session, scope="function")]
