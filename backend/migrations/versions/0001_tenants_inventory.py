"""tenants, suppliers, ingredients, ingredient_prices with RLS

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None

TENANT_TABLES = ["suppliers", "ingredients", "ingredient_prices"]


def upgrade() -> None:
    # Missing setting -> NULL -> policies match no rows. A bare ''::uuid cast would raise instead.
    op.execute("""
        CREATE FUNCTION current_tenant_id() RETURNS uuid LANGUAGE sql STABLE
        AS $$ SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid $$
    """)

    op.execute("""
        CREATE TABLE tenants (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            name text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)

    # tenant_id defaults to the session's tenant, so app code never sets it.
    # UNIQUE (tenant_id, id) is the target for composite FKs: FK checks ignore RLS,
    # so a plain FK on id would let tenant A reference tenant B's rows.
    op.execute("""
        CREATE TABLE suppliers (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenants (id),
            name text NOT NULL,
            phone text,
            version integer NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, id)
        )
    """)
    op.execute("CREATE UNIQUE INDEX suppliers_name_key ON suppliers (tenant_id, lower(name))")

    op.execute("CREATE TYPE base_unit AS ENUM ('g', 'ml', 'each')")
    op.execute("""
        CREATE TABLE ingredients (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenants (id),
            name text NOT NULL,
            base_unit base_unit NOT NULL,
            default_supplier_id uuid,
            version integer NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, id),
            FOREIGN KEY (tenant_id, default_supplier_id) REFERENCES suppliers (tenant_id, id)
        )
    """)
    op.execute("CREATE UNIQUE INDEX ingredients_name_key ON ingredients (tenant_id, lower(name))")

    # Append-only price history. pack_qty is in base units; current cost = latest row.
    op.execute("""
        CREATE TABLE ingredient_prices (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenants (id),
            ingredient_id uuid NOT NULL,
            supplier_id uuid,
            pack_qty numeric NOT NULL CHECK (pack_qty > 0),
            pack_price_cents integer NOT NULL CHECK (pack_price_cents >= 0),
            observed_at timestamptz NOT NULL DEFAULT now(),
            created_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (tenant_id, ingredient_id) REFERENCES ingredients (tenant_id, id),
            FOREIGN KEY (tenant_id, supplier_id) REFERENCES suppliers (tenant_id, id)
        )
    """)
    op.execute("""
        CREATE INDEX ingredient_prices_latest_idx
        ON ingredient_prices (tenant_id, ingredient_id, observed_at DESC)
    """)

    # FORCE also applies RLS to the table owner when it isn't a superuser.
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING (tenant_id = current_tenant_id())"
        )
    # No FORCE on tenants: the owner creates tenants before any tenant is set.
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tenant_isolation ON tenants USING (id = current_tenant_id())")

    # The database enforces what the app role may never do.
    op.execute("REVOKE INSERT, UPDATE, DELETE ON tenants FROM dineos_app")
    op.execute("REVOKE UPDATE, DELETE ON ingredient_prices FROM dineos_app")


def downgrade() -> None:
    op.execute("DROP TABLE ingredient_prices, ingredients, suppliers, tenants")
    op.execute("DROP TYPE base_unit")
    op.execute("DROP FUNCTION current_tenant_id()")
