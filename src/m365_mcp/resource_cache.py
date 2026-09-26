"""Resource-keyed cache for the unified tools (concept §7, task U2.12).

Unified tools cache Graph results per resource rather than per tool name.
A key combines the resolved account ID, the resource, the normalised
request parameters and the cursor; the parameters and cursor are hashed,
so no raw request value appears in a key. Entries live in the encrypted
``CacheManager`` and follow ``cache_config.RESOURCE_TTL_POLICIES``.

Mutations invalidate the matching resource keys for their account only,
as declared in ``MUTATION_INVALIDATES``. Values are returned exactly as
fetched: no cache metadata is ever added. The legacy tools keep their
own tool-name keys and are untouched by this module.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from typing import Any, TypeVar

from . import cache as _cache
from .cache_config import generate_cache_key
from .validators import ValidationError, format_validation_error

logger = logging.getLogger(__name__)

T = TypeVar("T")

RESOURCES: tuple[str, ...] = (
    "email",
    "email_folder",
    "email_rule",
    "event",
    "calendar",
    "contact",
    "contact_folder",
    "drive_item",
)

SCOPE_ALL = "all"

# Table key for tools that have no ``resource`` parameter.
ANY_RESOURCE = "*"

# Parameters that never change what Graph returns.
_IGNORED_PARAMS = frozenset({"refresh", "account_id"})

_EMAIL = ("email", "email_folder")  # messages plus folder counts

# Every mutating unified tool (readOnlyHint false; account_/admin_ tools
# excluded) -> its ``resource`` value (or ANY_RESOURCE) -> resources whose
# cached entries the call makes stale for that account.
MUTATION_INVALIDATES: dict[str, dict[str, tuple[str, ...]]] = {
    # Downloads and exports write local files only; Graph data is unchanged.
    "m365_get_content": {"drive_item": (), "email": (), "contact": ()},
    "m365_create": {
        "email_folder": ("email_folder",),
        "calendar": ("calendar",),
        "contact": ("contact",),
        "contact_folder": ("contact_folder",),
        "drive_item": ("drive_item",),
    },
    "m365_update": {
        "email": _EMAIL,  # is_read changes unread counts
        "email_folder": ("email_folder",),
        "contact": ("contact",),
        "drive_item": ("drive_item",),
    },
    "m365_move": {
        "email": _EMAIL,
        "email_folder": ("email_folder",),
        "contact": ("contact",),
        "drive_item": ("drive_item",),
    },
    "m365_delete": {
        "email": _EMAIL,
        "email_folder": ("email_folder", "email"),  # contents go with it
        "email_rule": ("email_rule",),
        "event": ("event",),
        "calendar": ("calendar", "event"),
        "contact": ("contact",),
        "contact_folder": ("contact_folder", "contact"),
        "drive_item": ("drive_item",),
    },
    "email_create_draft": {ANY_RESOURCE: _EMAIL},
    "email_send": {ANY_RESOURCE: _EMAIL},
    "email_reply": {ANY_RESOURCE: _EMAIL},
    "email_forward": {ANY_RESOURCE: _EMAIL},
    "calendar_create_event": {ANY_RESOURCE: ("event",)},
    "calendar_update_event": {ANY_RESOURCE: ("event",)},
    "calendar_respond": {ANY_RESOURCE: ("event",)},
    # Forwarding sends a message, which may land in Sent Items.
    "calendar_forward": {ANY_RESOURCE: _EMAIL},
    "drive_upload": {ANY_RESOURCE: ("drive_item",)},
    "drive_copy": {ANY_RESOURCE: ("drive_item",)},
    "drive_share": {ANY_RESOURCE: ("drive_item",)},
    "email_folder_mark_all_read": {ANY_RESOURCE: _EMAIL},
    "email_folder_empty": {ANY_RESOURCE: _EMAIL},
    "email_rule_manage": {ANY_RESOURCE: ("email_rule",)},
}


def _check_resource(resource: str) -> None:
    """Reject resources that have no cache policy."""
    if resource not in RESOURCES:
        raise ValidationError(
            format_validation_error(
                "resource",
                resource,
                "not a cacheable resource",
                ", ".join(RESOURCES),
            )
        )


def _normalise(value: Any) -> Any:
    """Drop None values from mappings recursively."""
    if isinstance(value, Mapping):
        return {k: _normalise(v) for k, v in value.items() if v is not None}
    if isinstance(value, (list, tuple)):
        return [_normalise(v) for v in value]
    return value


def cache_key(account_id: str, resource: str, params: Mapping[str, Any]) -> str:
    """Build the cache key for one unified-tool request.

    ``None`` values, ``refresh`` and ``account_id`` are dropped; the
    remaining parameters and the cursor are hashed from canonical JSON
    (sorted keys), so equivalent requests share a key and raw values never
    appear in it.

    Args:
        account_id: The resolved account ID (not an email alias).
        resource: One of ``RESOURCES``.
        params: The tool arguments, including ``cursor`` when paging.

    Returns:
        A key of the form ``<resource>:<account_id>:<hash>``.

    Raises:
        ValidationError: If ``resource`` is not cacheable.
    """
    return generate_cache_key(account_id, resource, _key_parameters(resource, params))


def _key_parameters(resource: str, params: Mapping[str, Any]) -> dict[str, Any]:
    """Return the normalised structure hashed into a request's key."""
    _check_resource(resource)
    normalised = _normalise(
        {k: v for k, v in params.items() if k not in _IGNORED_PARAMS}
    )
    cursor = normalised.pop("cursor", None)
    return {"params": normalised, "cursor": cursor}


