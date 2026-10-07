"""Application settings.

All settings come from environment variables (or a `.env` file in the working
directory). Nothing secret for a real environment is hard-coded here: the
defaults only suit local development (the docker-compose database, and a
clearly-marked development-only encryption key that production refuses to use).

Example: setting `DATABASE_URL=postgresql+psycopg://...` in the environment
overrides `database_url`.
"""

from functools import lru_cache
from typing import Annotated

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEV_SECRET_KEY = "tg6Dkzd3Z3b8l3TQ9Mqj2C1y8b8vYqgT8n6eU4nGX0s="


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # SQLAlchemy connection URL. `postgresql+psycopg` = Postgres via the psycopg 3 driver.
    database_url: str = "postgresql+psycopg://resolve:resolve@localhost:5432/resolve"

    # "local", "dev", "stg" or "prd". Used for logging and safety checks later on.
    app_env: str = "local"

    # --- Connectors (enrichment) -----------------------------------------------------
    # Key for encrypting connector secrets (Fernet, urlsafe base64, 32 bytes).
    # This default is for LOCAL DEVELOPMENT ONLY: it is public in the repo.
    # Every real environment must set CONNECTOR_SECRET_KEY (see app/security/secrets.py).
    connector_secret_key: str = DEV_SECRET_KEY
    # Hostnames connectors may call even though they're private (e.g. "mocks" in
    # docker-compose). Comma-separated in the environment. Empty in production.
    connector_allowed_hosts: Annotated[list[str], NoDecode] = []
    # Allow plain http:// connector URLs (local development only).
    connector_allow_http: bool = False
    # Largest connector response we read, in bytes.
    connector_max_response_bytes: int = 1_000_000
    # --- Email channel (IMAP/SMTP inboxes) --------------------------------------------
    # Mail servers that may be used even though they're private (e.g. "greenmail", the
    # local test mail server in docker-compose). Comma-separated. Empty in production.
    email_allowed_hosts: Annotated[list[str], NoDecode] = []
    # Allow IMAP/SMTP without TLS (local development only, e.g. GreenMail).
    email_allow_insecure: bool = False
    # Seconds to wait for a mail server before giving up.
    email_timeout_seconds: float = 20.0

    # --- AI reply drafting ------------------------------------------------------------
    # Anthropic API key (https://console.anthropic.com). Without it, drafting is off
    # and the UI says how to enable it.
    anthropic_api_key: str | None = None
    # TypeSafe AI key (https://console.typesafe.ai). When set, Jev reads incoming messages
    # (field values, category); otherwise Claude does, or patterns alone without either key.
    typesafe_api_key: str | None = None

    # --- Payouts -----------------------------------------------------------------------
    # Stripe API base URL. Only changed for local demos (the mock API's fake Stripe at
    # http://mocks:8100/stripe); each business's own Stripe key decides test vs live.
    stripe_api_base: str = "https://api.stripe.com"

    # --- Shopify -----------------------------------------------------------------------
    # Empty = each store at https://<shop>.myshopify.com. Local demos set the mock API's
    # fake Shopify (http://mocks:8100/shopify), which then serves /shopify/<shop>/admin/...
    shopify_api_base: str = ""

    # Background worker: seconds between checks for new jobs when idle.
    worker_poll_seconds: float = 1.0

    @field_validator("connector_allowed_hosts", "email_allowed_hosts", mode="before")
    @classmethod
    def _split_hosts(cls, value: object) -> object:
        if isinstance(value, str):
            return [h.strip() for h in value.split(",") if h.strip()]
        return value

    @model_validator(mode="after")
    def _require_real_key_outside_local(self) -> "Settings":
        if self.app_env not in ("local", "test") and self.connector_secret_key == DEV_SECRET_KEY:
            raise ValueError("CONNECTOR_SECRET_KEY must be set outside local development.")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the settings, read once and cached for the life of the process."""
    return Settings()
