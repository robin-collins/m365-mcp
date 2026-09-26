"""Tests for email_rule_manage (U3.22) against the fake Graph."""

from __future__ import annotations

from typing import Any

import pytest

from tests.unified_harness import UnifiedHarness

RULES = "/me/mailFolders/inbox/messageRules"
BILLS_FOLDER = "AQMkADAwATM3ZmYAZS1kBILL"


def _confirm_error(verb: str) -> str:
    return (
        f"Invalid confirm 'False': a rule that {verb} mail requires confirm=True "
        "to proceed. Expected: Explicit user confirmation"
    )


def _seed_folder(harness: UnifiedHarness, folder_id: str, name: str) -> None:
    harness.fake.folders[folder_id] = {
        "id": folder_id,
        "displayName": name,
        "parentFolderId": "msgfolderroot",
        "childFolderCount": 0,
        "unreadItemCount": 0,
        "totalItemCount": 0,
        "isHidden": False,
    }


def _seed_rule(
    harness: UnifiedHarness,
    rule_id: str,
    sequence: int,
    actions: dict[str, Any] | None = None,
) -> None:
    harness.fake.rules[rule_id] = {
        "id": rule_id,
        "displayName": rule_id.title(),
        "sequence": sequence,
        "isEnabled": True,
        "conditions": {"subjectContains": ["x"]},
        "actions": actions or {"markAsRead": True},
    }


def _order(harness: UnifiedHarness) -> list[str]:
    rules = sorted(harness.fake.rules.values(), key=lambda r: r["sequence"])
    return [r["id"] for r in rules]


def _sequences(harness: UnifiedHarness) -> list[int]:
    return sorted(r["sequence"] for r in harness.fake.rules.values())


# ----------------------------------------------------------------------
# create
# ----------------------------------------------------------------------


def test_create_example(harness: UnifiedHarness) -> None:
    _seed_folder(harness, BILLS_FOLDER, "Bills")
    data = harness.ok(
        "email_rule_manage",
        {
            "action": "create",
            "rule": {
                "display_name": "Bills",
                "conditions": {"from_addresses": ["billing@example.com"]},
                "actions": {
                    "move_to_folder": BILLS_FOLDER,
                    "stop_processing_rules": True,
                },
            },
        },
    )
    rule = data["rule"]
    assert data["action"] == "create"
    assert rule["id"] in harness.fake.rules
    assert rule["display_name"] == "Bills"
    assert rule["sequence"] == 3
    assert rule["is_enabled"] is True
    assert rule["conditions"] == {"from_addresses": ["billing@example.com"]}
    assert rule["actions"] == {
        "move_to_folder": BILLS_FOLDER,
        "stop_processing_rules": True,
    }
    assert rule["exceptions"] is None
    assert data["summary"] == "Created rule 'Bills' (position 3)."
    (post,) = harness.graph_calls("POST", RULES)
    assert post.body == {
        "displayName": "Bills",
        "conditions": {
            "fromAddresses": [{"emailAddress": {"address": "billing@example.com"}}]
        },
        "actions": {"moveToFolder": BILLS_FOLDER, "stopProcessingRules": True},
        "isEnabled": True,
        "sequence": 3,
    }


def test_create_translates_exceptions_and_sequence(harness: UnifiedHarness) -> None:
    data = harness.ok(
        "email_rule_manage",
        {
            "action": "create",
            "rule": {
                "display_name": "Big",
                "conditions": {"within_size_range": {"minimum_kb": 500}},
                "actions": {"mark_importance": "low"},
                "exceptions": {"sent_only_to_me": True},
                "is_enabled": False,
                "sequence": 1,
            },
        },
    )
    (post,) = harness.graph_calls("POST", RULES)
    assert post.body["conditions"] == {"withinSizeRange": {"minimumSize": 500}}
    assert post.body["exceptions"] == {"sentOnlyToMe": True}
    assert post.body["isEnabled"] is False
    assert post.body["sequence"] == 1
    assert data["rule"]["exceptions"] == {"sent_only_to_me": True}
    assert data["rule"]["is_enabled"] is False


