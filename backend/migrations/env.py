import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import MigrationSettings

if context.config.config_file_name:
    fileConfig(context.config.config_file_name)


def run_migrations(connection: Connection) -> None:
    # Migrations are hand-written SQL (RLS, composite FKs), so no autogenerate metadata yet.
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()


async def main() -> None:
    engine = create_async_engine(MigrationSettings().migration_database_url)
    async with engine.connect() as connection:
        await connection.run_sync(run_migrations)
    await engine.dispose()


asyncio.run(main())
