"""The Claude models a reply template can use, with their prices and API differences.

Prices are Anthropic first-party list prices in USD per million tokens.
Prompt-cache writes cost 1.25x the input price (5-minute cache) and cache
reads 0.1x. Check https://www.anthropic.com/pricing when prices change and
update this table: every cost figure in the app is derived from it.
"""

from dataclasses import dataclass
from typing import Literal

Effort = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class ModelInfo:
    id: str
    label: str
    summary: str
    input_per_mtok: float
    output_per_mtok: float
    # Haiku 4.5 has no `effort` setting; Sonnet 5 and Opus 5 do.
    supports_effort: bool
    # Server-side refusal fallback ("fallbacks": "default") - used on Opus 5.
    server_fallbacks: bool

    @property
    def cache_write_per_mtok(self) -> float:
        return self.input_per_mtok * 1.25

    @property
    def cache_read_per_mtok(self) -> float:
        return self.input_per_mtok * 0.1


MODELS: dict[str, ModelInfo] = {
    m.id: m
    for m in [
        ModelInfo(
            "claude-haiku-4-5",
            "Claude Haiku 4.5",
            "Fastest and cheapest. Good for short, well-specified replies.",
            1.00,
            5.00,
            supports_effort=False,
            server_fallbacks=False,
        ),
        ModelInfo(
            "claude-sonnet-5",
            "Claude Sonnet 5",
            "Best balance of quality and cost for most replies.",
            2.00,
            10.00,
            supports_effort=True,
            server_fallbacks=False,
        ),
        ModelInfo(
            "claude-opus-5",
            "Claude Opus 5",
            "Most capable. For complex or sensitive cases.",
            5.00,
            25.00,
            supports_effort=True,
            server_fallbacks=True,
        ),
    ]
}
DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_EFFORT: Effort = "low"


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0


def cost_usd(model: str, usage: Usage) -> float:
    """What one request cost, from its token usage."""
    info = MODELS[model]
    return (
        usage.input_tokens * info.input_per_mtok
        + usage.output_tokens * info.output_per_mtok
        + usage.cache_write_tokens * info.cache_write_per_mtok
        + usage.cache_read_tokens * info.cache_read_per_mtok
    ) / 1_000_000


def estimate_tokens(text: str) -> int:
    """Rough token count for planning (~4 characters per token for English).

    Only used for *estimates* before anything runs; real costs always come
    from the API's reported usage.
    """
    return max(1, len(text) // 4)


# Typical reply length when there's no measured history yet.
TYPICAL_OUTPUT_TOKENS = 350
