import base64
import datetime as dt
import pathlib as pl
from typing import Any
from fastmcp import FastMCP
from . import graph, auth

mcp = FastMCP("microsoft-mcp")

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


@mcp.tool
def list_accounts() -> list[dict[str, str]]:
    """List all signed-in Microsoft accounts"""
    return [
        {"username": acc.username, "account_id": acc.account_id}
        for acc in auth.list_accounts()
    ]


@mcp.tool
def authenticate_account() -> dict[str, str]:
    """Authenticate a new Microsoft account using device flow authentication

    Returns authentication instructions and device code for the user to complete authentication.
    The user must visit the URL and enter the code to authenticate their Microsoft account.
    """
    app = auth.get_app()
    flow = app.initiate_device_flow(scopes=auth.SCOPES)

    if "user_code" not in flow:
        error_msg = flow.get("error_description", "Unknown error")
        raise Exception(f"Failed to get device code: {error_msg}")

    verification_url = flow.get(
        "verification_uri",
        flow.get("verification_url", "https://microsoft.com/devicelogin"),
    )

    return {
        "status": "authentication_required",
        "instructions": "To authenticate a new Microsoft account:",
        "step1": f"Visit: {verification_url}",
        "step2": f"Enter code: {flow['user_code']}",
        "step3": "Sign in with the Microsoft account you want to add",
        "step4": "After authenticating, use the 'complete_authentication' tool to finish the process",
        "device_code": flow["user_code"],
        "verification_url": verification_url,
        "expires_in": flow.get("expires_in", 900),
        "_flow_cache": str(flow),
    }


@mcp.tool
def complete_authentication(flow_cache: str) -> dict[str, str]:
    """Complete the authentication process after the user has entered the device code

    Args:
        flow_cache: The flow data returned from authenticate_account (the _flow_cache field)

    Returns:
        Account information if authentication was successful
    """
    import ast

    try:
        flow = ast.literal_eval(flow_cache)
    except (ValueError, SyntaxError):
        raise ValueError("Invalid flow cache data")

    app = auth.get_app()
    result = app.acquire_token_by_device_flow(flow)

    if "error" in result:
        error_msg = result.get("error_description", result["error"])
        if "authorization_pending" in error_msg:
            return {
                "status": "pending",
                "message": "Authentication is still pending. The user needs to complete the authentication process.",
                "instructions": "Please ensure you've visited the URL and entered the code, then try again.",
            }
        raise Exception(f"Authentication failed: {error_msg}")

    # Save the token cache
    cache = app.token_cache
    if isinstance(cache, auth.msal.SerializableTokenCache) and cache.has_state_changed:
        auth._write_cache(cache.serialize())

    # Get the newly added account
    accounts = app.get_accounts()
    if accounts:
        # Find the account that matches the token we just got
        for account in accounts:
            if (
                account.get("username", "").lower()
                == result.get("id_token_claims", {})
                .get("preferred_username", "")
                .lower()
            ):
                return {
                    "status": "success",
                    "username": account["username"],
                    "account_id": account["home_account_id"],
                    "message": f"Successfully authenticated {account['username']}",
                }
        # If exact match not found, return the last account
        account = accounts[-1]
        return {
            "status": "success",
            "username": account["username"],
            "account_id": account["home_account_id"],
            "message": f"Successfully authenticated {account['username']}",
        }

    return {
        "status": "error",
        "message": "Authentication succeeded but no account was found",
    }


