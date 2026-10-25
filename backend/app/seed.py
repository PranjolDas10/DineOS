"""Seed a demo restaurant with fake data, for the web dashboard and the public demo.

    uv run python -m app.seed            # demo@dineos.dev / DINEOS_PASSWORD (default below)
    docker compose run --rm migrate python -m app.seed

Everything here is invented sample data, never real restaurant numbers. Dates are relative to
today, so the demo always shows the last four weeks. Refuses to run twice for the same email.
"""

import asyncio
import os
import random
import uuid
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app import jobs
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


async def seed(password: str) -> None:
    rng = random.Random(7)  # same demo every run
    tz = ZoneInfo(TZ)
    today = datetime.now(tz).date()
    owner = create_async_engine(MigrationSettings().migration_database_url)
    async with owner.connect() as conn:
        if await conn.scalar(text("SELECT 1 FROM users WHERE email = :e"), {"e": EMAIL}):
            await owner.dispose()
            raise SystemExit(f"{EMAIL} already exists; the demo is already seeded.")
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
            await call(
                "POST",
                f"/v1/ingredients/{ids[name]}/prices",
                {"pack_qty": qty, "pack_price_cents": cents},
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
            for d in range(DAYS):
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
    print(f"Seeded {n} orders over {DAYS} days. Log in as {EMAIL}.")


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
    asyncio.run(seed(os.environ.get("DINEOS_PASSWORD", "demo-password-123")))
