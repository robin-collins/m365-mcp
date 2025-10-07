from typing import Any
from ..mcp_instance import mcp
from .. import graph
from ..validators import require_confirm


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
def calendar_get_event(event_id: str, account_id: str) -> dict[str, Any]:
    """📖 Get full event details (read-only, safe for unsupervised use)

    Returns complete event information including recurrence patterns and online meeting details.

    Args:
        event_id: The event ID
        account_id: Microsoft account ID

    Returns:
        Complete event object with all metadata
    """
    result = graph.request("GET", f"/me/events/{event_id}", account_id)
    if not result:
        raise ValueError(f"Event with ID {event_id} not found")
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
    Attendees will receive meeting invitations.

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
    """
    event = {
        "subject": subject,
        "start": {"dateTime": start, "timeZone": timezone},
        "end": {"dateTime": end, "timeZone": timezone},
    }

    if location:
        event["location"] = {"displayName": location}

    if body:
        event["body"] = {"contentType": "Text", "content": body}

    if attendees:
        attendees_list = [attendees] if isinstance(attendees, str) else attendees
        event["attendees"] = [
            {"emailAddress": {"address": a}, "type": "required"} for a in attendees_list
        ]

    result = graph.request("POST", "/me/events", account_id, json=event)
    if not result:
        raise ValueError("Failed to create event")
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

    Args:
        event_id: The event ID to update
        updates: Dictionary with fields to update (subject, start, end, location, body)
        account_id: Microsoft account ID

    Returns:
        Updated event object
    """
    formatted_updates = {}

    if "subject" in updates:
        formatted_updates["subject"] = updates["subject"]
    if "start" in updates:
        formatted_updates["start"] = {
            "dateTime": updates["start"],
            "timeZone": updates.get("timezone", "UTC"),
        }
    if "end" in updates:
        formatted_updates["end"] = {
            "dateTime": updates["end"],
            "timeZone": updates.get("timezone", "UTC"),
        }
    if "location" in updates:
        formatted_updates["location"] = {"displayName": updates["location"]}
    if "body" in updates:
        formatted_updates["body"] = {"contentType": "Text", "content": updates["body"]}

    result = graph.request(
        "PATCH", f"/me/events/{event_id}", account_id, json=formatted_updates
    )
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

    Args:
        account_id: Microsoft account ID
        event_id: The event ID to respond to
        response: Response type (default: "accept")
        message: Optional message to the organizer

    Returns:
        Status confirmation
    """
    payload: dict[str, Any] = {"sendResponse": True}
    if message:
        payload["comment"] = message

    graph.request("POST", f"/me/events/{event_id}/{response}", account_id, json=payload)
    return {"status": response}


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
    """
    me_info = graph.request("GET", "/me", account_id)
    if not me_info or "mail" not in me_info:
        raise ValueError("Failed to get user email address")
    schedules = [me_info["mail"]]
    if attendees:
        attendees_list = [attendees] if isinstance(attendees, str) else attendees
        schedules.extend(attendees_list)

    payload = {
        "schedules": schedules,
        "startTime": {"dateTime": start, "timeZone": "UTC"},
        "endTime": {"dateTime": end, "timeZone": "UTC"},
        "availabilityViewInterval": 30,
    }

    result = graph.request("POST", "/me/calendar/getSchedule", account_id, json=payload)
    if not result:
        raise ValueError("Failed to check availability")
    return result
