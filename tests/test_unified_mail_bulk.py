"""Tests for email_folder_mark_all_read (U3.20) and email_folder_empty (U3.21)."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from m365_mcp.rate_limit import RateLimiter
from m365_mcp.tool_specs import load_tool_spec
from m365_mcp.tools.unified import common


@pytest.fixture(autouse=True)
def _fresh_rate_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give each test its own budget so deletes never hit the shared limit."""
    monkeypatch.setattr(common, "rate_limiter", RateLimiter())


def _example(tool: str) -> dict[str, Any]:
    return copy.deepcopy(load_tool_spec(tool)["examples"][0])


def _seed(harness, folder: str, count: int, *, is_read: bool = False) -> list[str]:
    ids = []
    for index in range(count):
        msg_id = f"{folder}-bulk-{index:04d}"
        harness.fake.messages[msg_id] = {
            "id": msg_id,
            "subject": f"Bulk {index}",
            "receivedDateTime": f"2026-09-01T{index % 24:02d}:00:00Z",
            "isRead": is_read,
            "parentFolderId": folder,
        }
        ids.append(msg_id)
    return ids


def _clear_folder(harness, folder: str) -> None:
    for msg_id in [
        m["id"] for m in harness.fake.messages.values() if m["parentFolderId"] == folder
    ]:
        del harness.fake.messages[msg_id]


def _fail_messages(
    harness, monkeypatch: pytest.MonkeyPatch, method: str, ids: set[str]
) -> None:
    """Make the fake refuse ``method`` on the given message IDs."""
    original = harness.fake.dispatch

    def dispatch(
        req_method: str, path: str, params: dict[str, str], body: Any
    ) -> tuple[int, Any]:
        if req_method.upper() == method and path.rsplit("/", 1)[-1] in ids:
            return 403, {"error": {"code": "ErrorAccessDenied", "message": "no"}}
        return original(req_method, path, params, body)

    monkeypatch.setattr(harness.fake, "dispatch", dispatch)


def _batch_sizes(harness) -> list[int]:
    return [len(c.body["requests"]) for c in harness.graph_calls("POST", "/$batch")]


# ----------------------------------------------------------------------
# email_folder_mark_all_read
# ----------------------------------------------------------------------


def test_mark_all_read_example_junk(harness) -> None:
    example = _example("email_folder_mark_all_read")
    _clear_folder(harness, "junkemail")
    ids = _seed(harness, "junkemail", 42)

    data = harness.ok("email_folder_mark_all_read", example["input"])

    assert data["marked"] == example["output"]["marked"]
    assert data["remaining_unread"] == 0
    assert data["summary"] == example["output"]["summary"]
    assert data["folder_id"] == "junkemail"
    assert all(harness.fake.messages[i]["isRead"] for i in ids)

    [page] = harness.graph_calls("GET", "/me/mailFolders/junkemail/messages")
    assert page.params["$filter"] == "isRead eq false"
    assert page.params["$select"] == "id"
    assert _batch_sizes(harness) == [20, 20, 2]
    patches = harness.graph_calls("PATCH")
    assert len(patches) == 42
    assert all(p.body == {"isRead": True} for p in patches)
    assert {p.path for p in patches} == {f"/me/messages/{i}" for i in ids}


def test_mark_all_read_is_bounded_by_max_messages(harness) -> None:
    _clear_folder(harness, "archive")
    _seed(harness, "archive", 30)
    data = harness.ok(
        "email_folder_mark_all_read", {"folder_id": "archive", "max_messages": 25}
    )
    assert data["marked"] == 25
    assert data["remaining_unread"] == 5
    assert "call again" in data["summary"]
    again = harness.ok(
        "email_folder_mark_all_read", {"folder_id": "archive", "max_messages": 25}
    )
    assert again["marked"] == 5 and again["remaining_unread"] == 0


def test_mark_all_read_pages_unread_ids(harness) -> None:
    _clear_folder(harness, "archive")
    _seed(harness, "archive", 1500)
    data = harness.ok(
        "email_folder_mark_all_read", {"folder_id": "archive", "max_messages": 1200}
    )
    assert data["marked"] == 1200
    assert data["remaining_unread"] == 300
    pages = harness.graph_calls("GET", "/me/mailFolders/archive/messages")
    assert len(pages) == 2


