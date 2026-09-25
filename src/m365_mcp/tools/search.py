from typing import Any, Sequence
from ..mcp_instance import mcp
from ..services import search as search_service
from ..validators import (
    ValidationError,
    format_validation_error,
    validate_choices,
    validate_folder_choice,
    validate_limit,
)

# Common constants (using from email.py as they are consistent across files)
from .email import EMAIL_FOLDER_NAMES, FOLDERS

MAX_SEARCH_QUERY_LENGTH = 512
ALLOWED_SEARCH_ENTITY_TYPES: Sequence[str] = ("message", "event", "driveItem")


def _validate_search_query(query: str, param_name: str = "query") -> str:
    """Ensure search queries are non-empty and within length bounds."""
    if not isinstance(query, str):
        reason = "must be a string"
        raise ValidationError(
            format_validation_error(
                param_name,
                query,
                reason,
                f"1-{MAX_SEARCH_QUERY_LENGTH} characters",
            )
        )
    trimmed = query.strip()
    if not trimmed:
        reason = "cannot be empty"
        raise ValidationError(
            format_validation_error(
                param_name,
                query,
                reason,
                f"1-{MAX_SEARCH_QUERY_LENGTH} characters",
            )
        )
    if len(trimmed) > MAX_SEARCH_QUERY_LENGTH:
        reason = f"must be <= {MAX_SEARCH_QUERY_LENGTH} characters"
        raise ValidationError(
            format_validation_error(
                param_name,
                trimmed,
                reason,
                f"1-{MAX_SEARCH_QUERY_LENGTH} characters",
            )
        )
    return trimmed


def _validate_entity_types(
    entity_types: list[str] | tuple[str, ...] | str | None,
) -> list[str]:
    """Validate unified search entity type selections."""
    if entity_types is None:
        return list(ALLOWED_SEARCH_ENTITY_TYPES)
    if isinstance(entity_types, str):
        candidate_iterable: Sequence[str] = [entity_types]
    else:
        candidate_iterable = entity_types
        if not isinstance(candidate_iterable, (list, tuple)):
            raise ValidationError(
                format_validation_error(
                    "entity_types",
                    entity_types,
                    "must be a list of entity types",
                    f"Subset of {sorted(ALLOWED_SEARCH_ENTITY_TYPES)}",
                )
            )
    validated: list[str] = []
    for index, value in enumerate(candidate_iterable):
        validated.append(
            validate_choices(
                value,
                ALLOWED_SEARCH_ENTITY_TYPES,
                f"entity_types[{index}]",
            )
        )
    return validated


