"""Delivery-platform integrations: store mapping, webhook intake, order sync.

Why a webhook is only a trigger: Uber Eats retries unacknowledged webhooks and does not
guarantee their order, so an "order updated" webhook can arrive after a newer one. Applying
webhook contents would let an old version overwrite a new one. Instead each webhook enqueues
a sync job, and the job fetches the order's *current* state from Uber and ingests that.

Why that is enough: sync jobs for one order run one at a time (a transaction-scoped advisory
lock on the order id), and each one reads the latest state at the moment it runs. So the
snapshots are applied in the order they were fetched, each at least as new as the last, and
the order inbox's own rule (a newer event id wins, see orders/service.py) never sees them out
of order. Duplicate webhooks are dropped by event id before any work is queued.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import jobs
from app.api import Problem
from app.config import settings
from app.db import SessionLocal, set_tenant
from app.integrations import uber_eats
from app.menu import service as menu
from app.orders import service as orders

log = logging.getLogger(__name__)

SOURCE = "uber_eats"  # order_events.source for orders that came from Uber's API
CHANNEL = "ubereats"  # same channel name the CSV exports use, so reports group them together
ORDER_EVENTS = {"orders.notification", "orders.cancel", "orders.failure"}
CANCELLED_STATES = {"DENIED", "CANCELED"}


def _cents(money: Any) -> int:
    """Uber money is {"amount": int in the smallest unit, ...}; absent means zero."""
    return int(money["amount"]) if isinstance(money, dict) and "amount" in money else 0


def to_order_payload(order: dict[str, Any]) -> dict[str, Any]:
    """Uber order -> the inbox's canonical order payload (see orders/parsing.py Order.payload).
    Raises KeyError/ValueError on a malformed order, which fails the job loudly."""
    charges = (order.get("payment") or {}).get("charges") or {}
    cart_charges = (order.get("cart") or {}).get("charges") or {}
    items = []
    for item in (order.get("cart") or {}).get("items") or []:
        quantity = int(item["quantity"])
        price = item.get("price") or {}
        unit = _cents(price.get("unit_price"))
        total = _cents(price.get("total_price")) if "total_price" in price else unit * quantity
        items.append(
            {
                "name": item["title"],
                "quantity": str(quantity),
                "unit_price_cents": unit,
                "line_total_cents": total,
            }
        )
    payload: dict[str, Any] = {
        "external_id": order["id"],
        "channel": CHANNEL,
        "placed_at": _utc_iso(order["placed_at"]),
        "tax_cents": _cents(charges.get("tax")),
        "tip_cents": _cents(charges.get("tip") or cart_charges.get("tip")),
        "items": items,
    }
    if order.get("current_state") in CANCELLED_STATES:
        payload["status"] = "cancelled"  # only when cancelled: see project() in orders/service.py
    return payload


def _utc_iso(value: str) -> str:
    placed = datetime.fromisoformat(value)
    if placed.tzinfo is None:
        raise ValueError(f"placed_at without a UTC offset: {value!r}")
    return placed.astimezone(UTC).isoformat()


async def receive_uber_eats(body: bytes, signature: str | None) -> None:
    """Verify, deduplicate and queue. Answers fast: Uber retries anything that isn't a 200."""
    secret = settings.uber_eats_client_secret
    if not secret:
        raise Problem(503, "Uber Eats is not configured on this server.")
    if not uber_eats.verify_signature(body, signature, secret):
        raise Problem(401, "Invalid webhook signature.")
    try:
        event = json.loads(body)
    except ValueError:
        raise Problem(400, "Body is not JSON.") from None
    event_type = event.get("event_type")
    if event_type not in ORDER_EVENTS:
        return  # store status and other events: acknowledged, not used
    meta = event.get("meta") or {}
    event_id, store_id, order_id = (
        event.get("event_id"),
        meta.get("user_id"),
        meta.get("resource_id"),
    )
    if not all(isinstance(v, str) and v for v in (event_id, store_id, order_id)):
        raise Problem(400, "Webhook is missing event_id, meta.user_id or meta.resource_id.")

    async with SessionLocal() as session, session.begin():
        found = (
            await session.execute(
                text("SELECT tenant_id, auto_accept FROM integration_for_store(:p, :s)"),
                {"p": SOURCE, "s": store_id},
            )
        ).one_or_none()
        if found is None:
            # Acknowledge anyway: Uber retrying a store nobody connected can't succeed later.
            log.warning("uber_eats webhook for unknown store %s", store_id)
            return
        await set_tenant(session, found.tenant_id)
        delivery = await session.scalar(
            text(
                "INSERT INTO webhook_deliveries (provider, event_id, event_type, body)"
                " VALUES (:p, :e, :t, CAST(:b AS jsonb))"
                " ON CONFLICT (tenant_id, provider, event_id) DO NOTHING RETURNING id"
            ),
            {"p": SOURCE, "e": event_id, "t": event_type, "b": json.dumps(event)},
        )
        if delivery is None:
            return  # a retry of a webhook we already queued
        await jobs.enqueue(
            session,
            "sync_uber_eats_order",
            {
                "order_id": order_id,
                "accept": event_type == "orders.notification" and found.auto_accept,
            },
            dedupe_key=f"uber_eats_delivery:{delivery}",
        )


