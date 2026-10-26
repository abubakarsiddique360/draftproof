"""API key enforcement and rate limiting."""

from __future__ import annotations

import pytest

from draftproof.api.security import ApiKeyGuard, TokenBucketLimiter, client_key
from draftproof.domain.errors import RateLimitedError, UnauthorizedError


def test_guard_disabled_allows_anything() -> None:
    guard = ApiKeyGuard(None)
    assert guard.enabled is False
    guard.check(None)
    guard.check("anything")


def test_guard_requires_matching_key() -> None:
    guard = ApiKeyGuard("s3cret")
    assert guard.enabled is True
    guard.check("s3cret")
    with pytest.raises(UnauthorizedError):
        guard.check(None)
    with pytest.raises(UnauthorizedError):
        guard.check("wrong")


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_token_bucket_limits_and_refills() -> None:
    clock = _Clock()
    limiter = TokenBucketLimiter(60, burst=2, clock=clock)
    assert limiter.allow("client")
    assert limiter.allow("client")
    assert not limiter.allow("client")
    clock.now += 1.0  # one token per second at 60/minute
    assert limiter.allow("client")


def test_token_bucket_is_per_client() -> None:
    limiter = TokenBucketLimiter(60, burst=1, clock=_Clock())
    assert limiter.allow("a")
    assert not limiter.allow("a")
    assert limiter.allow("b")


def test_limiter_raises_when_exhausted() -> None:
    limiter = TokenBucketLimiter(60, burst=1, clock=_Clock())
    limiter.check("a")
    with pytest.raises(RateLimitedError):
        limiter.check("a")


def test_limiter_zero_disables() -> None:
    limiter = TokenBucketLimiter(0)
    assert limiter.enabled is False
    for _ in range(100):
        assert limiter.allow("a")


def test_client_key_prefers_api_key() -> None:
    assert client_key("1.2.3.4", "abcdef123456") == "key:abcdef123456"
    assert client_key("1.2.3.4", None) == "host:1.2.3.4"
    assert client_key(None, None) == "host:unknown"
