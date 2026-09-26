"""Parity tests for legacy_mapping.json rows 43-84 (task U3.30, part 2).

One parametrized test per mapping row. Each row has a scenario: it performs
the practical task through the unified surface (the ``harness`` fixture) and
asserts the resulting fake-Graph state. Where the legacy tool is a plain
equivalent, the same task is also run through the legacy tool on a fresh,
identically seeded fake Graph and both end states are compared. Rows whose
``behaviour_change`` is set assert the NEW behaviour instead.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from evals.fake_graph import FakeGraph
from tests.parity_helpers_part2 import compare, run_legacy, seeded_copy
from tests.unified_harness import UnifiedHarness

MAPPING = json.loads(
    (Path(__file__).parent.parent / "docs/unified-tools/legacy_mapping.json").read_text(
        encoding="utf-8"
    )
)["mapping"]
ROWS = MAPPING[43:85]

Scenario = Callable[[UnifiedHarness], None]
SCENARIOS: dict[str, Scenario] = {}


def scenario(legacy_tool: str) -> Callable[[Scenario], Scenario]:
    """Register the scenario for the mapping row of ``legacy_tool``."""

    def register(fn: Scenario) -> Scenario:
        assert legacy_tool not in SCENARIOS
        SCENARIOS[legacy_tool] = fn
        return fn

    return register


# ----------------------------------------------------------------------
# shared views and helpers
# ----------------------------------------------------------------------
SEED_MESSAGE_IDS = set(seeded_copy().messages)
SEED_DRIVE_IDS = set(seeded_copy().drive)


def _addrs(recipients: list[dict[str, Any]]) -> list[str]:
    return sorted(r["emailAddress"]["address"] for r in recipients)


def _new_messages(g: FakeGraph) -> list[tuple[Any, ...]]:
    """Messages that were not in the seed: content only (ids differ)."""
    return sorted(
        (
            m["parentFolderId"],
            m["subject"],
            tuple(_addrs(m["toRecipients"])),
            tuple(_addrs(m["ccRecipients"])),
            m["body"]["content"],
        )
        for mid, m in g.messages.items()
        if mid not in SEED_MESSAGE_IDS
    )


def _folder_of(g: FakeGraph, subject: str) -> list[str]:
    return sorted(
        m["parentFolderId"] for m in g.messages.values() if m["subject"] == subject
    )


def _msg(g: FakeGraph, msg_id: str, *fields: str) -> tuple[Any, ...]:
    return tuple(g.messages[msg_id][f] for f in fields)


def _local_file(h: UnifiedHarness, name: str, data: bytes) -> str:
    (h.sandbox / name).write_bytes(data)
    return name


# ----------------------------------------------------------------------
# rows 43-46: email rule reordering
# ----------------------------------------------------------------------
def _add_third_rule(g: FakeGraph) -> None:
    g.rules["rule-third"] = {
        "id": "rule-third",
        "displayName": "Third",
        "sequence": 3,
        "isEnabled": True,
        "hasError": False,
        "isReadOnly": False,
        "conditions": {"subjectContains": ["x"]},
        "actions": {"markAsRead": True},
    }


def _rule_order(g: FakeGraph) -> list[str]:
    return [r["id"] for r in sorted(g.rules.values(), key=lambda r: r["sequence"])]


def _rule_reorder(
    h: UnifiedHarness,
    legacy_tool: str,
    rule_id: str,
    position: str,
    expected: list[str],
) -> None:
    _add_third_rule(h.fake)
    assert _rule_order(h.fake) == ["rule-news", "rule-boss", "rule-third"]
    legacy = run_legacy(legacy_tool, {"rule_id": rule_id}, prepare=_add_third_rule)
    assert not legacy.is_error, legacy.text
    h.ok(
        "email_rule_manage",
        {"action": "reorder", "rule_id": rule_id, "position": position},
    )
    assert _rule_order(h.fake) == expected
    # Legacy only sets the moved rule's sequence (ties are left to Graph), so
    # check the intent: it now runs first / last / before or after its
    # neighbour. The unified call renumbers, so its order is strict above.
    seq = {k: v["sequence"] for k, v in legacy.graph.rules.items()}
    others = [v for k, v in seq.items() if k != rule_id]
    if position == "top":
        assert seq[rule_id] <= min(others)
    elif position == "bottom":
        assert seq[rule_id] > max(others)
    elif position == "up":
        assert seq[rule_id] <= seq["rule-boss"]
    else:
        assert seq[rule_id] >= seq["rule-boss"]


@scenario("emailrules_move_top")
def _(h: UnifiedHarness) -> None:
    _rule_reorder(
        h, "emailrules_move_top", "rule-third", "top",
        ["rule-third", "rule-news", "rule-boss"],
    )  # fmt: skip


@scenario("emailrules_move_bottom")
def _(h: UnifiedHarness) -> None:
    _rule_reorder(
        h, "emailrules_move_bottom", "rule-news", "bottom",
        ["rule-boss", "rule-third", "rule-news"],
    )  # fmt: skip


@scenario("emailrules_move_up")
def _(h: UnifiedHarness) -> None:
    _rule_reorder(
        h, "emailrules_move_up", "rule-third", "up",
        ["rule-news", "rule-third", "rule-boss"],
    )  # fmt: skip


@scenario("emailrules_move_down")
def _(h: UnifiedHarness) -> None:
    _rule_reorder(
        h, "emailrules_move_down", "rule-news", "down",
        ["rule-boss", "rule-news", "rule-third"],
    )  # fmt: skip


# ----------------------------------------------------------------------
# rows 47-61: email
# ----------------------------------------------------------------------
INBOX_IDS = {
    m["id"] for m in seeded_copy().messages.values() if m["parentFolderId"] == "inbox"
}


@scenario("email_list")
def _(h: UnifiedHarness) -> None:
    # Practical task: list the newest inbox messages. Same messages either way.
    legacy = run_legacy("email_list", {"folder": "inbox", "limit": 5})
    assert not legacy.is_error, legacy.text
    legacy_ids = [m["id"] for m in json.loads(legacy.text)]
    page = h.ok("m365_list", {"resource": "email", "container_id": "inbox", "limit": 5})
    assert [m["id"] for m in page["items"]] == legacy_ids
    assert len(legacy_ids) == 5

    # NEW: compact items carry a preview, not the body.
    for item in page["items"]:
        assert item["preview"] and "body" not in item
    # NEW: filters.
    unread = h.ok(
        "m365_list",
        {
            "resource": "email",
            "container_id": "inbox",
            "email_filter": {"unread": True},
            "limit": 50,
        },
    )
    assert {m["id"] for m in unread["items"]} == {
        m["id"]
        for m in h.fake.messages.values()
        if m["parentFolderId"] == "inbox" and not m["isRead"]
    }
    # NEW: cursor paging walks the whole folder without repeats.
    seen: list[str] = []
    cursor = None
    while True:
        args: dict[str, Any] = {
            "resource": "email",
            "container_id": "inbox",
            "limit": 7,
        }
        if cursor:
            args["cursor"] = cursor
        page = h.ok("m365_list", args)
        seen += [m["id"] for m in page["items"]]
        cursor = page.get("next_cursor")
        if not cursor:
            break
    assert len(seen) == len(set(seen)) and set(seen) == INBOX_IDS


@scenario("email_get")
def _(h: UnifiedHarness) -> None:
    long_body = "word " * 8000  # 40,000 characters
    h.fake.messages["msg-004"]["body"]["content"] = long_body
    # NEW: the default body cap is 20k characters (legacy default was 50k).
    default = h.ok("m365_get", {"resource": "email", "id": "msg-004"})["item"]
    assert len(default["body"]) == 20000 and default["body_truncated"] is True
    assert default["attachments"][0]["name"] == "INV-2291.pdf"
    wide = h.ok(
        "m365_get", {"resource": "email", "id": "msg-004", "body_max_chars": 50000}
    )["item"]
    assert wide["body"] == long_body and wide["body_truncated"] is False


@scenario("email_create_draft")
def _(h: UnifiedHarness) -> None:
    legacy_args = {
        "to": "sam.lee@example.com",
        "cc": "mark.brown@example.com",
        "subject": "Modem",
        "body": "It came.",
    }
    legacy = run_legacy("email_create_draft", legacy_args)
    assert not legacy.is_error, legacy.text
    h.ok(
        "email_create_draft",
        {
            "to": ["sam.lee@example.com"],
            "cc": ["mark.brown@example.com"],
            "subject": "Modem",
            "body": "It came.",
        },
    )
    expected = [
        (
            "drafts",
            "Modem",
            ("sam.lee@example.com",),
            ("mark.brown@example.com",),
            "It came.",
        )
    ]
    assert _new_messages(legacy.graph) == _new_messages(h.fake) == expected

    # NEW: bcc, body_format and importance.
    h.ok(
        "email_create_draft",
        {
            "to": ["sam.lee@example.com"],
            "bcc": ["boss@example.com"],
            "subject": "Formatted",
            "body": "<b>Hi</b>",
            "body_format": "html",
            "importance": "high",
        },
    )
    (draft,) = [
        m
        for mid, m in h.fake.messages.items()
        if mid not in SEED_MESSAGE_IDS and m["subject"] == "Formatted"
    ]
    assert _addrs(draft["bccRecipients"]) == ["boss@example.com"]
    assert draft["body"] == {"contentType": "HTML", "content": "<b>Hi</b>"}
    assert draft["importance"] == "high" and draft["parentFolderId"] == "drafts"


@scenario("email_send")
def _(h: UnifiedHarness) -> None:
    legacy = run_legacy(
        "email_send",
        {
            "to": "sam.lee@example.com",
            "subject": "Modem arrived",
            "body": "It came.",
            "confirm": True,
        },
    )
    assert not legacy.is_error, legacy.text
    h.ok(
        "email_send",
        {
            "mode": "new",
            "to": ["sam.lee@example.com"],
            "subject": "Modem arrived",
            "body": "It came.",
            "confirm": True,
        },
    )
    expected = [
        ("sentitems", "Modem arrived", ("sam.lee@example.com",), (), "It came.")
    ]
    assert _new_messages(legacy.graph) == _new_messages(h.fake) == expected

    # NEW: bcc is delivered.
    h.ok(
        "email_send",
        {
            "mode": "new",
            "to": ["sam.lee@example.com"],
            "bcc": ["boss@example.com"],
            "subject": "Hidden copy",
            "body": "x",
            "confirm": True,
        },
    )
    (sent,) = [m for m in h.fake.messages.values() if m["subject"] == "Hidden copy"]
    assert _addrs(sent["bccRecipients"]) == ["boss@example.com"]
    # NEW: mode='draft' sends an existing draft.
    draft = h.ok(
        "email_create_draft",
        {"to": ["sam.lee@example.com"], "subject": "Later", "body": "y"},
    )["draft_id"]
    assert h.fake.messages[draft]["parentFolderId"] == "drafts"
    h.ok("email_send", {"mode": "draft", "draft_id": draft, "confirm": True})
    assert h.fake.messages[draft]["parentFolderId"] == "sentitems"
    assert h.fake.messages[draft]["isDraft"] is False


@scenario("email_update")
def _(h: UnifiedHarness) -> None:
    legacy = run_legacy(
        "email_update",
        {
            "email_id": "msg-001",
            "updates": {
                "isRead": True,
                "importance": "high",
                "categories": ["Home"],
            },
        },
    )
    assert not legacy.is_error, legacy.text
    h.ok(
        "m365_update",
        {
            "resource": "email",
            "id": "msg-001",
            "email_changes": {
                "is_read": True,
                "importance": "high",
                "categories_set": ["Home"],
            },
        },
    )

    def view(g: FakeGraph) -> tuple[Any, ...]:
        return _msg(g, "msg-001", "isRead", "importance", "categories")

    assert compare(h, legacy, view) == (True, "high", ["Home"])


@scenario("email_delete")
def _(h: UnifiedHarness) -> None:
    legacy = run_legacy("email_delete", {"email_id": "msg-004", "confirm": True})
    assert not legacy.is_error, legacy.text
    h.ok("m365_delete", {"resource": "email", "id": "msg-004", "confirm": True})

    def view(g: FakeGraph) -> Any:
        return _folder_of(g, "Invoice INV-2291 from Acme Plumbing")

    assert view(legacy.graph) == view(h.fake)
    assert "inbox" not in view(h.fake)
    # Refused without confirmation.
    text = h.error(
        "m365_delete", {"resource": "email", "id": "msg-005", "confirm": False}
    )
    assert "confirm" in text and "msg-005" in h.fake.messages


@scenario("email_move")
def _(h: UnifiedHarness) -> None:
    legacy = run_legacy(
        "email_move", {"email_id": "msg-004", "destination_folder": "drafts"}
    )
    assert not legacy.is_error, legacy.text
    data = h.ok(
        "m365_move",
        {"resource": "email", "id": "msg-004", "destination_id": "drafts"},
    )
    # NEW: the move returns the new message ID; the old one is gone.
    assert data["id"] != "msg-004" and data["previous_id"] == "msg-004"
    assert "msg-004" not in h.fake.messages
    assert h.fake.messages[data["id"]]["parentFolderId"] == "drafts"

    def view(g: FakeGraph) -> Any:
        return _folder_of(g, "Invoice INV-2291 from Acme Plumbing")

    assert compare(h, legacy, view) == ["drafts"]


def _reply_scenario(h: UnifiedHarness, legacy_tool: str, mode: str) -> None:
    """msg-003 (from Jane, cc Mark) replied to; compare sender/all replies."""
    legacy = run_legacy(
        legacy_tool, {"email_id": "msg-003", "body": "Yes, see you 7.", "confirm": True}
    )
    assert not legacy.is_error, legacy.text
    h.ok(
        "email_reply",
        {
            "email_id": "msg-003",
            "mode": mode,
            "body": "Yes, see you 7.",
            "confirm": True,
        },
    )

    def view(g: FakeGraph) -> Any:
        return [
            (m["parentFolderId"], m["subject"], m["body"]["content"])
            for mid, m in g.messages.items()
            if mid not in SEED_MESSAGE_IDS
        ]

    assert compare(h, legacy, view) == [
        ("sentitems", "Re: Dinner on Saturday?", "Yes, see you 7.")
    ]

    # NEW: cc and attachments on the reply.
    name = _local_file(h, "map.txt", b"the map")
    h.ok(
        "email_reply",
        {
            "email_id": "msg-003",
            "mode": mode,
            "body": "Map attached",
            "cc": ["kim@example.com"],
            "attachments": [name],
            "confirm": True,
        },
    )
    (sent,) = [
        (mid, m)
        for mid, m in h.fake.messages.items()
        if mid not in SEED_MESSAGE_IDS
        and "kim@example.com" in _addrs(m["ccRecipients"])
    ]
    assert sent[1]["parentFolderId"] == "sentitems"
    assert h.fake.attachments[sent[0]][0]["name"] == name
    assert base64.b64decode(h.fake.attachments[sent[0]][0]["contentBytes"]) == (
        b"the map"
    )


@scenario("email_reply")
def _(h: UnifiedHarness) -> None:
    _reply_scenario(h, "email_reply", "sender")


@scenario("email_reply_all")
def _(h: UnifiedHarness) -> None:
    _reply_scenario(h, "email_reply_all", "all")


@scenario("email_forward")
def _(h: UnifiedHarness) -> None:
    legacy = run_legacy(
        "email_forward",
        {
            "email_id": "msg-004",
            "to": "sam.lee@example.com",
            "body": "FYI",
            "confirm": True,
        },
    )
    assert not legacy.is_error, legacy.text
    h.ok(
        "email_forward",
        {
            "email_id": "msg-004",
            "to": ["sam.lee@example.com"],
            "comment": "FYI",
            "confirm": True,
        },
    )

    def view(g: FakeGraph) -> Any:
        return [
            (m["parentFolderId"], m["subject"], tuple(_addrs(m["toRecipients"])))
            for mid, m in g.messages.items()
            if mid not in SEED_MESSAGE_IDS
        ]

    assert compare(h, legacy, view) == [
        (
            "sentitems",
            "Fw: Invoice INV-2291 from Acme Plumbing",
            ("sam.lee@example.com",),
        )
    ]

    # NEW: bcc and attachments.
    name = _local_file(h, "extra.txt", b"extra")
    h.ok(
        "email_forward",
        {
            "email_id": "msg-004",
            "to": ["sam.lee@example.com"],
            "bcc": ["boss@example.com"],
            "attachments": [name],
            "confirm": True,
        },
    )
    (sent,) = [
        (mid, m)
        for mid, m in h.fake.messages.items()
        if mid not in SEED_MESSAGE_IDS and _addrs(m["bccRecipients"])
    ]
    assert _addrs(sent[1]["bccRecipients"]) == ["boss@example.com"]
    assert sent[1]["parentFolderId"] == "sentitems"
    assert h.fake.attachments[sent[0]][0]["name"] == name


@scenario("email_get_attachment")
def _(h: UnifiedHarness) -> None:
    legacy = run_legacy(
        "email_get_attachment",
        {"email_id": "msg-004", "attachment_id": "att-invoice", "save_path": "inv.pdf"},
    )
    assert not legacy.is_error, legacy.text
    args = {
        "resource": "email",
        "id": "msg-004",
        "attachment_id": "att-invoice",
        "mode": "download",
        "save_path": "inv.pdf",
    }
    h.ok("m365_get_content", args)
    expected = b"fake INV-2291.pdf content"
    assert (h.sandbox / "inv.pdf").read_bytes() == expected
    assert legacy.sandbox_files["inv.pdf"] == expected
    # NEW: no silent overwrite.
    (h.sandbox / "inv.pdf").write_bytes(b"precious")
    text = h.error("m365_get_content", args)
    assert "already exists" in text or "overwrite" in text
    assert (h.sandbox / "inv.pdf").read_bytes() == b"precious"
    h.ok("m365_get_content", {**args, "overwrite": True})
    assert (h.sandbox / "inv.pdf").read_bytes() == expected


@scenario("email_mark_read")
def _(h: UnifiedHarness) -> None:
    legacy = run_legacy("email_mark_read", {"email_id": "msg-001", "is_read": True})
    assert not legacy.is_error, legacy.text
    h.ok(
        "m365_update",
        {"resource": "email", "id": "msg-001", "email_changes": {"is_read": True}},
    )
    assert h.fake.messages["msg-001"]["isRead"] is True
    assert compare(h, legacy, lambda g: _msg(g, "msg-001", "isRead")) == (True,)


@scenario("email_flag")
def _(h: UnifiedHarness) -> None:
    legacy = run_legacy("email_flag", {"email_id": "msg-001", "flag_status": "flagged"})
    assert not legacy.is_error, legacy.text
    h.ok(
        "m365_update",
        {
            "resource": "email",
            "id": "msg-001",
            "email_changes": {"flag": {"status": "flagged"}},
        },
    )
    assert compare(
        h, legacy, lambda g: g.messages["msg-001"]["flag"]["flagStatus"]
    ) == ("flagged")


@scenario("email_add_category")
def _(h: UnifiedHarness) -> None:
    h.fake.messages["msg-001"]["categories"] = ["Home"]
    legacy = run_legacy(
        "email_add_category",
        {"email_id": "msg-001", "categories": ["Bills"]},
        prepare=lambda g: g.messages["msg-001"].update(categories=["Home"]),
    )
    assert not legacy.is_error, legacy.text
    h.ok(
        "m365_update",
        {
            "resource": "email",
            "id": "msg-001",
            "email_changes": {"categories_add": ["Bills"]},
        },
    )
    # Both apply the category. The legacy tool REPLACED the existing list (its
    # docstring says so); categories_add keeps what was there.
    assert legacy.graph.messages["msg-001"]["categories"] == ["Bills"]
    assert sorted(h.fake.messages["msg-001"]["categories"]) == ["Bills", "Home"]
    # NEW: remove and set are also available.
    h.ok(
        "m365_update",
        {
            "resource": "email",
            "id": "msg-001",
            "email_changes": {"categories_remove": ["Home"]},
        },
    )
    assert h.fake.messages["msg-001"]["categories"] == ["Bills"]
    h.ok(
        "m365_update",
        {
            "resource": "email",
            "id": "msg-001",
            "email_changes": {"categories_set": ["Work"]},
        },
    )
    assert h.fake.messages["msg-001"]["categories"] == ["Work"]


@scenario("email_archive")
def _(h: UnifiedHarness) -> None:
    legacy = run_legacy("email_archive", {"email_id": "msg-004"})
    assert not legacy.is_error, legacy.text
    data = h.ok(
        "m365_move", {"resource": "email", "id": "msg-004", "destination_id": "archive"}
    )
    assert h.fake.messages[data["id"]]["parentFolderId"] == "archive"

    def view(g: FakeGraph) -> Any:
        return _folder_of(g, "Invoice INV-2291 from Acme Plumbing")

    assert compare(h, legacy, view) == ["archive"]


# ----------------------------------------------------------------------
# rows 62-78: OneDrive files and folders
# ----------------------------------------------------------------------
def _drive_state(g: FakeGraph) -> list[tuple[Any, ...]]:
    """Every drive item as (name, parent id, content); ids may differ."""
    return sorted(
        (v["name"], v["parentReference"]["id"], v.get("_content", b""))
        for k, v in g.drive.items()
        if k != "root"
    )


def _names(obj: Any) -> set[str]:
    """All ``name`` values in a (legacy) JSON result, at any depth."""
    found: set[str] = set()
    if isinstance(obj, dict):
        if isinstance(obj.get("name"), str):
            found.add(obj["name"])
        for value in obj.values():
            found |= _names(value)
    elif isinstance(obj, list):
        for value in obj:
            found |= _names(value)
    return found


def _legacy_json(run: Any) -> Any:
    assert not run.is_error, run.text
    return json.loads(run.text)


@scenario("file_list")
def _(h: UnifiedHarness) -> None:
    legacy = _legacy_json(
        run_legacy("file_list", {"path": "/Documents", "type_filter": "files"})
    )
    page = h.ok(
        "m365_list",
        {"resource": "drive_item", "path": "/Documents", "item_type": "file"},
    )
    names = {i["name"] for i in page["items"]}
    assert names == _names(legacy) == {"budget.xlsx", "CV.docx"}
    assert {i["item_type"] for i in page["items"]} == {"file"}


@scenario("file_get")
def _(h: UnifiedHarness) -> None:
    legacy = run_legacy("file_get", {"file_id": "item-cv", "download_path": "cv.docx"})
    assert not legacy.is_error, legacy.text
    # Details and download are split: m365_get for details ...
    item = h.ok("m365_get", {"resource": "drive_item", "id": "item-cv"})["item"]
    assert (item["name"], item["size"], item["item_type"]) == (
        "CV.docx",
        31004,
        "file",
    )
    assert json.loads(legacy.text)["name"] == item["name"]
    # ... and m365_get_content(mode='download') for the bytes.
    h.ok(
        "m365_get_content",
        {
            "resource": "drive_item",
            "id": "item-cv",
            "mode": "download",
            "save_path": "cv.docx",
        },
    )
    assert (h.sandbox / "cv.docx").read_bytes() == b"fake contents of CV.docx"
    assert legacy.sandbox_files["cv.docx"] == b"fake contents of CV.docx"


@scenario("file_create")
def _(h: UnifiedHarness) -> None:
    legacy = run_legacy(
        "file_create",
        {"onedrive_path": "/Documents/report.pdf", "local_file_path": "report.pdf"},
    )
    assert not legacy.is_error, legacy.text
    h.ok("drive_upload", {"local_path": "report.pdf", "parent_path": "/Documents"})
    state = compare(h, legacy, _drive_state)
    local = (h.sandbox / "report.pdf").read_bytes()
    assert ("report.pdf", "item-documents", local) in state

    # NEW: if_exists defaults to fail, so an existing name is refused (the
    # legacy tool silently overwrote it) and the original is untouched.
    before = h.fake.drive["item-cv"]["_content"]
    text = h.error(
        "drive_upload",
        {"local_path": "report.pdf", "parent_path": "/Documents", "name": "CV.docx"},
    )
    assert text.startswith("A file named 'CV.docx' already exists there.")
    assert h.fake.drive["item-cv"]["_content"] == before
    h.ok(
        "drive_upload",
        {
            "local_path": "report.pdf",
            "parent_path": "/Documents",
            "name": "CV.docx",
            "if_exists": "replace",
        },
    )
    assert h.fake.drive["item-cv"]["_content"] == local


@scenario("file_update")
def _(h: UnifiedHarness) -> None:
    legacy = run_legacy(
        "file_update", {"file_id": "item-notes", "local_file_path": "notes-new.txt"}
    )
    assert not legacy.is_error, legacy.text
    h.ok("drive_upload", {"local_path": "notes-new.txt", "item_id": "item-notes"})
    local = (h.sandbox / "notes-new.txt").read_bytes()
    assert h.fake.drive["item-notes"]["_content"] == local
    assert local != seeded_copy().drive["item-notes"]["_content"]
    compare(h, legacy, _drive_state)


@scenario("file_delete")
def _(h: UnifiedHarness) -> None:
    legacy = run_legacy("file_delete", {"file_id": "item-cv", "confirm": True})
    assert not legacy.is_error, legacy.text
    # Not confirmed: refused, nothing deleted.
    h.error(
        "m365_delete", {"resource": "drive_item", "id": "item-cv", "confirm": False}
    )
    assert "item-cv" in h.fake.drive
    h.ok("m365_delete", {"resource": "drive_item", "id": "item-cv", "confirm": True})
    assert "item-cv" not in h.fake.drive
    compare(h, legacy, _drive_state)
    # NEW: the tool says the item goes to the recycle bin.
    spec = json.loads(
        (
            Path(__file__).parent.parent / "docs/unified-tools/tools/m365_delete.json"
        ).read_text(encoding="utf-8")
    )
    assert "recycle bin" in spec["description"]


@scenario("file_copy")
def _(h: UnifiedHarness) -> None:
    legacy = run_legacy(
        "file_copy",
        {
            "file_id": "item-cv",
            "destination_folder_id": "item-photos",
            "new_name": "CV copy.docx",
        },
    )
    assert not legacy.is_error, legacy.text
    result = h.ok(
        "drive_copy",
        {
            "item_id": "item-cv",
            "destination_id": "item-photos",
            "new_name": "CV copy.docx",
        },
    )
    # NEW: an operation handle with a status instead of "copy initiated".
    op_id = result["operation_id"]
    assert result["status"] == "in_progress" and op_id.startswith("op_")
    status = h.ok("m365_get", {"resource": "operation", "id": op_id})["item"]
    assert status["status"] == "completed"
    copied = h.fake.drive[status["resource_id"]]
    assert copied["name"] == "CV copy.docx"
    assert copied["parentReference"]["id"] == "item-photos"
    assert h.fake.drive["item-cv"]["parentReference"]["id"] == "item-documents"
    assert compare(h, legacy, _drive_state)


@scenario("file_move")
def _(h: UnifiedHarness) -> None:
    legacy = run_legacy(
        "file_move", {"file_id": "item-cv", "destination_folder_id": "item-photos"}
    )
    assert not legacy.is_error, legacy.text
    h.ok(
        "m365_move",
        {"resource": "drive_item", "id": "item-cv", "destination_id": "item-photos"},
    )
    assert h.fake.drive["item-cv"]["parentReference"]["id"] == "item-photos"
    compare(h, legacy, _drive_state)


@scenario("file_rename")
def _(h: UnifiedHarness) -> None:
    legacy = run_legacy(
        "file_rename", {"file_id": "item-cv", "new_name": "CV-2026.docx"}
    )
    assert not legacy.is_error, legacy.text
    h.ok(
        "m365_update",
        {
            "resource": "drive_item",
            "id": "item-cv",
            "drive_item_changes": {"name": "CV-2026.docx"},
        },
    )
    assert h.fake.drive["item-cv"]["name"] == "CV-2026.docx"
    compare(h, legacy, _drive_state)


@scenario("file_share")
def _(h: UnifiedHarness) -> None:
    legacy = run_legacy(
        "file_share",
        {"file_id": "item-cv", "permission_type": "view", "scope": "anonymous"},
    )
    legacy_link = _legacy_json(legacy)["link"]["webUrl"]
    args = {"item_id": "item-cv", "mode": "link", "link_type": "view"}
    unconfirmed = {**args, "confirm": False}
    # NEW: confirm is required; nothing is created without it.
    text = h.error("drive_share", unconfirmed)
    assert text.startswith("Invalid confirm 'False': sharing requires confirm=True")
    assert not h.graph_calls("POST", "/me/drive/items/item-cv/createLink")
    # NEW: no default scope/type; link_type must be chosen.
    text = h.error(
        "drive_share", {"item_id": "item-cv", "mode": "link", "confirm": True}
    )
    assert text == "Invalid link_type: required when mode='link'"
    assert not h.graph_calls("POST", "/me/drive/items/item-cv/createLink")
    result = h.ok("drive_share", {**args, "confirm": True})
    assert result["link_url"] == legacy_link
    assert result["created"] is True
    (call,) = h.graph_calls("POST", "/me/drive/items/item-cv/createLink")
    assert call.body == {"type": "view", "scope": "anonymous"}
    # NEW: invite mode.
    invited = h.ok(
        "drive_share",
        {
            "item_id": "item-cv",
            "mode": "invite",
            "recipients": ["sam.lee@example.com"],
            "role": "read",
            "confirm": True,
        },
    )
    assert invited["mode"] == "invite"
    (invite,) = h.graph_calls("POST", "/me/drive/items/item-cv/invite")
    assert invite.body["recipients"] == [{"email": "sam.lee@example.com"}]
    assert invite.body["roles"] == ["read"]


@scenario("file_download_url")
def _(h: UnifiedHarness) -> None:
    legacy = _legacy_json(run_legacy("file_download_url", {"file_id": "item-cv"}))
    result = h.ok(
        "m365_get_content",
        {"resource": "drive_item", "id": "item-cv", "mode": "download_url"},
    )
    assert result["download_url"] == legacy["download_url"]
    assert result["download_url"].endswith("/download/item-cv")
    assert result["saved_path"] is None


@scenario("folder_list")
def _(h: UnifiedHarness) -> None:
    legacy = _legacy_json(run_legacy("folder_list", {"path": "/Documents"}))
    page = h.ok(
        "m365_list",
        {"resource": "drive_item", "path": "/Documents", "item_type": "folder"},
    )
    names = {i["name"] for i in page["items"]}
    assert names == _names(legacy) == {"Old", "Tax"}
    assert {i["item_type"] for i in page["items"]} == {"folder"}


@scenario("folder_get")
def _(h: UnifiedHarness) -> None:
    legacy = _legacy_json(run_legacy("folder_get", {"folder_id": "item-tax"}))
    item = h.ok("m365_get", {"resource": "drive_item", "id": "item-tax"})["item"]
    assert (item["name"], item["child_count"], item["item_type"]) == (
        legacy["name"],
        legacy["childCount"],
        "folder",
    )
    assert item["name"] == "Tax" and item["child_count"] == 1


@scenario("folder_get_tree")
def _(h: UnifiedHarness) -> None:
    legacy = _legacy_json(run_legacy("folder_get_tree", {"path": "/Documents"}))
    tree = h.ok(
        "m365_list",
        {
            "resource": "drive_item",
            "path": "/Documents",
            "item_type": "folder",
            "recursive": True,
        },
    )
    assert {i["name"] for i in tree["items"]} == _names(legacy) == {"Old", "Tax"}
    assert all(i["children"] == [] for i in tree["items"])


@scenario("folder_create")
def _(h: UnifiedHarness) -> None:
    legacy = run_legacy(
        "folder_create", {"name": "Receipts", "parent_folder_id": "item-documents"}
    )
    assert not legacy.is_error, legacy.text
    result = h.ok(
        "m365_create",
        {
            "resource": "drive_item",
            "drive_folder": {"name": "Receipts", "parent_id": "item-documents"},
        },
    )
    assert result["item"]["name"] == "Receipts"
    assert result["item"]["item_type"] == "folder"
    assert h.fake.drive[result["item"]["id"]]["folder"] is not None
    assert compare(h, legacy, _drive_state)


@scenario("folder_delete")
def _(h: UnifiedHarness) -> None:
    legacy = run_legacy("folder_delete", {"folder_id": "item-old", "confirm": True})
    assert not legacy.is_error, legacy.text
    h.error(
        "m365_delete", {"resource": "drive_item", "id": "item-old", "confirm": False}
    )
    assert "item-old" in h.fake.drive
    h.ok("m365_delete", {"resource": "drive_item", "id": "item-old", "confirm": True})
    assert "item-old" not in h.fake.drive
    compare(h, legacy, _drive_state)


@scenario("folder_rename")
def _(h: UnifiedHarness) -> None:
    legacy = run_legacy("folder_rename", {"folder_id": "item-old", "new_name": "Older"})
    assert not legacy.is_error, legacy.text
    h.ok(
        "m365_update",
        {
            "resource": "drive_item",
            "id": "item-old",
            "drive_item_changes": {"name": "Older"},
        },
    )
    assert h.fake.drive["item-old"]["name"] == "Older"
    compare(h, legacy, _drive_state)


@scenario("folder_move")
def _(h: UnifiedHarness) -> None:
    legacy = run_legacy(
        "folder_move", {"folder_id": "item-old", "destination_folder_id": "item-photos"}
    )
    assert not legacy.is_error, legacy.text
    h.ok(
        "m365_move",
        {"resource": "drive_item", "id": "item-old", "destination_id": "item-photos"},
    )
    assert h.fake.drive["item-old"]["parentReference"]["id"] == "item-photos"
    compare(h, legacy, _drive_state)


# ----------------------------------------------------------------------
# rows 79-84: search and server info
# ----------------------------------------------------------------------
def _hits(result: dict[str, Any], resource: str) -> list[dict[str, Any]]:
    return [i["item"] for i in result["items"] if i["resource"] == resource]


def _bury_message(g: FakeGraph) -> None:
    """An old archived message hidden behind 260 newer inbox messages."""
    template = dict(g.messages["msg-002"])
    for n in range(260):
        g.messages[f"msg-filler-{n:03d}"] = {
            **template,
            "id": f"msg-filler-{n:03d}",
            "subject": f"Filler {n}",
            "body": {"contentType": "text", "content": "nothing"},
            "bodyPreview": "nothing",
            "receivedDateTime": g.at(-1, 1),
        }
    g.messages["msg-zebra"] = {
        **template,
        "id": "msg-zebra",
        "subject": "Zebra quote",
        "body": {"contentType": "text", "content": "the zebra quote is attached"},
        "bodyPreview": "the zebra quote is attached",
        "parentFolderId": "archive",
        "receivedDateTime": g.at(-400, 1),
    }


@scenario("search_files")
def _(h: UnifiedHarness) -> None:
    legacy = _legacy_json(run_legacy("search_files", {"query": "budget"}))
    result = h.ok("m365_search", {"query": "budget", "resources": ["drive_item"]})
    names = {i["name"] for i in _hits(result, "drive_item")}
    assert names == _names(legacy) == {"budget.xlsx"}
    assert {i["resource"] for i in result["items"]} == {"drive_item"}


@scenario("search_emails")
def _(h: UnifiedHarness) -> None:
    # Same practical task on the seeded mailbox: same messages found.
    legacy = _legacy_json(run_legacy("search_emails", {"query": "telstra"}))
    result = h.ok("m365_search", {"query": "telstra", "resources": ["email"]})
    assert (
        {m["id"] for m in _hits(result, "email")}
        == {m["id"] for m in legacy}
        == {"msg-001", "msg-002"}
    )

    # NEW: the whole mailbox via server-side $search. A message older than
    # the newest 250 (and outside the inbox) is still found.
    _bury_message(h.fake)
    h.clear_calls()
    found = h.ok("m365_search", {"query": "zebra", "resources": ["email"]})
    assert [(m["id"], m["folder_id"]) for m in _hits(found, "email")] == [
        ("msg-zebra", "archive")
    ]
    (call,) = h.graph_calls("GET", "/me/messages")
    assert call.params["$search"] == '"zebra"'
    assert "$filter" not in call.params
    # The legacy tool only scanned the newest 250 messages.
    buried = run_legacy("search_emails", {"query": "zebra"}, prepare=_bury_message)
    assert not buried.is_error and "msg-zebra" not in buried.text


@scenario("search_events")
def _(h: UnifiedHarness) -> None:
    legacy = _legacy_json(run_legacy("search_events", {"query": "dentist"}))
    assert {e["id"] for e in legacy} == {"evt-dentist"}
    # NEW: an explicit window bounds the search (calendarView).
    inside = h.ok(
        "m365_search",
        {
            "query": "dentist",
            "resources": ["event"],
            "event_start": "2026-09-28T00:00:00Z",
            "event_end": "2026-10-05T00:00:00Z",
        },
    )
    assert [e["id"] for e in _hits(inside, "event")] == ["evt-dentist"]
    (view,) = h.graph_calls("GET", "/me/calendarView")
    assert view.params["startDateTime"].startswith("2026-09-28")
    assert view.params["endDateTime"].startswith("2026-10-05")
    outside = h.ok(
        "m365_search",
        {
            "query": "dentist",
            "resources": ["event"],
            "event_start": "2026-10-06T00:00:00Z",
            "event_end": "2026-10-20T00:00:00Z",
        },
    )
    assert _hits(outside, "event") == []
    text = h.error(
        "m365_search",
        {
            "query": "dentist",
            "resources": ["event"],
            "event_start": "2026-10-06T00:00:00Z",
            "event_end": "2026-10-01T00:00:00Z",
        },
    )
    assert text == "Invalid event_end: must be after event_start and within 731 days"


@scenario("search_contacts")
def _(h: UnifiedHarness) -> None:
    legacy = _legacy_json(run_legacy("search_contacts", {"query": "smith"}))
    result = h.ok("m365_search", {"query": "smith", "resources": ["contact"]})
    ids = {c["id"] for c in _hits(result, "contact")}
    assert ids == {c["id"] for c in legacy} == {"contact-jane", "contact-anna"}


@scenario("search_unified")
def _(h: UnifiedHarness) -> None:
    legacy = _legacy_json(run_legacy("search_unified", {"query": "budget"}))
    assert {"message", "drive"} & set(legacy) or legacy
    h.clear_calls()
    result = h.ok(
        "m365_search",
        {"query": "budget", "resources": ["email", "drive_item", "event", "contact"]},
    )
    kinds = {i["resource"] for i in result["items"]}
    assert {"email", "drive_item"} <= kinds
    assert {m["id"] for m in _hits(result, "email")} == {"msg-006", "msg-012"}
    assert [d["name"] for d in _hits(result, "drive_item")] == ["budget.xlsx"]
    # NEW: fan-out over the per-resource endpoints; no Search API path.
    assert not h.graph_calls(None, "/search/query")
    paths = {c.path for c in h.fake.calls}
    assert {"/me/messages", "/me/calendarView", "/me/contacts"} <= paths
    assert "/me/drive/root/search(q='budget')" in paths


@scenario("server_get_version")
def _(h: UnifiedHarness) -> None:
    legacy = run_legacy("server_get_version", {})
    assert not legacy.is_error, legacy.text
    info = h.ok("admin_server_info", {})
    assert info["version"] == json.loads(legacy.text)["version"]
    assert info["tool_count"] == 29 and "admin" in info["toolsets_enabled"]


# ----------------------------------------------------------------------
# the parametrized entry point
# ----------------------------------------------------------------------
def test_every_row_has_a_scenario() -> None:
    assert len(ROWS) == 42
    assert {r["legacy_tool"] for r in ROWS} == set(SCENARIOS)
    assert ROWS[0]["legacy_tool"] == "emailrules_move_top"
    assert ROWS[-1]["legacy_tool"] == "server_get_version"


@pytest.mark.parametrize("row", ROWS, ids=[r["legacy_tool"] for r in ROWS])
def test_parity(harness: UnifiedHarness, row: dict[str, Any]) -> None:
    SCENARIOS[row["legacy_tool"]](harness)
