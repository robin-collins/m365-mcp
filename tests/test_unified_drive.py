"""Unified tools for OneDrive (``drive_item``, ``operation``) and drive_*.

Covers the drive parts of m365_list, m365_get, m365_get_content,
m365_create, m365_update, m365_move and m365_delete, plus drive_upload,
drive_copy and drive_share (tasks U3.1-U3.8, U3.17-U3.19) against the
fake Graph.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from m365_mcp import operations
from m365_mcp.rate_limit import RateLimiter
from m365_mcp.tools.unified import common
from tests.unified_harness import UnifiedHarness

MIB = 1024 * 1024


@pytest.fixture(autouse=True)
def _fresh_rate_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give each test its own budget so deletes never hit the shared limit."""
    monkeypatch.setattr(common, "rate_limiter", RateLimiter())


def _seed_item(
    harness: UnifiedHarness,
    item_id: str,
    name: str,
    parent: str,
    *,
    folder: bool = False,
    size: int = 0,
) -> None:
    item: dict[str, Any] = {
        "id": item_id,
        "name": name,
        "size": size,
        "createdDateTime": "2026-09-01T00:00:00Z",
        "lastModifiedDateTime": "2026-09-02T00:00:00Z",
        "parentReference": {"id": parent},
        "webUrl": f"https://onedrive.live.com/?id={item_id}",
    }
    if folder:
        item["folder"] = {"childCount": 0}
    else:
        item["file"] = {"mimeType": "application/octet-stream"}
        item["_content"] = b"content of " + name.encode()
    harness.fake.drive[item_id] = item


def _fail(status: int, code: str = "Boom") -> tuple[int, Any]:
    return status, {"error": {"code": code, "message": "failed"}}


def _patch_action(harness: UnifiedHarness, action: str, reply: Any) -> None:
    """Make ``POST /me/drive/items/{id}/<action>`` answer with ``reply``."""
    original = harness.fake._drive_action

    def patched(method, params, body, item_id, name):
        if name == action:
            return reply(method, params, body, item_id)
        return original(method, params, body, item_id, name)

    harness.fake._drive_action = patched  # type: ignore[method-assign]


# ----------------------------------------------------------------------
# m365_list
# ----------------------------------------------------------------------


def test_list_drive_root_by_default(harness: UnifiedHarness) -> None:
    result = harness.ok("m365_list", {"resource": "drive_item"})

    names = [i["name"] for i in result["items"]]
    assert names == ["Documents", "Notes.txt", "Photos"]
    assert result["has_more"] is False
    assert all(i["children"] is None for i in result["items"])
    notes = next(i for i in result["items"] if i["name"] == "Notes.txt")
    assert notes["item_type"] == "file"
    assert notes["path"] == "/"
    assert notes["mime_type"] == "text/plain"
    assert harness.graph_calls("GET", "/me/drive/root/children")


def test_list_drive_folder_by_id_and_by_path(harness: UnifiedHarness) -> None:
    by_id = harness.ok(
        "m365_list", {"resource": "drive_item", "container_id": "item-documents"}
    )
    by_path = harness.ok("m365_list", {"resource": "drive_item", "path": "/Documents"})

    expected = ["budget.xlsx", "CV.docx", "Old", "Tax"]
    assert sorted(i["name"] for i in by_id["items"]) == sorted(expected)
    assert [i["id"] for i in by_path["items"]] == [i["id"] for i in by_id["items"]]
    assert harness.graph_calls("GET", "/me/drive/items/item-documents/children")
    assert harness.graph_calls("GET", "/me/drive/root:/Documents:/children")


def test_list_drive_filters_item_type(harness: UnifiedHarness) -> None:
    folders = harness.ok(
        "m365_list",
        {"resource": "drive_item", "path": "/Documents", "item_type": "folder"},
    )
    files = harness.ok(
        "m365_list",
        {"resource": "drive_item", "path": "/Documents", "item_type": "file"},
    )

    assert {i["name"] for i in folders["items"]} == {"Old", "Tax"}
    assert {i["name"] for i in files["items"]} == {"budget.xlsx", "CV.docx"}


def test_list_drive_pages_with_cursor(harness: UnifiedHarness) -> None:
    args = {"resource": "drive_item", "path": "/Documents", "limit": 3}
    first = harness.ok("m365_list", args)
    assert len(first["items"]) == 3
    assert first["has_more"] is True

    second = harness.ok("m365_list", {**args, "cursor": first["next_cursor"]})
    assert len(second["items"]) == 1
    assert second["has_more"] is False
    assert second["next_cursor"] is None


