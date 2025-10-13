import base64
import logging
import pathlib as pl
from datetime import datetime
from typing import Any

from .. import graph
from ..mcp_instance import mcp
from ..validators import (
    ValidationError,
    ensure_safe_path,
    format_validation_error,
    normalize_recipients,
    require_confirm,
    validate_account_id,
    validate_choices,
    validate_iso_datetime,
    validate_json_payload,
    validate_limit,
    validate_microsoft_graph_id,
    validate_request_size,
    validate_timezone,
)

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

MAX_ATTACHMENT_DOWNLOAD_BYTES = 25 * 1024 * 1024
MAX_EMAIL_RECIPIENTS = 500
ALLOWED_EMAIL_UPDATE_KEYS = {
    "isRead",
    "categories",
    "importance",
    "flag",
    "inferenceClassification",
}
EMAIL_IMPORTANCE_CHOICES = {"low", "normal", "high"}
INFERENCE_CLASSIFICATIONS = {"focused", "other"}
ALLOWED_EMAIL_FLAG_KEYS = {
    "flagStatus",
    "startDateTime",
    "dueDateTime",
    "completedDateTime",
}
ALLOWED_FLAG_DATETIME_KEYS = {"dateTime", "timeZone"}
FLAG_STATUS_CHOICES = {"notFlagged", "flagged", "complete"}


def _validate_flag_datetime_section(
    payload: Any,
    section_name: str,
) -> tuple[dict[str, str], datetime]:
    """Validate the datetime payload within a message flag section."""
    section = validate_json_payload(
        payload,
        required_keys=("dateTime", "timeZone"),
        allowed_keys=ALLOWED_FLAG_DATETIME_KEYS,
        param_name=section_name,
    )
    timestamp = validate_iso_datetime(
        section["dateTime"],
        f"{section_name}.dateTime",
    )
    timezone_name = validate_timezone(
        section["timeZone"],
        f"{section_name}.timeZone",
    )
    return {"dateTime": section["dateTime"], "timeZone": timezone_name}, timestamp


def _validate_flag_payload(flag: Any) -> dict[str, Any]:
    """Validate the flag payload for email updates."""
    validated = validate_json_payload(
        flag,
        allowed_keys=ALLOWED_EMAIL_FLAG_KEYS,
        param_name="flag",
    )
    if not validated:
        raise ValidationError(
            format_validation_error(
                "flag",
                flag,
                "must include at least one field",
                f"Subset of {sorted(ALLOWED_EMAIL_FLAG_KEYS)}",
            )
        )

    result: dict[str, Any] = {}
    start_dt: datetime | None = None
    due_dt: datetime | None = None

    if "flagStatus" in validated:
        status = validate_choices(
            validated["flagStatus"],
            FLAG_STATUS_CHOICES,
            "flag.flagStatus",
        )
        result["flagStatus"] = status

    if "startDateTime" in validated:
        start_section, start_dt = _validate_flag_datetime_section(
            validated["startDateTime"],
            "flag.startDateTime",
        )
        result["startDateTime"] = start_section

    if "dueDateTime" in validated:
        due_section, due_dt = _validate_flag_datetime_section(
            validated["dueDateTime"],
            "flag.dueDateTime",
        )
        result["dueDateTime"] = due_section

    if start_dt and due_dt and start_dt > due_dt:
        raise ValidationError(
            format_validation_error(
                "flag.dueDateTime",
                flag,
                "must be later than startDateTime",
                "dueDateTime >= startDateTime",
            )
        )

    if "completedDateTime" in validated:
        completed_section, _ = _validate_flag_datetime_section(
            validated["completedDateTime"],
            "flag.completedDateTime",
        )
        result["completedDateTime"] = completed_section

    return result


