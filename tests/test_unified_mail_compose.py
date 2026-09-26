"""Tests for the unified compose tools (U3.9-U3.12).

email_create_draft, email_send, email_reply and email_forward run through
the real unified server against the fake Graph (``harness`` fixture).
"""

from __future__ import annotations

import base64
from typing import Any

import httpx
import pytest

from tests.unified_harness import UnifiedHarness

MB = 1024 * 1024
OUTCOME_UNKNOWN = "Outcome unknown: check Sent Items before retrying"


def _confirm_error(action: str) -> str:
    return (
        f"Invalid confirm 'False': {action} requires confirm=True to proceed. "
        "Expected: Explicit user confirmation"
    )


def _file(harness: UnifiedHarness, name: str, size: int) -> str:
    path = harness.sandbox / name
    path.write_bytes(b"x" * size)
    return name


def _sparse(harness: UnifiedHarness, name: str, size: int) -> str:
    path = harness.sandbox / name
    with path.open("wb") as handle:
        handle.truncate(size)
    return name


def _seed_message(
    harness: UnifiedHarness,
    msg_id: str,
    subject: str,
    *,
    conversation_id: str | None = None,
    cc: list[str] | None = None,
) -> None:
    harness.fake.messages[msg_id] = {
        "id": msg_id,
        "conversationId": conversation_id or f"conv-{msg_id}",
        "subject": subject,
        "body": {"contentType": "text", "content": "Hello"},
        "bodyPreview": "Hello",
        "from": {"emailAddress": {"name": "Sam", "address": "sam@example.com"}},
        "toRecipients": [{"emailAddress": {"address": harness.account_email}}],
        "ccRecipients": [{"emailAddress": {"address": a}} for a in cc or []],
        "bccRecipients": [],
        "receivedDateTime": "2026-09-25T10:00:00Z",
        "isRead": True,
        "isDraft": False,
        "hasAttachments": False,
        "importance": "normal",
        "flag": {"flagStatus": "notFlagged"},
        "categories": [],
        "parentFolderId": "inbox",
        "webLink": f"https://outlook.live.com/owa/?ItemID={msg_id}",
    }


def _fail(harness: UnifiedHarness, route: str, error: Exception | int) -> None:
    """Make one fake Graph handler fail with a status or an exception."""

    def handler(*args: Any) -> tuple[int, Any]:
        if isinstance(error, Exception):
            raise error
        return error, {"error": {"code": "InternalServerError", "message": "x"}}

    setattr(harness.fake, route, handler)


def _addresses(recipients: list[dict[str, Any]]) -> list[str]:
    return [r["emailAddress"]["address"] for r in recipients]


# ----------------------------------------------------------------------
# email_create_draft (U3.9)
# ----------------------------------------------------------------------


def test_create_draft_example(harness: UnifiedHarness) -> None:
    data = harness.ok(
        "email_create_draft",
        {
            "to": ["jane@example.com"],
            "subject": "Weekend",
            "body": "Are you free Saturday?",
        },
    )
    draft = harness.fake.messages[data["draft_id"]]
    assert draft["isDraft"] is True
    assert data["subject"] == "Weekend"
    assert data["to"] == ["jane@example.com"]
    assert data["cc"] == [] and data["bcc"] == []
    assert data["attachment_count"] == 0
    assert data["web_link"] == draft["webLink"]
    assert data["summary"] == (
        "Draft 'Weekend' created for jane@example.com (not sent)."
    )
    (post,) = harness.graph_calls("POST", "/me/messages")
    assert post.body["body"] == {
        "contentType": "Text",
        "content": "Are you free Saturday?",
    }
    assert not harness.graph_calls("POST", "/me/sendMail")


def test_create_draft_bcc_html_and_importance(harness: UnifiedHarness) -> None:
    data = harness.ok(
        "email_create_draft",
        {
            "to": ["jane@example.com"],
            "cc": ["mark@example.com"],
            "bcc": ["boss@example.com"],
            "subject": "Plan",
            "body": "<p>Hi</p>",
            "body_format": "html",
            "importance": "high",
        },
    )
    assert data["cc"] == ["mark@example.com"]
    assert data["bcc"] == ["boss@example.com"]
    (post,) = harness.graph_calls("POST", "/me/messages")
    assert post.body["body"]["contentType"] == "HTML"
    assert post.body["importance"] == "high"
    assert _addresses(post.body["bccRecipients"]) == ["boss@example.com"]