def test_mark_all_read_skips_read_messages(harness) -> None:
    _clear_folder(harness, "archive")
    _seed(harness, "archive", 3, is_read=True)
    data = harness.ok("email_folder_mark_all_read", {"folder_id": "archive"})
    assert data["marked"] == 0 and data["remaining_unread"] == 0
    assert not harness.graph_calls("POST", "/$batch")
    assert data["summary"] == "No unread messages in Archive."


def test_mark_all_read_counts_failures_as_remaining(
    harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_folder(harness, "archive")
    ids = _seed(harness, "archive", 10)
    _fail_messages(harness, monkeypatch, "PATCH", set(ids[:3]))
    data = harness.ok("email_folder_mark_all_read", {"folder_id": "archive"})
    assert data["marked"] == 7
    assert data["remaining_unread"] == 3


def test_mark_all_read_by_folder_id(harness) -> None:
    ids = _seed(harness, "folder-receipts", 2)
    data = harness.ok("email_folder_mark_all_read", {"folder_id": "folder-receipts"})
    assert data["folder_id"] == "folder-receipts"
    assert data["summary"] == "Marked 2 messages read in Receipts."
    assert all(harness.fake.messages[i]["isRead"] for i in ids)


def test_mark_all_read_unknown_alias(harness) -> None:
    text = harness.error("email_folder_mark_all_read", {"folder_id": "Inbx"})
    assert text == "Invalid folder_id 'Inbx': unknown folder alias"


# ----------------------------------------------------------------------
# email_folder_empty
# ----------------------------------------------------------------------


def test_empty_requires_confirm(harness) -> None:
    ids = _seed(harness, "deleteditems", 2)
    text = harness.error(
        "email_folder_empty", {"folder_id": "deleted", "confirm": False}
    )
    assert text == (
        "Invalid confirm 'False': empty folder requires confirm=True to proceed. "
        "Expected: Explicit user confirmation"
    )
    assert all(i in harness.fake.messages for i in ids)
    assert not harness.graph_calls()


def test_empty_example_deleted_items(harness) -> None:
    example = _example("email_folder_empty")
    _clear_folder(harness, "deleteditems")
    _seed(harness, "deleteditems", 318)
    harness.fake.folders["folder-old-projects"]["parentFolderId"] = "deleteditems"

    data = harness.ok("email_folder_empty", example["input"])

    assert data["deleted"] == example["output"]["deleted"]
    assert data["remaining"] == 0
    assert data["summary"] == example["output"]["summary"]
    assert data["folder_id"] == "deleteditems"
    assert not [
        m
        for m in harness.fake.messages.values()
        if m["parentFolderId"] == "deleteditems"
    ]
    # Subfolders are kept.
    assert "folder-old-projects" in harness.fake.folders
    [page] = harness.graph_calls("GET", "/me/mailFolders/deleteditems/messages")
    assert page.params["$select"] == "id"
    assert "$filter" not in page.params
    assert _batch_sizes(harness) == [20] * 15 + [18]
    assert len(harness.graph_calls("DELETE")) == 318


def test_empty_is_bounded_by_max_messages(harness) -> None:
    _clear_folder(harness, "junkemail")
    _seed(harness, "junkemail", 12, is_read=True)
    data = harness.ok(
        "email_folder_empty",
        {"folder_id": "junk", "max_messages": 10, "confirm": True},
    )
    assert data["deleted"] == 10
    assert data["remaining"] == 2
    assert "call again" in data["summary"]


def test_empty_reports_partial_failures(
    harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_folder(harness, "junkemail")
    ids = _seed(harness, "junkemail", 200)
    _fail_messages(harness, monkeypatch, "DELETE", set(ids[:20]))
    data = harness.ok("email_folder_empty", {"folder_id": "junk", "confirm": True})
    assert data["deleted"] == 180
    assert data["remaining"] == 20
    assert data["summary"] == (
        "Deleted 180 of 200; 20 failed (see remaining). Call again to retry the rest"
    )


def test_empty_an_empty_folder(harness) -> None:
    _clear_folder(harness, "junkemail")
    data = harness.ok("email_folder_empty", {"folder_id": "junk", "confirm": True})
    assert data["deleted"] == 0 and data["remaining"] == 0
    assert data["summary"] == "Junk Email is already empty."
    assert not harness.graph_calls("POST", "/$batch")
