"""Token primitives. Access tokens are stateless JWTs; refresh tokens are opaque random strings."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt

from app.config import settings

ACCESS_TTL = timedelta(minutes=15)
REFRESH_TTL = timedelta(days=30)
_ALGORITHM = "HS256"


def issue_access(user_id: UUID, tenant_id: UUID, role: str) -> str:
    """Short-lived: a stolen access token is useful for at most ACCESS_TTL, with no DB lookup."""
    now = datetime.now(UTC)
    claims = {"sub": str(user_id), "tid": str(tenant_id), "role": role, "iat": now}
    return jwt.encode({**claims, "exp": now + ACCESS_TTL}, settings.jwt_secret, _ALGORITHM)


def decode_access(token: str) -> dict[str, Any]:
    """Raises jwt.InvalidTokenError on a bad signature, expiry or missing claim."""
    # algorithms is pinned: never let the token's own header pick it (the "alg: none" attack).
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[_ALGORITHM],
        options={"require": ["exp", "sub", "tid", "role"]},
    )


def new_refresh() -> tuple[str, bytes]:
    """(token for the client, hash to store). 256 random bits, so a fast hash is enough:
    slow hashes like argon2 protect low-entropy passwords from guessing, not random tokens."""
    token = secrets.token_urlsafe(32)
    return token, hash_refresh(token)


def hash_refresh(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()
