"""Inbox message rule operations over Microsoft Graph.

Callers pass already-validated Graph payloads; this module owns the
endpoints and the multi-step sequence (reorder) logic.
"""

from typing import Any

from .. import graph
from ..errors import GraphAPIError
from ..validators import ValidationError

RULES_PATH = "/me/mailFolders/inbox/messageRules"


def _rule_path(rule_id: str) -> str:
    return f"{RULES_PATH}/{rule_id}"


def _set_sequence(
    account_id: str, rule_id: str, sequence: int, error: str
) -> dict[str, Any]:
    result = graph.request(
        "PATCH",
        _rule_path(rule_id),
        account_id,
        json={"sequence": sequence},
    )
    if not result:
        raise ValueError(error)
    return result


def list_rules(account_id: str) -> list[dict[str, Any]]:
    """List all inbox message rules.

    Args:
        account_id: Microsoft account ID.

    Returns:
        List of message rule dictionaries (empty if Graph returns none).
    """
    result = graph.request("GET", RULES_PATH, account_id)
    if not result or "value" not in result:
        return []
    return list(result["value"])


def get_rule(account_id: str, *, rule_id: str) -> dict[str, Any]:
    """Get a single inbox message rule.

    Args:
        account_id: Microsoft account ID.
        rule_id: The message rule ID.

    Returns:
        The message rule dictionary.

    Raises:
        ValueError: If Graph returns no rule.
    """
    result = graph.request("GET", _rule_path(rule_id), account_id)
    if not result:
        raise ValueError(f"Message rule with ID {rule_id} not found")
    return result


def create_rule(account_id: str, *, rule: dict[str, Any]) -> dict[str, Any]:
    """Create an inbox message rule.

    Args:
        account_id: Microsoft account ID.
        rule: Validated Graph messageRule payload.

    Returns:
        The created message rule.

    Raises:
        ValueError: If Graph returns no result.
    """
    result = graph.request("POST", RULES_PATH, account_id, json=rule)
    if not result:
        raise ValueError("Failed to create message rule")
    return result


def update_rule(
    account_id: str, *, rule_id: str, updates: dict[str, Any]
) -> dict[str, Any]:
    """Update an inbox message rule.

    Args:
        account_id: Microsoft account ID.
        rule_id: The message rule ID.
        updates: Validated Graph messageRule fields to patch.

    Returns:
        The updated message rule.

    Raises:
        ValueError: If Graph returns no result.
    """
    result = graph.request(
        "PATCH",
        _rule_path(rule_id),
        account_id,
        json=updates,
    )
    if not result:
        raise ValueError(f"Failed to update message rule {rule_id}")
    return result


def delete_rule(account_id: str, *, rule_id: str) -> dict[str, str]:
    """Delete an inbox message rule.

    Args:
        account_id: Microsoft account ID.
        rule_id: The message rule ID.

    Returns:
        Status dictionary with ``status`` and ``rule_id``.
    """
    graph.request("DELETE", _rule_path(rule_id), account_id)
    return {"status": "deleted", "rule_id": rule_id}


def move_rule_to_top(account_id: str, *, rule_id: str) -> dict[str, Any]:
    """Set a rule's sequence to 1 so it runs first.

    Args:
        account_id: Microsoft account ID.
        rule_id: The message rule ID.

    Returns:
        The updated message rule.

    Raises:
        ValueError: If Graph returns no result.
    """
    return _set_sequence(
        account_id, rule_id, 1, f"Failed to move rule {rule_id} to top"
    )


def move_rule_to_bottom(account_id: str, *, rule_id: str) -> dict[str, Any]:
    """Set a rule's sequence past the current highest so it runs last.

    Args:
        account_id: Microsoft account ID.
        rule_id: The message rule ID.

    Returns:
        The updated message rule.

    Raises:
        ValueError: If there are no rules or Graph returns no result.
    """
    all_rules = list_rules(account_id)
    if not all_rules:
        raise ValueError("No rules found")

    max_sequence = max(rule.get("sequence", 1) for rule in all_rules)
    return _set_sequence(
        account_id,
        rule_id,
        max_sequence + 1,
        f"Failed to move rule {rule_id} to bottom",
    )


