"""Settings shared by connector calls and token requests."""

import time
from collections.abc import Callable
from dataclasses import dataclass

from app.security.ssrf import Resolver


@dataclass(frozen=True)
class RunSettings:
    allow_http: bool
    allowed_hosts: list[str]
    max_response_bytes: int
    resolve: Resolver
    sleep: Callable[[float], None] = time.sleep
