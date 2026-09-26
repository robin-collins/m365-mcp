"""Account and admin tools: sign-in, accounts, cache and server info.

None of these call Microsoft Graph. Sign-in goes through the server-side
device-flow store (``auth_sessions``); the cache tools read the shared
``CacheManager``; ``admin_server_info`` reports the running
configuration.
"""

from __future__ import annotations

from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from fastmcp.exceptions import ToolError
from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS

from ... import auth, auth_sessions, cache, resource_cache
from ...services import accounts as accounts_service
from ...tool_specs import load_index
from ...validators import ValidationError, format_validation_error
from .. import cache_tools
from ..handlers import register_handler, register_validation_rule
from .common import account, arg, invalid

PACKAGE = "m365-mcp"
PERSONAL_ONLY_ERROR = "Only personal Microsoft accounts are supported"
_TASK_FIELDS = ("task_id", "operation", "status", "priority", "retry_count", "error")
_WARMING_COUNTS = (
    "operations_total",
    "operations_completed",
    "operations_skipped",
    "operations_failed",
)


def _plural(count: int, word: str, plural: str | None = None) -> str:
    return f"{count} {word if count == 1 else plural or word + 's'}"


# ----------------------------------------------------------------------
# Accounts (U3.24-U3.26)
# ----------------------------------------------------------------------


@register_handler("account_list")
def account_list(args: dict[str, Any]) -> dict[str, Any]:
    """List the signed-in accounts.

    Args:
        args: Validated (empty) arguments.

    Returns:
        ``accounts`` (``account_id``, ``email``, ``display_name``) and
        ``summary``.
    """
    accounts = accounts_service.list_account_records()
    return {
        "accounts": accounts,
        "summary": f"{_plural(len(accounts), 'account')} signed in.",
    }


@register_handler("account_auth_begin")
def account_auth_begin(args: dict[str, Any]) -> dict[str, Any]:
    """Start a device-code sign-in; the device code stays on the server.

    Args:
        args: Validated (empty) arguments.

    Returns:
        ``auth_session_id``, ``verification_url``, ``user_code``,
        ``expires_in`` and ``summary``.
    """
    started = auth_sessions.store.begin()
    return {
        **started,
        "summary": (
            f"Visit {started['verification_url']} and enter {started['user_code']}."
        ),
    }


@register_handler("account_auth_complete")
def account_auth_complete(args: dict[str, Any]) -> dict[str, Any]:
    """Poll a sign-in once, without blocking.

    Args:
        args: Validated arguments with ``auth_session_id``.

    Returns:
        ``status`` (``pending`` or ``success``), ``account`` and
        ``summary``.

    Raises:
        ValidationError: If the session is unknown or expired, or a work or
            school account signed in.
        ToolError: If Microsoft rejected the sign-in.
    """
    try:
        result = auth_sessions.store.complete(args["auth_session_id"])
    except auth.PersonalAccountRequiredError as exc:
        raise ValidationError(PERSONAL_ONLY_ERROR) from exc
    except RuntimeError as exc:
        raise ToolError(str(exc)) from exc
    if result["status"] == "pending":
        summary = "Waiting for the user to enter the code."
    else:
        summary = f"Signed in {result['account']['email']}."
    return {**result, "summary": summary}


# ----------------------------------------------------------------------
# Cache (U3.27, U3.28)
# ----------------------------------------------------------------------


def _iso(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, UTC).isoformat()


def _task(task: dict[str, Any]) -> dict[str, Any]:
    record = {name: task.get(name) for name in _TASK_FIELDS}
    record["retry_count"] = record["retry_count"] or 0
    for name in ("created_at", "started_at", "completed_at"):
        record[name] = _iso(task.get(name))
    return record


def _stats() -> tuple[dict[str, Any], str]:
    raw = cache.get_cache_manager().get_stats()
    stats = {
        "entry_count": raw["entry_count"],
        "total_bytes": raw["total_bytes"],
        "max_bytes": raw["max_bytes"],
        "usage_percent": raw["usage_percent"],
        "total_hits": raw["total_hits"],
        "by_resource": {
            name: {k: v for k, v in row.items() if k != "resource_type"}
            for name, row in raw["by_resource"].items()
        },
    }
    summary = (
        f"{_plural(stats['entry_count'], 'cached entry', 'cached entries')}, "
        f"{stats['total_bytes']} bytes ({stats['usage_percent']:.1f}% of the limit)."
    )
    return stats, summary


