"""``m365_search``: free-text search across mail, events, contacts, files.

Each requested resource is searched on its own Graph route (see
``services.search``); the results are interleaved newest first and
``limit`` caps the total. The opaque cursor stores one position per
resource, so the next page resumes every resource exactly where this page
stopped, including part-way through a Graph page.

The matching items of each Graph page are ordered newest first (mail and
events already are; drive and contact results come in relevance or name
order), then the resources are merged by recency. A position is the
Graph page an item came from plus its index in that ordered page. In the
cursor, ``<resource>`` holds the page's
nextLink (or, for the first page, the index as an offset) and
``<resource>:skip`` holds the index when both are needed. Exhausted
resources are left out.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from ... import projections
from ...cursors import PagePosition
from ...services import search as search_service
from ..handlers import register_handler, register_validation_rule
from .common import (
    account,
    arg,
    check_rate,
    decode_cursor,
    encode_cursor,
    invalid,
    resolve_mail_folder,
)

TOOL = "m365_search"
RESOURCES = ("email", "event", "contact", "drive_item")
CURSOR_RESOURCE = "search"
MAX_EVENT_SPAN = timedelta(days=731)
DEFAULT_EVENT_PAST = timedelta(days=90)
DEFAULT_EVENT_FUTURE = timedelta(days=365)
_OLDEST = datetime.min.replace(tzinfo=UTC)
_SKIP_SUFFIX = ":skip"

Record = dict[str, Any]
PageFetcher = Callable[[str | None], search_service.SearchPage]


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.upper())


def _event_window(args: dict[str, Any]) -> tuple[datetime, datetime]:
    """Return the event window: the arguments, else -90 / +365 days."""
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    start = args.get("event_start")
    end = args.get("event_end")
    return (
        _parse(start) if start else today - DEFAULT_EVENT_PAST,
        _parse(end) if end else today + DEFAULT_EVENT_FUTURE,
    )


@register_validation_rule(TOOL)
def _search_rules(args: dict[str, Any]) -> None:
    """Enforce parameter applicability and the event window span."""
    resources = args.get("resources")
    if resources is not None:
        if args.get("email_folder_id") is not None and "email" not in resources:
            raise invalid(
                "email_folder_id", "only valid when resources includes 'email'"
            )
        for param in ("event_start", "event_end"):
            if args.get(param) is not None and "event" not in resources:
                raise invalid(param, "only valid when resources includes 'event'")
    start, end = _event_window(args)
    if not start < end <= start + MAX_EVENT_SPAN:
        raise invalid("event_end", "must be after event_start and within 731 days")


# ----------------------------------------------------------------------
# Per-resource streams
# ----------------------------------------------------------------------


def _timestamp(value: str | None) -> datetime:
    return _parse(value) if value else _OLDEST


@dataclass(frozen=True)
class _Kind:
    """How one resource is fetched, filtered, projected and dated."""

    fetch: PageFetcher
    project: Callable[[Record], Record]
    recency: Callable[[Record, Record], datetime]
    match: Callable[[Record], bool] = lambda _item: True


@dataclass
class _Entry:
    recency: datetime
    record: Record
    page_url: str | None
    index: int


@dataclass
class _Stream:
    """Buffered results of one resource, starting at a cursor position."""

    kind: _Kind
    page_url: str | None
    skip: int
    entries: list[_Entry] = field(default_factory=list)
    next_link: str | None = None
    taken: int = 0

    def fill(self, need: int) -> None:
        """Fetch pages until ``need`` items are buffered or none are left."""
        url, skip = self.page_url, self.skip
        while True:
            raw, self.next_link = self.kind.fetch(url)
            page = [
                (self.kind.recency(item, record), record)
                for item in raw
                if self.kind.match(item)
                for record in (self.kind.project(item),)
            ]
            page.sort(key=lambda pair: pair[0], reverse=True)
            for index, (recency, record) in enumerate(page[skip:], start=skip):
                self.entries.append(_Entry(recency, record, url, index))
            if len(self.entries) >= need or self.next_link is None:
                return
            url, skip = self.next_link, 0

    def head(self) -> _Entry | None:
        return self.entries[self.taken] if self.taken < len(self.entries) else None

    def position(self, resource: str) -> dict[str, PagePosition]:
        """Return the cursor entries that resume after the taken items."""
        entry = self.head()
        if entry is None:
            if self.next_link is None:
                return {}
            return {resource: PagePosition(next_link=self.next_link)}
        if entry.page_url is None:
            return {resource: PagePosition(offset=entry.index)}
        position = {resource: PagePosition(next_link=entry.page_url)}
        if entry.index:
            position[resource + _SKIP_SUFFIX] = PagePosition(offset=entry.index)
        return position


def _kinds(args: dict[str, Any], account_id: str) -> dict[str, _Kind]:
    query = args["query"]
    folder = args.get("email_folder_id")
    folder_id = (
        None if folder is None else resolve_mail_folder(folder, "email_folder_id")
    )
    start, end = _event_window(args)
    event_start = args.get("event_start") or start.isoformat()
    event_end = args.get("event_end") or end.isoformat()
    return {
        "email": _Kind(
            fetch=lambda url: search_service.search_messages_page(
                account_id, query, folder_id, url
            ),
            project=projections.project_email_summary,
            recency=lambda _raw, rec: _timestamp(rec["received_at"]),
        ),
        "event": _Kind(
            fetch=lambda url: search_service.search_events_page(
                account_id, event_start, event_end, url
            ),
            project=projections.project_event_summary,
            recency=lambda _raw, rec: _timestamp(rec["start"]),
            match=lambda item: search_service.event_matches(item, query),
        ),
        "contact": _Kind(
            fetch=lambda url: search_service.search_contacts_page(
                account_id, query, url
            ),
            project=projections.project_contact,
            recency=lambda raw, _rec: _timestamp(
                raw.get("lastModifiedDateTime") or raw.get("createdDateTime")
            ),
        ),
        "drive_item": _Kind(
            fetch=lambda url: search_service.search_drive_page(account_id, query, url),
            project=projections.project_drive_item,
            recency=lambda _raw, rec: _timestamp(rec["modified_at"]),
        ),
    }


def _start_positions(
    args: dict[str, Any], account_id: str, resources: list[str]
) -> dict[str, tuple[str | None, int]]:
    """Return ``resource -> (page_url, skip)`` for resources still open."""
    decoded = decode_cursor(args, account_id, CURSOR_RESOURCE)
    if decoded is None:
        return {resource: (None, 0) for resource in resources}
    subs = decoded.sub_cursors or {}
    starts: dict[str, tuple[str | None, int]] = {}
    for resource in resources:
        position = subs.get(resource)
        if position is None:
            continue
        if position.next_link is None:
            starts[resource] = (None, position.offset or 0)
        else:
            extra = subs.get(resource + _SKIP_SUFFIX)
            starts[resource] = (position.next_link, (extra.offset or 0) if extra else 0)
    return starts


def _merge(streams: dict[str, _Stream], limit: int) -> list[Record]:
    """Take up to ``limit`` items, newest first across the streams.

    Ties go to the resource listed first in ``RESOURCES``.
    """
    items: list[Record] = []
    while len(items) < limit:
        best: tuple[datetime, int, str] | None = None
        for resource, stream in streams.items():
            entry = stream.head()
            if entry is None:
                continue
            rank = (entry.recency, -RESOURCES.index(resource), resource)
            if best is None or rank > best:
                best = rank
        if best is None:
            break
        stream = streams[best[2]]
        entry = stream.head()
        assert entry is not None
        stream.taken += 1
        items.append({"resource": best[2], "item": entry.record})
    return items


def _summary(items: list[Record], has_more: bool) -> str:
    count = len(items)
    text = f"Returned {count} match{'' if count == 1 else 'es'}"
    if items:
        counts = [
            f"{resource}: {n}"
            for resource in RESOURCES
            if (n := sum(1 for i in items if i["resource"] == resource))
        ]
        text += f" ({', '.join(counts)})"
    return text + ("; more available." if has_more else ".")


@register_handler(TOOL)
def m365_search(args: dict[str, Any]) -> dict[str, Any]:
    """Search the requested resources and interleave the matches.

    Args:
        args: Validated ``m365_search`` arguments.

    Returns:
        ``query``, ``items`` (newest first, ``limit`` in total),
        ``next_cursor``, ``has_more`` and ``summary``.

    Raises:
        ValidationError: On an invalid cursor or folder alias.
        GraphAPIError: If a Graph request fails.
    """
    account_id = account(args)
    check_rate(account_id, "normal")
    limit: int = arg(args, TOOL, "limit")
    requested = args.get("resources") or RESOURCES
    resources = [r for r in RESOURCES if r in requested]

    kinds = _kinds(args, account_id)
    streams: dict[str, _Stream] = {}
    for resource, (page_url, skip) in _start_positions(
        args, account_id, resources
    ).items():
        stream = _Stream(kinds[resource], page_url, skip)
        stream.fill(limit)
        streams[resource] = stream

    items = _merge(streams, limit)
    positions: dict[str, PagePosition] = {}
    for resource, stream in streams.items():
        positions.update(stream.position(resource))
    has_more = bool(positions)
    next_cursor = (
        encode_cursor(args, account_id, CURSOR_RESOURCE, sub_cursors=positions)
        if has_more
        else None
    )
    return {
        "query": args["query"],
        "items": items,
        "next_cursor": next_cursor,
        "has_more": has_more,
        "summary": _summary(items, has_more),
    }
