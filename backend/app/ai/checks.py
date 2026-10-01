"""Automated checks a reply template can define, applied to every draft.

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
