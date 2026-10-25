from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All config comes from the environment (or backend/.env locally). No defaults for secrets."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str


settings = Settings()