@mcp.tool
def list_emails(
    account_id: str,
    folder: str | None = None,
    folder_id: str | None = None,
    limit: int = 10,
    include_body: bool = True,
) -> list[dict[str, Any]]:
    """List emails from specified folder by name or ID

    Args:
        account_id: Microsoft account ID
        folder: Folder name (inbox, sent, drafts, etc.) - legacy support
        folder_id: Direct folder ID - takes precedence over folder name
        limit: Maximum emails to return
        include_body: Whether to include email body content

    Returns:
        List of email messages
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


@mcp.tool
def list_mail_folders(
    account_id: str,
    parent_folder_id: str | None = None,
    include_hidden: bool = False,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List mail folders - root folders or child folders of a specific parent

    Args:
        account_id: Microsoft account ID
        parent_folder_id: If None, lists root folders. If provided, lists child folders.
        include_hidden: Whether to include hidden folders
        limit: Maximum number of folders to return

    Returns:
        List of folder objects with: id, displayName, childFolderCount,
        unreadItemCount, totalItemCount, parentFolderId, isHidden
    """
    return _list_mail_folders_impl(account_id, parent_folder_id, include_hidden, limit)


@mcp.tool
def get_mail_folder(
    folder_id: str,
    account_id: str,
) -> dict[str, Any]:
    """Get detailed information about a specific mail folder

    Args:
        folder_id: The folder ID to retrieve
        account_id: Microsoft account ID

    Returns:
        Folder object with full metadata including id, displayName,
        childFolderCount, unreadItemCount, totalItemCount
    """
    result = graph.request("GET", f"/me/mailFolders/{folder_id}", account_id)
    if not result:
        raise ValueError(f"Mail folder with ID {folder_id} not found")
    return result


@mcp.tool
def get_mail_folder_tree(
    account_id: str,
    parent_folder_id: str | None = None,
    max_depth: int = 10,
    include_hidden: bool = False,
) -> dict[str, Any]:
    """Recursively build a tree of mail folders

    Args:
        account_id: Microsoft account ID
        parent_folder_id: Root folder to start from (None = root)
        max_depth: Maximum recursion depth to prevent infinite loops
        include_hidden: Whether to include hidden folders

    Returns:
        Nested tree structure with folders and their children
    """

    def _build_folder_tree(
        folder_id: str | None, current_depth: int
    ) -> list[dict[str, Any]]:
        """Internal recursive helper to build folder tree"""
        if current_depth >= max_depth:
            return []

        # Get folders at this level
        folders = _list_mail_folders_impl(
            account_id=account_id,
            parent_folder_id=folder_id,
            include_hidden=include_hidden,
            limit=1000,  # Large limit to get all folders at this level
        )

        result = []
        for folder in folders:
            folder_node = {
                "id": folder["id"],
                "displayName": folder.get("displayName", ""),
                "childFolderCount": folder.get("childFolderCount", 0),
                "unreadItemCount": folder.get("unreadItemCount", 0),
                "totalItemCount": folder.get("totalItemCount", 0),
                "parentFolderId": folder.get("parentFolderId"),
                "isHidden": folder.get("isHidden", False),
                "children": [],
            }

            # Recursively get children if this folder has child folders
            if folder.get("childFolderCount", 0) > 0:
                folder_node["children"] = _build_folder_tree(
                    folder["id"], current_depth + 1
                )

            result.append(folder_node)

        return result

    # Build tree starting from specified parent or root
    tree_data = _build_folder_tree(parent_folder_id, 0)

    return {
        "root_folder_id": parent_folder_id,
        "max_depth": max_depth,
        "folders": tree_data,
    }


