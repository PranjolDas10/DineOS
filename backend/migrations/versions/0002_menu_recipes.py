"""recipes, recipe_lines (sub-recipes), menu_items with RLS

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"

TENANT_TABLES = ["recipes", "recipe_lines", "menu_items"]


def upgrade() -> None:
    # One table for dishes and sub-recipes (e.g. makhani gravy yields 5000 g).
    op.execute("""
        CREATE TABLE recipes (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenants (id),
            name text NOT NULL,
            yield_qty numeric NOT NULL CHECK (yield_qty > 0),
            yield_unit base_unit NOT NULL,
            version integer NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, id)
        )
    """)
    op.execute("CREATE UNIQUE INDEX recipes_name_key ON recipes (tenant_id, lower(name))")

    # A line uses exactly one ingredient (qty in its base unit) or one sub-recipe
    # (qty in the sub-recipe's yield unit). Lines belong to their recipe and go with it.
    op.execute("""
        CREATE TABLE recipe_lines (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenants (id),
            recipe_id uuid NOT NULL,
            ingredient_id uuid,
            sub_recipe_id uuid,
            qty numeric NOT NULL CHECK (qty > 0),
            CHECK (num_nonnulls(ingredient_id, sub_recipe_id) = 1),
            FOREIGN KEY (tenant_id, recipe_id) REFERENCES recipes (tenant_id, id) ON DELETE CASCADE,
            FOREIGN KEY (tenant_id, ingredient_id) REFERENCES ingredients (tenant_id, id),
            FOREIGN KEY (tenant_id, sub_recipe_id) REFERENCES recipes (tenant_id, id)
        )
    """)
    op.execute("CREATE INDEX recipe_lines_recipe_idx ON recipe_lines (tenant_id, recipe_id)")

    # What is sold. recipe_id is NULL until the owner enters the recipe (cost unknown).
    # portion_qty is how much of the recipe one sale uses, in the recipe's yield unit.
    op.execute("""
        CREATE TABLE menu_items (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenants (id),
            name text NOT NULL,
            price_cents integer NOT NULL CHECK (price_cents >= 0),
            recipe_id uuid,
            portion_qty numeric NOT NULL DEFAULT 1 CHECK (portion_qty > 0),
            version integer NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (tenant_id, recipe_id) REFERENCES recipes (tenant_id, id)
        )
    """)
    op.execute("CREATE UNIQUE INDEX menu_items_name_key ON menu_items (tenant_id, lower(name))")

    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING (tenant_id = current_tenant_id())"
        )


def downgrade() -> None:
    op.execute("DROP TABLE menu_items, recipe_lines, recipes")