def test_list_drive_filtered_pages_with_cursor(harness: UnifiedHarness) -> None:
    args = {
        "resource": "drive_item",
        "path": "/Documents",
        "item_type": "file",
        "limit": 1,
    }
    first = harness.ok("m365_list", args)
    second = harness.ok("m365_list", {**args, "cursor": first["next_cursor"]})

    assert first["has_more"] is True
    assert second["has_more"] is False
    names = {first["items"][0]["name"], second["items"][0]["name"]}
    assert names == {"budget.xlsx", "CV.docx"}


def test_list_drive_folder_tree(harness: UnifiedHarness) -> None:
    result = harness.ok(
        "m365_list",
        {
            "resource": "drive_item",
            "item_type": "folder",
            "recursive": True,
            "max_depth": 2,
        },
    )

    top = {i["name"]: i for i in result["items"]}
    assert set(top) == {"Documents", "Photos"}
    documents = top["Documents"]
    assert {c["name"] for c in documents["children"]} == {"Old", "Tax"}
    # Depth 2 is the limit: the Tax folder is not expanded.
    assert all(c["children"] is None for c in documents["children"])
    assert top["Photos"]["children"] == []
    assert harness.graph_calls("GET", "/me/drive/items/item-documents/children")
    assert not harness.graph_calls("GET", "/me/drive/items/item-tax/children")


def test_list_drive_tree_with_files(harness: UnifiedHarness) -> None:
    result = harness.ok(
        "m365_list",
        {"resource": "drive_item", "path": "/Documents", "recursive": True},
    )

    tax = next(i for i in result["items"] if i["name"] == "Tax")
    assert [c["name"] for c in tax["children"]] == ["2025-tax-return.pdf"]
    assert tax["children"][0]["children"] is None
    budget = next(i for i in result["items"] if i["name"] == "budget.xlsx")
    assert budget["children"] is None


def test_list_drive_rejects_container_id_with_path(harness: UnifiedHarness) -> None:
    text = harness.error(
        "m365_list",
        {"resource": "drive_item", "container_id": "root", "path": "/Documents"},
    )

    assert text == (
        "Invalid path: cannot be combined with container_id. "
        "Expected: one of container_id or path"
    )


# ----------------------------------------------------------------------
# m365_get
# ----------------------------------------------------------------------


def test_get_drive_item_by_id(harness: UnifiedHarness) -> None:
    result = harness.ok("m365_get", {"resource": "drive_item", "id": "item-budget"})

    item = result["item"]
    assert item["name"] == "budget.xlsx"
    assert item["path"] == "/Documents"
    assert item["parent_id"] == "item-documents"
    assert item["size"] == 48_213
    assert item["children"] is None
    assert harness.graph_calls("GET", "/me/drive/items/item-budget")


def test_get_drive_item_by_path(harness: UnifiedHarness) -> None:
    result = harness.ok(
        "m365_get", {"resource": "drive_item", "path": "/Documents/Tax"}
    )

    assert result["item"]["id"] == "item-tax"
    assert result["item"]["item_type"] == "folder"
    assert harness.graph_calls("GET", "/me/drive/root:/Documents/Tax")


def test_get_drive_root_alias(harness: UnifiedHarness) -> None:
    result = harness.ok("m365_get", {"resource": "drive_item", "id": "root"})

    assert result["item"]["id"] == "root"
    assert harness.graph_calls("GET", "/me/drive/root")


def test_get_drive_item_rejects_id_with_path(harness: UnifiedHarness) -> None:
    text = harness.error(
        "m365_get", {"resource": "drive_item", "id": "item-tax", "path": "/Tax"}
    )

    assert text == "Invalid path: cannot be combined with id"


def test_get_operation_example(harness: UnifiedHarness) -> None:
    operations.operation_store._operations["op_7f3c2a"] = operations._Operation(
        "https://api.onedrive.com/copy/01ABCDEF2345",
        harness.account_id,
        time.time(),
    )

    result = harness.ok("m365_get", {"resource": "operation", "id": "op_7f3c2a"})

    assert result == {
        "resource": "operation",
        "item": {
            "operation_id": "op_7f3c2a",
            "status": "completed",
            "percent_complete": 100,
            "resource_id": "01ABCDEF2345",
            "error": None,
        },
        "summary": "Copy completed; new item id 01ABCDEF2345.",
    }


def test_get_unknown_operation(harness: UnifiedHarness) -> None:
    text = harness.error("m365_get", {"resource": "operation", "id": "op_missing"})

    assert text == (
        "Invalid id: unknown operation. Expected: an operation_id returned by "
        "drive_copy in the last 24 hours"
    )


# ----------------------------------------------------------------------
# m365_get_content
# ----------------------------------------------------------------------


