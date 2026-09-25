"""Unit tests for the contacts service layer."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from src.m365_mcp.cache_config import CacheState
from src.m365_mcp.services import contacts


class FakeGraph:
    """Record graph calls and return canned responses."""

    def __init__(self, response: Any = None, pages: list[Any] | None = None):
        self.response = response
        self.pages = pages or []
        self.calls: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        path: str,
        account_id: str | None = None,
        **kwargs: Any,
    ) -> Any:
        self.calls.append(
            {"method": method, "path": path, "account_id": account_id, **kwargs}
        )
        if callable(self.response):
            return self.response(method, path)
        return self.response

    def request_paginated(
        self,
        path: str,
        account_id: str | None = None,
        params: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        self.calls.append(
            {
                "path": path,
                "account_id": account_id,
                "params": params,
                "limit": limit,
            }
        )
        yield from self.pages


class FakeCache:
    """Minimal cache manager double."""

    def __init__(self, cached: Any = None):
        self.cached = cached
        self.get_calls: list[tuple[str, str, dict[str, Any]]] = []
        self.set_calls: list[tuple[str, str, dict[str, Any], Any]] = []

    def get_cached(
        self, account_id: str, resource_type: str, params: dict[str, Any]
    ) -> Any:
        self.get_calls.append((account_id, resource_type, params))
        return self.cached

    def set_cached(
        self,
        account_id: str,
        resource_type: str,
        params: dict[str, Any],
        data: Any,
    ) -> None:
        self.set_calls.append((account_id, resource_type, params, data))


def _install(
    monkeypatch: pytest.MonkeyPatch,
    graph: FakeGraph,
    cache: FakeCache | None = None,
) -> None:
    monkeypatch.setattr(contacts.graph, "request", graph.request)
    monkeypatch.setattr(contacts.graph, "request_paginated", graph.request_paginated)
    if cache is not None:
        monkeypatch.setattr(contacts, "_cache_manager", lambda: cache)


def test_list_contacts_fetches_and_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    graph = FakeGraph(pages=[{"id": "c1"}, {"id": "c2"}])
    cache = FakeCache()
    _install(monkeypatch, graph, cache)

    result = contacts.list_contacts("acc", limit=25)

    assert graph.calls == [
        {
            "path": "/me/contacts",
            "account_id": "acc",
            "params": {"$top": 25},
            "limit": 25,
        }
    ]
    assert [c["id"] for c in result] == ["c1", "c2"]
    assert all(c["_cache_status"] == "fresh" for c in result)
    assert all("_cached_at" in c for c in result)
    assert cache.set_calls == [("acc", "contact_list", {"limit": 25}, result)]


def test_list_contacts_returns_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    graph = FakeGraph()
    cache = FakeCache(cached=([{"id": "c1"}], CacheState.STALE))
    _install(monkeypatch, graph, cache)

    result = contacts.list_contacts("acc", limit=10)

    assert result == [{"id": "c1", "_cache_status": "stale"}]
    assert graph.calls == []
    assert cache.get_calls == [("acc", "contact_list", {"limit": 10})]


def test_list_contacts_force_refresh_skips_cache_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = FakeGraph(pages=[{"id": "c1"}])
    cache = FakeCache(cached=([{"id": "old"}], CacheState.FRESH))
    _install(monkeypatch, graph, cache)

    result = contacts.list_contacts("acc", limit=5, force_refresh=True)

    assert result[0]["id"] == "c1"
    assert cache.get_calls == []
    assert len(cache.set_calls) == 1


def test_get_contact_fetches_and_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    graph = FakeGraph(response={"id": "c1", "givenName": "Jane"})
    cache = FakeCache()
    _install(monkeypatch, graph, cache)

    result = contacts.get_contact("acc", contact_id="c1")

    assert graph.calls[0]["method"] == "GET"
    assert graph.calls[0]["path"] == "/me/contacts/c1"
    assert graph.calls[0]["account_id"] == "acc"
    assert result["givenName"] == "Jane"
    assert result["_cache_status"] == "miss"
    assert "_cached_at" in result
    assert cache.set_calls == [("acc", "contact_get", {"contact_id": "c1"}, result)]


def test_get_contact_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, FakeGraph(response=None), FakeCache())

    with pytest.raises(ValueError, match="Contact with ID c9 not found"):
        contacts.get_contact("acc", contact_id="c9")


def test_get_contact_returns_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    graph = FakeGraph()
    cache = FakeCache(cached=({"id": "c1"}, CacheState.FRESH))
    _install(monkeypatch, graph, cache)

    result = contacts.get_contact("acc", contact_id="c1")

    assert result == {"id": "c1", "_cache_status": "fresh"}
    assert graph.calls == []


def test_create_contact_builds_body(monkeypatch: pytest.MonkeyPatch) -> None:
    graph = FakeGraph(response={"id": "new"})
    _install(monkeypatch, graph)

    result = contacts.create_contact(
        "acc",
        given_name="Jane",
        surname="Doe",
        email_addresses="jane@example.com",
        phone_numbers={"business": "1", "home": "2", "mobile": "3"},
    )

    assert result == {"id": "new"}
    call = graph.calls[0]
    assert (call["method"], call["path"], call["account_id"]) == (
        "POST",
        "/me/contacts",
        "acc",
    )
    assert call["json"] == {
        "givenName": "Jane",
        "surname": "Doe",
        "emailAddresses": [{"address": "jane@example.com", "name": "Jane Doe"}],
        "businessPhones": ["1"],
        "homePhones": ["2"],
        "mobilePhone": "3",
    }


def test_create_contact_minimal_and_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = FakeGraph(response=None)
    _install(monkeypatch, graph)

    with pytest.raises(ValueError, match="Failed to create contact"):
        contacts.create_contact("acc", given_name="Jane")
    assert graph.calls[0]["json"] == {"givenName": "Jane"}


def test_update_contact_patches(monkeypatch: pytest.MonkeyPatch) -> None:
    graph = FakeGraph(response=None)
    _install(monkeypatch, graph)

    result = contacts.update_contact(
        "acc", contact_id="c1", updates={"givenName": "Jane"}
    )

    assert result == {"status": "updated"}
    call = graph.calls[0]
    assert (call["method"], call["path"]) == ("PATCH", "/me/contacts/c1")
    assert call["json"] == {"givenName": "Jane"}


def test_update_contact_returns_graph_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, FakeGraph(response={"id": "c1"}))

    result = contacts.update_contact("acc", contact_id="c1", updates={"x": 1})

    assert result == {"id": "c1"}


def test_delete_contact(monkeypatch: pytest.MonkeyPatch) -> None:
    graph = FakeGraph()
    _install(monkeypatch, graph)

    result = contacts.delete_contact("acc", contact_id="c1")

    assert result == {"status": "deleted"}
    call = graph.calls[0]
    assert (call["method"], call["path"], call["account_id"]) == (
        "DELETE",
        "/me/contacts/c1",
        "acc",
    )


def test_create_contact_list(monkeypatch: pytest.MonkeyPatch) -> None:
    graph = FakeGraph(response={"id": "f1"})
    _install(monkeypatch, graph)

    result = contacts.create_contact_list("acc", display_name="Team")

    assert result == {"id": "f1"}
    call = graph.calls[0]
    assert (call["method"], call["path"]) == ("POST", "/me/contactFolders")
    assert call["json"] == {"displayName": "Team"}


def test_create_contact_list_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, FakeGraph(response=None))

    with pytest.raises(ValueError, match="Failed to create contact list"):
        contacts.create_contact_list("acc", display_name="Team")


def test_add_contact_to_list_copies_without_system_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = {
        "id": "c1",
        "@odata.context": "ctx",
        "@odata.etag": "etag",
        "createdDateTime": "t1",
        "lastModifiedDateTime": "t2",
        "givenName": "Jane",
    }

    def respond(method: str, path: str) -> dict[str, Any]:
        return source if method == "GET" else {"id": "copy"}

    graph = FakeGraph(response=respond)
    _install(monkeypatch, graph)

    result = contacts.add_contact_to_list("acc", contact_id="c1", list_id="f1")

    assert result == {"id": "copy"}
    assert graph.calls[0]["path"] == "/me/contacts/c1"
    post = graph.calls[1]
    assert (post["method"], post["path"]) == (
        "POST",
        "/me/contactFolders/f1/contacts",
    )
    assert post["json"] == {"givenName": "Jane"}


def test_add_contact_to_list_missing_contact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, FakeGraph(response=None))

    with pytest.raises(ValueError, match="Contact with ID c1 not found"):
        contacts.add_contact_to_list("acc", contact_id="c1", list_id="f1")


def test_export_contact_vcard(monkeypatch: pytest.MonkeyPatch) -> None:
    graph = FakeGraph(
        response={
            "givenName": "Jane",
            "surname": "Doe",
            "emailAddresses": [{"address": "jane@example.com"}],
            "businessPhones": ["111"],
            "mobilePhone": "333",
            "companyName": "Acme",
            "jobTitle": "Eng",
        }
    )
    _install(monkeypatch, graph)

    result = contacts.export_contact_vcard("acc", contact_id="c1")

    assert graph.calls[0]["path"] == "/me/contacts/c1"
    expected = (
        "BEGIN:VCARD\r\n"
        "VERSION:3.0\r\n"
        "FN:Jane Doe\r\n"
        "N:Doe;Jane;;;\r\n"
        "EMAIL;type=INTERNET:jane@example.com\r\n"
        "TEL;type=WORK,VOICE:111\r\n"
        "TEL;type=CELL:333\r\n"
        "ORG:Acme;\r\n"
        "TITLE:Eng\r\n"
        "END:VCARD"
    )
    assert result == {
        "contact_id": "c1",
        "display_name": "Jane Doe",
        "format": "vcard",
        "vcard": expected,
        "size_bytes": len(expected.encode("utf-8")),
    }


def test_export_contact_vcard_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, FakeGraph(response=None))

    with pytest.raises(ValueError, match="Contact with ID c1 not found"):
        contacts.export_contact_vcard("acc", contact_id="c1")
