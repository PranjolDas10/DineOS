from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All config comes from the environment (or backend/.env locally). No defaults for secrets."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    # HS256 signing key for access tokens. RFC 7518 3.2: at least 256 bits.
    jwt_secret: str = Field(min_length=32)
    # S3 API (SeaweedFS locally). Credentials come from the standard AWS_* env vars, read by boto3.
    # Prometheus scrape port, separate from the API so it is never exposed publicly.
    metrics_port: int = 9100
    # Cache and rate-limit buckets only: everything in it can be lost without harm.
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint_url: str = "http://localhost:8333"
    # Presigned URLs embed the host in their signature, so they must be signed for the host
    # the phone will call (in Compose the API reaches storage as seaweedfs:8333, the phone can't).
    s3_public_endpoint_url: str = "http://localhost:8333"
    # Cheapest model first; the eval harness decides whether a bigger one earns its cost.
    receipt_model: str = "claude-haiku-5-5"


class MigrationSettings(BaseSettings):
    """Owner-role DSN for Alembic and test setup. Bypasses RLS, so the API never loads it."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    migration_database_url: str


settings = Settings()
