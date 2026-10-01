"""Masking personal data before it goes to the model, and checking what comes back.

Before a prompt is sent:
  "Hi, I'm Jane Smith, jane@x.com, call 555-123-4567"
  → "Hi, I'm [CUSTOMER_NAME], [CUSTOMER_EMAIL], call [PHONE_1]"

The model writes with the placeholders; `unmask` puts the real values back
before an agent sees the draft. `unexpected_pii` then flags any email,
phone or card number in the draft that wasn't in the case: the model must
never invent contact details.

This is pattern-based (regexes + the customer's known name/email). It catches
the common cases, not every possible identifier; a dedicated PII service can
replace it later behind the same functions.
"""

import re
from dataclasses import dataclass, field

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# 13-19 digits, optionally grouped by spaces/dashes (card numbers).
CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")
# Phone-number candidates: optional +country, digits with common separators.
# Filtered by `_is_phone` (9-15 digits, not a date), so "2026-09-01" or "3 items" stay.
PHONE = re.compile(r"(?<![\w-])\+?\d[\d ().-]{6,}\d(?![\w-])")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$|^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$")


def _is_phone(candidate: str) -> bool:
    digits = sum(ch.isdigit() for ch in candidate)
    return 9 <= digits <= 15 and not DATE.match(candidate.strip())


@dataclass
class Masked:
    text: str
    # placeholder → original value
    mapping: dict[str, str] = field(default_factory=dict)


class Masker:
    """Masks several texts consistently (the same value always gets the same placeholder)."""

    def __init__(self, customer_name: str | None, customer_email: str | None) -> None:
        self.mapping: dict[str, str] = {}
        self._reverse: dict[str, str] = {}
        self._counters: dict[str, int] = {}
        self._known: list[tuple[str, str]] = []
        # What templates should use for the first name: its own placeholder, or the
        # full name's when the name is a single word.
        self.first_name_placeholder = "[CUSTOMER_NAME]"
        if customer_email:
            self._known.append((customer_email, "[CUSTOMER_EMAIL]"))
        if customer_name and customer_name.strip():
            full = customer_name.strip()
            self._known.append((full, "[CUSTOMER_NAME]"))
            first = full.split()[0]
            if len(first) > 1 and first != full:
                self._known.append((first, "[CUSTOMER_FIRST_NAME]"))
                self.first_name_placeholder = "[CUSTOMER_FIRST_NAME]"
        # Known values can be restored even if they never appeared in a masked text
        # (e.g. the model greets the customer by the name given in the facts).
        for value, placeholder in self._known:
            self.mapping[placeholder] = value

    def _placeholder(self, kind: str, value: str) -> str:
        if value in self._reverse:
            return self._reverse[value]
        self._counters[kind] = self._counters.get(kind, 0) + 1
        placeholder = f"[{kind}_{self._counters[kind]}]"
        self.mapping[placeholder] = value
        self._reverse[value] = placeholder
        return placeholder

    def mask(self, text: str) -> str:
        for value, placeholder in self._known:  # name/email first (longest names first)
            if value:
                text = re.sub(rf"(?<!\w){re.escape(value)}(?!\w)", placeholder, text, flags=re.I)
                self.mapping[placeholder] = value
        text = EMAIL.sub(lambda m: self._placeholder("EMAIL", m.group()), text)
        text = CARD.sub(lambda m: self._placeholder("CARD", m.group()), text)
        text = PHONE.sub(
            lambda m: self._placeholder("PHONE", m.group()) if _is_phone(m.group()) else m.group(),
            text,
        )
        return text


def unmask(text: str, mapping: dict[str, str]) -> str:
    # Longest placeholders first so [CUSTOMER_NAME] doesn't clip [CUSTOMER_NAME_X]-style tokens.
    for placeholder in sorted(mapping, key=len, reverse=True):
        text = text.replace(placeholder, mapping[placeholder])
    return text


def leftover_placeholders(text: str) -> list[str]:
    """Placeholders the model wrote that we can't fill in (e.g. it invented [ORDER_ID])."""
    return sorted(set(re.findall(r"\[[A-Z][A-Z_]*\d*\]", text)))


def unexpected_pii(draft: str, source_texts: list[str]) -> list[str]:
    """Emails / phone / card numbers in the draft that appear nowhere in the case."""
    source = "\n".join(source_texts)
    found: list[str] = []
    for kind, pattern in (("email address", EMAIL), ("card number", CARD), ("phone number", PHONE)):
        for match in pattern.findall(draft):
            if kind == "phone number" and not _is_phone(match):
                continue
            if match not in source:
                found.append(f"{kind} {match}")
    return found
