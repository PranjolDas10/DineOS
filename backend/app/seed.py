"""Seed a demo restaurant with fake data, for the web dashboard and the public demo.

    uv run python -m app.seed            # demo@dineos.dev / DINEOS_PASSWORD (default below)
    docker compose run --rm migrate python -m app.seed

Everything here is invented sample data, never real restaurant numbers. Dates are relative to
today, so the demo shows the last four weeks as of the day it was seeded. Refuses to run twice
for the same email unless --reset is given, which deletes the demo restaurant first (the public
demo reseeds nightly so its "last 7 days" never goes empty).
"""

import asyncio
import os
import random
import sys
import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app import jobs, storage
from app.auth.cli import create_owner
from app.auth.tokens import issue_access
from app.config import MigrationSettings
from app.db import SessionLocal, set_tenant
from app.ledger import service as _ledger  # noqa: F401  (registers the post_order job)
from app.main import app
from app.menu import service as menu
from app.orders import service as orders

EMAIL = "demo@dineos.dev"
TZ = "America/New_York"
DAYS = 28

# name: (base_unit, pack_qty, pack_price_cents)
INGREDIENTS = {
    "Chicken thigh": ("g", 10000, 10560),
    "Lamb shoulder": ("g", 5000, 14080),
    "Paneer": ("g", 2000, 4180),
    "Onion": ("g", 22680, 5720),
    "Tomato puree": ("g", 3000, 1140),
    "Butter": ("g", 1000, 2090),
    "Cream": ("ml", 1000, 1360),
    "Yogurt": ("ml", 3780, 1720),
    "Ginger-garlic paste": ("g", 1000, 1540),
    "Garam masala": ("g", 500, 2530),
    "Chickpeas": ("g", 2500, 900),
    "Spinach": ("g", 2500, 1980),
    "Flour": ("g", 22680, 4180),
    "Basmati rice": ("g", 9072, 4620),
    "Mango pulp": ("ml", 850, 990),
}
# Supplier prices that moved since: name -> (days ago, new pack_price_cents). The menu costs
# page shows what each did to the dishes that use it.
PRICE_MOVES = {
    "Lamb shoulder": (16, 15490),  # +10%
    "Paneer": (11, 4520),  # +8%
    "Butter": (8, 2490),  # +19%
    "Chicken thigh": (5, 11400),  # +8%
    "Onion": (3, 5150),  # -10%
}
# name: (yield_qty, yield_unit, [(ingredient or sub-recipe, qty)]); sub-recipes come first
RECIPES: dict[str, tuple[int, str, list[tuple[str, int]]]] = {
    "Onion masala": (
        1000,
        "g",
        [
            ("Onion", 1200),
            ("Ginger-garlic paste", 100),
            ("Tomato puree", 400),
            ("Garam masala", 20),
        ],
    ),
    "Makhani gravy": (
        5000,
        "g",
        [("Onion masala", 1000), ("Tomato puree", 3000), ("Butter", 250), ("Cream", 500)],
    ),
    "Butter chicken": (1, "each", [("Chicken thigh", 240), ("Makhani gravy", 260), ("Cream", 30)]),
    "Paneer makhani": (1, "each", [("Paneer", 200), ("Makhani gravy", 260), ("Butter", 15)]),
    "Rogan josh": (1, "each", [("Lamb shoulder", 260), ("Onion masala", 150), ("Yogurt", 80)]),
    "Chana masala": (1, "each", [("Chickpeas", 220), ("Onion masala", 140), ("Tomato puree", 80)]),
    "Saag paneer": (1, "each", [("Spinach", 300), ("Paneer", 150), ("Onion masala", 60)]),
    "Garlic naan": (1, "each", [("Flour", 110), ("Butter", 12), ("Ginger-garlic paste", 6)]),
    "Steamed rice": (1, "each", [("Basmati rice", 120)]),
}
# name: (price_cents, recipe or None)
MENU: dict[str, tuple[int, str | None]] = {
    "Butter Chicken": (1799, "Butter chicken"),
    "Paneer Makhani": (1599, "Paneer makhani"),
    "Lamb Rogan Josh": (2199, "Rogan josh"),
    "Chana Masala": (1399, "Chana masala"),
    "Saag Paneer": (1599, "Saag paneer"),
    "Garlic Naan": (399, "Garlic naan"),
    "Basmati Rice": (349, "Steamed rice"),
    "Mango Lassi": (549, None),  # no recipe yet: the dashboard shows its cost as unknown
}
# Weighted mains/sides; "Chef's Special" is not on the menu, so it stays unmapped.
MAINS = ["Butter Chicken"] * 5 + ["Paneer Makhani"] * 3 + ["Lamb Rogan Josh"] * 2
MAINS += ["Chana Masala"] * 2 + ["Saag Paneer"] * 2 + ["Chef's Special"]
SIDES = ["Garlic Naan"] * 4 + ["Basmati Rice"] * 2 + ["Mango Lassi"]
# channel: (orders per weekday, commission bps)
CHANNELS = {"dine_in": (26, 0), "ubereats": (11, 3000), "doordash": (8, 2500)}
# name: (hourly_rate_cents, local (start, end) per day)
STAFF = {
    "Ravi (head cook)": (2400, ("10:30", "21:30")),
    "Meena (line cook)": (2000, ("16:00", "22:00")),
    "Arjun (server)": (1600, ("11:00", "15:00")),
    "Priya (server)": (1600, ("16:30", "22:00")),
    "Sam (dish)": (1500, ("17:00", "22:00")),
}


