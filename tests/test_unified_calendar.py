"""Unified calendar handlers: event/calendar resources and calendar tools.

Covers U3.1/U3.2/U3.5/U3.8 (event and calendar parts), U3.13, U3.14,
U3.15 and U3.23 against the fake Graph.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from m365_mcp.rate_limit import rate_limiter
from m365_mcp.services import calendar as cal_service
from m365_mcp.tool_specs import load_tool_spec
from m365_mcp.tools.unified import calendar as cal_tools
from tests.unified_harness import UnifiedHarness

ADELAIDE_WINDOWS = "Cen. Australia Standard Time"
CONFIRM_TEXT = (
    "Invalid confirm 'False': {action} requires confirm=True to proceed. "
    "Expected: Explicit user confirmation"
)


@pytest.fixture(autouse=True)
def _fresh_rate_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rate_limiter, "_buckets", {})


def _example(tool: str, index: int = 0) -> dict[str, Any]:
    return load_tool_spec(tool)["examples"][index]


def _adelaide(harness: UnifiedHarness) -> None:
    harness.fake.mailbox_settings["timeZone"] = ADELAIDE_WINDOWS


def _seed_event(
    harness: UnifiedHarness,
    event_id: str,
    subject: str,
    start: str,
    end: str,
    **extra: Any,
) -> dict[str, Any]:
    """Seed an event with UTC wall times (``2026-10-01T23:30:00``)."""
    event = {
        "id": event_id,
        "subject": subject,
        "start": {"dateTime": start + ".0000000", "timeZone": "UTC"},
        "end": {"dateTime": end + ".0000000", "timeZone": "UTC"},
        "isAllDay": False,
        "location": {"displayName": extra.pop("location", "")},
        "body": {"contentType": "text", "content": extra.pop("body", "")},
        "bodyPreview": "",
        "organizer": {
            "emailAddress": {"name": "Robin", "address": "robin@example.com"}
        },
        "isOrganizer": True,
        "attendees": [],
        "responseStatus": {"response": "organizer"},
        "showAs": "busy",
        "calendarId": "cal-default",
        "type": "singleInstance",
        "webLink": f"https://outlook.live.com/calendar/item/{event_id}",
    }
    event.update(extra)
    harness.fake.events[event_id] = event
    return event


def _attendee(address: str, name: str | None = None) -> dict[str, Any]:
    return {
        "emailAddress": {"name": name or address, "address": address},
        "type": "required",
        "status": {"response": "none", "time": "0001-01-01T00:00:00Z"},
    }


def _fail(
    harness: UnifiedHarness,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    outcome: Any,
) -> None:
    """Make ``method path`` fail with a status code or raise an exception."""
    original = harness.fake.dispatch

    def dispatch(m: str, p: str, params: dict[str, str], body: Any) -> Any:
        if m.upper() == method and p == path:
            if isinstance(outcome, int):
                return harness.fake._error(outcome, "Boom", "Something failed.")
            raise outcome
        return original(m, p, params, body)

    monkeypatch.setattr(harness.fake, "dispatch", dispatch)


# ----------------------------------------------------------------------
# services helpers
# ----------------------------------------------------------------------


def test_windows_time_zone_map_resolves_to_real_iana_zones() -> None:
    from zoneinfo import ZoneInfo

    for iana in cal_service.WINDOWS_TIME_ZONES.values():
        ZoneInfo(iana)
    assert cal_service.to_iana_time_zone(ADELAIDE_WINDOWS) == "Australia/Adelaide"
    assert cal_service.to_iana_time_zone("Europe/Paris") == "Europe/Paris"
    assert cal_service.to_iana_time_zone("tzone://Microsoft/Custom") is None
    assert cal_service.to_iana_time_zone(None) is None


# ----------------------------------------------------------------------
# m365_list event / calendar (U3.1)
# ----------------------------------------------------------------------


def test_list_events_uses_calendar_view_on_default_calendar(
    harness: UnifiedHarness,
) -> None:
    data = harness.ok(
        "m365_list",
        {
            "resource": "event",
            "start": "2026-09-28T00:00:00Z",
            "end": "2026-10-03T00:00:00Z",
            "limit": 50,
        },
    )
    calls = harness.graph_calls("GET", "/me/calendar/calendarView")
    assert len(calls) == 1
    assert calls[0].params["startDateTime"] == "2026-09-28T00:00:00Z"
    assert calls[0].params["endDateTime"] == "2026-10-03T00:00:00Z"
    ids = [i["id"] for i in data["items"]]
    assert "evt-dentist" in ids and "evt-gym" in ids
    assert "evt-birthday" not in ids  # other calendar
    starts = [i["start"] for i in data["items"]]
    assert starts == sorted(starts)
    assert data["has_more"] is False and data["next_cursor"] is None
    assert data["items"][0]["time_zone"] == "UTC"


def test_list_events_on_named_calendar(harness: UnifiedHarness) -> None:
    data = harness.ok(
        "m365_list",
        {
            "resource": "event",
            "container_id": "cal-family",
            "start": "2026-09-28T00:00:00Z",
            "end": "2026-10-06T00:00:00Z",
        },
    )
    assert harness.graph_calls("GET", "/me/calendars/cal-family/calendarView")
    assert [i["id"] for i in data["items"]] == ["evt-birthday"]
    assert data["items"][0]["calendar_id"] == "cal-family"


def test_list_events_expands_recurrences_via_calendar_view(
    harness: UnifiedHarness,
) -> None:
    # calendarView returns one instance per occurrence; standups are seeded
    # as a daily series of instances.
    data = harness.ok(
        "m365_list",
        {
            "resource": "event",
            "start": "2026-09-28T00:00:00Z",
            "end": "2026-10-03T00:00:00Z",
            "limit": 50,
        },
    )
    standups = [i for i in data["items"] if i["subject"] == "Team standup"]
    assert len(standups) == 5


def test_list_events_default_window_is_now_plus_seven_days(
    harness: UnifiedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cal_tools, "now", lambda: datetime(2026, 9, 28, 6, 0, tzinfo=UTC)
    )
    harness.ok("m365_list", {"resource": "event"})
    call = harness.graph_calls("GET", "/me/calendar/calendarView")[0]
    assert call.params["startDateTime"] == "2026-09-28T06:00:00Z"
    assert call.params["endDateTime"] == "2026-10-05T06:00:00Z"


def test_list_events_end_defaults_to_start_plus_seven_days(
    harness: UnifiedHarness,
) -> None:
    harness.ok("m365_list", {"resource": "event", "start": "2026-10-01T00:00:00+09:30"})
    call = harness.graph_calls("GET", "/me/calendar/calendarView")[0]
    assert call.params["startDateTime"] == "2026-09-30T14:30:00Z"
    assert call.params["endDateTime"] == "2026-10-07T14:30:00Z"


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-10-02T00:00:00Z", "2026-10-01T00:00:00Z"),
        ("2026-10-01T00:00:00Z", "2026-10-01T00:00:00Z"),
        ("2026-01-01T00:00:00Z", "2027-01-02T00:00:01Z"),
    ],
)
def test_list_events_window_rule(harness: UnifiedHarness, start: str, end: str) -> None:
    assert harness.error(
        "m365_list", {"resource": "event", "start": start, "end": end}
    ) == (
        "Invalid end: must be after start and within 366 days. "
        "Expected: a later RFC 3339 date-time"
    )
    assert not harness.graph_calls("GET", "/me/calendar/calendarView")


def test_list_events_window_of_exactly_366_days_is_allowed(
    harness: UnifiedHarness,
) -> None:
    harness.ok(
        "m365_list",
        {
            "resource": "event",
            "start": "2026-01-01T00:00:00Z",
            "end": "2027-01-02T00:00:00Z",
        },
    )


def test_list_events_in_mailbox_time_zone(harness: UnifiedHarness) -> None:
    _adelaide(harness)
    data = harness.ok(
        "m365_list",
        {
            "resource": "event",
            "start": "2026-09-29T00:00:00Z",
            "end": "2026-09-30T00:00:00Z",
        },
    )
    dentist = next(i for i in data["items"] if i["id"] == "evt-dentist")
    assert dentist["time_zone"] == "Australia/Adelaide"
    assert dentist["start"] == "2026-09-29T19:30:00+09:30"
    assert harness.graph_calls("GET", "/me/mailboxSettings/timeZone")


def test_list_events_cursor_pages_through_the_window(harness: UnifiedHarness) -> None:
    args = {
        "resource": "event",
        "start": "2026-09-28T00:00:00Z",
        "end": "2026-10-03T00:00:00Z",
        "limit": 3,
    }
    first = harness.ok("m365_list", args)
    assert first["has_more"] is True and first["next_cursor"]
    second = harness.ok("m365_list", {**args, "cursor": first["next_cursor"]})
    first_ids = {i["id"] for i in first["items"]}
    assert len(second["items"]) == 3
    assert not first_ids & {i["id"] for i in second["items"]}
    assert "pass next_cursor for more" in first["summary"]

    text = harness.error(
        "m365_list", {**args, "limit": 4, "cursor": first["next_cursor"]}
    )
    assert text == (
        "Invalid cursor: it does not match this request. "
        "Expected: repeat the call without cursor"
    )


def test_list_calendars(harness: UnifiedHarness) -> None:
    data = harness.ok("m365_list", {"resource": "calendar"})
    assert harness.graph_calls("GET", "/me/calendars")
    by_id = {c["id"]: c for c in data["items"]}
    assert by_id["cal-default"] == {
        "id": "cal-default",
        "name": "Calendar",
        "is_default": True,
        "can_edit": True,
        "color": None,
    }
    assert by_id["cal-family"]["color"] == "lightGreen"
    assert data["has_more"] is False


def test_list_calendars_cursor(harness: UnifiedHarness) -> None:
    first = harness.ok("m365_list", {"resource": "calendar", "limit": 2})
    assert len(first["items"]) == 2 and first["has_more"] is True
    second = harness.ok(
        "m365_list",
        {"resource": "calendar", "limit": 2, "cursor": first["next_cursor"]},
    )
    assert [c["id"] for c in second["items"]] == ["cal-roster"]
    assert second["next_cursor"] is None


# ----------------------------------------------------------------------
# m365_get event / calendar (U3.2)
# ----------------------------------------------------------------------


def test_get_event_with_attendees_and_body(harness: UnifiedHarness) -> None:
    data = harness.ok("m365_get", {"resource": "event", "id": "evt-planning"})
    assert harness.graph_calls("GET", "/me/events/evt-planning")
    item = data["item"]
    assert item["body"] == "Plan Q4 priorities."
    assert item["body_truncated"] is False
    assert item["attendee_count"] == 2
    seeded = harness.fake.events["evt-planning"]["attendees"]
    assert [a["address"] for a in item["attendees"]] == [
        a["emailAddress"]["address"] for a in seeded
    ]
    assert all(a["type"] == "required" for a in item["attendees"])
    assert item["is_organizer"] is True and item["recurrence"] is None
    assert "2 attendees" in data["summary"]


def test_get_event_truncates_body_and_can_omit_it(harness: UnifiedHarness) -> None:
    _seed_event(
        harness,
        "evt-long",
        "Long",
        "2026-10-01T01:00:00",
        "2026-10-01T02:00:00",
        body="x" * 900,
    )
    data = harness.ok(
        "m365_get", {"resource": "event", "id": "evt-long", "body_max_chars": 500}
    )
    assert data["item"]["body"] == "x" * 500
    assert data["item"]["body_truncated"] is True
    data = harness.ok(
        "m365_get",
        {"resource": "event", "id": "evt-long", "include_body": False},
    )
    assert data["item"]["body"] is None
    assert data["item"]["body_truncated"] is False


def test_get_event_recurrence_summary(harness: UnifiedHarness) -> None:
    _seed_event(
        harness,
        "evt-series",
        "Book club",
        "2026-10-05T08:00:00",
        "2026-10-05T09:00:00",
        type="seriesMaster",
        recurrence={
            "pattern": {"type": "weekly", "interval": 2, "daysOfWeek": ["monday"]},
            "range": {
                "type": "endDate",
                "startDate": "2026-10-05",
                "endDate": "2026-12-21",
            },
        },
    )
    item = harness.ok("m365_get", {"resource": "event", "id": "evt-series"})["item"]
    assert item["recurrence"] == (
        "Every 2 weeks on Monday, from 2026-10-05 until 2026-12-21"
    )


def test_get_calendar_default_alias_and_id(harness: UnifiedHarness) -> None:
    data = harness.ok("m365_get", {"resource": "calendar", "id": "default"})
    assert harness.graph_calls("GET", "/me/calendar")
    assert data["item"]["id"] == "cal-default" and data["item"]["is_default"]
    data = harness.ok("m365_get", {"resource": "calendar", "id": "cal-family"})
    assert harness.graph_calls("GET", "/me/calendars/cal-family")
    assert data["item"]["name"] == "Family"


# ----------------------------------------------------------------------
# m365_create calendar (U3.5)
# ----------------------------------------------------------------------


def test_create_calendar(harness: UnifiedHarness) -> None:
    data = harness.ok(
        "m365_create", {"resource": "calendar", "calendar": {"name": "Holidays"}}
    )
    call = harness.graph_calls("POST", "/me/calendars")[0]
    assert call.body == {"name": "Holidays"}
    assert data["resource"] == "calendar"
    assert data["item"]["name"] == "Holidays"
    assert data["item"]["is_default"] is False
    assert data["summary"] == "Created calendar 'Holidays'."


def test_create_calendar_rejects_other_sub_objects(harness: UnifiedHarness) -> None:
    assert harness.error(
        "m365_create",
        {
            "resource": "calendar",
            "calendar": {"name": "X"},
            "contact": {"given_name": "Sam"},
        },
    ) == (
        "Invalid contact: resource is 'calendar'. Expected: supply only the "
        "'calendar' object"
    )


# ----------------------------------------------------------------------
# m365_delete event / calendar (U3.8)
# ----------------------------------------------------------------------


def test_delete_meeting_as_organiser_cancels_with_comment(
    harness: UnifiedHarness,
) -> None:
    data = harness.ok(
        "m365_delete",
        {
            "resource": "event",
            "id": "evt-planning",
            "cancellation_message": "Sorry, moving this to next quarter.",
            "confirm": True,
        },
    )
    call = harness.graph_calls("POST", "/me/events/evt-planning/cancel")[0]
    assert call.body == {"comment": "Sorry, moving this to next quarter."}
    assert not harness.graph_calls("DELETE", "/me/events/evt-planning")
    assert data["status"] == "cancelled_and_deleted"
    assert data["recoverable"] is False
    assert "evt-planning" not in harness.fake.events


def test_delete_private_event_uses_delete(harness: UnifiedHarness) -> None:
    data = harness.ok(
        "m365_delete", {"resource": "event", "id": "evt-dentist", "confirm": True}
    )
    assert harness.graph_calls("DELETE", "/me/events/evt-dentist")
    assert not harness.graph_calls("POST", "/me/events/evt-dentist/cancel")
    assert data == {
        "resource": "event",
        "id": "evt-dentist",
        "status": "deleted",
        "recoverable": False,
        "summary": "Deleted 'Dentist appointment' from your calendar.",
    }


def test_delete_invitation_as_attendee_uses_delete(harness: UnifiedHarness) -> None:
    data = harness.ok(
        "m365_delete", {"resource": "event", "id": "evt-sync", "confirm": True}
    )
    assert harness.graph_calls("DELETE", "/me/events/evt-sync")
    assert data["status"] == "deleted"


def test_delete_event_requires_confirm(harness: UnifiedHarness) -> None:
    assert harness.error(
        "m365_delete", {"resource": "event", "id": "evt-dentist", "confirm": False}
    ) == CONFIRM_TEXT.format(action="delete")
    assert "evt-dentist" in harness.fake.events


def test_cancellation_message_only_for_events(harness: UnifiedHarness) -> None:
    assert (
        harness.error(
            "m365_delete",
            {
                "resource": "calendar",
                "id": "cal-roster",
                "cancellation_message": "x",
                "confirm": True,
            },
        )
        == "Invalid cancellation_message: only valid for resource='event'"
    )


@pytest.mark.parametrize("outcome", [500, 504, httpx.ReadTimeout("slow")])
def test_delete_event_outcome_unknown(
    harness: UnifiedHarness, monkeypatch: pytest.MonkeyPatch, outcome: Any
) -> None:
    _fail(harness, monkeypatch, "POST", "/me/events/evt-planning/cancel", outcome)
    assert (
        harness.error(
            "m365_delete", {"resource": "event", "id": "evt-planning", "confirm": True}
        )
        == "Outcome unknown: check whether the item still exists before retrying"
    )


@pytest.mark.parametrize("calendar_id", ["default", "Default", "cal-default"])
def test_default_calendar_cannot_be_deleted(
    harness: UnifiedHarness, calendar_id: str
) -> None:
    assert (
        harness.error(
            "m365_delete", {"resource": "calendar", "id": calendar_id, "confirm": True}
        )
        == "Invalid id: the default calendar cannot be deleted"
    )
    assert not harness.graph_calls("DELETE")
    assert "cal-default" in harness.fake.calendars


def test_delete_calendar(harness: UnifiedHarness) -> None:
    data = harness.ok(
        "m365_delete", {"resource": "calendar", "id": "cal-roster", "confirm": True}
    )
    assert harness.graph_calls("DELETE", "/me/calendars/cal-roster")
    assert data["status"] == "deleted" and data["recoverable"] is False
    assert data["summary"] == "Deleted calendar 'Old Roster' and its events."
    assert "cal-roster" not in harness.fake.calendars


# ----------------------------------------------------------------------
# calendar_create_event (U3.13)
# ----------------------------------------------------------------------


def test_create_event_example(harness: UnifiedHarness) -> None:
    _adelaide(harness)
    example = _example("calendar_create_event")
    data = harness.ok("calendar_create_event", example["input"])
    call = harness.graph_calls("POST", "/me/events")[0]
    assert call.body == {
        "subject": "Dentist",
        "start": {"dateTime": "2026-10-02T09:00:00", "timeZone": "Australia/Adelaide"},
        "end": {"dateTime": "2026-10-02T10:00:00", "timeZone": "Australia/Adelaide"},
        "location": {"displayName": "City Dental"},
    }
    expected = example["output"]
    event = data["event"]
    for key in (
        "subject",
        "start",
        "end",
        "time_zone",
        "is_all_day",
        "location",
        "is_organizer",
        "my_response",
        "show_as",
        "attendee_count",
        "preview",
        "body",
        "body_truncated",
        "attendees",
        "recurrence",
    ):
        assert event[key] == expected["event"][key], key
    assert data["invitations_sent"] is False
    assert data["summary"] == expected["summary"]


def test_create_event_end_must_follow_start(harness: UnifiedHarness) -> None:
    assert (
        harness.error(
            "calendar_create_event",
            {
                "subject": "X",
                "start": "2026-10-02T10:00:00+09:30",
                "end": "2026-10-02T10:00:00+09:30",
            },
        )
        == "Invalid end: must be after start"
    )
    assert not harness.graph_calls("POST")


def test_create_event_with_attendees_requires_confirm(harness: UnifiedHarness) -> None:
    args = {
        "subject": "Planning",
        "start": "2026-10-02T10:00:00Z",
        "end": "2026-10-02T11:00:00Z",
        "attendees": [{"address": "jane@example.com"}],
    }
    assert harness.error("calendar_create_event", args) == CONFIRM_TEXT.format(
        action="inviting attendees"
    )
    assert not harness.graph_calls("POST")


def test_create_event_with_attendees_sends_invitations(harness: UnifiedHarness) -> None:
    data = harness.ok(
        "calendar_create_event",
        {
            "subject": "Planning",
            "start": "2026-10-02T10:00:00Z",
            "end": "2026-10-02T11:00:00Z",
            "attendees": [
                {"address": "jane@example.com", "name": "Jane"},
                {"address": "sam@example.com", "type": "optional"},
            ],
            "confirm": True,
        },
    )
    body = harness.graph_calls("POST", "/me/events")[0].body
    assert body["attendees"] == [
        {
            "emailAddress": {"address": "jane@example.com", "name": "Jane"},
            "type": "required",
        },
        {"emailAddress": {"address": "sam@example.com"}, "type": "optional"},
    ]
    assert data["invitations_sent"] is True
    assert data["event"]["attendee_count"] == 2
    assert data["summary"].endswith("and invited 2 attendees.")


def test_create_event_all_fields_on_named_calendar(harness: UnifiedHarness) -> None:
    data = harness.ok(
        "calendar_create_event",
        {
            "subject": "School holidays",
            "start": "2026-10-05T00:00:00+10:30",
            "end": "2026-10-06T00:00:00+10:30",
            "time_zone": "Australia/Adelaide",
            "is_all_day": True,
            "body": "<p>No school</p>",
            "body_format": "html",
            "reminder_minutes": 1440,
            "show_as": "free",
            "calendar_id": "cal-family",
        },
    )
    body = harness.graph_calls("POST", "/me/calendars/cal-family/events")[0].body
    assert body["isAllDay"] is True
    assert body["start"] == {
        "dateTime": "2026-10-05T00:00:00",
        "timeZone": "Australia/Adelaide",
    }
    assert body["body"] == {"contentType": "html", "content": "<p>No school</p>"}
    assert body["isReminderOn"] is True
    assert body["reminderMinutesBeforeStart"] == 1440
    assert body["showAs"] == "free"
    assert data["event"]["calendar_id"] == "cal-family"
    assert data["event"]["is_all_day"] is True
    assert data["event"]["show_as"] == "free"


def test_create_event_default_calendar_alias(harness: UnifiedHarness) -> None:
    harness.ok(
        "calendar_create_event",
        {
            "subject": "X",
            "start": "2026-10-02T10:00:00Z",
            "end": "2026-10-02T11:00:00Z",
            "calendar_id": "default",
        },
    )
    assert harness.graph_calls("POST", "/me/events")


def test_create_event_rejects_unknown_time_zone(harness: UnifiedHarness) -> None:
    assert harness.error(
        "calendar_create_event",
        {
            "subject": "X",
            "start": "2026-10-02T10:00:00Z",
            "end": "2026-10-02T11:00:00Z",
            "time_zone": "Mars/Olympus",
        },
    ) == (
        "Invalid time_zone 'Mars/Olympus': unknown timezone. "
        "Expected: Valid IANA timezone name"
    )


@pytest.mark.parametrize("outcome", [500, 502, httpx.ReadTimeout("slow")])
def test_create_event_outcome_unknown(
    harness: UnifiedHarness, monkeypatch: pytest.MonkeyPatch, outcome: Any
) -> None:
    _fail(harness, monkeypatch, "POST", "/me/events", outcome)
    assert (
        harness.error(
            "calendar_create_event",
            {
                "subject": "X",
                "start": "2026-10-02T10:00:00Z",
                "end": "2026-10-02T11:00:00Z",
            },
        )
        == "Outcome unknown: check your calendar before retrying"
    )
    assert len(harness.graph_calls("POST", "/me/events")) <= 1


def test_create_event_clear_failure_is_not_outcome_unknown(
    harness: UnifiedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fail(harness, monkeypatch, "POST", "/me/events", 400)
    text = harness.error(
        "calendar_create_event",
        {
            "subject": "X",
            "start": "2026-10-02T10:00:00Z",
            "end": "2026-10-02T11:00:00Z",
        },
    )
    assert "Outcome unknown" not in text


# ----------------------------------------------------------------------
# calendar_update_event (U3.14)
# ----------------------------------------------------------------------


def _seed_example_event(harness: UnifiedHarness) -> None:
    _seed_event(
        harness,
        "AAMkADAwATM3EVT",
        "Dentist",
        "2026-10-01T23:30:00",
        "2026-10-02T00:30:00",
        location="City Dental",
    )


def test_update_event_example(harness: UnifiedHarness) -> None:
    _adelaide(harness)
    _seed_example_event(harness)
    example = _example("calendar_update_event")
    data = harness.ok("calendar_update_event", example["input"])
    assert harness.graph_calls("GET", "/me/events/AAMkADAwATM3EVT")
    patch = harness.graph_calls("PATCH", "/me/events/AAMkADAwATM3EVT")[0]
    assert patch.body == {
        "start": {"dateTime": "2026-10-02T11:00:00", "timeZone": "Australia/Adelaide"},
        "end": {"dateTime": "2026-10-02T12:00:00", "timeZone": "Australia/Adelaide"},
    }
    expected = example["output"]
    # calendar_id: Graph does not return an event's calendar on GET/PATCH
    # /me/events/{id}, so it is null unless the call names the calendar.
    assert data["event"]["calendar_id"] is None
    assert {k: v for k, v in data["event"].items() if k != "calendar_id"} == {
        k: v for k, v in expected["event"].items() if k != "calendar_id"
    }
    assert data["attendees_notified"] is False
    assert data["changed_fields"] == ["start", "end"]
    assert data["summary"] == expected["summary"]


def test_update_attendees_set_is_exclusive(harness: UnifiedHarness) -> None:
    assert (
        harness.error(
            "calendar_update_event",
            {
                "event_id": "evt-planning",
                "changes": {
                    "attendees_set": [{"address": "a@example.com"}],
                    "attendees_remove": ["b@example.com"],
                },
                "confirm": True,
            },
        )
        == "Invalid attendees_set: cannot be combined with attendees_add or attendees_remove"
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"start": "2026-10-02T12:00:00Z", "end": "2026-10-02T11:00:00Z"},
        {"start": "2026-10-10T00:00:00Z"},  # after the current end
        {"end": "2026-09-01T00:00:00Z"},  # before the current start
    ],
)
def test_update_resulting_end_must_follow_start(
    harness: UnifiedHarness, changes: dict[str, Any]
) -> None:
    assert (
        harness.error(
            "calendar_update_event", {"event_id": "evt-dentist", "changes": changes}
        )
        == "Invalid end: must be after start"
    )
    assert not harness.graph_calls("PATCH")


@pytest.mark.parametrize(
    "changes",
    [
        {"start": "2026-09-30T15:00:00Z", "end": "2026-09-30T16:00:00Z"},
        {"location": "Elsewhere"},
        {"attendees_add": [{"address": "sam@example.com"}]},
    ],
)
def test_update_only_organiser_changes_time_attendees_location(
    harness: UnifiedHarness, changes: dict[str, Any]
) -> None:
    assert harness.error(
        "calendar_update_event",
        {"event_id": "evt-sync", "changes": changes, "confirm": True},
    ) == (
        "You are not the organiser of this meeting. "
        "Expected: use calendar_respond to propose a new time"
    )
    assert not harness.graph_calls("PATCH")


def test_update_meeting_with_attendees_requires_confirm(
    harness: UnifiedHarness,
) -> None:
    args = {"event_id": "evt-planning", "changes": {"subject": "Q4 planning"}}
    assert harness.error("calendar_update_event", args) == CONFIRM_TEXT.format(
        action="updating a meeting with attendees"
    )
    assert not harness.graph_calls("PATCH")
    data = harness.ok("calendar_update_event", {**args, "confirm": True})
    assert harness.graph_calls("PATCH", "/me/events/evt-planning")[0].body == {
        "subject": "Q4 planning"
    }
    assert data["attendees_notified"] is True
    assert data["changed_fields"] == ["subject"]
    assert data["event"]["subject"] == "Q4 planning"


def test_update_adding_attendees_to_private_event_requires_confirm(
    harness: UnifiedHarness,
) -> None:
    args = {
        "event_id": "evt-dentist",
        "changes": {"attendees_add": [{"address": "sam@example.com"}]},
    }
    assert harness.error("calendar_update_event", args) == CONFIRM_TEXT.format(
        action="updating a meeting with attendees"
    )
    data = harness.ok("calendar_update_event", {**args, "confirm": True})
    patch = harness.graph_calls("PATCH", "/me/events/evt-dentist")[0]
    assert patch.body == {
        "attendees": [
            {"emailAddress": {"address": "sam@example.com"}, "type": "required"}
        ]
    }
    assert data["attendees_notified"] is True
    assert data["event"]["attendee_count"] == 1


def test_update_private_event_needs_no_confirm(harness: UnifiedHarness) -> None:
    data = harness.ok(
        "calendar_update_event",
        {
            "event_id": "evt-dentist",
            "changes": {
                "subject": "Dentist (check-up)",
                "body": "Bring forms",
                "reminder_minutes": 30,
                "show_as": "oof",
            },
        },
    )
    body = harness.graph_calls("PATCH", "/me/events/evt-dentist")[0].body
    assert body == {
        "subject": "Dentist (check-up)",
        "body": {"contentType": "text", "content": "Bring forms"},
        "isReminderOn": True,
        "reminderMinutesBeforeStart": 30,
        "showAs": "oof",
    }
    assert data["attendees_notified"] is False
    assert data["changed_fields"] == ["subject", "body", "reminder_minutes", "show_as"]


def test_update_attendees_remove_and_add(harness: UnifiedHarness) -> None:
    before = harness.fake.events["evt-planning"]["attendees"]
    removed = before[1]["emailAddress"]["address"]
    kept = before[0]["emailAddress"]["address"]
    harness.ok(
        "calendar_update_event",
        {
            "event_id": "evt-planning",
            "changes": {
                "attendees_remove": [removed.upper()],
                "attendees_add": [
                    {"address": kept},  # already present: not duplicated
                    {"address": "sam@example.com", "type": "optional"},
                ],
            },
            "confirm": True,
        },
    )
    attendees = harness.graph_calls("PATCH", "/me/events/evt-planning")[0].body[
        "attendees"
    ]
    assert [a["emailAddress"]["address"] for a in attendees] == [
        kept,
        "sam@example.com",
    ]
    assert attendees[1]["type"] == "optional"
    assert "status" not in attendees[0]


def test_update_attendees_set_replaces_list(harness: UnifiedHarness) -> None:
    data = harness.ok(
        "calendar_update_event",
        {
            "event_id": "evt-planning",
            "changes": {"attendees_set": []},
            "confirm": True,
        },
    )
    assert harness.graph_calls("PATCH", "/me/events/evt-planning")[0].body == {
        "attendees": []
    }
    assert data["attendees_notified"] is True
    assert data["event"]["attendee_count"] == 0


def test_update_attendee_can_change_reminder_with_confirm(
    harness: UnifiedHarness,
) -> None:
    data = harness.ok(
        "calendar_update_event",
        {
            "event_id": "evt-sync",
            "changes": {"reminder_minutes": 5},
            "confirm": True,
        },
    )
    assert data["attendees_notified"] is False  # attendees are not emailed


# ----------------------------------------------------------------------
# calendar_respond (U3.15)
# ----------------------------------------------------------------------


def _seed_invitation(harness: UnifiedHarness) -> None:
    _seed_event(
        harness,
        "AAMkADAwATM3INV",
        "Book club",
        "2026-10-07T08:30:00",
        "2026-10-07T09:30:00",
        isOrganizer=False,
        organizer={"emailAddress": {"name": "Priya", "address": "priya@example.com"}},
        responseStatus={"response": "notResponded"},
        attendees=[_attendee("robin@example.com")],
    )


def test_respond_example(harness: UnifiedHarness) -> None:
    _seed_invitation(harness)
    example = _example("calendar_respond")
    data = harness.ok("calendar_respond", example["input"])
    call = harness.graph_calls("POST", "/me/events/AAMkADAwATM3INV/decline")[0]
    assert call.body == {
        "sendResponse": True,
        "comment": "Can we do Thursday?",
        "proposedNewTime": {
            "start": {"dateTime": "2026-10-08T04:30:00", "timeZone": "UTC"},
            "end": {"dateTime": "2026-10-08T05:30:00", "timeZone": "UTC"},
        },
    }
    assert data == example["output"]


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (
            {"action": "decline", "proposed_start": "2026-10-08T14:00:00+09:30"},
            "Invalid proposed_end: required with proposed_start",
        ),
        (
            {"action": "decline", "proposed_end": "2026-10-08T14:00:00+09:30"},
            "Invalid proposed_start: required with proposed_end",
        ),
        (
            {
                "action": "accept",
                "proposed_start": "2026-10-08T14:00:00+09:30",
                "proposed_end": "2026-10-08T15:00:00+09:30",
            },
            "Invalid proposed_start: only valid with action 'tentative' or 'decline'",
        ),
        (
            {
                "action": "tentative",
                "proposed_start": "2026-10-08T15:00:00+09:30",
                "proposed_end": "2026-10-08T14:00:00+09:30",
            },
            "Invalid proposed_end: must be after proposed_start",
        ),
    ],
)
def test_respond_proposed_time_rules(
    harness: UnifiedHarness, args: dict[str, Any], expected: str
) -> None:
    _seed_invitation(harness)
    assert (
        harness.error(
            "calendar_respond", {"event_id": "AAMkADAwATM3INV", "confirm": True, **args}
        )
        == expected
    )
    assert not harness.graph_calls("POST")


def test_respond_refuses_own_meeting(harness: UnifiedHarness) -> None:
    assert (
        harness.error(
            "calendar_respond",
            {"event_id": "evt-planning", "action": "accept", "confirm": True},
        )
        == "You organise this meeting; there is nothing to respond to"
    )
    assert not harness.graph_calls("POST")


def test_respond_requires_confirm_when_sending(harness: UnifiedHarness) -> None:
    _seed_invitation(harness)
    assert harness.error(
        "calendar_respond", {"event_id": "AAMkADAwATM3INV", "action": "accept"}
    ) == CONFIRM_TEXT.format(action="sending a response")
    assert not harness.graph_calls("POST")


@pytest.mark.parametrize(
    ("action", "path", "state"),
    [
        ("accept", "accept", "accepted"),
        ("tentative", "tentativelyAccept", "tentativelyAccepted"),
        ("decline", "decline", "declined"),
    ],
)
def test_respond_without_sending_needs_no_confirm(
    harness: UnifiedHarness, action: str, path: str, state: str
) -> None:
    _seed_invitation(harness)
    data = harness.ok(
        "calendar_respond",
        {"event_id": "AAMkADAwATM3INV", "action": action, "send_response": False},
    )
    call = harness.graph_calls("POST", f"/me/events/AAMkADAwATM3INV/{path}")[0]
    assert call.body == {"sendResponse": False}
    assert data["response_sent"] is False
    assert data["proposed_start"] is None and data["proposed_end"] is None
    assert data["summary"].endswith("without notifying the organiser.")
    assert harness.fake.events["AAMkADAwATM3INV"]["responseStatus"]["response"] == state


# ----------------------------------------------------------------------
# calendar_forward (U3.23)
# ----------------------------------------------------------------------


def test_forward_example(harness: UnifiedHarness) -> None:
    _seed_invitation(harness)
    example = _example("calendar_forward")
    data = harness.ok("calendar_forward", example["input"])
    call = harness.graph_calls("POST", "/me/events/AAMkADAwATM3INV/forward")[0]
    assert call.body == {
        "toRecipients": [{"emailAddress": {"address": "sam@example.com"}}]
    }
    assert data == example["output"]


def test_forward_with_comment(harness: UnifiedHarness) -> None:
    harness.ok(
        "calendar_forward",
        {
            "event_id": "evt-sync",
            "to": ["sam@example.com", "kim@example.com"],
            "comment": "FYI",
            "confirm": True,
        },
    )
    body = harness.graph_calls("POST", "/me/events/evt-sync/forward")[0].body
    assert body["comment"] == "FYI"
    assert len(body["toRecipients"]) == 2


def test_forward_requires_confirm(harness: UnifiedHarness) -> None:
    assert harness.error(
        "calendar_forward",
        {"event_id": "evt-sync", "to": ["sam@example.com"], "confirm": False},
    ) == CONFIRM_TEXT.format(action="forward invitation")
    assert not harness.graph_calls("POST")
