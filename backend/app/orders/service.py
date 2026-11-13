"""Order inbox: idempotent ingestion of POS / delivery-platform sales exports.

Four layers make re-imports and retries harmless:
1. A retried POST /v1/imports with the same id enqueues nothing new.
2. order_events is unique on (source, external_id, content hash): an order seen before with
   the same content is a duplicate, stored once.
3. The order projection only moves forward: an event older than the one already applied
   (by event id, which is time-ordered) can't overwrite a newer version.
4. Every job is safe to run twice, because 2 and 3 hold inside it.
"""

import asyncio
import hashlib
import json
import uuid
from collections import Counter
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, insert, literal_column, select, text
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud, jobs, storage
from app.api import Problem
from app.menu import service as menu
from app.orders import parsing
from app.orders.models import Order, OrderEvent, OrderItem, SalesImport


def new_object_key(tenant_id: str) -> str:
    return f"{tenant_id}/imports/{uuid.uuid4()}.csv"


async def create_import(
    session: AsyncSession, tenant_id: str, values: dict[str, Any]
) -> SalesImport:
    if values["source"] not in parsing.PROFILES:
        raise Problem(422, f"Unknown source; supported: {', '.join(parsing.PROFILES)}.")
    if not values["object_key"].startswith(f"{tenant_id}/imports/"):
        raise Problem(422, "object_key must come from POST /v1/imports/upload-url.")
    if "id" in values and (existing := await session.get(SalesImport, values["id"])):
        return existing  # retried request: don't import twice
    row = await crud.create(session, SalesImport, values)
    await jobs.enqueue(session, "import_sales", {"import_id": str(row.id)})
    return row


@jobs.job("import_sales")
async def import_sales(session: AsyncSession, payload: dict[str, Any]) -> None:
    imp = await session.get(SalesImport, UUID(payload["import_id"]))
    if imp is None or imp.status != "uploaded":
        return
    raw = await asyncio.to_thread(storage.get_bytes, imp.object_key)
    tz = ZoneInfo(await session.scalar(text("SELECT timezone FROM tenants")))
    try:
        # utf-8-sig: files saved from Excel start with a byte-order mark.
        orders = parsing.parse_sales(raw.decode("utf-8-sig"), imp.source, tz)
    except (parsing.SalesFileError, UnicodeDecodeError) as exc:
        imp.status, imp.error = "failed", str(exc)[:2000]  # permanent: retrying won't fix the file
        return

    names = {item.name for order in orders for item in order.items}
    menu_ids = await menu.menu_item_ids_by_name(session, names)
    counts: Counter[str] = Counter()
    for order in orders:
        counts[await ingest(session, imp.source, order.payload(), imp.id, menu_ids)] += 1
    imp.status, imp.error = "imported", None
    imp.orders_new, imp.orders_updated = counts["new"], counts["updated"]
    imp.duplicates = counts["duplicate"] + counts["stale"]


async def ingest(
    session: AsyncSession,
    source: str,
    payload: dict[str, Any],
    import_id: UUID | None,
    menu_ids: dict[str, UUID],
) -> str:
    """Store one order version as an event and project it. Returns new / updated /
    duplicate (same content seen before) / stale (an older version than the current one)."""
    body = json.dumps(payload, sort_keys=True).encode()
    event_id = await session.scalar(
        pg_insert(OrderEvent)
        .values(
            source=source,
            external_id=payload["external_id"],
            content_sha256=hashlib.sha256(body).digest(),
            payload=payload,
            import_id=import_id,
        )
        .on_conflict_do_nothing()
        .returning(OrderEvent.id)
    )
    if event_id is None:
        return "duplicate"
    return await project(session, source, payload, event_id, menu_ids)


