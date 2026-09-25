"""Unit tests for the mail folders service layer."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from src.m365_mcp.services import mail_folders

ACCOUNT = "acct-1"


class FakeGraph:
    """Record Graph calls and return canned responses."""

    def __init__(
        self,
        request_result: Any = None,
        pages: dict[str, list[dict[str, Any]]] | None = None,
        fail_paths: set[str] | None = None,
    ) -> None:
        self.request_result = request_result
        self.pages = pages or {}
        self.fail_paths = fail_paths or set()
        self.requests: list[dict[str, Any]] = []
        self.paginated: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        path: str,
        account_id: str | None = None,
        **kwargs: Any,
    ) -> Any:
        self.requests.append(
            {
                "method": method,
                "path": path,
                "account_id": account_id,
                "json": kwargs.get("json"),
            }
        )
        if path in self.fail_paths:
            raise RuntimeError("boom")
        return self.request_result

    def request_paginated(
        self,
        path: str,
        account_id: str | None = None,
        params: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        self.paginated.append(
            {
                "path": path,
                "account_id": account_id,
                "params": params,
                "limit": limit,
            }
        )
        return iter(self.pages.get(path, []))


@pytest.fixture
def fake_graph(monkeypatch: pytest.MonkeyPatch) -> FakeGraph:
    """Install a FakeGraph on the service module's graph object."""
    fake = FakeGraph()
    monkeypatch.setattr(mail_folders.graph, "request", fake.request)
    monkeypatch.setattr(mail_folders.graph, "request_paginated", fake.request_paginated)
    return fake


def test_list_folders_root(fake_graph: FakeGraph) -> None:
    fake_graph.pages["/me/mailFolders"] = [{"id": "f1"}]

    result = mail_folders.list_folders(ACCOUNT, limit=50)

    assert result == [{"id": "f1"}]
    call = fake_graph.paginated[0]
    assert call["path"] == "/me/mailFolders"
    assert call["account_id"] == ACCOUNT
    assert call["limit"] == 50
    assert call["params"]["$top"] == 50
    assert "childFolderCount" in call["params"]["$select"]
    assert "includeHiddenFolders" not in call["params"]


def test_list_folders_children_hidden_unlimited(fake_graph: FakeGraph) -> None:
    mail_folders.list_folders(
        ACCOUNT, parent_folder_id="p1", include_hidden=True, limit=None
    )

    call = fake_graph.paginated[0]
    assert call["path"] == "/me/mailFolders/p1/childFolders"
    assert call["params"]["$top"] == 250
    assert call["params"]["includeHiddenFolders"] == "true"
    assert call["limit"] is None


def test_get_folder(fake_graph: FakeGraph) -> None:
    fake_graph.request_result = {"id": "f1"}

    assert mail_folders.get_folder(ACCOUNT, folder_id="f1") == {"id": "f1"}
    assert fake_graph.requests[0]["method"] == "GET"
    assert fake_graph.requests[0]["path"] == "/me/mailFolders/f1"


def test_get_folder_not_found(fake_graph: FakeGraph) -> None:
    with pytest.raises(ValueError, match="Mail folder with ID f1 not found"):
        mail_folders.get_folder(ACCOUNT, folder_id="f1")


def test_get_folder_tree(fake_graph: FakeGraph) -> None:
    fake_graph.pages["/me/mailFolders"] = [
        {"id": "a", "displayName": "A", "childFolderCount": 1},
        {"id": "b", "displayName": "B"},
    ]
    fake_graph.pages["/me/mailFolders/a/childFolders"] = [
        {"id": "a1", "displayName": "A1", "parentFolderId": "a"},
    ]

    result = mail_folders.get_folder_tree(ACCOUNT, max_depth=5)

    assert result["root_folder_id"] is None
    assert result["max_depth"] == 5
    folders = result["folders"]
    assert [f["id"] for f in folders] == ["a", "b"]
    assert folders[0]["children"][0] == {
        "id": "a1",
        "displayName": "A1",
        "childFolderCount": 0,
        "unreadItemCount": 0,
        "totalItemCount": 0,
        "parentFolderId": "a",
        "isHidden": False,
        "children": [],
    }
    assert all(call["limit"] is None for call in fake_graph.paginated)


