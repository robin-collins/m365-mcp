"""Mail service: Microsoft Graph logic for Outlook messages.

Functions here take already-validated inputs from the MCP tool layer and
own the Graph endpoints, request bodies, caching and cache invalidation.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import graph
from ..validators import (
    ValidationError,
    format_validation_error,
    validate_request_size,
)

if TYPE_CHECKING:
    from ..cache import CacheManager

LOGGER = logging.getLogger("microsoft_mcp.tools.email")

FOLDERS = {
    k.casefold(): v
    for k, v in {
        "inbox": "inbox",
        "sent": "sentitems",
        "drafts": "drafts",
        "deleted": "deleteditems",
        "junk": "junkemail",
        "archive": "archive",
    }.items()
}
EMAIL_FOLDER_NAMES = tuple(FOLDERS.keys())

MAX_ATTACHMENT_DOWNLOAD_BYTES = 25 * 1024 * 1024
MAIL_INLINE_ATTACHMENT_THRESHOLD = 3 * 1024 * 1024

_LIST_SELECT_WITH_BODY = (
    "id,subject,from,toRecipients,ccRecipients,receivedDateTime,"
    "hasAttachments,body,conversationId,isRead"
)
_LIST_SELECT_WITHOUT_BODY = (
    "id,subject,from,toRecipients,receivedDateTime,hasAttachments,conversationId,isRead"
)


def get_cache_manager() -> CacheManager:
    """Return the process-wide cache manager.

    The singleton currently lives in ``tools.cache_tools``; it is imported
    lazily so this module does not import the tool layer at load time.

    Returns:
        The shared cache manager instance.
    """
    from ..cache import get_cache_manager as _get_cache_manager

    return _get_cache_manager()


def _invalidate(account_id: str, *patterns: str) -> None:
    """Invalidate cache patterns for an account, ignoring cache failures."""
    try:
        cache_manager = get_cache_manager()
        for pattern in patterns:
            cache_manager.invalidate_pattern(pattern, account_id=account_id)
    except Exception:
        # Don't fail the operation if cache invalidation fails
        LOGGER.debug("Cache invalidation failed", exc_info=True)


def _recipients(addresses: list[str]) -> list[dict[str, Any]]:
    """Build Graph recipient objects from email addresses."""
    return [{"emailAddress": {"address": addr}} for addr in addresses]


def _file_attachment(attachment: dict[str, Any]) -> dict[str, Any]:
    """Build an inline Graph fileAttachment from a prepared attachment."""
    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": attachment["name"],
        "contentBytes": base64.b64encode(attachment["content_bytes"]).decode("utf-8"),
    }


def _build_message(
    to: list[str], cc: list[str], subject: str, body: str
) -> dict[str, Any]:
    """Build a plain-text Graph message payload."""
    message: dict[str, Any] = {
        "subject": subject,
        "body": {"contentType": "Text", "content": body},
        "toRecipients": _recipients(to),
    }
    if cc:
        message["ccRecipients"] = _recipients(cc)
    return message


def _upload_large_attachment(
    account_id: str, message_id: str, attachment: dict[str, Any]
) -> None:
    """Upload one large attachment to a draft through an upload session."""
    graph.upload_large_mail_attachment(
        message_id,
        attachment["name"],
        attachment["content_bytes"],
        account_id,
        attachment.get("content_type", "application/octet-stream"),
    )


def list_messages(
    account_id: str,
    *,
    folder: str | None,
    folder_id: str | None,
    folder_path: str,
    limit: int,
    include_body: bool,
    use_cache: bool,
    force_refresh: bool,
) -> list[dict[str, Any]]:
    """List messages in a mail folder, using the cache when allowed.

    Args:
        account_id: Microsoft account identifier.
        folder: Folder name as supplied by the caller (cache key only).
        folder_id: Folder ID as supplied by the caller (cache key only).
        folder_path: Resolved Graph folder ID or well-known name.
        limit: Maximum number of messages to return.
        include_body: Whether to select the message body.
        use_cache: Whether to read and write the cache.
        force_refresh: Whether to skip the cache read.

    Returns:
        Messages with ``_cache_status`` and, on a miss, ``_cached_at``.
    """
    cache_params = {
        "folder": folder,
        "folder_id": folder_id,
        "folder_path": folder_path,
        "limit": limit,
        "include_body": include_body,
    }

    if use_cache and not force_refresh:
        try:
            cache_manager = get_cache_manager()
            cached_result = cache_manager.get_cached(
                account_id, "email_list", cache_params
            )

            if cached_result:
                data, state = cached_result
                for email in data:
                    email["_cache_status"] = state.value
                return data
        except Exception:
            # If cache fails, continue to API call
            LOGGER.debug("Cache read failed", exc_info=True)

    params = {
        "$top": limit,
        "$select": (
            _LIST_SELECT_WITH_BODY if include_body else _LIST_SELECT_WITHOUT_BODY
        ),
        "$orderby": "receivedDateTime desc",
    }

    emails = list(
        graph.request_paginated(
            f"/me/mailFolders/{folder_path}/messages",
            account_id,
            params=params,
            limit=limit,
        )
    )

    cached_at = datetime.now(timezone.utc).isoformat()
    for email in emails:
        email["_cache_status"] = "miss"
        email["_cached_at"] = cached_at

    if use_cache:
        try:
            cache_manager = get_cache_manager()
            cache_manager.set_cached(account_id, "email_list", cache_params, emails)
        except Exception:
            # If cache storage fails, still return the result
            LOGGER.debug("Cache write failed", exc_info=True)

    return emails


def get_message(
    account_id: str,
    *,
    email_id: str,
    include_body: bool,
    body_max_length: int,
    include_attachments: bool,
    use_cache: bool,
    force_refresh: bool,
) -> dict[str, Any]:
    """Get one message, truncating the body and using the cache.

    Args:
        account_id: Microsoft account identifier.
        email_id: Graph message identifier.
        include_body: Whether to keep the body in the result.
        body_max_length: Maximum body characters before truncation.
        include_attachments: Whether to expand attachment metadata.
        use_cache: Whether to read and write the cache.
        force_refresh: Whether to skip the cache read.

    Returns:
        Message details with ``_cache_status`` and ``_cached_at``.

    Raises:
        ValueError: If Graph returns no message.
    """
    cache_params = {
        "email_id": email_id,
        "include_body": include_body,
        "body_max_length": body_max_length,
        "include_attachments": include_attachments,
    }

    if use_cache and not force_refresh:
        try:
            cache_manager = get_cache_manager()
            cached_result = cache_manager.get_cached(
                account_id, "email_get", cache_params
            )

            if cached_result:
                data, state = cached_result
                data["_cache_status"] = state.value
                return data
        except Exception:
            # If cache fails, continue to API call
            LOGGER.debug("Cache read failed", exc_info=True)

    params = {}
    if include_attachments:
        params["$expand"] = "attachments($select=id,name,size,contentType)"

    result = graph.request("GET", f"/me/messages/{email_id}", account_id, params=params)
    if not result:
        raise ValueError(f"Email with ID {email_id} not found")

    if include_body and "body" in result and "content" in result["body"]:
        content = result["body"]["content"]
        if len(content) > body_max_length:
            result["body"]["content"] = (
                content[:body_max_length]
                + f"\n\n[Content truncated - {len(content)} total characters]"
            )
            result["body"]["truncated"] = True
            result["body"]["total_length"] = len(content)
    elif not include_body and "body" in result:
        del result["body"]

    # Remove attachment content bytes to reduce size
    if "attachments" in result and result["attachments"]:
        for attachment in result["attachments"]:
            if "contentBytes" in attachment:
                del attachment["contentBytes"]

    result["_cache_status"] = "miss"
    result["_cached_at"] = datetime.now(timezone.utc).isoformat()

    if use_cache:
        try:
            cache_manager = get_cache_manager()
            cache_manager.set_cached(account_id, "email_get", cache_params, result)
        except Exception:
            # If cache storage fails, still return the result
            LOGGER.debug("Cache write failed", exc_info=True)

    return result


def create_draft(
    account_id: str,
    *,
    to: list[str],
    cc: list[str],
    subject: str,
    body: str,
    attachments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create a draft message, uploading large attachments separately.

    Args:
        account_id: Microsoft account identifier.
        to: Validated, deduplicated To addresses.
        cc: Validated, deduplicated CC addresses.
        subject: Message subject.
        body: Plain-text message body.
        attachments: Prepared attachments with ``name``, ``content_bytes``
            and ``size`` keys.

    Returns:
        The created draft message from Graph.

    Raises:
        ValueError: If Graph returns no draft.
    """
    message = _build_message(to, cc, subject, body)

    small_attachments = []
    large_attachments = []
    for attachment in attachments:
        if attachment["size"] < MAIL_INLINE_ATTACHMENT_THRESHOLD:
            small_attachments.append(_file_attachment(attachment))
        else:
            large_attachments.append(attachment)

    if small_attachments:
        message["attachments"] = small_attachments

    result = graph.request("POST", "/me/messages", account_id, json=message)
    if not result:
        raise ValueError("Failed to create email draft")

    message_id = result["id"]
    for attachment in large_attachments:
        _upload_large_attachment(account_id, message_id, attachment)

    return result


