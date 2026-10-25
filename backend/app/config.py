from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All config comes from the environment (or backend/.env locally). No defaults for secrets."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    # HS256 signing key for access tokens. RFC 7518 3.2: at least 256 bits.
    jwt_secret: str = Field(min_length=32)


class MigrationSettings(BaseSettings):
    """Owner-role DSN for Alembic and test setup. Bypasses RLS, so the API never loads it."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    migration_database_url: str


settings = Settings()
