"""Application settings.

All settings come from environment variables (or a `.env` file in the working
directory). Nothing secret is ever hard-coded here — the defaults below only
point at the local development database started by docker-compose.

Example: setting `DATABASE_URL=postgresql+psycopg://...` in the environment
overrides `database_url`.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # SQLAlchemy connection URL. `postgresql+psycopg` = Postgres via the psycopg 3 driver.
    database_url: str = "postgresql+psycopg://resolve:resolve@localhost:5432/resolve"

    # "local", "dev", "stg" or "prd". Used for logging and safety checks later on.
    app_env: str = "local"


@lru_cache
def get_settings() -> Settings:
    """Return the settings, read once and cached for the life of the process."""
    return Settings()