def send_message(
    account_id: str,
    *,
    to: list[str],
    cc: list[str],
    subject: str,
    body: str,
    attachments: list[dict[str, Any]],
) -> dict[str, str]:
    """Send a message, via a draft when any attachment is large.

    Args:
        account_id: Microsoft account identifier.
        to: Validated, deduplicated To addresses.
        cc: Validated, deduplicated CC addresses.
        subject: Message subject.
        body: Plain-text message body.
        attachments: Prepared attachments with ``name``, ``content_bytes``
            and ``size`` keys.

    Returns:
        ``{"status": "sent"}``.

    Raises:
        ValueError: If the draft for a large-attachment send is not created.
    """
    has_large_attachments = any(
        att["size"] >= MAIL_INLINE_ATTACHMENT_THRESHOLD for att in attachments
    )

    if has_large_attachments:
        # Create draft first, then add attachments, then send
        message = _build_message(to, cc, subject, body)
        result = graph.request("POST", "/me/messages", account_id, json=message)
        if not result:
            raise ValueError("Failed to create email draft")

        message_id = result["id"]
        for att in attachments:
            if att["size"] >= MAIL_INLINE_ATTACHMENT_THRESHOLD:
                _upload_large_attachment(account_id, message_id, att)
            else:
                graph.request(
                    "POST",
                    f"/me/messages/{message_id}/attachments",
                    account_id,
                    json=_file_attachment(att),
                )

        graph.request("POST", f"/me/messages/{message_id}/send", account_id)
    else:
        message = _build_message(to, cc, subject, body)
        if attachments:
            message["attachments"] = [_file_attachment(att) for att in attachments]
        graph.request("POST", "/me/sendMail", account_id, json={"message": message})

    # Invalidate cache for sent folder
    _invalidate(account_id, "email_list:*")
    return {"status": "sent"}


