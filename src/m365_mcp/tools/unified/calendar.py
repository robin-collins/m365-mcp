"""Calendar handlers for the unified tools.

Covers the ``event`` and ``calendar`` resources of the generic tools
(``m365_list``, ``m365_get``, ``m365_create``, ``m365_delete``) and the
dedicated tools ``calendar_create_event``, ``calendar_update_event``,
``calendar_respond`` and ``calendar_forward``. Availability lives in
``calendar_availability.py``.

Times are shown in the mailbox time zone unless the call names one.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from fastmcp.exceptions import ToolError

from ...errors import GraphAPIError
from ...projections import (
    project_calendar,
    project_event_detail,
    project_event_summary,
)
from ...services import calendar as cal
from ...untrusted import sanitize_text
from ...validators import ValidationError, validate_timezone
from ..handlers import register_handler, register_validation_rule
from .common import (
    account,
    arg,
    check_rate,
    decode_cursor,
    encode_cursor,
    invalid,
    require_confirm,
    resource_op,
)

DEFAULT_CALENDAR = "default"
LIST_WINDOW = timedelta(days=7)
MAX_LIST_SPAN = timedelta(days=366)
EN_DASH = "–"

CREATE_UNKNOWN = "Outcome unknown: check your calendar before retrying"
DELETE_UNKNOWN = "Outcome unknown: check whether the item still exists before retrying"
NOT_ORGANISER = (
    "You are not the organiser of this meeting. "
    "Expected: use calendar_respond to propose a new time"
)
OWN_MEETING = "You organise this meeting; there is nothing to respond to"

# Plain event fields shared by calendar_create_event and the update changes.
_PLAIN_FIELDS = (
    "subject",
    "is_all_day",
    "location",
    "body",
    "reminder_minutes",
    "show_as",
)
# Changes only the organiser may make (time, attendees, location).
_ORGANISER_ONLY = frozenset(
    {
        "start",
        "end",
        "time_zone",
        "is_all_day",
        "location",
        "attendees_set",
        "attendees_add",
        "attendees_remove",
    }
)
_TIME_CHANGES = frozenset({"start", "end", "time_zone"})
_RESPONSE_VERBS = {
    "accept": "Accepted",
    "tentative": "Tentatively accepted",
    "decline": "Declined",
}


# ----------------------------------------------------------------------
# helpers (also used by calendar_availability)
# ----------------------------------------------------------------------


def now() -> datetime:
    """Return the current UTC time (patched in tests)."""
    return datetime.now(UTC)


def parse_dt(value: str) -> datetime:
    """Parse a schema-validated RFC 3339 date-time with offset."""
    return datetime.fromisoformat(value.upper())


def output_zone(account_id: str, requested: str | None) -> str:
    """Return the IANA zone to use: ``requested`` or the mailbox zone.

    Args:
        account_id: Resolved account ID.
        requested: The call's ``time_zone`` argument, if any.

    Returns:
        An IANA time-zone name (``UTC`` when the mailbox zone is unknown).

    Raises:
        ValidationError: If ``requested`` is not a known IANA zone.
    """
    if requested:
        return validate_timezone(requested, "time_zone")
    mailbox = cal.get_mailbox_time_zone(account_id)
    return cal.to_iana_time_zone(mailbox) or "UTC"


def check_time_zone(value: str | None) -> None:
    """Reject an unknown IANA ``time_zone`` before any Graph call."""
    if value:
        validate_timezone(value, "time_zone")


def short_moment(value: datetime) -> str:
    """Format as ``2 Oct 09:00``."""
    return f"{value.day} {value:%b %H:%M}"


def span(start: datetime, end: datetime) -> str:
    """Format a time range as ``2 Oct 09:00–10:00``."""
    if start.date() == end.date():
        return f"{short_moment(start)}{EN_DASH}{end:%H:%M}"
    return f"{short_moment(start)}{EN_DASH}{short_moment(end)}"


def plural(count: int, noun: str) -> str:
    """Return ``1 noun`` or ``N nouns``."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _is_ambiguous(exc: Exception) -> bool:
    """Return whether a failed write may still have taken effect."""
    if isinstance(exc, GraphAPIError):
        return exc.status >= 500 and exc.status != 503
    if isinstance(exc, httpx.TransportError):
        return not isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout))
    return False


