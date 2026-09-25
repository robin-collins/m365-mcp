"""Calendar service: Microsoft Graph logic for events and calendars.

Callers are expected to validate inputs first; these functions build the
Graph requests, handle caching and return the Graph results.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
