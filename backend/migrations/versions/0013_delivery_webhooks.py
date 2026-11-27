"""delivery webhooks: platform integrations, raw webhook log, cancelled orders

Revision ID: 0013
Revises: 0012

integrations maps a delivery platform's store id to a tenant. A webhook arrives before we
know the tenant, so that one lookup crosses tenants through a SECURITY DEFINER function, like
the auth lookups. webhook_deliveries is the raw, append-only log of every delivery we
accepted, deduplicated by the platform's event id. orders gain a status so a cancelled
order stays visible but leaves the books.
"""

from alembic import op

revision = "0013"
down_revision = "0012"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE integrations (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenants (id),
            provider text NOT NULL CHECK (provider IN ('uber_eats')),
            external_store_id text NOT NULL,
            auto_accept boolean NOT NULL DEFAULT true,
            version integer NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            -- Global, not per tenant: one platform store can only belong to one restaurant.
            UNIQUE (provider, external_store_id)
        )
    """)
    op.execute("""
        CREATE TABLE webhook_deliveries (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenants (id),
            provider text NOT NULL,
            event_id text NOT NULL,
            event_type text NOT NULL,
            body jsonb NOT NULL,
            received_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, provider, event_id)
        )
    """)
    for table in ("integrations", "webhook_deliveries"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING (tenant_id = current_tenant_id())"
        )
    op.execute("REVOKE UPDATE, DELETE ON webhook_deliveries FROM dineos_app")

    op.execute("""
        CREATE FUNCTION integration_for_store(p_provider text, p_store_id text)
        RETURNS TABLE (tenant_id uuid, auto_accept boolean)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
        AS $$
            SELECT tenant_id, auto_accept FROM integrations
            WHERE provider = p_provider AND external_store_id = p_store_id
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION integration_for_store(text, text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION integration_for_store(text, text) TO dineos_app")

    op.execute("""
        ALTER TABLE orders ADD COLUMN status text NOT NULL DEFAULT 'completed'
            CHECK (status IN ('completed', 'cancelled'))
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE orders DROP COLUMN status")
    op.execute("DROP FUNCTION integration_for_store(text, text)")
    op.execute("DROP TABLE webhook_deliveries, integrations")