def test_download_drive_file(harness: UnifiedHarness) -> None:
    result = harness.ok(
        "m365_get_content",
        {
            "resource": "drive_item",
            "id": "item-budget",
            "mode": "download",
            "save_path": "out/budget.xlsx",
        },
    )

    saved = harness.sandbox / "out" / "budget.xlsx"
    assert saved.read_bytes() == b"fake contents of budget.xlsx"
    assert Path(result["saved_path"]) == saved.resolve()
    assert result["size"] == len(b"fake contents of budget.xlsx")
    assert result["mime_type"].endswith("spreadsheetml.sheet")
    assert result["download_url"] is None
    assert result["vcard"] is None
    assert harness.graph_calls("GET", "/me/drive/items/item-budget")
    assert harness.graph_calls("GET", "/download/item-budget")
    assert "budget.xlsx" in result["summary"]


def test_download_refuses_existing_file(harness: UnifiedHarness) -> None:
    args = {
        "resource": "drive_item",
        "id": "item-notes",
        "mode": "download",
        "save_path": "notes-new.txt",
    }

    text = harness.error("m365_get_content", args)

    assert text == (
        "Invalid save_path: file exists. Expected: overwrite=true or another path"
    )
    assert (harness.sandbox / "notes-new.txt").read_text() == "milk\neggs\nbread\n"

    harness.ok("m365_get_content", {**args, "overwrite": True})
    assert (harness.sandbox / "notes-new.txt").read_bytes() == (
        b"fake contents of Notes.txt"
    )


