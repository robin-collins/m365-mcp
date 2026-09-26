"""Shared plumbing for the unified tool handlers.

Handlers receive arguments that already passed JSON Schema validation
(``tools/registry.py``). This module supplies what every handler needs:

- :func:`account` resolves the optional ``account_id`` (D6);
- :func:`require_confirm` enforces ``confirm=true`` with the spec's text;
- :func:`check_rate` applies the per-account rate limits (§12.5);
- :func:`resolve_mail_folder` / :func:`is_well_known_mail_folder` handle the
  mail folder aliases (§5);
- :func:`resource_op` and :func:`install_generic_handlers` dispatch the
  eight ``m365_*`` tools to per-resource functions, so each domain module
  registers only the resources it owns.

Schema defaults are not filled in by the registry: use :func:`arg` to read
an argument with its spec default.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Literal

from fastmcp.exceptions import ToolError

from ...rate_limit import rate_limiter
from ...services.accounts import resolve_account_id
from ...tool_specs import load_tool_spec
from ...validators import ValidationError, format_validation_error
from .. import handlers

Handler = Callable[[dict[str, Any]], dict[str, Any]]

GENERIC_TOOLS = (
    "m365_list",
    "m365_get",
    "m365_search",
    "m365_get_content",
    "m365_create",
    "m365_update",
    "m365_move",
    "m365_delete",
)

# Mail folder aliases (concept §5) mapped to Graph well-known names.
MAIL_FOLDER_ALIASES = {
    "inbox": "inbox",
    "sent": "sentitems",
    "drafts": "drafts",
    "deleted": "deleteditems",
    "junk": "junkemail",
    "archive": "archive",
    "root": "msgfolderroot",
}
WELL_KNOWN_MAIL_FOLDERS = frozenset(MAIL_FOLDER_ALIASES.values()) | {
    "outbox",
    "conversationhistory",
}
_ALIAS_LIKE = re.compile(r"[A-Za-z]{1,24}")

# tool -> resource -> handler
_RESOURCE_OPS: dict[str, dict[str, Handler]] = {name: {} for name in GENERIC_TOOLS}


def arg(args: dict[str, Any], tool: str, name: str) -> Any:
    """Return ``args[name]``, falling back to the spec default.

    Args:
        args: Validated tool arguments.
        tool: Tool name, used to look up the ``inputSchema`` default.
        name: Top-level parameter name.

    Returns:
        The supplied value, else the schema ``default``, else ``None``.
    """
    if name in args:
        return args[name]
    schema = load_tool_spec(tool)["inputSchema"]["properties"].get(name, {})
    return schema.get("default")


def account(args: dict[str, Any]) -> str:
    """Resolve the call's ``account_id`` to a signed-in account ID."""
    return resolve_account_id(args.get("account_id"))


def require_confirm(args: dict[str, Any], action: str) -> None:
    """Refuse the call unless ``confirm`` is true.

    Args:
        args: Validated tool arguments.
        action: Words that complete "<action> requires confirm=True",
            exactly as in the tool's ``validation_rules``.

    Raises:
        ValidationError: With the spec's confirm text.
    """
    if args.get("confirm") is not True:
        raise ValidationError(
            format_validation_error(
                "confirm",
                False,
                f"{action} requires confirm=True to proceed",
                "Explicit user confirmation",
            )
        )


def check_rate(account_id: str, kind: Literal["sensitive", "normal"]) -> None:
    """Apply the per-account rate limit (sends, shares, deletes: sensitive)."""
    rate_limiter.check(account_id, kind)


def resolve_mail_folder(value: str | None, param: str, default: str = "inbox") -> str:
    """Map a mail folder ID or alias to what Graph accepts.

    Args:
        value: Folder ID, alias, or ``None`` for ``default``.
        param: Parameter name for the error message.
        default: Alias used when ``value`` is ``None``.

    Returns:
        A Graph well-known folder name or the folder ID unchanged.

    Raises:
        ValidationError: If ``value`` looks like an alias but is not one.
    """
    raw = default if value is None else value
    alias = MAIL_FOLDER_ALIASES.get(raw.lower())
    if alias is not None:
        return alias
    if raw.lower() in WELL_KNOWN_MAIL_FOLDERS:
        return raw.lower()
    if _ALIAS_LIKE.fullmatch(raw):
        raise ValidationError(
            format_validation_error(
                param,
                raw,
                "unknown folder alias",
                "a folder ID or one of inbox, sent, drafts, deleted, junk, archive",
            )
        )
    return raw


def is_well_known_mail_folder(value: str) -> bool:
    """Return whether ``value`` names a well-known (protected) mail folder."""
    lowered = value.lower()
    return lowered in MAIL_FOLDER_ALIASES or lowered in WELL_KNOWN_MAIL_FOLDERS


def resource_op(tool: str, resource: str) -> Callable[[Handler], Handler]:
    """Register the function that runs ``tool`` for one ``resource``.

    Args:
        tool: One of the eight ``m365_*`` tools.
        resource: A value of that tool's ``resource`` enum.

    Returns:
        A decorator that records the function and returns it unchanged.

    Raises:
        KeyError: If the tool is not generic or the resource is not in its
            spec enum, or the pair is already registered.
    """
    if tool not in _RESOURCE_OPS:
        raise KeyError(f"{tool} is not a generic m365_* tool")
    allowed = _resource_enum(tool)
    if resource not in allowed:
        raise KeyError(f"{tool} does not accept resource {resource!r}")

    def decorator(func: Handler) -> Handler:
        if resource in _RESOURCE_OPS[tool]:
            raise KeyError(f"{tool} already has a handler for {resource!r}")
        _RESOURCE_OPS[tool][resource] = func
        return func

    return decorator


def registered_resources(tool: str) -> dict[str, Handler]:
    """Return the per-resource functions registered for a generic tool."""
    return dict(_RESOURCE_OPS[tool])


def _resource_enum(tool: str) -> list[str]:
    schema = load_tool_spec(tool)["inputSchema"]["properties"]
    if "resource" in schema:
        return list(schema["resource"]["enum"])
    return list(schema["resources"]["items"]["enum"])


def _dispatch(tool: str) -> Handler:
    def handler(args: dict[str, Any]) -> dict[str, Any]:
        resource = args["resource"]
        func = _RESOURCE_OPS[tool].get(resource)
        if func is None:
            raise ToolError(f"{tool} for resource '{resource}' is not implemented yet")
        return func(args)

    handler.__name__ = f"{tool}_dispatch"
    return handler


def install_generic_handlers() -> None:
    """Register the dispatching handler for each ``m365_*`` tool once.

    ``m365_search`` takes a ``resources`` list, so it is not dispatched
    here; its module registers its own handler.
    """
    for tool in GENERIC_TOOLS:
        if tool == "m365_search" or handlers.get_handler(tool) is not None:
            continue
        handlers.register_handler(tool)(_dispatch(tool))
