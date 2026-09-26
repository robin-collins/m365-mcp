"""Calendar service: Microsoft Graph logic for events and calendars.

Callers are expected to validate inputs first; these functions build the
Graph requests, handle caching and return the Graph results.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from .. import graph

if TYPE_CHECKING:
    from ..cache import CacheManager


def _get_cache_manager() -> CacheManager:
    """Return the shared cache manager.

    The singleton lives in ``m365_mcp.cache``; it is imported lazily so
    tests can replace the manager.
    """
    from ..cache import get_cache_manager

    return get_cache_manager()


















def forward_event(
    account_id: str,
    event_id: str,
    *,
    to: list[str],
    cc: list[str] | None = None,
    message: str | None = None,
) -> dict[str, str]:
    """Forward an event to recipients.

    Args:
        account_id: Microsoft account identifier.
        event_id: The event ID to forward.
        to: Validated, de-duplicated To addresses.
        cc: Validated, de-duplicated CC addresses.
        message: Optional comment; whitespace is stripped and an empty
            result is omitted.

    Returns:
        ``{"status": "forwarded"}``.
    """
    payload: dict[str, Any] = {
        "toRecipients": [{"emailAddress": {"address": addr}} for addr in to],
    }

    if cc:
        payload["ccRecipients"] = [{"emailAddress": {"address": addr}} for addr in cc]

    if message:
        message_stripped = message.strip()
        if message_stripped:
            payload["comment"] = message_stripped

    endpoint = f"/me/events/{event_id}/forward"
    graph.request("POST", endpoint, account_id, json=payload)

    return {"status": "forwarded"}




def create_calendar(account_id: str, *, name: str) -> dict[str, Any]:
    """Create a calendar and invalidate the calendar list cache.

    Args:
        account_id: Microsoft account identifier.
        name: Validated, stripped calendar name.

    Returns:
        The created calendar object.

    Raises:
        ValueError: If Graph returns no calendar.
    """
    payload = {"name": name}

    result = graph.request("POST", "/me/calendars", account_id, json=payload)
    if not result:
        raise ValueError("Failed to create calendar")

    # Invalidate calendar list cache
    try:
        cache_manager = _get_cache_manager()
        cache_manager.invalidate_pattern(
            f"calendar_list_calendars:{account_id}:*",
            reason="calendar_created",
        )
    except Exception:
        # If cache invalidation fails, continue
        pass

    return result








# ----------------------------------------------------------------------
# Unified tool surface (Phase 3). No caching here: the registry caches.
# ----------------------------------------------------------------------

# CLDR windowsZones (territory 001): Windows time-zone IDs, as returned by
# mailboxSettings and workingHours, mapped to IANA names.
WINDOWS_TIME_ZONES: dict[str, str] = {
    "Dateline Standard Time": "Etc/GMT+12",
    "UTC-11": "Etc/GMT+11",
    "Aleutian Standard Time": "America/Adak",
    "Hawaiian Standard Time": "Pacific/Honolulu",
    "Marquesas Standard Time": "Pacific/Marquesas",
    "Alaskan Standard Time": "America/Anchorage",
    "UTC-09": "Etc/GMT+9",
    "Pacific Standard Time (Mexico)": "America/Tijuana",
    "UTC-08": "Etc/GMT+8",
    "Pacific Standard Time": "America/Los_Angeles",
    "US Mountain Standard Time": "America/Phoenix",
    "Mountain Standard Time (Mexico)": "America/Mazatlan",
    "Mountain Standard Time": "America/Denver",
    "Yukon Standard Time": "America/Whitehorse",
    "Central America Standard Time": "America/Guatemala",
    "Central Standard Time": "America/Chicago",
    "Easter Island Standard Time": "Pacific/Easter",
    "Central Standard Time (Mexico)": "America/Mexico_City",
    "Canada Central Standard Time": "America/Regina",
    "SA Pacific Standard Time": "America/Bogota",
    "Eastern Standard Time (Mexico)": "America/Cancun",
    "Eastern Standard Time": "America/New_York",
    "Haiti Standard Time": "America/Port-au-Prince",
    "Cuba Standard Time": "America/Havana",
    "US Eastern Standard Time": "America/Indiana/Indianapolis",
    "Turks And Caicos Standard Time": "America/Grand_Turk",
    "Paraguay Standard Time": "America/Asuncion",
    "Atlantic Standard Time": "America/Halifax",
    "Venezuela Standard Time": "America/Caracas",
    "Central Brazilian Standard Time": "America/Cuiaba",
    "SA Western Standard Time": "America/La_Paz",
    "Pacific SA Standard Time": "America/Santiago",
    "Newfoundland Standard Time": "America/St_Johns",
    "Tocantins Standard Time": "America/Araguaina",
    "E. South America Standard Time": "America/Sao_Paulo",
    "SA Eastern Standard Time": "America/Cayenne",
    "Argentina Standard Time": "America/Argentina/Buenos_Aires",
    "Greenland Standard Time": "America/Nuuk",
    "Montevideo Standard Time": "America/Montevideo",
    "Magallanes Standard Time": "America/Punta_Arenas",
    "Saint Pierre Standard Time": "America/Miquelon",
    "Bahia Standard Time": "America/Bahia",
    "UTC-02": "Etc/GMT+2",
    "Mid-Atlantic Standard Time": "Etc/GMT+2",
    "Azores Standard Time": "Atlantic/Azores",
    "Cape Verde Standard Time": "Atlantic/Cape_Verde",
    "UTC": "UTC",
    "Coordinated Universal Time": "UTC",
    "GMT Standard Time": "Europe/London",
    "Greenwich Standard Time": "Atlantic/Reykjavik",
    "Sao Tome Standard Time": "Africa/Sao_Tome",
    "Morocco Standard Time": "Africa/Casablanca",
    "W. Europe Standard Time": "Europe/Berlin",
    "Central Europe Standard Time": "Europe/Budapest",
    "Romance Standard Time": "Europe/Paris",
    "Central European Standard Time": "Europe/Warsaw",
    "W. Central Africa Standard Time": "Africa/Lagos",
    "Jordan Standard Time": "Asia/Amman",
    "GTB Standard Time": "Europe/Bucharest",
    "Middle East Standard Time": "Asia/Beirut",
    "Egypt Standard Time": "Africa/Cairo",
    "E. Europe Standard Time": "Europe/Chisinau",
    "Syria Standard Time": "Asia/Damascus",
    "West Bank Standard Time": "Asia/Hebron",
    "South Africa Standard Time": "Africa/Johannesburg",
    "FLE Standard Time": "Europe/Kyiv",
    "Israel Standard Time": "Asia/Jerusalem",
    "South Sudan Standard Time": "Africa/Juba",
    "Kaliningrad Standard Time": "Europe/Kaliningrad",
    "Sudan Standard Time": "Africa/Khartoum",
    "Libya Standard Time": "Africa/Tripoli",
    "Namibia Standard Time": "Africa/Windhoek",
    "Arabic Standard Time": "Asia/Baghdad",
    "Turkey Standard Time": "Europe/Istanbul",
    "Arab Standard Time": "Asia/Riyadh",
    "Belarus Standard Time": "Europe/Minsk",
    "Russian Standard Time": "Europe/Moscow",
    "E. Africa Standard Time": "Africa/Nairobi",
    "Volgograd Standard Time": "Europe/Volgograd",
    "Iran Standard Time": "Asia/Tehran",
    "Arabian Standard Time": "Asia/Dubai",
    "Astrakhan Standard Time": "Europe/Astrakhan",
    "Azerbaijan Standard Time": "Asia/Baku",
    "Russia Time Zone 3": "Europe/Samara",
    "Mauritius Standard Time": "Indian/Mauritius",
    "Saratov Standard Time": "Europe/Saratov",
    "Georgian Standard Time": "Asia/Tbilisi",
    "Caucasus Standard Time": "Asia/Yerevan",
    "Afghanistan Standard Time": "Asia/Kabul",
    "West Asia Standard Time": "Asia/Tashkent",
    "Ekaterinburg Standard Time": "Asia/Yekaterinburg",
    "Pakistan Standard Time": "Asia/Karachi",
    "Qyzylorda Standard Time": "Asia/Qyzylorda",
    "India Standard Time": "Asia/Kolkata",
    "Sri Lanka Standard Time": "Asia/Colombo",
    "Nepal Standard Time": "Asia/Kathmandu",
    "Central Asia Standard Time": "Asia/Almaty",
    "Bangladesh Standard Time": "Asia/Dhaka",
    "Omsk Standard Time": "Asia/Omsk",
    "Myanmar Standard Time": "Asia/Yangon",
    "SE Asia Standard Time": "Asia/Bangkok",
    "Altai Standard Time": "Asia/Barnaul",
    "W. Mongolia Standard Time": "Asia/Hovd",
    "North Asia Standard Time": "Asia/Krasnoyarsk",
    "N. Central Asia Standard Time": "Asia/Novosibirsk",
    "Tomsk Standard Time": "Asia/Tomsk",
    "China Standard Time": "Asia/Shanghai",
    "North Asia East Standard Time": "Asia/Irkutsk",
    "Singapore Standard Time": "Asia/Singapore",
    "W. Australia Standard Time": "Australia/Perth",
    "Taipei Standard Time": "Asia/Taipei",
    "Ulaanbaatar Standard Time": "Asia/Ulaanbaatar",
    "Aus Central W. Standard Time": "Australia/Eucla",
    "Transbaikal Standard Time": "Asia/Chita",
    "Tokyo Standard Time": "Asia/Tokyo",
    "North Korea Standard Time": "Asia/Pyongyang",
    "Korea Standard Time": "Asia/Seoul",
    "Yakutsk Standard Time": "Asia/Yakutsk",
    "Cen. Australia Standard Time": "Australia/Adelaide",
    "AUS Central Standard Time": "Australia/Darwin",
    "E. Australia Standard Time": "Australia/Brisbane",
    "AUS Eastern Standard Time": "Australia/Sydney",
    "West Pacific Standard Time": "Pacific/Port_Moresby",
    "Tasmania Standard Time": "Australia/Hobart",
    "Vladivostok Standard Time": "Asia/Vladivostok",
    "Lord Howe Standard Time": "Australia/Lord_Howe",
    "Bougainville Standard Time": "Pacific/Bougainville",
    "Russia Time Zone 10": "Asia/Srednekolymsk",
    "Magadan Standard Time": "Asia/Magadan",
    "Norfolk Standard Time": "Pacific/Norfolk",
    "Sakhalin Standard Time": "Asia/Sakhalin",
    "Central Pacific Standard Time": "Pacific/Guadalcanal",
    "Russia Time Zone 11": "Asia/Kamchatka",
    "New Zealand Standard Time": "Pacific/Auckland",
    "UTC+12": "Etc/GMT-12",
    "Fiji Standard Time": "Pacific/Fiji",
    "Kamchatka Standard Time": "Asia/Kamchatka",
    "Chatham Islands Standard Time": "Pacific/Chatham",
    "UTC+13": "Etc/GMT-13",
    "Tonga Standard Time": "Pacific/Tongatapu",
    "Samoa Standard Time": "Pacific/Apia",
    "Line Islands Standard Time": "Pacific/Kiritimati",
}
_WINDOWS_TIME_ZONES_FOLDED = {k.casefold(): v for k, v in WINDOWS_TIME_ZONES.items()}


def to_iana_time_zone(name: str | None) -> str | None:
    """Return the IANA name for a Windows or IANA time-zone name.

    Args:
        name: A time-zone name from Graph (Windows ID or IANA name).

    Returns:
        The IANA name, or ``None`` when the name is unknown (for example a
        custom ``tzone://Microsoft/Custom`` zone).
    """
    if not name:
        return None
    mapped = _WINDOWS_TIME_ZONES_FOLDED.get(name.strip().casefold())
    if mapped:
        return mapped
    try:
        ZoneInfo(name.strip())
    except (ValueError, KeyError):
        return None
    return name.strip()


def _prefer(time_zone: str | None, *, text_body: bool = False) -> dict[str, str]:
    """Build the Graph ``Prefer`` header for event reads and writes."""
    values = []
    if time_zone:
        values.append(f'outlook.timezone="{time_zone}"')
    if text_body:
        values.append('outlook.body-content-type="text"')
    return {"Prefer": ", ".join(values)} if values else {}


def get_mailbox_time_zone(account_id: str) -> str | None:
    """Return the mailbox time zone as Graph stores it (often a Windows ID).

    Args:
        account_id: Microsoft account identifier.

    Returns:
        The ``mailboxSettings.timeZone`` value, or ``None`` when unset.
    """
    result = graph.request("GET", "/me/mailboxSettings/timeZone", account_id)
    return (result or {}).get("value") or None


def get_working_hours(account_id: str) -> dict[str, Any] | None:
    """Return ``mailboxSettings.workingHours`` (Graph shape), if set.

    Args:
        account_id: Microsoft account identifier.

    Returns:
        The Graph ``workingHours`` object, or ``None``.
    """
    result = graph.request("GET", "/me/mailboxSettings/workingHours", account_id)
    if not result or not result.get("daysOfWeek"):
        return None
    return result


def _calendar_base(calendar_id: str | None) -> str:
    """Return the Graph path of a calendar (``None`` is the default one)."""
    return "/me/calendar" if calendar_id is None else f"/me/calendars/{calendar_id}"


def _utc_param(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def calendar_view_page(
    account_id: str,
    *,
    calendar_id: str | None,
    start: datetime,
    end: datetime,
    top: int,
    time_zone: str,
    next_link: str | None = None,
) -> dict[str, Any]:
    """Read one page of a calendar's ``calendarView`` (recurrences expanded).

    Args:
        account_id: Microsoft account identifier.
        calendar_id: Calendar ID, or ``None`` for the default calendar.
        start: Timezone-aware window start.
        end: Timezone-aware window end.
        top: Page size.
        time_zone: IANA zone Graph should express times in.
        next_link: ``@odata.nextLink`` of the previous page, if any.

    Returns:
        The Graph page: ``value`` and optional ``@odata.nextLink``.
    """
    headers = _prefer(time_zone)
    if next_link:
        path = next_link.replace(graph.BASE_URL, "")
        return graph.request("GET", path, account_id, headers=headers) or {}
    params = {
        "startDateTime": _utc_param(start),
        "endDateTime": _utc_param(end),
        "$orderby": "start/dateTime",
        "$top": top,
    }
    return (
        graph.request(
            "GET",
            f"{_calendar_base(calendar_id)}/calendarView",
            account_id,
            params=params,
            headers=headers,
        )
        or {}
    )


def calendar_view_busy(
    account_id: str, *, start: datetime, end: datetime
) -> list[dict[str, Any]]:
    """Return every default-calendar instance in a window (all pages).

    Times come back in UTC; only the fields availability needs are read.

    Args:
        account_id: Microsoft account identifier.
        start: Timezone-aware window start.
        end: Timezone-aware window end.

    Returns:
        Graph event instances ordered by start.
    """
    params = {
        "startDateTime": _utc_param(start),
        "endDateTime": _utc_param(end),
        "$select": "subject,start,end,showAs",
        "$orderby": "start/dateTime",
        "$top": 100,
    }
    return list(graph.request_paginated("/me/calendarView", account_id, params=params))


def list_all_calendars(account_id: str) -> list[dict[str, Any]]:
    """Return all of the user's calendars (all pages, uncached).

    Args:
        account_id: Microsoft account identifier.

    Returns:
        Graph calendar objects.
    """
    return list(
        graph.request_paginated(
            "/me/calendars",
            account_id,
            params={"$select": "id,name,color,hexColor,canEdit,isDefaultCalendar"},
        )
    )


def get_calendar(account_id: str, calendar_id: str | None) -> dict[str, Any]:
    """Return one calendar; ``None`` means the default calendar.

    Args:
        account_id: Microsoft account identifier.
        calendar_id: Calendar ID or ``None``.

    Returns:
        The Graph calendar object.
    """
    return graph.request("GET", _calendar_base(calendar_id), account_id) or {}


def remove_calendar(account_id: str, calendar_id: str) -> None:
    """Delete a calendar by ID (callers refuse the default calendar).

    Args:
        account_id: Microsoft account identifier.
        calendar_id: Calendar ID.
    """
    graph.request("DELETE", f"/me/calendars/{calendar_id}", account_id)


def fetch_event(
    account_id: str, event_id: str, *, time_zone: str | None = None
) -> dict[str, Any]:
    """Return one event (uncached) with times in ``time_zone``.

    Args:
        account_id: Microsoft account identifier.
        event_id: Event ID.
        time_zone: IANA zone for the ``Prefer: outlook.timezone`` header.

    Returns:
        The Graph event object.
    """
    return (
        graph.request(
            "GET",
            f"/me/events/{event_id}",
            account_id,
            headers=_prefer(time_zone, text_body=True),
        )
        or {}
    )


def date_time_time_zone(value: datetime, time_zone: str) -> dict[str, str]:
    """Express an aware datetime as a Graph ``dateTimeTimeZone``.

    Args:
        value: Timezone-aware instant.
        time_zone: IANA zone to express it in.

    Returns:
        ``{"dateTime": <local wall time>, "timeZone": time_zone}``.
    """
    local = value.astimezone(ZoneInfo(time_zone)).replace(tzinfo=None)
    return {"dateTime": local.isoformat(), "timeZone": time_zone}


def attendees_body(attendees: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert tool attendees ``{address, name?, type?}`` to Graph attendees.

    Args:
        attendees: Schema-validated attendee objects.

    Returns:
        Graph ``attendee`` objects.
    """
    result = []
    for attendee in attendees:
        email: dict[str, str] = {"address": attendee["address"]}
        if attendee.get("name"):
            email["name"] = attendee["name"]
        result.append(
            {"emailAddress": email, "type": attendee.get("type") or "required"}
        )
    return result


def event_body(
    fields: dict[str, Any], *, time_zone: str, attendees: list[dict[str, Any]] | None
) -> dict[str, Any]:
    """Build a Graph event body from the tools' event fields.

    Args:
        fields: Any of ``subject``, ``start``/``end`` (aware datetimes),
            ``is_all_day``, ``location``, ``body``, ``body_format``,
            ``reminder_minutes`` and ``show_as``.
        time_zone: IANA zone for ``start``/``end``.
        attendees: Graph attendee objects to set, or ``None`` to leave
            them unchanged.

    Returns:
        The Graph request body (only the supplied fields).
    """
    body: dict[str, Any] = {}
    if "subject" in fields:
        body["subject"] = fields["subject"]
    for name in ("start", "end"):
        if fields.get(name) is not None:
            body[name] = date_time_time_zone(fields[name], time_zone)
    if "is_all_day" in fields:
        body["isAllDay"] = fields["is_all_day"]
    if "location" in fields:
        body["location"] = {"displayName": fields["location"]}
    if "body" in fields:
        body["body"] = {
            "contentType": "html" if fields.get("body_format") == "html" else "text",
            "content": fields["body"],
        }
    if "reminder_minutes" in fields:
        body["isReminderOn"] = True
        body["reminderMinutesBeforeStart"] = fields["reminder_minutes"]
    if "show_as" in fields:
        body["showAs"] = fields["show_as"]
    if attendees is not None:
        body["attendees"] = attendees
    return body


def post_event(
    account_id: str,
    body: dict[str, Any],
    *,
    calendar_id: str | None,
    time_zone: str,
) -> dict[str, Any]:
    """Create an event (``POST /me/events`` or a calendar's ``/events``).

    Args:
        account_id: Microsoft account identifier.
        body: Graph event body.
        calendar_id: Calendar ID, or ``None`` for the default calendar.
        time_zone: IANA zone for the ``Prefer: outlook.timezone`` header.

    Returns:
        The created Graph event.
    """
    path = (
        "/me/events" if calendar_id is None else f"/me/calendars/{calendar_id}/events"
    )
    return (
        graph.request(
            "POST",
            path,
            account_id,
            json=body,
            headers=_prefer(time_zone, text_body=True),
        )
        or {}
    )


def patch_event(
    account_id: str, event_id: str, body: dict[str, Any], *, time_zone: str
) -> dict[str, Any]:
    """Update an event with ``PATCH /me/events/{id}``.

    Args:
        account_id: Microsoft account identifier.
        event_id: Event ID.
        body: Graph event fields to change.
        time_zone: IANA zone for the ``Prefer: outlook.timezone`` header.

    Returns:
        The updated Graph event (empty when Graph returns no body).
    """
    return (
        graph.request(
            "PATCH",
            f"/me/events/{event_id}",
            account_id,
            json=body,
            headers=_prefer(time_zone, text_body=True),
        )
        or {}
    )


def cancel_event(account_id: str, event_id: str, *, comment: str | None) -> None:
    """Cancel a meeting you organise (``POST /me/events/{id}/cancel``).

    Args:
        account_id: Microsoft account identifier.
        event_id: Event ID.
        comment: Optional note sent with the cancellation.
    """
    graph.request(
        "POST",
        f"/me/events/{event_id}/cancel",
        account_id,
        json={"comment": comment or ""},
    )


def remove_event(account_id: str, event_id: str) -> None:
    """Delete an event (``DELETE /me/events/{id}``).

    Args:
        account_id: Microsoft account identifier.
        event_id: Event ID.
    """
    graph.request("DELETE", f"/me/events/{event_id}", account_id)


RESPONSE_ACTIONS = {
    "accept": "accept",
    "tentative": "tentativelyAccept",
    "decline": "decline",
}


def send_event_response(
    account_id: str,
    event_id: str,
    *,
    action: str,
    send_response: bool,
    comment: str | None = None,
    proposed_start: datetime | None = None,
    proposed_end: datetime | None = None,
) -> None:
    """Accept, tentatively accept or decline an invitation.

    Args:
        account_id: Microsoft account identifier.
        event_id: Event ID.
        action: ``accept``, ``tentative`` or ``decline``.
        send_response: Whether the organiser is emailed.
        comment: Optional message to the organiser.
        proposed_start: Proposed new start (tentative/decline only).
        proposed_end: Proposed new end (tentative/decline only).
    """
    payload: dict[str, Any] = {"sendResponse": send_response}
    if comment:
        payload["comment"] = comment
    if proposed_start is not None and proposed_end is not None:
        payload["proposedNewTime"] = {
            "start": date_time_time_zone(proposed_start, "UTC"),
            "end": date_time_time_zone(proposed_end, "UTC"),
        }
    graph.request(
        "POST",
        f"/me/events/{event_id}/{RESPONSE_ACTIONS[action]}",
        account_id,
        json=payload,
    )