@pytest.mark.parametrize(
    "rule",
    [
        None,
        {"display_name": "X", "conditions": {"has_attachments": True}},
        {"display_name": "X", "actions": {"mark_as_read": True}},
        {"conditions": {"has_attachments": True}, "actions": {"mark_as_read": True}},
    ],
)
def test_create_requires_name_conditions_actions(harness: UnifiedHarness, rule) -> None:
    args: dict[str, Any] = {"action": "create"}
    if rule is not None:
        args["rule"] = rule
    text = harness.error("email_rule_manage", args)
    assert text == "Invalid rule: create requires display_name, conditions and actions"


def test_create_unknown_folder(harness: UnifiedHarness) -> None:
    text = harness.error(
        "email_rule_manage",
        {
            "action": "create",
            "rule": {
                "display_name": "X",
                "conditions": {"has_attachments": True},
                "actions": {"move_to_folder": "no-such-folder"},
            },
        },
    )
    assert text == "Invalid move_to_folder: folder not found"
    assert not harness.graph_calls("POST", RULES)


def test_create_unknown_copy_folder(harness: UnifiedHarness) -> None:
    text = harness.error(
        "email_rule_manage",
        {
            "action": "create",
            "rule": {
                "display_name": "X",
                "conditions": {"has_attachments": True},
                "actions": {"copy_to_folder": "no-such-folder"},
            },
        },
    )
    assert text == "Invalid copy_to_folder: folder not found"


@pytest.mark.parametrize(
    ("actions", "verb"),
    [
        ({"forward_to": ["x@example.com"]}, "forwards"),
        ({"forward_as_attachment_to": ["x@example.com"]}, "forwards"),
        ({"redirect_to": ["x@example.com"]}, "redirects"),
        ({"delete": True}, "deletes"),
        ({"permanent_delete": True}, "deletes"),
    ],
)
def test_create_dangerous_rule_needs_confirm(
    harness: UnifiedHarness, actions, verb
) -> None:
    args = {
        "action": "create",
        "rule": {
            "display_name": "Danger",
            "conditions": {"has_attachments": True},
            "actions": actions,
        },
    }
    assert harness.error("email_rule_manage", args) == _confirm_error(verb)
    assert not harness.graph_calls("POST", RULES)
    harness.ok("email_rule_manage", {**args, "confirm": True})
    assert harness.graph_calls("POST", RULES)


def test_create_delete_false_needs_no_confirm(harness: UnifiedHarness) -> None:
    harness.ok(
        "email_rule_manage",
        {
            "action": "create",
            "rule": {
                "display_name": "Safe",
                "conditions": {"has_attachments": True},
                "actions": {"delete": False, "mark_as_read": True},
            },
        },
    )


# ----------------------------------------------------------------------
# rule_id / per-action requirements
# ----------------------------------------------------------------------


@pytest.mark.parametrize("action", ["update", "set_enabled", "reorder"])
def test_rule_id_required(harness: UnifiedHarness, action) -> None:
    text = harness.error("email_rule_manage", {"action": action})
    assert text == f"Invalid rule_id: required for action '{action}'"


@pytest.mark.parametrize(
    ("action", "param"),
    [("update", "rule"), ("set_enabled", "is_enabled"), ("reorder", "position")],
)
def test_action_parameters_required(harness: UnifiedHarness, action, param) -> None:
    text = harness.error(
        "email_rule_manage", {"action": action, "rule_id": "rule-news"}
    )
    assert text == f"Invalid {param}: required for action '{action}'"