def _patch_message(
    account_id: str,
    email_id: str,
    payload: dict[str, Any],
    *invalidate_patterns: str,
) -> dict[str, Any]:
    """PATCH a message and invalidate the given cache patterns."""
    result = graph.request(
        "PATCH", f"/me/messages/{email_id}", account_id, json=payload
    )
    if not result:
        raise ValueError(f"Failed to update email {email_id} - no response")

    _invalidate(account_id, *invalidate_patterns)
    return result


def update_message(
    account_id: str, *, email_id: str, updates: dict[str, Any]
) -> dict[str, Any]:
    """Apply validated property updates to a message.

    Args:
        account_id: Microsoft account identifier.
        email_id: Graph message identifier.
        updates: Validated Graph message properties to PATCH.

    Returns:
        The updated message from Graph.

    Raises:
        ValueError: If Graph returns no response.
    """
    return _patch_message(account_id, email_id, updates, "email_get:*")


def mark_read(account_id: str, *, email_id: str, is_read: bool) -> dict[str, Any]:
    """Mark a message as read or unread.

    Args:
        account_id: Microsoft account identifier.
        email_id: Graph message identifier.
        is_read: New read state.

    Returns:
        The updated message from Graph.

    Raises:
        ValueError: If Graph returns no response.
    """
    return _patch_message(
        account_id,
        email_id,
        {"isRead": is_read},
        "email_get:*",
        "email_list:*",
    )


