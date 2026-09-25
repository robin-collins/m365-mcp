"""Per-account rate limiting for tool calls (concept §12.5).

Each account has two token buckets that refill continuously:

- ``sensitive`` calls (send, share, delete): at most 20 per minute;
- all calls, sensitive ones included: at most 300 per minute.

A call is admitted only if every bucket it draws from has a whole token;
a refused call consumes nothing.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from typing import Literal

CallKind = Literal["sensitive", "normal"]

SENSITIVE_PER_MINUTE = 20
TOTAL_PER_MINUTE = 300
_PERIOD_SECONDS = 60.0
# Tolerance for floating-point refill arithmetic.
_EPSILON = 1e-9


class RateLimitError(Exception):
    """Raised when an account exceeds its call budget."""


class _Bucket:
    """A token bucket holding up to ``capacity`` tokens per minute."""

    def __init__(self, capacity: int, now: float) -> None:
        self.capacity = capacity
        self.tokens = float(capacity)
        self.updated = now

    def refill(self, now: float) -> None:
        elapsed = max(0.0, now - self.updated)
        self.tokens = min(
            float(self.capacity),
            self.tokens + elapsed * self.capacity / _PERIOD_SECONDS,
        )
        self.updated = now

    def wait_seconds(self) -> float:
        """Return how long until one whole token is available."""
        missing = 1.0 - self.tokens
        if missing <= _EPSILON:
            return 0.0
        return missing * _PERIOD_SECONDS / self.capacity


class RateLimiter:
    """Admit or refuse calls per account and call kind."""

    def __init__(
        self,
        sensitive_per_minute: int = SENSITIVE_PER_MINUTE,
        total_per_minute: int = TOTAL_PER_MINUTE,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Create a limiter.

        Args:
            sensitive_per_minute: Budget for send, share and delete calls.
            total_per_minute: Budget for all calls.
            clock: Monotonic clock in seconds.
        """
        self._limits = {
            "sensitive": sensitive_per_minute,
            "total": total_per_minute,
        }
        self._clock = clock
        self._buckets: dict[tuple[str, str], _Bucket] = {}
        self._lock = threading.Lock()

    def check(self, account_key: str, kind: CallKind) -> None:
        """Consume one call from the account's budget or refuse it.

        Args:
            account_key: Stable key for the account (ID or its hash).
            kind: ``sensitive`` for send, share and delete calls,
                ``normal`` for everything else.

        Raises:
            ValueError: If ``kind`` is not a known call kind.
            RateLimitError: If a budget is exhausted. The message says how
                long to wait.
        """
        if kind == "sensitive":
            names = ("sensitive", "total")
        elif kind == "normal":
            names = ("total",)
        else:
            raise ValueError(f"Unknown call kind: {kind!r}")

        with self._lock:
            now = self._clock()
            buckets = []
            for name in names:
                bucket = self._buckets.get((account_key, name))
                if bucket is None:
                    bucket = _Bucket(self._limits[name], now)
                    self._buckets[(account_key, name)] = bucket
                bucket.refill(now)
                buckets.append((name, bucket))

            for name, bucket in buckets:
                wait = bucket.wait_seconds()
                if wait > 0:
                    raise RateLimitError(_message(name, bucket, wait))
            for _, bucket in buckets:
                bucket.tokens = max(0.0, bucket.tokens - 1.0)


def _message(name: str, bucket: _Bucket, wait: float) -> str:
    """Build the actionable refusal text."""
    seconds = max(1, math.ceil(wait - _EPSILON))
    what = "send/share/delete calls" if name == "sensitive" else "calls"
    return (
        f"Rate limit: at most {bucket.capacity} {what} per minute; "
        f"try again in {seconds} s"
    )


rate_limiter = RateLimiter()
