from __future__ import annotations

from typing import Any

import pytest

from src.m365_mcp.tools import email_rules as email_rules_tools
from src.m365_mcp.validators import ValidationError


def test_emailrules_create_normalises_payload(
    monkeypatch: pytest.MonkeyPatch,
    mock_account_id: str,
) -> None:
    captured: dict[str, Any] = {}

    def fake_request(
        method: str,
        path: str,
        account_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        captured["method"] = method
        captured["path"] = path
        captured["account_id"] = account_id
        captured["json"] = kwargs.get("json") or {}
        return {"id": "rule-1"}

    monkeypatch.setattr(email_rules_tools.graph, "request", fake_request)

    result = email_rules_tools.emailrules_create.fn(
        account_id=mock_account_id,
        display_name="  Important Projects ",
        sequence=2,
        is_enabled=False,
        conditions={
            "categories": ["  Projects  "],
            "fromAddresses": ["LEAD@example.com"],
            "hasAttachments": True,
        },
        actions={
            "assignCategories": ["  Projects  "],
            "markAsRead": False,
            "forwardTo": ["manager@example.com"],
        },
        exceptions={"subjectContains": ["  FYI  "]},
    )

    assert result == {"id": "rule-1"}
    assert captured["method"] == "POST"
    assert captured["path"] == "/me/mailFolders/inbox/messageRules"
    assert captured["account_id"] == mock_account_id
    payload = captured["json"]
    assert payload["displayName"] == "Important Projects"
    assert payload["sequence"] == 2
    assert payload["isEnabled"] is False
    assert payload["conditions"]["categories"] == ["Projects"]
    assert payload["conditions"]["fromAddresses"] == [
        {"emailAddress": {"address": "lead@example.com"}}
    ]
    assert payload["actions"]["assignCategories"] == ["Projects"]
    assert payload["actions"]["forwardTo"] == [
        {"emailAddress": {"address": "manager@example.com"}}
    ]
    assert payload["exceptions"]["subjectContains"] == ["FYI"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"display_name": "   "},
        {"sequence": 0},
        {"sequence": "1"},
        {"is_enabled": "yes"},
        {"conditions": {"unknownPredicate": True}},
        {"conditions": {"hasAttachments": "yes"}},
        {"actions": {"assignCategories": "Projects"}},
        {"actions": {"forwardTo": ["not-an-email"]}},
        {"exceptions": {"subjectContains": [""]}},
    ],
)
def test_emailrules_create_rejects_invalid_payloads_locally(
    monkeypatch: pytest.MonkeyPatch,
    mock_account_id: str,
    kwargs: dict[str, Any],
) -> None:
    def fail_request(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Graph should not be called for invalid create payloads")

    monkeypatch.setattr(email_rules_tools.graph, "request", fail_request)

    payload = {
        "account_id": mock_account_id,
        "display_name": "Valid Rule",
        "conditions": {"subjectContains": ["Project"]},
        "actions": {"markAsRead": True},
    }
    payload.update(kwargs)

    with pytest.raises(ValidationError):
        email_rules_tools.emailrules_create.fn(**payload)


def test_emailrules_update_rejects_sequence_below_one(
    mock_account_id: str,
) -> None:
    with pytest.raises(ValidationError):
        email_rules_tools.emailrules_update.fn(
            rule_id="rule-1",
            account_id=mock_account_id,
            sequence=0,
        )


def test_emailrules_update_requires_updates(mock_account_id: str) -> None:
    with pytest.raises(ValidationError):
        email_rules_tools.emailrules_update.fn(
            rule_id="rule-1",
            account_id=mock_account_id,
        )


def test_emailrules_update_normalises_payload(
    monkeypatch: pytest.MonkeyPatch,
    mock_account_id: str,
) -> None:
    captured: dict[str, Any] = {}

    def fake_request(
        method: str,
        path: str,
        account_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        captured["json"] = kwargs.get("json") or {}
        return {"id": "rule-1"}

    monkeypatch.setattr(email_rules_tools.graph, "request", fake_request)

    result = email_rules_tools.emailrules_update.fn(
        rule_id="rule-1",
        account_id=mock_account_id,
        display_name="  Important Projects ",
        conditions={
            "categories": ["  Projects  "],
            "fromAddresses": ["LEAD@example.com"],
            "hasAttachments": True,
        },
        actions={
            "assignCategories": ["  Projects  "],
            "markAsRead": False,
            "forwardTo": ["manager@example.com"],
        },
    )

    assert result == {"id": "rule-1"}
    payload = captured["json"]
    assert payload["displayName"] == "Important Projects"
    assert payload["conditions"]["categories"] == ["Projects"]
    assert payload["conditions"]["fromAddresses"] == [
        {"emailAddress": {"address": "lead@example.com"}}
    ]
    assert payload["actions"]["assignCategories"] == ["Projects"]
    assert payload["actions"]["forwardTo"] == [
        {"emailAddress": {"address": "manager@example.com"}}
    ]


def test_emailrules_update_rejects_invalid_actions(mock_account_id: str) -> None:
    with pytest.raises(ValidationError):
        email_rules_tools.emailrules_update.fn(
            rule_id="rule-1",
            account_id=mock_account_id,
            actions={"assignCategories": "not-a-list"},
        )
