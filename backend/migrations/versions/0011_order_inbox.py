"""order inbox: sales imports, append-only order events, orders projected from them

Revision ID: 0011
Revises: 0010

order_events is the source of truth: every distinct version of an order ever received,
never updated or deleted. orders/order_items are a projection (the latest version of each
order) and can be rebuilt from the events at any time (replay).
"""

from alembic import op

revision = "0011"
down_revision = "0010"

TENANT_TABLES = ["sales_imports", "order_events", "orders", "order_items"]


def upgrade() -> None:
    op.execute("""
        CREATE TABLE sales_imports (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenants (id),
            source text NOT NULL,
            object_key text NOT NULL UNIQUE,
            status text NOT NULL DEFAULT 'uploaded'
                CHECK (status IN ('uploaded', 'imported', 'failed')),
            orders_new integer,
            orders_updated integer,
            duplicates integer,
            error text,
            version integer NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, id)
        )
    """)

    # Dedup key: the same order with the same content is stored once, however many times
    # the export is imported. A changed order (void, comp, fixed tip) is a new version.
    op.execute("""
        CREATE TABLE order_events (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenants (id),
            source text NOT NULL,
            external_id text NOT NULL,
            content_sha256 bytea NOT NULL,
            payload jsonb NOT NULL,
            import_id uuid,
            received_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, source, external_id, content_sha256),
            FOREIGN KEY (tenant_id, import_id) REFERENCES sales_imports (tenant_id, id)
        )
    """)

    # event_id = the order_events row this projection reflects (the latest one applied).
    op.execute("""
        CREATE TABLE orders (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenants (id),
            source text NOT NULL,
            external_id text NOT NULL,
            channel text NOT NULL,
            placed_at timestamptz NOT NULL,
            subtotal_cents integer NOT NULL,
            tax_cents integer NOT NULL,
            tip_cents integer NOT NULL,
            total_cents integer NOT NULL,
            event_id uuid NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, source, external_id),
            UNIQUE (tenant_id, id)
        )
    """)
    op.execute("CREATE INDEX orders_placed_idx ON orders (tenant_id, placed_at)")
    # Target for order_items' tenant-scoped FK (menu_items had no referrers until now).
    op.execute(
        "ALTER TABLE menu_items ADD CONSTRAINT menu_items_tenant_id_key UNIQUE (tenant_id, id)"
    )
    op.execute("""
        CREATE TABLE order_items (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenants (id),
            order_id uuid NOT NULL,
            position integer NOT NULL,
            name text NOT NULL,
            menu_item_id uuid,
            quantity numeric NOT NULL,
            unit_price_cents integer NOT NULL,
            line_total_cents integer NOT NULL,
            UNIQUE (order_id, position),
            FOREIGN KEY (tenant_id, order_id) REFERENCES orders (tenant_id, id) ON DELETE CASCADE,
            FOREIGN KEY (tenant_id, menu_item_id) REFERENCES menu_items (tenant_id, id)
        )
    """)

    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING (tenant_id = current_tenant_id())"
        )
    # The log is append-only for the app: history can't be edited, only added to.
    op.execute("REVOKE UPDATE, DELETE ON order_events FROM dineos_app")


def downgrade() -> None:
    op.execute("DROP TABLE order_items, orders, order_events, sales_imports")
    op.execute("ALTER TABLE menu_items DROP CONSTRAINT menu_items_tenant_id_key")
