"""Handler for ``email_rule_manage`` (U3.22).

Creates, updates, enables/disables and reorders Inbox rules. Typed
conditions, actions and exceptions are translated with
``projections.rule_to_graph``; results use ``project_email_rule``.

Confirm rule: the *resulting* rule must not forward, redirect or delete
mail without ``confirm=true``. For ``update`` the check uses the existing
rule merged with the supplied fields; for ``set_enabled`` it applies when
enabling (a disabled rule acts on nothing); ``reorder`` does not change
what a rule does.
"""

from __future__ import annotations

from typing import Any

from ...projections import actions_from_graph, project_email_rule, rule_to_graph
from ...services import mail_rules
from ..handlers import register_handler, register_validation_rule
from . import common
from .common import invalid, require_confirm

_NEEDS_RULE_ID = ("update", "set_enabled", "reorder")
_ACTION_PARAM = {"update": "rule", "set_enabled": "is_enabled", "reorder": "position"}
_FOLDER_ACTIONS = ("move_to_folder", "copy_to_folder")


def _dangerous_verb(actions: dict[str, Any]) -> str | None:
    """Return what a rule with ``actions`` does silently, if anything."""
    if actions.get("forward_to") or actions.get("forward_as_attachment_to"):
        return "forwards"
    if actions.get("redirect_to"):
        return "redirects"
    if actions.get("delete") or actions.get("permanent_delete"):
        return "deletes"
    return None


def _confirm_actions(args: dict[str, Any], actions: dict[str, Any]) -> None:
    verb = _dangerous_verb(actions)
    if verb is not None:
        require_confirm(args, f"a rule that {verb} mail")


@register_validation_rule("email_rule_manage")
def _rule_arguments(args: dict[str, Any]) -> None:
    action = args["action"]
    if action == "create":
        rule = args.get("rule") or {}
        if not all(k in rule for k in ("display_name", "conditions", "actions")):
            raise invalid(
                "rule", "create requires display_name, conditions and actions"
            )
        return
    if action in _NEEDS_RULE_ID and args.get("rule_id") is None:
        raise invalid("rule_id", f"required for action '{action}'")
    param = _ACTION_PARAM[action]
    if args.get(param) is None:
        raise invalid(param, f"required for action '{action}'")
    position = args.get("position")
    if action == "reorder" and position in ("before", "after"):
        relative = args.get("relative_to_rule_id")
        if relative is None:
            raise invalid("relative_to_rule_id", f"required for position '{position}'")
        if relative == args["rule_id"]:
            raise invalid("relative_to_rule_id", "must differ from rule_id")


@register_validation_rule("email_rule_manage")
def _create_confirm(args: dict[str, Any]) -> None:
    if args["action"] == "create":
        _confirm_actions(args, args["rule"]["actions"])


def _resolve_folders(account_id: str, rule: dict[str, Any]) -> dict[str, Any]:
    """Check move/copy folders exist and use their Graph IDs."""
    actions = rule.get("actions")
    if not actions:
        return rule
    resolved = dict(actions)
    for name in _FOLDER_ACTIONS:
        if name not in actions:
            continue
        folder_id = mail_rules.find_mail_folder_id(account_id, actions[name])
        if folder_id is None:
            raise invalid(name, "folder not found")
        resolved[name] = folder_id
    return {**rule, "actions": resolved}


def _create(account_id: str, args: dict[str, Any]) -> dict[str, Any]:
    rule = _resolve_folders(account_id, args["rule"])
    body = rule_to_graph(rule)
    body.setdefault("isEnabled", True)
    if "sequence" not in body:
        body["sequence"] = mail_rules.next_sequence(account_id)
    created = project_email_rule(mail_rules.create_rule(account_id, rule=body))
    summary = (
        f"Created rule '{created['display_name']}' (position {created['sequence']})."
    )
    return {"action": "create", "rule": created, "summary": summary}


def _update(account_id: str, args: dict[str, Any]) -> dict[str, Any]:
    rule_id, changes = args["rule_id"], args["rule"]
    existing = mail_rules.get_rule(account_id, rule_id=rule_id)
    merged_actions = changes.get("actions") or actions_from_graph(
        existing.get("actions")
    )
    _confirm_actions(args, merged_actions)
    changes = _resolve_folders(account_id, changes)
    updated = project_email_rule(
        mail_rules.update_rule(
            account_id, rule_id=rule_id, updates=rule_to_graph(changes)
        )
    )
    summary = f"Updated rule '{updated['display_name']}'."
    return {"action": "update", "rule": updated, "summary": summary}


def _set_enabled(account_id: str, args: dict[str, Any]) -> dict[str, Any]:
    rule_id, enabled = args["rule_id"], args["is_enabled"]
    existing = mail_rules.get_rule(account_id, rule_id=rule_id)
    if enabled:
        _confirm_actions(args, actions_from_graph(existing.get("actions")))
    updated = project_email_rule(
        mail_rules.update_rule(
            account_id, rule_id=rule_id, updates={"isEnabled": enabled}
        )
    )
    state = "Enabled" if enabled else "Disabled"
    summary = f"{state} rule '{updated['display_name']}'."
    return {"action": "set_enabled", "rule": updated, "summary": summary}


def _reorder(account_id: str, args: dict[str, Any]) -> dict[str, Any]:
    moved = project_email_rule(
        mail_rules.reorder_rule(
            account_id,
            rule_id=args["rule_id"],
            position=args["position"],
            relative_to_rule_id=args.get("relative_to_rule_id"),
        )
    )
    summary = f"Moved rule '{moved['display_name']}' to position {moved['sequence']}."
    return {"action": "reorder", "rule": moved, "summary": summary}


_ACTIONS = {
    "create": _create,
    "update": _update,
    "set_enabled": _set_enabled,
    "reorder": _reorder,
}


@register_handler("email_rule_manage")
def email_rule_manage(args: dict[str, Any]) -> dict[str, Any]:
    """Create, update, enable/disable or reorder an Inbox rule.

    Args:
        args: Validated ``email_rule_manage`` arguments.

    Returns:
        ``{action, rule, summary}`` with the rule after the change.

    Raises:
        ValidationError: If a move/copy folder does not exist, a rule to
            reorder is not found, or the resulting rule forwards,
            redirects or deletes mail without ``confirm=true``.
    """
    account_id = common.account(args)
    common.check_rate(account_id, "normal")
    return _ACTIONS[args["action"]](account_id, args)
