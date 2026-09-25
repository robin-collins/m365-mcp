"""Unit tests for the mail rules service layer."""

from __future__ import annotations

from typing import Any

import pytest

from src.m365_mcp.services import mail_rules

RULES_PATH = "/me/mailFolders/inbox/messageRules"
ACCOUNT = "account-1"


class FakeGraph:
    """Record Graph requests and return queued responses."""

    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        path: str,
        account_id: str | None = None,
        **kwargs: Any,
    ) -> Any:
        self.calls.append(
            {
                "method": method,
                "path": path,
                "account_id": account_id,
                "json": kwargs.get("json"),
            }
        )
        return self.responses.pop(0)


@pytest.fixture
def fake_graph(monkeypatch: pytest.MonkeyPatch):
    def install(*responses: Any) -> FakeGraph:
        fake = FakeGraph(list(responses))
        monkeypatch.setattr(mail_rules.graph, "request", fake.request)
        return fake

    return install


def test_list_rules_returns_value(fake_graph) -> None:
    fake = fake_graph({"value": [{"id": "r1"}, {"id": "r2"}]})

    result = mail_rules.list_rules(ACCOUNT)

    assert result == [{"id": "r1"}, {"id": "r2"}]
    assert fake.calls == [
        {"method": "GET", "path": RULES_PATH, "account_id": ACCOUNT, "json": None}
    ]


@pytest.mark.parametrize("response", [None, {}, {"other": 1}])
def test_list_rules_empty_response(fake_graph, response: Any) -> None:
    fake_graph(response)

    assert mail_rules.list_rules(ACCOUNT) == []


def test_get_rule(fake_graph) -> None:
    fake = fake_graph({"id": "r1", "sequence": 3})

    result = mail_rules.get_rule(ACCOUNT, rule_id="r1")

    assert result == {"id": "r1", "sequence": 3}
    assert fake.calls[0]["method"] == "GET"
    assert fake.calls[0]["path"] == f"{RULES_PATH}/r1"
    assert fake.calls[0]["account_id"] == ACCOUNT


def test_get_rule_not_found(fake_graph) -> None:
    fake_graph(None)

    with pytest.raises(ValueError, match="Message rule with ID r1 not found"):
        mail_rules.get_rule(ACCOUNT, rule_id="r1")


def test_create_rule(fake_graph) -> None:
    fake = fake_graph({"id": "new"})
    rule = {"displayName": "X", "sequence": 1}

    result = mail_rules.create_rule(ACCOUNT, rule=rule)

    assert result == {"id": "new"}
    assert fake.calls == [
        {"method": "POST", "path": RULES_PATH, "account_id": ACCOUNT, "json": rule}
    ]


def test_create_rule_failure(fake_graph) -> None:
    fake_graph(None)

    with pytest.raises(ValueError, match="Failed to create message rule"):
        mail_rules.create_rule(ACCOUNT, rule={"displayName": "X"})


def test_update_rule(fake_graph) -> None:
    fake = fake_graph({"id": "r1", "isEnabled": False})

    result = mail_rules.update_rule(ACCOUNT, rule_id="r1", updates={"isEnabled": False})

    assert result == {"id": "r1", "isEnabled": False}
    assert fake.calls == [
        {
            "method": "PATCH",
            "path": f"{RULES_PATH}/r1",
            "account_id": ACCOUNT,
            "json": {"isEnabled": False},
        }
    ]


def test_update_rule_failure(fake_graph) -> None:
    fake_graph(None)

    with pytest.raises(ValueError, match="Failed to update message rule r1"):
        mail_rules.update_rule(ACCOUNT, rule_id="r1", updates={"sequence": 2})


def test_delete_rule(fake_graph) -> None:
    fake = fake_graph(None)

    result = mail_rules.delete_rule(ACCOUNT, rule_id="r1")

    assert result == {"status": "deleted", "rule_id": "r1"}
    assert fake.calls == [
        {
            "method": "DELETE",
            "path": f"{RULES_PATH}/r1",
            "account_id": ACCOUNT,
            "json": None,
        }
    ]


