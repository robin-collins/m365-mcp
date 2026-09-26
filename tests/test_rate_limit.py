"""Tests for per-account rate limiting (task U2.14)."""

from __future__ import annotations

import pytest

from src.m365_mcp.rate_limit import RateLimiter, RateLimitError


class FakeClock:
    """Controllable monotonic clock."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def limiter(clock: FakeClock) -> RateLimiter:
    return RateLimiter(clock=clock)


def test_twenty_sensitive_calls_then_refused(
    limiter: RateLimiter, clock: FakeClock
) -> None:
    for _ in range(20):
        limiter.check("acc-1", "sensitive")

    with pytest.raises(RateLimitError) as exc:
        limiter.check("acc-1", "sensitive")
    assert str(exc.value) == (
        "Rate limit: at most 20 send/share/delete calls per minute; try again in 3 s"
    )


def test_sensitive_bucket_refills_over_time(
    limiter: RateLimiter, clock: FakeClock
) -> None:
    for _ in range(20):
        limiter.check("acc-1", "sensitive")

    start = clock.now
    clock.now = start + 2.9
    with pytest.raises(RateLimitError):
        limiter.check("acc-1", "sensitive")

    clock.now = start + 3.0
    limiter.check("acc-1", "sensitive")


def test_full_minute_restores_full_budget(
    limiter: RateLimiter, clock: FakeClock
) -> None:
    for _ in range(20):
        limiter.check("acc-1", "sensitive")
    clock.now += 60

    for _ in range(20):
        limiter.check("acc-1", "sensitive")
    with pytest.raises(RateLimitError):
        limiter.check("acc-1", "sensitive")


def test_normal_calls_not_limited_by_sensitive_budget(
    limiter: RateLimiter,
) -> None:
    for _ in range(20):
        limiter.check("acc-1", "sensitive")

    limiter.check("acc-1", "normal")


def test_three_hundred_calls_then_refused(limiter: RateLimiter) -> None:
    for _ in range(300):
        limiter.check("acc-1", "normal")

    with pytest.raises(RateLimitError) as exc:
        limiter.check("acc-1", "normal")
    assert str(exc.value) == (
        "Rate limit: at most 300 calls per minute; try again in 1 s"
    )


def test_sensitive_calls_count_towards_total(limiter: RateLimiter) -> None:
    for _ in range(290):
        limiter.check("acc-1", "normal")
    for _ in range(10):
        limiter.check("acc-1", "sensitive")

    with pytest.raises(RateLimitError, match="300 calls"):
        limiter.check("acc-1", "sensitive")


def test_refused_call_consumes_nothing(limiter: RateLimiter) -> None:
    for _ in range(20):
        limiter.check("acc-1", "sensitive")
    for _ in range(5):
        with pytest.raises(RateLimitError):
            limiter.check("acc-1", "sensitive")

    # The refused calls did not use any of the remaining 280 total tokens.
    for _ in range(280):
        limiter.check("acc-1", "normal")
    with pytest.raises(RateLimitError, match="300 calls"):
        limiter.check("acc-1", "normal")


def test_accounts_are_isolated(limiter: RateLimiter) -> None:
    for _ in range(20):
        limiter.check("acc-1", "sensitive")

    limiter.check("acc-2", "sensitive")


def test_retry_hint_is_rounded_up(limiter: RateLimiter, clock: FakeClock) -> None:
    for _ in range(20):
        limiter.check("acc-1", "sensitive")
    clock.now += 0.5

    with pytest.raises(RateLimitError, match=r"try again in 3 s$"):
        limiter.check("acc-1", "sensitive")


def test_unknown_kind_is_rejected(limiter: RateLimiter) -> None:
    with pytest.raises(ValueError):
        limiter.check("acc-1", "bulk")  # type: ignore[arg-type]
