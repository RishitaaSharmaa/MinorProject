"""Small in-process sliding-window rate limiter for public endpoints."""

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from app.config import get_settings


class RateLimiter:
    """Slow credential stuffing and sign-up / lead-form spam."""

    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit, self.window = limit, window_seconds
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        hits = self.hits[key]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            raise HTTPException(status_code=429, detail="Too many attempts. Try again in a few minutes.")
        hits.append(now)
        if len(self.hits) > 10_000:  # drop idle keys so the table cannot grow without bound
            for stale in [k for k, v in self.hits.items() if not v or now - v[-1] > self.window]:
                del self.hits[stale]


def client_key(request: Request, extra: str = "") -> str:
    """Caller identity. Behind the bundled nginx every request comes from the proxy's address,
    so with `TRUST_PROXY_HEADERS=true` use the real client IP nginx puts in `X-Real-IP`."""
    host = request.client.host if request.client else "unknown"
    if get_settings().trust_proxy_headers:
        host = request.headers.get("x-real-ip", host)
    return f"{host}|{extra}"
