"""Lightweight in-process rate limiting for sensitive FastAPI routes.

The legacy Flask app declared `@limiter.limit(...)` on login/register but the
decorators were commented out ("Temporarily disabled for debugging"), so those
endpoints were never actually rate-limited. This restores real limiting on the
FastAPI side.

A fixed-window counter keyed by client IP + route. In-process (per worker) — fine
as a brute-force speed bump; swap for a Redis-backed limiter if you run many
workers and need a global limit. Disabled automatically under pytest so the
suite isn't throttled, and via the GAPI_DISABLE_RATELIMIT env var.
"""
import os
import sys
import threading
import time
from collections import defaultdict

from fastapi import HTTPException, Request, status

_LOCK = threading.Lock()
_HITS: dict[str, list] = defaultdict(list)  # key -> [monotonic timestamps]


def _enabled() -> bool:
    if os.environ.get("GAPI_DISABLE_RATELIMIT") == "1":
        return False
    if "pytest" in sys.modules:  # never throttle the test suite
        return False
    return True


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(name: str, limit: int, window_seconds: int):
    """Return a FastAPI dependency enforcing `limit` requests per window per IP."""

    def dependency(request: Request) -> None:
        if not _enabled():
            return
        key = f"{name}:{_client_ip(request)}"
        now = time.monotonic()
        cutoff = now - window_seconds
        with _LOCK:
            hits = [t for t in _HITS[key] if t > cutoff]
            if len(hits) >= limit:
                hits.append(now)
                _HITS[key] = hits
                retry = max(1, int(window_seconds - (now - hits[0])))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many requests. Please slow down.",
                    headers={"Retry-After": str(retry)},
                )
            hits.append(now)
            _HITS[key] = hits

    return dependency


def reset() -> None:
    """Clear all counters (used by tests)."""
    with _LOCK:
        _HITS.clear()