@jobs.job("sync_uber_eats_order")
async def sync_uber_eats_order(session: AsyncSession, payload: dict[str, Any]) -> None:
    """Fetch the order's current state and ingest it (see the module docstring for why this
    is safe however webhooks arrive). Safe to run twice: ingest drops an unchanged order, and
    the order is accepted only while Uber still says CREATED."""
    order_id = payload["order_id"]
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"{SOURCE}:{order_id}"},
    )
    order = await uber_eats.get_order(order_id)
    canonical = to_order_payload(order)
    menu_ids = await menu.menu_item_ids_by_name(session, {i["name"] for i in canonical["items"]})
    await orders.ingest(session, SOURCE, canonical, None, menu_ids)
    if payload.get("accept") and order.get("current_state") == "CREATED":
        # Last, so a failed ingest never accepts an order we didn't record. If the commit
        # fails after this, the retry refetches, sees ACCEPTED and doesn't accept again.
        await uber_eats.accept_order(order_id)


async def list_integrations(session: AsyncSession) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            "SELECT id, provider, external_store_id, auto_accept, created_at"
            " FROM integrations ORDER BY id"
        )
    )
    return [dict(r._mapping) for r in rows]


async def connect(
    session: AsyncSession, provider: str, external_store_id: str, auto_accept: bool
) -> dict[str, Any]:
    """Idempotent: connecting the same store again returns the existing connection."""
    if provider != SOURCE:
        raise Problem(422, f"Unknown provider; supported: {SOURCE}.")
    cols = "id, provider, external_store_id, auto_accept, created_at"
    row = (
        await session.execute(
            text(
                "INSERT INTO integrations (provider, external_store_id, auto_accept)"
                " VALUES (:p, :s, :a) ON CONFLICT (provider, external_store_id) DO NOTHING"
                f" RETURNING {cols}"
            ),
            {"p": provider, "s": external_store_id, "a": auto_accept},
        )
    ).one_or_none()
    if row is None:
        row = (
            await session.execute(
                text(
                    f"SELECT {cols} FROM integrations"
                    " WHERE provider = :p AND external_store_id = :s"
                ),
                {"p": provider, "s": external_store_id},
            )
        ).one_or_none()
        if row is None:  # the store exists but RLS hides it: another restaurant owns it
            raise Problem(409, "This store is already connected to another restaurant.")
    return dict(row._mapping)


async def disconnect(session: AsyncSession, integration_id: UUID) -> None:
    result = await session.execute(
        text("DELETE FROM integrations WHERE id = :i RETURNING id"), {"i": integration_id}
    )
    if result.first() is None:
        raise Problem(404, "Integration not found.")
