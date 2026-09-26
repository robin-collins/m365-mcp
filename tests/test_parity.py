"""Behaviour tests for every row of ``legacy_mapping.json`` (task U3.30).

The 85 legacy tools no longer exist. ``docs/unified-tools/legacy_mapping.json``
stays as the migration record: for each legacy tool it names the unified
replacement. Every row has a scenario here that performs the practical task
the legacy tool was used for through the unified surface and asserts the
concrete expected end state or result of the fake Graph (literals, or the
seeded baseline plus an explicit delta). Rows whose ``behaviour_change`` is
set assert the NEW behaviour.

Rows 0-42 (account, admin, calendar, contact, mail folder, mail rule) are
registered with ``@row``; rows 43-84 (rule ordering, mail, OneDrive, search,
server info) with ``@scenario`` and run through the ``harness`` fixture.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from evals.fake_graph import FakeGraph
from m365_mcp import auth, auth_sessions, cache, warming_status
from tests.parity_helpers import (
    MAPPING_PATH,
    mapping_row,
    seeded_copy,
    unified_session,
)
from tests.unified_harness import UnifiedHarness

MAPPING_ROW_COUNT = 85

AID = "alex.morgan@outlook.com"
ROW_COUNT = 43

ROW_SCENARIOS: dict[int, Callable[[pytest.MonkeyPatch], None]] = {}


def row(index: int, legacy_tool: str, replacement: str) -> Callable[[Any], Any]:
    """Register a scenario for mapping row ``index``.

    The names are checked against ``legacy_mapping.json`` so a scenario
    cannot silently drift from the row it claims to cover.
    """

    def register(fn: Any) -> Any:
        fn.expected = (legacy_tool, replacement)  # type: ignore[attr-defined]
        ROW_SCENARIOS[index] = fn
        return fn

    return register


@pytest.mark.parametrize("index", range(ROW_COUNT))
def test_parity_row(index: int, monkeypatch: pytest.MonkeyPatch) -> None:
    """The replacement completes the same practical task as the legacy tool."""
    scenario = ROW_SCENARIOS.get(index)
    assert scenario is not None, f"no parity scenario for mapping row {index}"
    entry = mapping_row(index)
    assert (entry["legacy_tool"], entry["replacement"]) == scenario.expected  # type: ignore[attr-defined]
    scenario(monkeypatch)


# ----------------------------------------------------------------------
# generic helpers
# ----------------------------------------------------------------------


def _remaining_ids(fake: Any, attr: str) -> set[str]:
    return set(getattr(fake, attr))


def _message_state(fake: Any, folder: str) -> dict[str, bool]:
    """Read flag of every message in ``folder``, keyed by message ID."""
    return {
        m["id"]: m["isRead"]
        for m in fake.messages.values()
        if m["parentFolderId"] == folder
    }


# ----------------------------------------------------------------------
# account rows 0-2
# ----------------------------------------------------------------------

DEVICE_CODE = "DAQABAAEAAAD--very-secret-device-code"
PERSONAL_ID = f"00000000-0000-0000-1111-222233334444.{auth.PERSONAL_TENANT_ID}"
WORK_TENANT = "72f988bf-86f1-41af-91ab-2d7cd011db47"


class FakeApp:
    """MSAL stand-in whose device-flow outcome the scenario sets."""

    def __init__(self) -> None:
        self.outcome: dict[str, Any] = {"error": "authorization_pending"}
        self.accounts: list[dict[str, str]] = []
        self.polls = 0

    def initiate_device_flow(self, scopes: list[str]) -> dict[str, Any]:
        return {
            "user_code": "PMQDYGWPS",
            "device_code": DEVICE_CODE,
            "verification_uri": "https://login.microsoft.com/device",
            "expires_in": 900,
            "interval": 5,
        }

    def acquire_token_by_device_flow(
        self, flow: dict[str, Any], exit_condition: Any = None
    ) -> dict[str, Any]:
        self.polls += 1
        return self.outcome

    def get_accounts(self) -> list[dict[str, str]]:
        return list(self.accounts)

    def remove_account(self, account: dict[str, str]) -> None:
        self.accounts.remove(account)

    def sign_in(self, username: str, home_account_id: str, tid: str) -> None:
        self.accounts = [{"username": username, "home_account_id": home_account_id}]
        self.outcome = {
            "access_token": "secret-access-token",
            "id_token_claims": {"preferred_username": username, "tid": tid},
        }


def _install_msal(mp: pytest.MonkeyPatch) -> FakeApp:
    """Replace MSAL and the auth-session store with a scriptable fake."""
    fake = FakeApp()
    mp.setattr(auth, "get_app", lambda: (fake, "consumers"))
    mp.setattr(auth, "_build_app", lambda tenant: fake)
    mp.setattr(auth_sessions, "store", auth_sessions.AuthSessionStore())
    mp.setattr(auth_sessions.secrets, "token_urlsafe", lambda n: "91b2")
    return fake


@row(0, "account_list", "account_list")
def _account_list(mp: pytest.MonkeyPatch) -> None:
    with unified_session() as h:
        data = h.ok("account_list", {})
    (account,) = data["accounts"]
    assert set(account) == {"account_id", "email", "display_name"}
    assert "account_type" not in json.dumps(data)
    assert account["email"] == AID
    assert account["account_id"] == h.account_id
    assert data["summary"] == "1 account signed in."


@row(1, "account_authenticate", "account_auth_begin")
def _account_auth_begin(mp: pytest.MonkeyPatch) -> None:
    app = _install_msal(mp)
    with unified_session() as h:
        data = h.ok("account_auth_begin", {})
    assert data["auth_session_id"] == "as_91b2"
    assert data["user_code"] == "PMQDYGWPS"
    assert data["verification_url"] == "https://login.microsoft.com/device"
    # The device code stays server-side: not returned in any form.
    assert DEVICE_CODE not in json.dumps(data)
    assert "device_code" not in data and "_flow_cache" not in data
    assert app.polls == 0  # beginning never blocks on the user


@row(2, "account_complete_auth", "account_auth_complete")
def _account_auth_complete(mp: pytest.MonkeyPatch) -> None:
    app = _install_msal(mp)
    with unified_session() as h:
        session = h.ok("account_auth_begin", {})["auth_session_id"]

        # Non-blocking: one poll, immediate "pending" result.
        pending = h.ok("account_auth_complete", {"auth_session_id": session})
        assert pending["status"] == "pending" and pending["account"] is None
        assert app.polls == 1

        # Personal account signs in: the session handle completes the flow.
        app.sign_in("ada@outlook.com", PERSONAL_ID, auth.PERSONAL_TENANT_ID)
        done = h.ok("account_auth_complete", {"auth_session_id": session})
        assert done["status"] == "success"
        assert done["account"] == {
            "account_id": PERSONAL_ID,
            "email": "ada@outlook.com",
        }
        assert "secret-access-token" not in json.dumps(done)
        assert app.accounts  # the account stays signed in

        # Work/school accounts are refused and removed.
        session = h.ok("account_auth_begin", {})["auth_session_id"]
        app.sign_in("ada@contoso.com", f"oid.{WORK_TENANT}", WORK_TENANT)
        text = h.error("account_auth_complete", {"auth_session_id": session})
        assert text == "Only personal Microsoft accounts are supported"
        assert app.accounts == []


# ----------------------------------------------------------------------
# admin cache rows 3-7
# ----------------------------------------------------------------------


def _enqueue(account_id: str, operations: list[str]) -> list[str]:
    manager = cache.get_cache_manager()
    return [
        manager.enqueue_task(account_id, op, {"n": n}, priority=3)
        for n, op in enumerate(operations)
    ]


@row(3, "cache_task_get_status", "admin_cache_get(view='task')")
def _cache_task_get(mp: pytest.MonkeyPatch) -> None:
    with unified_session() as h:
        (task_id,) = _enqueue(h.account_id, ["email_list"])
        data = h.ok("admin_cache_get", {"view": "task", "task_id": task_id})
    (task,) = data["tasks"]
    assert task["task_id"] == task_id
    assert task["operation"] == "email_list"
    assert task["retry_count"] == 0
    assert task["priority"] == 3 and task["status"] == "queued"


@row(4, "cache_task_list", "admin_cache_get(view='tasks')")
def _cache_task_list(mp: pytest.MonkeyPatch) -> None:
    ops = ["email_list", "file_list", "folder_get_tree"]
    with unified_session() as h:
        _enqueue(h.account_id, ops)
        data = h.ok(
            "admin_cache_get", {"view": "tasks", "status": "queued", "limit": 2}
        )
        everything = h.ok("admin_cache_get", {"view": "tasks"})
    assert len(data["tasks"]) == 2
    assert {t["operation"] for t in everything["tasks"]} == set(ops)
    assert len(everything["tasks"]) == 3


def _seed_cache(account_id: str) -> None:
    manager = cache.get_cache_manager()
    for n in range(3):
        manager.set_cached(account_id, "email", {"n": n}, {"value": [n]})
    manager.set_cached(account_id, "event", {"n": 0}, {"value": [0]})


@row(5, "cache_get_stats", "admin_cache_get(view='stats')")
def _cache_stats(mp: pytest.MonkeyPatch) -> None:
    with unified_session() as h:
        _seed_cache(h.account_id)
        stats = h.ok("admin_cache_get", {"view": "stats"})["stats"]
    assert stats["entry_count"] == 4
    assert stats["total_bytes"] == 56
    assert stats["max_bytes"] == 2 * 1024**3
    assert {r: v["entry_count"] for r, v in stats["by_resource"].items()} == {
        "email": 3,
        "event": 1,
    }


def _cache_resources() -> dict[str, int]:
    return {
        r: v["entry_count"]
        for r, v in cache.get_cache_manager().get_stats()["by_resource"].items()
    }


@row(6, "cache_invalidate", "admin_cache_invalidate")
def _cache_invalidate(mp: pytest.MonkeyPatch) -> None:
    with unified_session() as h:
        _seed_cache(h.account_id)
        data = h.ok("admin_cache_invalidate", {"scope": "email"})
        left = _cache_resources()
        # New behaviour: a typed scope, not a glob pattern.
        for bad in ("email:*", "email_*", "*"):
            assert "scope" in h.error("admin_cache_invalidate", {"scope": bad}).lower()
        assert (
            h.ok("admin_cache_invalidate", {"scope": "email"})["entries_removed"] == 0
        )
    assert data["entries_removed"] == 3
    assert left == {"event": 1}
    assert data["scope"] == "email"


@row(7, "cache_warming_status", "admin_cache_get(view='warming')")
def _cache_warming(mp: pytest.MonkeyPatch) -> None:
    warming_status.set_warming_status_provider(None)
    with unified_session() as h:
        data = h.ok("admin_cache_get", {"view": "warming"})
    warming = data["warming"]
    assert warming["is_warming"] is False
    assert warming["operations_total"] == 0
    assert warming["operations_completed"] == 0
    assert warming["progress_percent"] == 0.0
    assert data["stats"] is None and data["tasks"] is None


# ----------------------------------------------------------------------
# calendar rows 8-20
# ----------------------------------------------------------------------

CONFIRM_TEXT = (
    "Invalid confirm 'False': {action} requires confirm=True to proceed. "
    "Expected: Explicit user confirmation"
)


def _instant(value: dict[str, str] | str) -> datetime:
    """UTC instant of a Graph ``dateTimeTimeZone`` (or an offset string)."""
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
        zone = "UTC"
    else:
        parsed = datetime.fromisoformat(value["dateTime"])
        zone = value.get("timeZone", "UTC")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(zone))
    return parsed.astimezone(UTC)


def _addresses(event: dict[str, Any]) -> list[str]:
    return sorted(a["emailAddress"]["address"] for a in event["attendees"])


def _posts(fake: Any, suffix: str) -> list[Any]:
    return [c for c in fake.calls if c.method == "POST" and c.path.endswith(suffix)]


@row(8, "calendar_list_events", "m365_list(resource='event', start, end)")
def _calendar_list_events(mp: pytest.MonkeyPatch) -> None:
    start, end = "2026-09-28T00:00:00Z", "2026-10-01T00:00:00Z"
    with unified_session() as h:
        data = h.ok(
            "m365_list",
            {"resource": "event", "start": start, "end": end, "limit": 50},
        )
        lo, hi = _instant(start), _instant(end)
        expected = {
            e["id"]
            for e in h.fake.events.values()
            if e["calendarId"] == "cal-default" and lo <= _instant(e["start"]) < hi
        }
        assert expected  # the window is not empty
        # A time window, not days_ahead: exactly the events inside it.
        assert {i["id"] for i in data["items"]} == expected
        assert "evt-car" not in expected and "evt-planning" not in expected
        # Recurrences expand through calendarView: one item per occurrence.
        standups = [i for i in data["items"] if i["subject"] == "Team standup"]
        assert len(standups) == 3
        assert len({i["id"] for i in standups}) == 3
        (call,) = h.graph_calls("GET", "/me/calendar/calendarView")
        assert call.params["startDateTime"] == start
        assert call.params["endDateTime"] == end
        assert not h.graph_calls("GET", "/me/events")
        # days_ahead is gone from the surface.
        assert h.error("m365_list", {"resource": "event", "days_ahead": 7})


@row(9, "calendar_get_event", "m365_get(resource='event')")
def _calendar_get_event(mp: pytest.MonkeyPatch) -> None:
    with unified_session() as h:
        item = h.ok("m365_get", {"resource": "event", "id": "evt-planning"})["item"]
    assert item["id"] == "evt-planning"
    assert item["subject"] == "Quarterly planning"
    assert item["location"] == "Cafe Roma"
    assert _instant(item["start"]) == datetime(2026, 10, 2, 13, 0, tzinfo=UTC)
    assert _instant(item["end"]) == datetime(2026, 10, 2, 14, 30, tzinfo=UTC)
    assert item["body"] == "Plan Q4 priorities."
    assert sorted(a["address"] for a in item["attendees"]) == [
        "jane.smith@example.com",
        "mark.brown@example.com",
    ]
    assert item["organizer"]["address"] == "alex.morgan@outlook.com"


@row(10, "calendar_create_event", "calendar_create_event")
def _calendar_create_event(mp: pytest.MonkeyPatch) -> None:
    fields = {
        "subject": "Planning",
        "start": "2026-10-02T10:00:00Z",
        "end": "2026-10-02T11:00:00Z",
        "location": "Cafe Roma",
        "body": "Plan Q4",
    }
    attendee = "jane.smith@example.com"
    with unified_session() as h:
        args = {**fields, "attendees": [{"address": attendee}]}
        # New: inviting attendees requires confirm.
        assert h.error("calendar_create_event", args) == CONFIRM_TEXT.format(
            action="inviting attendees"
        )
        assert not [e for e in h.fake.events.values() if e["subject"] == "Planning"]
        data = h.ok("calendar_create_event", {**args, "confirm": True})
        (created,) = [e for e in h.fake.events.values() if e["subject"] == "Planning"]
        assert created["id"] == data["event"]["id"]
        assert data["invitations_sent"] is True
        assert _instant(created["start"]) == datetime(2026, 10, 2, 10, 0, tzinfo=UTC)
        assert _instant(created["end"]) == datetime(2026, 10, 2, 11, 0, tzinfo=UTC)
        assert created["location"]["displayName"] == "Cafe Roma"
        assert created["body"]["content"] == "Plan Q4"
        assert _addresses(created) == [attendee]

        # New fields: calendar_id, is_all_day, reminder, show_as.
        data = h.ok(
            "calendar_create_event",
            {
                "subject": "School holidays",
                "start": "2026-10-05T00:00:00Z",
                "end": "2026-10-06T00:00:00Z",
                "time_zone": "UTC",
                "is_all_day": True,
                "reminder_minutes": 1440,
                "show_as": "free",
                "calendar_id": "cal-family",
            },
        )
        holiday = h.fake.events[data["event"]["id"]]
        assert holiday["calendarId"] == "cal-family"
        assert holiday["isAllDay"] is True
        assert holiday["showAs"] == "free"
        (post,) = h.graph_calls("POST", "/me/calendars/cal-family/events")
        assert post.body["isReminderOn"] is True
        assert post.body["reminderMinutesBeforeStart"] == 1440


@row(11, "calendar_update_event", "calendar_update_event")
def _calendar_update_event(mp: pytest.MonkeyPatch) -> None:
    with unified_session() as h:
        data = h.ok(
            "calendar_update_event",
            {
                "event_id": "evt-dentist",
                "changes": {
                    "subject": "Dentist (check-up)",
                    "start": "2026-09-29T11:00:00Z",
                    "end": "2026-09-29T12:00:00Z",
                    "location": "Elsewhere",
                },
            },
        )
        event = h.fake.events["evt-dentist"]
        assert data["changed_fields"] == ["subject", "start", "end", "location"]
        assert event["subject"] == "Dentist (check-up)"
        assert _instant(event["start"]) == datetime(2026, 9, 29, 11, 0, tzinfo=UTC)
        assert _instant(event["end"]) == datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
        assert event["location"]["displayName"] == "Elsewhere"
        # New: a meeting with attendees needs confirm; the event is untouched.
        before = json.dumps(h.fake.events["evt-planning"], sort_keys=True)
        args = {"event_id": "evt-planning", "changes": {"subject": "Q4 planning"}}
        assert h.error("calendar_update_event", args) == CONFIRM_TEXT.format(
            action="updating a meeting with attendees"
        )
        assert json.dumps(h.fake.events["evt-planning"], sort_keys=True) == before
        h.ok("calendar_update_event", {**args, "confirm": True})
        assert h.fake.events["evt-planning"]["subject"] == "Q4 planning"


@row(12, "calendar_delete_event", "m365_delete(resource='event')")
def _calendar_delete_event(mp: pytest.MonkeyPatch) -> None:
    with unified_session() as h:
        before = set(h.fake.events)
        data = h.ok(
            "m365_delete",
            {
                "resource": "event",
                "id": "evt-planning",
                "cancellation_message": "Moving this to next quarter.",
                "confirm": True,
            },
        )
        assert set(h.fake.events) == before - {"evt-planning"}
        assert "evt-planning" not in h.fake.events
        # New: the organiser's meeting is cancelled (attendees told, with the
        # message) rather than silently deleted.
        (cancel,) = _posts(h.fake, "/me/events/evt-planning/cancel")
        assert cancel.body == {"comment": "Moving this to next quarter."}
        assert not h.graph_calls("DELETE", "/me/events/evt-planning")
        assert data["status"] == "cancelled_and_deleted"
        # A private event is simply deleted.
        h.ok("m365_delete", {"resource": "event", "id": "evt-gym", "confirm": True})
        assert "evt-gym" not in h.fake.events
        assert not _posts(h.fake, "/me/events/evt-gym/cancel")


@row(13, "calendar_respond_event", "calendar_respond")
def _calendar_respond_event(mp: pytest.MonkeyPatch) -> None:
    cases = [
        ("evt-sync", "accept", "accepted"),
        ("evt-standup-00", "tentative", "tentativelyAccepted"),
        ("evt-standup-01", "decline", "declined"),
    ]

    def states(fake: Any) -> dict[str, Any]:
        return {
            e: fake.events.get(e, {}).get("responseStatus", {}).get("response")
            for e, _, _ in cases
        }

    with unified_session() as h:
        for event_id, action, state in cases:
            args = {"event_id": event_id, "action": action}
            # New: a response the organiser is told about needs confirm.
            assert h.error("calendar_respond", args) == CONFIRM_TEXT.format(
                action="sending a response"
            )
            assert h.fake.events[event_id]["responseStatus"]["response"] != state
            data = h.ok("calendar_respond", {**args, "confirm": True})
            assert data["response_sent"] is True
        unified = states(h.fake)
    assert unified["evt-sync"] == "accepted"
    assert unified["evt-standup-00"] == "tentativelyAccepted"


# The only busy time on 28 September: the 09:00 standup.
BUSY_SEP_28 = [
    (datetime(2026, 9, 28, 9, 0, tzinfo=UTC), datetime(2026, 9, 28, 9, 30, tzinfo=UTC))
]


def _unified_busy(data: dict[str, Any]) -> list[tuple[datetime, datetime]]:
    return sorted(
        (datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"]))
        for b in data["busy"]
    )


@row(14, "calendar_check_availability", "calendar_find_availability")
def _calendar_check_availability(mp: pytest.MonkeyPatch) -> None:
    window = {"start": "2026-09-28T00:00:00Z", "end": "2026-09-29T00:00:00Z"}
    with unified_session() as h:
        data = h.ok("calendar_find_availability", window)
        assert _unified_busy(data) == BUSY_SEP_28
        # New: own calendar only. Other people's calendars cannot be queried
        # and the tool reads calendarView, not getSchedule.
        assert h.error("calendar_find_availability", {**window, "attendees": [AID]})
        assert h.graph_calls("GET", "/me/calendarView")
        assert not h.graph_calls("POST", "/me/calendar/getSchedule")


@row(15, "calendar_forward_event", "calendar_forward")
def _calendar_forward_event(mp: pytest.MonkeyPatch) -> None:
    to = "sam.lee@example.com"
    with unified_session() as h:
        args = {"event_id": "evt-sync", "to": [to], "comment": "FYI"}
        assert h.error(
            "calendar_forward", {**args, "confirm": False}
        ) == CONFIRM_TEXT.format(action="forward invitation")
        assert not _posts(h.fake, "/forward")
        h.ok("calendar_forward", {**args, "confirm": True})
        (forwarded,) = _posts(h.fake, "/me/events/evt-sync/forward")
    assert forwarded.body["toRecipients"] == [{"emailAddress": {"address": to}}]
    assert forwarded.body["comment"] == "FYI"


@row(16, "calendar_list_calendars", "m365_list(resource='calendar')")
def _calendar_list_calendars(mp: pytest.MonkeyPatch) -> None:
    with unified_session() as h:
        items = h.ok("m365_list", {"resource": "calendar"})["items"]
    assert [(c["id"], c["name"], c["is_default"], c["can_edit"]) for c in items] == [
        ("cal-default", "Calendar", True, True),
        ("cal-family", "Family", False, True),
        ("cal-roster", "Old Roster", False, True),
    ]


@row(17, "calendar_create_calendar", "m365_create(resource='calendar')")
def _calendar_create_calendar(mp: pytest.MonkeyPatch) -> None:
    with unified_session() as h:
        data = h.ok(
            "m365_create", {"resource": "calendar", "calendar": {"name": "Holidays"}}
        )
        created = h.fake.calendars[data["item"]["id"]]
        assert created["name"] == "Holidays"
        assert created["isDefaultCalendar"] is False
        assert sorted(c["name"] for c in h.fake.calendars.values()) == [
            "Calendar",
            "Family",
            "Holidays",
            "Old Roster",
        ]


@row(18, "calendar_delete_calendar", "m365_delete(resource='calendar')")
def _calendar_delete_calendar(mp: pytest.MonkeyPatch) -> None:
    with unified_session() as h:
        h.ok(
            "m365_delete", {"resource": "calendar", "id": "cal-roster", "confirm": True}
        )
        assert set(h.fake.calendars) == {"cal-default", "cal-family"}
        # New: the default calendar is refused, by ID or by alias.
        for calendar_id in ("cal-default", "default"):
            text = h.error(
                "m365_delete",
                {"resource": "calendar", "id": calendar_id, "confirm": True},
            )
            assert text == "Invalid id: the default calendar cannot be deleted"
        assert "cal-default" in h.fake.calendars
        assert not h.graph_calls("DELETE", "/me/calendars/cal-default")


@row(
    19,
    "calendar_propose_new_time",
    "calendar_respond(action='tentative'|'decline', proposed_start, proposed_end)",
)
def _calendar_propose_new_time(mp: pytest.MonkeyPatch) -> None:
    proposal = {
        "proposed_start": "2026-10-02T10:00:00Z",
        "proposed_end": "2026-10-02T11:00:00Z",
    }
    with unified_session() as h:
        args = {
            "event_id": "evt-sync",
            "action": "tentative",
            "comment": "Later?",
            **proposal,
        }
        # New: sending a proposal needs confirm; nothing is sent without it.
        assert h.error("calendar_respond", args) == CONFIRM_TEXT.format(
            action="sending a response"
        )
        assert not [c for c in h.fake.calls if c.method == "POST"]
        data = h.ok("calendar_respond", {**args, "confirm": True})
        (sent,) = [c for c in h.fake.calls if c.method == "POST"]
    assert sent.path == "/me/events/evt-sync/tentativelyAccept"
    assert _instant(sent.body["proposedNewTime"]["start"]) == datetime(
        2026, 10, 2, 10, 0, tzinfo=UTC
    )
    assert _instant(sent.body["proposedNewTime"]["end"]) == datetime(
        2026, 10, 2, 11, 0, tzinfo=UTC
    )
    assert sent.body["comment"] == "Later?"
    assert data["response_sent"] is True
    assert data["proposed_start"] is not None and data["proposed_end"] is not None


@row(20, "calendar_get_free_busy", "calendar_find_availability")
def _calendar_get_free_busy(mp: pytest.MonkeyPatch) -> None:
    window = {"start": "2026-09-28T00:00:00Z", "end": "2026-09-29T00:00:00Z"}
    busy = BUSY_SEP_28
    with unified_session() as h:
        data = h.ok("calendar_find_availability", {**window, "slot_minutes": 30})
        assert _unified_busy(data) == busy
        # New: free slots are computed, inside working hours, clear of busy time.
        slots = [
            (datetime.fromisoformat(s["start"]), datetime.fromisoformat(s["end"]))
            for s in data["free_slots"]
        ]
        assert slots
        assert all(end - start == timedelta(minutes=30) for start, end in slots)
        assert all(
            end <= b_start or start >= b_end
            for start, end in slots
            for b_start, b_end in busy
        )
        assert slots[0][0] == busy[-1][1]  # first free slot follows the standup
        # New: own calendar only; attendees are no longer accepted.
        assert h.error("calendar_find_availability", {**window, "attendees": [AID]})


# ----------------------------------------------------------------------
# contact rows 21-28
# ----------------------------------------------------------------------


def _contact_addresses(contact: dict[str, Any]) -> list[str]:
    return sorted(e["address"] for e in contact["emailAddresses"])


def _vcard_properties(vcard: str) -> dict[str, list[str]]:
    """``{NAME: [values]}`` of a vCard, ignoring property parameters."""
    props: dict[str, list[str]] = {}
    for line in vcard.split("\r\n"):
        name, _, value = line.partition(":")
        props.setdefault(name.split(";")[0], []).append(value)
    return props


@row(21, "contact_list", "m365_list(resource='contact')")
def _contact_list(mp: pytest.MonkeyPatch) -> None:
    with unified_session() as h:
        items = h.ok("m365_list", {"resource": "contact", "limit": 50})["items"]
        assert {c["id"] for c in items} == {
            "contact-jane",
            "contact-mark",
            "contact-priya",
            "contact-sam",
            "contact-dentist",
            "contact-anna",
        }
        assert len(items) == 6
        assert sorted(c["display_name"] for c in items) == [
            "Anna Smith",
            "Jane Smith",
            "Mark Brown",
            "Priya Patel",
            "Sam Lee",
            "Wilson Dental",
        ]
        assert {c["id"]: c["emails"] for c in items} == {
            "contact-jane": ["jane.smith@example.com"],
            "contact-mark": ["mark.brown@example.com"],
            "contact-priya": ["priya.patel@example.com"],
            "contact-sam": ["sam.lee@example.com"],
            "contact-dentist": ["reception@wilsondental.example"],
            "contact-anna": ["anna.smith@example.com"],
        }
        # New: an optional contact folder narrows the list.
        work = h.ok(
            "m365_list",
            {"resource": "contact", "container_id": "cfolder-work"},
        )["items"]
        assert (
            [c["id"] for c in work]
            == [
                c["id"]
                for c in h.fake.contacts.values()
                if c["parentFolderId"] == "cfolder-work"
            ]
            == ["contact-priya"]
        )


@row(22, "contact_get", "m365_get(resource='contact')")
def _contact_get(mp: pytest.MonkeyPatch) -> None:
    with unified_session() as h:
        item = h.ok("m365_get", {"resource": "contact", "id": "contact-mark"})["item"]
    assert item["id"] == "contact-mark"
    assert item["display_name"] == "Mark Brown"
    assert item["given_name"] == "Mark"
    assert item["surname"] == "Brown"
    assert item["emails"] == ["mark.brown@example.com"]
    assert item["business_phones"] == ["08 8111 2222"]
    assert item["company_name"] == "Brown Engineering"
    assert item["job_title"] == "Engineer"


@row(23, "contact_create", "m365_create(resource='contact')")
def _contact_create(mp: pytest.MonkeyPatch) -> None:
    with unified_session() as h:
        data = h.ok(
            "m365_create",
            {
                "resource": "contact",
                "contact": {
                    "given_name": "Bo",
                    "surname": "Ng",
                    "emails": ["bo@example.com"],
                    "mobile_phone": "0400 000 000",
                    "business_phones": ["08 1111 2222"],
                },
            },
        )
        created = h.fake.contacts[data["item"]["id"]]
        assert created["givenName"] == "Bo"
        assert created["surname"] == "Ng"
        assert created["mobilePhone"] == "0400 000 000"
        assert created["businessPhones"] == ["08 1111 2222"]
        assert _contact_addresses(created) == ["bo@example.com"]
        assert created["parentFolderId"] == "contacts-root"

        # New: more fields and an optional folder.
        data = h.ok(
            "m365_create",
            {
                "resource": "contact",
                "contact": {
                    "given_name": "Cy",
                    "company_name": "Build Co",
                    "job_title": "Builder",
                    "department": "Works",
                    "folder_id": "cfolder-work",
                },
            },
        )
        cy = h.fake.contacts[data["item"]["id"]]
        assert cy["parentFolderId"] == "cfolder-work"
        assert (cy["companyName"], cy["jobTitle"], cy["department"]) == (
            "Build Co",
            "Builder",
            "Works",
        )


@row(24, "contact_update", "m365_update(resource='contact')")
def _contact_update(mp: pytest.MonkeyPatch) -> None:
    with unified_session() as h:
        h.ok(
            "m365_update",
            {
                "resource": "contact",
                "id": "contact-mark",
                "contact_changes": {
                    "job_title": "Principal Engineer",
                    "business_phones": ["08 9999 0000"],
                    "mobile_phone": "0400 123 456",
                },
            },
        )
        updated = h.fake.contacts["contact-mark"]
        assert updated["jobTitle"] == "Principal Engineer"
        assert updated["businessPhones"] == ["08 9999 0000"]
        assert updated["mobilePhone"] == "0400 123 456"
        assert updated["givenName"] == "Mark"
        # Fields not mentioned are unchanged.
        assert updated["companyName"] == "Brown Engineering"


@row(25, "contact_delete", "m365_delete(resource='contact')")
def _contact_delete(mp: pytest.MonkeyPatch) -> None:
    with unified_session() as h:
        # Same confirm gate: nothing is deleted without it.
        h.error(
            "m365_delete",
            {"resource": "contact", "id": "contact-sam", "confirm": False},
        )
        assert "contact-sam" in h.fake.contacts
        h.ok(
            "m365_delete", {"resource": "contact", "id": "contact-sam", "confirm": True}
        )
        assert set(h.fake.contacts) == {
            "contact-jane",
            "contact-mark",
            "contact-priya",
            "contact-dentist",
            "contact-anna",
        }


@row(26, "contact_create_list", "m365_create(resource='contact_folder')")
def _contact_create_list(mp: pytest.MonkeyPatch) -> None:
    with unified_session() as h:
        data = h.ok(
            "m365_create",
            {"resource": "contact_folder", "contact_folder": {"display_name": "Club"}},
        )
        created = h.fake.contact_folders[data["item"]["id"]]
        assert created["displayName"] == "Club"
        assert created["parentFolderId"] == "contacts-root"
        # The named folder is what m365_list contact_folder now returns.
        listed = h.ok("m365_list", {"resource": "contact_folder"})["items"]
        assert "Club" in [f["display_name"] for f in listed]


@row(27, "contact_add_to_list", "m365_move(resource='contact', destination_id)")
def _contact_add_to_list(mp: pytest.MonkeyPatch) -> None:
    def janes(fake: Any) -> dict[str, dict[str, Any]]:
        return {k: v for k, v in fake.contacts.items() if v["givenName"] == "Jane"}

    with unified_session() as h:
        data = h.ok(
            "m365_move",
            {
                "resource": "contact",
                "id": "contact-jane",
                "destination_id": "cfolder-work",
            },
        )
        # New: a real move. The original is gone, the contact has a new ID and
        # lives in the destination folder with the same details.
        moved = janes(h.fake)
        assert list(moved) == [data["id"]]
        assert data["id"] != "contact-jane"
        assert data["previous_id"] == "contact-jane"
        assert "contact-jane" not in h.fake.contacts
        contact = moved[data["id"]]
        assert contact["parentFolderId"] == "cfolder-work"
        assert contact["displayName"] == "Jane Smith"
        assert contact["surname"] == "Smith"
        assert contact["mobilePhone"] == "0412 111 222"
        assert _contact_addresses(contact) == ["jane.smith@example.com"]
        assert len(h.fake.contacts) == 6  # nothing duplicated


@row(28, "contact_export", "m365_get_content(resource='contact', mode='vcard')")
def _contact_export(mp: pytest.MonkeyPatch) -> None:
    with unified_session() as h:
        data = h.ok(
            "m365_get_content",
            {"resource": "contact", "id": "contact-mark", "mode": "vcard"},
        )
    assert data["mime_type"] == "text/vcard"
    unified = _vcard_properties(data["vcard"])
    assert unified["FN"] == ["Mark Brown"]
    assert unified["EMAIL"] == ["mark.brown@example.com"]
    assert unified["TITLE"] == ["Engineer"]


# ----------------------------------------------------------------------
# mail folder rows 29-37
# ----------------------------------------------------------------------


def _flatten_unified_tree(nodes: list[dict[str, Any]]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for node in nodes:
        pairs.append((node["id"], node["parent_id"]))
        pairs.extend(_flatten_unified_tree(node.get("children") or []))
    return sorted(pairs)


def _folder_summary(fake: Any) -> dict[str, tuple[str, str]]:
    return {
        f["id"]: (f["displayName"], f["parentFolderId"]) for f in fake.folders.values()
    }


@row(29, "emailfolders_list", "m365_list(resource='email_folder')")
def _emailfolders_list(mp: pytest.MonkeyPatch) -> None:
    with unified_session() as h:
        items = h.ok("m365_list", {"resource": "email_folder", "limit": 50})["items"]
    assert [(f["id"], f["display_name"]) for f in items] == [
        ("inbox", "Inbox"),
        ("sentitems", "Sent Items"),
        ("drafts", "Drafts"),
        ("deleteditems", "Deleted Items"),
        ("junkemail", "Junk Email"),
        ("archive", "Archive"),
        ("folder-receipts", "Receipts"),
        ("folder-old-projects", "Old Projects"),
        ("folder-reading", "Reading"),
    ]
    assert [f["unread_count"] for f in items] == [4, 0, 0, 0, 0, 0, 0, 0, 0]
    assert [f["total_count"] for f in items] == [62, 0, 0, 0, 0, 0, 0, 0, 0]
    assert "folder-conversation-history" not in {f["id"] for f in items}  # hidden
    assert len(items) == 9


@row(30, "emailfolders_get", "m365_get(resource='email_folder')")
def _emailfolders_get(mp: pytest.MonkeyPatch) -> None:
    with unified_session() as h:
        item = h.ok("m365_get", {"resource": "email_folder", "id": "folder-family"})[
            "item"
        ]
    assert item["id"] == "folder-family"
    assert item["display_name"] == "Family"
    assert item["parent_id"] == "inbox"
    assert item["child_count"] == 1


@row(31, "emailfolders_get_tree", "m365_list(resource='email_folder', recursive=true)")
def _emailfolders_get_tree(mp: pytest.MonkeyPatch) -> None:
    with unified_session() as h:
        items = h.ok(
            "m365_list",
            {"resource": "email_folder", "recursive": True, "limit": 50},
        )["items"]
    assert _flatten_unified_tree(items) == sorted(
        (folder_id, parent)
        for folder_id, (_, parent) in _folder_summary(seeded_copy()).items()
        if folder_id != "folder-conversation-history"
    )
    # The nested folders really are nested: School under Family under Inbox.
    inbox = next(f for f in items if f["id"] == "inbox")
    (family,) = inbox["children"]
    assert [c["id"] for c in family["children"]] == ["folder-school"]


@row(32, "emailfolders_create", "m365_create(resource='email_folder')")
def _emailfolders_create(mp: pytest.MonkeyPatch) -> None:
    with unified_session() as h:
        h.ok(
            "m365_create",
            {"resource": "email_folder", "email_folder": {"display_name": "Bills"}},
        )
        h.ok(
            "m365_create",
            {
                "resource": "email_folder",
                "email_folder": {"display_name": "Kids", "parent_id": "inbox"},
            },
        )
        unified = {
            name: parent
            for name, parent in _folder_summary(h.fake).values()
            if name in ("Bills", "Kids")
        }
    assert unified == {"Bills": "msgfolderroot", "Kids": "inbox"}


@row(33, "emailfolders_rename", "m365_update(resource='email_folder')")
def _emailfolders_rename(mp: pytest.MonkeyPatch) -> None:
    with unified_session() as h:
        h.ok(
            "m365_update",
            {
                "resource": "email_folder",
                "id": "folder-receipts",
                "email_folder_changes": {"display_name": "Receipts 2026"},
            },
        )
        assert _folder_summary(h.fake) == {
            **_folder_summary(seeded_copy()),
            "folder-receipts": ("Receipts 2026", "msgfolderroot"),
        }


@row(34, "emailfolders_move", "m365_move(resource='email_folder')")
def _emailfolders_move(mp: pytest.MonkeyPatch) -> None:
    with unified_session() as h:
        h.ok(
            "m365_move",
            {
                "resource": "email_folder",
                "id": "folder-reading",
                "destination_id": "archive",
            },
        )
        assert _folder_summary(h.fake) == {
            **_folder_summary(seeded_copy()),
            "folder-reading": ("Reading", "archive"),
        }


@row(35, "emailfolders_delete", "m365_delete(resource='email_folder')")
def _emailfolders_delete(mp: pytest.MonkeyPatch) -> None:
    with unified_session() as h:
        h.ok(
            "m365_delete",
            {"resource": "email_folder", "id": "folder-old-projects", "confirm": True},
        )
        assert set(h.fake.folders) == set(seeded_copy().folders) - {
            "folder-old-projects"
        }
        # New: well-known folders (by ID or alias) are refused.
        for folder in ("inbox", "deleteditems", "Deleted", "archive", "root"):
            text = h.error(
                "m365_delete",
                {"resource": "email_folder", "id": folder, "confirm": True},
            )
            assert text == f"Invalid id: {folder} cannot be deleted"
        assert {"inbox", "deleteditems", "archive"} <= set(h.fake.folders)
        assert not h.graph_calls("DELETE", "/me/mailFolders/inbox")


@row(36, "emailfolders_mark_all_as_read", "email_folder_mark_all_read")
def _emailfolders_mark_all_as_read(mp: pytest.MonkeyPatch) -> None:
    with unified_session() as h:
        junk_before = _message_state(h.fake, "junkemail")
        unread = [m for m, read in _message_state(h.fake, "inbox").items() if not read]
        assert len(unread) == 4
        # New: bounded per call. Two of four unread are marked, then the rest.
        first = h.ok(
            "email_folder_mark_all_read", {"folder_id": "inbox", "max_messages": 2}
        )
        assert first["marked"] == 2 and first["remaining_unread"] == 2
        assert sum(1 for r in _message_state(h.fake, "inbox").values() if not r) == 2
        second = h.ok("email_folder_mark_all_read", {"folder_id": "inbox"})
        assert second["marked"] == 2 and second["remaining_unread"] == 0
        # Batched through $batch, not one request per message.
        assert h.graph_calls("POST", "/$batch")
        # Every inbox message is read; other folders untouched.
        assert all(_message_state(h.fake, "inbox").values())
        assert _message_state(h.fake, "junkemail") == junk_before


@row(37, "emailfolders_empty", "email_folder_empty")
def _emailfolders_empty(mp: pytest.MonkeyPatch) -> None:
    with unified_session() as h:
        # confirm still gates it; nothing is deleted without it.
        text = h.error("email_folder_empty", {"folder_id": "junk", "confirm": False})
        assert "requires confirm=True" in text
        assert {"msg-008", "msg-009"} <= set(h.fake.messages)
        # New: bounded per call.
        first = h.ok(
            "email_folder_empty",
            {"folder_id": "junk", "max_messages": 1, "confirm": True},
        )
        assert first["deleted"] == 1 and first["remaining"] == 1
        second = h.ok("email_folder_empty", {"folder_id": "junk", "confirm": True})
        assert second["deleted"] == 1 and second["remaining"] == 0
        assert h.graph_calls("POST", "/$batch")
        assert set(h.fake.messages) == set(seeded_copy().messages) - {
            "msg-008",
            "msg-009",
        }
        assert not {"msg-008", "msg-009"} & set(h.fake.messages)
        assert "msg-013" in h.fake.messages  # other folders untouched


# ----------------------------------------------------------------------
# email rule rows 38-42
# ----------------------------------------------------------------------


@row(38, "emailrules_list", "m365_list(resource='email_rule')")
def _emailrules_list(mp: pytest.MonkeyPatch) -> None:
    with unified_session() as h:
        items = h.ok("m365_list", {"resource": "email_rule"})["items"]
    assert [
        (r["id"], r["display_name"], r["sequence"], r["is_enabled"]) for r in items
    ] == [
        ("rule-news", "Newsletters to Reading", 1, True),
        ("rule-boss", "Flag boss", 2, True),
    ]


@row(39, "emailrules_get", "m365_get(resource='email_rule')")
def _emailrules_get(mp: pytest.MonkeyPatch) -> None:
    with unified_session() as h:
        item = h.ok("m365_get", {"resource": "email_rule", "id": "rule-news"})["item"]
    assert item["id"] == "rule-news"
    assert item["display_name"] == "Newsletters to Reading"
    assert item["sequence"] == 1
    assert item["conditions"]["sender_contains"] == ["dailybrief"]
    assert item["actions"]["move_to_folder"] == "folder-reading"
    assert item["actions"]["stop_processing_rules"] is True


@row(40, "emailrules_create", "email_rule_manage(action='create')")
def _emailrules_create(mp: pytest.MonkeyPatch) -> None:
    with unified_session() as h:
        data = h.ok(
            "email_rule_manage",
            {
                "action": "create",
                "rule": {
                    "display_name": "Bills",
                    "conditions": {"sender_contains": ["billing"]},
                    "actions": {"move_to_folder": "folder-receipts"},
                },
            },
        )
        created = h.fake.rules[data["rule"]["id"]]
        assert created["conditions"] == {"senderContains": ["billing"]}
        assert created["actions"] == {"moveToFolder": "folder-receipts"}
        assert created["isEnabled"] is True

        # New: forward, redirect and delete rules need confirm; none is saved
        # without it.
        for actions, key, value in [
            ({"forward_to": ["x@example.com"]}, "forwardTo", None),
            ({"redirect_to": ["x@example.com"]}, "redirectTo", None),
            ({"delete": True}, "delete", True),
        ]:
            before = set(h.fake.rules)
            args = {
                "action": "create",
                "rule": {
                    "display_name": f"Rule {key}",
                    "conditions": {"has_attachments": True},
                    "actions": actions,
                },
            }
            assert h.error("email_rule_manage", args).startswith(
                "Invalid confirm 'False': "
            )
            assert set(h.fake.rules) == before
            saved = h.ok("email_rule_manage", {**args, "confirm": True})
            actions_stored = h.fake.rules[saved["rule"]["id"]]["actions"]
            assert key in actions_stored
            if value is not None:
                assert actions_stored[key] is value


@row(41, "emailrules_update", "email_rule_manage(action='update')")
def _emailrules_update(mp: pytest.MonkeyPatch) -> None:
    seed_rule = seeded_copy().rules["rule-news"]
    with unified_session() as h:
        data = h.ok(
            "email_rule_manage",
            {
                "action": "update",
                "rule_id": "rule-news",
                "rule": {
                    "display_name": "News",
                    "is_enabled": False,
                    "actions": {"move_to_folder": "archive"},
                },
            },
        )
        updated = h.fake.rules["rule-news"]
        assert data["rule"]["display_name"] == "News"
        assert updated["displayName"] == "News"
        assert updated["actions"] == {"moveToFolder": "archive"}
        assert updated["conditions"] == seed_rule["conditions"]
        assert updated["sequence"] == seed_rule["sequence"] == 1
        assert updated["isEnabled"] is False
        # As create: turning a rule into a redirect needs confirm.
        args = {
            "action": "update",
            "rule_id": "rule-boss",
            "rule": {"actions": {"redirect_to": ["x@example.com"]}},
        }
        assert h.error("email_rule_manage", args).startswith(
            "Invalid confirm 'False': "
        )
        assert "redirectTo" not in h.fake.rules["rule-boss"]["actions"]
        h.ok("email_rule_manage", {**args, "confirm": True})
        assert "redirectTo" in h.fake.rules["rule-boss"]["actions"]


@row(42, "emailrules_delete", "m365_delete(resource='email_rule')")
def _emailrules_delete(mp: pytest.MonkeyPatch) -> None:
    with unified_session() as h:
        h.error(
            "m365_delete",
            {"resource": "email_rule", "id": "rule-boss", "confirm": False},
        )
        assert "rule-boss" in h.fake.rules
        h.ok(
            "m365_delete",
            {"resource": "email_rule", "id": "rule-boss", "confirm": True},
        )
        assert set(h.fake.rules) == {"rule-news"}


MAIL_DRIVE_ROWS = [mapping_row(i) for i in range(43, MAPPING_ROW_COUNT)]

Scenario = Callable[[UnifiedHarness], None]
NAMED_SCENARIOS: dict[str, Scenario] = {}


def scenario(legacy_tool: str) -> Callable[[Scenario], Scenario]:
    """Register the scenario for the mapping row of ``legacy_tool``."""

    def register(fn: Scenario) -> Scenario:
        assert legacy_tool not in NAMED_SCENARIOS
        NAMED_SCENARIOS[legacy_tool] = fn
        return fn

    return register


# ----------------------------------------------------------------------
# shared views and helpers
# ----------------------------------------------------------------------
SEED_MESSAGE_IDS = set(seeded_copy().messages)
SEED_DRIVE_IDS = set(seeded_copy().drive)


def _addrs(recipients: list[dict[str, Any]]) -> list[str]:
    return sorted(r["emailAddress"]["address"] for r in recipients)


def _new_messages(g: FakeGraph) -> list[tuple[Any, ...]]:
    """Messages that were not in the seed: content only (ids differ)."""
    return sorted(
        (
            m["parentFolderId"],
            m["subject"],
            tuple(_addrs(m["toRecipients"])),
            tuple(_addrs(m["ccRecipients"])),
            m["body"]["content"],
        )
        for mid, m in g.messages.items()
        if mid not in SEED_MESSAGE_IDS
    )


def _folder_of(g: FakeGraph, subject: str) -> list[str]:
    return sorted(
        m["parentFolderId"] for m in g.messages.values() if m["subject"] == subject
    )


def _msg(g: FakeGraph, msg_id: str, *fields: str) -> tuple[Any, ...]:
    return tuple(g.messages[msg_id][f] for f in fields)


def _local_file(h: UnifiedHarness, name: str, data: bytes) -> str:
    (h.sandbox / name).write_bytes(data)
    return name


# ----------------------------------------------------------------------
# rows 43-46: email rule reordering
# ----------------------------------------------------------------------
def _add_third_rule(g: FakeGraph) -> None:
    g.rules["rule-third"] = {
        "id": "rule-third",
        "displayName": "Third",
        "sequence": 3,
        "isEnabled": True,
        "hasError": False,
        "isReadOnly": False,
        "conditions": {"subjectContains": ["x"]},
        "actions": {"markAsRead": True},
    }


def _rule_order(g: FakeGraph) -> list[str]:
    return [r["id"] for r in sorted(g.rules.values(), key=lambda r: r["sequence"])]


def _rule_reorder(
    h: UnifiedHarness,
    rule_id: str,
    position: str,
    expected: list[str],
) -> None:
    _add_third_rule(h.fake)
    assert _rule_order(h.fake) == ["rule-news", "rule-boss", "rule-third"]
    h.ok(
        "email_rule_manage",
        {"action": "reorder", "rule_id": rule_id, "position": position},
    )
    assert _rule_order(h.fake) == expected


@scenario("emailrules_move_top")
def _(h: UnifiedHarness) -> None:
    _rule_reorder(
        h, "rule-third", "top",
        ["rule-third", "rule-news", "rule-boss"],
    )  # fmt: skip


@scenario("emailrules_move_bottom")
def _(h: UnifiedHarness) -> None:
    _rule_reorder(
        h, "rule-news", "bottom",
        ["rule-boss", "rule-third", "rule-news"],
    )  # fmt: skip


@scenario("emailrules_move_up")
def _(h: UnifiedHarness) -> None:
    _rule_reorder(
        h, "rule-third", "up",
        ["rule-news", "rule-third", "rule-boss"],
    )  # fmt: skip


@scenario("emailrules_move_down")
def _(h: UnifiedHarness) -> None:
    _rule_reorder(
        h, "rule-news", "down",
        ["rule-boss", "rule-news", "rule-third"],
    )  # fmt: skip


# ----------------------------------------------------------------------
# rows 47-61: email
# ----------------------------------------------------------------------
INBOX_IDS = {
    m["id"] for m in seeded_copy().messages.values() if m["parentFolderId"] == "inbox"
}


@scenario("email_list")
def _(h: UnifiedHarness) -> None:
    # Practical task: list the newest inbox messages.
    page = h.ok("m365_list", {"resource": "email", "container_id": "inbox", "limit": 5})
    assert [m["id"] for m in page["items"]] == [
        "msg-005",
        "msg-news-00",
        "msg-news-01",
        "msg-news-02",
        "msg-news-03",
    ]

    # NEW: compact items carry a preview, not the body.
    for item in page["items"]:
        assert item["preview"] and "body" not in item
    # NEW: filters.
    unread = h.ok(
        "m365_list",
        {
            "resource": "email",
            "container_id": "inbox",
            "email_filter": {"unread": True},
            "limit": 50,
        },
    )
    assert {m["id"] for m in unread["items"]} == {
        m["id"]
        for m in h.fake.messages.values()
        if m["parentFolderId"] == "inbox" and not m["isRead"]
    }
    # NEW: cursor paging walks the whole folder without repeats.
    seen: list[str] = []
    cursor = None
    while True:
        args: dict[str, Any] = {
            "resource": "email",
            "container_id": "inbox",
            "limit": 7,
        }
        if cursor:
            args["cursor"] = cursor
        page = h.ok("m365_list", args)
        seen += [m["id"] for m in page["items"]]
        cursor = page.get("next_cursor")
        if not cursor:
            break
    assert len(seen) == len(set(seen)) and set(seen) == INBOX_IDS


@scenario("email_get")
def _(h: UnifiedHarness) -> None:
    long_body = "word " * 8000  # 40,000 characters
    h.fake.messages["msg-004"]["body"]["content"] = long_body
    # NEW: the default body cap is 20k characters (legacy default was 50k).
    default = h.ok("m365_get", {"resource": "email", "id": "msg-004"})["item"]
    assert len(default["body"]) == 20000 and default["body_truncated"] is True
    assert default["attachments"][0]["name"] == "INV-2291.pdf"
    wide = h.ok(
        "m365_get", {"resource": "email", "id": "msg-004", "body_max_chars": 50000}
    )["item"]
    assert wide["body"] == long_body and wide["body_truncated"] is False


@scenario("email_create_draft")
def _(h: UnifiedHarness) -> None:
    h.ok(
        "email_create_draft",
        {
            "to": ["sam.lee@example.com"],
            "cc": ["mark.brown@example.com"],
            "subject": "Modem",
            "body": "It came.",
        },
    )
    expected = [
        (
            "drafts",
            "Modem",
            ("sam.lee@example.com",),
            ("mark.brown@example.com",),
            "It came.",
        )
    ]
    assert _new_messages(h.fake) == expected

    # NEW: bcc, body_format and importance.
    h.ok(
        "email_create_draft",
        {
            "to": ["sam.lee@example.com"],
            "bcc": ["boss@example.com"],
            "subject": "Formatted",
            "body": "<b>Hi</b>",
            "body_format": "html",
            "importance": "high",
        },
    )
    (draft,) = [
        m
        for mid, m in h.fake.messages.items()
        if mid not in SEED_MESSAGE_IDS and m["subject"] == "Formatted"
    ]
    assert _addrs(draft["bccRecipients"]) == ["boss@example.com"]
    assert draft["body"] == {"contentType": "HTML", "content": "<b>Hi</b>"}
    assert draft["importance"] == "high" and draft["parentFolderId"] == "drafts"


@scenario("email_send")
def _(h: UnifiedHarness) -> None:
    h.ok(
        "email_send",
        {
            "mode": "new",
            "to": ["sam.lee@example.com"],
            "subject": "Modem arrived",
            "body": "It came.",
            "confirm": True,
        },
    )
    expected = [
        ("sentitems", "Modem arrived", ("sam.lee@example.com",), (), "It came.")
    ]
    assert _new_messages(h.fake) == expected

    # NEW: bcc is delivered.
    h.ok(
        "email_send",
        {
            "mode": "new",
            "to": ["sam.lee@example.com"],
            "bcc": ["boss@example.com"],
            "subject": "Hidden copy",
            "body": "x",
            "confirm": True,
        },
    )
    (sent,) = [m for m in h.fake.messages.values() if m["subject"] == "Hidden copy"]
    assert _addrs(sent["bccRecipients"]) == ["boss@example.com"]
    # NEW: mode='draft' sends an existing draft.
    draft = h.ok(
        "email_create_draft",
        {"to": ["sam.lee@example.com"], "subject": "Later", "body": "y"},
    )["draft_id"]
    assert h.fake.messages[draft]["parentFolderId"] == "drafts"
    h.ok("email_send", {"mode": "draft", "draft_id": draft, "confirm": True})
    assert h.fake.messages[draft]["parentFolderId"] == "sentitems"
    assert h.fake.messages[draft]["isDraft"] is False


@scenario("email_update")
def _(h: UnifiedHarness) -> None:
    fields = ("isRead", "importance", "categories")
    before = _msg(seeded_copy(), "msg-001", *fields)
    h.ok(
        "m365_update",
        {
            "resource": "email",
            "id": "msg-001",
            "email_changes": {
                "is_read": True,
                "importance": "high",
                "categories_set": ["Home"],
            },
        },
    )
    after = _msg(h.fake, "msg-001", *fields)
    assert after == (True, "high", ["Home"])
    assert after != before  # the call changed the message


@scenario("email_delete")
def _(h: UnifiedHarness) -> None:
    subject = "Invoice INV-2291 from Acme Plumbing"
    assert _folder_of(seeded_copy(), subject) == ["inbox"]
    h.ok("m365_delete", {"resource": "email", "id": "msg-004", "confirm": True})
    assert _folder_of(h.fake, subject) == []
    # Refused without confirmation.
    text = h.error(
        "m365_delete", {"resource": "email", "id": "msg-005", "confirm": False}
    )
    assert "confirm" in text and "msg-005" in h.fake.messages


@scenario("email_move")
def _(h: UnifiedHarness) -> None:
    data = h.ok(
        "m365_move",
        {"resource": "email", "id": "msg-004", "destination_id": "drafts"},
    )
    # NEW: the move returns the new message ID; the old one is gone.
    assert data["id"] != "msg-004" and data["previous_id"] == "msg-004"
    assert "msg-004" not in h.fake.messages
    assert h.fake.messages[data["id"]]["parentFolderId"] == "drafts"
    assert _folder_of(h.fake, "Invoice INV-2291 from Acme Plumbing") == ["drafts"]


def _reply_scenario(h: UnifiedHarness, mode: str) -> None:
    """msg-003 (from Jane, cc Mark) replied to (sender or all)."""
    h.ok(
        "email_reply",
        {
            "email_id": "msg-003",
            "mode": mode,
            "body": "Yes, see you 7.",
            "confirm": True,
        },
    )

    assert [
        (m["parentFolderId"], m["subject"], m["body"]["content"])
        for mid, m in h.fake.messages.items()
        if mid not in SEED_MESSAGE_IDS
    ] == [("sentitems", "Re: Dinner on Saturday?", "Yes, see you 7.")]

    # NEW: cc and attachments on the reply.
    name = _local_file(h, "map.txt", b"the map")
    h.ok(
        "email_reply",
        {
            "email_id": "msg-003",
            "mode": mode,
            "body": "Map attached",
            "cc": ["kim@example.com"],
            "attachments": [name],
            "confirm": True,
        },
    )
    (sent,) = [
        (mid, m)
        for mid, m in h.fake.messages.items()
        if mid not in SEED_MESSAGE_IDS
        and "kim@example.com" in _addrs(m["ccRecipients"])
    ]
    assert sent[1]["parentFolderId"] == "sentitems"
    assert h.fake.attachments[sent[0]][0]["name"] == name
    assert base64.b64decode(h.fake.attachments[sent[0]][0]["contentBytes"]) == (
        b"the map"
    )


@scenario("email_reply")
def _(h: UnifiedHarness) -> None:
    _reply_scenario(h, "sender")


@scenario("email_reply_all")
def _(h: UnifiedHarness) -> None:
    _reply_scenario(h, "all")


@scenario("email_forward")
def _(h: UnifiedHarness) -> None:
    h.ok(
        "email_forward",
        {
            "email_id": "msg-004",
            "to": ["sam.lee@example.com"],
            "comment": "FYI",
            "confirm": True,
        },
    )

    assert [
        (m["parentFolderId"], m["subject"], tuple(_addrs(m["toRecipients"])))
        for mid, m in h.fake.messages.items()
        if mid not in SEED_MESSAGE_IDS
    ] == [
        (
            "sentitems",
            "Fw: Invoice INV-2291 from Acme Plumbing",
            ("sam.lee@example.com",),
        )
    ]

    # NEW: bcc and attachments.
    name = _local_file(h, "extra.txt", b"extra")
    h.ok(
        "email_forward",
        {
            "email_id": "msg-004",
            "to": ["sam.lee@example.com"],
            "bcc": ["boss@example.com"],
            "attachments": [name],
            "confirm": True,
        },
    )
    (sent,) = [
        (mid, m)
        for mid, m in h.fake.messages.items()
        if mid not in SEED_MESSAGE_IDS and _addrs(m["bccRecipients"])
    ]
    assert _addrs(sent[1]["bccRecipients"]) == ["boss@example.com"]
    assert sent[1]["parentFolderId"] == "sentitems"
    assert h.fake.attachments[sent[0]][0]["name"] == name


@scenario("email_get_attachment")
def _(h: UnifiedHarness) -> None:
    args = {
        "resource": "email",
        "id": "msg-004",
        "attachment_id": "att-invoice",
        "mode": "download",
        "save_path": "inv.pdf",
    }
    h.ok("m365_get_content", args)
    expected = b"fake INV-2291.pdf content"
    assert (h.sandbox / "inv.pdf").read_bytes() == expected
    # NEW: no silent overwrite.
    (h.sandbox / "inv.pdf").write_bytes(b"precious")
    text = h.error("m365_get_content", args)
    assert "already exists" in text or "overwrite" in text
    assert (h.sandbox / "inv.pdf").read_bytes() == b"precious"
    h.ok("m365_get_content", {**args, "overwrite": True})
    assert (h.sandbox / "inv.pdf").read_bytes() == expected


@scenario("email_mark_read")
def _(h: UnifiedHarness) -> None:
    assert _msg(seeded_copy(), "msg-001", "isRead") == (False,)
    h.ok(
        "m365_update",
        {"resource": "email", "id": "msg-001", "email_changes": {"is_read": True}},
    )
    assert _msg(h.fake, "msg-001", "isRead") == (True,)


@scenario("email_flag")
def _(h: UnifiedHarness) -> None:
    assert seeded_copy().messages["msg-001"]["flag"]["flagStatus"] != "flagged"
    h.ok(
        "m365_update",
        {
            "resource": "email",
            "id": "msg-001",
            "email_changes": {"flag": {"status": "flagged"}},
        },
    )
    assert h.fake.messages["msg-001"]["flag"]["flagStatus"] == "flagged"


@scenario("email_add_category")
def _(h: UnifiedHarness) -> None:
    h.fake.messages["msg-001"]["categories"] = ["Home"]
    h.ok(
        "m365_update",
        {
            "resource": "email",
            "id": "msg-001",
            "email_changes": {"categories_add": ["Bills"]},
        },
    )
    # categories_add keeps what was there (the retired tool replaced the list).
    assert sorted(h.fake.messages["msg-001"]["categories"]) == ["Bills", "Home"]
    # NEW: remove and set are also available.
    h.ok(
        "m365_update",
        {
            "resource": "email",
            "id": "msg-001",
            "email_changes": {"categories_remove": ["Home"]},
        },
    )
    assert h.fake.messages["msg-001"]["categories"] == ["Bills"]
    h.ok(
        "m365_update",
        {
            "resource": "email",
            "id": "msg-001",
            "email_changes": {"categories_set": ["Work"]},
        },
    )
    assert h.fake.messages["msg-001"]["categories"] == ["Work"]


@scenario("email_archive")
def _(h: UnifiedHarness) -> None:
    data = h.ok(
        "m365_move", {"resource": "email", "id": "msg-004", "destination_id": "archive"}
    )
    assert h.fake.messages[data["id"]]["parentFolderId"] == "archive"
    assert _folder_of(h.fake, "Invoice INV-2291 from Acme Plumbing") == ["archive"]


# ----------------------------------------------------------------------
# rows 62-78: OneDrive files and folders
# ----------------------------------------------------------------------
def _drive_state(g: FakeGraph) -> list[tuple[Any, ...]]:
    """Every drive item as (name, parent id, content); ids may differ."""
    return sorted(
        (v["name"], v["parentReference"]["id"], v.get("_content", b""))
        for k, v in g.drive.items()
        if k != "root"
    )


def _expected_drive(
    remove: tuple[str, ...] = (), add: tuple[tuple[Any, ...], ...] = ()
) -> list[tuple[Any, ...]]:
    """The seeded drive state minus ``remove`` item IDs plus ``add`` entries."""
    seed = seeded_copy()
    kept = [
        (v["name"], v["parentReference"]["id"], v.get("_content", b""))
        for k, v in seed.drive.items()
        if k != "root" and k not in remove
    ]
    return sorted([*kept, *add])


def _seed_entry(item_id: str, **changes: Any) -> tuple[Any, ...]:
    """A seeded drive item as a state tuple, with name/parent/content changed."""
    item = seeded_copy().drive[item_id]
    return (
        changes.get("name", item["name"]),
        changes.get("parent", item["parentReference"]["id"]),
        changes.get("content", item.get("_content", b"")),
    )


@scenario("file_list")
def _(h: UnifiedHarness) -> None:
    page = h.ok(
        "m365_list",
        {"resource": "drive_item", "path": "/Documents", "item_type": "file"},
    )
    names = {i["name"] for i in page["items"]}
    assert names == {"budget.xlsx", "CV.docx"}
    assert {i["item_type"] for i in page["items"]} == {"file"}


@scenario("file_get")
def _(h: UnifiedHarness) -> None:
    # Details and download are split: m365_get for details ...
    item = h.ok("m365_get", {"resource": "drive_item", "id": "item-cv"})["item"]
    assert (item["name"], item["size"], item["item_type"]) == (
        "CV.docx",
        31004,
        "file",
    )
    # ... and m365_get_content(mode='download') for the bytes.
    h.ok(
        "m365_get_content",
        {
            "resource": "drive_item",
            "id": "item-cv",
            "mode": "download",
            "save_path": "cv.docx",
        },
    )
    assert (h.sandbox / "cv.docx").read_bytes() == b"fake contents of CV.docx"


@scenario("file_create")
def _(h: UnifiedHarness) -> None:
    h.ok("drive_upload", {"local_path": "report.pdf", "parent_path": "/Documents"})
    local = (h.sandbox / "report.pdf").read_bytes()
    assert _drive_state(h.fake) == _expected_drive(
        add=(("report.pdf", "item-documents", local),)
    )

    # NEW: if_exists defaults to fail, so an existing name is refused (the
    # legacy tool silently overwrote it) and the original is untouched.
    before = h.fake.drive["item-cv"]["_content"]
    text = h.error(
        "drive_upload",
        {"local_path": "report.pdf", "parent_path": "/Documents", "name": "CV.docx"},
    )
    assert text.startswith("A file named 'CV.docx' already exists there.")
    assert h.fake.drive["item-cv"]["_content"] == before
    h.ok(
        "drive_upload",
        {
            "local_path": "report.pdf",
            "parent_path": "/Documents",
            "name": "CV.docx",
            "if_exists": "replace",
        },
    )
    assert h.fake.drive["item-cv"]["_content"] == local


@scenario("file_update")
def _(h: UnifiedHarness) -> None:
    h.ok("drive_upload", {"local_path": "notes-new.txt", "item_id": "item-notes"})
    local = (h.sandbox / "notes-new.txt").read_bytes()
    assert local != seeded_copy().drive["item-notes"]["_content"]
    assert _drive_state(h.fake) == _expected_drive(
        remove=("item-notes",),
        add=(_seed_entry("item-notes", content=local),),
    )


@scenario("file_delete")
def _(h: UnifiedHarness) -> None:
    # Not confirmed: refused, nothing deleted.
    h.error(
        "m365_delete", {"resource": "drive_item", "id": "item-cv", "confirm": False}
    )
    assert "item-cv" in h.fake.drive
    h.ok("m365_delete", {"resource": "drive_item", "id": "item-cv", "confirm": True})
    assert "item-cv" not in h.fake.drive
    assert _drive_state(h.fake) == _expected_drive(remove=("item-cv",))
    # NEW: the tool says the item goes to the recycle bin.
    spec = json.loads(
        (MAPPING_PATH.parent / "tools/m365_delete.json").read_text(encoding="utf-8")
    )
    assert "recycle bin" in spec["description"]


@scenario("file_copy")
def _(h: UnifiedHarness) -> None:
    result = h.ok(
        "drive_copy",
        {
            "item_id": "item-cv",
            "destination_id": "item-photos",
            "new_name": "CV copy.docx",
        },
    )
    # NEW: an operation handle with a status instead of "copy initiated".
    op_id = result["operation_id"]
    assert result["status"] == "in_progress" and op_id.startswith("op_")
    status = h.ok("m365_get", {"resource": "operation", "id": op_id})["item"]
    assert status["status"] == "completed"
    copied = h.fake.drive[status["resource_id"]]
    assert copied["name"] == "CV copy.docx"
    assert copied["parentReference"]["id"] == "item-photos"
    assert h.fake.drive["item-cv"]["parentReference"]["id"] == "item-documents"
    assert _drive_state(h.fake) == _expected_drive(
        add=(
            _seed_entry(
                "item-cv", name="CV copy.docx", parent="item-photos", content=b""
            ),
        )
    )


@scenario("file_move")
def _(h: UnifiedHarness) -> None:
    h.ok(
        "m365_move",
        {"resource": "drive_item", "id": "item-cv", "destination_id": "item-photos"},
    )
    assert h.fake.drive["item-cv"]["parentReference"]["id"] == "item-photos"
    assert _drive_state(h.fake) == _expected_drive(
        remove=("item-cv",), add=(_seed_entry("item-cv", parent="item-photos"),)
    )


@scenario("file_rename")
def _(h: UnifiedHarness) -> None:
    h.ok(
        "m365_update",
        {
            "resource": "drive_item",
            "id": "item-cv",
            "drive_item_changes": {"name": "CV-2026.docx"},
        },
    )
    assert h.fake.drive["item-cv"]["name"] == "CV-2026.docx"
    assert _drive_state(h.fake) == _expected_drive(
        remove=("item-cv",), add=(_seed_entry("item-cv", name="CV-2026.docx"),)
    )


@scenario("file_share")
def _(h: UnifiedHarness) -> None:
    args = {"item_id": "item-cv", "mode": "link", "link_type": "view"}
    unconfirmed = {**args, "confirm": False}
    # NEW: confirm is required; nothing is created without it.
    text = h.error("drive_share", unconfirmed)
    assert text.startswith("Invalid confirm 'False': sharing requires confirm=True")
    assert not h.graph_calls("POST", "/me/drive/items/item-cv/createLink")
    # NEW: no default scope/type; link_type must be chosen.
    text = h.error(
        "drive_share", {"item_id": "item-cv", "mode": "link", "confirm": True}
    )
    assert text == "Invalid link_type: required when mode='link'"
    assert not h.graph_calls("POST", "/me/drive/items/item-cv/createLink")
    result = h.ok("drive_share", {**args, "confirm": True})
    assert result["link_url"] == "https://1drv.ms/x/s!item-cv-view"
    assert result["created"] is True
    (call,) = h.graph_calls("POST", "/me/drive/items/item-cv/createLink")
    assert call.body == {"type": "view", "scope": "anonymous"}
    # NEW: invite mode.
    invited = h.ok(
        "drive_share",
        {
            "item_id": "item-cv",
            "mode": "invite",
            "recipients": ["sam.lee@example.com"],
            "role": "read",
            "confirm": True,
        },
    )
    assert invited["mode"] == "invite"
    (invite,) = h.graph_calls("POST", "/me/drive/items/item-cv/invite")
    assert invite.body["recipients"] == [{"email": "sam.lee@example.com"}]
    assert invite.body["roles"] == ["read"]


@scenario("file_download_url")
def _(h: UnifiedHarness) -> None:
    result = h.ok(
        "m365_get_content",
        {"resource": "drive_item", "id": "item-cv", "mode": "download_url"},
    )
    assert result["download_url"] == "https://fake.1drv.com/download/item-cv"
    assert result["saved_path"] is None


@scenario("folder_list")
def _(h: UnifiedHarness) -> None:
    page = h.ok(
        "m365_list",
        {"resource": "drive_item", "path": "/Documents", "item_type": "folder"},
    )
    names = {i["name"] for i in page["items"]}
    assert names == {"Old", "Tax"}
    assert {i["item_type"] for i in page["items"]} == {"folder"}


@scenario("folder_get")
def _(h: UnifiedHarness) -> None:
    item = h.ok("m365_get", {"resource": "drive_item", "id": "item-tax"})["item"]
    assert (item["name"], item["child_count"], item["item_type"]) == (
        "Tax",
        1,
        "folder",
    )


@scenario("folder_get_tree")
def _(h: UnifiedHarness) -> None:
    tree = h.ok(
        "m365_list",
        {
            "resource": "drive_item",
            "path": "/Documents",
            "item_type": "folder",
            "recursive": True,
        },
    )
    assert {i["name"] for i in tree["items"]} == {"Old", "Tax"}
    assert all(i["children"] == [] for i in tree["items"])


@scenario("folder_create")
def _(h: UnifiedHarness) -> None:
    result = h.ok(
        "m365_create",
        {
            "resource": "drive_item",
            "drive_folder": {"name": "Receipts", "parent_id": "item-documents"},
        },
    )
    assert result["item"]["name"] == "Receipts"
    assert result["item"]["item_type"] == "folder"
    assert h.fake.drive[result["item"]["id"]]["folder"] is not None
    assert _drive_state(h.fake) == _expected_drive(
        add=(("Receipts", "item-documents", b""),)
    )


@scenario("folder_delete")
def _(h: UnifiedHarness) -> None:
    h.error(
        "m365_delete", {"resource": "drive_item", "id": "item-old", "confirm": False}
    )
    assert "item-old" in h.fake.drive
    h.ok("m365_delete", {"resource": "drive_item", "id": "item-old", "confirm": True})
    assert "item-old" not in h.fake.drive
    assert _drive_state(h.fake) == _expected_drive(
        remove=("item-old", "item-receipts2024")  # its contents go with it
    )


@scenario("folder_rename")
def _(h: UnifiedHarness) -> None:
    h.ok(
        "m365_update",
        {
            "resource": "drive_item",
            "id": "item-old",
            "drive_item_changes": {"name": "Older"},
        },
    )
    assert h.fake.drive["item-old"]["name"] == "Older"
    assert _drive_state(h.fake) == _expected_drive(
        remove=("item-old",), add=(_seed_entry("item-old", name="Older"),)
    )


@scenario("folder_move")
def _(h: UnifiedHarness) -> None:
    h.ok(
        "m365_move",
        {"resource": "drive_item", "id": "item-old", "destination_id": "item-photos"},
    )
    assert h.fake.drive["item-old"]["parentReference"]["id"] == "item-photos"
    assert _drive_state(h.fake) == _expected_drive(
        remove=("item-old",), add=(_seed_entry("item-old", parent="item-photos"),)
    )


# ----------------------------------------------------------------------
# rows 79-84: search and server info
# ----------------------------------------------------------------------
def _hits(result: dict[str, Any], resource: str) -> list[dict[str, Any]]:
    return [i["item"] for i in result["items"] if i["resource"] == resource]


def _bury_message(g: FakeGraph) -> None:
    """An old archived message hidden behind 260 newer inbox messages."""
    template = dict(g.messages["msg-002"])
    for n in range(260):
        g.messages[f"msg-filler-{n:03d}"] = {
            **template,
            "id": f"msg-filler-{n:03d}",
            "subject": f"Filler {n}",
            "body": {"contentType": "text", "content": "nothing"},
            "bodyPreview": "nothing",
            "receivedDateTime": g.at(-1, 1),
        }
    g.messages["msg-zebra"] = {
        **template,
        "id": "msg-zebra",
        "subject": "Zebra quote",
        "body": {"contentType": "text", "content": "the zebra quote is attached"},
        "bodyPreview": "the zebra quote is attached",
        "parentFolderId": "archive",
        "receivedDateTime": g.at(-400, 1),
    }


@scenario("search_files")
def _(h: UnifiedHarness) -> None:
    result = h.ok("m365_search", {"query": "budget", "resources": ["drive_item"]})
    names = {i["name"] for i in _hits(result, "drive_item")}
    assert names == {"budget.xlsx"}
    assert {i["resource"] for i in result["items"]} == {"drive_item"}


@scenario("search_emails")
def _(h: UnifiedHarness) -> None:
    # Practical task on the seeded mailbox: find the Telstra messages.
    result = h.ok("m365_search", {"query": "telstra", "resources": ["email"]})
    assert {m["id"] for m in _hits(result, "email")} == {"msg-001", "msg-002"}

    # NEW: the whole mailbox via server-side $search. A message older than
    # the newest 250 (and outside the inbox) is still found.
    _bury_message(h.fake)
    h.clear_calls()
    found = h.ok("m365_search", {"query": "zebra", "resources": ["email"]})
    assert [(m["id"], m["folder_id"]) for m in _hits(found, "email")] == [
        ("msg-zebra", "archive")
    ]
    (call,) = h.graph_calls("GET", "/me/messages")
    assert call.params["$search"] == '"zebra"'
    assert "$filter" not in call.params


@scenario("search_events")
def _(h: UnifiedHarness) -> None:
    # NEW: an explicit window bounds the search (calendarView).
    inside = h.ok(
        "m365_search",
        {
            "query": "dentist",
            "resources": ["event"],
            "event_start": "2026-09-28T00:00:00Z",
            "event_end": "2026-10-05T00:00:00Z",
        },
    )
    assert [e["id"] for e in _hits(inside, "event")] == ["evt-dentist"]
    (view,) = h.graph_calls("GET", "/me/calendarView")
    assert view.params["startDateTime"].startswith("2026-09-28")
    assert view.params["endDateTime"].startswith("2026-10-05")
    outside = h.ok(
        "m365_search",
        {
            "query": "dentist",
            "resources": ["event"],
            "event_start": "2026-10-06T00:00:00Z",
            "event_end": "2026-10-20T00:00:00Z",
        },
    )
    assert _hits(outside, "event") == []
    text = h.error(
        "m365_search",
        {
            "query": "dentist",
            "resources": ["event"],
            "event_start": "2026-10-06T00:00:00Z",
            "event_end": "2026-10-01T00:00:00Z",
        },
    )
    assert text == "Invalid event_end: must be after event_start and within 731 days"


@scenario("search_contacts")
def _(h: UnifiedHarness) -> None:
    result = h.ok("m365_search", {"query": "smith", "resources": ["contact"]})
    ids = {c["id"] for c in _hits(result, "contact")}
    assert ids == {"contact-jane", "contact-anna"}


@scenario("search_unified")
def _(h: UnifiedHarness) -> None:
    h.clear_calls()
    result = h.ok(
        "m365_search",
        {"query": "budget", "resources": ["email", "drive_item", "event", "contact"]},
    )
    kinds = {i["resource"] for i in result["items"]}
    assert {"email", "drive_item"} <= kinds
    assert {m["id"] for m in _hits(result, "email")} == {"msg-006", "msg-012"}
    assert [d["name"] for d in _hits(result, "drive_item")] == ["budget.xlsx"]
    # NEW: fan-out over the per-resource endpoints; no Search API path.
    assert not h.graph_calls(None, "/search/query")
    paths = {c.path for c in h.fake.calls}
    assert {"/me/messages", "/me/calendarView", "/me/contacts"} <= paths
    assert "/me/drive/root/search(q='budget')" in paths


@scenario("server_get_version")
def _(h: UnifiedHarness) -> None:
    info = h.ok("admin_server_info", {})
    assert info["version"] == version("m365-mcp")
    assert info["tool_count"] == 29 and "admin" in info["toolsets_enabled"]


# ----------------------------------------------------------------------
# the parametrized entry point
# ----------------------------------------------------------------------
def test_every_row_has_a_scenario() -> None:
    assert len(MAIL_DRIVE_ROWS) == 42
    assert {r["legacy_tool"] for r in MAIL_DRIVE_ROWS} == set(NAMED_SCENARIOS)
    assert MAIL_DRIVE_ROWS[0]["legacy_tool"] == "emailrules_move_top"
    assert MAIL_DRIVE_ROWS[-1]["legacy_tool"] == "server_get_version"


@pytest.mark.parametrize(
    "row", MAIL_DRIVE_ROWS, ids=[r["legacy_tool"] for r in MAIL_DRIVE_ROWS]
)
def test_parity(harness: UnifiedHarness, row: dict[str, Any]) -> None:
    NAMED_SCENARIOS[row["legacy_tool"]](harness)


def test_mapping_rows_are_all_covered() -> None:
    """All 85 mapping rows have a scenario; none is registered twice."""
    total = len(json.loads(MAPPING_PATH.read_text(encoding="utf-8"))["mapping"])
    assert total == MAPPING_ROW_COUNT == ROW_COUNT + len(MAIL_DRIVE_ROWS)
    assert set(ROW_SCENARIOS) == set(range(ROW_COUNT))
    assert len(NAMED_SCENARIOS) == len(MAIL_DRIVE_ROWS)
