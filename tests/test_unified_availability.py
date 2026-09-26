"""calendar_find_availability (U3.16): busy blocks, working hours, slots."""

from __future__ import annotations

from typing import Any

import pytest

from m365_mcp.rate_limit import rate_limiter
from m365_mcp.tool_specs import load_tool_spec
from tests.unified_harness import UnifiedHarness

TOOL = "calendar_find_availability"
ADELAIDE_WINDOWS = "Cen. Australia Standard Time"


@pytest.fixture(autouse=True)
def _fresh_rate_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rate_limiter, "_buckets", {})


def _adelaide(harness: UnifiedHarness, start: str = "08:00:00") -> None:
    """Mailbox and working hours in Adelaide; empty calendar."""
    harness.fake.events.clear()
    harness.fake.mailbox_settings["timeZone"] = ADELAIDE_WINDOWS
    harness.fake.mailbox_settings["workingHours"] = {
        "daysOfWeek": ["monday", "tuesday", "wednesday", "thursday", "friday"],
        "startTime": f"{start}.0000000",
        "endTime": "17:00:00.0000000",
        "timeZone": {"name": ADELAIDE_WINDOWS},
    }


def _busy(
    harness: UnifiedHarness,
    event_id: str,
    start_utc: str,
    end_utc: str,
    *,
    subject: str = "Busy",
    show_as: str = "busy",
) -> None:
    harness.fake.events[event_id] = {
        "id": event_id,
        "subject": subject,
        "start": {"dateTime": start_utc, "timeZone": "UTC"},
        "end": {"dateTime": end_utc, "timeZone": "UTC"},
        "showAs": show_as,
        "calendarId": "cal-default",
        "attendees": [],
        "isAllDay": False,
    }


def _slots(data: dict[str, Any]) -> list[tuple[str, str]]:
    return [(s["start"], s["end"]) for s in data["free_slots"]]


def test_example_busy_block_and_working_hours(harness: UnifiedHarness) -> None:
    _adelaide(harness)
    _busy(
        harness,
        "evt-physio",
        "2026-09-30T23:30:00.0000000",
        "2026-10-01T01:00:00.0000000",
        subject="Physio",
    )
    example = load_tool_spec(TOOL)["examples"][0]
    data = harness.ok(TOOL, example["input"])
    expected = example["output"]
    assert data["time_zone"] == expected["time_zone"]
    assert data["busy"] == expected["busy"]
    assert data["working_hours"] == expected["working_hours"]
    # Spec example lists 10:30-11:30, but 08:00-09:00 is also free inside
    # the 08:00-17:00 working hours; the earliest free hour is returned.
    assert _slots(data) == [("2026-10-01T08:00:00+09:30", "2026-10-01T09:00:00+09:30")]
    assert data["summary"] == "1 busy block; first free hour 08:00–09:00."


def test_graph_calls(harness: UnifiedHarness) -> None:
    harness.ok(TOOL, {"start": "2026-09-28T00:00:00Z", "end": "2026-09-29T00:00:00Z"})
    view = harness.graph_calls("GET", "/me/calendarView")
    assert len(view) == 1
    assert view[0].params["startDateTime"] == "2026-09-28T00:00:00Z"
    assert view[0].params["endDateTime"] == "2026-09-29T00:00:00Z"
    assert view[0].params["$select"] == "subject,start,end,showAs"
    assert harness.graph_calls("GET", "/me/mailboxSettings/workingHours")


def test_calendar_view_is_paged(harness: UnifiedHarness) -> None:
    harness.fake.events.clear()
    for day in range(1, 31):
        _busy(
            harness,
            f"evt-{day:02d}",
            f"2026-10-{day:02d}T10:00:00",
            f"2026-10-{day:02d}T11:00:00",
        )
    data = harness.ok(
        TOOL, {"start": "2026-10-01T00:00:00Z", "end": "2026-11-01T00:00:00Z"}
    )
    assert len(data["busy"]) == 30


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-10-02T00:00:00Z", "2026-10-01T00:00:00Z"),
        ("2026-10-01T00:00:00Z", "2026-10-01T00:00:00Z"),
        ("2026-10-01T00:00:00Z", "2026-12-02T00:00:01Z"),
    ],
)
def test_window_rule(harness: UnifiedHarness, start: str, end: str) -> None:
    assert harness.error(TOOL, {"start": start, "end": end}) == (
        "Invalid end: must be after start and within 62 days"
    )
    assert not harness.graph_calls("GET", "/me/calendarView")


