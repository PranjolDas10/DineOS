"""Mock Curry Original menu with hand-computed costs.

These are test check values, not owner measurements. Round pack prices keep the arithmetic
checkable by hand; every expected number below is derived in a comment.
"""

from typing import Any

from httpx import AsyncClient

# name: (base_unit, pack_qty, pack_price_cents); None = no price entered yet
INGREDIENTS: dict[str, tuple[str, int | None, int | None]] = {
    "Onion": ("g", 20000, 2000),  # 0.10 c/g
    "Tomato puree": ("g", 3000, 450),  # 0.15 c/g
    "Butter": ("g", 1000, 800),  # 0.80 c/g
    "Cream": ("ml", 1000, 500),  # 0.50 c/ml
    "Chicken thigh": ("g", 10000, 6000),  # 0.60 c/g
    "Ginger-garlic paste": ("g", 1000, 600),  # 0.60 c/g
    "Garam masala": ("g", 500, 1000),  # 2.00 c/g
    "Chickpeas": ("g", 2500, 375),  # 0.15 c/g
    "Flour": ("g", 10000, 1200),  # 0.12 c/g
    "Saffron": ("g", None, None),
}

# name: (yield_qty, yield_unit, [(ingredient or sub-recipe name, qty)])
RECIPES: dict[str, tuple[int, str, list[tuple[str, int]]]] = {
    # 1200*0.10 + 100*0.60 + 400*0.15 + 20*2 = 120 + 60 + 60 + 40 = 280 -> 0.28 c/g
    "Onion masala paste": (
        1000,
        "g",
        [
            ("Onion", 1200),
            ("Ginger-garlic paste", 100),
            ("Tomato puree", 400),
            ("Garam masala", 20),
        ],
    ),
    # 1000*0.28 + 3000*0.15 + 250*0.80 + 500*0.50 + 10*2 = 280+450+200+250+20 = 1200 -> 0.24 c/g
    "Makhani gravy": (
        5000,
        "g",
        [
            ("Onion masala paste", 1000),
            ("Tomato puree", 3000),
            ("Butter", 250),
            ("Cream", 500),
            ("Garam masala", 10),
        ],
    ),
    # Diamond: paste is reached directly and through the gravy.
    # 3000*0.60 + 2500*0.24 + 300*0.28 + 50*0.80 = 1800 + 600 + 84 + 40 = 2524
    "Butter chicken batch": (
        6000,
        "g",
        [
            ("Chicken thigh", 3000),
            ("Makhani gravy", 2500),
            ("Onion masala paste", 300),
            ("Butter", 50),
        ],
    ),
    # 2500*0.15 + 500*0.28 + 1000*0.15 + 15*2 = 375 + 140 + 150 + 30 = 695
    "Chana masala batch": (
        4000,
        "g",
        [
            ("Chickpeas", 2500),
            ("Onion masala paste", 500),
            ("Tomato puree", 1000),
            ("Garam masala", 15),
        ],
    ),
    # 1000*0.12 + 100*0.80 + 50*0.60 = 120 + 80 + 30 = 230 -> 23 c each
    "Garlic naan dough": (
        10,
        "each",
        [("Flour", 1000), ("Butter", 100), ("Ginger-garlic paste", 50)],
    ),
    "Saffron rice": (2000, "g", [("Saffron", 1)]),  # unknown: Saffron has no price
    "Veg thali": (
        1,
        "each",
        [("Chana masala batch", 300), ("Saffron rice", 250)],
    ),  # unknown via sub
    "Mango kulfi": (12, "each", []),  # unknown: no lines entered yet
}

EXPECTED_RECIPE_TOTALS: dict[str, int | None] = {
    "Onion masala paste": 280,
    "Makhani gravy": 1200,
    "Butter chicken batch": 2524,
    "Chana masala batch": 695,
    "Garlic naan dough": 230,
    "Saffron rice": None,
    "Veg thali": None,
    "Mango kulfi": None,
}

# name: (price_cents, recipe name or None, portion_qty in the recipe's yield unit)
MENU: dict[str, tuple[int, str | None, int]] = {
    "Butter Chicken": (1799, "Butter chicken batch", 350),
    "Chana Masala": (1399, "Chana masala batch", 300),
    "Garlic Naan": (399, "Garlic naan dough", 1),
    "Veg Thali": (1599, "Veg thali", 1),
    "Mango Kulfi": (499, "Mango kulfi", 1),
    "Mango Lassi": (499, None, 1),
}

# name: (cost_cents, margin_cents, food_cost_pct)
EXPECTED_MENU: dict[str, tuple[int | None, int | None, str | None]] = {
    # 350 * 2524/6000 = 147.233.. -> 147; 1799 - 147 = 1652; 147.233/1799 = 8.18% -> 8.2
    "Butter Chicken": (147, 1652, "8.2"),
    # 300 * 695/4000 = 52.125 -> 52; 1399 - 52 = 1347; 52.125/1399 = 3.73% -> 3.7
    "Chana Masala": (52, 1347, "3.7"),
    # 1 * 230/10 = 23; 399 - 23 = 376; 23/399 = 5.76% -> 5.8
    "Garlic Naan": (23, 376, "5.8"),
    "Veg Thali": (None, None, None),
    "Mango Kulfi": (None, None, None),
    "Mango Lassi": (None, None, None),
}


async def load(client: AsyncClient, headers: dict[str, str]) -> dict[str, str]:
    """Create the whole mock menu through the API. Returns name -> id."""
    ids: dict[str, str] = {}

    async def post(url: str, body: dict[str, Any]) -> str:
        resp = await client.post(url, json=body, headers=headers)
        assert resp.status_code == 201, resp.text
        new_id: str = resp.json()["id"]
        return new_id

    for name, (unit, pack_qty, pack_cents) in INGREDIENTS.items():
        ids[name] = await post("/v1/ingredients", {"name": name, "base_unit": unit})
        if pack_qty is not None:
            pack = {"pack_qty": pack_qty, "pack_price_cents": pack_cents}
            await post(f"/v1/ingredients/{ids[name]}/prices", pack)

    # All recipes first, so lines can reference any of them as sub-recipes.
    for name, (yield_qty, yield_unit, _) in RECIPES.items():
        recipe_body = {"name": name, "yield_qty": yield_qty, "yield_unit": yield_unit}
        ids[name] = await post("/v1/recipes", recipe_body)
    for name, (_, _, lines) in RECIPES.items():
        body_lines = [
            {("ingredient_id" if t in INGREDIENTS else "sub_recipe_id"): ids[t], "qty": q}
            for t, q in lines
        ]
        resp = await client.put(
            f"/v1/recipes/{ids[name]}/lines",
            json={"lines": body_lines},
            headers={**headers, "If-Match": '"1"'},
        )
        assert resp.status_code == 200, resp.text

    for name, (price, recipe, portion) in MENU.items():
        body: dict[str, Any] = {"name": name, "price_cents": price, "portion_qty": portion}
        if recipe:
            body["recipe_id"] = ids[recipe]
        ids[name] = await post("/v1/menu-items", body)
    return ids
