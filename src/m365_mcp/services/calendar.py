"""Calendar service: Microsoft Graph logic for events and calendars.

Callers are expected to validate inputs first; these functions build the
Graph requests, handle caching and return the Graph results.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from .. import graph

if TYPE_CHECKING:
    from ..cache import CacheManager


def _get_cache_manager() -> CacheManager:
    """Return the shared cache manager.

    The singleton currently lives in ``tools.cache_tools``; it is imported
    lazily so this module does not import the tool layer at load time.
    """
    from ..cache import get_cache_manager

    return get_cache_manager()


def _get_user_email_with_fallback(account_id: str) -> str:
    """Get user email with fallback chain for profiles missing mail field.

    Implements a fallback strategy:
    1. Try mail field (primary email)
    2. Fallback to userPrincipalName (usually email-like)
    3. Fallback to first item in otherMails array
    4. Raise ValueError if no email found

    Args:
        account_id: Microsoft account identifier.

    Returns:
        User email address.

    Raises:
        ValueError: If no email address can be determined from user profile.
    """
    # Request user info with all possible email fields
    user_info = graph.request(
        "GET",
        "/me?$select=mail,userPrincipalName,otherMails",
        account_id,
    )

    if not user_info:
        raise ValueError("Failed to retrieve user profile information")

    # Try mail field first (primary email)
    mail = user_info.get("mail")
    if mail and isinstance(mail, str) and mail.strip():
        return mail.strip()

    # Fallback to userPrincipalName (usually email format)
    upn = user_info.get("userPrincipalName")
    if upn and isinstance(upn, str) and upn.strip():
        return upn.strip()

    # Fallback to first item in otherMails array
    other_mails = user_info.get("otherMails")
    if other_mails and isinstance(other_mails, list) and len(other_mails) > 0:
        first_other = other_mails[0]
        if first_other and isinstance(first_other, str) and first_other.strip():
            return first_other.strip()

    # No email found in any field
    raise ValueError(
        "Unable to determine user email address. "
        "The user profile is missing mail, userPrincipalName, "
        "and otherMails fields."
    )


def list_events(
    account_id: str,
    *,
    days_ahead: int = 7,
    include_details: bool = False,
    limit: int = 50,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """List upcoming events from now until ``days_ahead`` days ahead.

    Args:
        account_id: Microsoft account identifier.
        days_ahead: Number of days ahead to look for events.
        include_details: Include attendees, body, recurrence and meeting data.
        limit: Maximum number of events to return.
        use_cache: Whether to read and write the cache.
        force_refresh: Bypass cached data and fetch from Graph.

    Returns:
        List of event dicts, each with ``_cache_status`` (and
        ``_cached_at`` when freshly fetched).
    """
    # Calculate time window
    now = datetime.now(timezone.utc)
    end_time = now + timedelta(days=days_ahead)

    # Build cache parameters
    cache_params = {
        "days_ahead": days_ahead,
        "include_details": include_details,
        "limit": limit,
    }

    # Check cache if enabled
    if use_cache and not force_refresh:
        try:
            cache_manager = _get_cache_manager()
            cached_result = cache_manager.get_cached(
                account_id, "calendar_list_events", cache_params
            )

            if cached_result:
                data, state = cached_result
                # Add cache status to each event
                for event in data:
                    event["_cache_status"] = state.value
                return data
        except Exception:
            # If cache fails, continue to API call
            pass

    # Build select fields based on include_details
    if include_details:
        select_fields = "id,subject,start,end,location,body,attendees,organizer,isAllDay,isCancelled,recurrence,onlineMeeting"
    else:
        select_fields = "id,subject,start,end,location,organizer,isAllDay,isCancelled"

    # Query parameters
    params = {
        "$filter": f"start/dateTime ge '{now.isoformat()}' and start/dateTime le '{end_time.isoformat()}'",
        "$select": select_fields,
        "$orderby": "start/dateTime",
        "$top": limit,
    }

    # Fetch from API
    events = list(
        graph.request_paginated(
            "/me/calendar/events",
            account_id,
            params=params,
            limit=limit,
        )
    )

    # Add cache metadata to each event
    cached_at = datetime.now(timezone.utc).isoformat()
    for event in events:
        event["_cache_status"] = "fresh"
        event["_cached_at"] = cached_at

    # Store in cache
    if use_cache:
        try:
            cache_manager = _get_cache_manager()
            cache_manager.set_cached(
                account_id, "calendar_list_events", cache_params, events
            )
        except Exception:
            # If cache storage fails, still return the result
            pass

    return events


def get_event(
    account_id: str,
    event_id: str,
    *,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Get full details of one event.

    Args:
        account_id: Microsoft account identifier.
        event_id: The event ID.
        use_cache: Whether to read and write the cache.
        force_refresh: Bypass cached data and fetch from Graph.

    Returns:
        Event dict with ``_cache_status`` (and ``_cached_at`` when fresh).

    Raises:
        ValueError: If Graph returns no event.
    """
    # Build cache parameters
    cache_params = {"event_id": event_id}

    # Check cache if enabled
    if use_cache and not force_refresh:
        try:
            cache_manager = _get_cache_manager()
            cached_result = cache_manager.get_cached(
                account_id, "calendar_get_event", cache_params
            )

            if cached_result:
                data, state = cached_result
                data["_cache_status"] = state.value
                return data
        except Exception:
            # If cache fails, continue to API call
            pass

    # Fetch from API
    result = graph.request("GET", f"/me/events/{event_id}", account_id)
    if not result:
        raise ValueError(f"Event with ID {event_id} not found")

    # Add cache metadata
    result["_cache_status"] = "fresh"
    result["_cached_at"] = datetime.now(timezone.utc).isoformat()

    # Store in cache
    if use_cache:
        try:
            cache_manager = _get_cache_manager()
            cache_manager.set_cached(
                account_id, "calendar_get_event", cache_params, result
            )
        except Exception:
            # If cache storage fails, still return the result
            pass

    return result


