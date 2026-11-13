"""Profitability ledger: posts every order version as a balanced, append-only transaction and
reports profit by channel and by dish."""

from collections import defaultdict
from datetime import date, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import jobs
from app.ledger.posting import Entry, allocate, reversal_entries, sale_entries
from app.menu import service as menu
from app.orders import service as orders
from app.scheduling import service as scheduling


async def _post(
    session: AsyncSession,
    kind: str,
    key: str,
    order_id: UUID,
    business_date: date,
    channel: str,
    entries: list[Entry],
    food_cost_complete: bool = True,
    reverses_id: UUID | None = None,
) -> None:
    txn_id = await session.scalar(
        text(
            "INSERT INTO ledger_transactions"
            " (kind, idempotency_key, order_id, business_date, reverses_id, food_cost_complete)"
            " VALUES (:k, :key, :o, :d, :r, :c) RETURNING id"
        ),
        {
            "k": kind,
            "key": key,
            "o": order_id,
            "d": business_date,
            "r": reverses_id,
            "c": food_cost_complete,
        },
    )
    await session.execute(
        text(
            "INSERT INTO ledger_entries"
            " (transaction_id, account, amount_cents, channel, menu_item_id)"
            " VALUES (:t, :a, :amt, :ch, :m)"
        ),
        [
            {"t": txn_id, "a": e.account, "amt": e.amount_cents, "ch": channel, "m": e.menu_item_id}
            for e in entries
        ],
    )


@jobs.job("post_order")
async def post_order(session: AsyncSession, payload: dict[str, Any]) -> None:
    """Post the order's current version. If an earlier version was posted, reverse it first,
    so the books always net to the latest version. Idempotent by version (event id)."""
    order = await orders.order_for_posting(session, UUID(payload["order_id"]))
    if order is None:
        return
    key = f"sale:{order['event_id']}"
    if await session.scalar(
        text("SELECT 1 FROM ledger_transactions WHERE idempotency_key = :k"), {"k": key}
    ):
        return  # this version is already in the books

    previous = (
        await session.execute(
            text(
                "SELECT s.id, s.business_date, e.channel FROM ledger_transactions s"
                " JOIN ledger_entries e ON e.transaction_id = s.id"
                " WHERE s.order_id = :o AND s.kind = 'sale' AND NOT EXISTS"
                " (SELECT 1 FROM ledger_transactions r WHERE r.reverses_id = s.id)"
                " ORDER BY s.id DESC LIMIT 1"
            ),
            {"o": order["id"]},
        )
    ).one_or_none()
    if previous is not None:
        rows = await session.execute(
            text(
                "SELECT account, amount_cents, menu_item_id FROM ledger_entries"
                " WHERE transaction_id = :t"
            ),
            {"t": previous.id},
        )
        # Dated like the original sale, so that day's profit is corrected in place.
        await _post(
            session,
            "reversal",
            f"reversal:{previous.id}",  # unique: a concurrent job can't reverse it twice
            order["id"],
            previous.business_date,
            previous.channel,
            reversal_entries([Entry(a, amt, m) for a, amt, m in rows]),
            reverses_id=previous.id,
        )

    tz = ZoneInfo(await session.scalar(text("SELECT timezone FROM tenants")))
    bps = await session.scalar(
        text("SELECT commission_bps FROM channel_fees WHERE channel = :c"), {"c": order["channel"]}
    )
    entries, complete = sale_entries(order, bps or 0, await menu.portion_costs(session))
    await _post(
        session,
        "sale",
        key,
        order["id"],
        order["placed_at"].astimezone(tz).date(),
        order["channel"],
        entries,
        food_cost_complete=complete,
    )


async def profit_report(session: AsyncSession, first: date, last: date) -> dict[str, Any]:
    """Profit by channel and by dish for local business days [first, last].
    Labor comes from the schedule and is allocated to channels by their share of revenue."""
    rows = await session.execute(
        text(
            "SELECT t.business_date, e.channel, e.account, e.menu_item_id,"
            " sum(e.amount_cents) AS cents"
            " FROM ledger_entries e JOIN ledger_transactions t ON t.id = e.transaction_id"
            " WHERE t.business_date BETWEEN :a AND :b"
            " GROUP BY t.business_date, e.channel, e.account, e.menu_item_id"
        ),
        {"a": first, "b": last},
    )
    by_channel: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    by_dish: dict[UUID | None, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    by_day: dict[date, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for day, channel, account, menu_item_id, amount in rows:
        by_channel[channel][account] += int(amount)
        by_day[day][account] += int(amount)
        if account in ("revenue", "food_cost"):
            by_dish[menu_item_id][account] += int(amount)

    channels = sorted(by_channel)
    revenue = [-by_channel[c]["revenue"] for c in channels]  # credits are negative
    labor_report = await scheduling.labor_report(session, first, last)
    labor = labor_report["total_labor_cents"]
    labor_by_day = {d["date"]: d["labor_cents"] for d in labor_report["days"]}
    labor_parts = allocate(labor, revenue)
    names = await menu.menu_item_names(session)
    incomplete = await session.scalar(
        text(
            "SELECT count(*) FROM ledger_transactions s WHERE s.kind = 'sale'"
            " AND NOT s.food_cost_complete AND s.business_date BETWEEN :a AND :b"
            " AND NOT EXISTS (SELECT 1 FROM ledger_transactions r WHERE r.reverses_id = s.id)"
        ),
        {"a": first, "b": last},
    )

    def row(rev: int, commission: int, food: int, labor_cents: int | None) -> dict[str, Any]:
        gross = rev - commission - food
        return {
            "revenue_cents": rev,
            "commission_cents": commission,
            "food_cost_cents": food,
            "gross_profit_cents": gross,
            **(
                {"labor_cents": labor_cents, "profit_cents": gross - labor_cents}
                if labor_cents is not None
                else {}
            ),
        }

    return {
        "labor_cents": labor,
        "sales_with_unknown_food_cost": incomplete,
        # Every day in the range, quiet days included, so a chart has no gaps.
        "daily": [
            {
                "date": day,
                **row(
                    -by_day[day]["revenue"],
                    by_day[day]["platform_commission"],
                    by_day[day]["food_cost"],
                    labor_by_day.get(day, 0),
                ),
            }
            for day in (first + timedelta(days=n) for n in range((last - first).days + 1))
        ],
        "channels": [
            {
                "channel": c,
                **row(rev, by_channel[c]["platform_commission"], by_channel[c]["food_cost"], part),
            }
            for c, rev, part in zip(channels, revenue, labor_parts, strict=True)
        ],
        "dishes": sorted(
            (
                {
                    "menu_item_id": m,
                    "name": names.get(m, "Unmapped items") if m else "Unmapped items",
                    **row(-d["revenue"], 0, d["food_cost"], None),
                }
                for m, d in by_dish.items()
            ),
            key=lambda d: -d["gross_profit_cents"],
        ),
    }
