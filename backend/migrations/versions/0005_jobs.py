"""jobs: Postgres-backed queue / transactional outbox

Revision ID: 0005
Revises: 0004

Producers insert a job in the same transaction as the state change, so a job exists if and
only if that change committed. Workers claim jobs across all tenants through claim_job()
(SECURITY DEFINER, like the auth lookups) and then run the handler under that job's tenant.
"""

from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE jobs (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenants (id),
            kind text NOT NULL,
            payload jsonb NOT NULL DEFAULT '{}',
            status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'done', 'failed')),
            attempts integer NOT NULL DEFAULT 0,
            max_attempts integer NOT NULL DEFAULT 5,
            run_after timestamptz NOT NULL DEFAULT now(),
            last_error text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    # Partial index: only queued jobs are ever polled, so done/failed rows don't bloat it.
    op.execute("CREATE INDEX jobs_ready_idx ON jobs (kind, run_after) WHERE status = 'queued'")
    op.execute("ALTER TABLE jobs ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tenant_isolation ON jobs USING (tenant_id = current_tenant_id())")

    # FOR UPDATE SKIP LOCKED: lock the oldest ready job; rows another worker holds are skipped
    # instead of waited on. The lock belongs to the caller's transaction and is held until it
    # ends, so a crashed worker's job unlocks and is retried.
    op.execute("""
        CREATE FUNCTION claim_job(p_kinds text[])
        RETURNS TABLE (id uuid, tenant_id uuid, kind text, payload text, attempts integer,
                       max_attempts integer)
        LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
        AS $$
            SELECT id, tenant_id, kind, payload::text, attempts, max_attempts
            FROM jobs
            WHERE status = 'queued' AND run_after <= now() AND kind = ANY (p_kinds)
            ORDER BY run_after
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION claim_job(text[]) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION claim_job(text[]) TO dineos_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION claim_job(text[])")
    op.execute("DROP TABLE jobs")