def test_move_rule_to_top(fake_graph) -> None:
    fake = fake_graph({"id": "r1", "sequence": 1})

    result = mail_rules.move_rule_to_top(ACCOUNT, rule_id="r1")

    assert result == {"id": "r1", "sequence": 1}
    assert fake.calls[0]["method"] == "PATCH"
    assert fake.calls[0]["path"] == f"{RULES_PATH}/r1"
    assert fake.calls[0]["json"] == {"sequence": 1}


def test_move_rule_to_top_failure(fake_graph) -> None:
    fake_graph(None)

    with pytest.raises(ValueError, match="Failed to move rule r1 to top"):
        mail_rules.move_rule_to_top(ACCOUNT, rule_id="r1")


def test_move_rule_to_bottom_uses_max_sequence(fake_graph) -> None:
    fake = fake_graph(
        {"value": [{"id": "a", "sequence": 2}, {"id": "b", "sequence": 7}, {}]},
        {"id": "r1", "sequence": 8},
    )

    result = mail_rules.move_rule_to_bottom(ACCOUNT, rule_id="r1")

    assert result == {"id": "r1", "sequence": 8}
    assert [c["method"] for c in fake.calls] == ["GET", "PATCH"]
    assert fake.calls[0]["path"] == RULES_PATH
    assert fake.calls[1]["path"] == f"{RULES_PATH}/r1"
    assert fake.calls[1]["json"] == {"sequence": 8}


def test_move_rule_to_bottom_no_rules(fake_graph) -> None:
    fake = fake_graph({"value": []})

    with pytest.raises(ValueError, match="No rules found"):
        mail_rules.move_rule_to_bottom(ACCOUNT, rule_id="r1")
    assert len(fake.calls) == 1


def test_move_rule_to_bottom_failure(fake_graph) -> None:
    fake_graph({"value": [{"sequence": 1}]}, None)

    with pytest.raises(ValueError, match="Failed to move rule r1 to bottom"):
        mail_rules.move_rule_to_bottom(ACCOUNT, rule_id="r1")


def test_move_rule_up_decrements_sequence(fake_graph) -> None:
    fake = fake_graph({"id": "r1", "sequence": 3}, {"id": "r1", "sequence": 2})

    result = mail_rules.move_rule_up(ACCOUNT, rule_id="r1")

    assert result == {"id": "r1", "sequence": 2}
    assert [c["method"] for c in fake.calls] == ["GET", "PATCH"]
    assert fake.calls[0]["path"] == f"{RULES_PATH}/r1"
    assert fake.calls[1]["json"] == {"sequence": 2}


@pytest.mark.parametrize("rule", [{"id": "r1", "sequence": 1}, {"id": "r1"}])
def test_move_rule_up_already_top(fake_graph, rule: dict[str, Any]) -> None:
    fake = fake_graph(rule)

    with pytest.raises(ValueError, match="already at the top"):
        mail_rules.move_rule_up(ACCOUNT, rule_id="r1")
    assert len(fake.calls) == 1


def test_move_rule_up_failure(fake_graph) -> None:
    fake_graph({"sequence": 4}, None)

    with pytest.raises(ValueError, match="Failed to move rule r1 up"):
        mail_rules.move_rule_up(ACCOUNT, rule_id="r1")


def test_move_rule_down_increments_sequence(fake_graph) -> None:
    fake = fake_graph({"id": "r1", "sequence": 3}, {"id": "r1", "sequence": 4})

    result = mail_rules.move_rule_down(ACCOUNT, rule_id="r1")

    assert result == {"id": "r1", "sequence": 4}
    assert [c["method"] for c in fake.calls] == ["GET", "PATCH"]
    assert fake.calls[1]["path"] == f"{RULES_PATH}/r1"
    assert fake.calls[1]["json"] == {"sequence": 4}


def test_move_rule_down_failure(fake_graph) -> None:
    fake_graph({"sequence": 1}, None)

    with pytest.raises(ValueError, match="Failed to move rule r1 down"):
        mail_rules.move_rule_down(ACCOUNT, rule_id="r1")