def test_create_draft_small_and_large_attachments(harness: UnifiedHarness) -> None:
    small = _file(harness, "small.txt", 10)
    large = _file(harness, "large.bin", 3 * MB)
    data = harness.ok(
        "email_create_draft",
        {
            "to": ["jane@example.com"],
            "subject": "Files",
            "body": "Attached.",
            "attachments": [small, large],
        },
    )
    draft_id = data["draft_id"]
    assert data["attachment_count"] == 2
    (small_post,) = harness.graph_calls("POST", f"/me/messages/{draft_id}/attachments")
    assert small_post.body["name"] == "small.txt"
    assert base64.b64decode(small_post.body["contentBytes"]) == b"x" * 10
    (session,) = harness.graph_calls(
        "POST", f"/me/messages/{draft_id}/attachments/createUploadSession"
    )
    assert session.body["AttachmentItem"]["name"] == "large.bin"
    assert session.body["AttachmentItem"]["size"] == 3 * MB
    puts = [c for c in harness.fake.calls if c.method == "PUT"]
    assert len(puts) == 1


def test_create_draft_recipient_limit(harness: UnifiedHarness) -> None:
    to = [f"to{i}@example.com" for i in range(300)]
    cc = [f"cc{i}@example.com" for i in range(201)]
    text = harness.error(
        "email_create_draft",
        {"to": to, "cc": cc, "subject": "Big", "body": "x"},
    )
    assert text == "Invalid to: more than 500 recipients in total"
    assert not harness.graph_calls("POST", "/me/messages")


def test_create_draft_duplicates_count_once(harness: UnifiedHarness) -> None:
    to = [f"p{i}@example.com" for i in range(300)]
    cc = [f"P{i}@example.com" for i in range(200)]
    harness.ok(
        "email_create_draft",
        {"to": to, "cc": cc, "subject": "Dup", "body": "x"},
    )


def test_create_draft_attachment_too_large(harness: UnifiedHarness) -> None:
    name = _sparse(harness, "report.zip", 31 * MB)
    text = harness.error(
        "email_create_draft",
        {"to": ["a@example.com"], "subject": "s", "body": "b", "attachments": [name]},
    )
    assert text == "Invalid attachments: 'report.zip' is 31 MB. Expected: at most 25 MB"
    assert not harness.graph_calls("POST", "/me/messages")


def test_create_draft_attachment_path_checks(harness: UnifiedHarness) -> None:
    text = harness.error(
        "email_create_draft",
        {"to": ["a@example.com"], "subject": "s", "body": "b", "attachments": [".env"]},
    )
    assert text == "Invalid attachments: '.env' is a protected file"
    text = harness.error(
        "email_create_draft",
        {
            "to": ["a@example.com"],
            "subject": "s",
            "body": "b",
            "attachments": ["missing.pdf"],
        },
    )
    assert text.startswith("Invalid attachments: file not found")


# ----------------------------------------------------------------------
# email_send (U3.10)
# ----------------------------------------------------------------------


def test_send_requires_confirm(harness: UnifiedHarness) -> None:
    text = harness.error(
        "email_send",
        {"mode": "draft", "draft_id": "AQMkADAwATM3ZmYAZS1kDRFT", "confirm": False},
    )
    assert text == _confirm_error("send email")
    assert not harness.fake.calls


def test_send_draft_requires_draft_id(harness: UnifiedHarness) -> None:
    text = harness.error("email_send", {"mode": "draft", "confirm": True})
    assert text == "Invalid draft_id: required when mode='draft'"


@pytest.mark.parametrize("field", ["to", "subject", "body"])
def test_send_new_requires_message_fields(harness: UnifiedHarness, field) -> None:
    args: dict[str, Any] = {
        "mode": "new",
        "to": ["jane@example.com"],
        "subject": "Hi",
        "body": "Hello",
        "confirm": True,
    }
    del args[field]
    assert (
        harness.error("email_send", args)
        == f"Invalid {field}: required when mode='new'"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("to", ["jane@example.com"]),
        ("subject", "Hi"),
        ("body_format", "html"),
        ("attachments", ["report.pdf"]),
        ("save_to_sent", False),
    ],
)
def test_send_draft_forbids_message_fields(
    harness: UnifiedHarness, field, value
) -> None:
    text = harness.error(
        "email_send",
        {"mode": "draft", "draft_id": "d1", field: value, "confirm": True},
    )
    assert text == f"Invalid {field}: not allowed when mode='draft'"


