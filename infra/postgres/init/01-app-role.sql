-- Runs as the owner role (POSTGRES_USER) on first start of an empty volume; CI runs it with psql.
-- The API connects as dineos_app: not a superuser and not a table owner, so RLS applies to it.
-- Dev-only password; the demo VM sets its own.
CREATE ROLE dineos_app LOGIN PASSWORD 'dineos_app';

-- Tables created later by migrations (as the owner) are usable by the app role.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO dineos_app;
