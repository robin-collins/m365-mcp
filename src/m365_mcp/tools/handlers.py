"""Handler and semantic-validation registries for the unified tools.

Phase 3 registers one handler per unified tool and one function per
``validation_rules`` entry of its spec. ``tools/registry.py`` looks both
up at call time, so registration order does not matter.

Example:
    @register_validation_rule("m365_list")
    def _limit_needs_email(args: dict[str, Any]) -> None:
        ...  # raise ValidationError with the spec's exact error text

    @register_handler("m365_list")
    def m365_list(args: dict[str, Any]) -> dict[str, Any]:
        return {..., "summary": "Returned 3 emails."}
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from ..tool_specs import load_index

Handler = Callable[[dict[str, Any]], dict[str, Any] | Awaitable[dict[str, Any]]]
ValidationRule = Callable[[dict[str, Any]], None]

_F = TypeVar("_F", bound=Callable[..., Any])

HANDLERS: dict[str, Handler] = {}
VALIDATION_RULES: dict[str, list[ValidationRule]] = {}


def _check_tool_name(tool_name: str) -> None:
    if tool_name not in load_index()["tool_order"]:
        raise KeyError(f"Unknown unified tool {tool_name!r}")


def register_handler(tool_name: str) -> Callable[[_F], _F]:
    """Register the handler for one unified tool.

    The handler receives the validated arguments dict and returns the
    result dict (``structuredContent``), which must include ``summary``.
    It may be sync or async.

    Args:
        tool_name: Unified tool name from ``index.json``.

    Returns:
        A decorator that registers and returns the handler unchanged.

    Raises:
        KeyError: If the tool is unknown.
        ValueError: If the tool already has a handler.
    """
    _check_tool_name(tool_name)

    def decorator(handler: _F) -> _F:
        if tool_name in HANDLERS:
            raise ValueError(f"{tool_name} already has a handler")
        HANDLERS[tool_name] = handler
        return handler

    return decorator


def register_validation_rule(tool_name: str) -> Callable[[_F], _F]:
    """Register a semantic validation rule for one unified tool.

    Rules run in registration order after JSON Schema validation and before
    the handler. A rule raises ``ValidationError`` (a ``ValueError``) with
    the spec's ``validation_rules`` error text when the arguments break it.

    Args:
        tool_name: Unified tool name from ``index.json``.

    Returns:
        A decorator that registers and returns the rule unchanged.

    Raises:
        KeyError: If the tool is unknown.
    """
    _check_tool_name(tool_name)

    def decorator(rule: _F) -> _F:
        VALIDATION_RULES.setdefault(tool_name, []).append(rule)
        return rule

    return decorator


def get_handler(tool_name: str) -> Handler | None:
    """Return the registered handler for ``tool_name``, if any.

    Args:
        tool_name: Unified tool name.

    Returns:
        The handler, or ``None`` when the tool is not implemented yet.
    """
    return HANDLERS.get(tool_name)


def get_validation_rules(tool_name: str) -> list[ValidationRule]:
    """Return the semantic validation rules registered for ``tool_name``.

    Args:
        tool_name: Unified tool name.

    Returns:
        The rules in registration order (a copy).
    """
    return list(VALIDATION_RULES.get(tool_name, ()))
