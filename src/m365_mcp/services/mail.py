"""Mail service: Microsoft Graph logic for Outlook messages.

Functions here take already-validated inputs from the MCP tool layer and
own the Graph endpoints, request bodies, caching and cache invalidation.
"""

from __future__ import annotations

import base64
from typing import Any

from .. import graph
from ..validators import (
    ValidationError,
)

MAX_ATTACHMENT_DOWNLOAD_BYTES = 25 * 1024 * 1024


# ----------------------------------------------------------------------
# Unified tool surface (m365_* and email_folder_* tools)
# ----------------------------------------------------------------------

_SUMMARY_SELECT = (
    "id,conversationId,subject,from,toRecipients,ccRecipients,"
    "receivedDateTime,isRead,hasAttachments,importance,flag,categories,"
    "bodyPreview,parentFolderId"
)
_DETAIL_EXPAND = "attachments($select=id,name,size,contentType,isInline)"
_TEXT_BODY = {"Prefer": 'outlook.body-content-type="text"'}
_FILE_ATTACHMENT = "#microsoft.graph.fileAttachment"
_ID_PAGE_SIZE = 1000


def _relative(next_link: str) -> str:
    """Return a Graph nextLink relative to the API version root."""
    return next_link.replace(graph.BASE_URL, "")