def test_window_of_exactly_62_days_is_allowed(harness: UnifiedHarness) -> None:
    harness.ok(TOOL, {"start": "2026-10-01T00:00:00Z", "end": "2026-12-02T00:00:00Z"})


def test_without_slot_minutes_only_busy_blocks_are_returned(
    harness: UnifiedHarness,
) -> None:
    data = harness.ok(
        TOOL,
        {
            "start": "2026-09-28T00:00:00Z",
            "end": "2026-09-29T00:00:00Z",
            "working_hours_only": False,  # no effect without slot_minutes
        },
    )
    assert data["free_slots"] == []
    assert data["busy"] and data["working_hours"]["time_zone"] == "UTC"
    count = len(data["busy"])
    assert data["summary"] == f"{count} busy block{'' if count == 1 else 's'}."


def test_free_and_unknown_events_are_not_busy(harness: UnifiedHarness) -> None:
    harness.fake.events.clear()
    for state in ("busy", "tentative", "oof", "workingElsewhere", "free", "unknown"):
        _busy(
            harness,
            f"evt-{state}",
            "2026-10-01T10:00:00",
            "2026-10-01T11:00:00",
            show_as=state,
            subject=state,
        )
    data = harness.ok(
        TOOL, {"start": "2026-10-01T00:00:00Z", "end": "2026-10-02T00:00:00Z"}
    )
    assert sorted(b["show_as"] for b in data["busy"]) == [
        "busy",
        "oof",
        "tentative",
        "workingElsewhere",
    ]


def test_min_gap_keeps_a_buffer_around_busy_time(harness: UnifiedHarness) -> None:
    harness.fake.events.clear()
    _busy(harness, "evt-a", "2026-10-01T10:00:00", "2026-10-01T11:00:00")
    data = harness.ok(
        TOOL,
        {
            "start": "2026-10-01T09:00:00Z",
            "end": "2026-10-01T12:00:00Z",
            "slot_minutes": 30,
            "min_gap_minutes": 15,
        },
    )
    assert _slots(data) == [
        ("2026-10-01T09:00:00+00:00", "2026-10-01T09:30:00+00:00"),
        ("2026-10-01T11:15:00+00:00", "2026-10-01T11:45:00+00:00"),
    ]


def test_overlapping_busy_blocks_are_merged(harness: UnifiedHarness) -> None:
    harness.fake.events.clear()
    _busy(harness, "evt-a", "2026-10-01T09:00:00", "2026-10-01T10:30:00")
    _busy(harness, "evt-b", "2026-10-01T10:00:00", "2026-10-01T11:00:00")
    _busy(harness, "evt-c", "2026-10-01T11:00:00", "2026-10-01T12:00:00")
    data = harness.ok(
        TOOL,
        {
            "start": "2026-10-01T09:00:00Z",
            "end": "2026-10-01T14:00:00Z",
            "slot_minutes": 60,
        },
    )
    assert _slots(data) == [
        ("2026-10-01T12:00:00+00:00", "2026-10-01T13:00:00+00:00"),
        ("2026-10-01T13:00:00+00:00", "2026-10-01T14:00:00+00:00"),
    ]


def test_outside_working_hours_when_disabled(harness: UnifiedHarness) -> None:
    harness.fake.events.clear()
    data = harness.ok(
        TOOL,
        {
            "start": "2026-10-03T00:00:00Z",  # a Saturday
            "end": "2026-10-03T03:00:00Z",
            "slot_minutes": 60,
            "working_hours_only": False,
        },
    )
    assert len(data["free_slots"]) == 3
    assert data["free_slots"][0]["start"] == "2026-10-03T00:00:00+00:00"


def test_working_hours_skip_weekends_and_nights(harness: UnifiedHarness) -> None:
    harness.fake.events.clear()
    data = harness.ok(
        TOOL,
        {
            "start": "2026-10-02T16:00:00Z",  # Friday 16:00 UTC
            "end": "2026-10-05T10:00:00Z",  # Monday 10:00 UTC
            "slot_minutes": 60,
        },
    )
    assert _slots(data) == [
        ("2026-10-02T16:00:00+00:00", "2026-10-02T17:00:00+00:00"),
        ("2026-10-05T09:00:00+00:00", "2026-10-05T10:00:00+00:00"),
    ]


