"""Bootstrap a restaurant (tenant) and its owner account.

    uv run python -m app.auth.cli --tenant "Curry Original" --email owner@example.com
    docker compose run --rm migrate python -m app.auth.cli --tenant ... --email ...   # in Docker

Runs as the owner DB role, because the API role can't create tenants. The password comes from
DINEOS_PASSWORD if set (scripts, demo seed), otherwise an interactive prompt.
"""

import argparse
import asyncio
import os
from getpass import getpass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.auth.service import hash_password
from app.config import MigrationSettings


async def create_owner(tenant: str, email: str, password: str) -> None:
    engine = create_async_engine(MigrationSettings().migration_database_url)
    async with engine.begin() as conn:
        tenant_id = await conn.scalar(
            text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"), {"n": tenant}
        )
        await conn.execute(
            text("INSERT INTO users (tenant_id, email, password_hash) VALUES (:t, :e, :h)"),
            {"t": tenant_id, "e": email, "h": hash_password(password)},
        )
    await engine.dispose()
    print(f"Created tenant {tenant_id} with owner {email}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    password = os.environ.get("DINEOS_PASSWORD") or getpass("Owner password: ")
    asyncio.run(create_owner(args.tenant, args.email, password))


if __name__ == "__main__":
    main()
