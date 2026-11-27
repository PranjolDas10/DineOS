"""Uber Eats: signed webhooks, dedup, sync from the platform's current state, accept, cancel."""

import hashlib
import hmac
import json
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app import jobs
from app.config import settings
from app.db import SessionLocal, set_tenant
from app.integrations import service, uber_eats
from tests.conftest import MakeTenant, auth_headers

pytestmark = pytest.mark.anyio
SECRET = "test-uber-client-secret"
URL = "/v1/webhooks/uber-eats"


def order(state: str = "CREATED", order_id: str = "ue-1") -> dict[str, Any]:
    """Shape of GET /v2/eats/order/{id}, trimmed to the fields we read."""
    usd = lambda cents: {"amount": cents, "currency_code": "USD"}  # noqa: E731
    return {
        "id": order_id,
        "current_state": state,
        "placed_at": "2026-11-20T19:05:00-05:00",
        "cart": {
            "items": [
                {
                    "title": "Butter Chicken",
                    "quantity": 2,
                    "price": {"unit_price": usd(1799), "total_price": usd(3598)},
                },
                {"title": "Garlic Naan", "quantity": 1, "price": {"unit_price": usd(399)}},
            ]
        },
        "payment": {"charges": {"tax": usd(315), "tip": usd(500)}},
    }


def test_maps_an_uber_order_to_the_inbox_payload() -> None:
    payload = service.to_order_payload(order())
    assert payload == {
        "external_id": "ue-1",
        "channel": "ubereats",
        "placed_at": "2026-11-21T00:05:00+00:00",  # stored in UTC
        "tax_cents": 315,
        "tip_cents": 500,
        "items": [
            {
                "name": "Butter Chicken",
                "quantity": "2",
                "unit_price_cents": 1799,
                "line_total_cents": 3598,
            },
            {
                "name": "Garlic Naan",
                "quantity": "1",
                "unit_price_cents": 399,
                "line_total_cents": 399,
            },
        ],
    }
    assert "status" not in payload  # absent = completed, same hash rule as CSV orders
    assert service.to_order_payload(order("CANCELED"))["status"] == "cancelled"
    assert service.to_order_payload(order("DENIED"))["status"] == "cancelled"


def test_signature_is_hmac_sha256_hex_of_the_raw_body() -> None:
    body = b'{"a":1}'
    good = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    assert uber_eats.verify_signature(body, good, SECRET)
    assert uber_eats.verify_signature(body, good.upper(), SECRET)  # header case doesn't matter
    assert not uber_eats.verify_signature(body + b" ", good, SECRET)
    assert not uber_eats.verify_signature(body, None, SECRET)


def webhook(
    event_type: str, event_id: str, store: str = "store-1", order_id: str = "ue-1"
) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(
        {
            "event_type": event_type,
            "event_id": event_id,
            "event_time": 1763683500,
            "meta": {"resource_id": order_id, "user_id": store, "status": "pos"},
            "resource_href": f"https://api.uber.com/v2/eats/order/{order_id}",
        }
    ).encode()
    sig = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return body, {"X-Uber-Signature": sig, "Content-Type": "application/json"}