def test_max_slots(harness: UnifiedHarness) -> None:
    harness.fake.events.clear()
    data = harness.ok(
        TOOL,
        {
            "start": "2026-10-05T00:00:00Z",
            "end": "2026-10-10T00:00:00Z",
            "slot_minutes": 30,
            "max_slots": 4,
        },
    )
    assert len(data["free_slots"]) == 4
    assert data["free_slots"][-1]["end"] == "2026-10-05T11:00:00+00:00"


def test_no_free_slot(harness: UnifiedHarness) -> None:
    harness.fake.events.clear()
    _busy(harness, "evt-a", "2026-10-05T08:00:00", "2026-10-05T18:00:00")
    data = harness.ok(
        TOOL,
        {
            "start": "2026-10-05T00:00:00Z",
            "end": "2026-10-06T00:00:00Z",
            "slot_minutes": 30,
        },
    )
    assert data["free_slots"] == []
    assert data["summary"] == "1 busy block; no free 30-minute slot found."


def test_slots_follow_local_hours_across_a_dst_change(harness: UnifiedHarness) -> None:
    # Adelaide moves from +09:30 to +10:30 on Sunday 4 Oct 2026 at 02:00.
    _adelaide(harness, start="09:00:00")
    data = harness.ok(
        TOOL,
        {
            "start": "2026-10-02T00:00:00+09:30",
            "end": "2026-10-07T00:00:00+10:30",
            "slot_minutes": 480,
        },
    )
    assert data["time_zone"] == "Australia/Adelaide"
    assert _slots(data) == [
        ("2026-10-02T09:00:00+09:30", "2026-10-02T17:00:00+09:30"),
        ("2026-10-05T09:00:00+10:30", "2026-10-05T17:00:00+10:30"),
        ("2026-10-06T09:00:00+10:30", "2026-10-06T17:00:00+10:30"),
    ]


def test_busy_block_crossing_dst_change(harness: UnifiedHarness) -> None:
    _adelaide(harness, start="09:00:00")
    # Monday 5 Oct 09:00-10:00 +10:30 is 22:30-23:30 UTC on 4 Oct.
    _busy(harness, "evt-a", "2026-10-04T22:30:00", "2026-10-04T23:30:00")
    data = harness.ok(
        TOOL,
        {
            "start": "2026-10-03T00:00:00+09:30",
            "end": "2026-10-06T00:00:00+10:30",
            "slot_minutes": 60,
            "max_slots": 1,
        },
    )
    assert data["busy"][0]["start"] == "2026-10-05T09:00:00+10:30"
    assert _slots(data) == [("2026-10-05T10:00:00+10:30", "2026-10-05T11:00:00+10:30")]


def test_explicit_time_zone_and_working_hours_zone(harness: UnifiedHarness) -> None:
    _adelaide(harness, start="09:00:00")
    data = harness.ok(
        TOOL,
        {
            "start": "2026-09-30T20:00:00Z",
            "end": "2026-10-02T00:00:00Z",
            "time_zone": "Europe/London",
            "slot_minutes": 60,
            "max_slots": 1,
        },
    )
    assert data["time_zone"] == "Europe/London"
    assert not harness.graph_calls("GET", "/me/mailboxSettings/timeZone")
    # Working hours stay in Adelaide: 09:00 ACST on 1 Oct is 00:30 BST.
    assert _slots(data) == [("2026-10-01T00:30:00+01:00", "2026-10-01T01:30:00+01:00")]


def test_unknown_time_zone(harness: UnifiedHarness) -> None:
    assert harness.error(
        TOOL,
        {
            "start": "2026-10-01T00:00:00Z",
            "end": "2026-10-02T00:00:00Z",
            "time_zone": "Nowhere/Land",
        },
    ) == (
        "Invalid time_zone 'Nowhere/Land': unknown timezone. "
        "Expected: Valid IANA timezone name"
    )


def test_no_working_hours_configured(harness: UnifiedHarness) -> None:
    harness.fake.events.clear()
    harness.fake.mailbox_settings["workingHours"] = {}
    data = harness.ok(
        TOOL,
        {
            "start": "2026-10-03T00:00:00Z",
            "end": "2026-10-03T02:00:00Z",
            "slot_minutes": 60,
        },
    )
    assert data["working_hours"] is None
    assert len(data["free_slots"]) == 2