@contextmanager
def outcome_unknown(message: str) -> Iterator[None]:
    """Turn an ambiguous write failure (timeout, 5xx) into ``message``."""
    try:
        yield
    except (GraphAPIError, httpx.TransportError) as exc:
        if _is_ambiguous(exc):
            raise ToolError(message) from exc
        raise


def _calendar_ref(value: str | None) -> str | None:
    """Map a calendar ID or the ``default`` alias to a Graph reference."""
    if value is None or value.lower() == DEFAULT_CALENDAR:
        return None
    return value


def _blank_to_none(record: dict[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        if record.get(key) == "":
            record[key] = None
    return record


def event_detail(
    event: dict[str, Any],
    *,
    zone: str,
    calendar_id: str | None = None,
    include_body: bool = True,
    body_max_chars: int = 20000,
) -> dict[str, Any]:
    """Project a Graph event to ``event_detail`` (empty text is ``None``)."""
    record = project_event_detail(
        event,
        calendar_id=calendar_id,
        include_body=include_body,
        body_max_chars=body_max_chars,
        tz=zone,
    )
    return _blank_to_none(record, "body", "preview")


def _event_span(record: dict[str, Any]) -> str:
    return span(parse_dt(record["start"]), parse_dt(record["end"]))


def _title(event: dict[str, Any]) -> str:
    return sanitize_text(event.get("subject")) or "(no subject)"


def _address(attendee: dict[str, Any]) -> str:
    return ((attendee.get("emailAddress") or {}).get("address") or "").casefold()


# ----------------------------------------------------------------------
# m365_list: event, calendar
# ----------------------------------------------------------------------


def _list_window(args: dict[str, Any]) -> tuple[datetime, datetime]:
    start = parse_dt(args["start"]) if args.get("start") else now()
    end = parse_dt(args["end"]) if args.get("end") else start + LIST_WINDOW
    if end <= start or end - start > MAX_LIST_SPAN:
        raise invalid(
            "end",
            "must be after start and within 366 days",
            "a later RFC 3339 date-time",
        )
    return start, end


@resource_op("m365_list", "event")
def list_events(args: dict[str, Any]) -> dict[str, Any]:
    """List event instances in a window via ``calendarView``."""
    start, end = _list_window(args)
    account_id = account(args)
    decoded = decode_cursor(args, account_id, "event")
    check_rate(account_id, "normal")
    zone = output_zone(account_id, None)
    calendar_ref = _calendar_ref(args.get("container_id"))
    page = cal.calendar_view_page(
        account_id,
        calendar_id=calendar_ref,
        start=start,
        end=end,
        top=arg(args, "m365_list", "limit"),
        time_zone=zone,
        next_link=decoded.next_link if decoded else None,
    )
    items = [
        _blank_to_none(
            project_event_summary(e, calendar_id=calendar_ref, tz=zone), "preview"
        )
        for e in page.get("value") or []
    ]
    next_link = page.get("@odata.nextLink")
    cursor = (
        encode_cursor(args, account_id, "event", next_link=next_link)
        if next_link
        else None
    )
    local = ZoneInfo(zone)
    summary = (
        f"Returned {plural(len(items), 'event')} from "
        f"{short_moment(start.astimezone(local))} to "
        f"{short_moment(end.astimezone(local))}"
    )
    summary += "; pass next_cursor for more." if cursor else "."
    return {
        "resource": "event",
        "items": items,
        "next_cursor": cursor,
        "has_more": cursor is not None,
        "summary": summary,
    }


@resource_op("m365_list", "calendar")
def list_calendars(args: dict[str, Any]) -> dict[str, Any]:
    """List the user's calendars (offset cursor over the full list)."""
    account_id = account(args)
    decoded = decode_cursor(args, account_id, "calendar")
    offset = (decoded.offset or 0) if decoded else 0
    limit = arg(args, "m365_list", "limit")
    check_rate(account_id, "normal")
    calendars = cal.list_all_calendars(account_id)
    items = [project_calendar(c) for c in calendars[offset : offset + limit]]
    more = offset + limit < len(calendars)
    cursor = (
        encode_cursor(args, account_id, "calendar", offset=offset + limit)
        if more
        else None
    )
    summary = f"Returned {plural(len(items), 'calendar')}"
    summary += "; pass next_cursor for more." if more else "."
    return {
        "resource": "calendar",
        "items": items,
        "next_cursor": cursor,
        "has_more": more,
        "summary": summary,
    }


# ----------------------------------------------------------------------
# m365_get: event, calendar
# ----------------------------------------------------------------------


@resource_op("m365_get", "event")
def get_event(args: dict[str, Any]) -> dict[str, Any]:
    """Read one event with body, attendees and recurrence summary."""
    account_id = account(args)
    check_rate(account_id, "normal")
    zone = output_zone(account_id, None)
    event = cal.fetch_event(account_id, args["id"], time_zone=zone)
    item = event_detail(
        event,
        zone=zone,
        include_body=arg(args, "m365_get", "include_body"),
        body_max_chars=arg(args, "m365_get", "body_max_chars"),
    )
    summary = f"Event '{_title(event)}' on {_event_span(item)}"
    if item["attendee_count"]:
        summary += f" with {plural(item['attendee_count'], 'attendee')}"
    summary += "; the body was truncated." if item["body_truncated"] else "."
    return {"resource": "event", "item": item, "summary": summary}


@resource_op("m365_get", "calendar")
def get_calendar(args: dict[str, Any]) -> dict[str, Any]:
    """Read one calendar (``default`` is the default calendar)."""
    account_id = account(args)
    check_rate(account_id, "normal")
    item = project_calendar(cal.get_calendar(account_id, _calendar_ref(args["id"])))
    default = " (default)" if item["is_default"] else ""
    return {
        "resource": "calendar",
        "item": item,
        "summary": f"Calendar '{item['name']}'{default}.",
    }


# ----------------------------------------------------------------------
# m365_create: calendar
# ----------------------------------------------------------------------


@resource_op("m365_create", "calendar")
def create_calendar(args: dict[str, Any]) -> dict[str, Any]:
    """Create a calendar with ``POST /me/calendars``."""
    account_id = account(args)
    check_rate(account_id, "normal")
    item = project_calendar(
        cal.create_calendar(account_id, name=args["calendar"]["name"])
    )
    return {
        "resource": "calendar",
        "item": item,
        "summary": f"Created calendar '{item['name']}'.",
    }


# ----------------------------------------------------------------------
# m365_delete: event, calendar
# ----------------------------------------------------------------------


@resource_op("m365_delete", "event")
def delete_event(args: dict[str, Any]) -> dict[str, Any]:
    """Delete an event; the organiser of a meeting cancels it instead."""
    account_id = account(args)
    check_rate(account_id, "sensitive")
    event_id = args["id"]
    event = cal.fetch_event(account_id, event_id)
    attendees = event.get("attendees") or []
    title = _title(event)
    if event.get("isOrganizer") and attendees:
        with outcome_unknown(DELETE_UNKNOWN):
            cal.cancel_event(
                account_id, event_id, comment=args.get("cancellation_message")
            )
        status = "cancelled_and_deleted"
        summary = (
            f"Cancelled '{title}'; {plural(len(attendees), 'attendee')} "
            "received a cancellation."
        )
    else:
        with outcome_unknown(DELETE_UNKNOWN):
            cal.remove_event(account_id, event_id)
        status = "deleted"
        summary = f"Deleted '{title}' from your calendar."
    return {
        "resource": "event",
        "id": event_id,
        "status": status,
        "recoverable": False,
        "summary": summary,
    }


@resource_op("m365_delete", "calendar")
def delete_calendar(args: dict[str, Any]) -> dict[str, Any]:
    """Delete a calendar; the default calendar is refused."""
    calendar_id = args["id"]
    if calendar_id.lower() == DEFAULT_CALENDAR:
        raise invalid("id", "the default calendar cannot be deleted")
    account_id = account(args)
    check_rate(account_id, "sensitive")
    calendar = cal.get_calendar(account_id, calendar_id)
    if calendar.get("isDefaultCalendar"):
        raise invalid("id", "the default calendar cannot be deleted")
    with outcome_unknown(DELETE_UNKNOWN):
        cal.remove_calendar(account_id, calendar_id)
    name = calendar.get("name") or calendar_id
    return {
        "resource": "calendar",
        "id": calendar_id,
        "status": "deleted",
        "recoverable": False,
        "summary": f"Deleted calendar '{name}' and its events.",
    }


# ----------------------------------------------------------------------
# calendar_create_event
# ----------------------------------------------------------------------


@register_validation_rule("calendar_create_event")
def _create_event_rules(args: dict[str, Any]) -> None:
    if parse_dt(args["end"]) <= parse_dt(args["start"]):
        raise invalid("end", "must be after start")
    check_time_zone(args.get("time_zone"))
    if args.get("attendees"):
        require_confirm(args, "inviting attendees")


def _plain_fields(source: dict[str, Any]) -> dict[str, Any]:
    fields = {k: source[k] for k in _PLAIN_FIELDS if k in source}
    if "body" in source:
        fields["body_format"] = source.get("body_format") or "text"
    return fields


@register_handler("calendar_create_event")
def create_event(args: dict[str, Any]) -> dict[str, Any]:
    """Create an event; invitations go out when attendees are given."""
    account_id = account(args)
    attendees = args.get("attendees") or []
    check_rate(account_id, "sensitive" if attendees else "normal")
    zone = output_zone(account_id, args.get("time_zone"))
    fields = _plain_fields(args)
    fields["start"] = parse_dt(args["start"])
    fields["end"] = parse_dt(args["end"])
    calendar_ref = _calendar_ref(args.get("calendar_id"))
    body = cal.event_body(
        fields,
        time_zone=zone,
        attendees=cal.attendees_body(attendees) if attendees else None,
    )
    with outcome_unknown(CREATE_UNKNOWN):
        created = cal.post_event(
            account_id, body, calendar_id=calendar_ref, time_zone=zone
        )
    event = event_detail(created, zone=zone, calendar_id=calendar_ref)
    summary = f"Created '{_title(created)}' on {_event_span(event)}"
    if attendees:
        summary += f" and invited {plural(len(attendees), 'attendee')}."
    else:
        summary += " (no invitations sent)."
    return {
        "event": event,
        "invitations_sent": bool(attendees),
        "summary": summary,
    }


# ----------------------------------------------------------------------
# calendar_update_event
# ----------------------------------------------------------------------


@register_validation_rule("calendar_update_event")
def _update_event_rules(args: dict[str, Any]) -> None:
    changes = args["changes"]
    if "attendees_set" in changes and (
        "attendees_add" in changes or "attendees_remove" in changes
    ):
        raise invalid(
            "attendees_set", "cannot be combined with attendees_add or attendees_remove"
        )
    if (
        "start" in changes
        and "end" in changes
        and parse_dt(changes["end"]) <= parse_dt(changes["start"])
    ):
        raise invalid("end", "must be after start")
    check_time_zone(changes.get("time_zone"))


def _new_attendees(
    changes: dict[str, Any], existing: list[dict[str, Any]]
) -> list[dict[str, Any]] | None:
    """Return the attendee list to PATCH, or ``None`` when unchanged."""
    if "attendees_set" in changes:
        return cal.attendees_body(changes["attendees_set"])
    if "attendees_add" not in changes and "attendees_remove" not in changes:
        return None
    removed = {a.casefold() for a in changes.get("attendees_remove") or []}
    result = [
        {
            "emailAddress": a.get("emailAddress") or {},
            "type": a.get("type") or "required",
        }
        for a in existing
        if _address(a) not in removed
    ]
    present = {_address(a) for a in result}
    for attendee in cal.attendees_body(changes.get("attendees_add") or []):
        if _address(attendee) not in present:
            result.append(attendee)
            present.add(_address(attendee))
    return result


@register_handler("calendar_update_event")
def update_event(args: dict[str, Any]) -> dict[str, Any]:
    """Update an event after checking organiser rights and attendees."""
    account_id = account(args)
    event_id, changes = args["event_id"], args["changes"]
    zone = output_zone(account_id, changes.get("time_zone"))
    current = cal.fetch_event(account_id, event_id, time_zone=zone)
    now_record = project_event_summary(current, tz=zone)
    start = parse_dt(changes["start"]) if "start" in changes else None
    end = parse_dt(changes["end"]) if "end" in changes else None
    new_start = start or parse_dt(now_record["start"])
    new_end = end or parse_dt(now_record["end"])
    if new_end <= new_start:
        raise invalid("end", "must be after start")
    is_organizer = bool(current.get("isOrganizer"))
    if not is_organizer and _ORGANISER_ONLY.intersection(changes):
        raise ValidationError(NOT_ORGANISER)
    existing = current.get("attendees") or []
    attendees = _new_attendees(changes, existing)
    affected = bool(existing) or bool(attendees)
    if affected:
        require_confirm(args, "updating a meeting with attendees")
    notified = affected and is_organizer
    check_rate(account_id, "sensitive" if notified else "normal")

    fields = _plain_fields(changes)
    if _TIME_CHANGES.intersection(changes):
        fields["start"], fields["end"] = new_start, new_end
    body = cal.event_body(fields, time_zone=zone, attendees=attendees)
    updated = current
    if body:
        updated = cal.patch_event(account_id, event_id, body, time_zone=zone) or current
    event = event_detail(updated, zone=zone)
    changed = [k for k in changes if k != "body_format"] or list(changes)
    title = _title(updated)
    if set(changed) <= _TIME_CHANGES and {"start", "end"} & set(changed):
        summary = f"Moved '{title}' to {_event_span(event)}."
    else:
        summary = f"Updated '{title}' ({', '.join(changed)})."
    if notified:
        summary = summary[:-1] + "; attendees were notified."
    return {
        "event": event,
        "attendees_notified": notified,
        "changed_fields": changed,
        "summary": summary,
    }


# ----------------------------------------------------------------------
# calendar_respond
# ----------------------------------------------------------------------


@register_validation_rule("calendar_respond")
def _respond_rules(args: dict[str, Any]) -> None:
    proposed_start = args.get("proposed_start")
    proposed_end = args.get("proposed_end")
    if proposed_start is not None or proposed_end is not None:
        if proposed_end is None:
            raise invalid("proposed_end", "required with proposed_start")
        if proposed_start is None:
            raise invalid("proposed_start", "required with proposed_end")
        if args["action"] == "accept":
            raise invalid(
                "proposed_start", "only valid with action 'tentative' or 'decline'"
            )
        if parse_dt(proposed_end) <= parse_dt(proposed_start):
            raise invalid("proposed_end", "must be after proposed_start")
    if arg(args, "calendar_respond", "send_response"):
        require_confirm(args, "sending a response")


@register_handler("calendar_respond")
def respond(args: dict[str, Any]) -> dict[str, Any]:
    """Accept, tentatively accept or decline an invitation."""
    account_id = account(args)
    send_response = bool(arg(args, "calendar_respond", "send_response"))
    check_rate(account_id, "sensitive" if send_response else "normal")
    event_id, action = args["event_id"], args["action"]
    event = cal.fetch_event(account_id, event_id)
    if event.get("isOrganizer"):
        raise ValidationError(OWN_MEETING)
    proposed_start = args.get("proposed_start")
    proposed_end = args.get("proposed_end")
    cal.send_event_response(
        account_id,
        event_id,
        action=action,
        send_response=send_response,
        comment=args.get("comment"),
        proposed_start=parse_dt(proposed_start) if proposed_start else None,
        proposed_end=parse_dt(proposed_end) if proposed_end else None,
    )
    summary = f"{_RESPONSE_VERBS[action]} '{_title(event)}'"
    if proposed_start and proposed_end:
        summary += (
            f" and proposed {span(parse_dt(proposed_start), parse_dt(proposed_end))}"
        )
    summary += "." if send_response else " without notifying the organiser."
    return {
        "event_id": event_id,
        "action": action,
        "response_sent": send_response,
        "proposed_start": proposed_start,
        "proposed_end": proposed_end,
        "summary": summary,
    }


# ----------------------------------------------------------------------
# calendar_forward
# ----------------------------------------------------------------------


@register_validation_rule("calendar_forward")
def _forward_rules(args: dict[str, Any]) -> None:
    require_confirm(args, "forward invitation")


@register_handler("calendar_forward")
def forward(args: dict[str, Any]) -> dict[str, Any]:
    """Forward a meeting invitation with ``POST /me/events/{id}/forward``."""
    account_id = account(args)
    check_rate(account_id, "sensitive")
    event_id, recipients = args["event_id"], args["to"]
    event = cal.fetch_event(account_id, event_id)
    cal.forward_event(account_id, event_id, to=recipients, message=args.get("comment"))
    return {
        "event_id": event_id,
        "status": "forwarded",
        "recipient_count": len(recipients),
        "summary": (
            f"Forwarded '{_title(event)}' to {plural(len(recipients), 'recipient')}."
        ),
    }