def test_send_new_forbids_draft_id(harness: UnifiedHarness) -> None:
    text = harness.error(
        "email_send",
        {
            "mode": "new",
            "draft_id": "d1",
            "to": ["a@example.com"],
            "subject": "s",
            "body": "b",
            "confirm": True,
        },
    )
    assert text == "Invalid draft_id: not allowed when mode='new'"


def test_send_draft_example(harness: UnifiedHarness) -> None:
    draft_id = "AQMkADAwATM3ZmYAZS1kDRFT"
    _seed_message(harness, draft_id, "Weekend")
    harness.fake.messages[draft_id].update(
        isDraft=True,
        parentFolderId="drafts",
        toRecipients=[{"emailAddress": {"address": "jane@example.com"}}],
    )
    data = harness.ok(
        "email_send", {"mode": "draft", "draft_id": draft_id, "confirm": True}
    )
    assert data["status"] == "sent"
    assert data["mode"] == "draft"
    assert data["draft_id"] == draft_id
    assert data["recipient_count"] == 1
    assert data["summary"] == "Sent 'Weekend' to 1 recipient."
    assert len(harness.graph_calls("POST", f"/me/messages/{draft_id}/send")) == 1
    assert harness.fake.messages[draft_id]["isDraft"] is False


def test_send_new_uses_send_mail(harness: UnifiedHarness) -> None:
    small = _file(harness, "note.txt", 5)
    data = harness.ok(
        "email_send",
        {
            "mode": "new",
            "to": ["jane@example.com"],
            "cc": ["mark@example.com"],
            "bcc": ["boss@example.com"],
            "subject": "Hi",
            "body": "Hello",
            "importance": "low",
            "attachments": [small],
            "save_to_sent": False,
            "confirm": True,
        },
    )
    assert data["draft_id"] is None
    assert data["recipient_count"] == 3
    assert data["summary"] == "Sent 'Hi' to 3 recipients."
    (call,) = harness.graph_calls("POST", "/me/sendMail")
    assert call.body["saveToSentItems"] is False
    message = call.body["message"]
    assert _addresses(message["bccRecipients"]) == ["boss@example.com"]
    assert message["importance"] == "low"
    assert message["attachments"][0]["name"] == "note.txt"
    assert not harness.graph_calls("POST", "/me/messages")


def test_send_new_with_large_attachment_goes_through_draft(
    harness: UnifiedHarness,
) -> None:
    large = _file(harness, "big.bin", 3 * MB)
    data = harness.ok(
        "email_send",
        {
            "mode": "new",
            "to": ["jane@example.com"],
            "subject": "Big",
            "body": "See file",
            "attachments": [large],
            "confirm": True,
        },
    )
    draft_id = data["draft_id"]
    assert draft_id
    assert harness.graph_calls("POST", "/me/messages")
    assert harness.graph_calls(
        "POST", f"/me/messages/{draft_id}/attachments/createUploadSession"
    )
    assert len(harness.graph_calls("POST", f"/me/messages/{draft_id}/send")) == 1
    assert not harness.graph_calls("POST", "/me/sendMail")


@pytest.mark.parametrize(
    "error",
    [500, 504, httpx.ReadTimeout("timed out")],
    ids=["500", "504", "timeout"],
)
def test_send_outcome_unknown_is_not_retried(harness: UnifiedHarness, error) -> None:
    _fail(harness, "_send_mail", error)
    text = harness.error(
        "email_send",
        {
            "mode": "new",
            "to": ["jane@example.com"],
            "subject": "Hi",
            "body": "Hello",
            "confirm": True,
        },
    )
    assert text == OUTCOME_UNKNOWN
    if isinstance(error, int):
        assert len(harness.graph_calls("POST", "/me/sendMail")) == 1