def set_flag(account_id: str, *, email_id: str, flag_status: str) -> dict[str, Any]:
    """Set the follow-up flag status of a message.

    Args:
        account_id: Microsoft account identifier.
        email_id: Graph message identifier.
        flag_status: Validated flag status.

    Returns:
        The updated message from Graph.

    Raises:
        ValueError: If Graph returns no response.
    """
    return _patch_message(
        account_id,
        email_id,
        {"flag": {"flagStatus": flag_status}},
        "email_get:*",
    )


def set_categories(
    account_id: str, *, email_id: str, categories: list[str]
) -> dict[str, Any]:
    """Replace the categories of a message.

    Args:
        account_id: Microsoft account identifier.
        email_id: Graph message identifier.
        categories: Validated, non-empty category names.

    Returns:
        The updated message from Graph.

    Raises:
        ValueError: If Graph returns no response.
    """
    return _patch_message(
        account_id,
        email_id,
        {"categories": categories},
        "email_get:*",
    )


def delete_message(account_id: str, *, email_id: str) -> dict[str, str]:
    """Permanently delete a message.

    Args:
        account_id: Microsoft account identifier.
        email_id: Graph message identifier.

    Returns:
        ``{"status": "deleted"}``.
    """
    graph.request("DELETE", f"/me/messages/{email_id}", account_id)
    _invalidate(account_id, "email_list:*", "email_get:*")
    return {"status": "deleted"}


def _find_folder_id(
    account_id: str, well_known_name: str, display_name: str
) -> str | None:
    """Find a top-level mail folder ID by well-known or display name."""
    folders = graph.request("GET", "/me/mailFolders", account_id)

    if not folders:
        raise ValueError("Failed to retrieve mail folders")
    if "value" not in folders:
        raise ValueError(f"Unexpected folder response structure: {folders}")

    for folder in folders["value"]:
        folder_display_name = folder.get("displayName", "")
        well_known = folder.get("wellKnownName", "")
        if (
            isinstance(well_known, str)
            and well_known.casefold() == well_known_name.casefold()
        ):
            return folder["id"]
        if (
            isinstance(folder_display_name, str)
            and folder_display_name.casefold() == display_name.casefold()
        ):
            return folder["id"]
    return None


def _move(account_id: str, email_id: str, folder_id: str, action: str) -> str:
    """Move a message to a folder and return its new ID."""
    payload = {"destinationId": folder_id}
    result = graph.request(
        "POST", f"/me/messages/{email_id}/move", account_id, json=payload
    )
    if not result:
        raise ValueError(f"Failed to {action} email - no response from server")
    if "id" not in result:
        raise ValueError(f"Failed to {action} email - unexpected response: {result}")

    # Invalidate cache for email lists (folder contents changed)
    _invalidate(account_id, "email_list:*")
    return result["id"]


def move_message(
    account_id: str,
    *,
    email_id: str,
    folder_key: str,
    destination_folder: str,
) -> dict[str, Any]:
    """Move a message to a well-known mail folder.

    Args:
        account_id: Microsoft account identifier.
        email_id: Graph message identifier.
        folder_key: Validated folder name, a key of ``FOLDERS``.
        destination_folder: Folder name as supplied by the caller, used in
            error messages.

    Returns:
        ``{"status": "moved", "new_id": ...}``.

    Raises:
        ValueError: If folders cannot be listed, the folder is not found,
            or the move returns no usable response.
    """
    folder_path = FOLDERS[folder_key.casefold()]
    folder_id = _find_folder_id(account_id, folder_path, folder_key)
    if not folder_id:
        raise ValueError(
            f"Folder '{destination_folder}' not found. "
            f"Valid options: {', '.join(sorted(EMAIL_FOLDER_NAMES))}"
        )

    new_id = _move(account_id, email_id, folder_id, "move")
    return {"status": "moved", "new_id": new_id}


def archive_message(account_id: str, *, email_id: str) -> dict[str, Any]:
    """Move a message to the Archive folder.

    Args:
        account_id: Microsoft account identifier.
        email_id: Graph message identifier.

    Returns:
        ``{"status": "archived", "new_id": ...}``.

    Raises:
        ValueError: If folders cannot be listed, no archive folder exists,
            or the move returns no usable response.
    """
    folder_id = _find_folder_id(account_id, FOLDERS["archive"], "archive")
    if not folder_id:
        raise ValueError(
            "Archive folder not found. This may indicate the account does not "
            "have an archive folder enabled."
        )

    new_id = _move(account_id, email_id, folder_id, "archive")
    return {"status": "archived", "new_id": new_id}


