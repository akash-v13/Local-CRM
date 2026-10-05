"""Automated checks prompt templates can define (merged across layers), applied to every draft.

They make "does the model follow the template?" measurable:
- max_words:        the reply must not be longer than this
- must_include:     phrases that must appear (case-insensitive)
- must_not_include: phrases that must not appear (e.g. "small gesture", "voucher")
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


def word_count(text: str) -> int:
    return len(re.findall(r"\b\w[\w'-]*\b", text))


def run_checks(
    reply: str,
    *,
    max_words: int | None,
    must_include: list[str],
    must_not_include: list[str],
) -> list[CheckResult]:
    results: list[CheckResult] = []
    lowered = reply.lower()
    if max_words:
        words = word_count(reply)
        results.append(
            CheckResult("max_words", words <= max_words, f"{words} words (max {max_words})")
        )
    for phrase in must_include:
        ok = phrase.lower() in lowered
        results.append(
            CheckResult("must_include", ok, f'{"Mentions" if ok else "Missing"} "{phrase}"')
        )
    for phrase in must_not_include:
        ok = phrase.lower() not in lowered
        results.append(
            CheckResult("must_not_include", ok, f'{"Avoids" if ok else "Contains"} "{phrase}"')
        )
    return results


def consistency(replies: list[str]) -> float | None:
    """How alike repeated replies to the same input are: mean pairwise word-level
    similarity, 0-1 (1 = identical). None with fewer than two replies.

    A standardization signal: a well-specified template should produce replies
    that say the same things in a similar way, even if wording varies.
    """
    from difflib import SequenceMatcher

    if len(replies) < 2:
        return None
    tokens = [r.lower().split() for r in replies]
    scores = [
        SequenceMatcher(None, tokens[i], tokens[j]).ratio()
        for i in range(len(tokens))
        for j in range(i + 1, len(tokens))
    ]
    return sum(scores) / len(scores)


# ----- warnings: commitments the case facts don't support -----------------------------------
# These don't fail a template check; they're shown to the agent (and counted in the test
# lab) because they're the mistakes that cost money or trust: promising a timeline nobody
# agreed to, or offering compensation nobody decided.

_NUMBER = r"(?:\d+|one|two|three|four|five|seven|ten|a few|a couple of)"
_UNIT = r"(?:business\s+|working\s+)?(?:hours?|days?|weeks?)"
_TIMEFRAME = re.compile(
    rf"\b(?:within|in the next|in)\s+{_NUMBER}\s+{_UNIT}\b"
    rf"|\b{_NUMBER}\s+(?:business|working)\s+days?\b"
    r"|\bby\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow"
    r"|tonight|the end of (?:the )?(?:day|week)|end of (?:the )?(?:day|week))\b",
    re.IGNORECASE,
)
_OFFER = re.compile(
    r"\b(?:arrang\w*|issu\w*|send\w*|offer\w*|process\w*|give|giving|provid\w*|refund you)\b"
    r"(?:\s+\w+){0,3}?\s+(?:a\s+|an\s+|your\s+|the\s+)?(?:full\s+|partial\s+)?"
    r"(?:refund|replacement|voucher|credit|discount|compensation|reimbursement)\b",
    re.IGNORECASE,
)
_ASKS_FOR_MONEY = re.compile(
    r"\b(?:refund|money back|compensat\w*|reimburs\w*|replacement|chargeback)\b", re.IGNORECASE
)


def unsupported_commitments(
    reply: str, facts: str, *, compensation: str | None, flagged: bool, customer_text: str
) -> list[str]:
    """Warnings for timelines and offers the facts don't support.

    `facts` is everything the model was given (case facts + conversation); a timeframe
    that appears there (e.g. a delivery promise from the order data) is fine.
    """
    warnings: list[str] = []
    lowered_facts = facts.lower()
    for match in dict.fromkeys(m.group(0) for m in _TIMEFRAME.finditer(reply)):
        if match.lower() not in lowered_facts:
            warnings.append(f'Promises a timeframe that isn\'t in the case: "{match}". Check it.')
    if not compensation:
        for match in dict.fromkeys(m.group(0) for m in _OFFER.finditer(reply)):
            warnings.append(f'Offers something no rule has decided: "{match}". Check it.')
        if not flagged and _ASKS_FOR_MONEY.search(customer_text):
            warnings.append(
                "The customer asked for money back or compensation and none is decided: "
                "an agent should review this request."
            )
    return warnings
