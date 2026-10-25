"""prevent sub-recipe cycles with a trigger

Revision ID: 0003
Revises: 0002

A line "R uses S" is an edge R -> S. Adding it closes a cycle iff R is already reachable
from S. The trigger walks down from S with a recursive CTE and rejects the row if it finds R.

Concurrency: under READ COMMITTED two transactions can add A -> B and B -> A at the same time;
neither sees the other's uncommitted row, so both checks pass and the cycle commits.
A per-tenant advisory lock serializes sub-recipe edits: the second transaction waits until the
first commits. The check runs as a new query after the lock, and a VOLATILE (default) plpgsql
function takes a fresh snapshot per query, so it then sees the committed edge and rejects.
This relies on READ COMMITTED (the default). Under REPEATABLE READ the snapshot is fixed at the
first query, so the waiting transaction would still not see the other edge.
"""

from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION recipe_lines_no_cycle() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            -- Two-key form: (lock namespace, tenant). Held until the transaction ends.
            PERFORM pg_advisory_xact_lock(hashtext('recipe_graph'), hashtext(NEW.tenant_id::text));

            IF EXISTS (
                WITH RECURSIVE reachable(id) AS (
                    SELECT NEW.sub_recipe_id
                    UNION  -- not UNION ALL: dedup makes shared sub-recipes cheap and ends the walk
                    SELECT l.sub_recipe_id
                    FROM recipe_lines l
                    JOIN reachable r ON l.tenant_id = NEW.tenant_id AND l.recipe_id = r.id
                    WHERE l.sub_recipe_id IS NOT NULL
                )
                SELECT 1 FROM reachable WHERE id = NEW.recipe_id
            ) THEN
                RAISE EXCEPTION 'recipe % would use itself through sub-recipe %',
                    NEW.recipe_id, NEW.sub_recipe_id
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'recipe_lines_no_cycle';
            END IF;
            RETURN NULL;
        END
        $$
    """)
    # AFTER ROW triggers run at the end of the statement, so a multi-row INSERT is checked
    # with all of its rows visible. Ingredient lines can't form cycles, so they skip the lock.
    op.execute("""
        CREATE TRIGGER recipe_lines_no_cycle
        AFTER INSERT OR UPDATE OF recipe_id, sub_recipe_id ON recipe_lines
        FOR EACH ROW WHEN (NEW.sub_recipe_id IS NOT NULL)
        EXECUTE FUNCTION recipe_lines_no_cycle()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER recipe_lines_no_cycle ON recipe_lines")
    op.execute("DROP FUNCTION recipe_lines_no_cycle()")
