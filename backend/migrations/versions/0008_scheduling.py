"""staff, shifts (no overlaps per person, enforced by an exclusion constraint), tenant timezone

Revision ID: 0008
Revises: 0007
"""

from alembic import op

revision = "0008"
down_revision = "0007"


def upgrade() -> None:
    # Business days (labor cost per day) are local days. IANA name, e.g. America/New_York.
    op.execute("ALTER TABLE tenants ADD COLUMN timezone text NOT NULL DEFAULT 'UTC'")

    op.execute("""
        CREATE TABLE staff (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenants (id),
            name text NOT NULL,
            hourly_rate_cents integer NOT NULL CHECK (hourly_rate_cents >= 0),
            active boolean NOT NULL DEFAULT true,
            version integer NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, id)
        )
    """)

    # btree_gist lets one GiST index mix "=" on uuids with "&&" (overlaps) on ranges.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    # during is half-open [start, end): a 9-17 shift and a 17-22 shift touch but don't overlap.
    # hourly_rate_cents is copied from staff when the shift is created, so a raise later
    # doesn't rewrite the labor cost of past weeks.
    op.execute("""
        CREATE TABLE shifts (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenants (id),
            staff_id uuid NOT NULL,
            during tstzrange NOT NULL,
            hourly_rate_cents integer NOT NULL CHECK (hourly_rate_cents >= 0),
            note text,
            version integer NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CHECK (NOT isempty(during) AND upper(during) - lower(during) <= interval '16 hours'),
            FOREIGN KEY (tenant_id, staff_id) REFERENCES staff (tenant_id, id),
            CONSTRAINT shifts_no_overlap
                EXCLUDE USING gist (tenant_id WITH =, staff_id WITH =, during WITH &&)
        )
    """)

    for table in ("staff", "shifts"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING (tenant_id = current_tenant_id())"
        )


def downgrade() -> None:
    op.execute("DROP TABLE shifts, staff")
    op.execute("ALTER TABLE tenants DROP COLUMN timezone")