def _post_reply(account_id: str, endpoint: str, body: str) -> dict[str, str]:
    """POST a plain-text reply payload to a reply endpoint."""
    payload = {"message": {"body": {"contentType": "Text", "content": body}}}
    graph.request("POST", endpoint, account_id, json=payload)
    return {"status": "sent"}


def reply(account_id: str, *, email_id: str, body: str) -> dict[str, str]:
    """Reply to the sender of a message.

    Args:
        account_id: Microsoft account identifier.
        email_id: Graph message identifier.
        body: Validated, stripped plain-text reply body.

    Returns:
        ``{"status": "sent"}``.
    """
    return _post_reply(account_id, f"/me/messages/{email_id}/reply", body)


def reply_all(account_id: str, *, email_id: str, body: str) -> dict[str, str]:
    """Reply to all recipients of a message.

    Args:
        account_id: Microsoft account identifier.
        email_id: Graph message identifier.
        body: Validated, stripped plain-text reply body.

    Returns:
        ``{"status": "sent"}``.
    """
    return _post_reply(account_id, f"/me/messages/{email_id}/replyAll", body)


def forward_message(
    account_id: str,
    *,
    email_id: str,
    to: list[str],
    cc: list[str],
    body: str | None,
) -> dict[str, str]:
    """Forward a message with an optional comment.

    Args:
        account_id: Microsoft account identifier.
        email_id: Graph message identifier.
        to: Validated, deduplicated To addresses.
        cc: Validated, deduplicated CC addresses.
        body: Optional comment; omitted when empty after stripping.

    Returns:
        ``{"status": "sent"}``.
    """
    payload: dict[str, Any] = {"toRecipients": _recipients(to)}

    if cc:
        payload["ccRecipients"] = _recipients(cc)

    if body:
        body_stripped = body.strip()
        if body_stripped:
            payload["comment"] = body_stripped

    graph.request("POST", f"/me/messages/{email_id}/forward", account_id, json=payload)
    return {"status": "sent"}


def download_attachment(
    account_id: str,
    *,
    email_id: str,
    attachment_id: str,
    destination: Path,
) -> dict[str, Any]:
    """Download a message attachment and write it to a local path.

    Args:
        account_id: Microsoft account identifier.
        email_id: Validated Graph message identifier.
        attachment_id: Validated attachment identifier.
        destination: Validated destination path; its parent must exist.

    Returns:
        Attachment ``name``, ``content_type``, ``size`` and ``saved_to``.

    Raises:
        ValidationError: If the attachment is missing or too large.
        RuntimeError: If content is unavailable, undecodable, or cannot be
            written.
    """
    result = graph.request(
        "GET", f"/me/messages/{email_id}/attachments/{attachment_id}", account_id
    )

    if not result:
        raise ValidationError(
            format_validation_error(
                "attachment_id",
                attachment_id,
                "attachment not found for email",
                "Existing attachment identifier",
            )
        )

    if "contentBytes" not in result:
        raise RuntimeError("Attachment content not available for download")

    reported_size = result.get("size", 0) or 0
    validate_request_size(
        int(reported_size),
        MAX_ATTACHMENT_DOWNLOAD_BYTES,
        "attachment_size",
    )

    try:
        content_bytes = base64.b64decode(result["contentBytes"])
    except (ValueError, KeyError) as exc:
        raise RuntimeError(f"Failed to decode attachment content: {exc}") from exc

    validate_request_size(
        len(content_bytes),
        MAX_ATTACHMENT_DOWNLOAD_BYTES,
        "attachment_size",
    )

    try:
        destination.write_bytes(content_bytes)
    except OSError as exc:
        if destination.exists():
            destination.unlink(missing_ok=True)
        LOGGER.error(
            "Failed to persist attachment",
            extra={
                "email_id": email_id,
                "attachment_id": attachment_id,
                "destination": str(destination),
            },
        )
        raise RuntimeError(f"Unable to write attachment to disk: {exc}") from exc

    return {
        "name": result.get("name", "unknown"),
        "content_type": result.get("contentType", "application/octet-stream"),
        "size": len(content_bytes),
        "saved_to": str(destination),
    }


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
