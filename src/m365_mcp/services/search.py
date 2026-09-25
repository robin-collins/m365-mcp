"""Search service for Microsoft Graph.

This module holds the Graph logic behind the ``search_*`` MCP tools: cached
search entry points (``find_*``) and the account-type router (formerly
``m365_mcp.search_router``). It routes search requests to the appropriate
Microsoft Graph API endpoint based on account type (personal vs
work/school). Personal Microsoft accounts have limited search API support
compared to organizational accounts.

Routing Strategy:
- Personal accounts: Use service-specific endpoints with $search parameter
  (e.g., /me/messages?$search="query")
- Work/school accounts: Use unified search API (/search/query)

Personal Account Limitations:
- No unified search API support
- Contact search limited to prefix matching with $filter
- Search performance may vary from work/school accounts
"""

import datetime as dt
import logging
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import quote

from .. import graph
from ..cache import CacheManager

logger = logging.getLogger(__name__)

SearchResult = list[dict[str, Any]] | dict[str, list[dict[str, Any]]]

EMAIL_FOLDER_SELECT = (
    "id,subject,from,toRecipients,receivedDateTime,hasAttachments,body,"
    "conversationId,isRead"
)


def _get_cache_manager() -> CacheManager:
    """Return the process-wide cache manager.

    The singleton still lives in ``tools.cache_tools``; it is imported lazily
    so this service has no import-time dependency on the tool layer.
    """
    from ..cache import get_cache_manager

    return get_cache_manager()


def _iter_items(data: SearchResult) -> Iterator[dict[str, Any]]:
    """Yield every result item from a list or an entity-type mapping."""
    if isinstance(data, dict):
        for items in data.values():
            yield from items
    else:
        yield from data


def _cached_search(
    account_id: str,
    operation: str,
    cache_params: dict[str, Any],
    use_cache: bool,
    force_refresh: bool,
    fetch: Callable[[], SearchResult],
) -> Any:
    """Serve a search from cache or fetch, tag and store fresh results.

    Cache read and write failures are swallowed so search still works when
    the cache is unavailable.

    Args:
        account_id: Microsoft account identifier.
        operation: Cache operation name (e.g. ``"search_files"``).
        cache_params: Parameters forming the cache key.
        use_cache: Whether to read and write the cache.
        force_refresh: Skip the cache read when True.
        fetch: Callable returning fresh results from Graph.

    Returns:
        Cached or fresh results, each item tagged with ``_cache_status``
        (and ``_cached_at`` when fresh).
    """
    if use_cache and not force_refresh:
        try:
            cached_result = _get_cache_manager().get_cached(
                account_id, operation, cache_params
            )
            if cached_result:
                data, state = cached_result
                for item in _iter_items(data):
                    item["_cache_status"] = state.value
                return data
        except Exception:  # cache failure falls back to Graph
            logger.debug("Cache read failed for %s", operation, exc_info=True)

    results = fetch()

    cached_at = dt.datetime.now(dt.UTC).isoformat()
    for item in _iter_items(results):
        item["_cache_status"] = "fresh"
        item["_cached_at"] = cached_at

    if use_cache:
        try:
            _get_cache_manager().set_cached(
                account_id, operation, cache_params, results
            )
        except Exception:  # cache failure must not fail search
            logger.debug("Cache write failed for %s", operation, exc_info=True)

    return results


def get_account_type(account_id: str) -> str:
    """Return the account type used to route legacy searches.

    Only personal Microsoft accounts can sign in (work/school accounts are
    rejected), so the work/school search routes are no longer reached.

    Args:
        account_id: Microsoft account identifier (unused).

    Returns:
        Always ``"personal"``.
    """
    return "personal"