@pytest.mark.parametrize("position", ["before", "after"])
def test_relative_rule_required(harness: UnifiedHarness, position) -> None:
    text = harness.error(
        "email_rule_manage",
        {"action": "reorder", "rule_id": "rule-news", "position": position},
    )
    assert text == f"Invalid relative_to_rule_id: required for position '{position}'"


def test_relative_rule_must_differ(harness: UnifiedHarness) -> None:
    text = harness.error(
        "email_rule_manage",
        {
            "action": "reorder",
            "rule_id": "rule-news",
            "position": "after",
            "relative_to_rule_id": "rule-news",
        },
    )
    assert text == "Invalid relative_to_rule_id: must differ from rule_id"


# ----------------------------------------------------------------------
# update and set_enabled
# ----------------------------------------------------------------------


def test_update_is_partial(harness: UnifiedHarness) -> None:
    data = harness.ok(
        "email_rule_manage",
        {
            "action": "update",
            "rule_id": "rule-news",
            "rule": {"display_name": "Newsletters"},
        },
    )
    (patch,) = harness.graph_calls("PATCH", f"{RULES}/rule-news")
    assert patch.body == {"displayName": "Newsletters"}
    assert data["rule"]["display_name"] == "Newsletters"
    assert data["rule"]["actions"] == {
        "move_to_folder": "folder-reading",
        "stop_processing_rules": True,
    }
    assert data["summary"] == "Updated rule 'Newsletters'."


def test_update_checks_new_folder(harness: UnifiedHarness) -> None:
    text = harness.error(
        "email_rule_manage",
        {
            "action": "update",
            "rule_id": "rule-news",
            "rule": {"actions": {"move_to_folder": "missing"}},
        },
    )
    assert text == "Invalid move_to_folder: folder not found"
    assert not harness.graph_calls("PATCH")


def test_update_confirm_uses_merged_rule(harness: UnifiedHarness) -> None:
    _seed_rule(
        harness,
        "rule-fwd",
        3,
        {"forwardTo": [{"emailAddress": {"address": "a@x.com"}}]},
    )
    # Renaming a forwarding rule still results in a forwarding rule.
    args = {
        "action": "update",
        "rule_id": "rule-fwd",
        "rule": {"display_name": "Renamed"},
    }
    assert harness.error("email_rule_manage", args) == _confirm_error("forwards")
    assert not harness.graph_calls("PATCH")
    harness.ok("email_rule_manage", {**args, "confirm": True})
    # Replacing the actions with safe ones needs no confirm.
    harness.ok(
        "email_rule_manage",
        {
            "action": "update",
            "rule_id": "rule-fwd",
            "rule": {"actions": {"mark_as_read": True}},
        },
    )


def test_update_adding_redirect_needs_confirm(harness: UnifiedHarness) -> None:
    text = harness.error(
        "email_rule_manage",
        {
            "action": "update",
            "rule_id": "rule-boss",
            "rule": {"actions": {"redirect_to": ["x@example.com"]}},
        },
    )
    assert text == _confirm_error("redirects")


def test_set_enabled(harness: UnifiedHarness) -> None:
    data = harness.ok(
        "email_rule_manage",
        {"action": "set_enabled", "rule_id": "rule-boss", "is_enabled": False},
    )
    (patch,) = harness.graph_calls("PATCH", f"{RULES}/rule-boss")
    assert patch.body == {"isEnabled": False}
    assert data["rule"]["is_enabled"] is False
    assert data["summary"] == "Disabled rule 'Flag boss'."


def test_enabling_a_deleting_rule_needs_confirm(harness: UnifiedHarness) -> None:
    _seed_rule(harness, "rule-del", 3, {"permanentDelete": True})
    harness.fake.rules["rule-del"]["isEnabled"] = False
    args = {"action": "set_enabled", "rule_id": "rule-del", "is_enabled": True}
    assert harness.error("email_rule_manage", args) == _confirm_error("deletes")
    data = harness.ok("email_rule_manage", {**args, "confirm": True})
    assert data["summary"] == "Enabled rule 'Rule-Del'."
    # Disabling it stops the deletions, so it needs no confirm.
    harness.ok(
        "email_rule_manage",
        {"action": "set_enabled", "rule_id": "rule-del", "is_enabled": False},
    )