async def _delete_tenant(conn: AsyncConnection, tenant_id: uuid.UUID) -> None:
    """Delete one tenant and all its rows, as the owner role. Tables are found by their
    tenant_id column and deleted in passes: a table whose rows are still referenced fails its
    foreign key, rolls back to a savepoint and is retried after its children are gone, so there
    is no hand-kept deletion order to forget when a table is added."""
    tables = list(
        await conn.scalars(
            text(
                "SELECT table_name FROM information_schema.columns"
                " WHERE table_schema = 'public' AND column_name = 'tenant_id'"
            )
        )
    )
    while tables:
        blocked = []
        for table in tables:
            try:
                async with conn.begin_nested():
                    await conn.execute(
                        text(f'DELETE FROM "{table}" WHERE tenant_id = :t'), {"t": tenant_id}
                    )
            except IntegrityError:
                blocked.append(table)
        if len(blocked) == len(tables):
            raise RuntimeError(f"Can't delete tenant rows from: {', '.join(blocked)}")
        tables = blocked
    await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})


async def seed(password: str, reset: bool = False) -> None:
    rng = random.Random(7)  # same demo every run
    tz = ZoneInfo(TZ)
    today = datetime.now(tz).date()
    owner = create_async_engine(MigrationSettings().migration_database_url)
    async with owner.begin() as conn:
        existing = await conn.scalar(
            text("SELECT tenant_id FROM users WHERE email = :e"), {"e": EMAIL}
        )
        if existing and not reset:
            raise SystemExit(f"{EMAIL} already exists; pass --reset to reseed the demo.")
        if existing:
            await _delete_tenant(conn, existing)
    await owner.dispose()
    await create_owner("Curry Original (demo)", EMAIL, password, TZ)
    async with SessionLocal() as session:
        tenant = await session.scalar(
            text("SELECT tenant_id FROM auth_user_by_email(:e)"), {"e": EMAIL}
        )

    headers = {"Authorization": f"Bearer {issue_access(uuid.uuid4(), tenant, 'owner')}"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://seed", headers=headers
    ) as api:

        async def call(method: str, url: str, body: Any, **h: str) -> Any:
            resp = await api.request(method, url, json=body, headers=h)
            resp.raise_for_status()
            return resp.json()

        ids: dict[str, str] = {}
        for name, (unit, qty, cents) in INGREDIENTS.items():
            ids[name] = (await call("POST", "/v1/ingredients", {"name": name, "base_unit": unit}))[
                "id"
            ]
            prices = f"/v1/ingredients/{ids[name]}/prices"
            # The starting price predates the demo window; some then move inside it.
            await call(
                "POST",
                prices,
                {"pack_qty": qty, "pack_price_cents": cents, "observed_at": _days_ago(DAYS + 14)},
            )
            if name in PRICE_MOVES:
                ago, moved = PRICE_MOVES[name]
                await call(
                    "POST",
                    prices,
                    {"pack_qty": qty, "pack_price_cents": moved, "observed_at": _days_ago(ago)},
                )
        for name, (yqty, yunit, lines) in RECIPES.items():
            recipe = await call(
                "POST", "/v1/recipes", {"name": name, "yield_qty": yqty, "yield_unit": yunit}
            )
            await call(
                "PUT",
                f"/v1/recipes/{recipe['id']}/lines",
                {
                    "lines": [
                        {
                            "sub_recipe_id" if n in RECIPES else "ingredient_id": ids[n],
                            "qty": str(q),
                        }
                        for n, q in lines
                    ]
                },
                **{"If-Match": '"1"'},
            )
            ids[name] = recipe["id"]
        for name, (price, recipe_name) in MENU.items():
            await call(
                "POST",
                "/v1/menu-items",
                {"name": name, "price_cents": price, "recipe_id": recipe_name and ids[recipe_name]},
            )
        for channel, (_, bps) in CHANNELS.items():
            await call("PUT", f"/v1/channel-fees/{channel}", {"commission_bps": bps})
        for name, (rate, (start, end)) in STAFF.items():
            staff = await call("POST", "/v1/staff", {"name": name, "hourly_rate_cents": rate})
            # Past four weeks plus the week ahead, so the schedule page has a full grid.
            for d in range(-7, DAYS):
                day = today - timedelta(days=d)
                await call(
                    "POST",
                    "/v1/shifts",
                    {
                        "staff_id": staff["id"],
                        "starts_at": _at(day, start, tz),
                        "ends_at": _at(day, end, tz),
                    },
                )

    async with SessionLocal() as session, session.begin():
        await set_tenant(session, tenant)
        menu_ids = await menu.menu_item_ids_by_name(session, set(MENU) | {"Chef's Special"})
        n = 0
        for d in range(DAYS):
            day = today - timedelta(days=d)
            busy = 1.4 if day.weekday() >= 4 else 1.0  # Friday-Sunday
            for channel, (per_day, _) in CHANNELS.items():
                for _ in range(round(per_day * busy * rng.uniform(0.8, 1.2))):
                    n += 1
                    await orders.ingest(
                        session, "dineos", _order(rng, n, channel, day, tz), None, menu_ids
                    )
    while await jobs.run_once(["post_order"]) is not None:
        pass
    await _seed_receipts(tenant, today)
    print(f"Seeded {n} orders over {DAYS} days and {len(RECEIPTS)} receipts. Log in as {EMAIL}.")


