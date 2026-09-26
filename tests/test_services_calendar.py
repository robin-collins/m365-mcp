"""Unit tests for the calendar service layer."""

from __future__ import annotations

from typing import Any

import pytest

from src.m365_mcp.services import calendar as calendar_service

ACCOUNT = "acct-1"


class FakeCacheState:
    """Minimal stand-in for a cache state enum member."""

    value = "stale"


class FakeCache:
    """Record cache calls and optionally serve a cached value."""

    def __init__(self, cached: Any = None) -> None:
        self.cached = cached
        self.gets: list[tuple[Any, ...]] = []
        self.sets: list[tuple[Any, ...]] = []
        self.invalidations: list[tuple[str, str]] = []

    def get_cached(self, account_id: str, op: str, params: dict[str, Any]) -> Any:
        self.gets.append((account_id, op, params))
        if self.cached is None:
            return None
        return self.cached, FakeCacheState()

    def set_cached(
        self, account_id: str, op: str, params: dict[str, Any], data: Any
    ) -> None:
        self.sets.append((account_id, op, params, data))

    def invalidate_pattern(self, pattern: str, reason: str) -> None:
        self.invalidations.append((pattern, reason))


class Recorder:
    """Capture graph.request calls and return queued responses."""

    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        method: str,
        path: str,
        account_id: str | None = None,
        **kwargs: Any,
    ) -> Any:
        self.calls.append(
            {
                "method": method,
                "path": path,
                "account_id": account_id,
                "json": kwargs.get("json"),
            }
        )
        return self.responses.pop(0) if self.responses else None


@pytest.fixture
def cache(monkeypatch: pytest.MonkeyPatch) -> FakeCache:
    fake = FakeCache()
    monkeypatch.setattr(calendar_service, "_get_cache_manager", lambda: fake)
    return fake


def _patch_request(monkeypatch: pytest.MonkeyPatch, *responses: Any) -> Recorder:
    recorder = Recorder(*responses)
    monkeypatch.setattr(calendar_service.graph, "request", recorder)
    return recorder


def _patch_paginated(
    monkeypatch: pytest.MonkeyPatch, items: list[dict[str, Any]]
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake(path: str, account_id: str, **kwargs: Any) -> Any:
        captured["path"] = path
        captured["account_id"] = account_id
        captured.update(kwargs)
        return iter(items)

    monkeypatch.setattr(calendar_service.graph, "request_paginated", fake)
    return captured


def test_forward_event(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _patch_request(monkeypatch)

    result = calendar_service.forward_event(
        ACCOUNT,
        "e1",
        to=["a@example.com"],
        cc=["c@example.com"],
        message="  FYI ",
    )

    assert result == {"status": "forwarded"}
    call = recorder.calls[0]
    assert call["path"] == "/me/events/e1/forward"
    assert call["json"] == {
        "toRecipients": [{"emailAddress": {"address": "a@example.com"}}],
        "ccRecipients": [{"emailAddress": {"address": "c@example.com"}}],
        "comment": "FYI",
    }


def test_create_calendar_invalidates(
    monkeypatch: pytest.MonkeyPatch, cache: FakeCache
) -> None:
    recorder = _patch_request(monkeypatch, {"id": "c1"})

    result = calendar_service.create_calendar(ACCOUNT, name="Work")

    assert result == {"id": "c1"}
    assert recorder.calls[0]["path"] == "/me/calendars"
    assert recorder.calls[0]["json"] == {"name": "Work"}
    assert cache.invalidations == [
        (f"calendar_list_calendars:{ACCOUNT}:*", "calendar_created")
    ]
