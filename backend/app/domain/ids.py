"""Case numbers: the public, human-facing case ID.

A case number is the case's creation time as a Unix timestamp in
**microseconds**, e.g. 1790812345678901 (= 2026-10-01 ... UTC). It sorts by
creation time and reads as a plain number in URLs, emails and phone calls.

Each case also keeps a random UUID primary key (`cases.id`) used internally for
relationships between tables; only the case number is shown to people.

Uniqueness:
- Within one process, `next()` never returns the same number twice: if two
  cases are created in the same microsecond, the second gets +1.
- Across processes (several API servers, the worker), a database unique
  constraint catches the rare collision and the caller retries
  (see `CaseService.create_case`).

JavaScript can represent integers exactly only up to 2**53 - 1 (~9.007e15).
Microsecond timestamps stay below that until about the year 2255, so these
numbers are safe to send to the browser as plain JSON numbers.
"""

import threading
import time

JS_MAX_SAFE_INTEGER = 2**53 - 1


class MicrosecondIdGenerator:
    """Thread-safe, strictly increasing microsecond timestamps."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last = 0

    def next(self) -> int:
        with self._lock:
            now = time.time_ns() // 1_000
            self._last = max(now, self._last + 1)
            return self._last


_generator = MicrosecondIdGenerator()


def next_case_number() -> int:
    return _generator.next()