@mcp.tool
def get_email(
    email_id: str,
    account_id: str,
    include_body: bool = True,
    body_max_length: int = 50000,
    include_attachments: bool = True,
) -> dict[str, Any]:
    """Get email details with size limits

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


@mcp.tool
def create_email_draft(
    account_id: str,
    to: str | list[str],
    subject: str,
    body: str,
    cc: str | list[str] | None = None,
    attachments: str | list[str] | None = None,
) -> dict[str, Any]:
    """Create an email draft with file path(s) as attachments"""
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


@mcp.tool
def send_email(
    account_id: str,
    to: str | list[str],
    subject: str,
    body: str,
    cc: str | list[str] | None = None,
    attachments: str | list[str] | None = None,
) -> dict[str, str]:
    """Send an email immediately with file path(s) as attachments"""
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


@mcp.tool
def update_email(
    email_id: str, updates: dict[str, Any], account_id: str
) -> dict[str, Any]:
    """Update email properties (isRead, categories, flag, etc.)"""
    result = graph.request(
        "PATCH", f"/me/messages/{email_id}", account_id, json=updates
    )
    if not result:
        raise ValueError(f"Failed to update email {email_id} - no response")
    return result


@mcp.tool
def delete_email(email_id: str, account_id: str) -> dict[str, str]:
    """Delete an email"""
    graph.request("DELETE", f"/me/messages/{email_id}", account_id)
    return {"status": "deleted"}


@mcp.tool
def move_email(
    email_id: str, destination_folder: str, account_id: str
) -> dict[str, Any]:
    """Move email to another folder"""
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


@mcp.tool
def reply_to_email(account_id: str, email_id: str, body: str) -> dict[str, str]:
    """Reply to an email (sender only)"""
    endpoint = f"/me/messages/{email_id}/reply"
    payload = {"message": {"body": {"contentType": "Text", "content": body}}}
    graph.request("POST", endpoint, account_id, json=payload)
    return {"status": "sent"}


@mcp.tool
def reply_all_email(account_id: str, email_id: str, body: str) -> dict[str, str]:
    """Reply to all recipients of an email"""
    endpoint = f"/me/messages/{email_id}/replyAll"
    payload = {"message": {"body": {"contentType": "Text", "content": body}}}
    graph.request("POST", endpoint, account_id, json=payload)
    return {"status": "sent"}


@mcp.tool
def list_message_rules(account_id: str) -> list[dict[str, Any]]:
    """List all inbox message rules (email filters) for the account

    Message rules automatically process incoming emails based on conditions.
    Rules are executed in sequence order (1, 2, 3...).

    Returns:
        List of rules with: id, displayName, sequence, isEnabled, conditions, actions
    """
    result = graph.request("GET", "/me/mailFolders/inbox/messageRules", account_id)
    if not result or "value" not in result:
        return []
    return result["value"]


@mcp.tool
def get_message_rule(rule_id: str, account_id: str) -> dict[str, Any]:
    """Get details of a specific message rule

    Args:
        rule_id: The message rule ID
        account_id: Microsoft account ID

    Returns:
        Rule details including conditions, actions, sequence, and enabled status
    """
    result = graph.request(
        "GET", f"/me/mailFolders/inbox/messageRules/{rule_id}", account_id
    )
    if not result:
        raise ValueError(f"Message rule with ID {rule_id} not found")
    return result


@mcp.tool
def create_message_rule(
    account_id: str,
    display_name: str,
    conditions: dict[str, Any],
    actions: dict[str, Any],
    sequence: int = 1,
    is_enabled: bool = True,
    exceptions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a new inbox message rule to automatically process emails

    Args:
        account_id: Microsoft account ID
        display_name: Name for the rule (e.g., "Move work emails to Projects")
        conditions: Conditions that trigger the rule
        actions: Actions to perform when conditions match
        sequence: Rule execution order (lower numbers execute first)
        is_enabled: Whether the rule is active
        exceptions: Optional conditions that prevent rule execution

    Conditions examples:
        {"fromAddresses": [{"address": "john@example.com"}]}
        {"subjectContains": ["urgent", "important"]}
        {"senderContains": ["@company.com"]}
        {"hasAttachments": true}

    Actions examples:
        {"moveToFolder": "folder_id"}
        {"markAsRead": true}
        {"forwardTo": [{"emailAddress": {"address": "manager@example.com"}}]}
        {"assignCategories": ["Red category"]}
        {"delete": true}

    Returns:
        Created rule with its ID and full configuration
    """
    rule_data = {
        "displayName": display_name,
        "sequence": sequence,
        "isEnabled": is_enabled,
        "conditions": conditions,
        "actions": actions,
    }

    if exceptions:
        rule_data["exceptions"] = exceptions

    result = graph.request(
        "POST", "/me/mailFolders/inbox/messageRules", account_id, json=rule_data
    )
    if not result:
        raise ValueError("Failed to create message rule")
    return result


