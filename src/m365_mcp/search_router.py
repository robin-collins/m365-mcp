"""Compatibility shim for the search router.

The search routing logic now lives in :mod:`m365_mcp.services.search`. This
module re-exports it so existing imports keep working until it is removed
(task U5.1). Patch ``services.search`` rather than this module when a test
needs the replacement to reach the tool layer.
"""

from .services.search import (
    _odata_string_literal,
    _search_contacts_filter,
    _search_emails_odata,
    _search_emails_unified,
    _search_events_odata,
    _search_events_unified,
    _search_files_drive,
    _search_files_unified,
    _unified_search_api,
    _unified_search_fallback,
    graph,
    logger,
    search_contacts,
    search_emails,
    search_events,
    search_files,
    unified_search,
)

__all__ = [
    "_odata_string_literal",
    "_search_contacts_filter",
    "_search_emails_odata",
    "_search_emails_unified",
    "_search_events_odata",
    "_search_events_unified",
    "_search_files_drive",
    "_search_files_unified",
    "_unified_search_api",
    "_unified_search_fallback",
    "graph",
    "logger",
    "search_contacts",
    "search_emails",
    "search_events",
    "search_files",
    "unified_search",
]