class FakeUber:
    """Stands in for Uber: holds each order's current state and records accepts."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.orders: dict[str, dict[str, Any]] = {}
        self.accepted: list[str] = []
        monkeypatch.setattr(settings, "uber_eats_client_secret", SECRET)
        monkeypatch.setattr(uber_eats, "get_order", self.get_order)
        monkeypatch.setattr(uber_eats, "accept_order", self.accept_order)

    async def get_order(self, order_id: str) -> dict[str, Any]:
        return self.orders[order_id]

    async def accept_order(self, order_id: str) -> None:
        self.accepted.append(order_id)
        self.orders[order_id] = {**self.orders[order_id], "current_state": "ACCEPTED"}


@pytest.fixture
def uber(monkeypatch: pytest.MonkeyPatch) -> FakeUber:
    return FakeUber(monkeypatch)


@pytest.fixture
async def store(client: AsyncClient, make_tenant: MakeTenant) -> UUID:
    tenant_id = await make_tenant()
    resp = await client.post(
        "/v1/integrations",
        json={"provider": "uber_eats", "external_store_id": "store-1"},
        headers=auth_headers(tenant_id),
    )
    assert resp.status_code == 201, resp.text
    return tenant_id


async def drain() -> None:
    while await jobs.run_once(["sync_uber_eats_order", "post_order"]) is not None:
        pass


async def tenant_rows(tenant_id: UUID, sql: str) -> list[Any]:
    async with SessionLocal() as session, session.begin():
        await set_tenant(session, tenant_id)
        return list(await session.execute(text(sql)))


async def test_rejects_a_bad_signature(client: AsyncClient, uber: FakeUber, store: UUID) -> None:
    body, headers = webhook("orders.notification", "ev-1")
    resp = await client.post(URL, content=body, headers={**headers, "X-Uber-Signature": "00" * 32})
    assert resp.status_code == 401
    assert await tenant_rows(store, "SELECT 1 FROM webhook_deliveries") == []


async def test_new_order_is_recorded_posted_and_accepted_once(
    client: AsyncClient, uber: FakeUber, store: UUID
) -> None:
    uber.orders["ue-1"] = order()
    body, headers = webhook("orders.notification", "ev-1")
    for _ in range(3):  # Uber retries until it sees a 200: one delivery, one job
        assert (await client.post(URL, content=body, headers=headers)).status_code == 200
    assert (
        len(await tenant_rows(store, "SELECT 1 FROM jobs WHERE kind = 'sync_uber_eats_order'")) == 1
    )
    await drain()

    rows = await tenant_rows(store, "SELECT source, channel, status, total_cents FROM orders")
    assert [tuple(r) for r in rows] == [("uber_eats", "ubereats", "completed", 3997 + 315 + 500)]
    assert uber.accepted == ["ue-1"]
    kinds = await tenant_rows(store, "SELECT kind FROM ledger_transactions ORDER BY id")
    assert [k for (k,) in kinds] == ["sale"]

    # A late, duplicate-looking notification with a new event id: synced again, not re-accepted.
    body, headers = webhook("orders.notification", "ev-2")
    await client.post(URL, content=body, headers=headers)
    await drain()
    assert uber.accepted == ["ue-1"]
    assert len(await tenant_rows(store, "SELECT 1 FROM orders")) == 1


async def test_cancel_reverses_the_sale_even_if_an_old_webhook_arrives_last(
    client: AsyncClient, uber: FakeUber, store: UUID
) -> None:
    uber.orders["ue-1"] = order()
    await client.post(
        URL,
        content=webhook("orders.notification", "ev-1")[0],
        headers=webhook("orders.notification", "ev-1")[1],
    )
    await drain()

    uber.orders["ue-1"] = order("CANCELED")
    for event_type, event_id in (("orders.cancel", "ev-3"), ("orders.notification", "ev-2")):
        body, headers = webhook(event_type, event_id)  # ev-2 is older but delivered last
        await client.post(URL, content=body, headers=headers)
    await drain()

    rows = await tenant_rows(store, "SELECT status FROM orders")
    assert [s for (s,) in rows] == ["cancelled"]  # the stale webhook didn't resurrect it
    kinds = await tenant_rows(store, "SELECT kind FROM ledger_transactions ORDER BY id")
    assert [k for (k,) in kinds] == ["sale", "reversal"]
    total = await tenant_rows(store, "SELECT coalesce(sum(amount_cents), 0) FROM ledger_entries")
    assert total[0][0] == 0
    assert uber.accepted == ["ue-1"]


async def test_unknown_store_and_other_events_are_acknowledged_and_ignored(
    client: AsyncClient, uber: FakeUber, store: UUID
) -> None:
    body, headers = webhook("orders.notification", "ev-9", store="someone-else")
    assert (await client.post(URL, content=body, headers=headers)).status_code == 200
    body, headers = webhook("store.status.changed", "ev-10")
    assert (await client.post(URL, content=body, headers=headers)).status_code == 200
    assert await tenant_rows(store, "SELECT 1 FROM webhook_deliveries") == []


async def test_a_store_belongs_to_one_restaurant(
    client: AsyncClient, make_tenant: MakeTenant, store: UUID
) -> None:
    again = await client.post(
        "/v1/integrations",
        json={"provider": "uber_eats", "external_store_id": "store-1"},
        headers=auth_headers(store),
    )
    assert again.status_code == 201  # idempotent for its owner
    other = await client.post(
        "/v1/integrations",
        json={"provider": "uber_eats", "external_store_id": "store-1"},
        headers=auth_headers(await make_tenant()),
    )
    assert other.status_code == 409