# Parsed receipts waiting for review, as if the model had read them: (description, qty, unit,
# total_cents, confidence). Low confidence = "check this" in the review screen.
RECEIPTS: dict[str, tuple[int, int | None, list[tuple[str, str, str, int, str]]]] = {
    # supplier: (days ago, total the model read or None, lines)
    "Restaurant Depot": (
        1,
        None,
        [
            ("Chicken thigh boneless", "40", "lb", 21120, "0.97"),
            ("Onion yellow jumbo", "50", "lb", 5720, "0.95"),
            ("Heavy cream 36%", "4", "l", 5440, "0.92"),
            ("PANR BLK 5LB", "2", "each", 9500, "0.61"),
            ("GHEE 1.6KG", "3", "each", 5397, "0.54"),
            ("Trash bags 42 gal", "1", "case", 2499, "0.93"),
        ],
    ),
    "Patel Brothers": (
        3,
        6150,  # the model read $61.50; the lines add up to $59.50, so the screen flags it
        [
            ("Garam masala", "1", "kg", 4800, "0.96"),
            ("Basmati rice", "20", "lb", 4130, "0.68"),
            ("Ginger garlic pste", "2", "kg", 3080, "0.72"),
        ],
    ),
}


async def _seed_receipts(tenant: uuid.UUID, today: date) -> None:
    await asyncio.to_thread(storage.ensure_bucket)  # idempotent; local runs skip storage-init
    async with SessionLocal() as session, session.begin():
        await set_tenant(session, tenant)
        for supplier, (ago, read_total, lines) in RECEIPTS.items():
            key = f"{tenant}/receipts/demo-{uuid.uuid4()}.svg"
            total = read_total if read_total is not None else sum(line[3] for line in lines)
            day = today - timedelta(days=ago)
            await asyncio.to_thread(
                storage.put_bytes, key, _receipt_svg(supplier, day, lines, total), "image/svg+xml"
            )
            receipt_id = await session.scalar(
                text(
                    "INSERT INTO receipts (object_key, status, supplier_name, receipt_date,"
                    " total_cents, model, prompt_version, input_tokens, output_tokens)"
                    " VALUES (:k, 'parsed', :s, :d, :t, 'claude-haiku-5-5', 'demo', NULL, NULL)"
                    " RETURNING id"
                ),
                {"k": key, "s": supplier, "d": day, "t": total},
            )
            for position, (desc, qty, unit, cents, conf) in enumerate(lines):
                await session.execute(
                    text(
                        "INSERT INTO receipt_lines (receipt_id, position, description, quantity,"
                        " unit, line_total_cents, confidence)"
                        " VALUES (:r, :p, :d, :q, :u, :c, :conf)"
                    ),
                    {
                        "r": receipt_id,
                        "p": position,
                        "d": desc,
                        "q": Decimal(qty),
                        "u": unit,
                        "c": cents,
                        "conf": Decimal(conf),
                    },
                )


