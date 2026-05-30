from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pytest

from src.m365_mcp import validators
from src.m365_mcp.tools import email as email_tools
from src.m365_mcp.validators import ValidationError


def test_email_send_rejects_invalid_to_before_confirm(
    mock_account_id: str,
) -> None:
    with pytest.raises(ValidationError) as exc:
        email_tools.email_send.fn(
            account_id=mock_account_id,
            to="not-an-email",
            subject="Test",
            body="Hello",
            confirm=False,
        )

    assert "Invalid to" in str(exc.value)


def test_email_send_deduplicates_recipients(
    monkeypatch: pytest.MonkeyPatch,
    mock_account_id: str,
) -> None:
    captured: dict[str, Any] = {}

    def fake_request(
        method: str,
        path: str,
        account_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, str]:
        captured["method"] = method
        captured["path"] = path
        captured["account_id"] = account_id
        captured["json"] = kwargs.get("json")
        return {"status": "sent"}

    monkeypatch.setattr(email_tools.graph, "request", fake_request)

    result = email_tools.email_send.fn(
        account_id=mock_account_id,
        to=["User@example.com", "other@example.com"],
        cc=["user@example.com", "cc@example.com"],
        subject="Greetings",
        body="Hello",
        confirm=True,
    )

    assert result == {"status": "sent"}
    message = captured["json"]["message"]
    to_addresses = [
        entry["emailAddress"]["address"] for entry in message["toRecipients"]
    ]
    assert to_addresses == ["user@example.com", "other@example.com"]
    assert "ccRecipients" in message
    cc_addresses = [
        entry["emailAddress"]["address"] for entry in message["ccRecipients"]
    ]
    assert cc_addresses == ["cc@example.com"]


def test_email_send_enforces_recipient_limit(
    mock_account_id: str,
) -> None:
    recipients = [
        f"user{i}@example.com" for i in range(email_tools.MAX_EMAIL_RECIPIENTS + 1)
    ]

    with pytest.raises(ValidationError) as exc:
        email_tools.email_send.fn(
            account_id=mock_account_id,
            to=recipients,
            subject="Overflow",
            body="Hello",
            confirm=True,
        )

    assert "Invalid recipients" in str(exc.value)


def test_email_send_accepts_valid_attachment(
    monkeypatch: pytest.MonkeyPatch,
    mock_account_id: str,
    tmp_path: Path,
) -> None:
    attachment = tmp_path / "notes.txt"
    attachment.write_text("hello", encoding="utf-8")
    captured: dict[str, Any] = {}

    class FakeCache:
        def invalidate_pattern(self, *args: Any, **kwargs: Any) -> int:
            return 0

    def fake_request(
        method: str,
        path: str,
        account_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, str]:
        captured["method"] = method
        captured["path"] = path
        captured["account_id"] = account_id
        captured["json"] = kwargs.get("json")
        return {"status": "sent"}

    monkeypatch.setattr(email_tools.graph, "request", fake_request)
    monkeypatch.setattr(email_tools, "get_cache_manager", lambda: FakeCache())

    result = email_tools.email_send.fn(
        account_id=mock_account_id,
        to="ada@example.com",
        subject="With attachment",
        body="Hello",
        attachments=str(attachment),
        confirm=True,
    )

    assert result == {"status": "sent"}
    message = captured["json"]["message"]
    assert message["attachments"] == [
        {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": "notes.txt",
            "contentBytes": base64.b64encode(b"hello").decode("utf-8"),
        }
    ]


def test_email_create_draft_rejects_traversal_attachment(
    mock_account_id: str,
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationError, match="parent directory"):
        email_tools.email_create_draft.fn(
            account_id=mock_account_id,
            to="ada@example.com",
            subject="Unsafe",
            body="Hello",
            attachments=str(tmp_path / ".." / "secret.txt"),
        )


def test_email_send_rejects_attachment_outside_allowed_roots(
    monkeypatch: pytest.MonkeyPatch,
    mock_account_id: str,
    tmp_path: Path,
) -> None:
    allowed_root = tmp_path / "allowed"
    blocked_root = tmp_path / "blocked"
    allowed_root.mkdir()
    blocked_root.mkdir()
    attachment = blocked_root / "secret.txt"
    attachment.write_text("secret", encoding="utf-8")

    monkeypatch.delenv("MCP_FILE_ALLOWED_ROOTS", raising=False)
    monkeypatch.setattr(
        validators,
        "DEFAULT_ALLOWED_ROOTS",
        (allowed_root.resolve(),),
    )

    with pytest.raises(ValidationError, match="allowed directories"):
        email_tools.email_send.fn(
            account_id=mock_account_id,
            to="ada@example.com",
            subject="Blocked",
            body="Hello",
            attachments=str(attachment),
            confirm=True,
        )


def test_email_send_rejects_oversize_attachment(
    monkeypatch: pytest.MonkeyPatch,
    mock_account_id: str,
    tmp_path: Path,
) -> None:
    attachment = tmp_path / "too-large.txt"
    attachment.write_bytes(b"abcd")
    monkeypatch.setattr(email_tools, "MAX_MAIL_ATTACHMENT_BYTES", 3)

    with pytest.raises(ValidationError, match="exceeds limit"):
        email_tools.email_send.fn(
            account_id=mock_account_id,
            to="ada@example.com",
            subject="Too large",
            body="Hello",
            attachments=str(attachment),
            confirm=True,
        )