def test_send_draft_outcome_unknown(harness: UnifiedHarness) -> None:
    _seed_message(harness, "d1", "Weekend")
    _fail(harness, "_message_action", 502)
    text = harness.error(
        "email_send", {"mode": "draft", "draft_id": "d1", "confirm": True}
    )
    assert text == OUTCOME_UNKNOWN
    assert len(harness.graph_calls("POST", "/me/messages/d1/send")) == 1


def test_send_client_error_is_not_outcome_unknown(harness: UnifiedHarness) -> None:
    text = harness.error(
        "email_send", {"mode": "draft", "draft_id": "nope", "confirm": True}
    )
    assert OUTCOME_UNKNOWN not in text


# ----------------------------------------------------------------------
# email_reply (U3.11)
# ----------------------------------------------------------------------


def test_reply_requires_confirm(harness: UnifiedHarness) -> None:
    text = harness.error(
        "email_reply",
        {
            "email_id": "msg-003",
            "mode": "sender",
            "body": "Yes",
            "confirm": False,
        },
    )
    assert text == _confirm_error("reply")
    assert not harness.fake.calls


def test_reply_all_example(harness: UnifiedHarness) -> None:
    email_id = "AQMkADAwATM3ZmYAZS1k"
    _seed_message(
        harness, email_id, "Planning meeting", conversation_id="AQQkADAwATM3ZmYAZS1"
    )
    data = harness.ok(
        "email_reply",
        {
            "email_id": email_id,
            "mode": "all",
            "body": "Tuesday works for me.",
            "confirm": True,
        },
    )
    assert data == {
        "status": "sent",
        "mode": "all",
        "in_reply_to": email_id,
        "conversation_id": "AQQkADAwATM3ZmYAZS1",
        "summary": "Replied to all on 'Planning meeting'.",
    }
    (call,) = harness.graph_calls("POST", f"/me/messages/{email_id}/replyAll")
    assert call.body == {"comment": "Tuesday works for me."}


def test_reply_sender_plain(harness: UnifiedHarness) -> None:
    data = harness.ok(
        "email_reply",
        {"email_id": "msg-003", "mode": "sender", "body": "Yes!", "confirm": True},
    )
    assert data["summary"] == "Replied to the sender on 'Dinner on Saturday?'."
    assert len(harness.graph_calls("POST", "/me/messages/msg-003/reply")) == 1
    assert not harness.graph_calls("POST", "/me/messages/msg-003/createReply")


def test_reply_with_cc_and_attachment_uses_create_reply(
    harness: UnifiedHarness,
) -> None:
    _seed_message(harness, "m1", "Plans", cc=["mark@example.com"])
    name = _file(harness, "map.png", 20)
    harness.ok(
        "email_reply",
        {
            "email_id": "m1",
            "mode": "all",
            "body": "See map",
            "cc": ["kim@example.com"],
            "attachments": [name],
            "confirm": True,
        },
    )
    (create,) = harness.graph_calls("POST", "/me/messages/m1/createReplyAll")
    assert create.body == {"comment": "See map"}
    draft_id = next(
        c.path.split("/")[3]
        for c in harness.fake.calls
        if c.method == "PATCH" and c.path.startswith("/me/messages/")
    )
    (patch,) = harness.graph_calls("PATCH", f"/me/messages/{draft_id}")
    assert _addresses(patch.body["ccRecipients"]) == [
        "mark@example.com",
        "kim@example.com",
    ]
    assert harness.graph_calls("POST", f"/me/messages/{draft_id}/attachments")
    assert len(harness.graph_calls("POST", f"/me/messages/{draft_id}/send")) == 1
    assert not harness.graph_calls("POST", "/me/messages/m1/replyAll")


def test_reply_sender_with_attachment_only(harness: UnifiedHarness) -> None:
    name = _file(harness, "a.txt", 3)
    harness.ok(
        "email_reply",
        {
            "email_id": "msg-003",
            "mode": "sender",
            "body": "Here",
            "attachments": [name],
            "confirm": True,
        },
    )
    assert harness.graph_calls("POST", "/me/messages/msg-003/createReply")
    assert not [c for c in harness.fake.calls if c.method == "PATCH"]


def test_reply_outcome_unknown(harness: UnifiedHarness) -> None:
    _fail(harness, "_message_action", httpx.ReadTimeout("timed out"))
    text = harness.error(
        "email_reply",
        {"email_id": "msg-003", "mode": "sender", "body": "Yes", "confirm": True},
    )
    assert text == OUTCOME_UNKNOWN


