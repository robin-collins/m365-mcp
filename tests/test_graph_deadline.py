"""Fake-clock tests for the per-call deadline budget (task U2.9)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from src.m365_mcp import graph
from src.m365_mcp.errors import DeadlineExceeded, to_tool_error


class FakeClock:
    """Monotonic clock that only moves when told to."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class SlowClient:
    """Return queued outcomes; each request takes ``latency`` fake seconds."""

    def __init__(
        self, clock: FakeClock, outcomes: list[Any], latency: float = 0.0
    ) -> None:
        self.clock = clock
        self.outcomes = outcomes
        self.latency = latency
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append({"method": method, "url": url, **kwargs})
        self.clock.now += self.latency
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        outcome.request = httpx.Request(method, url)
        return outcome


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(graph, "_clock", fake)
    monkeypatch.setattr(graph.time, "sleep", fake.sleep)
    monkeypatch.setattr(graph, "get_token", lambda _a, force_refresh=False: "token")
    return fake


def _install(
    monkeypatch: pytest.MonkeyPatch,
    clock: FakeClock,
    *outcomes: Any,
    latency: float = 0.0,
) -> SlowClient:
    client = SlowClient(clock, list(outcomes), latency)
    monkeypatch.setattr(graph, "_client", client)
    return client


def _throttled(seconds: int) -> httpx.Response:
    return httpx.Response(429, headers={"Retry-After": str(seconds)})


def test_budgets_are_45_s_for_reads_and_60_s_for_writes() -> None:
    assert graph.READ_DEADLINE_SECONDS == 45
    assert graph.WRITE_DEADLINE_SECONDS == 60


def test_read_retry_within_budget_sleeps(
    monkeypatch: pytest.MonkeyPatch, clock: FakeClock
) -> None:
    _install(monkeypatch, clock, _throttled(30), httpx.Response(200, json={}))

    assert graph.request("GET", "/me", "acc-1") == {}
    assert clock.sleeps == [30.0]


def test_read_raises_before_a_sleep_that_would_exceed_45_s(
    monkeypatch: pytest.MonkeyPatch, clock: FakeClock
) -> None:
    client = _install(monkeypatch, clock, _throttled(30), _throttled(20))

    with pytest.raises(DeadlineExceeded) as info:
        graph.request("GET", "/me", "acc-1")

    # Slept 30 s once; 30 + 20 > 45 so it stops without sleeping again.
    assert clock.sleeps == [30.0]
    assert len(client.calls) == 2
    assert info.value.retry_after_seconds == 20
    assert "try again in 20 s" in str(to_tool_error(info.value))


def test_write_budget_is_60_s(
    monkeypatch: pytest.MonkeyPatch, clock: FakeClock
) -> None:
    _install(monkeypatch, clock, _throttled(30), _throttled(20), httpx.Response(204))

    # 30 + 20 = 50 fits in 60 s for a write (it would not for a read).
    assert graph.request("DELETE", "/me/messages/1", "acc-1") is None
    assert clock.sleeps == [30.0, 20.0]


def test_write_raises_when_retry_after_exceeds_budget(
    monkeypatch: pytest.MonkeyPatch, clock: FakeClock
) -> None:
    _install(monkeypatch, clock, _throttled(45), _throttled(30))

    with pytest.raises(DeadlineExceeded) as info:
        graph.request("POST", "/me/sendMail", "acc-1", json={"m": 1})

    assert clock.sleeps == [45.0]
    assert info.value.retry_after_seconds == 30


def test_slow_responses_count_against_the_budget(
    monkeypatch: pytest.MonkeyPatch, clock: FakeClock
) -> None:
    """Time spent waiting on Graph counts, not only sleeps."""
    _install(monkeypatch, clock, httpx.Response(500), latency=44.5)

    with pytest.raises(DeadlineExceeded) as info:
        graph.request("GET", "/me", "acc-1")

    assert clock.sleeps == []
    assert info.value.retry_after_seconds == 1


def test_network_error_retry_is_checked_against_budget(
    monkeypatch: pytest.MonkeyPatch, clock: FakeClock
) -> None:
    _install(monkeypatch, clock, httpx.ConnectError("down"), latency=50.0)

    with pytest.raises(DeadlineExceeded) as info:
        graph.request("GET", "/me", "acc-1")

    assert isinstance(info.value.__cause__, httpx.ConnectError)


def test_401_refresh_retry_is_checked_against_budget(
    monkeypatch: pytest.MonkeyPatch, clock: FakeClock
) -> None:
    client = _install(monkeypatch, clock, httpx.Response(401), latency=46.0)

    with pytest.raises(DeadlineExceeded):
        graph.request("GET", "/me", "acc-1")
    assert len(client.calls) == 1


def test_final_error_within_budget_is_a_graph_error_not_deadline(
    monkeypatch: pytest.MonkeyPatch, clock: FakeClock
) -> None:
    _install(monkeypatch, clock, httpx.Response(404), latency=100.0)

    with pytest.raises(httpx.HTTPStatusError):
        graph.request("GET", "/me/messages/x", "acc-1")


def test_chunked_upload_is_exempt(
    monkeypatch: pytest.MonkeyPatch, clock: FakeClock
) -> None:
    monkeypatch.setattr(graph, "UPLOAD_CHUNK_SIZE", 4)
    _install(
        monkeypatch,
        clock,
        httpx.Response(503, headers={"Retry-After": "60"}),
        httpx.Response(202),
        httpx.Response(503, headers={"Retry-After": "60"}),
        httpx.Response(201),
        latency=30.0,
    )

    assert graph._do_chunked_upload("https://upload.example/s", b"abcdef") == {}
    assert clock.sleeps == [60.0, 60.0]


def test_download_is_exempt(monkeypatch: pytest.MonkeyPatch, clock: FakeClock) -> None:
    _install(
        monkeypatch,
        clock,
        _throttled(40),
        _throttled(40),
        httpx.Response(200, content=b"data"),
        latency=10.0,
    )

    assert graph.download_raw("/me/drive/items/1/content", "acc-1") == b"data"
    assert clock.sleeps == [40.0, 40.0]


def test_default_clock_is_monotonic() -> None:
    import time

    assert graph._clock is time.monotonic