def test_email_send_rejects_too_many_attachments(
    monkeypatch: pytest.MonkeyPatch,
    mock_account_id: str,
    tmp_path: Path,
) -> None:
    first = tmp_path / "one.txt"
    second = tmp_path / "two.txt"
    first.write_text("one", encoding="utf-8")
    second.write_text("two", encoding="utf-8")
    monkeypatch.setattr(email_tools, "MAX_MAIL_ATTACHMENTS", 1)

    with pytest.raises(ValidationError, match="exceeds limit"):
        email_tools.email_send.fn(
            account_id=mock_account_id,
            to="ada@example.com",
            subject="Too many",
            body="Hello",
            attachments=[str(first), str(second)],
            confirm=True,
        )


def test_email_reply_rejects_empty_body_before_confirm(
    mock_account_id: str,
) -> None:
    with pytest.raises(ValidationError) as exc:
        email_tools.email_reply.fn(
            account_id=mock_account_id,
            email_id="message-id",
            body="   ",
            confirm=False,
        )

    assert "Invalid body" in str(exc.value)


def test_email_reply_trims_body_before_send(
    monkeypatch: pytest.MonkeyPatch,
    mock_account_id: str,
) -> None:
    captured: dict[str, Any] = {}

    def fake_request(
        method: str,
        path: str,
        account_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, str]:
        captured["method"] = method
        captured["path"] = path
        captured["account_id"] = account_id
        captured["json"] = kwargs.get("json")
        return {"status": "sent"}

    monkeypatch.setattr(email_tools.graph, "request", fake_request)

    result = email_tools.email_reply.fn(
        account_id=mock_account_id,
        email_id="msg-123",
        body="  Thanks!  ",
        confirm=True,
    )

    assert result == {"status": "sent"}
    payload = captured["json"]
    assert payload["message"]["body"]["content"] == "Thanks!"


def test_email_update_rejects_unknown_key(
    mock_account_id: str,
) -> None:
    with pytest.raises(ValidationError):
        email_tools.email_update.fn(
            email_id="msg-1",
            updates={"subject": "Not allowed"},
            account_id=mock_account_id,
        )


def test_email_update_normalises_payload(
    monkeypatch: pytest.MonkeyPatch,
    mock_account_id: str,
) -> None:
    captured: dict[str, Any] = {}

    def fake_request(
        method: str,
        path: str,
        account_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, str]:
        captured["json"] = kwargs.get("json") or {}
        return {"id": "updated"}

    monkeypatch.setattr(email_tools.graph, "request", fake_request)

    result = email_tools.email_update.fn(
        email_id="msg-1",
        updates={
            "isRead": False,
            "categories": ["  Important  ", "Follow Up"],
            "importance": "HIGH",
            "flag": {
                "flagStatus": "Flagged",
                "startDateTime": {
                    "dateTime": "2024-01-01T09:00:00+00:00",
                    "timeZone": "UTC",
                },
                "dueDateTime": {
                    "dateTime": "2024-01-02T09:00:00+00:00",
                    "timeZone": "UTC",
                },
            },
            "inferenceClassification": "FOCUSED",
        },
        account_id=mock_account_id,
    )

    assert result == {"id": "updated"}
    payload = captured["json"]
    assert payload["isRead"] is False
    assert payload["categories"] == ["Important", "Follow Up"]
    assert payload["importance"] == "high"
    assert payload["flag"]["flagStatus"] == "flagged"
    assert payload["inferenceClassification"] == "focused"


def test_email_update_rejects_invalid_flag_dates(
    mock_account_id: str,
) -> None:
    with pytest.raises(ValidationError):
        email_tools.email_update.fn(
            email_id="msg-1",
            updates={
                "flag": {
                    "flagStatus": "flagged",
                    "startDateTime": {
                        "dateTime": "2024-01-03T10:00:00+00:00",
                        "timeZone": "UTC",
                    },
                    "dueDateTime": {
                        "dateTime": "2024-01-02T10:00:00+00:00",
                        "timeZone": "UTC",
                    },
                }
            },
            account_id=mock_account_id,
        )


def test_email_list_rejects_invalid_limit(mock_account_id: str) -> None:
    with pytest.raises(ValidationError):
        email_tools.email_list.fn(
            account_id=mock_account_id,
            limit=0,
        )


def test_email_get_rejects_invalid_body_limit(mock_account_id: str) -> None:
    with pytest.raises(ValidationError):
        email_tools.email_get.fn(
            email_id="msg-1",
            account_id=mock_account_id,
            body_max_length=0,
        )


def test_email_list_rejects_unknown_folder(mock_account_id: str) -> None:
    with pytest.raises(ValidationError):
        email_tools.email_list.fn(
            account_id=mock_account_id,
            folder="unknown",
        )


def test_email_move_rejects_unknown_folder(mock_account_id: str) -> None:
    with pytest.raises(ValidationError):
        email_tools.email_move.fn(
            email_id="msg-1",
            destination_folder="other",
            account_id=mock_account_id,
        )