def create_event(
    account_id: str,
    *,
    subject: str,
    start: datetime,
    end: datetime,
    timezone_name: str,
    location: str | None = None,
    body: str | None = None,
    attendees: list[str] | None = None,
) -> dict[str, Any]:
    """Create a calendar event.

    Args:
        account_id: Microsoft account identifier.
        subject: Event title.
        start: Validated, timezone-aware start datetime.
        end: Validated, timezone-aware end datetime.
        timezone_name: Validated IANA timezone the event is expressed in.
        location: Optional location display name.
        body: Optional plain-text description.
        attendees: Validated, de-duplicated attendee addresses.

    Returns:
        The created event object.

    Raises:
        ValueError: If Graph returns no event.
    """
    tzinfo = ZoneInfo(timezone_name)
    start_local = start.astimezone(tzinfo)
    end_local = end.astimezone(tzinfo)

    event: dict[str, Any] = {
        "subject": subject,
        "start": {
            "dateTime": start_local.isoformat(),
            "timeZone": timezone_name,
        },
        "end": {
            "dateTime": end_local.isoformat(),
            "timeZone": timezone_name,
        },
    }

    if location:
        event["location"] = {"displayName": location}

    if body:
        event["body"] = {"contentType": "Text", "content": body}

    if attendees:
        event["attendees"] = [
            {"emailAddress": {"address": address}, "type": "required"}
            for address in attendees
        ]

    result = graph.request("POST", "/me/events", account_id, json=event)
    if not result:
        raise ValueError("Failed to create event")

    # Note: Cache invalidation for calendar events happens automatically via TTL
    # No manual invalidation needed as calendar list caches are short-lived (5min)

    return result


def update_event(
    account_id: str,
    event_id: str,
    *,
    subject: str | None = None,
    start: str | None = None,
    end: str | None = None,
    timezone_name: str = "UTC",
    location: str | None = None,
    body: str | None = None,
    attendees: list[str] | None = None,
) -> dict[str, Any]:
    """Update event properties; ``None`` fields are left unchanged.

    Args:
        account_id: Microsoft account identifier.
        event_id: The event ID to update.
        subject: New subject.
        start: New ISO-8601 start datetime string.
        end: New ISO-8601 end datetime string.
        timezone_name: Timezone applied to ``start`` and ``end``.
        location: New location display name (whitespace is stripped).
        body: New plain-text description.
        attendees: Validated, de-duplicated attendee addresses; an empty
            list clears the attendees.

    Returns:
        The updated event object, or ``{"status": "updated"}`` when Graph
        returns no body.
    """
    formatted_updates: dict[str, Any] = {}

    if subject is not None:
        formatted_updates["subject"] = subject

    if start is not None:
        formatted_updates["start"] = {
            "dateTime": start,
            "timeZone": timezone_name,
        }

    if end is not None:
        formatted_updates["end"] = {
            "dateTime": end,
            "timeZone": timezone_name,
        }

    if location is not None:
        formatted_updates["location"] = {"displayName": location.strip()}

    if body is not None:
        formatted_updates["body"] = {"contentType": "Text", "content": body}

    if attendees is not None:
        formatted_updates["attendees"] = [
            {"emailAddress": {"address": address}, "type": "required"}
            for address in attendees
        ]

    result = graph.request(
        "PATCH", f"/me/events/{event_id}", account_id, json=formatted_updates
    )

    # Note: Cache invalidation happens automatically via TTL (5min for calendar_list_events)

    return result or {"status": "updated"}