def find_files(
    account_id: str,
    *,
    query: str,
    limit: int,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """Search OneDrive files, served from cache when possible.

    Args:
        account_id: Microsoft account identifier.
        query: Validated, trimmed search query.
        limit: Maximum number of results.
        use_cache: Whether to read and write the cache.
        force_refresh: Skip the cache read when True.

    Returns:
        List of file summaries with ``id``, ``name``, ``type``, ``size``,
        ``modified`` and ``download_url`` plus cache metadata.
    """

    def fetch() -> list[dict[str, Any]]:
        account_type = get_account_type(account_id)
        items = search_files(account_id, account_type, query, limit)
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

    cache_params = {"query": query, "limit": limit}
    return _cached_search(
        account_id, "search_files", cache_params, use_cache, force_refresh, fetch
    )


def find_emails(
    account_id: str,
    *,
    query: str,
    limit: int,
    folder: str | None = None,
    folder_path: str | None = None,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """Search emails, served from cache when possible.

    With ``folder_path`` the folder's messages endpoint is searched with
    ``$search``; otherwise the search is routed by account type.

    Args:
        account_id: Microsoft account identifier.
        query: Validated, trimmed search query.
        limit: Maximum number of results.
        folder: Folder name as supplied by the caller (part of the cache
            key).
        folder_path: Graph folder path resolved from ``folder``.
        use_cache: Whether to read and write the cache.
        force_refresh: Skip the cache read when True.

    Returns:
        List of email message dictionaries plus cache metadata.
    """

    def fetch() -> list[dict[str, Any]]:
        if folder_path:
            params = {
                "$search": f'"{query}"',
                "$top": limit,
                "$select": EMAIL_FOLDER_SELECT,
            }
            return list(
                graph.request_paginated(
                    f"/me/mailFolders/{folder_path}/messages",
                    account_id,
                    params=params,
                    limit=limit,
                )
            )
        account_type = get_account_type(account_id)
        return search_emails(account_id, account_type, query, limit)

    cache_params = {"query": query, "limit": limit, "folder": folder}
    return _cached_search(
        account_id, "search_emails", cache_params, use_cache, force_refresh, fetch
    )


def _event_in_range(
    event: dict[str, Any], start: dt.datetime, end: dt.datetime
) -> bool:
    """Return True when an event overlaps the ``start``-``end`` window."""
    start_info = event.get("start", {})
    end_info = event.get("end", {})
    if not isinstance(start_info, dict) or not isinstance(end_info, dict):
        return False
    start_raw = start_info.get("dateTime")
    end_raw = end_info.get("dateTime")
    if not isinstance(start_raw, str) or not isinstance(end_raw, str):
        return False
    try:
        event_start = dt.datetime.fromisoformat(start_raw)
        event_end = dt.datetime.fromisoformat(end_raw)
    except ValueError:
        return False
    return event_start <= end and event_end >= start


def find_events(
    account_id: str,
    *,
    query: str,
    days_ahead: int,
    days_back: int,
    limit: int,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """Search calendar events, served from cache when possible.

    Results are filtered to the date window unless both ``days_ahead`` and
    ``days_back`` are 365.

    Args:
        account_id: Microsoft account identifier.
        query: Validated, trimmed search query.
        days_ahead: Days to look forward.
        days_back: Days to look back.
        limit: Maximum number of results.
        use_cache: Whether to read and write the cache.
        force_refresh: Skip the cache read when True.

    Returns:
        List of calendar event dictionaries plus cache metadata.
    """

    def fetch() -> list[dict[str, Any]]:
        account_type = get_account_type(account_id)
        events = search_events(account_id, account_type, query, limit)
        if days_ahead != 365 or days_back != 365:
            now = dt.datetime.now(dt.UTC)
            start = now - dt.timedelta(days=days_back)
            end = now + dt.timedelta(days=days_ahead)
            events = [e for e in events if _event_in_range(e, start, end)]
        return events

    cache_params = {
        "query": query,
        "days_ahead": days_ahead,
        "days_back": days_back,
        "limit": limit,
    }
    return _cached_search(
        account_id, "search_events", cache_params, use_cache, force_refresh, fetch
    )


def find_contacts(
    account_id: str,
    *,
    query: str,
    limit: int,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """Search contacts by name prefix, served from cache when possible.

    Args:
        account_id: Microsoft account identifier.
        query: Validated, trimmed search query (prefix).
        limit: Maximum number of results.
        use_cache: Whether to read and write the cache.
        force_refresh: Skip the cache read when True.

    Returns:
        List of contact dictionaries plus cache metadata.
    """

    def fetch() -> list[dict[str, Any]]:
        account_type = get_account_type(account_id)
        return search_contacts(account_id, account_type, query, limit)

    cache_params = {"query": query, "limit": limit}
    return _cached_search(
        account_id, "search_contacts", cache_params, use_cache, force_refresh, fetch
    )


def find_unified(
    account_id: str,
    *,
    query: str,
    entity_types: list[str],
    limit: int,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    """Search several entity types at once, served from cache when possible.

    Args:
        account_id: Microsoft account identifier.
        query: Validated, trimmed search query.
        entity_types: Validated entity types to search.
        limit: Maximum number of results per entity type.
        use_cache: Whether to read and write the cache.
        force_refresh: Skip the cache read when True.

    Returns:
        Mapping of entity type to result list, items tagged with cache
        metadata.
    """

    def fetch() -> dict[str, list[dict[str, Any]]]:
        account_type = get_account_type(account_id)
        return unified_search(account_id, account_type, query, entity_types, limit)

    cache_params = {
        "query": query,
        "entity_types": sorted(entity_types),
        "limit": limit,
    }
    return _cached_search(
        account_id, "search_unified", cache_params, use_cache, force_refresh, fetch
    )


def _odata_string_literal(value: str) -> str:
    """Encode a Python string as an OData single-quoted string literal."""
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def search_emails(
    account_id: str,
    account_type: str,
    query: str,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Route email search to appropriate API based on account type.

    Args:
        account_id: Microsoft account identifier.
        account_type: "personal" or "work_school".
        query: Search query string.
        limit: Maximum number of results to return.

    Returns:
        List of email message dictionaries.

    Raises:
        ValueError: If account_id or query is empty.
        Exception: If Graph API request fails.
    """
    if not account_id:
        raise ValueError("account_id is required")
    if not query:
        raise ValueError("query is required")

    logger.info(
        f"Routing email search for account_type={account_type}, "
        f"query='{query}', limit={limit}"
    )

    if account_type == "personal":
        return _search_emails_odata(account_id, query, limit)
    else:
        # work_school or unknown - try unified search
        return _search_emails_unified(account_id, query, limit)


def _search_emails_unified(
    account_id: str, query: str, limit: int
) -> list[dict[str, Any]]:
    """Search emails using unified search API (work/school accounts).

    Args:
        account_id: Account identifier.
        query: Search query.
        limit: Result limit.

    Returns:
        List of email messages.
    """
    logger.debug(f"Using unified search API for emails: {query}")

    payload = {
        "requests": [
            {
                "entityTypes": ["message"],
                "query": {"queryString": query},
                "from": 0,
                "size": limit,
                "fields": [
                    "subject",
                    "from",
                    "receivedDateTime",
                    "hasAttachments",
                    "bodyPreview",
                ],
            }
        ]
    }

    result = graph.request("POST", "/search/query", account_id=account_id, json=payload)

    if not result or "value" not in result:
        return []

    # Extract hits from unified search response
    messages = []
    for response in result.get("value", []):
        for hit_container in response.get("hitsContainers", []):
            for hit in hit_container.get("hits", []):
                resource = hit.get("resource", {})
                if resource:
                    messages.append(resource)

    return messages[:limit]


def _search_emails_odata(
    account_id: str, query: str, limit: int
) -> list[dict[str, Any]]:
    """Search emails using client-side filtering for personal accounts.

    Note: Personal accounts don't support $search or advanced $filter operations.
    We fetch recent messages and filter client-side by checking if the query
    appears in subject, body preview, or sender name.

    Args:
        account_id: Account identifier.
        query: Search query (case-insensitive).
        limit: Result limit.

    Returns:
        List of email messages matching the query.
    """
    logger.debug(f"Using client-side filter search for emails: {query}")

    # Fetch more messages than needed since we'll filter client-side
    # Request 5x the limit to increase chance of finding matches
    fetch_limit = max(limit * 5, 50)

    params = {
        "$top": fetch_limit,
        "$select": "id,subject,from,receivedDateTime,hasAttachments,bodyPreview",
        "$orderby": "receivedDateTime desc",
    }

    result = graph.request("GET", "/me/messages", account_id=account_id, params=params)

    if not result or "value" not in result:
        return []

    # Filter messages client-side
    query_lower = query.lower()
    matching_messages = []

    for message in result.get("value", []):
        # Check if query appears in subject, body preview, or sender name
        subject = (message.get("subject") or "").lower()
        body_preview = (message.get("bodyPreview") or "").lower()
        from_name = (
            message.get("from", {}).get("emailAddress", {}).get("name") or ""
        ).lower()
        from_address = (
            message.get("from", {}).get("emailAddress", {}).get("address") or ""
        ).lower()

        if (
            query_lower in subject
            or query_lower in body_preview
            or query_lower in from_name
            or query_lower in from_address
        ):
            matching_messages.append(message)

            if len(matching_messages) >= limit:
                break

    return matching_messages[:limit]


def search_files(
    account_id: str,
    account_type: str,
    query: str,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Route file search to appropriate API based on account type.

    Args:
        account_id: Microsoft account identifier.
        account_type: "personal" or "work_school".
        query: Search query string.
        limit: Maximum number of results to return.

    Returns:
        List of file/driveItem dictionaries.

    Raises:
        ValueError: If account_id or query is empty.
        Exception: If Graph API request fails.
    """
    if not account_id:
        raise ValueError("account_id is required")
    if not query:
        raise ValueError("query is required")

    logger.info(
        f"Routing file search for account_type={account_type}, "
        f"query='{query}', limit={limit}"
    )

    if account_type == "personal":
        return _search_files_drive(account_id, query, limit)
    else:
        # work_school or unknown - try unified search
        return _search_files_unified(account_id, query, limit)


def _search_files_unified(
    account_id: str, query: str, limit: int
) -> list[dict[str, Any]]:
    """Search files using unified search API (work/school accounts).

    Args:
        account_id: Account identifier.
        query: Search query.
        limit: Result limit.

    Returns:
        List of driveItems.
    """
    logger.debug(f"Using unified search API for files: {query}")

    payload = {
        "requests": [
            {
                "entityTypes": ["driveItem"],
                "query": {"queryString": query},
                "from": 0,
                "size": limit,
                "fields": [
                    "name",
                    "webUrl",
                    "lastModifiedDateTime",
                    "size",
                    "file",
                    "folder",
                ],
            }
        ]
    }

    result = graph.request("POST", "/search/query", account_id=account_id, json=payload)

    if not result or "value" not in result:
        return []

    # Extract hits from unified search response
    files = []
    for response in result.get("value", []):
        for hit_container in response.get("hitsContainers", []):
            for hit in hit_container.get("hits", []):
                resource = hit.get("resource", {})
                if resource:
                    files.append(resource)

    return files[:limit]


def _search_files_drive(
    account_id: str, query: str, limit: int
) -> list[dict[str, Any]]:
    """Search files using OneDrive search endpoint (personal accounts).

    Args:
        account_id: Account identifier.
        query: Search query.
        limit: Result limit.

    Returns:
        List of driveItems.
    """
    logger.debug(f"Using OneDrive search for files: {query}")

    # URL-encode the query for the search endpoint
    encoded_query = quote(query)

    params = {"$top": limit}

    result = graph.request(
        "GET",
        f"/me/drive/root/search(q='{encoded_query}')",
        account_id=account_id,
        params=params,
    )

    return result.get("value", []) if result else []


def search_events(
    account_id: str,
    account_type: str,
    query: str,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Route event search to appropriate API based on account type.

    Args:
        account_id: Microsoft account identifier.
        account_type: "personal" or "work_school".
        query: Search query string.
        limit: Maximum number of results to return.

    Returns:
        List of calendar event dictionaries.

    Raises:
        ValueError: If account_id or query is empty.
        Exception: If Graph API request fails.
    """
    if not account_id:
        raise ValueError("account_id is required")
    if not query:
        raise ValueError("query is required")

    logger.info(
        f"Routing event search for account_type={account_type}, "
        f"query='{query}', limit={limit}"
    )

    if account_type == "personal":
        return _search_events_odata(account_id, query, limit)
    else:
        # work_school or unknown - try unified search
        return _search_events_unified(account_id, query, limit)


def _search_events_unified(
    account_id: str, query: str, limit: int
) -> list[dict[str, Any]]:
    """Search events using unified search API (work/school accounts).

    Args:
        account_id: Account identifier.
        query: Search query.
        limit: Result limit.

    Returns:
        List of calendar events.
    """
    logger.debug(f"Using unified search API for events: {query}")

    payload = {
        "requests": [
            {
                "entityTypes": ["event"],
                "query": {"queryString": query},
                "from": 0,
                "size": limit,
                "fields": [
                    "subject",
                    "start",
                    "end",
                    "location",
                    "attendees",
                    "organizer",
                ],
            }
        ]
    }

    result = graph.request("POST", "/search/query", account_id=account_id, json=payload)

    if not result or "value" not in result:
        return []

    # Extract hits from unified search response
    events = []
    for response in result.get("value", []):
        for hit_container in response.get("hitsContainers", []):
            for hit in hit_container.get("hits", []):
                resource = hit.get("resource", {})
                if resource:
                    events.append(resource)

    return events[:limit]


def _search_events_odata(
    account_id: str, query: str, limit: int
) -> list[dict[str, Any]]:
    """Search events using client-side filtering for personal accounts.

    Note: Personal accounts don't support $search or advanced $filter operations.
    We fetch recent events and filter client-side by checking if the query
    appears in subject, location, or organizer name.

    Args:
        account_id: Account identifier.
        query: Search query (case-insensitive).
        limit: Result limit.

    Returns:
        List of calendar events matching the query.
    """
    logger.debug(f"Using client-side filter search for events: {query}")

    # Fetch more events than needed since we'll filter client-side
    # Request 5x the limit to increase chance of finding matches
    fetch_limit = max(limit * 5, 50)

    params = {
        "$top": fetch_limit,
        "$select": "id,subject,start,end,location,attendees,organizer",
        "$orderby": "start/dateTime desc",
    }

    result = graph.request("GET", "/me/events", account_id=account_id, params=params)

    if not result or "value" not in result:
        return []

    # Filter events client-side
    query_lower = query.lower()
    matching_events = []

    for event in result.get("value", []):
        # Check if query appears in subject, location, or organizer name
        subject = (event.get("subject") or "").lower()
        location_name = (event.get("location", {}).get("displayName") or "").lower()
        organizer_name = (
            event.get("organizer", {}).get("emailAddress", {}).get("name") or ""
        ).lower()
        organizer_email = (
            event.get("organizer", {}).get("emailAddress", {}).get("address") or ""
        ).lower()

        if (
            query_lower in subject
            or query_lower in location_name
            or query_lower in organizer_name
            or query_lower in organizer_email
        ):
            matching_events.append(event)

            if len(matching_events) >= limit:
                break

    return matching_events[:limit]


def search_contacts(
    account_id: str,
    account_type: str,
    query: str,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Route contact search to appropriate API based on account type.

    NOTE: Both personal and work/school accounts use $filter for contact search
    as the unified search API has limited contact support. The filter uses
    prefix matching (startswith) which is a limitation of the Graph API.

    Args:
        account_id: Microsoft account identifier.
        account_type: "personal" or "work_school".
        query: Search query string (prefix matching only).
        limit: Maximum number of results to return.

    Returns:
        List of contact dictionaries.

    Raises:
        ValueError: If account_id or query is empty.
        Exception: If Graph API request fails.
    """
    if not account_id:
        raise ValueError("account_id is required")
    if not query:
        raise ValueError("query is required")

    logger.info(
        f"Routing contact search for account_type={account_type}, "
        f"query='{query}', limit={limit}"
    )

    # Both account types use filter-based search
    return _search_contacts_filter(account_id, query, limit)


def _search_contacts_filter(
    account_id: str, query: str, limit: int
) -> list[dict[str, Any]]:
    """Search contacts using $filter with startswith (all account types).

    Limitation: Only supports prefix matching, not full-text search.

    Args:
        account_id: Account identifier.
        query: Search query (used as prefix).
        limit: Result limit.

    Returns:
        List of contacts.
    """
    logger.debug(f"Using $filter search for contacts: {query}")

    # Build filter with OR conditions for multiple fields
    query_literal = _odata_string_literal(query)
    filter_parts = [
        f"startswith(displayName,{query_literal})",
        f"startswith(givenName,{query_literal})",
        f"startswith(surname,{query_literal})",
    ]
    filter_query = " or ".join(filter_parts)

    params = {
        "$filter": filter_query,
        "$top": limit,
        "$select": "id,displayName,emailAddresses,givenName,surname,companyName",
    }

    result = graph.request("GET", "/me/contacts", account_id=account_id, params=params)

    return result.get("value", []) if result else []


def unified_search(
    account_id: str,
    account_type: str,
    query: str,
    entity_types: list[str],
    limit: int = 10,
) -> dict[str, list[dict[str, Any]]]:
    """Route unified search to appropriate API based on account type.

    For work/school accounts, uses the /search/query endpoint to search
    multiple entity types in a single request.

    For personal accounts, falls back to individual search calls for each
    entity type and combines results.

    Args:
        account_id: Microsoft account identifier.
        account_type: "personal" or "work_school".
        query: Search query string.
        entity_types: List of entity types to search (e.g., ["message",
            "driveItem", "event", "contact"]).
        limit: Maximum number of results per entity type.

    Returns:
        Dictionary mapping entity type to list of results.
        Example: {"message": [...], "driveItem": [...]}

    Raises:
        ValueError: If account_id, query, or entity_types is empty.
        Exception: If Graph API request fails.
    """
    if not account_id:
        raise ValueError("account_id is required")
    if not query:
        raise ValueError("query is required")
    if not entity_types:
        raise ValueError("entity_types list is required")

    logger.info(
        f"Routing unified search for account_type={account_type}, "
        f"query='{query}', entity_types={entity_types}, limit={limit}"
    )

    if account_type == "personal":
        return _unified_search_fallback(account_id, query, entity_types, limit)
    else:
        # work_school or unknown - try unified API
        return _unified_search_api(account_id, query, entity_types, limit)


def _unified_search_api(
    account_id: str,
    query: str,
    entity_types: list[str],
    limit: int,
) -> dict[str, list[dict[str, Any]]]:
    """Perform unified search using /search/query API.

    Args:
        account_id: Account identifier.
        query: Search query.
        entity_types: Entity types to search.
        limit: Result limit per type.

    Returns:
        Dictionary mapping entity type to results.
    """
    logger.debug(f"Using unified search API for types: {entity_types}")

    # Build requests for each entity type
    requests = []
    for entity_type in entity_types:
        requests.append(
            {
                "entityTypes": [entity_type],
                "query": {"queryString": query},
                "from": 0,
                "size": limit,
            }
        )

    payload = {"requests": requests}

    result = graph.request("POST", "/search/query", account_id=account_id, json=payload)

    if not result or "value" not in result:
        return {entity_type: [] for entity_type in entity_types}

    # Parse results by entity type
    results_by_type: dict[str, list[dict[str, Any]]] = {
        entity_type: [] for entity_type in entity_types
    }

    for response in result.get("value", []):
        for hit_container in response.get("hitsContainers", []):
            # Determine entity type from hits
            hits = hit_container.get("hits", [])
            if hits:
                # Extract resources
                for hit in hits:
                    resource = hit.get("resource", {})
                    if resource:
                        # Determine entity type from resource
                        if "@odata.type" in resource:
                            odata_type = resource["@odata.type"]
                            if "message" in odata_type:
                                results_by_type.setdefault("message", []).append(
                                    resource
                                )
                            elif "driveItem" in odata_type:
                                results_by_type.setdefault("driveItem", []).append(
                                    resource
                                )
                            elif "event" in odata_type:
                                results_by_type.setdefault("event", []).append(resource)
                            elif "contact" in odata_type:
                                results_by_type.setdefault("contact", []).append(
                                    resource
                                )

    return results_by_type


def _unified_search_fallback(
    account_id: str,
    query: str,
    entity_types: list[str],
    limit: int,
) -> dict[str, list[dict[str, Any]]]:
    """Fallback unified search for personal accounts.

    Performs individual searches for each entity type and combines results.

    Args:
        account_id: Account identifier.
        query: Search query.
        entity_types: Entity types to search.
        limit: Result limit per type.

    Returns:
        Dictionary mapping entity type to results.
    """
    logger.info(
        f"Using sequential search fallback for personal account (types: {entity_types})"
    )

    results: dict[str, list[dict[str, Any]]] = {}

    # Map entity types to search functions
    search_functions = {
        "message": lambda: _search_emails_odata(account_id, query, limit),
        "driveItem": lambda: _search_files_drive(account_id, query, limit),
        "event": lambda: _search_events_odata(account_id, query, limit),
        "contact": lambda: _search_contacts_filter(account_id, query, limit),
    }

    # Execute searches for requested entity types
    for entity_type in entity_types:
        if entity_type in search_functions:
            try:
                results[entity_type] = search_functions[entity_type]()
            except Exception as e:
                logger.error(f"Search failed for entity_type={entity_type}: {e}")
                results[entity_type] = []
        else:
            logger.warning(f"Unsupported entity type: {entity_type}")
            results[entity_type] = []

    return results
