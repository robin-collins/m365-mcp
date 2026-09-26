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

from typing import Any
from urllib.parse import parse_qsl, quote, urlsplit

from .. import graph


def _odata_string_literal(value: str) -> str:
    """Encode a Python string as an OData single-quoted string literal."""
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


# --------------------------------------------------------------------------
# Unified m365_search (task U3.3)
#
# One page per call, so the tool can interleave resources and resume each
# one from its own position. A page is ``(items, next_link)``; pass the
# ``next_link`` back as ``page_url`` to fetch the following page.
# --------------------------------------------------------------------------

SEARCH_PAGE_SIZE = 50
EVENT_PAGE_SIZE = 100
MESSAGE_SEARCH_SELECT = (
    "id,conversationId,subject,from,toRecipients,ccRecipients,"
    "receivedDateTime,isRead,hasAttachments,importance,flag,categories,"
    "bodyPreview,parentFolderId"
)
EVENT_SEARCH_SELECT = (
    "id,subject,start,end,isAllDay,location,organizer,isOrganizer,"
    "responseStatus,showAs,attendees,bodyPreview"
)

SearchPage = tuple[list[dict[str, Any]], str | None]


def search_phrase(query: str) -> str:
    """Quote free text as one ``$search`` phrase.

    Backslashes and double quotes are escaped, so the text can never close
    the phrase and add KQL operators of its own.

    Args:
        query: Plain search text.

    Returns:
        The double-quoted phrase, e.g. ``"tax return"``.
    """
    escaped = query.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _get_search_page(
    account_id: str,
    path: str,
    params: dict[str, Any],
    page_url: str | None,
) -> SearchPage:
    """Fetch the first page, or the page at a Graph ``@odata.nextLink``.

    A nextLink is split into path and query so ``graph.request`` sends the
    same headers (``ConsistencyLevel``, ``Prefer``) the first page needed.
    """
    if page_url is not None:
        split = urlsplit(page_url)
        path = split.path.removeprefix(urlsplit(graph.BASE_URL).path)
        params = dict(parse_qsl(split.query, keep_blank_values=True))
    result = graph.request("GET", path, account_id=account_id, params=params) or {}
    return list(result.get("value") or []), result.get("@odata.nextLink")


def search_messages_page(
    account_id: str,
    query: str,
    folder_id: str | None = None,
    page_url: str | None = None,
) -> SearchPage:
    """Search the whole mailbox (or one folder) with server-side ``$search``.

    Args:
        account_id: Resolved account ID.
        query: Plain search text; quoted with :func:`search_phrase`.
        folder_id: Graph folder ID or well-known name, or None for all mail.
        page_url: nextLink of the page to fetch; None for the first page.

    Returns:
        The page's Graph messages (newest first) and the next page link.
    """
    path = "/me/messages"
    if folder_id is not None:
        path = f"/me/mailFolders/{quote(folder_id, safe='')}/messages"
    params = {
        "$search": search_phrase(query),
        "$top": SEARCH_PAGE_SIZE,
        "$select": MESSAGE_SEARCH_SELECT,
    }
    return _get_search_page(account_id, path, params, page_url)


def search_events_page(
    account_id: str,
    start: str,
    end: str,
    page_url: str | None = None,
) -> SearchPage:
    """Read one ``calendarView`` page of the search window, latest first.

    Graph has no event ``$search`` for personal accounts; match the items
    with :func:`event_matches`.

    Args:
        account_id: Resolved account ID.
        start: Window start (RFC 3339).
        end: Window end (RFC 3339).
        page_url: nextLink of the page to fetch; None for the first page.

    Returns:
        The page's Graph events and the next page link.
    """
    params = {
        "startDateTime": start,
        "endDateTime": end,
        "$orderby": "start/dateTime desc",
        "$top": EVENT_PAGE_SIZE,
        "$select": EVENT_SEARCH_SELECT,
    }
    return _get_search_page(account_id, "/me/calendarView", params, page_url)


def event_matches(event: dict[str, Any], query: str) -> bool:
    """Return whether every query word occurs in the event, ignoring case.

    Subject, location, preview and organiser (name and address) are
    searched.

    Args:
        event: Graph event.
        query: Plain search text.

    Returns:
        True when each whitespace-separated word of ``query`` is found.
    """
    organizer = (event.get("organizer") or {}).get("emailAddress") or {}
    haystack = " ".join(
        str(part or "")
        for part in (
            event.get("subject"),
            (event.get("location") or {}).get("displayName"),
            event.get("bodyPreview"),
            organizer.get("name"),
            organizer.get("address"),
        )
    ).casefold()
    return all(word in haystack for word in query.casefold().split())


def contact_search_filter(query: str) -> str:
    """Build the contact ``$filter``: name prefixes, plus the email address.

    The address clause is added when the query looks like an email address.
    The query is an escaped OData string literal (single quotes doubled).

    Args:
        query: Plain search text.

    Returns:
        The ``$filter`` expression.
    """
    literal = _odata_string_literal(query)
    parts = [
        f"startswith({name},{literal})"
        for name in ("displayName", "givenName", "surname")
    ]
    if "@" in query:
        parts.append(f"emailAddresses/any(a:a/address eq {literal})")
    return " or ".join(parts)


def search_contacts_page(
    account_id: str, query: str, page_url: str | None = None
) -> SearchPage:
    """Find contacts by name prefix or email address.

    Args:
        account_id: Resolved account ID.
        query: Plain search text.
        page_url: nextLink of the page to fetch; None for the first page.

    Returns:
        The page's Graph contacts and the next page link.
    """
    params = {"$filter": contact_search_filter(query), "$top": SEARCH_PAGE_SIZE}
    return _get_search_page(account_id, "/me/contacts", params, page_url)


def search_drive_page(
    account_id: str, query: str, page_url: str | None = None
) -> SearchPage:
    """Search OneDrive with ``/me/drive/root/search(q='...')``.

    The query is an OData string literal (single quotes doubled), then
    percent-encoded so it stays inside the path segment.

    Args:
        account_id: Resolved account ID.
        query: Plain search text.
        page_url: nextLink of the page to fetch; None for the first page.

    Returns:
        The page's Graph driveItems and the next page link.
    """
    literal = quote(query.replace("'", "''"), safe="")
    path = f"/me/drive/root/search(q='{literal}')"
    params = {"$top": SEARCH_PAGE_SIZE}
    return _get_search_page(account_id, path, params, page_url)
