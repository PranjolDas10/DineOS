"""Adapter for the Uber Eats Marketplace API. The only module that talks to Uber: tests replace
`get_order` and `accept_order`, so CI never calls the real API.

Contract, from developer.uber.com (Eats webhooks guide, orders.notification reference,
GET /v2/eats/order/{order_id}):
- Webhooks carry an X-Uber-Signature header: lowercase hex HMAC-SHA256 of the raw body,
  keyed with the app's client secret.
- An order webhook carries only the order id; the order itself is fetched with
  GET /v2/eats/order/{order_id} using a client-credentials token (scope eats.order).
- Money is {"amount": <int, smallest currency unit>, "currency_code": ..}.
- A new order must be accepted within 11.5 minutes or Uber cancels it.
Sandbox-verify before go-live: the tip path and the accept endpoint's body.
"""

import hashlib
import hmac
import time
from typing import Any

import httpx

from app.config import settings

TIMEOUT = httpx.Timeout(10.0)
_token: tuple[str, float] | None = None  # (access token, monotonic expiry)


def verify_signature(body: bytes, signature: str | None, secret: str) -> bool:
    """Constant-time compare, so the check can't leak how much of a forged signature matched."""
    if not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


def _credentials() -> tuple[str, str]:
    if not (settings.uber_eats_client_id and settings.uber_eats_client_secret):
        raise RuntimeError("UBER_EATS_CLIENT_ID / UBER_EATS_CLIENT_SECRET are not set")
    return settings.uber_eats_client_id, settings.uber_eats_client_secret


async def _access_token(client: httpx.AsyncClient) -> str:
    """Client-credentials token, cached until a minute before it expires. ponytail: per
    process; with N workers that is N token requests an hour, well inside Uber's limits."""
    global _token
    if _token and time.monotonic() < _token[1]:
        return _token[0]
    client_id, secret = _credentials()
    resp = await client.post(
        settings.uber_eats_auth_url,
        data={
            "client_id": client_id,
            "client_secret": secret,
            "grant_type": "client_credentials",
            "scope": "eats.order",
        },
    )
    resp.raise_for_status()
    body = resp.json()
    _token = (body["access_token"], time.monotonic() + int(body["expires_in"]) - 60)
    return _token[0]


async def _request(method: str, path: str, json: dict[str, Any] | None = None) -> httpx.Response:
    """Transient failures (network, 429, 5xx) raise, so the job queue retries with backoff."""
    async with httpx.AsyncClient(base_url=settings.uber_eats_api_url, timeout=TIMEOUT) as client:
        token = await _access_token(client)
        resp = await client.request(
            method, path, json=json, headers={"Authorization": f"Bearer {token}"}
        )
        if resp.status_code == 401:  # token revoked early: drop it, the retry gets a new one
            global _token
            _token = None
        resp.raise_for_status()
        return resp


async def get_order(order_id: str) -> dict[str, Any]:
    order: dict[str, Any] = (await _request("GET", f"/v2/eats/order/{order_id}")).json()
    return order


async def accept_order(order_id: str) -> None:
    await _request(
        "POST", f"/v1/eats/orders/{order_id}/accept_pos_order", json={"reason": "accepted"}
    )
