"""profitability ledger: double-entry, append-only, balanced by a deferred constraint trigger

Revision ID: 0012
Revises: 0011

Sign convention: amount_cents > 0 is a debit, < 0 a credit. Every transaction's entries
must sum to zero. The check is a DEFERRABLE INITIALLY DEFERRED constraint trigger: it runs at
COMMIT, after all of a transaction's entries are inserted, so entries can be written one by
one but an unbalanced transaction can never be committed.
"""

from alembic import op

revision = "0012"
down_revision = "0011"

ACCOUNTS = (
    "cash",  # money received (or receivable from a delivery platform)
    "revenue",  # food sales
    "tax_payable",  # sales tax collected for the government
    "tips_payable",  # tips owed to staff
    "platform_commission",  # delivery platform fees (expense)
    "food_cost",  # cost of the food sold (expense)
    "inventory",  # stock used up by the sale
)


def upgrade() -> None:
    # Commission per sales channel, set by the owner (dine_in: 0; a delivery app: e.g. 3000).
    op.execute("""
        CREATE TABLE channel_fees (
            tenant_id uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenants (id),
            channel text NOT NULL,
            commission_bps integer NOT NULL CHECK (commission_bps BETWEEN 0 AND 10000),
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, channel)
        )
    """)

    # idempotency_key: "sale:<order event id>" or "reversal:<transaction id>". Unique, so a
    # retried or concurrent posting job can't post the same thing twice.
    op.execute("""
        CREATE TABLE ledger_transactions (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenants (id),
            kind text NOT NULL CHECK (kind IN ('sale', 'reversal')),
            idempotency_key text NOT NULL,
            order_id uuid,
            business_date date NOT NULL,
            reverses_id uuid,
            food_cost_complete boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, idempotency_key),
            UNIQUE (tenant_id, id),
            FOREIGN KEY (tenant_id, order_id) REFERENCES orders (tenant_id, id),
            FOREIGN KEY (tenant_id, reverses_id) REFERENCES ledger_transactions (tenant_id, id)
        )
    """)
    accounts = ", ".join(f"'{a}'" for a in ACCOUNTS)
    op.execute(f"""
        CREATE TABLE ledger_entries (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenants (id),
            transaction_id uuid NOT NULL,
            account text NOT NULL CHECK (account IN ({accounts})),
            amount_cents bigint NOT NULL CHECK (amount_cents <> 0),
            channel text NOT NULL,
            menu_item_id uuid,
            FOREIGN KEY (tenant_id, transaction_id) REFERENCES ledger_transactions (tenant_id, id),
            FOREIGN KEY (tenant_id, menu_item_id) REFERENCES menu_items (tenant_id, id)
        )
    """)
    op.execute("CREATE INDEX ledger_entries_txn_idx ON ledger_entries (tenant_id, transaction_id)")
    op.execute(
        "CREATE INDEX ledger_transactions_day_idx ON ledger_transactions (tenant_id, business_date)"
    )

    op.execute("""
        CREATE FUNCTION ledger_balanced() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE total bigint;
        BEGIN
            SELECT sum(amount_cents) INTO total
            FROM ledger_entries WHERE transaction_id = NEW.transaction_id;
            IF total <> 0 THEN
                RAISE EXCEPTION 'ledger transaction % is unbalanced by % cents',
                    NEW.transaction_id, total
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'ledger_balanced';
            END IF;
            RETURN NULL;
        END
        $$
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER ledger_balanced
        AFTER INSERT ON ledger_entries
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION ledger_balanced()
    """)

    for table in ("channel_fees", "ledger_transactions", "ledger_entries"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING (tenant_id = current_tenant_id())"
        )
    # The books are append-only: a mistake is corrected by a reversing transaction.
    op.execute("REVOKE UPDATE, DELETE ON ledger_transactions, ledger_entries FROM dineos_app")


def downgrade() -> None:
    op.execute("DROP TABLE ledger_entries, ledger_transactions, channel_fees")
    op.execute("DROP FUNCTION ledger_balanced()")