# email_list
@mcp.tool(
    name="email_list",
    annotations={
        "title": "List Emails",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "email", "safety_level": "safe"},
)
def email_list(
    account_id: str,
    folder: str | None = None,
    folder_id: str | None = None,
    limit: int = 10,
    include_body: bool = True,
) -> list[dict[str, Any]]:
    """📖 List emails from a mailbox folder (read-only, safe for unsupervised use)

    Returns recent emails with subject, sender, date, size, and attachment info.

    Args:
        account_id: Microsoft account ID
        folder: Folder name (inbox, sent, drafts, deleted, junk, archive)
        folder_id: Direct folder ID - takes precedence over folder name
        limit: Maximum emails to return (1-200, default: 10)
        include_body: Whether to include email body content (default: True)

    Returns:
        List of email messages with metadata and optionally body content
    """
    limit = validate_limit(limit, 1, 200, "limit")
    # Determine which folder to use
    if folder_id:
        # Direct folder ID takes precedence
        folder_path = folder_id
    elif folder:
        # Use folder name mapping
        folder_path = FOLDERS.get(folder.casefold(), folder)
    else:
        # Default to inbox
        folder_path = "inbox"

    if include_body:
        select_fields = "id,subject,from,toRecipients,ccRecipients,receivedDateTime,hasAttachments,body,conversationId,isRead"
    else:
        select_fields = "id,subject,from,toRecipients,receivedDateTime,hasAttachments,conversationId,isRead"

    params = {
        "$top": limit,
        "$select": select_fields,
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

    return emails


def _list_mail_folders_impl(
    account_id: str,
    parent_folder_id: str | None = None,
    include_hidden: bool = False,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Internal implementation for listing mail folders"""
    if parent_folder_id:
        endpoint = f"/me/mailFolders/{parent_folder_id}/childFolders"
    else:
        endpoint = "/me/mailFolders"

    page_size = limit if limit is not None else 250
    params = {
        "$select": "id,displayName,childFolderCount,unreadItemCount,totalItemCount,parentFolderId,isHidden",
        "$top": page_size,
    }

    if include_hidden:
        params["includeHiddenFolders"] = "true"

    folders = list(
        graph.request_paginated(endpoint, account_id, params=params, limit=limit)
    )

    return folders


# email_get
@mcp.tool(
    name="email_get",
    annotations={
        "title": "Get Email",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "email", "safety_level": "safe"},
)
def email_get(
    email_id: str,
    account_id: str,
    include_body: bool = True,
    body_max_length: int = 50000,
    include_attachments: bool = True,
) -> dict[str, Any]:
    """📖 Get detailed information about a specific email (read-only, safe for unsupervised use)

    Includes full headers, body content, and attachment metadata.
    Body content is truncated at 50,000 characters by default.

    Args:
        email_id: The email ID
        account_id: The account ID
        include_body: Whether to include the email body (default: True)
        body_max_length: Maximum characters for body content (1-500000, default: 50000)
        include_attachments: Whether to include attachment metadata (default: True)
    """
    body_max_length = validate_limit(body_max_length, 1, 500_000, "body_max_length")
    params = {}
    if include_attachments:
        params["$expand"] = "attachments($select=id,name,size,contentType)"

    result = graph.request("GET", f"/me/messages/{email_id}", account_id, params=params)
    if not result:
        raise ValueError(f"Email with ID {email_id} not found")

    # Truncate body if needed
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

    return result


# email_create_draft
@mcp.tool(
    name="email_create_draft",
    annotations={
        "title": "Create Email Draft",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    meta={"category": "email", "safety_level": "moderate"},
)
def email_create_draft(
    account_id: str,
    to: str | list[str],
    subject: str,
    body: str,
    cc: str | list[str] | None = None,
    attachments: str | list[str] | None = None,
) -> dict[str, Any]:
    """✏️ Create an email draft (requires user confirmation recommended)

    Creates a draft email message that can be edited later before sending.
    Supports attachments from local file paths.

    Args:
        account_id: Microsoft account ID
        to: Recipient email address(es)
        subject: Email subject
        body: Email body (plain text)
        cc: CC recipient email address(es) (optional)
        attachments: Local file path(s) for attachments (optional)

    Returns:
        Created draft message with ID
    """
    to_list = [to] if isinstance(to, str) else to

    message = {
        "subject": subject,
        "body": {"contentType": "Text", "content": body},
        "toRecipients": [{"emailAddress": {"address": addr}} for addr in to_list],
    }

    if cc:
        cc_list = [cc] if isinstance(cc, str) else cc
        message["ccRecipients"] = [
            {"emailAddress": {"address": addr}} for addr in cc_list
        ]

    small_attachments = []
    large_attachments = []

    if attachments:
        # Convert single path to list
        attachment_paths = (
            [attachments] if isinstance(attachments, str) else attachments
        )
        for file_path in attachment_paths:
            path = pl.Path(file_path).expanduser().resolve()
            content_bytes = path.read_bytes()
            att_size = len(content_bytes)
            att_name = path.name

            if att_size < 3 * 1024 * 1024:
                small_attachments.append(
                    {
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "name": att_name,
                        "contentBytes": base64.b64encode(content_bytes).decode("utf-8"),
                    }
                )
            else:
                large_attachments.append(
                    {
                        "name": att_name,
                        "content_bytes": content_bytes,
                        "content_type": "application/octet-stream",
                    }
                )

    if small_attachments:
        message["attachments"] = small_attachments

    result = graph.request("POST", "/me/messages", account_id, json=message)
    if not result:
        raise ValueError("Failed to create email draft")

    message_id = result["id"]

    for att in large_attachments:
        graph.upload_large_mail_attachment(
            message_id,
            att["name"],
            att["content_bytes"],
            account_id,
            att.get("content_type", "application/octet-stream"),
        )

    return result


# email_send
@mcp.tool(
    name="email_send",
    annotations={
        "title": "Send Email",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    meta={
        "category": "email",
        "safety_level": "dangerous",
        "requires_confirmation": True,
    },
)
def email_send(
    account_id: str,
    to: str | list[str],
    subject: str,
    body: str,
    cc: str | list[str] | None = None,
    attachments: str | list[str] | None = None,
    confirm: bool = False,
) -> dict[str, str]:
    """📧 Send an email to recipients (always require user confirmation)

    WARNING: Email will be sent immediately upon execution.
    This action cannot be undone.

    Supports multiple recipients, CC, attachments, and HTML formatting.
    Addresses are validated, deduplicated across To/CC, and limited to
    500 unique recipients in total.

    Args:
        account_id: Microsoft account ID
        to: Recipient email address(es)
        subject: Email subject
        body: Email body (plain text)
        cc: CC recipient email address(es) (optional)
        attachments: Local file path(s) for attachments (optional)
        confirm: Must be True to confirm sending (prevents accidents)

    Returns:
        Status confirmation

    Raises:
        ValidationError: If recipients are invalid, exceed limits,
            or confirm is False.
    """
    to_normalized = normalize_recipients(to, "to")
    cc_normalized = normalize_recipients(cc, "cc") if cc else []

    seen: set[str] = set()
    to_unique: list[str] = []
    cc_unique: list[str] = []

    for address in to_normalized:
        key = address.casefold()
        if key in seen:
            continue
        seen.add(key)
        to_unique.append(address)

    for address in cc_normalized:
        key = address.casefold()
        if key in seen:
            continue
        seen.add(key)
        cc_unique.append(address)

    total_unique = len(to_unique) + len(cc_unique)
    if total_unique > MAX_EMAIL_RECIPIENTS:
        reason = f"must not exceed {MAX_EMAIL_RECIPIENTS} unique recipients"
        raise ValidationError(
            format_validation_error(
                "recipients",
                total_unique,
                reason,
                f"≤ {MAX_EMAIL_RECIPIENTS}",
            )
        )

    require_confirm(confirm, "send email")

    def build_message() -> dict[str, Any]:
        payload: dict[str, Any] = {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": addr}} for addr in to_unique],
        }
        if cc_unique:
            payload["ccRecipients"] = [
                {"emailAddress": {"address": addr}} for addr in cc_unique
            ]
        return payload

    has_large_attachments = False
    processed_attachments = []

    if attachments:
        # Convert single path to list
        attachment_paths = (
            [attachments] if isinstance(attachments, str) else attachments
        )
        for file_path in attachment_paths:
            path = pl.Path(file_path).expanduser().resolve()
            content_bytes = path.read_bytes()
            att_size = len(content_bytes)
            att_name = path.name

            processed_attachments.append(
                {
                    "name": att_name,
                    "content_bytes": content_bytes,
                    "content_type": "application/octet-stream",
                    "size": att_size,
                }
            )

            if att_size >= 3 * 1024 * 1024:
                has_large_attachments = True

    if not has_large_attachments and processed_attachments:
        message = build_message()
        message["attachments"] = [
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": att["name"],
                "contentBytes": base64.b64encode(att["content_bytes"]).decode("utf-8"),
            }
            for att in processed_attachments
        ]
        graph.request("POST", "/me/sendMail", account_id, json={"message": message})
        return {"status": "sent"}
    elif has_large_attachments:
        # Create draft first, then add large attachments, then send
        # We need to handle large attachments manually here
        message = build_message()
        result = graph.request("POST", "/me/messages", account_id, json=message)
        if not result:
            raise ValueError("Failed to create email draft")

        message_id = result["id"]

        for att in processed_attachments:
            if att["size"] >= 3 * 1024 * 1024:
                graph.upload_large_mail_attachment(
                    message_id,
                    att["name"],
                    att["content_bytes"],
                    account_id,
                    att.get("content_type", "application/octet-stream"),
                )
            else:
                small_att = {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": att["name"],
                    "contentBytes": base64.b64encode(att["content_bytes"]).decode(
                        "utf-8"
                    ),
                }
                graph.request(
                    "POST",
                    f"/me/messages/{message_id}/attachments",
                    account_id,
                    json=small_att,
                )

        graph.request("POST", f"/me/messages/{message_id}/send", account_id)
        return {"status": "sent"}
    else:
        graph.request(
            "POST", "/me/sendMail", account_id, json={"message": build_message()}
        )
        return {"status": "sent"}


# email_update
@mcp.tool(
    name="email_update",
    annotations={
        "title": "Update Email Properties",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "email", "safety_level": "moderate"},
)
def email_update(
    email_id: str, updates: dict[str, Any], account_id: str
) -> dict[str, Any]:
    """✏️ Update email properties (requires user confirmation recommended)

    Modifies properties like isRead status, categories, and flags without
    changing email content.

    Examples:
        email_update(email_id, {"isRead": True}, account_id)
        email_update(email_id, {"categories": ["Important"]}, account_id)

    Allowed update keys: isRead, categories, importance, flag, inferenceClassification.

    Args:
        email_id: The email ID to update
        updates: Dictionary of properties to update
        account_id: Microsoft account ID

    Returns:
        Updated email object
    """
    payload = validate_json_payload(
        updates,
        allowed_keys=ALLOWED_EMAIL_UPDATE_KEYS,
        param_name="updates",
    )
    if not payload:
        raise ValidationError(
            format_validation_error(
                "updates",
                payload,
                "must include at least one field",
                f"Subset of {sorted(ALLOWED_EMAIL_UPDATE_KEYS)}",
            )
        )

    graph_updates: dict[str, Any] = {}

    if "isRead" in payload:
        is_read = payload["isRead"]
        if not isinstance(is_read, bool):
            raise ValidationError(
                format_validation_error(
                    "updates.isRead",
                    is_read,
                    "must be a boolean value",
                    "True or False",
                )
            )
        graph_updates["isRead"] = is_read

    if "categories" in payload:
        categories_raw = payload["categories"]
        if not isinstance(categories_raw, list):
            raise ValidationError(
                format_validation_error(
                    "updates.categories",
                    categories_raw,
                    "must be a list of category names",
                    "List of non-empty strings",
                )
            )
        normalised_categories: list[str] = []
        for index, category in enumerate(categories_raw):
            if not isinstance(category, str):
                raise ValidationError(
                    format_validation_error(
                        f"updates.categories[{index}]",
                        category,
                        "must be a string",
                        "Category name string",
                    )
                )
            trimmed = category.strip()
            if not trimmed:
                raise ValidationError(
                    format_validation_error(
                        f"updates.categories[{index}]",
                        category,
                        "cannot be empty",
                        "Non-empty category name",
                    )
                )
            normalised_categories.append(trimmed)
        graph_updates["categories"] = normalised_categories

    if "importance" in payload:
        importance = validate_choices(
            payload["importance"],
            EMAIL_IMPORTANCE_CHOICES,
            "updates.importance",
        )
        graph_updates["importance"] = importance

    if "flag" in payload:
        graph_updates["flag"] = _validate_flag_payload(payload["flag"])

    if "inferenceClassification" in payload:
        inference = validate_choices(
            payload["inferenceClassification"],
            INFERENCE_CLASSIFICATIONS,
            "updates.inferenceClassification",
        )
        graph_updates["inferenceClassification"] = inference

    result = graph.request(
        "PATCH", f"/me/messages/{email_id}", account_id, json=graph_updates
    )
    if not result:
        raise ValueError(f"Failed to update email {email_id} - no response")
    return result


# email_delete
@mcp.tool(
    name="email_delete",
    annotations={
        "title": "Delete Email",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={
        "category": "email",
        "safety_level": "critical",
        "requires_confirmation": True,
    },
)
def email_delete(
    email_id: str, account_id: str, confirm: bool = False
) -> dict[str, str]:
    """🔴 Delete an email permanently (always require user confirmation)

    WARNING: This action permanently deletes the email and cannot be undone.

    For safety, consider moving items to the deleted items folder first using email_move.

    Args:
        email_id: The email to delete
        account_id: The account ID
        confirm: Must be True to confirm deletion (prevents accidents)

    Returns:
        Status confirmation
    """
    require_confirm(confirm, "delete email")
    graph.request("DELETE", f"/me/messages/{email_id}", account_id)
    return {"status": "deleted"}


# email_move
@mcp.tool(
    name="email_move",
    annotations={
        "title": "Move Email",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "email", "safety_level": "moderate"},
)
def email_move(
    email_id: str, destination_folder: str, account_id: str
) -> dict[str, Any]:
    """✏️ Move an email to a different folder (requires user confirmation recommended)

    Moves the email to the specified folder without deleting it from the source.

    Valid folder names: inbox, sent, drafts, deleted, junk, archive

    Args:
        email_id: The email ID to move
        destination_folder: Folder name or ID to move to
        account_id: Microsoft account ID

    Returns:
        Status confirmation with new email ID
    """
    folder_path = FOLDERS.get(destination_folder.casefold(), destination_folder)

    folders = graph.request("GET", "/me/mailFolders", account_id)
    folder_id = None

    if not folders:
        raise ValueError("Failed to retrieve mail folders")
    if "value" not in folders:
        raise ValueError(f"Unexpected folder response structure: {folders}")

    for folder in folders["value"]:
        if folder["displayName"].lower() == folder_path.lower():
            folder_id = folder["id"]
            break

    if not folder_id:
        raise ValueError(f"Folder '{destination_folder}' not found")

    payload = {"destinationId": folder_id}
    result = graph.request(
        "POST", f"/me/messages/{email_id}/move", account_id, json=payload
    )
    if not result:
        raise ValueError("Failed to move email - no response from server")
    if "id" not in result:
        raise ValueError(f"Failed to move email - unexpected response: {result}")
    return {"status": "moved", "new_id": result["id"]}


# email_reply
@mcp.tool(
    name="email_reply",
    annotations={
        "title": "Reply to Email",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    meta={
        "category": "email",
        "safety_level": "dangerous",
        "requires_confirmation": True,
    },
)
def email_reply(
    account_id: str, email_id: str, body: str, confirm: bool = False
) -> dict[str, str]:
    """📧 Reply to an email (always require user confirmation)

    WARNING: Reply will be sent immediately to the original sender.
    This action cannot be undone.

    Body content is stripped of surrounding whitespace and must not be
    empty before sending.

    Args:
        account_id: Microsoft account ID
        email_id: The email ID to reply to
        body: Reply message body (plain text)
        confirm: Must be True to confirm sending (prevents accidents)

    Returns:
        Status confirmation

    Raises:
        ValidationError: If the reply body is empty/whitespace or confirm
            is False.
    """
    if not isinstance(body, str):
        reason = "must be a string"
        raise ValidationError(
            format_validation_error("body", body, reason, "Non-empty reply body")
        )

    body_stripped = body.strip()
    if not body_stripped:
        reason = "cannot be empty"
        raise ValidationError(
            format_validation_error("body", body, reason, "Non-empty reply body")
        )

    require_confirm(confirm, "reply to email")
    endpoint = f"/me/messages/{email_id}/reply"
    payload = {"message": {"body": {"contentType": "Text", "content": body_stripped}}}
    graph.request("POST", endpoint, account_id, json=payload)
    return {"status": "sent"}


# email_get_attachment
@mcp.tool(
    name="email_get_attachment",
    annotations={
        "title": "Get Email Attachment",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "email", "safety_level": "moderate"},
)
def email_get_attachment(
    email_id: str, attachment_id: str, save_path: str, account_id: str
) -> dict[str, Any]:
    """Download an email attachment to a validated local path.

    Args:
        email_id: Microsoft Graph message identifier containing the attachment.
        attachment_id: Target attachment identifier within the message.
        save_path: Destination path for the attachment. Validated via
            `ensure_safe_path`; existing files are never overwritten.
        account_id: Microsoft account identifier.

    Returns:
        Attachment metadata, including saved path and content size.
    """

    account = validate_account_id(account_id)
    message_id = validate_microsoft_graph_id(email_id, "email_id")
    attachment = validate_microsoft_graph_id(attachment_id, "attachment_id")
    destination = ensure_safe_path(save_path, allow_overwrite=False)
    destination.parent.mkdir(parents=True, exist_ok=True)

    result = graph.request(
        "GET", f"/me/messages/{message_id}/attachments/{attachment}", account
    )

    if not result:
        raise ValidationError(
            format_validation_error(
                "attachment_id",
                attachment,
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
    except OSError as exc:  # noqa: BLE001
        if destination.exists():
            destination.unlink(missing_ok=True)
        LOGGER.error(
            "Failed to persist attachment",
            extra={
                "email_id": message_id,
                "attachment_id": attachment,
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
