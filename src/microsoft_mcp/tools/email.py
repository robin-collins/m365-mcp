import base64
import pathlib as pl
from typing import Any
from ..mcp_instance import mcp
from .. import graph

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
        limit: Maximum emails to return (default: 10)
        include_body: Whether to include email body content (default: True)

    Returns:
        List of email messages with metadata and optionally body content
    """
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
        "$top": min(limit, 100),
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
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Internal implementation for listing mail folders"""
    if parent_folder_id:
        endpoint = f"/me/mailFolders/{parent_folder_id}/childFolders"
    else:
        endpoint = "/me/mailFolders"

    params = {
        "$select": "id,displayName,childFolderCount,unreadItemCount,totalItemCount,parentFolderId,isHidden",
        "$top": min(limit, 100),
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
        body_max_length: Maximum characters for body content (default: 50000)
        include_attachments: Whether to include attachment metadata (default: True)
    """
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

    Supports multiple recipients, CC, BCC, attachments, and HTML formatting.

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
    """
    if not confirm:
        raise ValueError(
            "Email sending requires explicit confirmation. "
            "Set confirm=True to proceed. "
            "This action cannot be undone."
        )
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

    # Check if we have large attachments
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
        graph.request("POST", "/me/sendMail", account_id, json={"message": message})
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

    Args:
        email_id: The email ID to update
        updates: Dictionary of properties to update
        account_id: Microsoft account ID

    Returns:
        Updated email object
    """
    result = graph.request(
        "PATCH", f"/me/messages/{email_id}", account_id, json=updates
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
    if not confirm:
        raise ValueError(
            "Deletion requires explicit confirmation. "
            "Set confirm=True to proceed. "
            "This action cannot be undone."
        )
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

    Args:
        account_id: Microsoft account ID
        email_id: The email ID to reply to
        body: Reply message body (plain text)
        confirm: Must be True to confirm sending (prevents accidents)

    Returns:
        Status confirmation
    """
    if not confirm:
        raise ValueError(
            "Email reply requires explicit confirmation. "
            "Set confirm=True to proceed. "
            "This action cannot be undone."
        )
    endpoint = f"/me/messages/{email_id}/reply"
    payload = {"message": {"body": {"contentType": "Text", "content": body}}}
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
    """⚠️ Download email attachment to local path (requires user confirmation recommended)

    IMPORTANT: Large files may take significant time to download.
    Ensure sufficient local disk space is available.

    Args:
        email_id: The email ID containing the attachment
        attachment_id: The attachment ID to download
        save_path: Local file path to save the attachment
        account_id: Microsoft account ID

    Returns:
        Attachment metadata including name, size, content type, and saved path
    """
    result = graph.request(
        "GET", f"/me/messages/{email_id}/attachments/{attachment_id}", account_id
    )

    if not result:
        raise ValueError("Attachment not found")

    if "contentBytes" not in result:
        raise ValueError("Attachment content not available")

    # Save attachment to file
    path = pl.Path(save_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    content_bytes = base64.b64decode(result["contentBytes"])
    path.write_bytes(content_bytes)

    return {
        "name": result.get("name", "unknown"),
        "content_type": result.get("contentType", "application/octet-stream"),
        "size": result.get("size", 0),
        "saved_to": str(path),
    }
