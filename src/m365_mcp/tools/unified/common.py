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

from ...cursors import cursor_codec
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


# ----------------------------------------------------------------------
# Cross-resource rules for the generic tools (spec validation_rules)
# ----------------------------------------------------------------------

# tool -> parameter -> resources it applies to
APPLIES_TO: dict[str, dict[str, tuple[str, ...]]] = {
    "m365_list": {
        "container_id": ("email", "email_folder", "event", "contact", "drive_item"),
        "path": ("drive_item",),
        "email_filter": ("email",),
        "start": ("event",),
        "end": ("event",),
        "item_type": ("drive_item",),
        "recursive": ("email_folder", "drive_item"),
        "max_depth": ("email_folder", "drive_item"),
        "include_hidden": ("email_folder",),
    },
    "m365_get": {
        "path": ("drive_item",),
        "include_body": ("email", "event"),
        "body_max_chars": ("email", "event"),
    },
    "m365_move": {
        "destination_path": ("drive_item",),
        "new_name": ("drive_item",),
    },
    "m365_delete": {"cancellation_message": ("event",)},
    "m365_get_content": {"attachment_id": ("email",)},
}

CREATE_OBJECTS = {
    "email_folder": "email_folder",
    "calendar": "calendar",
    "contact": "contact",
    "contact_folder": "contact_folder",
    "drive_item": "drive_folder",
}
UPDATE_OBJECTS = {
    "email": "email_changes",
    "email_folder": "email_folder_changes",
    "contact": "contact_changes",
    "drive_item": "drive_item_changes",
}
CONTENT_MODES = {
    "drive_item": ("download", "download_url"),
    "email": ("download",),
    "contact": ("vcard",),
}


def invalid(param: str, reason: str, expected: str | None = None) -> ValidationError:
    """Build a spec-style error that has no ``'<value>'`` part.

    Args:
        param: Parameter name.
        reason: Why it is invalid.
        expected: Optional correction hint.

    Returns:
        A ``ValidationError`` reading ``Invalid <param>: <reason>[. Expected: ...]``.
    """
    text = f"Invalid {param}: {reason}"
    if expected:
        text += f". Expected: {expected}"
    return ValidationError(text)


def _quoted(resources: tuple[str, ...]) -> str:
    return " or ".join(f"'{r}'" for r in resources)


def reject_inapplicable(tool: str, args: dict[str, Any]) -> None:
    """Reject parameters that do not apply to the chosen resource.

    Raises:
        ValidationError: With the spec's "only valid with resource=" text.
    """
    resource = args.get("resource")
    for param, resources in APPLIES_TO.get(tool, {}).items():
        if args.get(param) is None or resource in resources:
            continue
        if tool == "m365_delete":
            raise invalid(param, f"only valid for resource={_quoted(resources)}")
        raise invalid(
            param,
            f"only valid with resource={_quoted(resources)}",
            f"remove {param} or use resource={_quoted(resources)}",
        )


def _exactly_one_object(args: dict[str, Any], objects: dict[str, str]) -> None:
    resource = args["resource"]
    wanted = objects[resource]
    creating = objects is CREATE_OBJECTS
    for name in objects.values():
        if name != wanted and args.get(name) is not None:
            expected = f"supply only the '{wanted}' object" if creating else wanted
            raise invalid(name, f"resource is '{resource}'", expected)
    if args.get(wanted) is None:
        expected = f"supply the '{wanted}' object" if creating else wanted
        raise invalid(wanted, f"required when resource='{resource}'", expected)


def _list_rules(args: dict[str, Any]) -> None:
    reject_inapplicable("m365_list", args)
    if args.get("container_id") is not None and args.get("path") is not None:
        raise invalid(
            "path",
            "cannot be combined with container_id",
            "one of container_id or path",
        )


def _get_rules(args: dict[str, Any]) -> None:
    reject_inapplicable("m365_get", args)
    has_id, has_path = args.get("id") is not None, args.get("path") is not None
    if has_id and has_path:
        raise invalid("path", "cannot be combined with id")
    if not has_id and not has_path:
        raise invalid("id", "required unless resource='drive_item' with path")


def _create_rules(args: dict[str, Any]) -> None:
    _exactly_one_object(args, CREATE_OBJECTS)


def _update_rules(args: dict[str, Any]) -> None:
    _exactly_one_object(args, UPDATE_OBJECTS)


def _move_rules(args: dict[str, Any]) -> None:
    reject_inapplicable("m365_move", args)
    has_id = args.get("destination_id") is not None
    has_path = args.get("destination_path") is not None
    if has_id and has_path:
        raise invalid("destination_path", "cannot be combined with destination_id")
    if not has_id and not has_path:
        raise invalid("destination_id", "required")


def _delete_rules(args: dict[str, Any]) -> None:
    require_confirm(args, "delete")
    reject_inapplicable("m365_delete", args)


def _content_rules(args: dict[str, Any]) -> None:
    resource, mode = args["resource"], args["mode"]
    modes = CONTENT_MODES[resource]
    if mode not in modes:
        raise ValidationError(
            format_validation_error(
                "mode", mode, f"not valid for resource '{resource}'", " or ".join(modes)
            )
        )
    reject_inapplicable("m365_get_content", args)
    if resource == "email" and args.get("attachment_id") is None:
        raise invalid("attachment_id", "required for resource='email'")
    if mode == "download" and args.get("save_path") is None:
        raise invalid("save_path", "required for mode='download'")


Rule = Callable[[dict[str, Any]], None]

_GENERIC_RULES: dict[str, Rule] = {
    "m365_list": _list_rules,
    "m365_get": _get_rules,
    "m365_create": _create_rules,
    "m365_update": _update_rules,
    "m365_move": _move_rules,
    "m365_delete": _delete_rules,
    "m365_get_content": _content_rules,
}


def install_generic_rules() -> None:
    """Register the cross-resource rules once, ahead of per-tool rules."""
    for tool, rule in _GENERIC_RULES.items():
        if rule not in handlers.get_validation_rules(tool):
            handlers.register_validation_rule(tool)(rule)


# ----------------------------------------------------------------------
# Cursors
# ----------------------------------------------------------------------


def _cursor_request(args: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in args.items() if k != "refresh"}


def encode_cursor(
    args: dict[str, Any],
    account_id: str,
    resource: str,
    *,
    next_link: str | None = None,
    offset: int | None = None,
    sub_cursors: dict[str, Any] | None = None,
) -> str:
    """Encode the next-page cursor, bound to this exact request.

    Args:
        args: The validated tool arguments (``refresh`` is ignored).
        account_id: Resolved account ID.
        resource: Resource the cursor pages through.
        next_link: Graph ``@odata.nextLink``, or
        offset: an item offset (tree modes, client-side matching), or
        sub_cursors: per-resource positions for multi-resource search.

    Returns:
        The opaque cursor string.
    """
    return cursor_codec.encode(
        account_id,
        resource,
        _cursor_request(args),
        next_link=next_link,
        offset=offset,
        sub_cursors=sub_cursors,
    )


def decode_cursor(args: dict[str, Any], account_id: str, resource: str) -> Any:
    """Decode ``args['cursor']`` for this request.

    Returns:
        The ``DecodedCursor``, or ``None`` when no cursor was passed.

    Raises:
        ValidationError: If the cursor was tampered with, is expired, or was
            issued for a different request.
    """
    cursor = args.get("cursor")
    if not cursor:
        return None
    return cursor_codec.decode(cursor, account_id, resource, _cursor_request(args))
