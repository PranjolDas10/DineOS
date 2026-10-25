"""receipt_labels: model output vs owner-confirmed truth, per confirmed receipt

Revision ID: 0007
Revises: 0006

Every confirmed receipt becomes a labeled example for the eval harness: what the model
said (model_output) next to what the owner confirmed (confirmed), plus the model and
prompt version that produced it. Corrections are the diff between the two.
"""

from alembic import op

revision = "0007"
down_revision = "0006"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE receipt_labels (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenants (id),
            receipt_id uuid NOT NULL UNIQUE,
            model text NOT NULL,
            prompt_version text NOT NULL,
            model_output jsonb NOT NULL,
            confirmed jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (tenant_id, receipt_id) REFERENCES receipts (tenant_id, id)
                ON DELETE CASCADE
        )
    """)
    op.execute("ALTER TABLE receipt_labels ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE receipt_labels FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON receipt_labels USING (tenant_id = current_tenant_id())"
    )


def downgrade() -> None:
    op.execute("DROP TABLE receipt_labels")