def move_rule_up(account_id: str, *, rule_id: str) -> dict[str, Any]:
    """Decrease a rule's sequence by one.

    Args:
        account_id: Microsoft account ID.
        rule_id: The message rule ID.

    Returns:
        The updated message rule.

    Raises:
        ValueError: If the rule is already at sequence 1, is not found,
            or Graph returns no result.
    """
    current_sequence = get_rule(account_id, rule_id=rule_id).get("sequence", 1)
    if current_sequence <= 1:
        raise ValueError("Rule is already at the top (sequence = 1)")

    return _set_sequence(
        account_id,
        rule_id,
        current_sequence - 1,
        f"Failed to move rule {rule_id} up",
    )


def move_rule_down(account_id: str, *, rule_id: str) -> dict[str, Any]:
    """Increase a rule's sequence by one.

    Args:
        account_id: Microsoft account ID.
        rule_id: The message rule ID.

    Returns:
        The updated message rule.

    Raises:
        ValueError: If the rule is not found or Graph returns no result.
    """
    current_sequence = get_rule(account_id, rule_id=rule_id).get("sequence", 1)
    return _set_sequence(
        account_id,
        rule_id,
        current_sequence + 1,
        f"Failed to move rule {rule_id} down",
    )


# ----------------------------------------------------------------------
# Unified tool support (email_rule_manage)
# ----------------------------------------------------------------------


def next_sequence(account_id: str) -> int:
    """Return the sequence that places a new rule after all others.

    Args:
        account_id: Microsoft account ID.

    Returns:
        One more than the highest current sequence (1 with no rules).
    """
    sequences = [r.get("sequence") or 0 for r in list_rules(account_id)]
    return max(sequences, default=0) + 1


def find_mail_folder_id(account_id: str, folder_id: str) -> str | None:
    """Look up a mail folder for a rule's move/copy action.

    Args:
        account_id: Microsoft account ID.
        folder_id: Folder ID supplied by the caller.

    Returns:
        The folder's Graph ID, or ``None`` when no such folder exists.

    Raises:
        GraphAPIError: For failures other than not found or a malformed ID.
    """
    try:
        folder = graph.request(
            "GET",
            f"/me/mailFolders/{folder_id}",
            account_id,
            params={"$select": "id"},
        )
    except GraphAPIError as exc:
        if exc.status in (400, 404):
            return None
        raise
    return str(folder["id"]) if folder else None


def _new_index(
    order: list[str],
    old_index: int,
    position: str,
    relative_to_rule_id: str | None,
) -> int:
    """Return where the moved rule goes in ``order`` (which excludes it)."""
    if position == "top":
        return 0
    if position == "bottom":
        return len(order)
    if position == "up":
        return max(old_index - 1, 0)
    if position == "down":
        return min(old_index + 1, len(order))
    if relative_to_rule_id not in order:
        raise ValidationError("Invalid relative_to_rule_id: rule not found")
    anchor = order.index(relative_to_rule_id)
    return anchor if position == "before" else anchor + 1


def reorder_rule(
    account_id: str,
    *,
    rule_id: str,
    position: str,
    relative_to_rule_id: str | None = None,
) -> dict[str, Any]:
    """Move a rule and rewrite the sequence of every rule that moved.

    Reads all rules, computes the new order, then PATCHes ``sequence`` to
    1..n on each rule whose sequence changes (the legacy ``move_*`` tools
    also moved rules by rewriting ``sequence``).

    Args:
        account_id: Microsoft account ID.
        rule_id: Rule to move.
        position: ``top``, ``bottom``, ``up``, ``down``, ``before`` or
            ``after``.
        relative_to_rule_id: Anchor rule for ``before`` / ``after``.

    Returns:
        The moved rule after the change.

    Raises:
        ValidationError: If either rule is not found.
    """
    rules = sorted(list_rules(account_id), key=lambda r: r.get("sequence") or 0)
    ids = [str(r["id"]) for r in rules]
    if rule_id not in ids:
        raise ValidationError("Invalid rule_id: rule not found")
    old_index = ids.index(rule_id)
    order = [i for i in ids if i != rule_id]
    order.insert(_new_index(order, old_index, position, relative_to_rule_id), rule_id)

    by_id = {str(r["id"]): r for r in rules}
    moved = by_id[rule_id]
    for index, current_id in enumerate(order):
        sequence = index + 1
        if by_id[current_id].get("sequence") == sequence:
            continue
        updated = _set_sequence(
            account_id,
            current_id,
            sequence,
            f"Failed to set the sequence of rule {current_id}",
        )
        if current_id == rule_id:
            moved = updated
    return moved