def _warming() -> tuple[dict[str, Any], str]:
    provider = cache_tools._warming_status_provider
    raw: dict[str, Any] = {} if provider is None else provider.get_warming_status()
    if provider is None or str(raw.get("status", "")).startswith(
        "Cache warming disabled"
    ):
        status = "disabled"
    elif raw.get("is_warming"):
        status = "warming"
    elif raw.get("completed_at"):
        status = "completed"
    else:
        status = "idle"
    warming = {
        "status": status,
        "is_warming": bool(raw.get("is_warming")),
        **{name: int(raw.get(name) or 0) for name in _WARMING_COUNTS},
        "progress_percent": float(raw.get("progress_percent") or 0.0),
    }
    done, total = warming["operations_completed"], warming["operations_total"]
    summary = {
        "disabled": "Cache warming is disabled.",
        "warming": (
            f"Cache warming in progress: {warming['progress_percent']}% "
            f"({done} of {total})."
        ),
        "completed": f"Cache warming completed ({done} of {total}).",
        "idle": "Cache warming has not started.",
    }[status]
    return warming, summary


@register_validation_rule("admin_cache_get")
def _task_view_needs_id(args: dict[str, Any]) -> None:
    """Require ``task_id`` for ``view='task'``."""
    if args["view"] == "task" and args.get("task_id") is None:
        raise invalid("task_id", "required for view='task'")


@register_handler("admin_cache_get")
def admin_cache_get(args: dict[str, Any]) -> dict[str, Any]:
    """Show cache statistics, background tasks, one task or warming status.

    Args:
        args: Validated ``admin_cache_get`` arguments.

    Returns:
        ``view``, ``stats``, ``tasks``, ``warming`` (fields for other views
        are null) and ``summary``.

    Raises:
        ValidationError: If ``task_id`` names no task.
    """
    view = args["view"]
    result: dict[str, Any] = {"view": view, "stats": None, "tasks": None}
    result["warming"] = None
    manager = cache.get_cache_manager()
    if view == "stats":
        result["stats"], summary = _stats()
    elif view == "warming":
        result["warming"], summary = _warming()
    elif view == "task":
        task = manager.get_task_status(args["task_id"])
        if task is None:
            raise ValidationError(
                format_validation_error(
                    "task_id",
                    args["task_id"],
                    "no such task",
                    "a task_id from admin_cache_get view='tasks'",
                )
            )
        result["tasks"] = [_task(task)]
        summary = f"Task {task['task_id']} is {task['status']}."
    else:
        account_id = account(args) if args.get("account_id") else None
        tasks = manager.list_tasks(
            account_id=account_id,
            status=args.get("status"),
            limit=arg(args, "admin_cache_get", "limit"),
        )
        result["tasks"] = [_task(task) for task in tasks]
        summary = f"{_plural(len(tasks), 'background task')}."
    return {**result, "summary": summary}


@register_handler("admin_cache_invalidate")
def admin_cache_invalidate(args: dict[str, Any]) -> dict[str, Any]:
    """Clear cached results for one resource type or all, for one or all accounts.

    Args:
        args: Validated ``admin_cache_invalidate`` arguments.

    Returns:
        ``scope``, ``entries_removed`` and ``summary``.
    """
    scope = args["scope"]
    account_id = account(args) if args.get("account_id") else None
    removed = resource_cache.invalidate_scope(
        scope, account_id, args.get("reason") or "manual"
    )
    what = "cached" if scope == resource_cache.SCOPE_ALL else f"cached {scope}"
    return {
        "scope": scope,
        "entries_removed": removed,
        "summary": f"Removed {removed} {what} {'entry' if removed == 1 else 'entries'}.",
    }


# ----------------------------------------------------------------------
# Server info (U3.29)
# ----------------------------------------------------------------------


def _cache_enabled() -> bool:
    try:
        cache.get_cache_manager()
    except Exception:  # noqa: BLE001 - an unusable cache means it is off
        return False
    return True


@register_handler("admin_server_info")
def admin_server_info(args: dict[str, Any]) -> dict[str, Any]:
    """Report the version, MCP protocol versions and enabled toolsets.

    Args:
        args: Validated (empty) arguments.

    Returns:
        ``version``, ``protocol_versions``, ``toolsets_enabled``,
        ``tool_count``, ``cache_enabled`` and ``summary``.
    """
    # Imported here: the registry imports this package while it loads.
    from ..registry import _parse_toolsets

    try:
        pkg_version = version(PACKAGE)
    except PackageNotFoundError:
        pkg_version = "dev"
    tiers = _parse_toolsets(None)  # M365_MCP_TOOLSETS, else the default
    index = load_index()
    tool_count = sum(len(index["tiers"][tier]) for tier in tiers)
    return {
        "version": pkg_version,
        "protocol_versions": list(SUPPORTED_PROTOCOL_VERSIONS),
        "toolsets_enabled": tiers,
        "tool_count": tool_count,
        "cache_enabled": _cache_enabled(),
        "summary": f"{PACKAGE} {pkg_version}, {_plural(tool_count, 'tool')}.",
    }