async def project(
    session: AsyncSession,
    source: str,
    payload: dict[str, Any],
    event_id: UUID,
    menu_ids: dict[str, UUID],
    force: bool = False,
) -> str:
    """Upsert the order from an event. Only moves forward (newer event id wins) unless
    force (replay). Order ids stay stable, so anything referencing an order survives."""
    items = payload["items"]
    subtotal = sum(i["line_total_cents"] for i in items)
    values = {
        "source": source,
        "external_id": payload["external_id"],
        "channel": payload["channel"],
        "placed_at": datetime.fromisoformat(payload["placed_at"]),
        "subtotal_cents": subtotal,
        "tax_cents": payload["tax_cents"],
        "tip_cents": payload["tip_cents"],
        "total_cents": subtotal + payload["tax_cents"] + payload["tip_cents"],
        "event_id": event_id,
    }
    stmt = pg_insert(Order).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["tenant_id", "source", "external_id"],
        set_={**{k: stmt.excluded[k] for k in values}, "updated_at": literal_column("now()")},
        where=None if force else Order.event_id < stmt.excluded.event_id,
    )
    # xmax = 0 only for a freshly inserted row: tells "new" from "updated" in one round trip.
    row = (
        (await session.execute(stmt.returning(Order.id, literal_column("xmax = 0").label("new"))))
        .mappings()
        .one_or_none()
    )
    if row is None:
        return "stale"
    order_id: UUID = row["id"]
    await session.execute(delete(OrderItem).where(OrderItem.order_id == order_id))
    if items:
        await session.execute(
            insert(OrderItem),
            [
                {
                    "order_id": order_id,
                    "position": n,
                    "name": i["name"],
                    "menu_item_id": menu_ids.get(i["name"].lower()),
                    "quantity": i["quantity"],
                    "unit_price_cents": i["unit_price_cents"],
                    "line_total_cents": i["line_total_cents"],
                }
                for n, i in enumerate(items)
            ],
        )
    # Outbox: posting to the ledger is enqueued in the same transaction as the change.
    # One posting job per order version (dedupe), so replays and retries never double-post.
    await jobs.enqueue(
        session, "post_order", {"order_id": str(order_id)}, dedupe_key=f"post_order:{event_id}"
    )
    return "new" if row["new"] else "updated"


@jobs.job("replay_orders")
async def replay_orders(session: AsyncSession, payload: dict[str, Any]) -> None:
    """Rebuild every order from its latest event (e.g. after a projection bug fix or after
    menu items were renamed, to re-map sold items). Idempotent."""
    latest = (
        await session.execute(
            select(OrderEvent.id, OrderEvent.source, OrderEvent.payload)
            .ext(distinct_on(OrderEvent.source, OrderEvent.external_id))
            .order_by(OrderEvent.source, OrderEvent.external_id, OrderEvent.id.desc())
        )
    ).all()
    names = {i["name"] for _, _, p in latest for i in p["items"]}
    menu_ids = await menu.menu_item_ids_by_name(session, names)
    for event_id, source, event_payload in latest:
        await project(session, source, event_payload, event_id, menu_ids, force=True)


async def order_for_posting(session: AsyncSession, order_id: UUID) -> dict[str, Any] | None:
    """Public read for the ledger: the order's current version with its items."""
    order = await session.get(Order, order_id)
    if order is None:
        return None
    items = await session.scalars(
        select(OrderItem).where(OrderItem.order_id == order_id).order_by(OrderItem.position)
    )
    return {
        "id": order.id,
        "event_id": order.event_id,
        "channel": order.channel,
        "placed_at": order.placed_at,
        "subtotal_cents": order.subtotal_cents,
        "tax_cents": order.tax_cents,
        "tip_cents": order.tip_cents,
        "total_cents": order.total_cents,
        "items": [
            {
                "menu_item_id": i.menu_item_id,
                "quantity": i.quantity,
                "line_total_cents": i.line_total_cents,
            }
            for i in items
        ],
    }


async def units_sold(session: AsyncSession, since: datetime) -> dict[UUID, Decimal]:
    """Public read: how many of each menu item sold since a moment (mapped items only)."""
    rows = await session.execute(
        select(OrderItem.menu_item_id, func.sum(OrderItem.quantity))
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.placed_at >= since, OrderItem.menu_item_id.is_not(None))
        .group_by(OrderItem.menu_item_id)
    )
    return {menu_item_id: qty for menu_item_id, qty in rows}
