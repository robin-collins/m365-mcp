"""Unit tests for the mail service layer."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pytest

from src.m365_mcp.services import mail as mail_service
from src.m365_mcp.validators import ValidationError

ACCOUNT = "account-1"


class FakeCache:
    """Minimal cache manager double recording calls."""

    def __init__(self, cached: Any = None) -> None:
        self.cached = cached
        self.set_calls: list[tuple[str, str, dict[str, Any], Any]] = []
        self.invalidated: list[tuple[str, str | None]] = []

    def get_cached(self, account_id: str, resource: str, params: dict[str, Any]) -> Any:
        return self.cached

    def set_cached(
        self,
        account_id: str,
        resource: str,
        params: dict[str, Any],
        data: Any,
    ) -> None:
        self.set_calls.append((account_id, resource, params, data))

    def invalidate_pattern(self, pattern: str, account_id: str | None = None) -> int:
        self.invalidated.append((pattern, account_id))
        return 0


class FakeState:
    value = "fresh"


@pytest.fixture
def cache(monkeypatch: pytest.MonkeyPatch) -> FakeCache:
    fake = FakeCache()
    monkeypatch.setattr(mail_service, "get_cache_manager", lambda: fake)
    return fake


def _fake_request(recorded: list[dict[str, Any]], responses: list[Any]) -> Any:
    def fake(
        method: str,
        path: str,
        account_id: str | None = None,
        **kwargs: Any,
    ) -> Any:
        recorded.append(
            {"method": method, "path": path, "account_id": account_id, **kwargs}
        )
        return responses.pop(0) if responses else None

    return fake


def test_list_messages_fetches_folder_and_caches(
    monkeypatch: pytest.MonkeyPatch, cache: FakeCache
) -> None:
    captured: dict[str, Any] = {}

    def fake_paginated(
        path: str,
        account_id: str,
        params: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        captured.update(path=path, account_id=account_id, params=params, limit=limit)
        return [{"id": "m1"}]

    monkeypatch.setattr(mail_service.graph, "request_paginated", fake_paginated)

    result = mail_service.list_messages(
        ACCOUNT,
        folder="sent",
        folder_id=None,
        folder_path="sentitems",
        limit=5,
        include_body=False,
        use_cache=True,
        force_refresh=False,
    )

    assert captured["path"] == "/me/mailFolders/sentitems/messages"
    assert captured["account_id"] == ACCOUNT
    assert captured["limit"] == 5
    assert captured["params"]["$top"] == 5
    assert captured["params"]["$orderby"] == "receivedDateTime desc"
    assert "body" not in captured["params"]["$select"].split(",")
    assert result[0]["id"] == "m1"
    assert result[0]["_cache_status"] == "miss"
    assert "_cached_at" in result[0]
    assert cache.set_calls[0][1] == "email_list"
    assert cache.set_calls[0][2]["folder_path"] == "sentitems"


def test_list_messages_returns_cached_data(
    monkeypatch: pytest.MonkeyPatch, cache: FakeCache
) -> None:
    cache.cached = ([{"id": "cached"}], FakeState())

    def fail(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("graph should not be called")

    monkeypatch.setattr(mail_service.graph, "request_paginated", fail)

    result = mail_service.list_messages(
        ACCOUNT,
        folder=None,
        folder_id=None,
        folder_path="inbox",
        limit=10,
        include_body=True,
        use_cache=True,
        force_refresh=False,
    )

    assert result == [{"id": "cached", "_cache_status": "fresh"}]


def test_get_message_truncates_body_and_strips_content_bytes(
    monkeypatch: pytest.MonkeyPatch, cache: FakeCache
) -> None:
    recorded: list[dict[str, Any]] = []
    response = {
        "id": "m1",
        "body": {"content": "abcdefghij"},
        "attachments": [{"id": "a1", "contentBytes": "xx"}],
    }
    monkeypatch.setattr(
        mail_service.graph, "request", _fake_request(recorded, [response])
    )

    result = mail_service.get_message(
        ACCOUNT,
        email_id="m1",
        include_body=True,
        body_max_length=4,
        include_attachments=True,
        use_cache=True,
        force_refresh=False,
    )

    assert recorded[0]["method"] == "GET"
    assert recorded[0]["path"] == "/me/messages/m1"
    assert recorded[0]["params"] == {
        "$expand": "attachments($select=id,name,size,contentType)"
    }
    assert result["body"]["content"].startswith("abcd\n\n[Content truncated")
    assert result["body"]["truncated"] is True
    assert result["body"]["total_length"] == 10
    assert "contentBytes" not in result["attachments"][0]
    assert result["_cache_status"] == "miss"
    assert cache.set_calls[0][1] == "email_get"


def test_get_message_raises_when_missing(
    monkeypatch: pytest.MonkeyPatch, cache: FakeCache
) -> None:
    monkeypatch.setattr(mail_service.graph, "request", _fake_request([], [{}]))

    with pytest.raises(ValueError, match="Email with ID m1 not found"):
        mail_service.get_message(
            ACCOUNT,
            email_id="m1",
            include_body=False,
            body_max_length=10,
            include_attachments=False,
            use_cache=False,
            force_refresh=False,
        )


def test_create_draft_posts_message_and_uploads_large_attachments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[dict[str, Any]] = []
    uploads: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        mail_service.graph,
        "request",
        _fake_request(recorded, [{"id": "draft-1"}]),
    )
    monkeypatch.setattr(
        mail_service.graph,
        "upload_large_mail_attachment",
        lambda *args: uploads.append(args),
    )
    large = mail_service.MAIL_INLINE_ATTACHMENT_THRESHOLD
    attachments = [
        {"name": "a.txt", "content_bytes": b"hi", "size": 2},
        {"name": "big.bin", "content_bytes": b"x", "size": large},
    ]

    result = mail_service.create_draft(
        ACCOUNT,
        to=["a@example.com"],
        cc=["c@example.com"],
        subject="S",
        body="B",
        attachments=attachments,
    )

    assert result == {"id": "draft-1"}
    assert recorded[0]["method"] == "POST"
    assert recorded[0]["path"] == "/me/messages"
    message = recorded[0]["json"]
    assert message["toRecipients"] == [{"emailAddress": {"address": "a@example.com"}}]
    assert message["ccRecipients"] == [{"emailAddress": {"address": "c@example.com"}}]
    assert message["attachments"] == [
        {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": "a.txt",
            "contentBytes": base64.b64encode(b"hi").decode("utf-8"),
        }
    ]
    assert uploads == [
        ("draft-1", "big.bin", b"x", ACCOUNT, "application/octet-stream")
    ]


def test_send_message_posts_send_mail_and_invalidates(
    monkeypatch: pytest.MonkeyPatch, cache: FakeCache
) -> None:
    recorded: list[dict[str, Any]] = []
    monkeypatch.setattr(mail_service.graph, "request", _fake_request(recorded, []))

    result = mail_service.send_message(
        ACCOUNT,
        to=["a@example.com"],
        cc=[],
        subject="S",
        body="B",
        attachments=[],
    )

    assert result == {"status": "sent"}
    assert recorded[0]["path"] == "/me/sendMail"
    assert recorded[0]["json"]["message"]["subject"] == "S"
    assert "ccRecipients" not in recorded[0]["json"]["message"]
    assert cache.invalidated == [("email_list:*", ACCOUNT)]


def test_send_message_with_large_attachment_uses_draft_then_send(
    monkeypatch: pytest.MonkeyPatch, cache: FakeCache
) -> None:
    recorded: list[dict[str, Any]] = []
    monkeypatch.setattr(
        mail_service.graph,
        "request",
        _fake_request(recorded, [{"id": "d1"}, {}, {}]),
    )
    uploads: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        mail_service.graph,
        "upload_large_mail_attachment",
        lambda *args: uploads.append(args),
    )
    large = mail_service.MAIL_INLINE_ATTACHMENT_THRESHOLD

    mail_service.send_message(
        ACCOUNT,
        to=["a@example.com"],
        cc=[],
        subject="S",
        body="B",
        attachments=[
            {"name": "s.txt", "content_bytes": b"s", "size": 1},
            {"name": "b.bin", "content_bytes": b"b", "size": large},
        ],
    )

    assert [c["path"] for c in recorded] == [
        "/me/messages",
        "/me/messages/d1/attachments",
        "/me/messages/d1/send",
    ]
    assert uploads[0][:2] == ("d1", "b.bin")


def test_update_message_patches_and_invalidates(
    monkeypatch: pytest.MonkeyPatch, cache: FakeCache
) -> None:
    recorded: list[dict[str, Any]] = []
    monkeypatch.setattr(
        mail_service.graph, "request", _fake_request(recorded, [{"id": "m1"}])
    )

    result = mail_service.update_message(
        ACCOUNT, email_id="m1", updates={"isRead": True}
    )

    assert result == {"id": "m1"}
    assert recorded[0]["method"] == "PATCH"
    assert recorded[0]["path"] == "/me/messages/m1"
    assert recorded[0]["json"] == {"isRead": True}
    assert cache.invalidated == [("email_get:*", ACCOUNT)]


def test_update_message_raises_on_empty_response(
    monkeypatch: pytest.MonkeyPatch, cache: FakeCache
) -> None:
    monkeypatch.setattr(mail_service.graph, "request", _fake_request([], []))

    with pytest.raises(ValueError, match="Failed to update email m1"):
        mail_service.update_message(ACCOUNT, email_id="m1", updates={"a": 1})


def test_mark_read_patches_and_invalidates_get_and_list(
    monkeypatch: pytest.MonkeyPatch, cache: FakeCache
) -> None:
    recorded: list[dict[str, Any]] = []
    monkeypatch.setattr(
        mail_service.graph, "request", _fake_request(recorded, [{"id": "m1"}])
    )

    mail_service.mark_read(ACCOUNT, email_id="m1", is_read=False)

    assert recorded[0]["json"] == {"isRead": False}
    assert cache.invalidated == [
        ("email_get:*", ACCOUNT),
        ("email_list:*", ACCOUNT),
    ]


def test_set_flag_patches_flag_status(
    monkeypatch: pytest.MonkeyPatch, cache: FakeCache
) -> None:
    recorded: list[dict[str, Any]] = []
    monkeypatch.setattr(
        mail_service.graph, "request", _fake_request(recorded, [{"id": "m1"}])
    )

    mail_service.set_flag(ACCOUNT, email_id="m1", flag_status="complete")

    assert recorded[0]["path"] == "/me/messages/m1"
    assert recorded[0]["json"] == {"flag": {"flagStatus": "complete"}}
    assert cache.invalidated == [("email_get:*", ACCOUNT)]


def test_set_categories_patches_categories(
    monkeypatch: pytest.MonkeyPatch, cache: FakeCache
) -> None:
    recorded: list[dict[str, Any]] = []
    monkeypatch.setattr(
        mail_service.graph, "request", _fake_request(recorded, [{"id": "m1"}])
    )

    mail_service.set_categories(ACCOUNT, email_id="m1", categories=["Red"])

    assert recorded[0]["json"] == {"categories": ["Red"]}
    assert cache.invalidated == [("email_get:*", ACCOUNT)]


def test_delete_message_deletes_and_invalidates(
    monkeypatch: pytest.MonkeyPatch, cache: FakeCache
) -> None:
    recorded: list[dict[str, Any]] = []
    monkeypatch.setattr(mail_service.graph, "request", _fake_request(recorded, []))

    result = mail_service.delete_message(ACCOUNT, email_id="m1")

    assert result == {"status": "deleted"}
    assert recorded[0]["method"] == "DELETE"
    assert recorded[0]["path"] == "/me/messages/m1"
    assert cache.invalidated == [
        ("email_list:*", ACCOUNT),
        ("email_get:*", ACCOUNT),
    ]


FOLDER_LISTING = {
    "value": [
        {"id": "f-inbox", "displayName": "Inbox", "wellKnownName": "inbox"},
        {"id": "f-arch", "displayName": "Archive", "wellKnownName": ""},
    ]
}


def test_move_message_resolves_folder_and_moves(
    monkeypatch: pytest.MonkeyPatch, cache: FakeCache
) -> None:
    recorded: list[dict[str, Any]] = []
    monkeypatch.setattr(
        mail_service.graph,
        "request",
        _fake_request(recorded, [FOLDER_LISTING, {"id": "new-1"}]),
    )

    result = mail_service.move_message(
        ACCOUNT,
        email_id="m1",
        folder_key="inbox",
        destination_folder="Inbox",
    )

    assert result == {"status": "moved", "new_id": "new-1"}
    assert recorded[0]["path"] == "/me/mailFolders"
    assert recorded[1]["path"] == "/me/messages/m1/move"
    assert recorded[1]["json"] == {"destinationId": "f-inbox"}
    assert cache.invalidated == [("email_list:*", ACCOUNT)]


def test_move_message_raises_when_folder_missing(
    monkeypatch: pytest.MonkeyPatch, cache: FakeCache
) -> None:
    monkeypatch.setattr(
        mail_service.graph,
        "request",
        _fake_request([], [{"value": []}]),
    )

    with pytest.raises(ValueError, match="Folder 'junk' not found"):
        mail_service.move_message(
            ACCOUNT,
            email_id="m1",
            folder_key="junk",
            destination_folder="junk",
        )


def test_archive_message_matches_display_name(
    monkeypatch: pytest.MonkeyPatch, cache: FakeCache
) -> None:
    recorded: list[dict[str, Any]] = []
    monkeypatch.setattr(
        mail_service.graph,
        "request",
        _fake_request(recorded, [FOLDER_LISTING, {"id": "new-2"}]),
    )

    result = mail_service.archive_message(ACCOUNT, email_id="m1")

    assert result == {"status": "archived", "new_id": "new-2"}
    assert recorded[1]["json"] == {"destinationId": "f-arch"}


def test_reply_posts_reply_body(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[dict[str, Any]] = []
    monkeypatch.setattr(mail_service.graph, "request", _fake_request(recorded, []))

    result = mail_service.reply(ACCOUNT, email_id="m1", body="Thanks")

    assert result == {"status": "sent"}
    assert recorded[0]["path"] == "/me/messages/m1/reply"
    assert recorded[0]["json"] == {
        "message": {"body": {"contentType": "Text", "content": "Thanks"}}
    }


def test_reply_all_posts_reply_all(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[dict[str, Any]] = []
    monkeypatch.setattr(mail_service.graph, "request", _fake_request(recorded, []))

    result = mail_service.reply_all(ACCOUNT, email_id="m1", body="All")

    assert result == {"status": "sent"}
    assert recorded[0]["path"] == "/me/messages/m1/replyAll"
    assert recorded[0]["json"]["message"]["body"]["content"] == "All"


def test_forward_message_builds_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[dict[str, Any]] = []
    monkeypatch.setattr(mail_service.graph, "request", _fake_request(recorded, []))

    result = mail_service.forward_message(
        ACCOUNT,
        email_id="m1",
        to=["a@example.com"],
        cc=["c@example.com"],
        body="  FYI  ",
    )

    assert result == {"status": "sent"}
    assert recorded[0]["path"] == "/me/messages/m1/forward"
    assert recorded[0]["json"] == {
        "toRecipients": [{"emailAddress": {"address": "a@example.com"}}],
        "ccRecipients": [{"emailAddress": {"address": "c@example.com"}}],
        "comment": "FYI",
    }


def test_forward_message_omits_blank_comment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[dict[str, Any]] = []
    monkeypatch.setattr(mail_service.graph, "request", _fake_request(recorded, []))

    mail_service.forward_message(
        ACCOUNT, email_id="m1", to=["a@example.com"], cc=[], body="   "
    )

    assert recorded[0]["json"] == {
        "toRecipients": [{"emailAddress": {"address": "a@example.com"}}]
    }


def test_download_attachment_writes_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recorded: list[dict[str, Any]] = []
    response = {
        "name": "doc.txt",
        "contentType": "text/plain",
        "size": 5,
        "contentBytes": base64.b64encode(b"hello").decode("ascii"),
    }
    monkeypatch.setattr(
        mail_service.graph, "request", _fake_request(recorded, [response])
    )
    destination = tmp_path / "doc.txt"

    result = mail_service.download_attachment(
        ACCOUNT,
        email_id="m1",
        attachment_id="a1",
        destination=destination,
    )

    assert recorded[0]["method"] == "GET"
    assert recorded[0]["path"] == "/me/messages/m1/attachments/a1"
    assert destination.read_bytes() == b"hello"
    assert result == {
        "name": "doc.txt",
        "content_type": "text/plain",
        "size": 5,
        "saved_to": str(destination),
    }


def test_download_attachment_raises_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(mail_service.graph, "request", _fake_request([], [{}]))

    with pytest.raises(ValidationError, match="attachment not found"):
        mail_service.download_attachment(
            ACCOUNT,
            email_id="m1",
            attachment_id="a1",
            destination=tmp_path / "x.bin",
        )