def test_download_refuses_path_outside_allowed_folders(
    harness: UnifiedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MCP_FILE_ALLOWED_ROOTS", raising=False)
    outside = Path(harness.sandbox.anchor) / "m365-not-allowed" / "x.txt"

    text = harness.error(
        "m365_get_content",
        {
            "resource": "drive_item",
            "id": "item-notes",
            "mode": "download",
            "save_path": str(outside),
        },
    )

    assert text == (
        "Invalid save_path: outside allowed folders. Expected: a path under the "
        "working directory, temp directory or MCP_FILE_ALLOWED_ROOTS"
    )
    assert not harness.graph_calls()


def test_download_refuses_folders(harness: UnifiedHarness) -> None:
    text = harness.error(
        "m365_get_content",
        {
            "resource": "drive_item",
            "id": "item-tax",
            "mode": "download",
            "save_path": "tax.bin",
        },
    )

    assert text == "Invalid id: item is a folder. Expected: a file"
    assert not (harness.sandbox / "tax.bin").exists()


def test_download_respects_size_limit(
    harness: UnifiedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCP_FILE_DOWNLOAD_MAX_MB", "1")

    text = harness.error(
        "m365_get_content",
        {
            "resource": "drive_item",
            "id": "item-receipts2024",
            "mode": "download",
            "save_path": "receipts.zip",
        },
    )

    assert text == (
        "Invalid id: the file is larger than the 1 MB download limit. "
        "Expected: a smaller file, or raise MCP_FILE_DOWNLOAD_MAX_MB"
    )
    assert not harness.graph_calls("GET", "/download/item-receipts2024")


def test_download_requires_save_path(harness: UnifiedHarness) -> None:
    text = harness.error(
        "m365_get_content",
        {"resource": "drive_item", "id": "item-notes", "mode": "download"},
    )

    assert text == "Invalid save_path: required for mode='download'"


def test_download_url(harness: UnifiedHarness) -> None:
    result = harness.ok(
        "m365_get_content",
        {"resource": "drive_item", "id": "item-budget", "mode": "download_url"},
    )

    assert result["download_url"] == "https://fake.1drv.com/download/item-budget"
    assert result["size"] == 48_213
    assert result["saved_path"] is None
    assert result["vcard"] is None
    assert "expires" in result["summary"]
    (call,) = harness.graph_calls("GET", "/me/drive/items/item-budget")
    assert "@microsoft.graph.downloadUrl" in call.params["$select"]


def test_download_url_refuses_folders(harness: UnifiedHarness) -> None:
    text = harness.error(
        "m365_get_content",
        {"resource": "drive_item", "id": "item-tax", "mode": "download_url"},
    )

    assert text == "Invalid id: item is a folder. Expected: a file"


def test_get_content_mode_must_suit_drive_item(harness: UnifiedHarness) -> None:
    text = harness.error(
        "m365_get_content",
        {"resource": "drive_item", "id": "item-budget", "mode": "vcard"},
    )

    assert text == (
        "Invalid mode 'vcard': not valid for resource 'drive_item'. "
        "Expected: download or download_url"
    )


# ----------------------------------------------------------------------
# m365_create (drive folder)
# ----------------------------------------------------------------------


def test_create_drive_folder_in_path(harness: UnifiedHarness) -> None:
    result = harness.ok(
        "m365_create",
        {
            "resource": "drive_item",
            "drive_folder": {"name": "Receipts", "parent_path": "/Documents"},
        },
    )

    item = result["item"]
    assert item["name"] == "Receipts"
    assert item["item_type"] == "folder"
    assert item["path"] == "/Documents"
    assert result["summary"] == "Created folder Receipts in /Documents."
    (call,) = harness.graph_calls("POST", "/me/drive/root:/Documents:/children")
    assert call.body == {
        "name": "Receipts",
        "folder": {},
        "@microsoft.graph.conflictBehavior": "fail",
    }


def test_create_drive_folder_defaults_to_root(harness: UnifiedHarness) -> None:
    result = harness.ok(
        "m365_create", {"resource": "drive_item", "drive_folder": {"name": "New"}}
    )

    assert result["item"]["path"] == "/"
    assert harness.graph_calls("POST", "/me/drive/root/children")


def test_create_drive_folder_name_conflict(harness: UnifiedHarness) -> None:
    text = harness.error(
        "m365_create",
        {
            "resource": "drive_item",
            "drive_folder": {"name": "Tax", "parent_id": "item-documents"},
        },
    )

    assert text == (
        "A folder named 'Tax' already exists there. "
        "Expected: another name or if_exists='rename'"
    )
    assert harness.graph_calls("POST", "/me/drive/items/item-documents/children")


def test_create_drive_folder_rename_on_conflict(harness: UnifiedHarness) -> None:
    result = harness.ok(
        "m365_create",
        {
            "resource": "drive_item",
            "drive_folder": {
                "name": "Tax",
                "parent_id": "item-documents",
                "if_exists": "rename",
            },
        },
    )

    assert result["item"]["name"] == "Tax 1"
    (call,) = harness.graph_calls("POST", "/me/drive/items/item-documents/children")
    assert call.body["@microsoft.graph.conflictBehavior"] == "rename"


def test_create_drive_folder_parent_exclusivity(harness: UnifiedHarness) -> None:
    text = harness.error(
        "m365_create",
        {
            "resource": "drive_item",
            "drive_folder": {
                "name": "X",
                "parent_id": "item-documents",
                "parent_path": "/Documents",
            },
        },
    )

    assert text == "Invalid parent_path: cannot be combined with parent_id"


# ----------------------------------------------------------------------
# m365_update (rename)
# ----------------------------------------------------------------------


def test_rename_drive_item(harness: UnifiedHarness) -> None:
    result = harness.ok(
        "m365_update",
        {
            "resource": "drive_item",
            "id": "item-cv",
            "drive_item_changes": {"name": "CV-2026.docx"},
        },
    )

    assert result == {
        "resource": "drive_item",
        "id": "item-cv",
        "status": "updated",
        "changed_fields": ["name"],
        "summary": "Renamed OneDrive item to CV-2026.docx.",
    }
    (call,) = harness.graph_calls("PATCH", "/me/drive/items/item-cv")
    assert call.body == {"name": "CV-2026.docx"}
    assert harness.fake.drive["item-cv"]["name"] == "CV-2026.docx"


def test_rename_root_is_refused(harness: UnifiedHarness) -> None:
    text = harness.error(
        "m365_update",
        {"resource": "drive_item", "id": "root", "drive_item_changes": {"name": "x"}},
    )

    assert text == "Invalid id: the OneDrive root cannot be renamed"
    assert not harness.graph_calls("PATCH")


# ----------------------------------------------------------------------
# m365_move
# ----------------------------------------------------------------------


def test_move_drive_item_by_path_with_new_name(harness: UnifiedHarness) -> None:
    result = harness.ok(
        "m365_move",
        {
            "resource": "drive_item",
            "id": "item-budget",
            "destination_path": "/Photos",
            "new_name": "budget-old.xlsx",
        },
    )

    assert result == {
        "resource": "drive_item",
        "previous_id": "item-budget",
        "id": "item-budget",
        "status": "moved",
        "destination_id": "item-photos",
        "summary": "Moved budget-old.xlsx to /Photos.",
    }
    (call,) = harness.graph_calls("PATCH", "/me/drive/items/item-budget")
    assert call.body == {
        "parentReference": {"id": "item-photos"},
        "name": "budget-old.xlsx",
    }
    assert harness.fake.drive["item-budget"]["parentReference"]["id"] == "item-photos"


def test_move_drive_item_to_root(harness: UnifiedHarness) -> None:
    result = harness.ok(
        "m365_move",
        {"resource": "drive_item", "id": "item-tax", "destination_id": "root"},
    )

    assert result["destination_id"] == "root"
    assert harness.fake.drive["item-tax"]["parentReference"]["id"] == "root"


def test_move_folder_into_own_subfolder_is_refused(harness: UnifiedHarness) -> None:
    text = harness.error(
        "m365_move",
        {
            "resource": "drive_item",
            "id": "item-documents",
            "destination_id": "item-tax",
        },
    )

    assert text == "Invalid destination_id: is inside the folder being moved"
    assert not harness.graph_calls("PATCH")


def test_move_drive_item_ambiguous_failure(harness: UnifiedHarness) -> None:
    original = harness.fake._drive_item

    def broken(method, params, body, item_id):
        if method == "PATCH":
            return _fail(500, "generalException")
        return original(method, params, body, item_id)

    harness.fake._drive_item = broken  # type: ignore[method-assign]

    text = harness.error(
        "m365_move",
        {"resource": "drive_item", "id": "item-cv", "destination_id": "item-photos"},
    )

    assert text == "Outcome unknown: check the destination folder before retrying"
    assert len(harness.graph_calls("PATCH")) == 1


def test_move_rejects_both_destinations(harness: UnifiedHarness) -> None:
    text = harness.error(
        "m365_move",
        {
            "resource": "drive_item",
            "id": "item-cv",
            "destination_id": "root",
            "destination_path": "/Photos",
        },
    )

    assert text == "Invalid destination_path: cannot be combined with destination_id"


# ----------------------------------------------------------------------
# m365_delete
# ----------------------------------------------------------------------


def test_delete_drive_file_example(harness: UnifiedHarness) -> None:
    _seed_item(harness, "01ABCDEF2345", "Tax return 2026.pdf", "item-tax")

    result = harness.ok(
        "m365_delete",
        {"resource": "drive_item", "id": "01ABCDEF2345", "confirm": True},
    )

    assert result == {
        "resource": "drive_item",
        "id": "01ABCDEF2345",
        "status": "deleted",
        "recoverable": True,
        "summary": "Moved 'Tax return 2026.pdf' to the OneDrive recycle bin.",
    }
    assert harness.graph_calls("DELETE", "/me/drive/items/01ABCDEF2345")
    assert "01ABCDEF2345" not in harness.fake.drive


def test_delete_drive_requires_confirm(harness: UnifiedHarness) -> None:
    text = harness.error(
        "m365_delete", {"resource": "drive_item", "id": "item-cv", "confirm": False}
    )

    assert text == (
        "Invalid confirm 'False': delete requires confirm=True to proceed. "
        "Expected: Explicit user confirmation"
    )
    assert not harness.graph_calls("DELETE")


def test_delete_drive_root_is_refused(harness: UnifiedHarness) -> None:
    text = harness.error(
        "m365_delete", {"resource": "drive_item", "id": "root", "confirm": True}
    )

    assert text == "Invalid id: the OneDrive root cannot be deleted"
    assert not harness.graph_calls("DELETE")


def test_delete_drive_ambiguous_failure(harness: UnifiedHarness) -> None:
    original = harness.fake._drive_item

    def broken(method, params, body, item_id):
        if method == "DELETE":
            return _fail(500, "generalException")
        return original(method, params, body, item_id)

    harness.fake._drive_item = broken  # type: ignore[method-assign]

    text = harness.error(
        "m365_delete", {"resource": "drive_item", "id": "item-cv", "confirm": True}
    )

    assert (
        text == "Outcome unknown: check whether the item still exists before retrying"
    )


# ----------------------------------------------------------------------
# drive_upload
# ----------------------------------------------------------------------


def test_upload_new_file_example(harness: UnifiedHarness) -> None:
    harness.fake.drive.pop("item-budget")
    local = harness.sandbox / "budget.xlsx"
    local.write_bytes(b"x" * 20480)

    result = harness.ok(
        "drive_upload", {"local_path": str(local), "parent_path": "/Documents"}
    )

    item = result["item"]
    assert result["status"] == "created"
    assert item["name"] == "budget.xlsx"
    assert item["item_type"] == "file"
    assert item["path"] == "/Documents"
    assert item["parent_id"] == "item-documents"
    assert item["size"] == 20480
    assert item["child_count"] is None
    assert item["children"] is None
    assert result["summary"] == "Uploaded budget.xlsx to /Documents."
    (call,) = harness.graph_calls(
        "PUT", "/me/drive/items/item-documents:/budget.xlsx:/content"
    )
    assert call.params["@microsoft.graph.conflictBehavior"] == "fail"
    assert call.body == b"x" * 20480


def test_upload_name_conflict_fails_by_default(harness: UnifiedHarness) -> None:
    local = harness.sandbox / "budget.xlsx"
    local.write_bytes(b"new")

    text = harness.error(
        "drive_upload", {"local_path": str(local), "parent_id": "item-documents"}
    )

    assert text == (
        "A file named 'budget.xlsx' already exists there. "
        "Expected: if_exists='replace' or 'rename'"
    )


def test_upload_replace_existing_name(harness: UnifiedHarness) -> None:
    local = harness.sandbox / "budget.xlsx"
    local.write_bytes(b"new")

    result = harness.ok(
        "drive_upload",
        {
            "local_path": str(local),
            "parent_id": "item-documents",
            "if_exists": "replace",
        },
    )

    assert result["status"] == "replaced"
    assert result["item"]["id"] == "item-budget"
    assert harness.fake.drive["item-budget"]["_content"] == b"new"


def test_upload_rename_on_conflict(harness: UnifiedHarness) -> None:
    result = harness.ok(
        "drive_upload",
        {
            "local_path": "report.pdf",
            "parent_id": "root",
            "name": "Notes.txt",
            "if_exists": "rename",
        },
    )

    assert result["status"] == "renamed"
    assert result["item"]["name"] != "Notes.txt"
    assert harness.fake.drive["item-notes"]["_content"] == b"fake contents of Notes.txt"
    assert harness.graph_calls("PUT", "/me/drive/items/root:/Notes.txt:/content")


def test_upload_replace_by_item_id(harness: UnifiedHarness) -> None:
    result = harness.ok(
        "drive_upload", {"local_path": "notes-new.txt", "item_id": "item-notes"}
    )

    assert result["status"] == "replaced"
    assert result["item"]["id"] == "item-notes"
    assert harness.graph_calls("PUT", "/me/drive/items/item-notes/content")
    local = (harness.sandbox / "notes-new.txt").read_bytes()
    assert harness.fake.drive["item-notes"]["_content"] == local


def test_upload_exactly_four_mib_uses_simple_put(harness: UnifiedHarness) -> None:
    (harness.sandbox / "four.bin").write_bytes(b"\0" * (4 * MIB))

    harness.ok("drive_upload", {"local_path": "four.bin", "parent_id": "root"})

    assert harness.graph_calls("PUT", "/me/drive/items/root:/four.bin:/content")
    assert not harness.graph_calls("POST")


def test_upload_large_file_uses_upload_session(harness: UnifiedHarness) -> None:
    (harness.sandbox / "big.bin").write_bytes(b"\1" * (4 * MIB + 1))

    result = harness.ok(
        "drive_upload", {"local_path": "big.bin", "parent_id": "item-documents"}
    )

    assert result["status"] == "created"
    (session,) = harness.graph_calls(
        "POST", "/me/drive/items/item-documents:/big.bin:/createUploadSession"
    )
    assert session.body == {"item": {"@microsoft.graph.conflictBehavior": "fail"}}
    chunks = harness.graph_calls("PUT", "/drive/item-documents/big.bin")
    assert chunks


def test_upload_large_replacement_uses_item_session(harness: UnifiedHarness) -> None:
    (harness.sandbox / "big.bin").write_bytes(b"\1" * (4 * MIB + 1))

    result = harness.ok(
        "drive_upload", {"local_path": "big.bin", "item_id": "item-notes"}
    )

    assert result["status"] == "replaced"
    assert harness.graph_calls("POST", "/me/drive/items/item-notes/createUploadSession")


def test_upload_target_exclusivity(harness: UnifiedHarness) -> None:
    text = harness.error(
        "drive_upload",
        {"local_path": "report.pdf", "item_id": "item-notes", "parent_id": "root"},
    )

    assert text == "Invalid item_id: cannot be combined with parent_id or parent_path"


def test_upload_requires_a_target(harness: UnifiedHarness) -> None:
    text = harness.error("drive_upload", {"local_path": "report.pdf"})

    assert text == (
        "Invalid parent_id: required. Expected: parent_id, parent_path or item_id"
    )


def test_upload_parent_exclusivity(harness: UnifiedHarness) -> None:
    text = harness.error(
        "drive_upload",
        {"local_path": "report.pdf", "parent_id": "root", "parent_path": "/"},
    )

    assert text == "Invalid parent_path: cannot be combined with parent_id"


def test_upload_name_only_for_new_files(harness: UnifiedHarness) -> None:
    text = harness.error(
        "drive_upload",
        {"local_path": "report.pdf", "item_id": "item-notes", "name": "x.pdf"},
    )

    assert text == (
        "Invalid name: only valid for a new file. "
        "Expected: remove name, or use parent_id or parent_path"
    )


def test_upload_refuses_protected_files(harness: UnifiedHarness) -> None:
    text = harness.error("drive_upload", {"local_path": ".env", "parent_id": "root"})

    assert text == "Invalid local_path: '.env' is a protected file"
    assert not harness.graph_calls()


# ----------------------------------------------------------------------
# drive_copy
# ----------------------------------------------------------------------


def test_copy_example(harness: UnifiedHarness) -> None:
    _seed_item(harness, "01ABCDEF6789", "budget.xlsx", "item-documents")
    _seed_item(harness, "item-backups", "Backups", "root", folder=True)

    result = harness.ok(
        "drive_copy", {"item_id": "01ABCDEF6789", "destination_path": "/Backups"}
    )

    op_id = result["operation_id"]
    assert op_id.startswith("op_")
    assert result["status"] == "in_progress"
    assert result["summary"] == (
        f"Copy started; check with m365_get(resource='operation', id='{op_id}')."
    )
    (call,) = harness.graph_calls("POST", "/me/drive/items/01ABCDEF6789/copy")
    assert call.body["parentReference"]["id"] == "item-backups"
    assert "name" not in call.body

    status = harness.ok("m365_get", {"resource": "operation", "id": op_id})
    assert status["item"]["status"] == "completed"
    copied = status["item"]["resource_id"]
    assert harness.fake.drive[copied]["parentReference"]["id"] == "item-backups"


def test_copy_with_new_name_to_root(harness: UnifiedHarness) -> None:
    harness.ok(
        "drive_copy",
        {"item_id": "item-cv", "destination_id": "root", "new_name": "CV copy.docx"},
    )

    (call,) = harness.graph_calls("POST", "/me/drive/items/item-cv/copy")
    assert call.body["name"] == "CV copy.docx"
    assert call.body["parentReference"]["id"] == "root"


def test_copy_destination_exclusivity(harness: UnifiedHarness) -> None:
    text = harness.error(
        "drive_copy",
        {"item_id": "item-cv", "destination_id": "root", "destination_path": "/"},
    )

    assert text == "Invalid destination_path: cannot be combined with destination_id"


def test_copy_requires_destination(harness: UnifiedHarness) -> None:
    text = harness.error("drive_copy", {"item_id": "item-cv"})

    assert text == "Invalid destination_id: required"


# ----------------------------------------------------------------------
# drive_share
# ----------------------------------------------------------------------


def test_share_view_link_example(harness: UnifiedHarness) -> None:
    _seed_item(harness, "01ABCDEF6789", "budget.xlsx", "item-documents")

    result = harness.ok(
        "drive_share",
        {
            "item_id": "01ABCDEF6789",
            "mode": "link",
            "link_type": "view",
            "confirm": True,
        },
    )

    assert result == {
        "mode": "link",
        "permission_ids": ["perm-01ABCDEF6789-view"],
        "link_url": "https://1drv.ms/x/s!01ABCDEF6789-view",
        "created": True,
        "recipients": [],
        "summary": (
            "Created a view-only link to budget.xlsx "
            "(anyone with the link can open it)."
        ),
    }
    (call,) = harness.graph_calls("POST", "/me/drive/items/01ABCDEF6789/createLink")
    assert call.body == {"type": "view", "scope": "anonymous"}


def test_share_link_reports_existing_link(harness: UnifiedHarness) -> None:
    def existing(method, params, body, item_id):
        return 200, {
            "id": "perm-existing",
            "roles": ["write"],
            "link": {"type": "edit", "webUrl": "https://1drv.ms/x/s!existing"},
        }

    _patch_action(harness, "createLink", existing)

    result = harness.ok(
        "drive_share",
        {
            "item_id": "item-budget",
            "mode": "link",
            "link_type": "edit",
            "password": "s3cret-pass",
            "expires_at": "2026-12-31T00:00:00+10:30",
            "confirm": True,
        },
    )

    assert result["created"] is False
    assert result["permission_ids"] == ["perm-existing"]
    assert result["summary"].startswith("Returned the existing edit link")
    (call,) = harness.graph_calls("POST", "/me/drive/items/item-budget/createLink")
    assert call.body == {
        "type": "edit",
        "scope": "anonymous",
        "password": "s3cret-pass",
        "expirationDateTime": "2026-12-31T00:00:00+10:30",
    }


def test_share_requires_confirm(harness: UnifiedHarness) -> None:
    text = harness.error(
        "drive_share",
        {
            "item_id": "item-budget",
            "mode": "link",
            "link_type": "view",
            "confirm": False,
        },
    )

    assert text == (
        "Invalid confirm 'False': sharing requires confirm=True to proceed. "
        "Expected: Explicit user confirmation"
    )
    assert not harness.graph_calls("POST")


def test_share_root_is_refused(harness: UnifiedHarness) -> None:
    text = harness.error(
        "drive_share",
        {"item_id": "root", "mode": "link", "link_type": "view", "confirm": True},
    )

    assert text == "Invalid item_id: the OneDrive root cannot be shared"
    assert not harness.graph_calls("POST")


def test_share_embed_only_for_files(harness: UnifiedHarness) -> None:
    text = harness.error(
        "drive_share",
        {"item_id": "item-tax", "mode": "link", "link_type": "embed", "confirm": True},
    )

    assert text == "Invalid link_type 'embed': only files can be embedded"
    assert not harness.graph_calls("POST")

    result = harness.ok(
        "drive_share",
        {"item_id": "item-cv", "mode": "link", "link_type": "embed", "confirm": True},
    )
    assert result["created"] is True


def test_share_link_rejects_invite_fields(harness: UnifiedHarness) -> None:
    text = harness.error(
        "drive_share",
        {
            "item_id": "item-cv",
            "mode": "link",
            "link_type": "view",
            "recipients": ["a@example.com"],
            "confirm": True,
        },
    )

    assert text == "Invalid recipients: only valid with mode='invite'"


def test_share_invite_rejects_link_type(harness: UnifiedHarness) -> None:
    text = harness.error(
        "drive_share",
        {
            "item_id": "item-cv",
            "mode": "invite",
            "recipients": ["a@example.com"],
            "role": "read",
            "link_type": "view",
            "confirm": True,
        },
    )

    assert text == "Invalid link_type: only valid with mode='link'"


def test_share_link_requires_link_type(harness: UnifiedHarness) -> None:
    text = harness.error(
        "drive_share", {"item_id": "item-cv", "mode": "link", "confirm": True}
    )

    assert text == "Invalid link_type: required when mode='link'"


def test_share_invite_requires_recipients_and_role(harness: UnifiedHarness) -> None:
    missing_recipients = harness.error(
        "drive_share",
        {"item_id": "item-cv", "mode": "invite", "role": "read", "confirm": True},
    )
    missing_role = harness.error(
        "drive_share",
        {
            "item_id": "item-cv",
            "mode": "invite",
            "recipients": ["a@example.com"],
            "confirm": True,
        },
    )

    assert missing_recipients == "Invalid recipients: required when mode='invite'"
    assert missing_role == "Invalid role: required when mode='invite'"


def test_share_invite(harness: UnifiedHarness) -> None:
    result = harness.ok(
        "drive_share",
        {
            "item_id": "item-cv",
            "mode": "invite",
            "recipients": ["a@example.com", "b@example.com"],
            "role": "write",
            "message": "Please review",
            "confirm": True,
        },
    )

    assert result["mode"] == "invite"
    assert result["link_url"] is None
    assert result["created"] is None
    assert result["permission_ids"] == ["perm-item-cv-0", "perm-item-cv-1"]
    assert result["recipients"] == [
        {"email": "a@example.com", "status": "granted", "error": None},
        {"email": "b@example.com", "status": "granted", "error": None},
    ]
    (call,) = harness.graph_calls("POST", "/me/drive/items/item-cv/invite")
    assert call.body == {
        "recipients": [{"email": "a@example.com"}, {"email": "b@example.com"}],
        "roles": ["write"],
        "message": "Please review",
        "sendInvitation": True,
        "requireSignIn": True,
    }


def test_share_invite_partial_success(harness: UnifiedHarness) -> None:
    def partial(method, params, body, item_id):
        return 207, {
            "value": [
                {
                    "id": "perm-ok",
                    "roles": ["read"],
                    "invitation": {"email": "a@example.com"},
                },
                {
                    "error": {
                        "code": "notAllowed",
                        "message": "Account verification needed.",
                    }
                },
            ]
        }

    _patch_action(harness, "invite", partial)

    result = harness.ok(
        "drive_share",
        {
            "item_id": "item-cv",
            "mode": "invite",
            "recipients": ["a@example.com", "b@example.com"],
            "role": "read",
            "send_invitation": False,
            "require_sign_in": False,
            "confirm": True,
        },
    )

    assert result["permission_ids"] == ["perm-ok"]
    assert result["recipients"] == [
        {"email": "a@example.com", "status": "granted", "error": None},
        {
            "email": "b@example.com",
            "status": "failed",
            "error": "Account verification needed.",
        },
    ]
    assert "1 failed" in result["summary"]
    (call,) = harness.graph_calls("POST", "/me/drive/items/item-cv/invite")
    assert call.body["sendInvitation"] is False
    assert call.body["requireSignIn"] is False
