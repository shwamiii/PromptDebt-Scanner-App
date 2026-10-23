"""Simple in-memory, per-IP rate limiting (sliding one-minute window).

Good enough for a single server process. Counts reset when the server restarts.
"""

import time
from collections import defaultdict, deque

from fastapi import Request

from .config import TRUST_PROXY
from .errors import ApiError

WINDOW_SECONDS = 60


def client_ip(request: Request) -> str:
    """Caller's IP. Behind a proxy (TRUST_PROXY=1), the first X-Forwarded-For entry."""
    forwarded = request.headers.get("x-forwarded-for")
    if TRUST_PROXY and forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimiter:
    def __init__(self, per_minute: int, action: str) -> None:
        self.per_minute = per_minute
        self.action = action
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def __call__(self, request: Request) -> None:
        """FastAPI dependency: raises 429 once an IP exceeds the limit."""
        now = time.monotonic()
        hits = self.hits[client_ip(request)]
        while hits and now - hits[0] >= WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= self.per_minute:
            wait = int(WINDOW_SECONDS - (now - hits[0])) + 1
            raise ApiError(
                429, "rate_limited", f"Too many {self.action}. Try again in {wait} seconds."
            )
        hits.append(now)