def delete_event(
    account_id: str,
    event_id: str,
    *,
    send_cancellation: bool = True,
) -> dict[str, str]:
    """Delete an event, optionally cancelling it for attendees.

    Args:
        account_id: Microsoft account identifier.
        event_id: The event to delete.
        send_cancellation: Send cancellation notices via ``/cancel``
            instead of a plain delete.

    Returns:
        ``{"status": "deleted"}``.
    """
    if send_cancellation:
        graph.request("POST", f"/me/events/{event_id}/cancel", account_id, json={})
    else:
        graph.request("DELETE", f"/me/events/{event_id}", account_id)

    # Note: Cache invalidation happens automatically via TTL (5min for calendar_list_events)

    return {"status": "deleted"}


def respond_event(
    account_id: str,
    event_id: str,
    *,
    response: str,
    comment: str | None = None,
) -> dict[str, str]:
    """Respond to an event invitation.

    Args:
        account_id: Microsoft account identifier.
        event_id: The event ID to respond to.
        response: Graph response action: ``accept``, ``decline`` or
            ``tentativelyAccept``.
        comment: Optional trimmed message to the organizer.

    Returns:
        ``{"status": response}``.
    """
    payload: dict[str, Any] = {"sendResponse": True}
    if comment is not None:
        payload["comment"] = comment

    graph.request(
        "POST",
        f"/me/events/{event_id}/{response}",
        account_id,
        json=payload,
    )
    return {"status": response}


def check_availability(
    account_id: str,
    *,
    start: datetime,
    end: datetime,
    attendees: list[str] | None = None,
) -> dict[str, Any]:
    """Get the schedule of the current user and optional attendees.

    Args:
        account_id: Microsoft account identifier.
        start: Validated, timezone-aware window start.
        end: Validated, timezone-aware window end.
        attendees: Validated, de-duplicated attendee addresses.

    Returns:
        Graph ``getSchedule`` result.

    Raises:
        ValueError: If the user email is unavailable or Graph returns
            no result.
    """
    # Get user email with fallback chain
    user_email = _get_user_email_with_fallback(account_id)
    schedules = [user_email]
    current_keys = {user_email.casefold()}
    for address in attendees or []:
        key = address.casefold()
        if key in current_keys:
            continue
        current_keys.add(key)
        schedules.append(address)

    payload = {
        "schedules": schedules,
        "startTime": {
            "dateTime": start.astimezone(timezone.utc).isoformat(),
            "timeZone": "UTC",
        },
        "endTime": {
            "dateTime": end.astimezone(timezone.utc).isoformat(),
            "timeZone": "UTC",
        },
        "availabilityViewInterval": 30,
    }

    result = graph.request("POST", "/me/calendar/getSchedule", account_id, json=payload)
    if not result:
        raise ValueError("Failed to check availability")
    return result


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


