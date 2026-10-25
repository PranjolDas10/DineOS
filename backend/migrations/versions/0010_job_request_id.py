"""jobs.request_id: follow one request into the background jobs it caused

Revision ID: 0010
Revises: 0009
"""

from alembic import op

revision = "0010"
down_revision = "0009"

_CLAIM = """
    CREATE FUNCTION claim_job(p_kinds text[])
    RETURNS TABLE (id uuid, tenant_id uuid, kind text, payload text, attempts integer,
                   max_attempts integer{extra})
    LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
    AS $$
        SELECT id, tenant_id, kind, payload::text, attempts, max_attempts{extra_col}
        FROM jobs
        WHERE status = 'queued' AND run_after <= now() AND kind = ANY (p_kinds)
        ORDER BY run_after
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    $$
"""


def _replace_claim(extra: str, extra_col: str) -> None:
    # The return type changes, so the function is dropped and recreated (not REPLACEd).
    op.execute("DROP FUNCTION claim_job(text[])")
    op.execute(_CLAIM.format(extra=extra, extra_col=extra_col))
    op.execute("REVOKE ALL ON FUNCTION claim_job(text[]) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION claim_job(text[]) TO dineos_app")


def upgrade() -> None:
    op.execute("ALTER TABLE jobs ADD COLUMN request_id text")
    _replace_claim(", request_id text", ", request_id")


def downgrade() -> None:
    _replace_claim("", "")
    op.execute("ALTER TABLE jobs DROP COLUMN request_id")