@mcp.tool
def update_message_rule(
    rule_id: str,
    account_id: str,
    display_name: str | None = None,
    conditions: dict[str, Any] | None = None,
    actions: dict[str, Any] | None = None,
    sequence: int | None = None,
    is_enabled: bool | None = None,
    exceptions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Update an existing message rule

    Args:
        rule_id: The message rule ID to update
        account_id: Microsoft account ID
        display_name: New name for the rule
        conditions: New conditions
        actions: New actions
        sequence: New execution order
        is_enabled: Enable or disable the rule
        exceptions: New exception conditions

    Returns:
        Updated rule configuration
    """
    updates = {}
    if display_name is not None:
        updates["displayName"] = display_name
    if conditions is not None:
        updates["conditions"] = conditions
    if actions is not None:
        updates["actions"] = actions
    if sequence is not None:
        updates["sequence"] = sequence
    if is_enabled is not None:
        updates["isEnabled"] = is_enabled
    if exceptions is not None:
        updates["exceptions"] = exceptions

    if not updates:
        raise ValueError("At least one field must be provided to update")

    result = graph.request(
        "PATCH",
        f"/me/mailFolders/inbox/messageRules/{rule_id}",
        account_id,
        json=updates,
    )
    if not result:
        raise ValueError(f"Failed to update message rule {rule_id}")
    return result


@mcp.tool
def delete_message_rule(rule_id: str, account_id: str) -> dict[str, str]:
    """Delete a message rule

    Args:
        rule_id: The message rule ID to delete
        account_id: Microsoft account ID

    Returns:
        Status confirmation
    """
    graph.request("DELETE", f"/me/mailFolders/inbox/messageRules/{rule_id}", account_id)
    return {"status": "deleted", "rule_id": rule_id}


@mcp.tool
def move_rule_to_top(rule_id: str, account_id: str) -> dict[str, Any]:
    """Move a message rule to the top of the execution order (sequence = 1)

    Rules execute in sequence order. Moving to top means it runs before all other rules.

    Args:
        rule_id: The message rule ID to move
        account_id: Microsoft account ID

    Returns:
        Updated rule with new sequence number
    """
    result = graph.request(
        "PATCH",
        f"/me/mailFolders/inbox/messageRules/{rule_id}",
        account_id,
        json={"sequence": 1},
    )
    if not result:
        raise ValueError(f"Failed to move rule {rule_id} to top")
    return result


@mcp.tool
def move_rule_to_bottom(rule_id: str, account_id: str) -> dict[str, Any]:
    """Move a message rule to the bottom of the execution order

    Args:
        rule_id: The message rule ID to move
        account_id: Microsoft account ID

    Returns:
        Updated rule with new sequence number
    """
    # Get all rules to find the highest sequence number
    all_rules = list_message_rules(account_id)
    if not all_rules:
        raise ValueError("No rules found")

    max_sequence = max(rule.get("sequence", 1) for rule in all_rules)
    new_sequence = max_sequence + 1

    result = graph.request(
        "PATCH",
        f"/me/mailFolders/inbox/messageRules/{rule_id}",
        account_id,
        json={"sequence": new_sequence},
    )
    if not result:
        raise ValueError(f"Failed to move rule {rule_id} to bottom")
    return result


@mcp.tool
def move_rule_up(rule_id: str, account_id: str) -> dict[str, Any]:
    """Move a message rule up one position in the execution order (decrease sequence by 1)

    Rules execute in sequence order. Moving up means it runs earlier.

    Args:
        rule_id: The message rule ID to move
        account_id: Microsoft account ID

    Returns:
        Updated rule with new sequence number
    """
    # Get current rule
    current_rule = get_message_rule(rule_id, account_id)
    current_sequence = current_rule.get("sequence", 1)

    if current_sequence <= 1:
        raise ValueError("Rule is already at the top (sequence = 1)")

    new_sequence = current_sequence - 1

    result = graph.request(
        "PATCH",
        f"/me/mailFolders/inbox/messageRules/{rule_id}",
        account_id,
        json={"sequence": new_sequence},
    )
    if not result:
        raise ValueError(f"Failed to move rule {rule_id} up")
    return result


@mcp.tool
def move_rule_down(rule_id: str, account_id: str) -> dict[str, Any]:
    """Move a message rule down one position in the execution order (increase sequence by 1)

    Rules execute in sequence order. Moving down means it runs later.

    Args:
        rule_id: The message rule ID to move
        account_id: Microsoft account ID

    Returns:
        Updated rule with new sequence number
    """
    # Get current rule
    current_rule = get_message_rule(rule_id, account_id)
    current_sequence = current_rule.get("sequence", 1)

    new_sequence = current_sequence + 1

    result = graph.request(
        "PATCH",
        f"/me/mailFolders/inbox/messageRules/{rule_id}",
        account_id,
        json={"sequence": new_sequence},
    )
    if not result:
        raise ValueError(f"Failed to move rule {rule_id} down")
    return result


@mcp.tool
def list_events(
    account_id: str,
    days_ahead: int = 7,
    days_back: int = 0,
    include_details: bool = True,
) -> list[dict[str, Any]]:
    """List calendar events within specified date range, including recurring event instances"""
    now = dt.datetime.now(dt.timezone.utc)
    start = (now - dt.timedelta(days=days_back)).isoformat()
    end = (now + dt.timedelta(days=days_ahead)).isoformat()

    params = {
        "startDateTime": start,
        "endDateTime": end,
        "$orderby": "start/dateTime",
        "$top": 100,
    }

    if include_details:
        params["$select"] = (
            "id,subject,start,end,location,body,attendees,organizer,isAllDay,recurrence,onlineMeeting,seriesMasterId"
        )
    else:
        params["$select"] = "id,subject,start,end,location,organizer,seriesMasterId"

    # Use calendarView to get recurring event instances
    events = list(
        graph.request_paginated("/me/calendarView", account_id, params=params)
    )

    return events


@mcp.tool
def get_event(event_id: str, account_id: str) -> dict[str, Any]:
    """Get full event details"""
    result = graph.request("GET", f"/me/events/{event_id}", account_id)
    if not result:
        raise ValueError(f"Event with ID {event_id} not found")
    return result


@mcp.tool
def create_event(
    account_id: str,
    subject: str,
    start: str,
    end: str,
    location: str | None = None,
    body: str | None = None,
    attendees: str | list[str] | None = None,
    timezone: str = "UTC",
) -> dict[str, Any]:
    """Create a calendar event"""
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


@mcp.tool
def update_event(
    event_id: str, updates: dict[str, Any], account_id: str
) -> dict[str, Any]:
    """Update event properties"""
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


@mcp.tool
def delete_event(
    account_id: str, event_id: str, send_cancellation: bool = True
) -> dict[str, str]:
    """Delete or cancel a calendar event"""
    if send_cancellation:
        graph.request("POST", f"/me/events/{event_id}/cancel", account_id, json={})
    else:
        graph.request("DELETE", f"/me/events/{event_id}", account_id)
    return {"status": "deleted"}


@mcp.tool
def respond_event(
    account_id: str,
    event_id: str,
    response: str = "accept",
    message: str | None = None,
) -> dict[str, str]:
    """Respond to event invitation (accept, decline, tentativelyAccept)"""
    payload: dict[str, Any] = {"sendResponse": True}
    if message:
        payload["comment"] = message

    graph.request("POST", f"/me/events/{event_id}/{response}", account_id, json=payload)
    return {"status": response}


@mcp.tool
def check_availability(
    account_id: str,
    start: str,
    end: str,
    attendees: str | list[str] | None = None,
) -> dict[str, Any]:
    """Check calendar availability for scheduling"""
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


@mcp.tool
def list_contacts(account_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """List contacts"""
    params = {"$top": min(limit, 100)}

    contacts = list(
        graph.request_paginated("/me/contacts", account_id, params=params, limit=limit)
    )

    return contacts


@mcp.tool
def get_contact(contact_id: str, account_id: str) -> dict[str, Any]:
    """Get contact details"""
    result = graph.request("GET", f"/me/contacts/{contact_id}", account_id)
    if not result:
        raise ValueError(f"Contact with ID {contact_id} not found")
    return result


@mcp.tool
def create_contact(
    account_id: str,
    given_name: str,
    surname: str | None = None,
    email_addresses: str | list[str] | None = None,
    phone_numbers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Create a new contact"""
    contact: dict[str, Any] = {"givenName": given_name}

    if surname:
        contact["surname"] = surname

    if email_addresses:
        email_list = (
            [email_addresses] if isinstance(email_addresses, str) else email_addresses
        )
        contact["emailAddresses"] = [
            {"address": email, "name": f"{given_name} {surname or ''}".strip()}
            for email in email_list
        ]

    if phone_numbers:
        if "business" in phone_numbers:
            contact["businessPhones"] = [phone_numbers["business"]]
        if "home" in phone_numbers:
            contact["homePhones"] = [phone_numbers["home"]]
        if "mobile" in phone_numbers:
            contact["mobilePhone"] = phone_numbers["mobile"]

    result = graph.request("POST", "/me/contacts", account_id, json=contact)
    if not result:
        raise ValueError("Failed to create contact")
    return result


@mcp.tool
def update_contact(
    contact_id: str, updates: dict[str, Any], account_id: str
) -> dict[str, Any]:
    """Update contact information"""
    result = graph.request(
        "PATCH", f"/me/contacts/{contact_id}", account_id, json=updates
    )
    return result or {"status": "updated"}


@mcp.tool
def delete_contact(contact_id: str, account_id: str) -> dict[str, str]:
    """Delete a contact"""
    graph.request("DELETE", f"/me/contacts/{contact_id}", account_id)
    return {"status": "deleted"}


@mcp.tool
def list_files(
    account_id: str,
    path: str = "/",
    folder_id: str | None = None,
    limit: int = 50,
    type_filter: str = "all",
) -> list[dict[str, Any]]:
    """List files and/or folders in OneDrive

    Args:
        account_id: Microsoft account ID
        path: Path to list from
        folder_id: Direct folder ID (takes precedence over path)
        limit: Maximum items to return
        type_filter: Filter by type - "all", "files", or "folders"

    Returns:
        List of items matching the filter criteria
    """
    # Validate type_filter
    if type_filter not in ["all", "files", "folders"]:
        raise ValueError("type_filter must be one of: 'all', 'files', 'folders'")

    # Determine endpoint
    if folder_id:
        endpoint = f"/me/drive/items/{folder_id}/children"
    elif path == "/":
        endpoint = "/me/drive/root/children"
    else:
        endpoint = f"/me/drive/root:/{path}:/children"

    params = {
        "$top": min(limit, 100),
        "$select": "id,name,size,lastModifiedDateTime,folder,file,@microsoft.graph.downloadUrl",
    }

    items = list(
        graph.request_paginated(endpoint, account_id, params=params, limit=limit)
    )

    # Apply type filtering
    result = []
    for item in items:
        is_folder = "folder" in item
        is_file = "file" in item

        # Filter based on type_filter
        if type_filter == "folders" and not is_folder:
            continue
        if type_filter == "files" and not is_file:
            continue

        result.append(
            {
                "id": item["id"],
                "name": item["name"],
                "type": "folder" if is_folder else "file",
                "size": item.get("size", 0),
                "modified": item.get("lastModifiedDateTime"),
                "download_url": item.get("@microsoft.graph.downloadUrl"),
            }
        )

    return result


@mcp.tool
def get_file(file_id: str, account_id: str, download_path: str) -> dict[str, Any]:
    """Download a file from OneDrive to local path"""
    import subprocess

    metadata = graph.request("GET", f"/me/drive/items/{file_id}", account_id)
    if not metadata:
        raise ValueError(f"File with ID {file_id} not found")

    download_url = metadata.get("@microsoft.graph.downloadUrl")
    if not download_url:
        raise ValueError("No download URL available for this file")

    try:
        subprocess.run(
            ["curl", "-L", "-o", download_path, download_url],
            check=True,
            capture_output=True,
        )

        return {
            "path": download_path,
            "name": metadata.get("name", "unknown"),
            "size_mb": round(metadata.get("size", 0) / (1024 * 1024), 2),
            "mime_type": metadata.get("file", {}).get("mimeType") if metadata else None,
        }
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to download file: {e.stderr.decode()}")


@mcp.tool
def create_file(
    onedrive_path: str, local_file_path: str, account_id: str
) -> dict[str, Any]:
    """Upload a local file to OneDrive"""
    path = pl.Path(local_file_path).expanduser().resolve()
    data = path.read_bytes()
    result = graph.upload_large_file(
        f"/me/drive/root:/{onedrive_path}:", data, account_id
    )
    if not result:
        raise ValueError(f"Failed to create file at path: {onedrive_path}")
    return result


@mcp.tool
def update_file(file_id: str, local_file_path: str, account_id: str) -> dict[str, Any]:
    """Update OneDrive file content from a local file"""
    path = pl.Path(local_file_path).expanduser().resolve()
    data = path.read_bytes()
    result = graph.upload_large_file(f"/me/drive/items/{file_id}", data, account_id)
    if not result:
        raise ValueError(f"Failed to update file with ID: {file_id}")
    return result


@mcp.tool
def delete_file(file_id: str, account_id: str) -> dict[str, str]:
    """Delete a file or folder"""
    graph.request("DELETE", f"/me/drive/items/{file_id}", account_id)
    return {"status": "deleted"}


def _list_folders_impl(
    account_id: str,
    path: str = "/",
    folder_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Internal implementation for listing OneDrive folders"""
    if folder_id:
        endpoint = f"/me/drive/items/{folder_id}/children"
    elif path == "/":
        endpoint = "/me/drive/root/children"
    else:
        endpoint = f"/me/drive/root:/{path}:/children"

    params = {
        "$top": min(limit, 100),
        "$select": "id,name,folder,parentReference,size,lastModifiedDateTime",
    }

    items = list(
        graph.request_paginated(endpoint, account_id, params=params, limit=limit)
    )

    # Filter to only return folders
    folders = []
    for item in items:
        if "folder" in item:
            folders.append(
                {
                    "id": item["id"],
                    "name": item["name"],
                    "childCount": item.get("folder", {}).get("childCount", 0),
                    "path": item.get("parentReference", {}).get("path", ""),
                    "parentId": item.get("parentReference", {}).get("id"),
                    "modified": item.get("lastModifiedDateTime"),
                }
            )

    return folders


@mcp.tool
def list_folders(
    account_id: str,
    path: str = "/",
    folder_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List only folders (not files) in OneDrive location

    Args:
        account_id: Microsoft account ID
        path: Path to list folders from (e.g., "/Documents")
        folder_id: Direct folder ID (takes precedence over path)
        limit: Maximum folders to return

    Returns:
        List of folder objects with: id, name, childCount, path, parentId
    """
    return _list_folders_impl(account_id, path, folder_id, limit)


@mcp.tool
def get_folder(
    account_id: str,
    folder_id: str | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    """Get metadata for a specific OneDrive folder

    Args:
        account_id: Microsoft account ID
        folder_id: Folder ID (takes precedence)
        path: Folder path (e.g., "/Documents/Projects")

    Returns:
        Folder metadata including childCount
    """
    if not folder_id and not path:
        raise ValueError("Either folder_id or path must be provided")

    if folder_id:
        endpoint = f"/me/drive/items/{folder_id}"
    elif path == "/":
        endpoint = "/me/drive/root"
    else:
        endpoint = f"/me/drive/root:/{path}"

    result = graph.request("GET", endpoint, account_id)
    if not result:
        raise ValueError("Folder not found")

    # Validate it's actually a folder
    if "folder" not in result:
        raise ValueError("Item at specified location is not a folder")

    return {
        "id": result["id"],
        "name": result["name"],
        "childCount": result.get("folder", {}).get("childCount", 0),
        "path": result.get("parentReference", {}).get("path", ""),
        "parentId": result.get("parentReference", {}).get("id"),
        "modified": result.get("lastModifiedDateTime"),
        "webUrl": result.get("webUrl"),
    }


@mcp.tool
def get_folder_tree(
    account_id: str,
    path: str = "/",
    folder_id: str | None = None,
    max_depth: int = 10,
) -> dict[str, Any]:
    """Recursively build a tree of OneDrive folders

    Args:
        account_id: Microsoft account ID
        path: Starting path (default root)
        folder_id: Starting folder ID (takes precedence over path)
        max_depth: Maximum recursion depth

    Returns:
        Nested tree structure with folders and their children
    """

    def _build_drive_folder_tree(
        item_id: str | None, item_path: str, current_depth: int
    ) -> list[dict[str, Any]]:
        """Internal recursive helper to build OneDrive folder tree"""
        if current_depth >= max_depth:
            return []

        # Get folders at this level
        folders = _list_folders_impl(
            account_id=account_id,
            path=item_path if not item_id else None,
            folder_id=item_id,
            limit=1000,  # Large limit to get all folders at this level
        )

        result = []
        for folder in folders:
            folder_node = {
                "id": folder["id"],
                "name": folder["name"],
                "childCount": folder.get("childCount", 0),
                "path": folder.get("path", ""),
                "parentId": folder.get("parentId"),
                "modified": folder.get("modified"),
                "children": [],
            }

            # Recursively get children if this folder has subfolders
            if folder.get("childCount", 0) > 0:
                folder_node["children"] = _build_drive_folder_tree(
                    folder["id"], None, current_depth + 1
                )

            result.append(folder_node)

        return result

    # Build tree starting from specified location
    if folder_id:
        start_id = folder_id
        start_path = None
    else:
        start_id = None
        start_path = path

    tree_data = _build_drive_folder_tree(start_id, start_path, 0)

    return {
        "root_folder_id": folder_id,
        "root_path": path if not folder_id else None,
        "max_depth": max_depth,
        "folders": tree_data,
    }


@mcp.tool
def get_attachment(
    email_id: str, attachment_id: str, save_path: str, account_id: str
) -> dict[str, Any]:
    """Download email attachment to a specified file path"""
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


@mcp.tool
def search_files(
    query: str,
    account_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Search for files in OneDrive using the modern search API."""
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


@mcp.tool
def search_emails(
    query: str,
    account_id: str,
    limit: int = 50,
    folder: str | None = None,
) -> list[dict[str, Any]]:
    """Search emails using the modern search API."""
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


@mcp.tool
def search_events(
    query: str,
    account_id: str,
    days_ahead: int = 365,
    days_back: int = 365,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Search calendar events using the modern search API."""
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


@mcp.tool
def search_contacts(
    query: str,
    account_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Search contacts. Uses traditional search since unified_search doesn't support contacts."""
    params = {
        "$search": f'"{query}"',
        "$top": min(limit, 100),
    }

    contacts = list(
        graph.request_paginated("/me/contacts", account_id, params=params, limit=limit)
    )

    return contacts


@mcp.tool
def unified_search(
    query: str,
    account_id: str,
    entity_types: list[str] | None = None,
    limit: int = 50,
) -> dict[str, list[dict[str, Any]]]:
    """Search across multiple Microsoft 365 resources using the modern search API

    entity_types can include: 'message', 'event', 'drive', 'driveItem', 'list', 'listItem', 'site'
    If not specified, searches across all available types.
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
