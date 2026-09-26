"""Parity tests for ``legacy_mapping.json`` rows 0-42 (task U3.30, part 1).

One parametrized test per row. Each scenario performs the practical task
the legacy tool was used for through the unified surface and asserts the
resulting fake-Graph state or structured result. Where the legacy tool is
a plain equivalent, the same task also runs through the legacy tool on a
fresh, identically seeded fake Graph and the two end states are compared.
Where the row has a ``behaviour_change`` the NEW behaviour is asserted (the
legacy surface is used only to show what changed, when that is useful).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from m365_mcp import auth, auth_sessions, cache
from m365_mcp.tools import cache_tools
from tests.parity_helpers import legacy_session, mapping_row, unified_session

AID = "alex.morgan@outlook.com"
ROW_COUNT = 43

SCENARIOS: dict[int, Callable[[pytest.MonkeyPatch], None]] = {}


def row(index: int, legacy_tool: str, replacement: str) -> Callable[[Any], Any]:
    """Register a scenario for mapping row ``index``.

    The names are checked against ``legacy_mapping.json`` so a scenario
    cannot silently drift from the row it claims to cover.
    """

    def register(fn: Any) -> Any:
        fn.expected = (legacy_tool, replacement)  # type: ignore[attr-defined]
        SCENARIOS[index] = fn
        return fn

    return register


@pytest.mark.parametrize("index", range(ROW_COUNT))
def test_parity_row(index: int, monkeypatch: pytest.MonkeyPatch) -> None:
    """The replacement completes the same practical task as the legacy tool."""
    scenario = SCENARIOS.get(index)
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
    with legacy_session() as lg:
        legacy = lg.call("account_list")
    assert legacy[0]["account_type"] == "personal"  # the field being removed

    with unified_session() as h:
        data = h.ok("account_list", {})
    (account,) = data["accounts"]
    assert set(account) == {"account_id", "email", "display_name"}
    assert "account_type" not in json.dumps(data)
    # Same account as the legacy tool reports.
    assert account["email"] == legacy[0]["username"]
    assert account["account_id"] == legacy[0]["account_id"]
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
    with legacy_session() as lg:
        (task_id,) = _enqueue(AID, ["email_list"])
        legacy = lg.call("cache_task_get_status", {"task_id": task_id})

    with unified_session() as h:
        (task_id,) = _enqueue(h.account_id, ["email_list"])
        data = h.ok("admin_cache_get", {"view": "task", "task_id": task_id})
    (task,) = data["tasks"]
    assert task["task_id"] == task_id
    for legacy_key, key in [
        ("status", "status"),
        ("operation", "operation"),
        ("retry_count", "retry_count"),
    ]:
        assert task[key] == legacy[legacy_key]
    assert task["priority"] == 3 and task["status"] == "queued"


@row(4, "cache_task_list", "admin_cache_get(view='tasks')")
def _cache_task_list(mp: pytest.MonkeyPatch) -> None:
    ops = ["email_list", "file_list", "folder_get_tree"]
    with legacy_session() as lg:
        _enqueue(AID, ops)
        legacy = lg.call("cache_task_list", {"status": "queued", "limit": 2})
        legacy_all = lg.call("cache_task_list")

    with unified_session() as h:
        _enqueue(h.account_id, ops)
        data = h.ok(
            "admin_cache_get", {"view": "tasks", "status": "queued", "limit": 2}
        )
        everything = h.ok("admin_cache_get", {"view": "tasks"})
    assert len(data["tasks"]) == len(legacy) == 2
    assert {t["operation"] for t in everything["tasks"]} == {
        t["operation"] for t in legacy_all
    }
    assert len(everything["tasks"]) == len(legacy_all) == 3


def _seed_cache(account_id: str) -> None:
    manager = cache.get_cache_manager()
    for n in range(3):
        manager.set_cached(account_id, "email", {"n": n}, {"value": [n]})
    manager.set_cached(account_id, "event", {"n": 0}, {"value": [0]})


@row(5, "cache_get_stats", "admin_cache_get(view='stats')")
def _cache_stats(mp: pytest.MonkeyPatch) -> None:
    with legacy_session() as lg:
        _seed_cache(AID)
        legacy = lg.call("cache_get_stats")

    with unified_session() as h:
        _seed_cache(h.account_id)
        stats = h.ok("admin_cache_get", {"view": "stats"})["stats"]
    assert stats["entry_count"] == legacy["entry_count"] == 4
    assert stats["total_bytes"] == legacy["total_bytes"]
    assert stats["max_bytes"] == legacy["max_bytes"]
    assert {r: v["entry_count"] for r, v in stats["by_resource"].items()} == {
        r: v["entry_count"] for r, v in legacy["by_resource"].items()
    }


def _cache_resources() -> dict[str, int]:
    return {
        r: v["entry_count"]
        for r, v in cache.get_cache_manager().get_stats()["by_resource"].items()
    }


@row(6, "cache_invalidate", "admin_cache_invalidate")
def _cache_invalidate(mp: pytest.MonkeyPatch) -> None:
    with legacy_session() as lg:
        _seed_cache(AID)
        legacy = lg.call("cache_invalidate", {"pattern": "email:*"})
        legacy_left = _cache_resources()

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
    assert legacy["entries_deleted"] == data["entries_removed"] == 3
    assert left == legacy_left == {"event": 1}
    assert data["scope"] == "email"


@row(7, "cache_warming_status", "admin_cache_get(view='warming')")
def _cache_warming(mp: pytest.MonkeyPatch) -> None:
    cache_tools.set_warming_status_provider(None)
    with legacy_session() as lg:
        legacy = lg.call("cache_warming_status")

    with unified_session() as h:
        data = h.ok("admin_cache_get", {"view": "warming"})
    warming = data["warming"]
    assert warming["is_warming"] is legacy["is_warming"] is False
    for key in ("operations_total", "operations_completed", "progress_percent"):
        assert warming[key] == legacy[key]
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
    with legacy_session() as lg:
        legacy = lg.call(
            "calendar_get_event", {"event_id": "evt-planning", "account_id": AID}
        )

    with unified_session() as h:
        item = h.ok("m365_get", {"resource": "event", "id": "evt-planning"})["item"]
    assert item["id"] == legacy["id"]
    assert item["subject"] == legacy["subject"] == "Quarterly planning"
    assert item["location"] == legacy["location"]["displayName"] == "Cafe Roma"
    assert _instant(item["start"]) == _instant(legacy["start"])
    assert _instant(item["end"]) == _instant(legacy["end"])
    assert item["body"] == legacy["body"]["content"]
    assert sorted(a["address"] for a in item["attendees"]) == _addresses(legacy)
    organizer = legacy["organizer"]["emailAddress"]["address"]
    assert item["organizer"]["address"] == organizer


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
    with legacy_session() as lg:
        lg.call(
            "calendar_create_event",
            {"account_id": AID, **fields, "attendees": [attendee]},
        )
        (legacy,) = [e for e in lg.fake.events.values() if e["subject"] == "Planning"]

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
        assert _instant(created["start"]) == _instant(legacy["start"])
        assert _instant(created["end"]) == _instant(legacy["end"])
        assert created["location"]["displayName"] == legacy["location"]["displayName"]
        assert created["body"]["content"] == legacy["body"]["content"] == "Plan Q4"
        assert _addresses(created) == _addresses(legacy) == [attendee]

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
    with legacy_session() as lg:
        lg.call(
            "calendar_update_event",
            {
                "event_id": "evt-dentist",
                "updates": {
                    "subject": "Dentist (check-up)",
                    "start": "2026-09-29T11:00:00+00:00",
                    "end": "2026-09-29T12:00:00+00:00",
                    "location": "Elsewhere",
                },
                "account_id": AID,
            },
        )
        legacy = lg.fake.events["evt-dentist"]

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
        assert event["subject"] == legacy["subject"] == "Dentist (check-up)"
        assert _instant(event["start"]) == _instant(legacy["start"])
        assert _instant(event["end"]) == _instant(legacy["end"])
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
    with legacy_session() as lg:
        lg.call(
            "calendar_delete_event",
            {"account_id": AID, "event_id": "evt-planning", "confirm": True},
        )
        legacy_left = set(lg.fake.events)

    with unified_session() as h:
        data = h.ok(
            "m365_delete",
            {
                "resource": "event",
                "id": "evt-planning",
                "cancellation_message": "Moving this to next quarter.",
                "confirm": True,
            },
        )
        assert set(h.fake.events) == legacy_left
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

    with legacy_session() as lg:
        for event_id, action, _ in cases:
            lg.call(
                "calendar_respond_event",
                {"account_id": AID, "event_id": event_id, "response": action},
            )
        legacy = states(lg.fake)

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
    assert unified == legacy
    assert unified["evt-sync"] == "accepted"
    assert unified["evt-standup-00"] == "tentativelyAccepted"


def _schedule_busy(legacy: dict[str, Any]) -> list[tuple[datetime, datetime]]:
    """Busy intervals from a legacy ``getSchedule`` result."""
    (schedule,) = legacy["value"]
    return sorted(
        (_instant(i["start"]), _instant(i["end"]))
        for i in schedule["scheduleItems"]
        if i["status"] != "free"
    )


def _unified_busy(data: dict[str, Any]) -> list[tuple[datetime, datetime]]:
    return sorted(
        (datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"]))
        for b in data["busy"]
    )


@row(14, "calendar_check_availability", "calendar_find_availability")
def _calendar_check_availability(mp: pytest.MonkeyPatch) -> None:
    window = {"start": "2026-09-28T00:00:00Z", "end": "2026-09-29T00:00:00Z"}
    with legacy_session() as lg:
        legacy = lg.call("calendar_check_availability", {"account_id": AID, **window})

    with unified_session() as h:
        data = h.ok("calendar_find_availability", window)
        # Same busy time as the legacy schedule lookup for the own calendar.
        assert _unified_busy(data) == _schedule_busy(legacy)
        assert _unified_busy(data)  # the standup: not an empty comparison
        # New: own calendar only. Other people's calendars cannot be queried
        # and the tool reads calendarView, not getSchedule.
        assert h.error("calendar_find_availability", {**window, "attendees": [AID]})
        assert h.graph_calls("GET", "/me/calendarView")
        assert not h.graph_calls("POST", "/me/calendar/getSchedule")


@row(15, "calendar_forward_event", "calendar_forward")
def _calendar_forward_event(mp: pytest.MonkeyPatch) -> None:
    to = "sam.lee@example.com"
    with legacy_session() as lg:
        lg.call(
            "calendar_forward_event",
            {
                "account_id": AID,
                "event_id": "evt-sync",
                "to": to,
                "message": "FYI",
                "confirm": True,
            },
        )
        (legacy,) = _posts(lg.fake, "/me/events/evt-sync/forward")

    with unified_session() as h:
        args = {"event_id": "evt-sync", "to": [to], "comment": "FYI"}
        assert h.error(
            "calendar_forward", {**args, "confirm": False}
        ) == CONFIRM_TEXT.format(action="forward invitation")
        assert not _posts(h.fake, "/forward")
        h.ok("calendar_forward", {**args, "confirm": True})
        (forwarded,) = _posts(h.fake, "/me/events/evt-sync/forward")
    assert forwarded.body["toRecipients"] == legacy.body["toRecipients"]
    assert forwarded.body["comment"] == legacy.body["comment"] == "FYI"


@row(16, "calendar_list_calendars", "m365_list(resource='calendar')")
def _calendar_list_calendars(mp: pytest.MonkeyPatch) -> None:
    with legacy_session() as lg:
        legacy = lg.call("calendar_list_calendars", {"account_id": AID})

    with unified_session() as h:
        items = h.ok("m365_list", {"resource": "calendar"})["items"]
    assert [(c["id"], c["name"], c["is_default"], c["can_edit"]) for c in items] == [
        (c["id"], c["name"], c["isDefaultCalendar"], c["canEdit"]) for c in legacy
    ]
    assert len(items) == 3


@row(17, "calendar_create_calendar", "m365_create(resource='calendar')")
def _calendar_create_calendar(mp: pytest.MonkeyPatch) -> None:
    with legacy_session() as lg:
        lg.call("calendar_create_calendar", {"account_id": AID, "name": "Holidays"})
        legacy = sorted(c["name"] for c in lg.fake.calendars.values())

    with unified_session() as h:
        data = h.ok(
            "m365_create", {"resource": "calendar", "calendar": {"name": "Holidays"}}
        )
        created = h.fake.calendars[data["item"]["id"]]
        assert created["name"] == "Holidays"
        assert created["isDefaultCalendar"] is False
        assert sorted(c["name"] for c in h.fake.calendars.values()) == legacy


@row(18, "calendar_delete_calendar", "m365_delete(resource='calendar')")
def _calendar_delete_calendar(mp: pytest.MonkeyPatch) -> None:
    with legacy_session() as lg:
        lg.call(
            "calendar_delete_calendar",
            {"account_id": AID, "calendar_id": "cal-roster", "confirm": True},
        )
        legacy_left = set(lg.fake.calendars)

    with unified_session() as h:
        h.ok(
            "m365_delete", {"resource": "calendar", "id": "cal-roster", "confirm": True}
        )
        assert set(h.fake.calendars) == legacy_left == {"cal-default", "cal-family"}
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
    with legacy_session() as lg:
        lg.call(
            "calendar_propose_new_time",
            {
                "account_id": AID,
                "event_id": "evt-sync",
                "message": "Later?",
                **proposal,
            },
        )
        legacy = [c for c in lg.fake.calls if c.method == "POST"][-1]

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
    assert sent.path == legacy.path
    for edge in ("start", "end"):
        assert _instant(sent.body["proposedNewTime"][edge]) == _instant(
            legacy.body["proposedNewTime"][edge]
        )
    assert sent.body["comment"] == legacy.body["comment"] == "Later?"
    assert data["response_sent"] is True
    assert data["proposed_start"] is not None and data["proposed_end"] is not None


@row(20, "calendar_get_free_busy", "calendar_find_availability")
def _calendar_get_free_busy(mp: pytest.MonkeyPatch) -> None:
    window = {"start": "2026-09-28T00:00:00Z", "end": "2026-09-29T00:00:00Z"}
    with legacy_session() as lg:
        legacy = lg.call(
            "calendar_get_free_busy",
            {"account_id": AID, "attendees": [AID], **window},
        )
    busy = _schedule_busy(legacy)

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
    with legacy_session() as lg:
        legacy = lg.call("contact_list", {"account_id": AID, "limit": 50})

    with unified_session() as h:
        items = h.ok("m365_list", {"resource": "contact", "limit": 50})["items"]
        assert {c["id"] for c in items} == {c["id"] for c in legacy}
        assert len(items) == 6
        assert sorted(c["display_name"] for c in items) == sorted(
            c["displayName"] for c in legacy
        )
        by_id = {c["id"]: c for c in items}
        for contact in legacy:
            assert by_id[contact["id"]]["emails"] == [
                e["address"] for e in contact["emailAddresses"]
            ]
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
    with legacy_session() as lg:
        legacy = lg.call(
            "contact_get", {"contact_id": "contact-mark", "account_id": AID}
        )

    with unified_session() as h:
        item = h.ok("m365_get", {"resource": "contact", "id": "contact-mark"})["item"]
    assert item["id"] == legacy["id"]
    assert item["display_name"] == legacy["displayName"] == "Mark Brown"
    assert item["given_name"] == legacy["givenName"]
    assert item["surname"] == legacy["surname"]
    assert item["emails"] == [e["address"] for e in legacy["emailAddresses"]]
    assert item["business_phones"] == legacy["businessPhones"] == ["08 8111 2222"]
    assert item["company_name"] == legacy["companyName"] == "Brown Engineering"
    assert item["job_title"] == legacy["jobTitle"] == "Engineer"


@row(23, "contact_create", "m365_create(resource='contact')")
def _contact_create(mp: pytest.MonkeyPatch) -> None:
    with legacy_session() as lg:
        lg.call(
            "contact_create",
            {
                "account_id": AID,
                "given_name": "Bo",
                "surname": "Ng",
                "email_addresses": ["bo@example.com"],
                "phone_numbers": {"mobile": "0400 000 000", "business": "08 1111 2222"},
            },
        )
        (legacy,) = [c for c in lg.fake.contacts.values() if c["givenName"] == "Bo"]

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
        for key in ("givenName", "surname", "mobilePhone", "businessPhones"):
            assert created[key] == legacy[key], key
        assert _contact_addresses(created) == _contact_addresses(legacy)
        assert created["parentFolderId"] == legacy["parentFolderId"] == "contacts-root"

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
    with legacy_session() as lg:
        lg.call(
            "contact_update",
            {
                "contact_id": "contact-mark",
                "updates": {
                    "jobTitle": "Principal Engineer",
                    "businessPhones": ["08 9999 0000"],
                    "mobilePhone": "0400 123 456",
                },
                "account_id": AID,
            },
        )
        legacy = lg.fake.contacts["contact-mark"]

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
        for key in ("jobTitle", "businessPhones", "mobilePhone", "givenName"):
            assert updated[key] == legacy[key], key
        assert updated["jobTitle"] == "Principal Engineer"
        # Fields not mentioned are unchanged.
        assert updated["companyName"] == "Brown Engineering"


@row(25, "contact_delete", "m365_delete(resource='contact')")
def _contact_delete(mp: pytest.MonkeyPatch) -> None:
    with legacy_session() as lg:
        lg.call(
            "contact_delete",
            {"contact_id": "contact-sam", "account_id": AID, "confirm": True},
        )
        legacy_left = set(lg.fake.contacts)

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
        assert set(h.fake.contacts) == legacy_left
        assert "contact-sam" not in h.fake.contacts
        assert len(h.fake.contacts) == 5


@row(26, "contact_create_list", "m365_create(resource='contact_folder')")
def _contact_create_list(mp: pytest.MonkeyPatch) -> None:
    with legacy_session() as lg:
        lg.call("contact_create_list", {"account_id": AID, "list_name": "Club"})
        (legacy,) = [
            f for f in lg.fake.contact_folders.values() if f["displayName"] == "Club"
        ]

    with unified_session() as h:
        data = h.ok(
            "m365_create",
            {"resource": "contact_folder", "contact_folder": {"display_name": "Club"}},
        )
        created = h.fake.contact_folders[data["item"]["id"]]
        assert created["displayName"] == legacy["displayName"] == "Club"
        assert created["parentFolderId"] == legacy["parentFolderId"]
        # The named folder is what m365_list contact_folder now returns.
        listed = h.ok("m365_list", {"resource": "contact_folder"})["items"]
        assert "Club" in [f["display_name"] for f in listed]


@row(27, "contact_add_to_list", "m365_move(resource='contact', destination_id)")
def _contact_add_to_list(mp: pytest.MonkeyPatch) -> None:
    def janes(fake: Any) -> dict[str, dict[str, Any]]:
        return {k: v for k, v in fake.contacts.items() if v["givenName"] == "Jane"}

    with legacy_session() as lg:
        lg.call(
            "contact_add_to_list",
            {
                "account_id": AID,
                "contact_id": "contact-jane",
                "list_id": "cfolder-work",
            },
        )
        legacy = janes(lg.fake)
    # Legacy duplicated the contact: the original stayed where it was.
    assert (
        len(legacy) == 2 and legacy["contact-jane"]["parentFolderId"] == "contacts-root"
    )
    (legacy_copy,) = [v for k, v in legacy.items() if k != "contact-jane"]

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
        for key in ("displayName", "surname", "mobilePhone"):
            assert contact[key] == legacy_copy[key], key
        assert _contact_addresses(contact) == _contact_addresses(legacy_copy)
        assert len(h.fake.contacts) == 6  # nothing duplicated


@row(28, "contact_export", "m365_get_content(resource='contact', mode='vcard')")
def _contact_export(mp: pytest.MonkeyPatch) -> None:
    with legacy_session() as lg:
        legacy = lg.call(
            "contact_export", {"account_id": AID, "contact_id": "contact-mark"}
        )["vcard"]

    with unified_session() as h:
        data = h.ok(
            "m365_get_content",
            {"resource": "contact", "id": "contact-mark", "mode": "vcard"},
        )
    assert data["mime_type"] == "text/vcard"
    unified = _vcard_properties(data["vcard"])
    expected = _vcard_properties(legacy)
    assert unified == expected
    assert unified["FN"] == ["Mark Brown"]
    assert unified["EMAIL"] == ["mark.brown@example.com"]
    assert unified["TITLE"] == ["Engineer"]


# ----------------------------------------------------------------------
# mail folder rows 29-37
# ----------------------------------------------------------------------


def _flatten_legacy_tree(nodes: list[dict[str, Any]]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for node in nodes:
        pairs.append((node["id"], node["parentFolderId"]))
        pairs.extend(_flatten_legacy_tree(node.get("children") or []))
    return sorted(pairs)


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
    with legacy_session() as lg:
        legacy = lg.call("emailfolders_list", {"account_id": AID, "limit": 50})

    with unified_session() as h:
        items = h.ok("m365_list", {"resource": "email_folder", "limit": 50})["items"]
    assert [(f["id"], f["display_name"]) for f in items] == [
        (f["id"], f["displayName"]) for f in legacy
    ]
    assert [f["unread_count"] for f in items] == [f["unreadItemCount"] for f in legacy]
    assert [f["total_count"] for f in items] == [f["totalItemCount"] for f in legacy]
    assert "folder-conversation-history" not in {f["id"] for f in items}  # hidden
    assert len(items) == 9


@row(30, "emailfolders_get", "m365_get(resource='email_folder')")
def _emailfolders_get(mp: pytest.MonkeyPatch) -> None:
    with legacy_session() as lg:
        legacy = lg.call(
            "emailfolders_get", {"folder_id": "folder-family", "account_id": AID}
        )

    with unified_session() as h:
        item = h.ok("m365_get", {"resource": "email_folder", "id": "folder-family"})[
            "item"
        ]
    assert item["id"] == legacy["id"] == "folder-family"
    assert item["display_name"] == legacy["displayName"] == "Family"
    assert item["parent_id"] == legacy["parentFolderId"] == "inbox"
    assert item["child_count"] == legacy["childFolderCount"] == 1


@row(31, "emailfolders_get_tree", "m365_list(resource='email_folder', recursive=true)")
def _emailfolders_get_tree(mp: pytest.MonkeyPatch) -> None:
    with legacy_session() as lg:
        legacy = lg.call("emailfolders_get_tree", {"account_id": AID})

    with unified_session() as h:
        items = h.ok(
            "m365_list",
            {"resource": "email_folder", "recursive": True, "limit": 50},
        )["items"]
    assert _flatten_unified_tree(items) == _flatten_legacy_tree(legacy["folders"])
    # The nested folders really are nested: School under Family under Inbox.
    inbox = next(f for f in items if f["id"] == "inbox")
    (family,) = inbox["children"]
    assert [c["id"] for c in family["children"]] == ["folder-school"]


@row(32, "emailfolders_create", "m365_create(resource='email_folder')")
def _emailfolders_create(mp: pytest.MonkeyPatch) -> None:
    with legacy_session() as lg:
        lg.call("emailfolders_create", {"display_name": "Bills", "account_id": AID})
        lg.call(
            "emailfolders_create",
            {"display_name": "Kids", "parent_folder_id": "inbox", "account_id": AID},
        )
        legacy = {
            name: parent
            for name, parent in _folder_summary(lg.fake).values()
            if name in ("Bills", "Kids")
        }

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
    assert unified == legacy == {"Bills": "msgfolderroot", "Kids": "inbox"}


@row(33, "emailfolders_rename", "m365_update(resource='email_folder')")
def _emailfolders_rename(mp: pytest.MonkeyPatch) -> None:
    with legacy_session() as lg:
        lg.call(
            "emailfolders_rename",
            {
                "folder_id": "folder-receipts",
                "new_display_name": "Receipts 2026",
                "account_id": AID,
            },
        )
        legacy = _folder_summary(lg.fake)

    with unified_session() as h:
        h.ok(
            "m365_update",
            {
                "resource": "email_folder",
                "id": "folder-receipts",
                "email_folder_changes": {"display_name": "Receipts 2026"},
            },
        )
        assert _folder_summary(h.fake) == legacy
        assert h.fake.folders["folder-receipts"]["displayName"] == "Receipts 2026"


@row(34, "emailfolders_move", "m365_move(resource='email_folder')")
def _emailfolders_move(mp: pytest.MonkeyPatch) -> None:
    with legacy_session() as lg:
        lg.call(
            "emailfolders_move",
            {
                "folder_id": "folder-reading",
                "destination_folder_id": "archive",
                "account_id": AID,
            },
        )
        legacy = _folder_summary(lg.fake)

    with unified_session() as h:
        h.ok(
            "m365_move",
            {
                "resource": "email_folder",
                "id": "folder-reading",
                "destination_id": "archive",
            },
        )
        assert _folder_summary(h.fake) == legacy
        assert h.fake.folders["folder-reading"]["parentFolderId"] == "archive"


@row(35, "emailfolders_delete", "m365_delete(resource='email_folder')")
def _emailfolders_delete(mp: pytest.MonkeyPatch) -> None:
    with legacy_session() as lg:
        lg.call(
            "emailfolders_delete",
            {"folder_id": "folder-old-projects", "account_id": AID, "confirm": True},
        )
        legacy_left = set(lg.fake.folders)

    with unified_session() as h:
        h.ok(
            "m365_delete",
            {"resource": "email_folder", "id": "folder-old-projects", "confirm": True},
        )
        assert set(h.fake.folders) == legacy_left
        assert "folder-old-projects" not in h.fake.folders
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
    with legacy_session() as lg:
        lg.call(
            "emailfolders_mark_all_as_read",
            {"folder_id": "inbox", "account_id": AID},
        )
        legacy = _message_state(lg.fake, "inbox")
        legacy_other = _message_state(lg.fake, "junkemail")

    with unified_session() as h:
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
        # Same end state as the legacy tool; other folders untouched.
        assert _message_state(h.fake, "inbox") == legacy
        assert all(legacy.values())
        assert _message_state(h.fake, "junkemail") == legacy_other


@row(37, "emailfolders_empty", "email_folder_empty")
def _emailfolders_empty(mp: pytest.MonkeyPatch) -> None:
    with legacy_session() as lg:
        lg.call(
            "emailfolders_empty",
            {"folder_id": "junkemail", "account_id": AID, "confirm": True},
        )
        legacy_left = set(lg.fake.messages)

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
        assert set(h.fake.messages) == legacy_left
        assert not {"msg-008", "msg-009"} & set(h.fake.messages)
        assert "msg-013" in h.fake.messages  # other folders untouched


# ----------------------------------------------------------------------
# email rule rows 38-42
# ----------------------------------------------------------------------


@row(38, "emailrules_list", "m365_list(resource='email_rule')")
def _emailrules_list(mp: pytest.MonkeyPatch) -> None:
    with legacy_session() as lg:
        legacy = lg.call("emailrules_list", {"account_id": AID})

    with unified_session() as h:
        items = h.ok("m365_list", {"resource": "email_rule"})["items"]
    assert [
        (r["id"], r["display_name"], r["sequence"], r["is_enabled"]) for r in items
    ] == [(r["id"], r["displayName"], r["sequence"], r["isEnabled"]) for r in legacy]
    assert [r["id"] for r in items] == ["rule-news", "rule-boss"]


@row(39, "emailrules_get", "m365_get(resource='email_rule')")
def _emailrules_get(mp: pytest.MonkeyPatch) -> None:
    with legacy_session() as lg:
        legacy = lg.call("emailrules_get", {"rule_id": "rule-news", "account_id": AID})

    with unified_session() as h:
        item = h.ok("m365_get", {"resource": "email_rule", "id": "rule-news"})["item"]
    assert item["id"] == legacy["id"]
    assert item["display_name"] == legacy["displayName"]
    assert item["sequence"] == legacy["sequence"] == 1
    assert (
        item["conditions"]["sender_contains"] == legacy["conditions"]["senderContains"]
    )
    assert item["actions"]["move_to_folder"] == legacy["actions"]["moveToFolder"]
    assert (
        item["actions"]["stop_processing_rules"]
        == legacy["actions"]["stopProcessingRules"]
        is True
    )


@row(40, "emailrules_create", "email_rule_manage(action='create')")
def _emailrules_create(mp: pytest.MonkeyPatch) -> None:
    with legacy_session() as lg:
        lg.call(
            "emailrules_create",
            {
                "account_id": AID,
                "display_name": "Bills",
                "conditions": {"senderContains": ["billing"]},
                "actions": {"moveToFolder": "folder-receipts"},
            },
        )
        (legacy,) = [r for r in lg.fake.rules.values() if r["displayName"] == "Bills"]

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
        assert created["conditions"] == legacy["conditions"]
        assert created["actions"] == legacy["actions"]
        assert created["isEnabled"] is legacy["isEnabled"] is True

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
    with legacy_session() as lg:
        lg.call(
            "emailrules_update",
            {
                "rule_id": "rule-news",
                "account_id": AID,
                "display_name": "News",
                "is_enabled": False,
                "actions": {"moveToFolder": "archive"},
            },
        )
        legacy = lg.fake.rules["rule-news"]

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
        for key in ("displayName", "isEnabled", "actions", "conditions", "sequence"):
            assert updated[key] == legacy[key], key
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
    with legacy_session() as lg:
        lg.call(
            "emailrules_delete",
            {"rule_id": "rule-boss", "account_id": AID, "confirm": True},
        )
        legacy_left = set(lg.fake.rules)

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
        assert set(h.fake.rules) == legacy_left == {"rule-news"}