def list_calendars(
    account_id: str,
    *,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """List all calendars accessible by the user.

    Args:
        account_id: Microsoft account identifier.
        use_cache: Whether to read and write the cache.
        force_refresh: Bypass cached data and fetch from Graph.

    Returns:
        List of calendar dicts, each with ``_cache_status`` (and
        ``_cached_at`` when freshly fetched).
    """
    # Build cache parameters
    cache_params: dict[str, Any] = {}

    # Check cache if enabled
    if use_cache and not force_refresh:
        try:
            cache_manager = _get_cache_manager()
            cached_result = cache_manager.get_cached(
                account_id, "calendar_list_calendars", cache_params
            )

            if cached_result:
                data, state = cached_result
                # Add cache status to each calendar
                for calendar in data:
                    calendar["_cache_status"] = state.value
                return data
        except Exception:
            # If cache fails, continue to API call
            pass

    # Fetch from API
    calendars = list(
        graph.request_paginated(
            "/me/calendars",
            account_id,
            params={
                "$select": "id,name,color,canEdit,canShare,canViewPrivateItems,owner,isDefaultCalendar"
            },
        )
    )

    # Add cache metadata to each calendar
    cached_at = datetime.now(timezone.utc).isoformat()
    for calendar in calendars:
        calendar["_cache_status"] = "fresh"
        calendar["_cached_at"] = cached_at

    # Store in cache
    if use_cache:
        try:
            cache_manager = _get_cache_manager()
            cache_manager.set_cached(
                account_id, "calendar_list_calendars", cache_params, calendars
            )
        except Exception:
            # If cache storage fails, still return the result
            pass

    return calendars


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


def delete_calendar(account_id: str, calendar_id: str) -> dict[str, str]:
    """Delete a non-default calendar and invalidate the list cache.

    Args:
        account_id: Microsoft account identifier.
        calendar_id: The calendar ID to delete.

    Returns:
        ``{"status": "deleted"}``.

    Raises:
        ValueError: If the calendar is the default calendar.
    """
    # Check if this is the default calendar (cannot be deleted)
    calendar_info = graph.request(
        "GET",
        f"/me/calendars/{calendar_id}?$select=isDefaultCalendar",
        account_id,
    )

    if calendar_info and calendar_info.get("isDefaultCalendar"):
        raise ValueError("Cannot delete the default calendar")

    # Delete calendar
    graph.request("DELETE", f"/me/calendars/{calendar_id}", account_id)

    # Invalidate calendar list cache
    try:
        cache_manager = _get_cache_manager()
        cache_manager.invalidate_pattern(
            f"calendar_list_calendars:{account_id}:*",
            reason="calendar_deleted",
        )
    except Exception:
        # If cache invalidation fails, continue
        pass

    return {"status": "deleted"}


def propose_new_time(
    account_id: str,
    event_id: str,
    *,
    start: datetime,
    end: datetime,
    message: str | None = None,
) -> dict[str, str]:
    """Tentatively accept an event while proposing a new time.

    Args:
        account_id: Microsoft account identifier.
        event_id: The event ID.
        start: Validated, timezone-aware proposed start.
        end: Validated, timezone-aware proposed end.
        message: Optional comment; whitespace is stripped and an empty
            result is omitted.

    Returns:
        ``{"status": "proposed_new_time"}``.
    """
    payload: dict[str, Any] = {
        "proposedNewTime": {
            "start": {
                "dateTime": start.astimezone(timezone.utc).isoformat(),
                "timeZone": "UTC",
            },
            "end": {
                "dateTime": end.astimezone(timezone.utc).isoformat(),
                "timeZone": "UTC",
            },
        },
        "sendResponse": True,
    }

    if message:
        message_stripped = message.strip()
        if message_stripped:
            payload["comment"] = message_stripped

    # Send tentative response with proposed new time
    graph.request(
        "POST",
        f"/me/events/{event_id}/tentativelyAccept",
        account_id,
        json=payload,
    )

    return {"status": "proposed_new_time"}


def get_free_busy(
    account_id: str,
    *,
    attendees: list[str],
    start: datetime,
    end: datetime,
    time_interval: int = 30,
) -> dict[str, Any]:
    """Get free/busy availability view for attendees.

    Args:
        account_id: Microsoft account identifier.
        attendees: Validated, de-duplicated attendee addresses.
        start: Validated, timezone-aware window start.
        end: Validated, timezone-aware window end.
        time_interval: Availability view interval in minutes.

    Returns:
        Graph ``getSchedule`` result.

    Raises:
        ValueError: If Graph returns no result.
    """
    payload = {
        "schedules": attendees,
        "startTime": {
            "dateTime": start.astimezone(timezone.utc).isoformat(),
            "timeZone": "UTC",
        },
        "endTime": {
            "dateTime": end.astimezone(timezone.utc).isoformat(),
            "timeZone": "UTC",
        },
        "availabilityViewInterval": time_interval,
    }

    # Make API request
    result = graph.request("POST", "/me/calendar/getSchedule", account_id, json=payload)
    if not result:
        raise ValueError("Failed to get free/busy information")

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