# ----------------------------------------------------------------------
# email_forward (U3.12)
# ----------------------------------------------------------------------


def test_forward_requires_confirm(harness: UnifiedHarness) -> None:
    text = harness.error(
        "email_forward",
        {"email_id": "msg-004", "to": ["a@example.com"], "confirm": False},
    )
    assert text == _confirm_error("forward")
    assert not harness.fake.calls


def test_forward_example(harness: UnifiedHarness) -> None:
    email_id = "AQMkADAwATM3ZmYAZS1k"
    _seed_message(harness, email_id, "Your September invoice")
    data = harness.ok(
        "email_forward",
        {
            "email_id": email_id,
            "to": ["accountant@example.com"],
            "comment": "For our records.",
            "confirm": True,
        },
    )
    assert data == {
        "status": "sent",
        "forwarded_id": email_id,
        "recipient_count": 1,
        "summary": "Forwarded 'Your September invoice' to 1 recipient.",
    }
    (call,) = harness.graph_calls("POST", f"/me/messages/{email_id}/forward")
    assert call.body == {
        "toRecipients": [{"emailAddress": {"address": "accountant@example.com"}}],
        "comment": "For our records.",
    }


def test_forward_with_extras_uses_create_forward(harness: UnifiedHarness) -> None:
    name = _file(harness, "extra.pdf", 50)
    data = harness.ok(
        "email_forward",
        {
            "email_id": "msg-004",
            "to": ["a@example.com"],
            "cc": ["b@example.com"],
            "bcc": ["c@example.com"],
            "attachments": [name],
            "confirm": True,
        },
    )
    assert data["recipient_count"] == 3
    (create,) = harness.graph_calls("POST", "/me/messages/msg-004/createForward")
    draft_id = next(
        c.path.split("/")[3] for c in harness.fake.calls if c.method == "PATCH"
    )
    (patch,) = harness.graph_calls("PATCH", f"/me/messages/{draft_id}")
    assert _addresses(patch.body["toRecipients"]) == ["a@example.com"]
    assert _addresses(patch.body["ccRecipients"]) == ["b@example.com"]
    assert _addresses(patch.body["bccRecipients"]) == ["c@example.com"]
    assert harness.graph_calls("POST", f"/me/messages/{draft_id}/attachments")
    assert len(harness.graph_calls("POST", f"/me/messages/{draft_id}/send")) == 1
    assert not harness.graph_calls("POST", "/me/messages/msg-004/forward")
    assert create.status == 201


def test_forward_outcome_unknown(harness: UnifiedHarness) -> None:
    _fail(harness, "_message_action", 500)
    text = harness.error(
        "email_forward",
        {"email_id": "msg-004", "to": ["a@example.com"], "confirm": True},
    )
    assert text == OUTCOME_UNKNOWN
    assert len(harness.graph_calls("POST", "/me/messages/msg-004/forward")) == 1


def test_sends_use_the_sensitive_rate_limit(
    harness: UnifiedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from m365_mcp.tools.unified import common

    kinds: list[str] = []
    monkeypatch.setattr(common, "check_rate", lambda _a, kind: kinds.append(kind))
    harness.ok(
        "email_forward",
        {"email_id": "msg-004", "to": ["a@example.com"], "confirm": True},
    )
    harness.ok(
        "email_create_draft", {"to": ["a@example.com"], "subject": "s", "body": "b"}
    )
    assert kinds == ["sensitive", "normal"]


@pytest.mark.parametrize(
    ("error", "ambiguous"),
    [
        (500, True),
        (502, True),
        (504, True),
        (503, False),
        (429, False),
        (400, False),
        (httpx.ReadTimeout("t"), True),
        (httpx.RemoteProtocolError("dropped"), True),
        (httpx.ConnectError("refused"), False),
        (httpx.ConnectTimeout("t"), False),
    ],
)
def test_ambiguous_failure_classification(error, ambiguous) -> None:
    from m365_mcp.errors import GraphAPIError
    from m365_mcp.services.mail_compose import is_ambiguous_failure

    if isinstance(error, int):
        error = GraphAPIError(error, "Code", "message", None)
    assert is_ambiguous_failure(error) is ambiguous
