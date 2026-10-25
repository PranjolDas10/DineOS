"""receipts, receipt_lines, extraction_cache

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"

TENANT_TABLES = ["receipts", "receipt_lines", "extraction_cache"]


def upgrade() -> None:
    # One row per uploaded photo. The image itself lives in S3/MinIO under object_key.
    # Token counts stay on the receipt: cost per receipt is a tracked metric.
    op.execute("""
        CREATE TABLE receipts (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenants (id),
            object_key text NOT NULL UNIQUE,
            status text NOT NULL DEFAULT 'uploaded'
                CHECK (status IN ('uploaded', 'parsed', 'failed', 'confirmed')),
            supplier_name text,
            receipt_date date,
            total_cents integer,
            model text,
            prompt_version text,
            input_tokens integer,
            output_tokens integer,
            failure_reason text,
            version integer NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, id)
        )
    """)

    # Extracted line items, each with the model's confidence (0..1) for the review screen.
    op.execute("""
        CREATE TABLE receipt_lines (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenants (id),
            receipt_id uuid NOT NULL,
            position integer NOT NULL,
            description text NOT NULL,
            quantity numeric NOT NULL,
            unit text NOT NULL,
            unit_price_cents integer,
            line_total_cents integer NOT NULL,
            confidence numeric NOT NULL CHECK (confidence BETWEEN 0 AND 1),
            ingredient_id uuid,
            UNIQUE (receipt_id, position),
            FOREIGN KEY (tenant_id, receipt_id) REFERENCES receipts (tenant_id, id)
                ON DELETE CASCADE,
            FOREIGN KEY (tenant_id, ingredient_id) REFERENCES ingredients (tenant_id, id)
        )
    """)

    # Same image bytes + model + prompt version => same answer: never pay for it twice
    # (job retries, re-uploads, eval reruns).
    op.execute("""
        CREATE TABLE extraction_cache (
            tenant_id uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenants (id),
            content_sha256 bytea NOT NULL,
            model text NOT NULL,
            prompt_version text NOT NULL,
            result jsonb NOT NULL,
            input_tokens integer NOT NULL,
            output_tokens integer NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, content_sha256, model, prompt_version)
        )
    """)

    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING (tenant_id = current_tenant_id())"
        )


def downgrade() -> None:
    op.execute("DROP TABLE extraction_cache, receipt_lines, receipts")
