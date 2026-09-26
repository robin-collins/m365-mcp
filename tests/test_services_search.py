"""Unit tests for the search service layer."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from src.m365_mcp.services import search as search_service


class RecordingGraph:
    """Record Graph calls and return canned responses."""

    def __init__(self, response: Any = None, pages: list[Any] | None = None):
        self.response = response
        self.pages = pages or []
        self.calls: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        path: str,
        account_id: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        self.calls.append(
            {
                "method": method,
                "path": path,
                "account_id": account_id,
                "params": params,
                "json": json,
            }
        )
        return self.response

    def request_paginated(
        self,
        path: str,
        account_id: str,
        params: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> Any:
        self.calls.append(
            {
                "method": "PAGINATED",
                "path": path,
                "account_id": account_id,
                "params": params,
                "limit": limit,
            }
        )
        return iter(self.pages)


class FakeState:
    """Cache state stand-in exposing ``value``."""

    value = "stale"


class FakeCache:
    """In-memory cache manager stand-in."""

    def __init__(self, hit: Any = None) -> None:
        self.hit = hit
        self.gets: list[tuple[str, str, dict[str, Any]]] = []
        self.sets: list[tuple[str, str, dict[str, Any], Any]] = []

    def get_cached(
        self, account_id: str, operation: str, params: dict[str, Any]
    ) -> Any:
        self.gets.append((account_id, operation, params))
        return (self.hit, FakeState()) if self.hit is not None else None

    def set_cached(
        self,
        account_id: str,
        operation: str,
        params: dict[str, Any],
        data: Any,
    ) -> None:
        self.sets.append((account_id, operation, params, data))


@pytest.fixture
def fake_graph(monkeypatch: pytest.MonkeyPatch) -> RecordingGraph:
    graph = RecordingGraph(response={"value": []})
    monkeypatch.setattr(search_service.graph, "request", graph.request)
    monkeypatch.setattr(
        search_service.graph, "request_paginated", graph.request_paginated
    )
    return graph


def _hits(*resources: dict[str, Any]) -> dict[str, Any]:
    return {
        "value": [{"hitsContainers": [{"hits": [{"resource": r} for r in resources]}]}]
    }


def test_get_account_type_is_always_personal() -> None:
    """Only personal accounts can sign in, so searches route as personal."""
    assert search_service.get_account_type("acc") == "personal"
    assert search_service.get_account_type("missing") == "personal"


def test_search_emails_personal_filters_client_side(
    fake_graph: RecordingGraph,
) -> None:
    fake_graph.response = {
        "value": [
            {"subject": "Quarterly Report"},
            {"subject": "Lunch", "bodyPreview": "nothing"},
            {"subject": "x", "from": {"emailAddress": {"name": "Report Bot"}}},
        ]
    }

    result = search_service.search_emails("acc", "personal", "report", limit=5)

    assert [m["subject"] for m in result] == ["Quarterly Report", "x"]
    call = fake_graph.calls[0]
    assert call["method"] == "GET"
    assert call["path"] == "/me/messages"
    assert call["params"]["$top"] == 50
    assert call["params"]["$orderby"] == "receivedDateTime desc"


def test_search_emails_work_school_uses_unified_api(
    fake_graph: RecordingGraph,
) -> None:
    fake_graph.response = _hits({"id": "m1"}, {"id": "m2"})

    result = search_service.search_emails("acc", "work_school", "q", limit=1)

    assert result == [{"id": "m1"}]
    call = fake_graph.calls[0]
    assert (call["method"], call["path"]) == ("POST", "/search/query")
    assert call["json"]["requests"][0]["entityTypes"] == ["message"]
    assert call["json"]["requests"][0]["size"] == 1


def test_search_emails_requires_query() -> None:
    with pytest.raises(ValueError, match="query is required"):
        search_service.search_emails("acc", "personal", "")


def test_search_files_personal_uses_drive_search(fake_graph: RecordingGraph) -> None:
    fake_graph.response = {"value": [{"id": "f1"}]}

    result = search_service.search_files("acc", "personal", "a b", limit=7)

    assert result == [{"id": "f1"}]
    call = fake_graph.calls[0]
    assert call["path"] == "/me/drive/root/search(q='a%20b')"
    assert call["params"] == {"$top": 7}


def test_search_files_work_school_uses_unified_api(
    fake_graph: RecordingGraph,
) -> None:
    fake_graph.response = _hits({"id": "f1"})

    result = search_service.search_files("acc", "work_school", "q")

    assert result == [{"id": "f1"}]
    assert fake_graph.calls[0]["json"]["requests"][0]["entityTypes"] == ["driveItem"]


def test_search_events_personal_filters_client_side(
    fake_graph: RecordingGraph,
) -> None:
    fake_graph.response = {
        "value": [
            {"subject": "Standup"},
            {"subject": "Other", "location": {"displayName": "standup room"}},
            {"subject": "Nope"},
        ]
    }

    result = search_service.search_events("acc", "personal", "STANDUP")

    assert len(result) == 2
    call = fake_graph.calls[0]
    assert call["path"] == "/me/events"
    assert call["params"]["$top"] == 125
    assert call["params"]["$orderby"] == "start/dateTime desc"


def test_search_events_work_school_uses_unified_api(
    fake_graph: RecordingGraph,
) -> None:
    fake_graph.response = None

    assert search_service.search_events("acc", "unknown", "q") == []
    assert fake_graph.calls[0]["json"]["requests"][0]["entityTypes"] == ["event"]


def test_search_contacts_uses_prefix_filter(fake_graph: RecordingGraph) -> None:
    fake_graph.response = {"value": [{"id": "c1"}]}

    result = search_service.search_contacts("acc", "work_school", "Ann", limit=3)

    assert result == [{"id": "c1"}]
    call = fake_graph.calls[0]
    assert call["path"] == "/me/contacts"
    assert call["params"]["$top"] == 3
    assert call["params"]["$filter"].startswith("startswith(displayName,'Ann')")


def test_unified_search_personal_falls_back_per_type(
    fake_graph: RecordingGraph,
) -> None:
    result = search_service.unified_search(
        "acc", "personal", "q", ["message", "driveItem", "bogus"], limit=2
    )

    assert result == {"message": [], "driveItem": [], "bogus": []}
    assert [c["path"] for c in fake_graph.calls] == [
        "/me/messages",
        "/me/drive/root/search(q='q')",
    ]


def test_unified_search_work_school_groups_by_odata_type(
    fake_graph: RecordingGraph,
) -> None:
    fake_graph.response = _hits(
        {"@odata.type": "#microsoft.graph.message", "id": "m"},
        {"@odata.type": "#microsoft.graph.event", "id": "e"},
    )

    result = search_service.unified_search(
        "acc", "work_school", "q", ["message", "event"], limit=4
    )

    assert result == {
        "message": [{"@odata.type": "#microsoft.graph.message", "id": "m"}],
        "event": [{"@odata.type": "#microsoft.graph.event", "id": "e"}],
    }
    assert len(fake_graph.calls[0]["json"]["requests"]) == 2


def test_unified_search_requires_entity_types() -> None:
    with pytest.raises(ValueError, match="entity_types"):
        search_service.unified_search("acc", "personal", "q", [])


@pytest.fixture
def personal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(search_service, "get_account_type", lambda _: "personal")


@pytest.fixture
def fake_cache(monkeypatch: pytest.MonkeyPatch) -> FakeCache:
    cache = FakeCache()
    monkeypatch.setattr(search_service, "_get_cache_manager", lambda: cache)
    return cache


def test_find_files_maps_items_and_caches(
    fake_graph: RecordingGraph,
    fake_cache: FakeCache,
    personal: None,
) -> None:
    fake_graph.response = {
        "value": [
            {"id": "1", "name": "a.txt", "size": 5, "lastModifiedDateTime": "t"},
            {"id": "2", "name": "dir", "folder": {}},
        ]
    }

    result = search_service.find_files("acc", query="a", limit=10)

    assert result[0]["type"] == "file"
    assert result[0]["size"] == 5
    assert result[0]["modified"] == "t"
    assert result[0]["download_url"] is None
    assert result[1]["type"] == "folder"
    assert all(item["_cache_status"] == "fresh" for item in result)
    assert fake_cache.sets == [
        ("acc", "search_files", {"query": "a", "limit": 10}, result)
    ]


def test_find_files_returns_cache_hit(
    fake_graph: RecordingGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = FakeCache(hit=[{"id": "1"}])
    monkeypatch.setattr(search_service, "_get_cache_manager", lambda: cache)

    result = search_service.find_files("acc", query="a", limit=10)

    assert result == [{"id": "1", "_cache_status": "stale"}]
    assert fake_graph.calls == []


def test_find_files_force_refresh_skips_cache_read(
    fake_graph: RecordingGraph,
    fake_cache: FakeCache,
    personal: None,
) -> None:
    search_service.find_files("acc", query="a", limit=10, force_refresh=True)

    assert fake_cache.gets == []
    assert len(fake_cache.sets) == 1


def test_find_emails_with_folder_uses_folder_endpoint(
    fake_graph: RecordingGraph, fake_cache: FakeCache
) -> None:
    fake_graph.pages = [{"id": "m1"}]

    result = search_service.find_emails(
        "acc",
        query="q",
        limit=5,
        folder="Inbox",
        folder_path="inbox",
        use_cache=False,
    )

    assert result[0]["id"] == "m1"
    call = fake_graph.calls[0]
    assert call["path"] == "/me/mailFolders/inbox/messages"
    assert call["params"]["$search"] == '"q"'
    assert call["limit"] == 5
    assert fake_cache.gets == []
    assert fake_cache.sets == []


def test_find_emails_without_folder_routes_by_account_type(
    fake_graph: RecordingGraph, fake_cache: FakeCache, personal: None
) -> None:
    fake_graph.response = {"value": [{"subject": "q here"}]}

    result = search_service.find_emails("acc", query="q", limit=5)

    assert result[0]["subject"] == "q here"
    assert fake_graph.calls[0]["path"] == "/me/messages"
    assert fake_cache.sets[0][2] == {"query": "q", "limit": 5, "folder": None}


def test_find_events_filters_date_range(
    monkeypatch: pytest.MonkeyPatch, fake_cache: FakeCache, personal: None
) -> None:
    now = dt.datetime.now(dt.UTC)
    inside = {
        "start": {"dateTime": (now - dt.timedelta(hours=1)).isoformat()},
        "end": {"dateTime": (now + dt.timedelta(hours=1)).isoformat()},
    }
    outside = {
        "start": {"dateTime": (now - dt.timedelta(days=10)).isoformat()},
        "end": {"dateTime": (now - dt.timedelta(days=9)).isoformat()},
    }
    monkeypatch.setattr(
        search_service, "search_events", lambda *a: [inside, outside, {}]
    )

    result = search_service.find_events(
        "acc", query="q", days_ahead=1, days_back=1, limit=5
    )

    assert result == [inside]
    assert fake_cache.sets[0][2] == {
        "query": "q",
        "days_ahead": 1,
        "days_back": 1,
        "limit": 5,
    }


def test_find_contacts_routes_to_filter(
    fake_graph: RecordingGraph, fake_cache: FakeCache, personal: None
) -> None:
    fake_graph.response = {"value": [{"id": "c1"}]}

    result = search_service.find_contacts("acc", query="Ann", limit=3)

    assert result[0]["id"] == "c1"
    assert fake_graph.calls[0]["path"] == "/me/contacts"
    assert fake_cache.sets[0][1] == "search_contacts"


def test_find_unified_tags_items_and_sorts_cache_key(
    fake_graph: RecordingGraph, fake_cache: FakeCache, personal: None
) -> None:
    fake_graph.response = {"value": [{"subject": "q", "id": "x"}]}

    result = search_service.find_unified(
        "acc", query="q", entity_types=["message", "event"], limit=2
    )

    assert set(result) == {"message", "event"}
    assert result["message"][0]["_cache_status"] == "fresh"
    assert fake_cache.sets[0][2]["entity_types"] == ["event", "message"]


def test_find_unified_returns_cache_hit(
    fake_graph: RecordingGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = FakeCache(hit={"message": [{"id": "m"}]})
    monkeypatch.setattr(search_service, "_get_cache_manager", lambda: cache)

    result = search_service.find_unified(
        "acc", query="q", entity_types=["message"], limit=2
    )

    assert result == {"message": [{"id": "m", "_cache_status": "stale"}]}
    assert fake_graph.calls == []