def list_messages_page(
    account_id: str,
    *,
    folder_id: str,
    top: int,
    filter_expr: str | None = None,
    next_link: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Fetch one newest-first page of message summaries from a folder.

    Args:
        account_id: Microsoft account identifier.
        folder_id: Mail folder ID or Graph well-known name.
        top: Page size.
        filter_expr: OData ``$filter``; its first clause must be on
            ``receivedDateTime`` (the ``$orderby`` property).
        next_link: Graph ``@odata.nextLink`` of a previous page; when set,
            the other query arguments are ignored.

    Returns:
        The Graph messages of the page and the next page's link, if any.
    """
    if next_link:
        result = graph.request("GET", _relative(next_link), account_id)
    else:
        params: dict[str, Any] = {
            "$select": _SUMMARY_SELECT,
            "$orderby": "receivedDateTime desc",
            "$top": top,
        }
        if filter_expr:
            params["$filter"] = filter_expr
        result = graph.request(
            "GET", f"/me/mailFolders/{folder_id}/messages", account_id, params=params
        )
    result = result or {}
    return list(result.get("value", [])), result.get("@odata.nextLink")


def get_message_detail(account_id: str, *, message_id: str) -> dict[str, Any]:
    """Get a message with its plain-text body and attachment metadata.

    Args:
        account_id: Microsoft account identifier.
        message_id: Graph message identifier.

    Returns:
        The Graph message, with ``attachments`` expanded (no content).
    """
    return (
        graph.request(
            "GET",
            f"/me/messages/{message_id}",
            account_id,
            params={"$expand": _DETAIL_EXPAND},
            headers=_TEXT_BODY,
        )
        or {}
    )


def get_message_categories(account_id: str, *, message_id: str) -> list[str]:
    """Return a message's current categories.

    Args:
        account_id: Microsoft account identifier.
        message_id: Graph message identifier.

    Returns:
        The category names, in Graph order.
    """
    result = graph.request(
        "GET",
        f"/me/messages/{message_id}",
        account_id,
        params={"$select": "categories"},
    )
    return list((result or {}).get("categories") or [])


def patch_message(
    account_id: str, *, message_id: str, changes: dict[str, Any]
) -> dict[str, Any]:
    """Apply a Graph message PATCH body.

    Args:
        account_id: Microsoft account identifier.
        message_id: Graph message identifier.
        changes: Graph ``message`` properties to set.

    Returns:
        The updated Graph message (empty if Graph returned no body).
    """
    return (
        graph.request("PATCH", f"/me/messages/{message_id}", account_id, json=changes)
        or {}
    )


def move_message_to(
    account_id: str, *, message_id: str, destination_id: str
) -> dict[str, Any]:
    """Move a message; Graph gives the moved message a new ID.

    Args:
        account_id: Microsoft account identifier.
        message_id: Graph message identifier.
        destination_id: Mail folder ID or Graph well-known name.

    Returns:
        The moved Graph message (with its new ``id``).

    Raises:
        ValueError: If Graph returns no message ID.
    """
    result = graph.request(
        "POST",
        f"/me/messages/{message_id}/move",
        account_id,
        json={"destinationId": destination_id},
    )
    if not result or "id" not in result:
        raise ValueError("Graph did not return the moved email's new ID")
    return result


def remove_message(account_id: str, *, message_id: str) -> None:
    """Delete a message (``DELETE /me/messages/{id}``).

    Args:
        account_id: Microsoft account identifier.
        message_id: Graph message identifier.
    """
    graph.request("DELETE", f"/me/messages/{message_id}", account_id)


def get_file_attachment(
    account_id: str,
    *,
    message_id: str,
    attachment_id: str,
    max_bytes: int = MAX_ATTACHMENT_DOWNLOAD_BYTES,
) -> tuple[dict[str, Any], bytes]:
    """Download one file attachment's metadata and content.

    Args:
        account_id: Microsoft account identifier.
        message_id: Graph message identifier.
        attachment_id: Attachment identifier.
        max_bytes: Largest attachment accepted.

    Returns:
        The Graph attachment (without ``contentBytes``) and its content.

    Raises:
        ValidationError: If it is not a file attachment or is too large.
    """
    result = (
        graph.request(
            "GET",
            f"/me/messages/{message_id}/attachments/{attachment_id}",
            account_id,
        )
        or {}
    )
    kind = result.get("@odata.type")
    if (kind is not None and kind != _FILE_ATTACHMENT) or "contentBytes" not in result:
        raise ValidationError(
            "Invalid attachment_id: not a file attachment. Expected: a file attachment"
        )
    limit_mb = max_bytes // (1024 * 1024)
    too_large = ValidationError(
        f"Invalid attachment_id: attachment is larger than {limit_mb} MB. "
        f"Expected: an attachment of at most {limit_mb} MB"
    )
    if int(result.get("size") or 0) > max_bytes:
        raise too_large
    content = base64.b64decode(result.pop("contentBytes"))
    if len(content) > max_bytes:
        raise too_large
    return result, content


def list_message_ids(
    account_id: str, *, folder_id: str, max_items: int, unread_only: bool
) -> tuple[list[str], int | None]:
    """Page the IDs of messages in a folder, up to ``max_items``.

    Args:
        account_id: Microsoft account identifier.
        folder_id: Mail folder ID or Graph well-known name.
        max_items: Most IDs to return.
        unread_only: Only unread messages (``isRead eq false``).

    Returns:
        The IDs and Graph's total count of matching messages
        (``@odata.count``), or ``None`` if Graph did not report it.
    """
    params: dict[str, Any] = {
        "$select": "id",
        "$top": min(max_items, _ID_PAGE_SIZE),
        "$count": "true",
    }
    if unread_only:
        params["$filter"] = "isRead eq false"
    result = graph.request(
        "GET", f"/me/mailFolders/{folder_id}/messages", account_id, params=params
    )
    total = (result or {}).get("@odata.count")
    ids: list[str] = []
    while result:
        for message in result.get("value", []):
            if len(ids) >= max_items:
                return ids, total
            ids.append(message["id"])
        next_link = result.get("@odata.nextLink")
        if not next_link or len(ids) >= max_items:
            break
        result = graph.request("GET", _relative(next_link), account_id)
    return ids, total


def _batch_count(
    account_id: str, method: str, ids: list[str], body: dict[str, Any] | None
) -> int:
    """Run one request per message through ``$batch``; count successes."""
    requests: list[dict[str, Any]] = []
    for message_id in ids:
        item: dict[str, Any] = {"method": method, "url": f"/me/messages/{message_id}"}
        if body is not None:
            item["body"] = body
        requests.append(item)
    if not requests:
        return 0
    results = graph.batch(requests, account_id)
    return sum(1 for result in results if 200 <= result["status"] < 300)


def mark_messages_read(account_id: str, *, message_ids: list[str]) -> int:
    """Mark messages read with batched PATCH requests (20 per batch).

    Args:
        account_id: Microsoft account identifier.
        message_ids: Graph message identifiers.

    Returns:
        How many messages Graph confirmed as changed.
    """
    return _batch_count(account_id, "PATCH", message_ids, {"isRead": True})


def delete_messages(account_id: str, *, message_ids: list[str]) -> int:
    """Delete messages with batched DELETE requests (20 per batch).

    Args:
        account_id: Microsoft account identifier.
        message_ids: Graph message identifiers.

    Returns:
        How many messages Graph confirmed as deleted.
    """
    return _batch_count(account_id, "DELETE", message_ids, None)
