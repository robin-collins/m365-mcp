"""Unit tests for the OneDrive drive service layer."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.m365_mcp.services import drive
from src.m365_mcp.validators import ValidationError

ACCOUNT = "acc-1"


class RecordingGraph:
    """Record Graph calls and replay canned responses."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.response: Any = None
        self.items: list[dict[str, Any]] = []
        self.pages: dict[str, list[dict[str, Any]]] = {}

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
                "method": "PAGINATED",
                "path": path,
                "account_id": account_id,
                "params": params,
                "limit": limit,
            }
        )
        return iter(self.pages.get(path, self.items))

    def upload_large_file(
        self, path: str, data: bytes, account_id: str | None = None
    ) -> dict[str, Any]:
        self.calls.append(
            {"method": "UPLOAD", "path": path, "data": data, "account_id": account_id}
        )
        return self.response


@pytest.fixture
def fake_graph(monkeypatch: pytest.MonkeyPatch) -> RecordingGraph:
    recorder = RecordingGraph()
    monkeypatch.setattr(drive.graph, "request", recorder.request)
    monkeypatch.setattr(drive.graph, "request_paginated", recorder.request_paginated)
    monkeypatch.setattr(drive.graph, "upload_large_file", recorder.upload_large_file)
    return recorder


@pytest.fixture
def cache(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    manager = MagicMock()
    manager.get_cached.return_value = None
    monkeypatch.setattr(drive, "get_cache_manager", lambda: manager)
    return manager


def _invalidated(cache: MagicMock) -> list[str]:
    return [c.args[0] for c in cache.invalidate_pattern.call_args_list]


# list_items


def test_list_items_root_endpoint_params_and_filter(
    fake_graph: RecordingGraph, cache: MagicMock
) -> None:
    fake_graph.items = [
        {"id": "f1", "name": "Docs", "folder": {}, "lastModifiedDateTime": "t"},
        {
            "id": "i1",
            "name": "a.txt",
            "file": {},
            "size": 3,
            "@microsoft.graph.downloadUrl": "https://x",
        },
    ]

    result = drive.list_items(ACCOUNT, path="/", limit=10, type_filter="files")

    call = fake_graph.calls[0]
    assert call["path"] == "/me/drive/root/children"
    assert call["params"]["$top"] == 10
    assert "@microsoft.graph.downloadUrl" in call["params"]["$select"]
    assert call["limit"] == 10
    assert len(result) == 1
    assert result[0]["id"] == "i1"
    assert result[0]["type"] == "file"
    assert result[0]["download_url"] == "https://x"
    assert result[0]["_cache_status"] == "miss"
    cache.set_cached.assert_called_once()
    assert cache.set_cached.call_args.args[1] == "file_list"


def test_list_items_path_and_folder_id_endpoints(
    fake_graph: RecordingGraph, cache: MagicMock
) -> None:
    drive.list_items(ACCOUNT, path="/Documents", use_cache=False)
    drive.list_items(ACCOUNT, folder_id="F1", use_cache=False)

    assert fake_graph.calls[0]["path"] == "/me/drive/root:/Documents:/children"
    assert fake_graph.calls[1]["path"] == "/me/drive/items/F1/children"
    cache.set_cached.assert_not_called()


def test_list_items_returns_cached_data(
    fake_graph: RecordingGraph, cache: MagicMock
) -> None:
    state = MagicMock(value="fresh")
    cache.get_cached.return_value = ([{"id": "c1"}], state)

    result = drive.list_items(ACCOUNT)

    assert result == [{"id": "c1", "_cache_status": "fresh"}]
    assert fake_graph.calls == []


# download_file


def test_download_file_fetches_metadata_and_streams(
    tmp_path: Path, fake_graph: RecordingGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_graph.response = {
        "id": "F1",
        "name": "a.txt",
        "size": 5,
        "file": {"mimeType": "text/plain"},
        "@microsoft.graph.downloadUrl": "https://graph.microsoft.com/v1.0/x",
    }
    streamed: list[str] = []

    def fake_stream(url: str, destination: Path, **kwargs: Any) -> None:
        streamed.append(url)
        destination.write_bytes(b"hello")

    monkeypatch.setattr(drive, "_stream_download", fake_stream)
    destination = tmp_path / "a.txt"

    result = drive.download_file(ACCOUNT, "F1", destination)

    assert fake_graph.calls[0]["method"] == "GET"
    assert fake_graph.calls[0]["path"] == "/me/drive/items/F1"
    assert streamed == ["https://graph.microsoft.com/v1.0/x"]
    assert result == {
        "path": str(destination),
        "name": "a.txt",
        "size_mb": 0.0,
        "mime_type": "text/plain",
    }


def test_download_file_missing_metadata_raises(
    tmp_path: Path, fake_graph: RecordingGraph
) -> None:
    fake_graph.response = None

    with pytest.raises(ValidationError):
        drive.download_file(ACCOUNT, "F1", tmp_path / "a.txt")


# upload_file / replace_file


def test_upload_file_uses_root_path_and_invalidates(
    fake_graph: RecordingGraph, cache: MagicMock
) -> None:
    fake_graph.response = {"id": "new"}

    result = drive.upload_file(ACCOUNT, "/Uploads/a.txt", b"data")

    assert result == {"id": "new"}
    assert fake_graph.calls[0]["path"] == "/me/drive/root:/Uploads/a.txt:"
    assert fake_graph.calls[0]["data"] == b"data"
    assert _invalidated(cache) == ["file_list:*", "folder_get_tree:*"]


def test_upload_file_empty_result_raises(
    fake_graph: RecordingGraph, cache: MagicMock
) -> None:
    fake_graph.response = {}

    with pytest.raises(RuntimeError, match="Failed to create file"):
        drive.upload_file(ACCOUNT, "/a.txt", b"x")


def test_replace_file_uses_item_path_and_invalidates(
    fake_graph: RecordingGraph, cache: MagicMock
) -> None:
    fake_graph.response = {"id": "F1"}

    result = drive.replace_file(ACCOUNT, "F1", b"new")

    assert result == {"id": "F1"}
    assert fake_graph.calls[0]["path"] == "/me/drive/items/F1"
    assert _invalidated(cache) == ["file_list:*"]


# delete / copy / move / rename


def test_delete_item(fake_graph: RecordingGraph, cache: MagicMock) -> None:
    result = drive.delete_item(ACCOUNT, "F1")

    assert result == {"status": "deleted"}
    assert fake_graph.calls[0]["method"] == "DELETE"
    assert fake_graph.calls[0]["path"] == "/me/drive/items/F1"
    assert _invalidated(cache) == ["file_list:*", "folder_get_tree:*"]


def test_copy_item_payload_and_default_status(
    fake_graph: RecordingGraph, cache: MagicMock
) -> None:
    fake_graph.response = None

    result = drive.copy_item(ACCOUNT, "F1", "D1", new_name="b.txt")

    call = fake_graph.calls[0]
    assert (call["method"], call["path"]) == ("POST", "/me/drive/items/F1/copy")
    assert call["json"] == {"parentReference": {"id": "D1"}, "name": "b.txt"}
    assert result == {"status": "copy initiated"}
    assert _invalidated(cache) == ["file_list:*", "folder_get_tree:*"]


def test_move_file(fake_graph: RecordingGraph, cache: MagicMock) -> None:
    fake_graph.response = {"id": "F1"}

    result = drive.move_file(ACCOUNT, "F1", "D1")

    call = fake_graph.calls[0]
    assert (call["method"], call["path"]) == ("PATCH", "/me/drive/items/F1")
    assert call["json"] == {"parentReference": {"id": "D1"}}
    assert result == {"id": "F1"}
    assert _invalidated(cache) == ["file_list:*", "folder_get_tree:*"]


def test_move_file_failure(fake_graph: RecordingGraph, cache: MagicMock) -> None:
    with pytest.raises(ValueError, match="Failed to move file"):
        drive.move_file(ACCOUNT, "F1", "D1")


def test_rename_file(fake_graph: RecordingGraph, cache: MagicMock) -> None:
    fake_graph.response = {"id": "F1", "name": "n.txt"}

    result = drive.rename_file(ACCOUNT, "F1", "n.txt")

    assert fake_graph.calls[0]["json"] == {"name": "n.txt"}
    assert result["name"] == "n.txt"
    assert _invalidated(cache) == ["file_list:*"]


# share / download url


def test_create_sharing_link(fake_graph: RecordingGraph) -> None:
    fake_graph.response = {"link": {"webUrl": "https://share"}}

    result = drive.create_sharing_link(
        ACCOUNT, "F1", permission_type="edit", scope="organization"
    )

    call = fake_graph.calls[0]
    assert (call["method"], call["path"]) == ("POST", "/me/drive/items/F1/createLink")
    assert call["json"] == {"type": "edit", "scope": "organization"}
    assert result == {"link": {"webUrl": "https://share"}}


def test_create_sharing_link_failure(fake_graph: RecordingGraph) -> None:
    with pytest.raises(ValueError, match="Failed to create sharing link"):
        drive.create_sharing_link(ACCOUNT, "F1", permission_type="view", scope="x")


def test_get_download_url(fake_graph: RecordingGraph) -> None:
    fake_graph.response = {
        "id": "F1",
        "name": "a.txt",
        "size": 1,
        "@microsoft.graph.downloadUrl": "https://dl",
        "extra": True,
    }

    result = drive.get_download_url(ACCOUNT, "F1")

    call = fake_graph.calls[0]
    assert call["path"] == "/me/drive/items/F1"
    assert call["params"] == {"$select": "id,name,size,@microsoft.graph.downloadUrl"}
    assert result == {
        "id": "F1",
        "name": "a.txt",
        "size": 1,
        "download_url": "https://dl",
    }


def test_get_download_url_missing_url(fake_graph: RecordingGraph) -> None:
    fake_graph.response = {"id": "F1"}

    with pytest.raises(ValueError, match="No download URL"):
        drive.get_download_url(ACCOUNT, "F1")


# folders


def test_list_folders_filters_and_caches(
    fake_graph: RecordingGraph, cache: MagicMock
) -> None:
    fake_graph.items = [
        {
            "id": "D1",
            "name": "Docs",
            "folder": {"childCount": 2},
            "parentReference": {"path": "/drive/root:", "id": "R"},
        },
        {"id": "i1", "name": "a.txt", "file": {}},
    ]

    result = drive.list_folders(ACCOUNT, path="/Documents", limit=20)

    call = fake_graph.calls[0]
    assert call["path"] == "/me/drive/root:/Documents:/children"
    assert call["params"]["$top"] == 20
    assert [f["id"] for f in result["folders"]] == ["D1"]
    assert result["folders"][0]["childCount"] == 2
    assert result["folders"][0]["parentId"] == "R"
    assert result["_cache_status"] == "miss"
    assert cache.set_cached.call_args.args[1] == "folder_list"


def test_list_folders_cache_hit(fake_graph: RecordingGraph, cache: MagicMock) -> None:
    cache.get_cached.return_value = (
        {"folders": [{"id": "D1"}], "_cached_at": "t"},
        MagicMock(value="stale"),
    )

    result = drive.list_folders(ACCOUNT)

    assert result == {
        "folders": [{"id": "D1"}],
        "_cache_status": "stale",
        "_cached_at": "t",
    }
    assert fake_graph.calls == []


def test_get_folder_by_path_and_not_folder(fake_graph: RecordingGraph) -> None:
    fake_graph.response = {
        "id": "D1",
        "name": "Docs",
        "folder": {"childCount": 1},
        "webUrl": "https://w",
    }

    result = drive.get_folder(ACCOUNT, path="/Documents")

    assert fake_graph.calls[0]["path"] == "/me/drive/root:/Documents"
    assert result["webUrl"] == "https://w"
    assert result["childCount"] == 1

    fake_graph.response = {"id": "i1", "name": "a.txt", "file": {}}
    with pytest.raises(ValueError, match="not a folder"):
        drive.get_folder(ACCOUNT, folder_id="i1")
    assert fake_graph.calls[1]["path"] == "/me/drive/items/i1"


def test_get_folder_tree_recurses(fake_graph: RecordingGraph, cache: MagicMock) -> None:
    fake_graph.pages = {
        "/me/drive/root/children": [{"id": "D1", "name": "A", "folder": {}}],
        "/me/drive/items/D1/children": [{"id": "D2", "name": "B", "folder": {}}],
        "/me/drive/items/D2/children": [],
    }

    result = drive.get_folder_tree(ACCOUNT, path="/", max_depth=5)

    assert result["root_path"] == "/"
    assert result["max_depth"] == 5
    assert result["folders"][0]["id"] == "D1"
    assert result["folders"][0]["children"][0]["id"] == "D2"
    assert result["folders"][0]["children"][0]["children"] == []
    assert fake_graph.calls[0]["limit"] is None
    assert fake_graph.calls[0]["params"]["$top"] == 500
    assert cache.set_cached.call_args.args[1] == "folder_get_tree"


def test_create_folder_payload(fake_graph: RecordingGraph) -> None:
    fake_graph.response = {"id": "D9"}

    assert drive.create_folder(ACCOUNT, "New") == {"id": "D9"}
    drive.create_folder(ACCOUNT, "Child", parent_folder_id="P1")

    assert fake_graph.calls[0]["path"] == "/me/drive/root/children"
    assert fake_graph.calls[0]["json"] == {
        "name": "New",
        "folder": {},
        "@microsoft.graph.conflictBehavior": "rename",
    }
    assert fake_graph.calls[1]["path"] == "/me/drive/items/P1/children"


def test_delete_folder(fake_graph: RecordingGraph) -> None:
    result = drive.delete_folder(ACCOUNT, "D1")

    assert fake_graph.calls[0]["method"] == "DELETE"
    assert fake_graph.calls[0]["path"] == "/me/drive/items/D1"
    assert result == {"status": "deleted", "folder_id": "D1"}


def test_rename_folder(fake_graph: RecordingGraph) -> None:
    fake_graph.response = {"id": "D1", "name": "X"}

    assert drive.rename_folder(ACCOUNT, "D1", "X")["name"] == "X"
    assert fake_graph.calls[0]["json"] == {"name": "X"}

    fake_graph.response = None
    with pytest.raises(ValueError, match="Failed to rename folder"):
        drive.rename_folder(ACCOUNT, "D1", "X")


def test_move_folder(fake_graph: RecordingGraph) -> None:
    fake_graph.response = {"id": "D1"}

    assert drive.move_folder(ACCOUNT, "D1", "P2") == {"id": "D1"}
    call = fake_graph.calls[0]
    assert (call["method"], call["path"]) == ("PATCH", "/me/drive/items/D1")
    assert call["json"] == {"parentReference": {"id": "P2"}}
