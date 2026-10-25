from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All config comes from the environment (or backend/.env locally). No defaults for secrets."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str


class MigrationSettings(BaseSettings):
    """Owner-role DSN for Alembic and test setup. Bypasses RLS, so the API never loads it."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    migration_database_url: str


settings = Settings()