# ----------------------------------------------------------------------
# reorder
# ----------------------------------------------------------------------


@pytest.fixture
def four_rules(harness: UnifiedHarness) -> UnifiedHarness:
    harness.fake.rules.clear()
    for index, rule_id in enumerate(["a", "b", "c", "d"], start=1):
        _seed_rule(harness, rule_id, index)
    return harness


@pytest.mark.parametrize(
    ("rule_id", "position", "relative", "expected"),
    [
        ("c", "top", None, ["c", "a", "b", "d"]),
        ("b", "bottom", None, ["a", "c", "d", "b"]),
        ("c", "up", None, ["a", "c", "b", "d"]),
        ("b", "down", None, ["a", "c", "b", "d"]),
        ("d", "before", "b", ["a", "d", "b", "c"]),
        ("a", "after", "c", ["b", "c", "a", "d"]),
    ],
)
def test_reorder_positions(
    four_rules: UnifiedHarness, rule_id, position, relative, expected
) -> None:
    harness = four_rules
    args: dict[str, Any] = {
        "action": "reorder",
        "rule_id": rule_id,
        "position": position,
    }
    if relative:
        args["relative_to_rule_id"] = relative
    data = harness.ok("email_rule_manage", args)
    assert _order(harness) == expected
    assert _sequences(harness) == [1, 2, 3, 4]
    new_position = expected.index(rule_id) + 1
    assert data["rule"]["sequence"] == new_position
    assert data["summary"] == (
        f"Moved rule '{rule_id.title()}' to position {new_position}."
    )
    assert harness.graph_calls("GET", RULES)
    patched = {c.path.rsplit("/", 1)[-1] for c in harness.graph_calls("PATCH")}
    unchanged = {r for i, r in enumerate(expected) if ["a", "b", "c", "d"][i] == r}
    assert patched == set(expected) - unchanged


def test_reorder_up_at_top_changes_nothing(four_rules: UnifiedHarness) -> None:
    data = four_rules.ok(
        "email_rule_manage", {"action": "reorder", "rule_id": "a", "position": "up"}
    )
    assert data["rule"]["sequence"] == 1
    assert not four_rules.graph_calls("PATCH")


def test_reorder_renumbers_gapped_sequences(harness: UnifiedHarness) -> None:
    harness.fake.rules.clear()
    _seed_rule(harness, "a", 5)
    _seed_rule(harness, "b", 10)
    harness.ok(
        "email_rule_manage", {"action": "reorder", "rule_id": "b", "position": "top"}
    )
    assert _order(harness) == ["b", "a"]
    assert _sequences(harness) == [1, 2]


def test_reorder_unknown_rules(four_rules: UnifiedHarness) -> None:
    text = four_rules.error(
        "email_rule_manage", {"action": "reorder", "rule_id": "zz", "position": "top"}
    )
    assert text == "Invalid rule_id: rule not found"
    text = four_rules.error(
        "email_rule_manage",
        {
            "action": "reorder",
            "rule_id": "a",
            "position": "before",
            "relative_to_rule_id": "zz",
        },
    )
    assert text == "Invalid relative_to_rule_id: rule not found"
    assert not four_rules.graph_calls("PATCH")


def test_rule_manage_uses_normal_rate_limit(
    harness: UnifiedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from m365_mcp.tools.unified import common

    kinds: list[str] = []
    monkeypatch.setattr(common, "check_rate", lambda _a, kind: kinds.append(kind))
    harness.ok(
        "email_rule_manage",
        {"action": "set_enabled", "rule_id": "rule-boss", "is_enabled": True},
    )
    assert kinds == ["normal"]
