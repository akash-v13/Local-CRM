"""Creating the production DraftWriter from settings."""

import anthropic

from app.ai.drafter import ClaudeDraftWriter
from app.config import Settings


def draft_writer_from(settings: Settings) -> ClaudeDraftWriter | None:
    """None when no API key is configured (AI drafting is then off)."""
    if not settings.anthropic_api_key:
        return None
    client = anthropic.Anthropic(
        api_key=settings.anthropic_api_key,
        timeout=anthropic.Timeout(120.0, connect=10.0),
        max_retries=2,  # the SDK retries 429/5xx/connection errors with backoff
    )
    return ClaudeDraftWriter(client)
