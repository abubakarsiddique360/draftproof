"""API security: optional key authentication and a token-bucket limiter."""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable

from draftproof.domain.errors import RateLimitedError, UnauthorizedError


class ApiKeyGuard:
    """Constant-time API key check."""

    def __init__(self, expected: str | None) -> None:
        self._expected = expected

    @property
    def enabled(self) -> bool:
        return bool(self._expected)

    def check(self, provided: str | None) -> None:
        """Raise ``UnauthorizedError`` when the key is missing or wrong."""
        if not self._expected:
            return
        if not provided or not secrets.compare_digest(provided, self._expected):
            raise UnauthorizedError(
                "A valid API key is required",
                hint="Send the key in the X-API-Key header.",
            )


class TokenBucketLimiter:
    """Per-client token bucket.

    Limits are per process. Deployments with several replicas should enforce a
    shared limit at the edge as well; this guard exists to protect a single
    instance from accidental request storms.
    """

    def __init__(
        self,
        per_minute: int,
        *,
        burst: int | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._rate = max(0.0, per_minute / 60.0)
        self._capacity = float(burst if burst is not None else max(1, per_minute))
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: dict[str, tuple[float, float]] = {}

    @property
    def enabled(self) -> bool:
        return self._rate > 0

    def allow(self, key: str) -> bool:
        """Consume one token for ``key`` and report success."""
        if not self.enabled:
            return True
        now = self._clock()
        with self._lock:
            tokens, last = self._buckets.get(key, (self._capacity, now))
            tokens = min(self._capacity, tokens + (now - last) * self._rate)
            if tokens < 1.0:
                self._buckets[key] = (tokens, now)
                return False
            self._buckets[key] = (tokens - 1.0, now)
            if len(self._buckets) > 10_000:  # pragma: no cover - defensive pruning
                self._buckets.clear()
            return True

    def check(self, key: str) -> None:
        """Raise ``RateLimitedError`` when the bucket is empty."""
        if not self.allow(key):
            raise RateLimitedError(
                "Too many requests",
                hint="Slow down, or raise DRAFTPROOF_RATE_LIMIT_PER_MINUTE.",
            )


def client_key(host: str | None, api_key: str | None) -> str:
    """Derive a stable rate-limit key for a request."""
    if api_key:
        return f"key:{api_key[:12]}"
    return f"host:{host or 'unknown'}"
