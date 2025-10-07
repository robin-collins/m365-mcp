import datetime as dt
from typing import Any
from ..mcp_instance import mcp
from .. import graph

# Common constants (using from email.py as they are consistent across files)
from .email import FOLDERS


# search_files
@mcp.tool(
    name="search_files",
    annotations={
        "title": "Search Files",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "search", "safety_level": "safe"},
)
def search_files(
    query: str,
    account_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """📖 Search for files in OneDrive (read-only, safe for unsupervised use)

    Searches file names and content across all accessible OneDrive folders.

    Args:
        query: Search query string
        account_id: Microsoft account ID
        limit: Maximum results to return (default: 50)

    Returns:
        List of matching files with metadata
    """
    items = list(graph.search_query(query, ["driveItem"], account_id, limit))

    return [
        {
            "id": item["id"],
            "name": item["name"],
            "type": "folder" if "folder" in item else "file",
            "size": item.get("size", 0),
            "modified": item.get("lastModifiedDateTime"),
            "download_url": item.get("@microsoft.graph.downloadUrl"),
        }
        for item in items
    ]


# search_emails
@mcp.tool(
    name="search_emails",
    annotations={
        "title": "Search Emails",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "search", "safety_level": "safe"},
)
def search_emails(
    query: str,
    account_id: str,
    limit: int = 50,
    folder: str | None = None,
) -> list[dict[str, Any]]:
    """📖 Search emails across mailbox (read-only, safe for unsupervised use)

    Searches email subject, body, and sender across all or specific folders.

    Args:
        query: Search query string
        account_id: Microsoft account ID
        limit: Maximum results to return (default: 50)
        folder: Optional folder to search within (e.g., "inbox", "sent")

    Returns:
        List of matching emails with metadata
    """
    if folder:
        # For folder-specific search, use the traditional endpoint
        folder_path = FOLDERS.get(folder.casefold(), folder)
        endpoint = f"/me/mailFolders/{folder_path}/messages"

        params = {
            "$search": f'"{query}"',
            "$top": min(limit, 100),
            "$select": "id,subject,from,toRecipients,receivedDateTime,hasAttachments,body,conversationId,isRead",
        }

        return list(
            graph.request_paginated(endpoint, account_id, params=params, limit=limit)
        )

    return list(graph.search_query(query, ["message"], account_id, limit))


# search_events
@mcp.tool(
    name="search_events",
    annotations={
        "title": "Search Events",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "search", "safety_level": "safe"},
)
def search_events(
    query: str,
    account_id: str,
    days_ahead: int = 365,
    days_back: int = 365,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """📖 Search calendar events (read-only, safe for unsupervised use)

    Searches event titles, locations, and descriptions within date range.

    Args:
        query: Search query string
        account_id: Microsoft account ID
        days_ahead: Days to look forward (default: 365)
        days_back: Days to look back (default: 365)
        limit: Maximum results to return (default: 50)

    Returns:
        List of matching events
    """
    events = list(graph.search_query(query, ["event"], account_id, limit))

    # Filter by date range if needed
    if days_ahead != 365 or days_back != 365:
        now = dt.datetime.now(dt.timezone.utc)
        start = now - dt.timedelta(days=days_back)
        end = now + dt.timedelta(days=days_ahead)

        filtered_events = []
        for event in events:
            event_start = dt.datetime.fromisoformat(
                event.get("start", {}).get("dateTime", "").replace("Z", "+00:00")
            )
            event_end = dt.datetime.fromisoformat(
                event.get("end", {}).get("dateTime", "").replace("Z", "+00:00")
            )

            if event_start <= end and event_end >= start:
                filtered_events.append(event)

        return filtered_events

    return events


# search_contacts
@mcp.tool(
    name="search_contacts",
    annotations={
        "title": "Search Contacts",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "search", "safety_level": "safe"},
)
def search_contacts(
    query: str,
    account_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """📖 Search contacts (read-only, safe for unsupervised use)

    Searches contact names, email addresses, and phone numbers.

    Args:
        query: Search query string
        account_id: Microsoft account ID
        limit: Maximum results to return (default: 50)

    Returns:
        List of matching contacts
    """
    params = {
        "$search": f'"{query}"',
        "$top": min(limit, 100),
    }

    contacts = list(
        graph.request_paginated("/me/contacts", account_id, params=params, limit=limit)
    )

    return contacts


# search_unified
@mcp.tool(
    name="search_unified",
    annotations={
        "title": "Unified Search",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "search", "safety_level": "safe"},
)
def search_unified(
    query: str,
    account_id: str,
    entity_types: list[str] | None = None,
    limit: int = 50,
) -> dict[str, list[dict[str, Any]]]:
    """📖 Search across multiple Microsoft 365 resources (read-only, safe for unsupervised use)

    Searches emails, events, and files simultaneously.

    Args:
        query: Search query string
        account_id: Microsoft account ID
        entity_types: Types to search: 'message', 'event', 'driveItem' (default: all)
        limit: Maximum results per type (default: 50)

    Returns:
        Dictionary with results grouped by entity type
    """
    if not entity_types:
        entity_types = ["message", "event", "driveItem"]

    results = {entity_type: [] for entity_type in entity_types}

    items = list(graph.search_query(query, entity_types, account_id, limit))

    for item in items:
        resource_type = item.get("@odata.type", "").split(".")[-1]

        if resource_type == "message":
            results.setdefault("message", []).append(item)
        elif resource_type == "event":
            results.setdefault("event", []).append(item)
        elif resource_type in ["driveItem", "file", "folder"]:
            results.setdefault("driveItem", []).append(item)
        else:
            results.setdefault("other", []).append(item)

    return {k: v for k, v in results.items() if v}
