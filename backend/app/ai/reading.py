"""Reading a customer's message: which data fields it contains, and what it's about.

The approach ("select, don't generate"):

1. Code finds **candidates** for each field the business defined, using a pattern
   (e.g. order numbers look like `NW-10211`), each with a few words of context.
2. A model **chooses** among them: "which of these is the order the customer is
   writing about?" over [candidate 1, candidate 2, …, none of these]. It can't
   invent a value, only pick one our code found. The same call picks the case's
   category from the business's list, judged on the whole message.
3. Code **decides** with the model's confidence: confident picks are saved on the
   case; uncertain ones are left for an agent, with the candidates shown.

Everything here is pure (no I/O). The models live in app/ai/readers.py and the
workflow in app/services/reading.py.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

# Ready-made patterns the business can pick from (or write their own regex).
PATTERN_PRESETS: dict[str, tuple[str, str]] = {
    "code": (r"\b[A-Z]{1,5}-?\d{3,12}\b", "Letters then digits, e.g. NW-10211 or ORD10211"),
    "digits": (r"\b\d{5,14}\b", "A long number, e.g. 104821377"),
    "amount": (
        r"(?:[$€£]\s?\d[\d,]*(?:\.\d{1,2})?|\b\d[\d,]*(?:\.\d{1,2})?\s?(?:USD|EUR|GBP|dollars|euros|pounds)\b)",
        "A money amount, e.g. $179.04 or 40 EUR",
    ),
    "date": (
        r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|\d{1,2}\s(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s\d{4})\b",
        "A date, e.g. 2026-09-18, 18/09/2026 or 18 Sep 2026",
    ),
}

MAX_TEXT = 20_000  # characters read per message (bounds the pattern work)
MAX_CANDIDATES = 15
CONTEXT_WORDS = 6

FieldStatus = Literal["found", "not_found", "needs_review", "provided"]


def pattern_problem(pattern: str) -> str | None:
    """Why a custom pattern can't be used, or None."""
    if not pattern or len(pattern) > 300:
        return "Patterns must be 1-300 characters."
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        return f"Not a valid pattern: {exc}."
    if compiled.match(""):
        return "The pattern must not match empty text."
    return None


@dataclass(frozen=True)
class Candidate:
    value: str
    context: str  # a few words around the first occurrence


def find_candidates(pattern: str, text: str, limit: int = MAX_CANDIDATES) -> list[Candidate]:
    """Distinct matches in order of first appearance, each with surrounding words."""
    text = text[:MAX_TEXT]
    seen: dict[str, Candidate] = {}
    for match in re.finditer(pattern, text, re.IGNORECASE):
        value = match.group(0).strip()
        if not value or value.lower() in (v.lower() for v in seen):
            continue
        before = text[: match.start()].split()[-CONTEXT_WORDS:]
        after = text[match.end() :].split()[:CONTEXT_WORDS]
        context = " ".join([*before, "«" + value + "»", *after])
        seen[value] = Candidate(value=value, context=context)
        if len(seen) >= limit:
            break
    return list(seen.values())


def category_options(taxonomy: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Every Type › Category › Subcategory (and Type › Category) as a choosable option."""
    options: dict[str, dict[str, Any]] = {}
    for t in taxonomy:
        for c in t["categories"]:
            subs = c["subcategories"] or [{"name": None}]
            for s in subs:
                value = {"type": t["name"], "category": c["name"], "subcategory": s["name"]}
                label = " › ".join(x for x in (t["name"], c["name"], s["name"]) if x)
                options[f"k{len(options) + 1}"] = {"label": label, "value": value}
    return options


@dataclass(frozen=True)
class Pick:
    """A model's answer to one question: the option it chose and how sure it was (0-1)."""

    option: str  # an option id, or "none"
    confidence: float


@dataclass
class FieldResult:
    key: str
    label: str
    status: FieldStatus
    value: str | None = None
    confidence: float | None = None
    candidates: list[str] = field(default_factory=list)
    reviewed_by: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "status": self.status,
            "value": self.value,
            "confidence": self.confidence,
            "candidates": self.candidates,
            "reviewed_by": self.reviewed_by,
        }


def decide_field(
    key: str,
    label: str,
    candidates: list[Candidate],
    pick: Pick | None,
    *,
    threshold: float,
    option_ids: dict[str, str],
) -> FieldResult:
    """Turn candidates + the model's pick into a result.

    `option_ids` maps the option ids the model saw to candidate values. `pick` is
    None when no model ran (patterns only): then a single candidate is accepted
    and several need a person.
    """
    values = [c.value for c in candidates]
    if not candidates:
        return FieldResult(key, label, "not_found")
    if pick is None:
        if len(candidates) == 1:
            return FieldResult(key, label, "found", values[0], None, values)
        return FieldResult(key, label, "needs_review", None, None, values)
    chosen = option_ids.get(pick.option)
    if chosen is None:  # "none of these", or an id we never offered
        status: FieldStatus = "not_found" if pick.confidence >= threshold else "needs_review"
        return FieldResult(key, label, status, None, pick.confidence, values)
    if pick.confidence >= threshold:
        return FieldResult(key, label, "found", chosen, pick.confidence, values)
    return FieldResult(key, label, "needs_review", chosen, pick.confidence, values)
