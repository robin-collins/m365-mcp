from typing import Any
from ..mcp_instance import mcp
from .. import graph


def _emailrules_list_impl(account_id: str) -> list[dict[str, Any]]:
    result = graph.request("GET", "/me/mailFolders/inbox/messageRules", account_id)
    if not result or "value" not in result:
        return []
    return list(result["value"])


def _emailrules_get_impl(rule_id: str, account_id: str) -> dict[str, Any]:
    result = graph.request(
        "GET", f"/me/mailFolders/inbox/messageRules/{rule_id}", account_id
    )
    if not result:
        raise ValueError(f"Message rule with ID {rule_id} not found")
    return result


# emailrules_list
@mcp.tool(
    name="emailrules_list",
    annotations={
        "title": "List Email Rules",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "emailrules", "safety_level": "safe"},
)
def emailrules_list(account_id: str) -> list[dict[str, Any]]:
    """📖 List all inbox message rules (read-only, safe for unsupervised use)

    Message rules automatically process incoming emails based on conditions.
    Rules are executed in sequence order (1, 2, 3...).

    Args:
        account_id: Microsoft account ID

    Returns:
        List of rules with: id, displayName, sequence, isEnabled, conditions, actions
    """
    return _emailrules_list_impl(account_id)


# emailrules_get
@mcp.tool(
    name="emailrules_get",
    annotations={
        "title": "Get Email Rule",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "emailrules", "safety_level": "safe"},
)
def emailrules_get(rule_id: str, account_id: str) -> dict[str, Any]:
    """📖 Get details of a specific message rule (read-only, safe for unsupervised use)

    Returns complete rule configuration including conditions, actions, and execution order.

    Args:
        rule_id: The message rule ID
        account_id: Microsoft account ID

    Returns:
        Rule details including conditions, actions, sequence, and enabled status
    """
    return _emailrules_get_impl(rule_id, account_id)


# emailrules_create
@mcp.tool(
    name="emailrules_create",
    annotations={
        "title": "Create Email Rule",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    meta={"category": "emailrules", "safety_level": "moderate"},
)
def emailrules_create(
    account_id: str,
    display_name: str,
    conditions: dict[str, Any],
    actions: dict[str, Any],
    sequence: int = 1,
    is_enabled: bool = True,
    exceptions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """✏️ Create a new inbox message rule to automatically process emails (requires user confirmation recommended)

    Rules are executed in priority order (sequence number).

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

    Args:
        account_id: Microsoft account ID
        display_name: Name for the rule (e.g., "Move work emails to Projects")
        conditions: Conditions that trigger the rule
        actions: Actions to perform when conditions match
        sequence: Rule execution order (lower numbers execute first, default: 1)
        is_enabled: Whether the rule is active (default: True)
        exceptions: Optional conditions that prevent rule execution

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


# emailrules_update
@mcp.tool(
    name="emailrules_update",
    annotations={
        "title": "Update Email Rule",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "emailrules", "safety_level": "moderate"},
)
def emailrules_update(
    rule_id: str,
    account_id: str,
    display_name: str | None = None,
    conditions: dict[str, Any] | None = None,
    actions: dict[str, Any] | None = None,
    sequence: int | None = None,
    is_enabled: bool | None = None,
    exceptions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """✏️ Update an existing message rule (requires user confirmation recommended)

    Modifies rule properties, conditions, actions, or execution order.
    At least one field must be provided to update.

    Args:
        rule_id: The message rule ID to update
        account_id: Microsoft account ID
        display_name: New name for the rule (optional)
        conditions: New conditions (optional)
        actions: New actions (optional)
        sequence: New execution order (optional)
        is_enabled: Enable or disable the rule (optional)
        exceptions: New exception conditions (optional)

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


# emailrules_delete
@mcp.tool(
    name="emailrules_delete",
    annotations={
        "title": "Delete Email Rule",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={
        "category": "emailrules",
        "safety_level": "critical",
        "requires_confirmation": True,
    },
)
def emailrules_delete(
    rule_id: str, account_id: str, confirm: bool = False
) -> dict[str, str]:
    """🔴 Delete a message rule permanently (always require user confirmation)

    WARNING: This action permanently deletes the rule and cannot be undone.
    Emails will no longer be automatically processed by this rule.

    Args:
        rule_id: The message rule ID to delete
        account_id: Microsoft account ID
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
    graph.request("DELETE", f"/me/mailFolders/inbox/messageRules/{rule_id}", account_id)
    return {"status": "deleted", "rule_id": rule_id}


# emailrules_move_top
@mcp.tool(
    name="emailrules_move_top",
    annotations={
        "title": "Move Email Rule to Top",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    meta={"category": "emailrules", "safety_level": "moderate"},
)
def emailrules_move_top(rule_id: str, account_id: str) -> dict[str, Any]:
    """✏️ Move a message rule to the top of execution order (requires user confirmation recommended)

    Rules execute in sequence order. Moving to top means it runs before all other rules.
    Sets the rule's sequence number to 1.

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


# emailrules_move_bottom
@mcp.tool(
    name="emailrules_move_bottom",
    annotations={
        "title": "Move Email Rule to Bottom",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    meta={"category": "emailrules", "safety_level": "moderate"},
)
def emailrules_move_bottom(rule_id: str, account_id: str) -> dict[str, Any]:
    """✏️ Move a message rule to the bottom of execution order (requires user confirmation recommended)

    Rules execute in sequence order. Moving to bottom means it runs after all other rules.

    Args:
        rule_id: The message rule ID to move
        account_id: Microsoft account ID

    Returns:
        Updated rule with new sequence number
    """
    # Get all rules to find the highest sequence number
    all_rules = _emailrules_list_impl(account_id)
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


# emailrules_move_up
@mcp.tool(
    name="emailrules_move_up",
    annotations={
        "title": "Move Email Rule Up",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    meta={"category": "emailrules", "safety_level": "moderate"},
)
def emailrules_move_up(rule_id: str, account_id: str) -> dict[str, Any]:
    """✏️ Move a message rule up one position in execution order (requires user confirmation recommended)

    Increases the rule's priority by moving it one position higher in the
    execution order. Rules at the top (sequence = 1) cannot be moved up.

    Args:
        rule_id: The message rule ID to move
        account_id: Microsoft account ID

    Returns:
        Updated rule with new sequence number
    """
    # Get current rule
    current_rule = _emailrules_get_impl(rule_id, account_id)
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


# emailrules_move_down
@mcp.tool(
    name="emailrules_move_down",
    annotations={
        "title": "Move Email Rule Down",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    meta={"category": "emailrules", "safety_level": "moderate"},
)
def emailrules_move_down(rule_id: str, account_id: str) -> dict[str, Any]:
    """✏️ Move a message rule down one position in execution order (requires user confirmation recommended)

    Decreases the rule's priority by moving it one position lower in the
    execution order. Rules at the bottom cannot be moved down further.

    Args:
        rule_id: The message rule ID to move
        account_id: Microsoft account ID

    Returns:
        Updated rule with new sequence number
    """
    # Get current rule
    current_rule = _emailrules_get_impl(rule_id, account_id)
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
