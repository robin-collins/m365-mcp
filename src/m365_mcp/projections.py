"""Graph JSON to result projections (concept §5.2).

Pure functions that turn Microsoft Graph objects into the closed records
defined by the ``$defs`` of ``docs/unified-tools/tools/*.json``. Every
field is present (``None`` when Graph omits it), ``@odata.*`` and other
Graph bookkeeping never leak, date-times are ISO 8601 with an offset, and
third-party text passes through :mod:`untrusted`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import unquote
from zoneinfo import ZoneInfo

from .untrusted import (
    DEFAULT_BODY_MAX_CHARS,
    sanitize_body,
    sanitize_preview,
    sanitize_text,
)

Record = dict[str, Any]

# Graph messageRulePredicates (30) and messageRuleActions (11) in the
# snake_case used by the tool schemas; Graph names are their camelCase.
RULE_PREDICATES: tuple[str, ...] = (
    "subject_contains",
    "body_contains",
    "body_or_subject_contains",
    "sender_contains",
    "recipient_contains",
    "header_contains",
    "categories",
    "from_addresses",
    "sent_to_addresses",
    "has_attachments",
    "importance",
    "sensitivity",
    "message_action_flag",
    "within_size_range",
    "is_approval_request",
    "is_automatic_forward",
    "is_automatic_reply",
    "is_encrypted",
    "is_meeting_request",
    "is_meeting_response",
    "is_non_delivery_report",
    "is_permission_controlled",
    "is_read_receipt",
    "is_signed",
    "is_voicemail",
    "not_sent_to_me",
    "sent_cc_me",
    "sent_only_to_me",
    "sent_to_me",
    "sent_to_or_cc_me",
)
RULE_ACTIONS: tuple[str, ...] = (
    "move_to_folder",
    "copy_to_folder",
    "assign_categories",
    "mark_as_read",
    "mark_importance",
    "stop_processing_rules",
    "forward_to",
    "forward_as_attachment_to",
    "redirect_to",
    "delete",
    "permanent_delete",
)
# Rule fields whose Graph value is a list of recipient objects.
_RULE_ADDRESS_FIELDS = frozenset(
    {
        "from_addresses",
        "sent_to_addresses",
        "forward_to",
        "forward_as_attachment_to",
        "redirect_to",
    }
)
_SIZE_RANGE = (("minimum_kb", "minimumSize"), ("maximum_kb", "maximumSize"))

_FLAG_STATUS = {
    "notFlagged": "not_flagged",
    "flagged": "flagged",
    "complete": "complete",
}
_OPERATION_STATUS = {"completed": "completed", "failed": "failed"}
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.capitalize() for part in rest)


_PREDICATE_TO_GRAPH = {name: _camel(name) for name in RULE_PREDICATES}
_ACTION_TO_GRAPH = {name: _camel(name) for name in RULE_ACTIONS}
_PREDICATE_FROM_GRAPH = {v: k for k, v in _PREDICATE_TO_GRAPH.items()}
_ACTION_FROM_GRAPH = {v: k for k, v in _ACTION_TO_GRAPH.items()}


# --------------------------------------------------------------------------
# shared helpers
# --------------------------------------------------------------------------


def iso_datetime(value: str | None, tz: str | None = None) -> str | None:
    """Normalise a Graph UTC timestamp to ISO 8601 with an offset.

    Args:
        value: Graph timestamp such as ``2026-09-19T22:45:00Z``.
        tz: Optional IANA time zone to express the result in.

    Returns:
        The timestamp with an explicit offset, or ``None``.
    """
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
    if tz:
        parsed = parsed.astimezone(ZoneInfo(tz))
    return parsed.isoformat()


def _event_time(value: dict[str, Any], tz: str | None) -> str:
    """Convert a Graph dateTimeTimeZone to ISO 8601 with an offset."""
    parsed = datetime.fromisoformat(value["dateTime"]).replace(
        tzinfo=ZoneInfo(value.get("timeZone") or "UTC")
    )
    if tz:
        parsed = parsed.astimezone(ZoneInfo(tz))
    return parsed.isoformat()


def _recipient(value: dict[str, Any] | None) -> Record | None:
    """Project a Graph recipient to ``{name, address}``."""
    if not value:
        return None
    email = value.get("emailAddress") or {}
    return {
        "name": sanitize_text(email.get("name")),
        "address": email.get("address") or "",
    }


def _recipients(values: list[dict[str, Any]] | None) -> list[Record]:
    return [r for r in (_recipient(v) for v in values or []) if r]


# --------------------------------------------------------------------------
# email
# --------------------------------------------------------------------------


def project_email_summary(message: dict[str, Any], *, tz: str | None = None) -> Record:
    """Project a Graph message to the ``email_summary`` record.

    Args:
        message: Graph ``message`` object.
        tz: Optional IANA time zone for ``received_at``.

    Returns:
        The summary record used by list and search results.
    """
    flag = message.get("flag") or {}
    return {
        "id": message["id"],
        "conversation_id": message.get("conversationId"),
        "subject": sanitize_text(message.get("subject")),
        "from": _recipient(message.get("from")),
        "to": _recipients(message.get("toRecipients")),
        "cc": _recipients(message.get("ccRecipients")),
        "received_at": iso_datetime(message.get("receivedDateTime"), tz),
        "is_read": bool(message.get("isRead")),
        "has_attachments": bool(message.get("hasAttachments")),
        "importance": message.get("importance") or "normal",
        "flag_status": _FLAG_STATUS.get(flag.get("flagStatus") or "", "not_flagged"),
        "categories": list(message.get("categories") or []),
        "preview": sanitize_preview(message.get("bodyPreview")),
        "folder_id": message.get("parentFolderId"),
    }


def project_email_detail(
    message: dict[str, Any],
    *,
    include_body: bool = True,
    body_max_chars: int = DEFAULT_BODY_MAX_CHARS,
    tz: str | None = None,
) -> Record:
    """Project a Graph message to the ``email_detail`` record.

    Attachment metadata is read from ``message["attachments"]`` (for
    example from ``$expand=attachments``); it is empty when absent.

    Args:
        message: Graph ``message`` object.
        include_body: Whether to return the body.
        body_max_chars: Body character cap; sets ``body_truncated``.
        tz: Optional IANA time zone for ``received_at``.

    Returns:
        The detail record returned by ``m365_get``.
    """
    body, truncated = None, False
    if include_body:
        graph_body = message.get("body") or {}
        body, truncated = sanitize_body(
            graph_body.get("content"),
            graph_body.get("contentType"),
            body_max_chars,
        )
    return {
        **project_email_summary(message, tz=tz),
        "bcc": _recipients(message.get("bccRecipients")),
        "body": body,
        "body_truncated": truncated,
        "attachments": [
            {
                "id": a["id"],
                "name": sanitize_text(a.get("name")) or "",
                "size": a.get("size") or 0,
                "content_type": a.get("contentType"),
                "is_inline": bool(a.get("isInline")),
            }
            for a in message.get("attachments") or []
        ],
        "web_link": message.get("webLink"),
    }


# --------------------------------------------------------------------------
# email_folder
# --------------------------------------------------------------------------


def project_email_folder(folder: dict[str, Any], *, tree: bool = False) -> Record:
    """Project a Graph mailFolder to the ``email_folder`` record.

    Args:
        folder: Graph ``mailFolder``; in tree mode its ``childFolders``
            (expanded recursively) become ``children``.
        tree: Whether to populate ``children``.

    Returns:
        The folder record; ``children`` is ``None`` outside tree mode.
    """
    return {
        "id": folder["id"],
        "display_name": folder.get("displayName") or "",
        "parent_id": folder.get("parentFolderId"),
        "unread_count": folder.get("unreadItemCount") or 0,
        "total_count": folder.get("totalItemCount") or 0,
        "child_count": folder.get("childFolderCount") or 0,
        "children": (
            [
                project_email_folder(child, tree=True)
                for child in folder.get("childFolders") or []
            ]
            if tree
            else None
        ),
    }


# --------------------------------------------------------------------------
# email_rule
# --------------------------------------------------------------------------


def _rule_value_from_graph(name: str, value: Any) -> Any:
    if name in _RULE_ADDRESS_FIELDS:
        return [(r.get("emailAddress") or {}).get("address") or "" for r in value]
    if name == "within_size_range":
        return {
            ours: value[theirs]
            for ours, theirs in _SIZE_RANGE
            if value.get(theirs) is not None
        }
    return value


def _rule_value_to_graph(name: str, value: Any) -> Any:
    if name in _RULE_ADDRESS_FIELDS:
        return [{"emailAddress": {"address": address}} for address in value]
    if name == "within_size_range":
        return {theirs: value[ours] for ours, theirs in _SIZE_RANGE if ours in value}
    return value


def _from_graph(values: dict[str, Any] | None, names: dict[str, str]) -> Record:
    result: Record = {}
    for graph_name, value in (values or {}).items():
        name = names.get(graph_name)
        if name is None or value is None:
            continue
        converted = _rule_value_from_graph(name, value)
        if converted != {}:
            result[name] = converted
    return result


def _to_graph(values: dict[str, Any], names: dict[str, str]) -> Record:
    return {
        names[name]: _rule_value_to_graph(name, value) for name, value in values.items()
    }


def predicates_from_graph(predicates: dict[str, Any] | None) -> Record:
    """Convert Graph ``messageRulePredicates`` to snake_case conditions.

    Unset (``null``) and unknown predicates are dropped. Recipient lists
    become address strings and ``withinSizeRange`` becomes
    ``{minimum_kb, maximum_kb}``.

    Args:
        predicates: Graph ``conditions`` or ``exceptions`` object.

    Returns:
        Conditions keyed by the names in ``RULE_PREDICATES``.
    """
    return _from_graph(predicates, _PREDICATE_FROM_GRAPH)


def predicates_to_graph(conditions: dict[str, Any]) -> Record:
    """Convert snake_case conditions to Graph ``messageRulePredicates``.

    Args:
        conditions: Schema-validated conditions or exceptions.

    Returns:
        The Graph predicates object.
    """
    return _to_graph(conditions, _PREDICATE_TO_GRAPH)


def actions_from_graph(actions: dict[str, Any] | None) -> Record:
    """Convert Graph ``messageRuleActions`` to snake_case actions.

    Args:
        actions: Graph ``actions`` object.

    Returns:
        Actions keyed by the names in ``RULE_ACTIONS``.
    """
    return _from_graph(actions, _ACTION_FROM_GRAPH)


def actions_to_graph(actions: dict[str, Any]) -> Record:
    """Convert snake_case actions to Graph ``messageRuleActions``.

    Args:
        actions: Schema-validated rule actions.

    Returns:
        The Graph actions object.
    """
    return _to_graph(actions, _ACTION_TO_GRAPH)


def rule_to_graph(rule: dict[str, Any]) -> Record:
    """Convert an ``email_rule_manage`` rule object to a Graph body.

    Only the supplied fields are included, so the result serves both
    create and partial update.

    Args:
        rule: Schema-validated ``rule`` argument.

    Returns:
        A Graph ``messageRule`` request body.
    """
    converters = {
        "display_name": ("displayName", lambda v: v),
        "sequence": ("sequence", lambda v: v),
        "is_enabled": ("isEnabled", lambda v: v),
        "conditions": ("conditions", predicates_to_graph),
        "actions": ("actions", actions_to_graph),
        "exceptions": ("exceptions", predicates_to_graph),
    }
    body: Record = {}
    for name, value in rule.items():
        graph_name, convert = converters[name]
        body[graph_name] = convert(value)
    return body


def project_email_rule(rule: dict[str, Any]) -> Record:
    """Project a Graph messageRule to the ``email_rule`` record.

    Args:
        rule: Graph ``messageRule`` object.

    Returns:
        The rule record; ``exceptions`` is ``None`` when none are set.
    """
    return {
        "id": rule["id"],
        "display_name": rule.get("displayName") or "",
        "sequence": rule.get("sequence") or 1,
        "is_enabled": bool(rule.get("isEnabled")),
        "conditions": predicates_from_graph(rule.get("conditions")),
        "actions": actions_from_graph(rule.get("actions")),
        "exceptions": predicates_from_graph(rule.get("exceptions")) or None,
    }


# --------------------------------------------------------------------------
# event
# --------------------------------------------------------------------------


def _ordinal_day(pattern: dict[str, Any]) -> str:
    days = ", ".join(d.capitalize() for d in pattern.get("daysOfWeek") or [])
    return f"the {pattern.get('index') or 'first'} {days}"


def _recurrence_summary(recurrence: dict[str, Any] | None) -> str | None:
    """Describe a Graph patternedRecurrence in one line."""
    if not recurrence:
        return None
    pattern = recurrence.get("pattern") or {}
    range_ = recurrence.get("range") or {}
    kind = pattern.get("type") or ""
    interval = pattern.get("interval") or 1
    unit = {"daily": "day", "weekly": "week"}.get(kind) or (
        "month" if kind.endswith("Monthly") else "year"
    )
    text = f"Every {unit}" if interval == 1 else f"Every {interval} {unit}s"
    month = _MONTHS[(pattern.get("month") or 1) - 1]
    if kind == "weekly":
        days = ", ".join(d.capitalize() for d in pattern.get("daysOfWeek") or [])
        text += f" on {days}"
    elif kind == "absoluteMonthly":
        text += f" on day {pattern.get('dayOfMonth')}"
    elif kind == "relativeMonthly":
        text += f" on {_ordinal_day(pattern)}"
    elif kind == "absoluteYearly":
        text += f" on {pattern.get('dayOfMonth')} {month}"
    elif kind == "relativeYearly":
        text += f" on {_ordinal_day(pattern)} of {month}"
    if range_.get("startDate"):
        text += f", from {range_['startDate']}"
    if range_.get("type") == "endDate" and range_.get("endDate"):
        text += f" until {range_['endDate']}"
    elif range_.get("type") == "numbered":
        text += f", {range_.get('numberOfOccurrences')} times"
    return text


def project_event_summary(
    event: dict[str, Any],
    *,
    calendar_id: str | None = None,
    tz: str | None = None,
) -> Record:
    """Project a Graph event (or calendarView instance) to ``event_summary``.

    Args:
        event: Graph ``event`` object.
        calendar_id: Calendar the event was read from, when known (Graph
            does not return it on the event).
        tz: IANA time zone for ``start``/``end``; defaults to the zone
            Graph used (``start.timeZone``).

    Returns:
        The summary record used by list and search results.
    """
    time_zone = tz or event["start"].get("timeZone") or "UTC"
    location = (event.get("location") or {}).get("displayName") or None
    return {
        "id": event["id"],
        "subject": sanitize_text(event.get("subject")),
        "start": _event_time(event["start"], time_zone),
        "end": _event_time(event["end"], time_zone),
        "time_zone": time_zone,
        "is_all_day": bool(event.get("isAllDay")),
        "location": sanitize_text(location),
        "organizer": _recipient(event.get("organizer")),
        "is_organizer": bool(event.get("isOrganizer")),
        "my_response": (event.get("responseStatus") or {}).get("response") or "none",
        "show_as": event.get("showAs") or "unknown",
        "attendee_count": len(event.get("attendees") or []),
        "calendar_id": calendar_id,
        "preview": sanitize_preview(event.get("bodyPreview")),
    }


def project_event_detail(
    event: dict[str, Any],
    *,
    calendar_id: str | None = None,
    include_body: bool = True,
    body_max_chars: int = DEFAULT_BODY_MAX_CHARS,
    tz: str | None = None,
) -> Record:
    """Project a Graph event to the ``event_detail`` record.

    Args:
        event: Graph ``event`` object.
        calendar_id: Calendar the event was read from, when known.
        include_body: Whether to return the body.
        body_max_chars: Body character cap; sets ``body_truncated``.
        tz: IANA time zone for ``start``/``end``.

    Returns:
        The detail record returned by ``m365_get`` and the calendar tools.
    """
    body, truncated = None, False
    if include_body:
        graph_body = event.get("body") or {}
        body, truncated = sanitize_body(
            graph_body.get("content"),
            graph_body.get("contentType"),
            body_max_chars,
        )
    attendees = []
    for attendee in event.get("attendees") or []:
        person = _recipient(attendee) or {"name": None, "address": ""}
        attendees.append(
            {
                **person,
                "type": attendee.get("type") or "required",
                "response": (attendee.get("status") or {}).get("response") or "none",
            }
        )
    return {
        **project_event_summary(event, calendar_id=calendar_id, tz=tz),
        "body": body,
        "body_truncated": truncated,
        "attendees": attendees,
        "web_link": event.get("webLink"),
        "recurrence": _recurrence_summary(event.get("recurrence")),
    }


# --------------------------------------------------------------------------
# calendar, contact, contact_folder
# --------------------------------------------------------------------------


def project_calendar(calendar: dict[str, Any]) -> Record:
    """Project a Graph calendar to the ``calendar`` record.

    Args:
        calendar: Graph ``calendar`` object.

    Returns:
        The calendar record; ``color`` prefers ``hexColor`` and is
        ``None`` for the automatic colour.
    """
    color = calendar.get("hexColor") or calendar.get("color")
    return {
        "id": calendar["id"],
        "name": calendar.get("name") or "",
        "is_default": bool(calendar.get("isDefaultCalendar")),
        "can_edit": bool(calendar.get("canEdit")),
        "color": None if color == "auto" else color,
    }


def project_contact(contact: dict[str, Any]) -> Record:
    """Project a Graph contact to the ``contact`` record.

    Args:
        contact: Graph ``contact`` object.

    Returns:
        The contact record.
    """
    return {
        "id": contact["id"],
        "display_name": contact.get("displayName"),
        "given_name": contact.get("givenName"),
        "surname": contact.get("surname"),
        "emails": [
            e["address"]
            for e in contact.get("emailAddresses") or []
            if e.get("address")
        ],
        "mobile_phone": contact.get("mobilePhone"),
        "business_phones": list(contact.get("businessPhones") or []),
        "home_phones": list(contact.get("homePhones") or []),
        "company_name": contact.get("companyName"),
        "job_title": contact.get("jobTitle"),
        "department": contact.get("department"),
        "folder_id": contact.get("parentFolderId"),
    }


def project_contact_folder(folder: dict[str, Any]) -> Record:
    """Project a Graph contactFolder to the ``contact_folder`` record.

    Args:
        folder: Graph ``contactFolder`` object.

    Returns:
        The contact folder record.
    """
    return {
        "id": folder["id"],
        "display_name": folder.get("displayName") or "",
        "parent_id": folder.get("parentFolderId"),
    }


# --------------------------------------------------------------------------
# drive_item
# --------------------------------------------------------------------------


def _drive_path(parent: dict[str, Any]) -> str | None:
    """Return the folder path from ``parentReference.path``.

    ``/drive/root:/Documents/Tax%20Files`` becomes ``/Documents/Tax Files``
    and ``/drive/root:`` becomes ``/``.
    """
    raw = parent.get("path")
    if not raw or "root:" not in raw:
        return None
    path = unquote(raw.split("root:", 1)[1]) or "/"
    return sanitize_text(path)


def project_drive_item(
    item: dict[str, Any], *, tree: bool = False, tz: str | None = None
) -> Record:
    """Project a Graph driveItem to the ``drive_item`` record.

    ``path`` is the containing folder's path, derived from
    ``parentReference.path``; it is ``None`` when Graph omits it (the
    drive root and some search results). Download URLs are never copied.

    Args:
        item: Graph ``driveItem`` object; in tree mode its expanded
            ``children`` become ``children``.
        tree: Whether to populate ``children`` for folders.
        tz: Optional IANA time zone for the timestamps.

    Returns:
        The drive item record.
    """
    is_folder = "folder" in item
    parent = item.get("parentReference") or {}
    children = None
    if tree and is_folder:
        children = [
            project_drive_item(child, tree=True, tz=tz)
            for child in item.get("children") or []
        ]
    return {
        "id": item["id"],
        "name": sanitize_text(item.get("name")) or "",
        "item_type": "folder" if is_folder else "file",
        "path": _drive_path(parent),
        "parent_id": parent.get("id"),
        "size": item.get("size") or 0,
        "modified_at": iso_datetime(item.get("lastModifiedDateTime"), tz),
        "created_at": iso_datetime(item.get("createdDateTime"), tz),
        "mime_type": (item.get("file") or {}).get("mimeType"),
        "child_count": (item["folder"].get("childCount") or 0) if is_folder else None,
        "web_url": item.get("webUrl"),
        "shared": bool(item.get("shared")),
        "children": children,
    }


# --------------------------------------------------------------------------
# operation
# --------------------------------------------------------------------------


def project_operation(monitor: dict[str, Any], *, operation_id: str) -> Record:
    """Project a Graph asyncJobStatus (copy monitor) to ``operation``.

    Args:
        monitor: JSON returned by the copy monitor URL.
        operation_id: The server's opaque handle for the operation.

    Returns:
        The operation record; any status other than completed or failed
        is reported as ``in_progress``.
    """
    status = _OPERATION_STATUS.get(monitor.get("status") or "", "in_progress")
    error = None
    if status == "failed":
        details = monitor.get("error") or {}
        error = details.get("message") or details.get("code") or "Copy failed"
    return {
        "operation_id": operation_id,
        "status": status,
        "percent_complete": monitor.get("percentageComplete"),
        "resource_id": monitor.get("resourceId"),
        "error": error,
    }
