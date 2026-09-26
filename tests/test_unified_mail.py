"""Tests for the mail resources of the generic m365_* tools.

Covers ``email``, ``email_folder`` and ``email_rule`` in m365_list,
m365_get, m365_get_content, m365_create, m365_update, m365_move and
m365_delete (tasks U3.1-U3.8, mail parts) against the fake Graph.
"""

from __future__ import annotations

import base64
import copy
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from m365_mcp.rate_limit import RateLimiter
from m365_mcp.tool_specs import load_tool_spec
from m365_mcp.tools.unified import common

EXAMPLE_ID = "AQMkADAwATM3ZmYAZS1k"


@pytest.fixture(autouse=True)
def _fresh_rate_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give each test its own budget so deletes never hit the shared limit."""
    monkeypatch.setattr(common, "rate_limiter", RateLimiter())


def _example(tool: str, title: str) -> dict[str, Any]:
    for example in load_tool_spec(tool)["examples"]:
        if example["title"] == title:
            return copy.deepcopy(example)
    raise KeyError(title)


def _seed_message(
    harness,
    msg_id: str,
    *,
    folder: str = "inbox",
    sender: dict[str, str] | None = None,
    **fields: Any,
) -> dict[str, Any]:
    sender = sender or {"name": "Sender", "address": "sender@example.com"}
    message = {
        "id": msg_id,
        "conversationId": f"conv-{msg_id}",
        "subject": f"Subject {msg_id}",
        "body": {"contentType": "text", "content": f"Body of {msg_id}"},
        "bodyPreview": f"Body of {msg_id}",
        "from": {"emailAddress": sender},
        "toRecipients": [
            {"emailAddress": {"name": "Robin", "address": "robin@example.com"}}
        ],
        "ccRecipients": [],
        "bccRecipients": [],
        "receivedDateTime": "2026-09-10T00:00:00Z",
        "isRead": True,
        "hasAttachments": False,
        "importance": "normal",
        "flag": {"flagStatus": "notFlagged"},
        "categories": [],
        "parentFolderId": folder,
        "inferenceClassification": "focused",
        "webLink": f"https://outlook.live.com/mail/item/{msg_id}",
    }
    message.update(fields)
    harness.fake.messages[msg_id] = message
    return message


def _same_instant(a: str, b: str) -> bool:
    return datetime.fromisoformat(a) == datetime.fromisoformat(b)


# ----------------------------------------------------------------------
# m365_list: email
# ----------------------------------------------------------------------


def test_list_email_example_unread_from_one_sender(harness) -> None:
    example = _example("m365_list", "Unread emails from one sender this month")
    expected = example["output"]["items"][0]
    billing = {"name": "Example Billing", "address": "billing@example.com"}
    _seed_message(
        harness,
        expected["id"],
        conversationId=expected["conversation_id"],
        subject=expected["subject"],
        bodyPreview=expected["preview"],
        sender=billing,
        receivedDateTime="2026-09-19T22:45:00Z",
        isRead=False,
        hasAttachments=True,
    )
    _seed_message(
        harness,
        "older-invoice",
        sender=billing,
        receivedDateTime="2026-09-05T00:00:00Z",
        isRead=False,
    )

    data = harness.ok("m365_list", example["input"])

    assert data["resource"] == "email"
    assert data["has_more"] is True
    assert isinstance(data["next_cursor"], str)
    assert data["summary"] == example["output"]["summary"]
    [item] = data["items"]
    assert _same_instant(item.pop("received_at"), expected.pop("received_at"))
    expected["folder_id"] = "inbox"
    assert item == expected

    [call] = harness.graph_calls("GET", "/me/mailFolders/inbox/messages")
    assert call.params["$filter"] == (
        "receivedDateTime ge 2026-08-31T14:30:00Z and isRead eq false "
        "and from/emailAddress/address eq 'billing@example.com'"
    )
    assert call.params["$orderby"] == "receivedDateTime desc"
    assert call.params["$top"] == "1"
    assert "bodyPreview" in call.params["$select"]
    assert "body," not in call.params["$select"] + ","


def test_list_email_filter_puts_orderby_property_first(harness) -> None:
    harness.ok(
        "m365_list",
        {
            "resource": "email",
            "container_id": "archive",
            "email_filter": {
                "category": "Kid's school",
                "flagged": True,
                "importance": "high",
                "has_attachments": False,
                "received_before": "2026-09-30T00:00:00Z",
            },
        },
    )
    [call] = harness.graph_calls("GET", "/me/mailFolders/archive/messages")
    assert call.params["$filter"] == (
        "receivedDateTime lt 2026-09-30T00:00:00Z and hasAttachments eq false "
        "and importance eq 'high' and flag/flagStatus eq 'flagged' "
        "and categories/any(c:c eq 'Kid''s school')"
    )


def test_list_email_filter_without_dates_adds_a_received_clause(harness) -> None:
    harness.ok(
        "m365_list",
        {"resource": "email", "email_filter": {"unread": False, "flagged": False}},
    )
    [call] = harness.graph_calls("GET", "/me/mailFolders/inbox/messages")
    assert call.params["$filter"] == (
        "receivedDateTime ge 1900-01-01T00:00:00Z and isRead eq true "
        "and flag/flagStatus ne 'flagged'"
    )


def test_list_email_without_filter_is_newest_first(harness) -> None:
    data = harness.ok("m365_list", {"resource": "email", "limit": 5})
    [call] = harness.graph_calls("GET", "/me/mailFolders/inbox/messages")
    assert "$filter" not in call.params
    received = [item["received_at"] for item in data["items"]]
    assert received == sorted(received, reverse=True)
    assert all(item["folder_id"] == "inbox" for item in data["items"])
    assert all(len(item["preview"] or "") <= 255 for item in data["items"])


def test_list_email_cursor_follows_the_graph_next_link(harness) -> None:
    args = {"resource": "email", "limit": 2}
    first = harness.ok("m365_list", args)
    assert first["has_more"] is True
    second = harness.ok("m365_list", {**args, "cursor": first["next_cursor"]})
    first_ids = {item["id"] for item in first["items"]}
    second_ids = {item["id"] for item in second["items"]}
    assert len(second_ids) == 2
    assert not first_ids & second_ids
    assert (
        harness.graph_calls("GET", "/me/mailFolders/inbox/messages")[-1].params["$skip"]
        == "2"
    )


def test_list_email_cursor_from_another_request_is_rejected(harness) -> None:
    first = harness.ok("m365_list", {"resource": "email", "limit": 2})
    text = harness.error(
        "m365_list",
        {"resource": "email", "limit": 3, "cursor": first["next_cursor"]},
    )
    assert text == (
        "Invalid cursor: it does not match this request. "
        "Expected: repeat the call without cursor"
    )


def test_list_email_received_before_must_follow_received_after(harness) -> None:
    text = harness.error(
        "m365_list",
        {
            "resource": "email",
            "email_filter": {
                "received_after": "2026-09-10T00:00:00+09:30",
                "received_before": "2026-09-09T14:30:00Z",
            },
        },
    )
    assert text == "Invalid received_before: must be after received_after"


def test_list_email_unknown_alias_is_rejected(harness) -> None:
    text = harness.error("m365_list", {"resource": "email", "container_id": "Inbx"})
    assert text == (
        "Invalid container_id 'Inbx': unknown folder alias. Expected: a folder "
        "ID or one of inbox, sent, drafts, deleted, junk, archive"
    )


def test_list_email_filter_on_other_resource_is_rejected(harness) -> None:
    text = harness.error(
        "m365_list", {"resource": "email_folder", "email_filter": {"unread": True}}
    )
    assert text == (
        "Invalid email_filter: only valid with resource='email'. "
        "Expected: remove email_filter or use resource='email'"
    )


# ----------------------------------------------------------------------
# m365_list: email_folder and email_rule
# ----------------------------------------------------------------------


def test_list_email_folders_top_level(harness) -> None:
    data = harness.ok("m365_list", {"resource": "email_folder", "limit": 50})
    names = [item["display_name"] for item in data["items"]]
    assert "Inbox" in names and "Receipts" in names
    assert "Conversation History" not in names
    assert "Family" not in names
    assert all(item["children"] is None for item in data["items"])
    [call] = harness.graph_calls("GET", "/me/mailFolders")
    assert "includeHiddenFolders" not in call.params


def test_list_email_folders_include_hidden(harness) -> None:
    data = harness.ok(
        "m365_list", {"resource": "email_folder", "include_hidden": True, "limit": 50}
    )
    names = [item["display_name"] for item in data["items"]]
    assert "Conversation History" in names
    [call] = harness.graph_calls("GET", "/me/mailFolders")
    assert call.params["includeHiddenFolders"] == "true"


def test_list_email_folders_children_of_a_parent_alias(harness) -> None:
    data = harness.ok(
        "m365_list", {"resource": "email_folder", "container_id": "inbox"}
    )
    assert [item["id"] for item in data["items"]] == ["folder-family"]
    assert harness.graph_calls("GET", "/me/mailFolders/inbox/childFolders")


def test_list_email_folders_page_cursor(harness) -> None:
    first = harness.ok("m365_list", {"resource": "email_folder", "limit": 4})
    assert first["has_more"] is True
    second = harness.ok(
        "m365_list",
        {"resource": "email_folder", "limit": 4, "cursor": first["next_cursor"]},
    )
    assert not {i["id"] for i in first["items"]} & {i["id"] for i in second["items"]}


def test_list_email_folder_tree_to_max_depth(harness) -> None:
    data = harness.ok(
        "m365_list",
        {
            "resource": "email_folder",
            "recursive": True,
            "max_depth": 3,
            "limit": 50,
        },
    )
    inbox = next(item for item in data["items"] if item["id"] == "inbox")
    [family] = inbox["children"]
    assert family["id"] == "folder-family"
    [school] = family["children"]
    assert school["id"] == "folder-school"
    assert school["children"] == []
    receipts = next(i for i in data["items"] if i["id"] == "folder-receipts")
    assert receipts["children"] == []
    assert harness.graph_calls("GET", "/me/mailFolders/inbox/childFolders")
    # Folders without subfolders are not queried.
    assert not harness.graph_calls(
        "GET", "/me/mailFolders/folder-receipts/childFolders"
    )


def test_list_email_folder_tree_stops_at_max_depth(harness) -> None:
    data = harness.ok(
        "m365_list",
        {"resource": "email_folder", "recursive": True, "max_depth": 2, "limit": 50},
    )
    inbox = next(item for item in data["items"] if item["id"] == "inbox")
    [family] = inbox["children"]
    assert family["child_count"] == 1
    assert family["children"] is None
    assert not harness.graph_calls("GET", "/me/mailFolders/folder-family/childFolders")


def test_list_email_folder_tree_pages_by_offset(harness) -> None:
    args = {"resource": "email_folder", "recursive": True, "limit": 5}
    first = harness.ok("m365_list", args)
    assert len(first["items"]) == 5 and first["has_more"] is True
    second = harness.ok("m365_list", {**args, "cursor": first["next_cursor"]})
    assert second["has_more"] is False
    assert not {i["id"] for i in first["items"]} & {i["id"] for i in second["items"]}


def test_list_email_rules(harness) -> None:
    data = harness.ok("m365_list", {"resource": "email_rule"})
    assert [item["id"] for item in data["items"]] == ["rule-news", "rule-boss"]
    news = data["items"][0]
    assert news["conditions"] == {"sender_contains": ["dailybrief"]}
    assert news["actions"] == {
        "move_to_folder": "folder-reading",
        "stop_processing_rules": True,
    }
    assert data["items"][1]["conditions"] == {
        "from_addresses": ["priya.patel@example.com"]
    }
    assert data["has_more"] is False and data["next_cursor"] is None
    assert harness.graph_calls("GET", "/me/mailFolders/inbox/messageRules")


def test_list_email_rules_page_by_offset(harness) -> None:
    first = harness.ok("m365_list", {"resource": "email_rule", "limit": 1})
    assert [i["id"] for i in first["items"]] == ["rule-news"]
    second = harness.ok(
        "m365_list",
        {"resource": "email_rule", "limit": 1, "cursor": first["next_cursor"]},
    )
    assert [i["id"] for i in second["items"]] == ["rule-boss"]
    assert second["has_more"] is False


# ----------------------------------------------------------------------
# m365_get
# ----------------------------------------------------------------------


def test_get_email_with_body_and_attachment_metadata(harness) -> None:
    data = harness.ok("m365_get", {"resource": "email", "id": "msg-004"})
    item = data["item"]
    assert item["id"] == "msg-004"
    assert item["body"].startswith("Please find attached invoice INV-2291")
    assert item["body_truncated"] is False
    assert item["web_link"] == "https://outlook.live.com/mail/item/msg-004"
    assert item["bcc"] == []
    [call] = harness.graph_calls("GET", "/me/messages/msg-004")
    assert call.params["$expand"] == (
        "attachments($select=id,name,size,contentType,isInline)"
    )
    attachments = harness.fake.attachments.get("msg-004", [])
    assert [a["id"] for a in item["attachments"]] == [a["id"] for a in attachments]
    for meta in item["attachments"]:
        assert set(meta) == {"id", "name", "size", "content_type", "is_inline"}


def test_get_email_truncates_the_body(harness) -> None:
    _seed_message(
        harness,
        "long-mail",
        body={"contentType": "text", "content": "x" * 2000},
    )
    data = harness.ok(
        "m365_get", {"resource": "email", "id": "long-mail", "body_max_chars": 500}
    )
    assert data["item"]["body_truncated"] is True
    assert len(data["item"]["body"]) <= 520


def test_get_email_without_body(harness) -> None:
    data = harness.ok(
        "m365_get", {"resource": "email", "id": "msg-001", "include_body": False}
    )
    assert data["item"]["body"] is None
    assert data["item"]["body_truncated"] is False


def test_get_email_folder_by_alias(harness) -> None:
    data = harness.ok("m365_get", {"resource": "email_folder", "id": "junk"})
    assert data["item"]["id"] == "junkemail"
    assert data["item"]["display_name"] == "Junk Email"
    assert data["item"]["children"] is None
    assert harness.graph_calls("GET", "/me/mailFolders/junkemail")


def test_get_email_rule(harness) -> None:
    data = harness.ok("m365_get", {"resource": "email_rule", "id": "rule-boss"})
    assert data["item"]["display_name"] == "Flag boss"
    assert data["item"]["actions"] == {"mark_importance": "high"}
    assert data["item"]["exceptions"] is None
    assert harness.graph_calls("GET", "/me/mailFolders/inbox/messageRules/rule-boss")


def test_get_requires_id(harness) -> None:
    text = harness.error("m365_get", {"resource": "email"})
    assert text == "Invalid id: required unless resource='drive_item' with path"


def test_get_missing_email_is_actionable(harness) -> None:
    text = harness.error("m365_get", {"resource": "email", "id": "nope"})
    assert "No email with that id" in text


# ----------------------------------------------------------------------
# m365_get_content: email attachment
# ----------------------------------------------------------------------


def _seed_attachment(
    harness, msg_id: str, att_id: str, name: str, content: bytes, **extra: Any
) -> None:
    attachment = {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "id": att_id,
        "name": name,
        "contentType": "application/pdf",
        "size": len(content),
        "isInline": False,
        "contentBytes": base64.b64encode(content).decode(),
    }
    attachment.update(extra)
    harness.fake.attachments.setdefault(msg_id, []).append(attachment)


def test_get_content_saves_an_attachment(harness) -> None:
    _seed_attachment(harness, "msg-001", "att-x", "invoice.pdf", b"%PDF invoice")
    target = harness.sandbox / "invoice.pdf"
    data = harness.ok(
        "m365_get_content",
        {
            "resource": "email",
            "id": "msg-001",
            "mode": "download",
            "attachment_id": "att-x",
            "save_path": str(target),
        },
    )
    assert target.read_bytes() == b"%PDF invoice"
    assert data["saved_path"] == str(target.resolve())
    assert data["size"] == len(b"%PDF invoice")
    assert data["mime_type"] == "application/pdf"
    assert data["download_url"] is None and data["vcard"] is None
    assert harness.graph_calls("GET", "/me/messages/msg-001/attachments/att-x")


def test_get_content_refuses_existing_file(harness) -> None:
    _seed_attachment(harness, "msg-001", "att-x", "invoice.pdf", b"new")
    target = harness.sandbox / "invoice.pdf"
    target.write_bytes(b"old")
    args = {
        "resource": "email",
        "id": "msg-001",
        "mode": "download",
        "attachment_id": "att-x",
        "save_path": str(target),
    }
    text = harness.error("m365_get_content", args)
    assert text == (
        "Invalid save_path: file exists. Expected: overwrite=true or another path"
    )
    assert target.read_bytes() == b"old"
    harness.ok("m365_get_content", {**args, "overwrite": True})
    assert target.read_bytes() == b"new"


def test_get_content_refuses_paths_outside_allowed_roots(harness) -> None:
    outside = Path(Path(tempfile.gettempdir()).anchor) / "m365-not-allowed" / "x.pdf"
    text = harness.error(
        "m365_get_content",
        {
            "resource": "email",
            "id": "msg-001",
            "mode": "download",
            "attachment_id": "att-x",
            "save_path": str(outside),
        },
    )
    assert text == (
        "Invalid save_path: outside allowed folders. Expected: a path under the "
        "working directory, temp directory or MCP_FILE_ALLOWED_ROOTS"
    )
    assert not harness.graph_calls("GET")


def test_get_content_refuses_deny_listed_names(harness) -> None:
    text = harness.error(
        "m365_get_content",
        {
            "resource": "email",
            "id": "msg-001",
            "mode": "download",
            "attachment_id": "att-x",
            "save_path": str(harness.sandbox / "server.pem"),
        },
    )
    assert text == "Invalid save_path: 'server.pem' is a protected file"


def test_get_content_into_a_folder_uses_the_sanitised_name(harness) -> None:
    _seed_attachment(harness, "msg-001", "att-x", 'bad:na"me?.pdf', b"data")
    folder = harness.sandbox / "downloads"
    folder.mkdir()
    data = harness.ok(
        "m365_get_content",
        {
            "resource": "email",
            "id": "msg-001",
            "mode": "download",
            "attachment_id": "att-x",
            "save_path": str(folder),
        },
    )
    assert data["saved_path"] == str((folder / "bad_na_me_.pdf").resolve())
    assert (folder / "bad_na_me_.pdf").read_bytes() == b"data"


def test_get_content_requires_attachment_id(harness) -> None:
    text = harness.error(
        "m365_get_content",
        {"resource": "email", "id": "msg-001", "mode": "download", "save_path": "a"},
    )
    assert text == "Invalid attachment_id: required for resource='email'"


def test_get_content_refuses_attachments_over_25_mb(harness) -> None:
    _seed_attachment(
        harness, "msg-001", "att-big", "big.bin", b"x", size=26 * 1024 * 1024
    )
    text = harness.error(
        "m365_get_content",
        {
            "resource": "email",
            "id": "msg-001",
            "mode": "download",
            "attachment_id": "att-big",
            "save_path": str(harness.sandbox / "big.bin"),
        },
    )
    assert text == (
        "Invalid attachment_id: attachment is larger than 25 MB. "
        "Expected: an attachment of at most 25 MB"
    )
    assert not (harness.sandbox / "big.bin").exists()


def test_get_content_refuses_non_file_attachments(harness) -> None:
    harness.fake.attachments.setdefault("msg-001", []).append(
        {
            "@odata.type": "#microsoft.graph.itemAttachment",
            "id": "att-item",
            "name": "Forwarded message",
            "size": 100,
        }
    )
    text = harness.error(
        "m365_get_content",
        {
            "resource": "email",
            "id": "msg-001",
            "mode": "download",
            "attachment_id": "att-item",
            "save_path": str(harness.sandbox / "item.eml"),
        },
    )
    assert text == (
        "Invalid attachment_id: not a file attachment. Expected: a file attachment"
    )


# ----------------------------------------------------------------------
# m365_create: email_folder
# ----------------------------------------------------------------------


def test_create_top_level_email_folder(harness) -> None:
    data = harness.ok(
        "m365_create",
        {"resource": "email_folder", "email_folder": {"display_name": "Bills"}},
    )
    item = data["item"]
    assert item["display_name"] == "Bills"
    assert item["children"] is None
    [call] = harness.graph_calls("POST", "/me/mailFolders")
    assert call.body == {"displayName": "Bills"}
    assert data["summary"] == "Created mail folder 'Bills'."


def test_create_email_folder_under_a_parent_alias(harness) -> None:
    data = harness.ok(
        "m365_create",
        {
            "resource": "email_folder",
            "email_folder": {"display_name": "Kids", "parent_id": "inbox"},
        },
    )
    assert data["item"]["parent_id"] == "inbox"
    assert harness.graph_calls("POST", "/me/mailFolders/inbox/childFolders")


def test_create_email_folder_with_wrong_object(harness) -> None:
    text = harness.error(
        "m365_create", {"resource": "email_folder", "calendar": {"name": "x"}}
    )
    assert text == (
        "Invalid calendar: resource is 'email_folder'. "
        "Expected: supply only the 'email_folder' object"
    )


# ----------------------------------------------------------------------
# m365_update: email and email_folder
# ----------------------------------------------------------------------


def test_update_email_example_mark_read_and_add_category(harness) -> None:
    example = _example("m365_update", "Mark read and add a category")
    _seed_message(harness, EXAMPLE_ID, isRead=False, categories=["Home"])
    data = harness.ok("m365_update", example["input"])
    assert data == example["output"]
    assert harness.graph_calls("GET", f"/me/messages/{EXAMPLE_ID}")
    [patch] = harness.graph_calls("PATCH", f"/me/messages/{EXAMPLE_ID}")
    assert patch.body == {"isRead": True, "categories": ["Home", "Bills"]}


def test_update_email_all_fields(harness) -> None:
    _seed_message(harness, "m1", categories=["A", "B"])
    data = harness.ok(
        "m365_update",
        {
            "resource": "email",
            "id": "m1",
            "email_changes": {
                "flag": {
                    "status": "flagged",
                    "start_at": "2026-10-01T09:00:00+09:30",
                    "due_at": "2026-10-02T09:00:00+09:30",
                },
                "importance": "high",
                "categories_remove": ["A", "Z"],
                "inference_classification": "other",
            },
        },
    )
    assert data["changed_fields"] == [
        "flag",
        "importance",
        "categories",
        "inference_classification",
    ]
    [patch] = harness.graph_calls("PATCH", "/me/messages/m1")
    assert patch.body == {
        "flag": {
            "flagStatus": "flagged",
            "startDateTime": {"dateTime": "2026-09-30T23:30:00", "timeZone": "UTC"},
            "dueDateTime": {"dateTime": "2026-10-01T23:30:00", "timeZone": "UTC"},
        },
        "importance": "high",
        "categories": ["B"],
        "inferenceClassification": "other",
    }


def test_update_email_categories_set_does_not_read_first(harness) -> None:
    _seed_message(harness, "m1", categories=["A"])
    harness.ok(
        "m365_update",
        {
            "resource": "email",
            "id": "m1",
            "email_changes": {"categories_set": [], "flag": {"status": "complete"}},
        },
    )
    assert not harness.graph_calls("GET", "/me/messages/m1")
    [patch] = harness.graph_calls("PATCH", "/me/messages/m1")
    assert patch.body == {"flag": {"flagStatus": "complete"}, "categories": []}


def test_update_email_categories_set_is_exclusive(harness) -> None:
    text = harness.error(
        "m365_update",
        {
            "resource": "email",
            "id": "m1",
            "email_changes": {"categories_set": ["A"], "categories_add": ["B"]},
        },
    )
    assert text == (
        "Invalid categories_set: cannot be combined with categories_add or "
        "categories_remove"
    )


def test_update_email_with_wrong_changes_object(harness) -> None:
    text = harness.error(
        "m365_update",
        {"resource": "contact", "id": "c1", "email_changes": {"is_read": True}},
    )
    assert text == (
        "Invalid email_changes: resource is 'contact'. Expected: contact_changes"
    )


def test_update_email_folder_rename(harness) -> None:
    data = harness.ok(
        "m365_update",
        {
            "resource": "email_folder",
            "id": "folder-receipts",
            "email_folder_changes": {"display_name": "Receipts 2026"},
        },
    )
    assert data["changed_fields"] == ["display_name"]
    assert data["status"] == "updated"
    [patch] = harness.graph_calls("PATCH", "/me/mailFolders/folder-receipts")
    assert patch.body == {"displayName": "Receipts 2026"}
    assert harness.fake.folders["folder-receipts"]["displayName"] == "Receipts 2026"


@pytest.mark.parametrize("folder", ["inbox", "Inbox", "sentitems", "archive"])
def test_update_well_known_folder_is_refused(harness, folder: str) -> None:
    text = harness.error(
        "m365_update",
        {
            "resource": "email_folder",
            "id": folder,
            "email_folder_changes": {"display_name": "X"},
        },
    )
    assert text == f"Invalid id: {folder} cannot be renamed"
    assert not harness.graph_calls("PATCH")


# ----------------------------------------------------------------------
# m365_move: email and email_folder
# ----------------------------------------------------------------------


def test_move_email_example_archive(harness) -> None:
    example = _example("m365_move", "Archive an email")
    _seed_message(harness, EXAMPLE_ID)
    data = harness.ok("m365_move", example["input"])
    new_id = data["id"]
    assert new_id != EXAMPLE_ID and new_id in harness.fake.messages
    assert data["previous_id"] == EXAMPLE_ID
    assert data["status"] == "moved"
    assert data["destination_id"] == "archive"
    assert data["summary"] == f"Moved email to Archive (new id {new_id})."
    [call] = harness.graph_calls("POST", f"/me/messages/{EXAMPLE_ID}/move")
    assert call.body == {"destinationId": "archive"}


def test_move_email_to_a_folder_id(harness) -> None:
    data = harness.ok(
        "m365_move",
        {"resource": "email", "id": "msg-001", "destination_id": "folder-receipts"},
    )
    assert data["destination_id"] == "folder-receipts"
    assert harness.fake.messages[data["id"]]["parentFolderId"] == "folder-receipts"


def test_move_email_unknown_alias(harness) -> None:
    text = harness.error(
        "m365_move", {"resource": "email", "id": "msg-001", "destination_id": "Arch"}
    )
    assert text.startswith("Invalid destination_id 'Arch': unknown folder alias")


def test_move_requires_destination(harness) -> None:
    text = harness.error("m365_move", {"resource": "email", "id": "msg-001"})
    assert text == "Invalid destination_id: required"


def _fail_route(
    harness, monkeypatch: pytest.MonkeyPatch, method: str, path: str, outcome: Any
) -> None:
    """Make the fake answer one route with an error status or exception."""
    original = harness.fake.dispatch

    def dispatch(
        req_method: str, req_path: str, params: dict[str, str], body: Any
    ) -> tuple[int, Any]:
        if req_method.upper() == method and req_path == path:
            if isinstance(outcome, Exception):
                raise outcome
            return outcome, {
                "error": {"code": "InternalServerError", "message": "boom"}
            }
        return original(req_method, req_path, params, body)

    monkeypatch.setattr(harness.fake, "dispatch", dispatch)


@pytest.mark.parametrize(
    "outcome", [500, 504, httpx.ReadTimeout("timed out")], ids=["500", "504", "timeout"]
)
def test_move_email_ambiguous_failure_reports_outcome_unknown(
    harness, monkeypatch: pytest.MonkeyPatch, outcome: Any
) -> None:
    _fail_route(harness, monkeypatch, "POST", "/me/messages/msg-001/move", outcome)
    text = harness.error(
        "m365_move", {"resource": "email", "id": "msg-001", "destination_id": "junk"}
    )
    assert text == "Outcome unknown: check the destination folder before retrying"


def test_move_email_folder(harness) -> None:
    data = harness.ok(
        "m365_move",
        {
            "resource": "email_folder",
            "id": "folder-receipts",
            "destination_id": "inbox",
        },
    )
    assert data["id"] == "folder-receipts"
    assert data["previous_id"] == "folder-receipts"
    assert data["destination_id"] == "inbox"
    [call] = harness.graph_calls("POST", "/me/mailFolders/folder-receipts/move")
    assert call.body == {"destinationId": "inbox"}
    assert harness.fake.folders["folder-receipts"]["parentFolderId"] == "inbox"


def test_move_email_folder_to_root(harness) -> None:
    data = harness.ok(
        "m365_move",
        {"resource": "email_folder", "id": "folder-school", "destination_id": "root"},
    )
    assert data["destination_id"] == "msgfolderroot"
    [call] = harness.graph_calls("POST", "/me/mailFolders/folder-school/move")
    assert call.body == {"destinationId": "msgfolderroot"}


@pytest.mark.parametrize("destination", ["folder-family", "folder-school"])
def test_move_email_folder_into_itself_or_descendant_is_refused(
    harness, destination: str
) -> None:
    text = harness.error(
        "m365_move",
        {
            "resource": "email_folder",
            "id": "folder-family",
            "destination_id": destination,
        },
    )
    assert text == "Invalid destination_id: is inside the folder being moved"
    assert not harness.graph_calls("POST")


def test_move_email_folder_ambiguous_failure(
    harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fail_route(
        harness, monkeypatch, "POST", "/me/mailFolders/folder-receipts/move", 502
    )
    text = harness.error(
        "m365_move",
        {
            "resource": "email_folder",
            "id": "folder-receipts",
            "destination_id": "inbox",
        },
    )
    assert text == "Outcome unknown: check the destination folder before retrying"


# ----------------------------------------------------------------------
# m365_delete: email, email_folder, email_rule
# ----------------------------------------------------------------------


def test_delete_requires_confirm(harness) -> None:
    text = harness.error(
        "m365_delete", {"resource": "email", "id": "msg-001", "confirm": False}
    )
    assert text == (
        "Invalid confirm 'False': delete requires confirm=True to proceed. "
        "Expected: Explicit user confirmation"
    )
    assert "msg-001" in harness.fake.messages


def test_delete_email(harness) -> None:
    data = harness.ok(
        "m365_delete", {"resource": "email", "id": "msg-001", "confirm": True}
    )
    assert data == {
        "resource": "email",
        "id": "msg-001",
        "status": "deleted",
        "recoverable": False,
        "summary": data["summary"],
    }
    assert "msg-001" not in harness.fake.messages
    assert harness.graph_calls("DELETE", "/me/messages/msg-001")


def test_delete_email_folder(harness) -> None:
    data = harness.ok(
        "m365_delete",
        {"resource": "email_folder", "id": "folder-receipts", "confirm": True},
    )
    assert data["status"] == "deleted" and data["recoverable"] is False
    assert "folder-receipts" not in harness.fake.folders
    assert harness.graph_calls("DELETE", "/me/mailFolders/folder-receipts")


@pytest.mark.parametrize(
    "folder", ["inbox", "Deleted", "junkemail", "root", "msgfolderroot", "outbox"]
)
def test_delete_well_known_folder_or_alias_is_refused(harness, folder: str) -> None:
    text = harness.error(
        "m365_delete", {"resource": "email_folder", "id": folder, "confirm": True}
    )
    assert text == f"Invalid id: {folder} cannot be deleted"
    assert not harness.graph_calls("DELETE")


def test_delete_email_rule(harness) -> None:
    data = harness.ok(
        "m365_delete", {"resource": "email_rule", "id": "rule-news", "confirm": True}
    )
    assert data["status"] == "deleted" and data["recoverable"] is False
    assert "rule-news" not in harness.fake.rules
    assert harness.graph_calls("DELETE", "/me/mailFolders/inbox/messageRules/rule-news")


def test_delete_cancellation_message_only_for_events(harness) -> None:
    text = harness.error(
        "m365_delete",
        {
            "resource": "email",
            "id": "msg-001",
            "confirm": True,
            "cancellation_message": "sorry",
        },
    )
    assert text == "Invalid cancellation_message: only valid for resource='event'"


@pytest.mark.parametrize(
    ("resource", "path"),
    [
        ("email", "/me/messages/msg-001"),
        ("email_folder", "/me/mailFolders/folder-receipts"),
        ("email_rule", "/me/mailFolders/inbox/messageRules/rule-news"),
    ],
)
def test_delete_ambiguous_failure_reports_outcome_unknown(
    harness, monkeypatch: pytest.MonkeyPatch, resource: str, path: str
) -> None:
    _fail_route(harness, monkeypatch, "DELETE", path, httpx.ReadTimeout("slow"))
    item_id = path.rsplit("/", 1)[-1]
    text = harness.error(
        "m365_delete", {"resource": resource, "id": item_id, "confirm": True}
    )
    assert text == (
        "Outcome unknown: check whether the item still exists before retrying"
    )


def test_delete_missing_email_is_not_ambiguous(harness) -> None:
    text = harness.error(
        "m365_delete", {"resource": "email", "id": "nope", "confirm": True}
    )
    assert "No email with that id" in text


def test_results_never_leak_odata_fields(harness) -> None:
    data = harness.ok("m365_get", {"resource": "email", "id": "msg-004"})
    assert "@odata" not in json.dumps(data)