# search_files
@mcp.tool(
    name="search_files",
    annotations={
        "title": "Search Files",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "search", "safety_level": "safe"},
)
def search_files(
    query: str,
    account_id: str,
    limit: int = 50,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """📖 Search for files in OneDrive (read-only, safe for unsupervised use)

    Searches file names and content across all accessible OneDrive folders.
    Automatically routes to the appropriate API based on account type:
    - Personal accounts: Uses OneDrive-specific search
    - Work/school accounts: Uses unified search API

    Args:
        query: Search query string (1-512 characters)
        account_id: Microsoft account ID
        limit: Maximum results to return (1-500, default: 50)
        use_cache: Whether to use cache (default: True)
        force_refresh: Bypass cache and fetch fresh data (default: False)

    Returns:
        List of matching files with metadata
    """
    limit = validate_limit(limit, 1, 500, "limit")
    search_query = _validate_search_query(query)
    return search_service.find_files(
        account_id,
        query=search_query,
        limit=limit,
        use_cache=use_cache,
        force_refresh=force_refresh,
    )


# search_emails
@mcp.tool(
    name="search_emails",
    annotations={
        "title": "Search Emails",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "search", "safety_level": "safe"},
)
def search_emails(
    query: str,
    account_id: str,
    limit: int = 50,
    folder: str | None = None,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """📖 Search emails across mailbox (read-only, safe for unsupervised use)

    Searches email subject, body, and sender across all or specific folders.
    Automatically routes to the appropriate API based on account type:
    - Personal accounts: Uses OData $search parameter
    - Work/school accounts: Uses unified search API

    Args:
        query: Search query string (1-512 characters)
        account_id: Microsoft account ID
        limit: Maximum results to return (1-500, default: 50)
        folder: Optional folder to search within (e.g., "inbox", "sent")
        use_cache: Whether to use cache (default: True)
        force_refresh: Bypass cache and fetch fresh data (default: False)

    Returns:
        List of matching emails with metadata
    """
    limit = validate_limit(limit, 1, 500, "limit")
    search_query = _validate_search_query(query)
    folder_path = None
    if folder:
        folder_key = validate_folder_choice(folder, EMAIL_FOLDER_NAMES, "folder")
        folder_path = FOLDERS[folder_key.casefold()]
    return search_service.find_emails(
        account_id,
        query=search_query,
        limit=limit,
        folder=folder,
        folder_path=folder_path,
        use_cache=use_cache,
        force_refresh=force_refresh,
    )


# search_events
@mcp.tool(
    name="search_events",
    annotations={
        "title": "Search Events",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "search", "safety_level": "safe"},
)
def search_events(
    query: str,
    account_id: str,
    days_ahead: int = 365,
    days_back: int = 365,
    limit: int = 50,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """📖 Search calendar events (read-only, safe for unsupervised use)

    Searches event titles, locations, and descriptions within date range.
    Automatically routes to the appropriate API based on account type:
    - Personal accounts: Uses OData $search parameter
    - Work/school accounts: Uses unified search API

    Args:
        query: Search query string (1-512 characters)
        account_id: Microsoft account ID
        days_ahead: Days to look forward (0-730, default: 365)
        days_back: Days to look back (0-730, default: 365)
        limit: Maximum results to return (1-500, default: 50)
        use_cache: Whether to use cache (default: True)
        force_refresh: Bypass cache and fetch fresh data (default: False)

    Returns:
        List of matching events
    """
    days_ahead = validate_limit(days_ahead, 0, 730, "days_ahead")
    days_back = validate_limit(days_back, 0, 730, "days_back")
    limit = validate_limit(limit, 1, 500, "limit")
    search_query = _validate_search_query(query)
    return search_service.find_events(
        account_id,
        query=search_query,
        days_ahead=days_ahead,
        days_back=days_back,
        limit=limit,
        use_cache=use_cache,
        force_refresh=force_refresh,
    )


# search_contacts
@mcp.tool(
    name="search_contacts",
    annotations={
        "title": "Search Contacts",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "search", "safety_level": "safe"},
)
def search_contacts(
    query: str,
    account_id: str,
    limit: int = 50,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """📖 Search contacts (read-only, safe for unsupervised use)

    Searches contact names, email addresses, and phone numbers.
    Uses $filter with prefix matching (startswith) for all account types
    due to Graph API limitations.

    Note: Contact search is limited to prefix matching and may not find
    matches in the middle of names.

    Args:
        query: Search query string (1-512 characters, used as prefix)
        account_id: Microsoft account ID
        limit: Maximum results to return (1-500, default: 50)
        use_cache: Whether to use cache (default: True)
        force_refresh: Bypass cache and fetch fresh data (default: False)

    Returns:
        List of matching contacts
    """
    limit = validate_limit(limit, 1, 500, "limit")
    search_query = _validate_search_query(query)
    return search_service.find_contacts(
        account_id,
        query=search_query,
        limit=limit,
        use_cache=use_cache,
        force_refresh=force_refresh,
    )


# search_unified
@mcp.tool(
    name="search_unified",
    annotations={
        "title": "Unified Search",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "search", "safety_level": "safe"},
)
def search_unified(
    query: str,
    account_id: str,
    entity_types: list[str] | None = None,
    limit: int = 50,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    """📖 Search across multiple Microsoft 365 resources (read-only, safe for unsupervised use)

    Searches emails, events, and files simultaneously.
    Automatically routes to the appropriate API based on account type:
    - Personal accounts: Performs sequential searches for each entity type
    - Work/school accounts: Uses unified search API for parallel search

    Args:
        query: Search query string (1-512 characters)
        account_id: Microsoft account ID
        entity_types: Types to search: 'message', 'event', 'driveItem' (default: all)
        limit: Maximum results per type (1-500, default: 50)
        use_cache: Whether to use cache (default: True)
        force_refresh: Bypass cache and fetch fresh data (default: False)

    Returns:
        Dictionary with results grouped by entity type
    """
    validated_entity_types = _validate_entity_types(entity_types)
    limit = validate_limit(limit, 1, 500, "limit")
    search_query = _validate_search_query(query)
    return search_service.find_unified(
        account_id,
        query=search_query,
        entity_types=validated_entity_types,
        limit=limit,
        use_cache=use_cache,
        force_refresh=force_refresh,
    )
