"""Unit tests for the calendar service layer."""

from __future__ import annotations

from datetime import UTC, datetime
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


def test_list_events_fetches_and_caches(
    monkeypatch: pytest.MonkeyPatch, cache: FakeCache
) -> None:
    captured = _patch_paginated(monkeypatch, [{"id": "e1"}])

    events = calendar_service.list_events(
        ACCOUNT, days_ahead=3, include_details=False, limit=10
    )

    assert captured["path"] == "/me/calendar/events"
    assert captured["account_id"] == ACCOUNT
    assert captured["limit"] == 10
    params = captured["params"]
    assert params["$top"] == 10
    assert params["$orderby"] == "start/dateTime"
    assert params["$select"] == (
        "id,subject,start,end,location,organizer,isAllDay,isCancelled"
    )
    assert params["$filter"].startswith("start/dateTime ge '")
    assert events[0]["id"] == "e1"
    assert events[0]["_cache_status"] == "fresh"
    assert "_cached_at" in events[0]
    assert cache.sets[0][1] == "calendar_list_events"
    assert cache.sets[0][2] == {
        "days_ahead": 3,
        "include_details": False,
        "limit": 10,
    }


def test_list_events_returns_cached(
    monkeypatch: pytest.MonkeyPatch, cache: FakeCache
) -> None:
    cache.cached = [{"id": "cached"}]
    _patch_paginated(monkeypatch, [])

    events = calendar_service.list_events(ACCOUNT, days_ahead=7)

    assert events == [{"id": "cached", "_cache_status": "stale"}]
    assert cache.sets == []


def test_get_event_fetches(monkeypatch: pytest.MonkeyPatch, cache: FakeCache) -> None:
    recorder = _patch_request(monkeypatch, {"id": "e1"})

    result = calendar_service.get_event(ACCOUNT, "e1")

    assert recorder.calls[0]["method"] == "GET"
    assert recorder.calls[0]["path"] == "/me/events/e1"
    assert result["id"] == "e1"
    assert result["_cache_status"] == "fresh"
    assert cache.sets[0][2] == {"event_id": "e1"}


def test_get_event_not_found(monkeypatch: pytest.MonkeyPatch, cache: FakeCache) -> None:
    _patch_request(monkeypatch, None)

    with pytest.raises(ValueError, match="Event with ID e1 not found"):
        calendar_service.get_event(ACCOUNT, "e1", use_cache=False)


def test_create_event_builds_body(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _patch_request(monkeypatch, {"id": "new"})
    start = datetime(2026, 1, 1, 10, tzinfo=UTC)
    end = datetime(2026, 1, 1, 11, tzinfo=UTC)

    result = calendar_service.create_event(
        ACCOUNT,
        subject="Sync",
        start=start,
        end=end,
        timezone_name="UTC",
        location="Room 1",
        body="Agenda",
        attendees=["a@example.com"],
    )

    assert result == {"id": "new"}
    call = recorder.calls[0]
    assert (call["method"], call["path"]) == ("POST", "/me/events")
    assert call["json"] == {
        "subject": "Sync",
        "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": end.isoformat(), "timeZone": "UTC"},
        "location": {"displayName": "Room 1"},
        "body": {"contentType": "Text", "content": "Agenda"},
        "attendees": [
            {"emailAddress": {"address": "a@example.com"}, "type": "required"}
        ],
    }


