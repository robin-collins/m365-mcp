from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .. import graph
from ..mcp_instance import mcp
from .cache_tools import get_cache_manager
from ..validators import (
    ValidationError,
    format_validation_error,
    normalize_recipients,
    require_confirm,
    validate_choices,
    validate_datetime_window,
    validate_iso_datetime,
    validate_json_payload,
    validate_limit,
    validate_timezone,
)

MAX_CALENDAR_ATTENDEES = 500
CALENDAR_RESPONSE_ALIASES = {
    "accept": "accept",
    "decline": "decline",
    "tentativelyAccept": "tentativelyAccept",
    "tentative": "tentativelyAccept",
}
ALLOWED_CALENDAR_UPDATE_KEYS = (
    "subject",
    "start",
    "end",
    "timezone",
    "location",
    "body",
    "attendees",
)


# calendar_list_events
@mcp.tool(
    name="calendar_list_events",
    annotations={
        "title": "List Calendar Events",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "calendar", "safety_level": "safe"},
)
def calendar_list_events(
    account_id: str,
    days_ahead: int = 7,
    include_details: bool = False,
    limit: int = 50,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """📖 List upcoming calendar events (read-only, safe for unsupervised use)

    Returns calendar events from now until the specified number of days ahead.

    Caching: Results are cached for 5 minutes (fresh) / 30 minutes (stale).
    Use force_refresh=True to bypass cache and fetch fresh data.

    Args:
        account_id: Microsoft account ID
        days_ahead: Number of days ahead to look for events (1-365, default: 7)
        include_details: Include full event details like attendees and body (default: False)
        limit: Maximum events to return (1-200, default: 50)
        use_cache: Whether to use cached data if available (default: True)
        force_refresh: Force refresh from API, bypassing cache (default: False)

    Returns:
        List of calendar events with metadata.
        Each event includes _cache_status and _cached_at fields.
    """
    # Validate parameters
    if not isinstance(days_ahead, int) or days_ahead < 1 or days_ahead > 365:
        reason = "must be between 1 and 365"
        raise ValidationError(
            format_validation_error("days_ahead", days_ahead, reason, "1-365")
        )

    limit = validate_limit(limit, 1, 200, "limit")

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
            cache_manager = get_cache_manager()
            cached_result = cache_manager.get_cached(account_id, "calendar_list_events", cache_params)

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
            cache_manager = get_cache_manager()
            cache_manager.set_cached(account_id, "calendar_list_events", cache_params, events)
        except Exception:
            # If cache storage fails, still return the result
            pass

    return events


# calendar_get_event
@mcp.tool(
    name="calendar_get_event",
    annotations={
        "title": "Get Calendar Event",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "calendar", "safety_level": "safe"},
)
def calendar_get_event(
    event_id: str,
    account_id: str,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """📖 Get full event details (read-only, safe for unsupervised use)

    Returns complete event information including recurrence patterns and online meeting details.

    Args:
        event_id: The event ID
        account_id: Microsoft account ID
        use_cache: Whether to use cache (default: True)
        force_refresh: Bypass cache and fetch fresh data (default: False)

    Returns:
        Complete event object with all metadata
    """
    # Build cache parameters
    cache_params = {"event_id": event_id}

    # Check cache if enabled
    if use_cache and not force_refresh:
        try:
            cache_manager = get_cache_manager()
            cached_result = cache_manager.get_cached(account_id, "calendar_get_event", cache_params)

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
            cache_manager = get_cache_manager()
            cache_manager.set_cached(account_id, "calendar_get_event", cache_params, result)
        except Exception:
            # If cache storage fails, still return the result
            pass

    return result


# calendar_create_event
@mcp.tool(
    name="calendar_create_event",
    annotations={
        "title": "Create Calendar Event",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    meta={"category": "calendar", "safety_level": "moderate"},
)
def calendar_create_event(
    account_id: str,
    subject: str,
    start: str,
    end: str,
    location: str | None = None,
    body: str | None = None,
    attendees: str | list[str] | None = None,
    timezone: str = "UTC",
) -> dict[str, Any]:
    """✏️ Create a calendar event (requires user confirmation recommended)

    Creates a new calendar event with optional attendees and location.
    Attendees will receive meeting invitations. Addresses are validated,
    deduplicated, and limited to 500 unique recipients.

    Args:
        account_id: Microsoft account ID
        subject: Event title
        start: Start time in ISO format (e.g., "2024-01-15T10:00:00")
        end: End time in ISO format
        location: Location name (optional)
        body: Event description (optional)
        attendees: Email address(es) of attendees (optional)
        timezone: Timezone for the event (default: "UTC")

    Returns:
        Created event object with ID

    Raises:
        ValidationError: If datetime values, timezone, or attendee
            addresses are invalid.
    """
    start_dt, end_dt = validate_datetime_window(start, end)
    timezone_normalized = validate_timezone(timezone)
    tzinfo = ZoneInfo(timezone_normalized)
    start_local = start_dt.astimezone(tzinfo)
    end_local = end_dt.astimezone(tzinfo)

    attendees_deduped: list[str] = []
    if attendees:
        attendee_candidates = normalize_recipients(attendees, "attendees")
        seen: set[str] = set()
        for address in attendee_candidates:
            key = address.casefold()
            if key in seen:
                continue
            seen.add(key)
            attendees_deduped.append(address)
        if len(attendees_deduped) > MAX_CALENDAR_ATTENDEES:
            reason = (
                f"must not exceed {MAX_CALENDAR_ATTENDEES} unique attendees per event"
            )
            raise ValidationError(
                format_validation_error(
                    "attendees",
                    len(attendees_deduped),
                    reason,
                    f"≤ {MAX_CALENDAR_ATTENDEES}",
                )
            )

    event = {
        "subject": subject,
        "start": {
            "dateTime": start_local.isoformat(),
            "timeZone": timezone_normalized,
        },
        "end": {
            "dateTime": end_local.isoformat(),
            "timeZone": timezone_normalized,
        },
    }

    if location:
        event["location"] = {"displayName": location}

    if body:
        event["body"] = {"contentType": "Text", "content": body}

    if attendees_deduped:
        event["attendees"] = [
            {"emailAddress": {"address": address}, "type": "required"}
            for address in attendees_deduped
        ]

    result = graph.request("POST", "/me/events", account_id, json=event)
    if not result:
        raise ValueError("Failed to create event")

    # Note: Cache invalidation for calendar events happens automatically via TTL
    # No manual invalidation needed as calendar list caches are short-lived (5min)

    return result


# calendar_update_event
@mcp.tool(
    name="calendar_update_event",
    annotations={
        "title": "Update Calendar Event",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "calendar", "safety_level": "moderate"},
)
def calendar_update_event(
    event_id: str, updates: dict[str, Any], account_id: str
) -> dict[str, Any]:
    """✏️ Update event properties (requires user confirmation recommended)

    Modifies event details like time, location, or attendees.
    Attendees will receive update notifications.

    Allowed update keys: subject, start, end, timezone, location, body, attendees.

    Args:
        event_id: The event ID to update
        updates: Dictionary with fields to update (subject, start, end, location, body)
        account_id: Microsoft account ID

    Returns:
        Updated event object
    """
    payload = validate_json_payload(
        updates,
        allowed_keys=ALLOWED_CALENDAR_UPDATE_KEYS,
        param_name="updates",
    )
    if not payload:
        raise ValidationError(
            format_validation_error(
                "updates",
                payload,
                "must include at least one field",
                f"Subset of {sorted(ALLOWED_CALENDAR_UPDATE_KEYS)}",
            )
        )

    timezone_override: str | None = None
    if "timezone" in payload:
        timezone_override = validate_timezone(payload["timezone"], "updates.timezone")
        if "start" not in payload and "end" not in payload:
            raise ValidationError(
                format_validation_error(
                    "updates.timezone",
                    payload["timezone"],
                    "can only be provided when updating start or end",
                    "Include start/end alongside timezone",
                )
            )

    start_value: str | None = None
    end_value: str | None = None

    if "start" in payload:
        start_raw = payload["start"]
        if not isinstance(start_raw, str):
            raise ValidationError(
                format_validation_error(
                    "updates.start",
                    start_raw,
                    "must be an ISO-8601 datetime string",
                    "YYYY-MM-DDTHH:MM:SS+TZ",
                )
            )
        validate_iso_datetime(start_raw, "updates.start")
        start_value = start_raw

    if "end" in payload:
        end_raw = payload["end"]
        if not isinstance(end_raw, str):
            raise ValidationError(
                format_validation_error(
                    "updates.end",
                    end_raw,
                    "must be an ISO-8601 datetime string",
                    "YYYY-MM-DDTHH:MM:SS+TZ",
                )
            )
        validate_iso_datetime(end_raw, "updates.end")
        end_value = end_raw

    if start_value and end_value:
        validate_datetime_window(start_value, end_value)

    formatted_updates: dict[str, Any] = {}

    if "subject" in payload:
        subject_value = payload["subject"]
        if not isinstance(subject_value, str):
            raise ValidationError(
                format_validation_error(
                    "updates.subject",
                    subject_value,
                    "must be a string",
                    "Subject string",
                )
            )
        formatted_updates["subject"] = subject_value

    timezone_for_dates = timezone_override or "UTC"

    if start_value is not None:
        formatted_updates["start"] = {
            "dateTime": start_value,
            "timeZone": timezone_for_dates,
        }

    if end_value is not None:
        formatted_updates["end"] = {
            "dateTime": end_value,
            "timeZone": timezone_for_dates,
        }

    if "location" in payload:
        location_value = payload["location"]
        if not isinstance(location_value, str):
            raise ValidationError(
                format_validation_error(
                    "updates.location",
                    location_value,
                    "must be a string",
                    "Location name string",
                )
            )
        formatted_updates["location"] = {"displayName": location_value.strip()}

    if "body" in payload:
        body_value = payload["body"]
        if not isinstance(body_value, str):
            raise ValidationError(
                format_validation_error(
                    "updates.body",
                    body_value,
                    "must be a string",
                    "Event description string",
                )
            )
        formatted_updates["body"] = {"contentType": "Text", "content": body_value}

    if "attendees" in payload:
        attendees_value = payload["attendees"]
        if isinstance(attendees_value, list) and not attendees_value:
            formatted_updates["attendees"] = []
        else:
            attendee_candidates = normalize_recipients(
                attendees_value,
                "updates.attendees",
            )
            deduped: list[str] = []
            seen: set[str] = set()
            for address in attendee_candidates:
                key = address.casefold()
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(address)
            if len(deduped) > MAX_CALENDAR_ATTENDEES:
                raise ValidationError(
                    format_validation_error(
                        "updates.attendees",
                        len(deduped),
                        f"must not exceed {MAX_CALENDAR_ATTENDEES} attendees",
                        f"≤ {MAX_CALENDAR_ATTENDEES}",
                    )
                )
            formatted_updates["attendees"] = [
                {"emailAddress": {"address": address}, "type": "required"}
                for address in deduped
            ]

    result = graph.request(
        "PATCH", f"/me/events/{event_id}", account_id, json=formatted_updates
    )

    # Note: Cache invalidation happens automatically via TTL (5min for calendar_list_events)

    return result or {"status": "updated"}


# calendar_delete_event
@mcp.tool(
    name="calendar_delete_event",
    annotations={
        "title": "Delete Calendar Event",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={
        "category": "calendar",
        "safety_level": "critical",
        "requires_confirmation": True,
    },
)
def calendar_delete_event(
    account_id: str,
    event_id: str,
    send_cancellation: bool = True,
    confirm: bool = False,
) -> dict[str, str]:
    """🔴 Delete a calendar event (always require user confirmation)

    WARNING: This action permanently deletes the event and cannot be undone.
    If this is a meeting, attendees will receive cancellation notices.

    Args:
        account_id: Microsoft account ID
        event_id: The event to delete
        send_cancellation: Whether to notify attendees (default: True)
        confirm: Must be True to confirm deletion (prevents accidents)

    Returns:
        Status confirmation
    """
    require_confirm(confirm, "delete calendar event")
    if send_cancellation:
        graph.request("POST", f"/me/events/{event_id}/cancel", account_id, json={})
    else:
        graph.request("DELETE", f"/me/events/{event_id}", account_id)

    # Note: Cache invalidation happens automatically via TTL (5min for calendar_list_events)

    return {"status": "deleted"}


# calendar_respond_event
@mcp.tool(
    name="calendar_respond_event",
    annotations={
        "title": "Respond to Calendar Event",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "calendar", "safety_level": "moderate"},
)
def calendar_respond_event(
    account_id: str,
    event_id: str,
    response: str = "accept",
    message: str | None = None,
) -> dict[str, str]:
    """⚠️ Respond to a calendar event invitation (requires user confirmation recommended)

    IMPORTANT: This sends a response to the event organizer.

    Valid responses:
        - "accept" - Accept the invitation
        - "decline" - Decline the invitation
        - "tentativelyAccept" - Mark as tentative
      (Input is case-insensitive; "tentative" is accepted as an alias.)

    Args:
        account_id: Microsoft account ID
        event_id: The event ID to respond to
        response: Response type (default: "accept")
        message: Optional message to the organizer

    Returns:
        Status confirmation

    Raises:
        ValidationError: If the response value or message payload is invalid.
    """
    canonical_key = validate_choices(
        response,
        CALENDAR_RESPONSE_ALIASES.keys(),
        "response",
    )
    resolved_response = CALENDAR_RESPONSE_ALIASES[canonical_key]

    payload: dict[str, Any] = {"sendResponse": True}

    if message is not None:
        if not isinstance(message, str):
            reason = "must be a string"
            raise ValidationError(
                format_validation_error(
                    "message",
                    message,
                    reason,
                    "Non-empty response message or omit parameter",
                )
            )
        message_trimmed = message.strip()
        if not message_trimmed:
            reason = "cannot be empty when provided"
            raise ValidationError(
                format_validation_error(
                    "message",
                    message,
                    reason,
                    "Non-empty response message or omit parameter",
                )
            )
        payload["comment"] = message_trimmed

    graph.request(
        "POST",
        f"/me/events/{event_id}/{resolved_response}",
        account_id,
        json=payload,
    )
    return {"status": resolved_response}


# calendar_check_availability
@mcp.tool(
    name="calendar_check_availability",
    annotations={
        "title": "Check Calendar Availability",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "calendar", "safety_level": "safe"},
)
def calendar_check_availability(
    account_id: str,
    start: str,
    end: str,
    attendees: str | list[str] | None = None,
) -> dict[str, Any]:
    """📖 Check calendar availability for scheduling (read-only, safe for unsupervised use)

    Returns free/busy information for the user and optional attendees.
    Useful for finding meeting times.

    Args:
        account_id: Microsoft account ID
        start: Start time in ISO format
        end: End time in ISO format
        attendees: Optional email address(es) to check availability

    Returns:
        Schedule information with free/busy slots

    Raises:
        ValidationError: If start/end datetimes or attendee addresses
            are invalid.
        ValueError: If the current account email address is unavailable.
    """
    start_dt, end_dt = validate_datetime_window(start, end)

    attendee_addresses: list[str] = []
    if attendees:
        attendee_candidates = normalize_recipients(attendees, "attendees")
        seen_attendees: set[str] = set()
        for address in attendee_candidates:
            key = address.casefold()
            if key in seen_attendees:
                continue
            seen_attendees.add(key)
            attendee_addresses.append(address)
        if len(attendee_addresses) > MAX_CALENDAR_ATTENDEES:
            reason = (
                f"must not exceed {MAX_CALENDAR_ATTENDEES} unique attendees per request"
            )
            raise ValidationError(
                format_validation_error(
                    "attendees",
                    len(attendee_addresses),
                    reason,
                    f"≤ {MAX_CALENDAR_ATTENDEES}",
                )
            )

    me_info = graph.request("GET", "/me", account_id)
    if not me_info or "mail" not in me_info or not me_info["mail"]:
        raise ValueError("Failed to get user email address")
    schedules = [me_info["mail"]]
    current_keys = {me_info["mail"].casefold()}
    for address in attendee_addresses:
        key = address.casefold()
        if key in current_keys:
            continue
        current_keys.add(key)
        schedules.append(address)

    payload = {
        "schedules": schedules,
        "startTime": {
            "dateTime": start_dt.astimezone(timezone.utc).isoformat(),
            "timeZone": "UTC",
        },
        "endTime": {
            "dateTime": end_dt.astimezone(timezone.utc).isoformat(),
            "timeZone": "UTC",
        },
        "availabilityViewInterval": 30,
    }

    result = graph.request("POST", "/me/calendar/getSchedule", account_id, json=payload)
    if not result:
        raise ValueError("Failed to check availability")
    return result