def _receipt_svg(
    supplier: str, day: date, lines: list[tuple[str, str, str, int, str]], total: int
) -> bytes:
    """A plain drawn receipt, so the demo has a photo to show next to the fields."""
    rows = [supplier.upper(), day.strftime("%m/%d/%Y"), ""]
    rows += [f"{d[:22].upper():<22} {q:>3} {u:<4} {c / 100:>8.2f}" for d, q, u, c, _ in lines]
    rows += ["", f"{'TOTAL':<31} {total / 100:>8.2f}", "", "THANK YOU"]
    text_rows = "".join(
        f'<text x="24" y="{48 + i * 26}">{escape(row)}</text>' for i, row in enumerate(rows)
    )
    height = 72 + len(rows) * 26
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="460" height="{height}">'
        f'<rect width="460" height="{height}" fill="#fbfaf6"/>'
        f'<g font-family="Courier New, monospace" font-size="15" fill="#2b2b2b"'
        f' style="white-space:pre">{text_rows}</g></svg>'
    ).encode()


def _days_ago(days: int) -> str:
    return (datetime.now(ZoneInfo("UTC")) - timedelta(days=days)).isoformat()


def _at(day: date, hhmm: str, tz: ZoneInfo) -> str:
    return datetime.combine(day, time.fromisoformat(hhmm), tz).isoformat()


def _order(rng: random.Random, n: int, channel: str, day: date, tz: ZoneInfo) -> dict[str, Any]:
    lines: dict[str, int] = {}
    for name in rng.choices(MAINS, k=rng.choice([1, 1, 2, 2, 3])) + rng.choices(
        SIDES, k=rng.randint(0, 3)
    ):
        lines[name] = lines.get(name, 0) + 1
    price = {name: MENU.get(name, (1899, None))[0] for name in lines}
    subtotal = sum(price[name] * q for name, q in lines.items())
    minute = rng.randint(11 * 60 + 30, 21 * 60 + 30)
    placed = datetime.combine(day, time(minute // 60, minute % 60), tz)
    tip = round(subtotal * rng.choice([0.15, 0.18, 0.2])) if channel == "dine_in" else 0
    return {
        "external_id": f"D{n:05d}",
        "channel": channel,
        "placed_at": placed.isoformat(),
        "tax_cents": round(subtotal * 0.08875),  # NYC sales tax
        "tip_cents": tip,
        "items": [
            {
                "name": name,
                "quantity": str(q),
                "unit_price_cents": price[name],
                "line_total_cents": price[name] * q,
            }
            for name, q in lines.items()
        ],
    }


if __name__ == "__main__":
    asyncio.run(
        seed(os.environ.get("DINEOS_PASSWORD", "demo-password-123"), reset="--reset" in sys.argv)
    )