def get_or_fetch(
    account_id: str,
    resource: str,
    params: Mapping[str, Any],
    fetch: Callable[[], T],
    *,
    refresh: bool = False,
) -> T:
    """Return a cached result, or fetch and cache it.

    Fresh and stale entries are served from cache; expired or missing
    entries are fetched. ``refresh=True`` skips the read but still stores
    the fetched value. The value is returned exactly as fetched (or as it
    was stored), with no cache metadata added.

    Args:
        account_id: The resolved account ID.
        resource: One of ``RESOURCES``.
        params: The tool arguments that shape the Graph request.
        fetch: Zero-argument callable returning a JSON-serialisable value.
        refresh: Bypass the cached value and fetch fresh data.

    Returns:
        The cached or freshly fetched value.

    Raises:
        ValidationError: If ``resource`` is not cacheable.
    """
    key_params = _key_parameters(resource, params)
    manager = _cache.get_cache_manager()
    if not refresh:
        cached = manager.get_cached(
            account_id, resource, key_params, enqueue_refresh=False
        )
        if cached is not None:
            return cached[0]

    value = fetch()
    try:
        manager.set_cached(account_id, resource, key_params, value)
    except ValueError:
        logger.warning(
            "Result too large to cache",
            extra={"resource": resource},
        )
    return value


def invalidate(
    account_id: str | None,
    resources: Iterable[str],
    reason: str = "mutation",
) -> int:
    """Remove cached entries for the given resources.

    Args:
        account_id: The resolved account ID, or None for every account.
        resources: Resources from ``RESOURCES`` to clear.
        reason: Recorded in the cache invalidation log.

    Returns:
        Number of entries removed.

    Raises:
        ValidationError: If a resource is not cacheable.
    """
    targets = tuple(dict.fromkeys(resources))
    for resource in targets:
        _check_resource(resource)
    if not targets:
        return 0
    manager = _cache.get_cache_manager()
    return sum(
        manager.invalidate_pattern(
            f"{resource}:*", account_id=account_id, reason=reason
        )
        for resource in targets
    )


def invalidate_scope(
    scope: str,
    account_id: str | None = None,
    reason: str = "manual",
) -> int:
    """Clear the cache for an ``admin_cache_invalidate`` scope.

    ``all`` clears every unified resource; legacy tool-name entries are
    left to the legacy tools.

    Args:
        scope: A resource from ``RESOURCES`` or ``all``.
        account_id: The resolved account ID, or None for every account.
        reason: Recorded in the cache invalidation log.

    Returns:
        Number of entries removed.

    Raises:
        ValidationError: If ``scope`` is not a valid scope.
    """
    if scope == SCOPE_ALL:
        return invalidate(account_id, RESOURCES, reason)
    if scope not in RESOURCES:
        raise ValidationError(
            format_validation_error(
                "scope",
                scope,
                "unknown cache scope",
                ", ".join((*RESOURCES, SCOPE_ALL)),
            )
        )
    return invalidate(account_id, (scope,), reason)


def invalidate_for_call(tool: str, args: Mapping[str, Any], account_id: str) -> int:
    """Invalidate the resources a unified tool call may have changed.

    Tools absent from ``MUTATION_INVALIDATES`` (read-only and admin
    tools) invalidate nothing.

    Args:
        tool: Unified tool name.
        args: The call's arguments (``resource`` for generic tools).
        account_id: The resolved account ID the call acted on.

    Returns:
        Number of entries removed.

    Raises:
        ValidationError: If a generic tool's ``resource`` has no entry.
    """
    entry = MUTATION_INVALIDATES.get(tool)
    if entry is None:
        return 0
    key = ANY_RESOURCE if ANY_RESOURCE in entry else args.get("resource")
    if key not in entry:
        raise ValidationError(
            format_validation_error(
                "resource",
                key,
                f"not supported by {tool}",
                ", ".join(entry),
            )
        )
    return invalidate(account_id, entry[key], reason=tool)