def test_get_folder_tree_respects_max_depth(fake_graph: FakeGraph) -> None:
    fake_graph.pages["/me/mailFolders"] = [
        {"id": "a", "childFolderCount": 1},
    ]

    result = mail_folders.get_folder_tree(ACCOUNT, max_depth=1)

    assert result["folders"][0]["children"] == []
    assert len(fake_graph.paginated) == 1


def test_create_folder_root(fake_graph: FakeGraph) -> None:
    fake_graph.request_result = {"id": "new"}

    result = mail_folders.create_folder(ACCOUNT, display_name="X")

    assert result == {"id": "new"}
    req = fake_graph.requests[0]
    assert req["method"] == "POST"
    assert req["path"] == "/me/mailFolders"
    assert req["json"] == {"displayName": "X"}


def test_create_folder_child_and_failure(fake_graph: FakeGraph) -> None:
    with pytest.raises(ValueError, match="Failed to create mail folder"):
        mail_folders.create_folder(ACCOUNT, display_name="X", parent_folder_id="p1")
    assert fake_graph.requests[0]["path"] == "/me/mailFolders/p1/childFolders"


def test_rename_folder(fake_graph: FakeGraph) -> None:
    fake_graph.request_result = {"id": "f1", "displayName": "N"}

    result = mail_folders.rename_folder(ACCOUNT, folder_id="f1", new_display_name="N")

    assert result["displayName"] == "N"
    req = fake_graph.requests[0]
    assert req["method"] == "PATCH"
    assert req["path"] == "/me/mailFolders/f1"
    assert req["json"] == {"displayName": "N"}


def test_rename_folder_failure(fake_graph: FakeGraph) -> None:
    with pytest.raises(ValueError, match="Failed to rename mail folder f1"):
        mail_folders.rename_folder(ACCOUNT, folder_id="f1", new_display_name="N")


def test_move_folder(fake_graph: FakeGraph) -> None:
    fake_graph.request_result = {"id": "f1", "parentFolderId": "d1"}

    result = mail_folders.move_folder(
        ACCOUNT, folder_id="f1", destination_folder_id="d1"
    )

    assert result["parentFolderId"] == "d1"
    req = fake_graph.requests[0]
    assert req["method"] == "PATCH"
    assert req["path"] == "/me/mailFolders/f1"
    assert req["json"] == {"parentFolderId": "d1"}


def test_move_folder_failure(fake_graph: FakeGraph) -> None:
    with pytest.raises(ValueError, match="Failed to move mail folder f1"):
        mail_folders.move_folder(ACCOUNT, folder_id="f1", destination_folder_id="d1")


def test_delete_folder(fake_graph: FakeGraph) -> None:
    result = mail_folders.delete_folder(ACCOUNT, folder_id="f1")

    assert result == {"status": "deleted", "folder_id": "f1"}
    assert fake_graph.requests[0]["method"] == "DELETE"
    assert fake_graph.requests[0]["path"] == "/me/mailFolders/f1"


def test_mark_all_as_read(fake_graph: FakeGraph) -> None:
    path = "/me/mailFolders/f1/messages"
    fake_graph.pages[path] = [
        {"id": "m1", "isRead": False},
        {"id": "m2", "isRead": True},
        {"id": "m3", "isRead": False},
    ]
    fake_graph.fail_paths = {"/me/messages/m3"}

    result = mail_folders.mark_all_as_read(ACCOUNT, folder_id="f1")

    assert result == {
        "status": "completed",
        "folder_id": "f1",
        "messages_marked_read": 1,
    }
    call = fake_graph.paginated[0]
    assert call["path"] == path
    assert call["params"] == {
        "$select": "id,isRead",
        "$filter": "isRead eq false",
        "$top": 999,
    }
    assert [r["path"] for r in fake_graph.requests] == [
        "/me/messages/m1",
        "/me/messages/m3",
    ]
    assert fake_graph.requests[0]["json"] == {"isRead": True}


def test_empty_folder(fake_graph: FakeGraph) -> None:
    path = "/me/mailFolders/f1/messages"
    fake_graph.pages[path] = [{"id": "m1"}, {"id": "m2"}]
    fake_graph.fail_paths = {"/me/messages/m2"}

    result = mail_folders.empty_folder(ACCOUNT, folder_id="f1")

    assert result == {
        "status": "completed",
        "folder_id": "f1",
        "messages_deleted": 1,
    }
    assert fake_graph.paginated[0]["params"] == {"$select": "id", "$top": 999}
    assert all(r["method"] == "DELETE" for r in fake_graph.requests)
    assert len(fake_graph.requests) == 2
