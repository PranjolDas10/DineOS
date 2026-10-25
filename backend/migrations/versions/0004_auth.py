"""users and refresh tokens, with pre-tenant lookup functions

Revision ID: 0004
Revises: 0003

Login and token refresh happen before any tenant is known, but both tables keep RLS like
every other table. The two lookups that must cross tenants are SECURITY DEFINER functions:
they run as the table owner (no FORCE on these tables, so the owner bypasses RLS), return only
the columns auth needs, and are the only pre-tenant read path the app role has.
"""

from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    # One tenant per user for now; a memberships table comes if staff ever span restaurants.
    op.execute("""
        CREATE TABLE users (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenants (id),
            email text NOT NULL,
            password_hash text NOT NULL,
            role text NOT NULL DEFAULT 'owner' CHECK (role IN ('owner', 'staff')),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, id)
        )
    """)
    op.execute("CREATE UNIQUE INDEX users_email_key ON users (lower(email))")

    # Only a SHA-256 hash of each refresh token is stored: a DB leak doesn't leak sessions.
    # All tokens issued from one login share family_id, so reuse can revoke the whole chain.
    op.execute("""
        CREATE TABLE refresh_tokens (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenants (id),
            user_id uuid NOT NULL,
            family_id uuid NOT NULL,
            token_hash bytea NOT NULL UNIQUE,
            expires_at timestamptz NOT NULL,
            used_at timestamptz,
            revoked_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (tenant_id, user_id) REFERENCES users (tenant_id, id) ON DELETE CASCADE
        )
    """)
    op.execute("CREATE INDEX refresh_tokens_family_idx ON refresh_tokens (tenant_id, family_id)")

    for table in ("users", "refresh_tokens"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING (tenant_id = current_tenant_id())"
        )

    # SECURITY DEFINER + pinned search_path: otherwise a caller could shadow objects the
    # function references by creating them earlier on its own search_path.
    op.execute("""
        CREATE FUNCTION auth_user_by_email(p_email text)
        RETURNS TABLE (id uuid, tenant_id uuid, password_hash text, role text)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
        AS $$
            SELECT id, tenant_id, password_hash, role FROM users WHERE lower(email) = lower(p_email)
        $$
    """)
    op.execute("""
        CREATE FUNCTION auth_refresh_token(p_hash bytea)
        RETURNS TABLE (id uuid, tenant_id uuid, user_id uuid, family_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
        AS $$
            SELECT id, tenant_id, user_id, family_id FROM refresh_tokens WHERE token_hash = p_hash
        $$
    """)
    for fn in ("auth_user_by_email(text)", "auth_refresh_token(bytea)"):
        op.execute(f"REVOKE ALL ON FUNCTION {fn} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {fn} TO dineos_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION auth_refresh_token(bytea), auth_user_by_email(text)")
    op.execute("DROP TABLE refresh_tokens, users")
