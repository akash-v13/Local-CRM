"""Calling Claude to write a draft, with typed output, costs and clear errors.

`DraftWriter` is the seam: production uses `ClaudeDraftWriter`; tests pass a
fake that returns canned drafts, so the suite never calls the real API.
"""

import time
from dataclasses import dataclass
from typing import Any, Protocol

import anthropic
from pydantic import BaseModel, Field

from app.ai.models import MODELS, Effort, Usage, cost_usd


class DraftOutput(BaseModel):
    """What the model returns (enforced by structured outputs)."""

    reply: str = Field(description="The reply to the customer, plain text, ready to send.")
    facts_used: list[str] = Field(
        description="The case facts the reply relies on, briefly (e.g. 'delivered 3 days late')."
    )
    needs_human_attention: bool = Field(
        description="True if an agent should handle this case personally."
    )
    attention_reason: str = Field(description="Why, if needs_human_attention; otherwise empty.")


@dataclass(frozen=True)
class DraftResult:
    output: DraftOutput
    model: str  # requested model
    served_by: str  # model that actually answered (differs if a fallback ran)
    usage: Usage
    cost_usd: float
    latency_ms: int
    request_id: str | None


class DraftError(Exception):
    """The draft couldn't be produced; the message is safe to show to users."""


class DraftWriter(Protocol):
    def write(self, *, model: str, effort: Effort, system: list[str], user: str) -> DraftResult: ...


class ClaudeDraftWriter:
    """Writes drafts with the Anthropic API.

    - Structured outputs (`output_format=DraftOutput`) guarantee a parseable reply.
    - `system` is a list of blocks: the first (the platform's fixed rules) is
      cached with `cache_control`, so repeat drafts reuse it at ~10% of the input
      price once it's long enough to cache; later blocks (the business's layers,
      rendered for this case) follow it.
    - `effort` is sent only to models that support it (Sonnet 5, Opus 5).
    - Opus 5 gets Anthropic's server-side refusal fallback ("default"); a
      refusal that still happens is reported, never returned as a draft.
    """

    MAX_TOKENS = 16_000

    def __init__(self, client: anthropic.Anthropic) -> None:
        self.client = client

    def write(self, *, model: str, effort: Effort, system: list[str], user: str) -> DraftResult:
        info = MODELS[model]
        blocks: list[dict[str, Any]] = [{"type": "text", "text": text} for text in system if text]
        if blocks:
            blocks[0]["cache_control"] = {"type": "ephemeral"}
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": self.MAX_TOKENS,
            "system": blocks,
            "messages": [{"role": "user", "content": user}],
            "output_format": DraftOutput,
        }
        if info.supports_effort:
            kwargs["output_config"] = {"effort": effort}
        if info.server_fallbacks:
            kwargs["betas"] = ["server-side-fallback-2026-07-01"]
            kwargs["fallbacks"] = "default"

        started = time.monotonic()
        try:
            response = self.client.beta.messages.parse(**kwargs)
        except anthropic.AuthenticationError as exc:
            raise DraftError(
                "The Anthropic API key was rejected. Check ANTHROPIC_API_KEY."
            ) from exc
        except anthropic.PermissionDeniedError as exc:
            raise DraftError(f"This API key can't use {info.label}.") from exc
        except anthropic.RateLimitError as exc:
            raise DraftError("Rate limited by the Anthropic API. Try again in a minute.") from exc
        except anthropic.BadRequestError as exc:
            raise DraftError(f"The Anthropic API rejected the request: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise DraftError("Couldn't reach the Anthropic API.") from exc
        except anthropic.APIStatusError as exc:
            raise DraftError(f"Anthropic API error (HTTP {exc.status_code}). Try again.") from exc
        latency_ms = int((time.monotonic() - started) * 1000)

        if response.stop_reason == "refusal":
            raise DraftError("The model declined to write this reply. Please write it yourself.")
        if response.stop_reason == "max_tokens":
            raise DraftError(
                "The draft was cut off (too long). Try again or simplify the template."
            )
        if response.parsed_output is None:
            raise DraftError("The model's answer couldn't be read. Try again.")

        served_by = response.model if response.model in MODELS else model
        u = response.usage
        usage = Usage(
            input_tokens=u.input_tokens or 0,
            output_tokens=u.output_tokens or 0,
            cache_write_tokens=u.cache_creation_input_tokens or 0,
            cache_read_tokens=u.cache_read_input_tokens or 0,
        )
        return DraftResult(
            output=response.parsed_output,
            model=model,
            served_by=served_by,
            usage=usage,
            cost_usd=cost_usd(served_by, usage),
            latency_ms=latency_ms,
            request_id=response._request_id,
        )