def test_update_event_builds_patch(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _patch_request(monkeypatch, None)

    result = calendar_service.update_event(
        ACCOUNT,
        "e1",
        subject="New",
        start="2026-01-01T10:00:00",
        location="  Room  ",
        attendees=[],
        timezone_name="Europe/London",
    )

    assert result == {"status": "updated"}
    call = recorder.calls[0]
    assert (call["method"], call["path"]) == ("PATCH", "/me/events/e1")
    assert call["json"] == {
        "subject": "New",
        "start": {
            "dateTime": "2026-01-01T10:00:00",
            "timeZone": "Europe/London",
        },
        "location": {"displayName": "Room"},
        "attendees": [],
    }


def test_delete_event_with_and_without_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _patch_request(monkeypatch)

    assert calendar_service.delete_event(ACCOUNT, "e1") == {"status": "deleted"}
    assert calendar_service.delete_event(ACCOUNT, "e2", send_cancellation=False) == {
        "status": "deleted"
    }

    assert recorder.calls[0]["method"] == "POST"
    assert recorder.calls[0]["path"] == "/me/events/e1/cancel"
    assert recorder.calls[0]["json"] == {}
    assert recorder.calls[1]["method"] == "DELETE"
    assert recorder.calls[1]["path"] == "/me/events/e2"


def test_respond_event(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _patch_request(monkeypatch)

    result = calendar_service.respond_event(
        ACCOUNT, "e1", response="decline", comment="Busy"
    )

    assert result == {"status": "decline"}
    assert recorder.calls[0]["path"] == "/me/events/e1/decline"
    assert recorder.calls[0]["json"] == {"sendResponse": True, "comment": "Busy"}


def test_check_availability_merges_user(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _patch_request(monkeypatch, {"mail": "Me@example.com"}, {"value": []})
    start = datetime(2026, 1, 1, 10, tzinfo=UTC)
    end = datetime(2026, 1, 1, 11, tzinfo=UTC)

    result = calendar_service.check_availability(
        ACCOUNT,
        start=start,
        end=end,
        attendees=["me@example.com", "b@example.com"],
    )

    assert result == {"value": []}
    assert recorder.calls[0]["path"] == (
        "/me?$select=mail,userPrincipalName,otherMails"
    )
    call = recorder.calls[1]
    assert call["path"] == "/me/calendar/getSchedule"
    assert call["json"]["schedules"] == ["Me@example.com", "b@example.com"]
    assert call["json"]["availabilityViewInterval"] == 30
    assert call["json"]["startTime"] == {
        "dateTime": start.isoformat(),
        "timeZone": "UTC",
    }


def test_check_availability_empty_result(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_request(monkeypatch, {"mail": "me@example.com"}, None)
    start = datetime(2026, 1, 1, 10, tzinfo=UTC)

    with pytest.raises(ValueError, match="Failed to check availability"):
        calendar_service.check_availability(ACCOUNT, start=start, end=start)


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


def test_list_calendars(monkeypatch: pytest.MonkeyPatch, cache: FakeCache) -> None:
    captured = _patch_paginated(monkeypatch, [{"id": "c1"}])

    result = calendar_service.list_calendars(ACCOUNT)

    assert captured["path"] == "/me/calendars"
    assert captured["params"] == {
        "$select": (
            "id,name,color,canEdit,canShare,canViewPrivateItems,owner,isDefaultCalendar"
        )
    }
    assert result[0]["_cache_status"] == "fresh"
    assert cache.sets[0][1:3] == ("calendar_list_calendars", {})


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


def test_delete_calendar_rejects_default(
    monkeypatch: pytest.MonkeyPatch, cache: FakeCache
) -> None:
    recorder = _patch_request(monkeypatch, {"isDefaultCalendar": True})

    with pytest.raises(ValueError, match="Cannot delete the default calendar"):
        calendar_service.delete_calendar(ACCOUNT, "c1")
    assert len(recorder.calls) == 1


def test_delete_calendar(monkeypatch: pytest.MonkeyPatch, cache: FakeCache) -> None:
    recorder = _patch_request(monkeypatch, {"isDefaultCalendar": False})

    assert calendar_service.delete_calendar(ACCOUNT, "c1") == {"status": "deleted"}
    assert recorder.calls[0]["path"] == ("/me/calendars/c1?$select=isDefaultCalendar")
    assert recorder.calls[1]["method"] == "DELETE"
    assert recorder.calls[1]["path"] == "/me/calendars/c1"
    assert cache.invalidations == [
        (f"calendar_list_calendars:{ACCOUNT}:*", "calendar_deleted")
    ]


def test_propose_new_time(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _patch_request(monkeypatch)
    start = datetime(2026, 1, 1, 10, tzinfo=UTC)
    end = datetime(2026, 1, 1, 11, tzinfo=UTC)

    result = calendar_service.propose_new_time(
        ACCOUNT, "e1", start=start, end=end, message=" later "
    )

    assert result == {"status": "proposed_new_time"}
    call = recorder.calls[0]
    assert call["path"] == "/me/events/e1/tentativelyAccept"
    assert call["json"]["sendResponse"] is True
    assert call["json"]["comment"] == "later"
    assert call["json"]["proposedNewTime"]["end"] == {
        "dateTime": end.isoformat(),
        "timeZone": "UTC",
    }


def test_get_free_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _patch_request(monkeypatch, {"value": ["x"]})
    start = datetime(2026, 1, 1, 10, tzinfo=UTC)
    end = datetime(2026, 1, 1, 11, tzinfo=UTC)

    result = calendar_service.get_free_busy(
        ACCOUNT,
        attendees=["a@example.com"],
        start=start,
        end=end,
        time_interval=15,
    )

    assert result == {"value": ["x"]}
    call = recorder.calls[0]
    assert call["path"] == "/me/calendar/getSchedule"
    assert call["json"]["schedules"] == ["a@example.com"]
    assert call["json"]["availabilityViewInterval"] == 15
