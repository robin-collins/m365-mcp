"""Tests for the account and admin tools (tasks U3.24-U3.29)."""

from __future__ import annotations

import json
from importlib.metadata import version
from typing import Any, NamedTuple

import pytest
from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS

from m365_mcp import auth, auth_sessions, cache
from m365_mcp.tool_specs import load_tool_spec
from m365_mcp.tools import cache_tools
from tests.unified_harness import UnifiedHarness

DEVICE_CODE = "DAQABAAEAAAD--very-secret-device-code"
PERSONAL_ID = f"00000000-0000-0000-1111-222233334444.{auth.PERSONAL_TENANT_ID}"
WORK_TENANT = "72f988bf-86f1-41af-91ab-2d7cd011db47"


def _example(tool: str, index: int = 0) -> dict[str, Any]:
    return load_tool_spec(tool)["examples"][index]


# ----------------------------------------------------------------------
# account_list (U3.24)
# ----------------------------------------------------------------------


class _NamedAccount(NamedTuple):
    username: str
    account_id: str
    display_name: str | None


def test_account_list_returns_signed_in_accounts(harness: UnifiedHarness) -> None:
    result = harness.ok("account_list", {})

    assert result == {
        "accounts": [
            {
                "account_id": harness.account_id,
                "email": harness.account_email,
                "display_name": None,
            }
        ],
        "summary": "1 account signed in.",
    }
    assert not harness.graph_calls()


def test_account_list_spec_example(
    harness: UnifiedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    example = _example("account_list")
    expected = example["output"]["accounts"][0]
    monkeypatch.setattr(
        auth,
        "list_accounts",
        lambda: [
            _NamedAccount(
                expected["email"], expected["account_id"], expected["display_name"]
            )
        ],
    )

    assert harness.ok("account_list", example["input"]) == example["output"]


def test_account_list_counts_several_accounts(
    harness: UnifiedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        auth,
        "list_accounts",
        lambda: [
            auth.Account(username="a@outlook.com", account_id="id-a"),
            auth.Account(username="b@outlook.com", account_id="id-b"),
        ],
    )

    result = harness.ok("account_list", {})

    assert [a["email"] for a in result["accounts"]] == [
        "a@outlook.com",
        "b@outlook.com",
    ]
    assert result["summary"] == "2 accounts signed in."


# ----------------------------------------------------------------------
# account_auth_begin / account_auth_complete (U3.25, U3.26)
# ----------------------------------------------------------------------


class FakeApp:
    """MSAL stand-in whose poll outcome the test sets."""

    def __init__(self) -> None:
        self.outcome: dict[str, Any] = {"error": "authorization_pending"}
        self.accounts: list[dict[str, str]] = []
        self.polls = 0

    def initiate_device_flow(self, scopes: list[str]) -> dict[str, Any]:
        return {
            "user_code": "PMQDYGWPS",
            "device_code": DEVICE_CODE,
            "verification_uri": "https://login.microsoft.com/device",
            "expires_in": 900,
            "interval": 5,
        }

    def acquire_token_by_device_flow(
        self, flow: dict[str, Any], exit_condition: Any = None
    ) -> dict[str, Any]:
        self.polls += 1
        return self.outcome

    def get_accounts(self) -> list[dict[str, str]]:
        return list(self.accounts)

    def remove_account(self, account: dict[str, str]) -> None:
        self.accounts.remove(account)

    def sign_in(self, username: str, home_account_id: str, tid: str) -> None:
        self.accounts = [{"username": username, "home_account_id": home_account_id}]
        self.outcome = {
            "access_token": "secret-access-token",
            "id_token_claims": {"preferred_username": username, "tid": tid},
        }


@pytest.fixture
def msal_app(monkeypatch: pytest.MonkeyPatch) -> FakeApp:
    fake = FakeApp()
    monkeypatch.setattr(auth, "get_app", lambda: (fake, "consumers"))
    monkeypatch.setattr(auth, "_build_app", lambda tenant: fake)
    monkeypatch.setattr(auth_sessions, "store", auth_sessions.AuthSessionStore())
    monkeypatch.setattr(auth_sessions.secrets, "token_urlsafe", lambda n: "91b2")
    return fake


def test_auth_begin_spec_example(harness: UnifiedHarness, msal_app: FakeApp) -> None:
    example = _example("account_auth_begin")

    result = harness.ok("account_auth_begin", example["input"])

    assert result == example["output"]
    assert DEVICE_CODE not in json.dumps(result)


def test_auth_complete_spec_example_pending(
    harness: UnifiedHarness, msal_app: FakeApp
) -> None:
    harness.ok("account_auth_begin", {})
    example = _example("account_auth_complete")

    result = harness.ok("account_auth_complete", example["input"])

    assert result == example["output"]
    assert msal_app.polls == 1


def test_auth_complete_success(harness: UnifiedHarness, msal_app: FakeApp) -> None:
    session = harness.ok("account_auth_begin", {})["auth_session_id"]
    msal_app.sign_in("ada@outlook.com", PERSONAL_ID, auth.PERSONAL_TENANT_ID)

    result = harness.ok("account_auth_complete", {"auth_session_id": session})

    assert result == {
        "status": "success",
        "account": {"account_id": PERSONAL_ID, "email": "ada@outlook.com"},
        "summary": "Signed in ada@outlook.com.",
    }
    assert "secret-access-token" not in json.dumps(result)


def test_rule_unknown_or_expired_session(
    harness: UnifiedHarness, msal_app: FakeApp
) -> None:
    text = harness.error("account_auth_complete", {"auth_session_id": "as_nope"})

    assert text == (
        "Invalid auth_session_id: unknown or expired. "
        "Expected: start again with account_auth_begin"
    )
    assert msal_app.polls == 0


def test_rule_work_accounts_rejected(
    harness: UnifiedHarness, msal_app: FakeApp
) -> None:
    session = harness.ok("account_auth_begin", {})["auth_session_id"]
    msal_app.sign_in("ada@contoso.com", f"oid.{WORK_TENANT}", WORK_TENANT)

    text = harness.error("account_auth_complete", {"auth_session_id": session})

    assert text == "Only personal Microsoft accounts are supported"
    assert msal_app.accounts == []


def test_auth_complete_reports_rejected_sign_in(
    harness: UnifiedHarness, msal_app: FakeApp
) -> None:
    session = harness.ok("account_auth_begin", {})["auth_session_id"]
    msal_app.outcome = {
        "error": "expired_token",
        "error_description": "AADSTS70020: The code has expired.\nTrace ID: x",
    }

    text = harness.error("account_auth_complete", {"auth_session_id": session})

    assert text == (
        "Sign-in failed: AADSTS70020: The code has expired.. "
        "Start again with account_auth_begin."
    )


# ----------------------------------------------------------------------
# admin_cache_get (U3.27)
# ----------------------------------------------------------------------


def _seed_cache(account_id: str, resource: str, count: int) -> None:
    manager = cache.get_cache_manager()
    for n in range(count):
        manager.set_cached(account_id, resource, {"n": n}, {"value": [n]})


def test_cache_get_stats(harness: UnifiedHarness) -> None:
    _seed_cache(harness.account_id, "email", 3)
    _seed_cache(harness.account_id, "event", 1)

    result = harness.ok("admin_cache_get", {"view": "stats"})

    stats = result["stats"]
    assert stats["entry_count"] == 4
    assert stats["total_bytes"] > 0
    assert stats["max_bytes"] > stats["total_bytes"]
    assert stats["by_resource"]["email"]["entry_count"] == 3
    assert stats["by_resource"]["event"]["entry_count"] == 1
    assert result["tasks"] is None and result["warming"] is None
    assert result["summary"].startswith("4 cached entries")


def test_cache_get_tasks_filters_and_limits(harness: UnifiedHarness) -> None:
    manager = cache.get_cache_manager()
    ids = [
        manager.enqueue_task(harness.account_id, "email_list", {"n": n}, priority=3)
        for n in range(3)
    ]
    manager.enqueue_task("other-account", "file_list", {}, priority=5)

    everything = harness.ok("admin_cache_get", {"view": "tasks"})
    mine = harness.ok(
        "admin_cache_get",
        {"view": "tasks", "account_id": harness.account_email, "limit": 2},
    )
    queued = harness.ok("admin_cache_get", {"view": "tasks", "status": "queued"})
    failed = harness.ok("admin_cache_get", {"view": "tasks", "status": "failed"})

    assert len(everything["tasks"]) == 4
    assert len(mine["tasks"]) == 2
    assert {t["task_id"] for t in mine["tasks"]} <= set(ids)
    assert len(queued["tasks"]) == 4
    assert failed["tasks"] == []
    task = mine["tasks"][0]
    assert task["operation"] == "email_list"
    assert task["status"] == "queued"
    assert task["priority"] == 3
    assert task["retry_count"] == 0
    assert task["created_at"] is not None and task["started_at"] is None
    assert everything["stats"] is None and everything["warming"] is None
    assert everything["summary"] == "4 background tasks."


def test_cache_get_one_task(harness: UnifiedHarness) -> None:
    task_id = cache.get_cache_manager().enqueue_task(
        harness.account_id, "email_list", {}
    )

    result = harness.ok("admin_cache_get", {"view": "task", "task_id": task_id})

    assert [t["task_id"] for t in result["tasks"]] == [task_id]
    assert result["summary"] == f"Task {task_id} is queued."


def test_cache_get_unknown_task(harness: UnifiedHarness) -> None:
    text = harness.error("admin_cache_get", {"view": "task", "task_id": "nope"})

    assert text == (
        "Invalid task_id 'nope': no such task. "
        "Expected: a task_id from admin_cache_get view='tasks'"
    )


def test_rule_task_view_requires_task_id(harness: UnifiedHarness) -> None:
    text = harness.error("admin_cache_get", {"view": "task"})

    assert text == "Invalid task_id: required for view='task'"


def test_cache_get_warming_spec_example(harness: UnifiedHarness) -> None:
    example = _example("admin_cache_get")

    assert harness.ok("admin_cache_get", example["input"]) == example["output"]


class _Warmer:
    def get_warming_status(self) -> dict[str, Any]:
        return {
            "is_warming": True,
            "operations_total": 4,
            "operations_completed": 1,
            "operations_skipped": 1,
            "operations_failed": 0,
            "progress_percent": 25.0,
            "started_at": "2026-09-26T00:00:00+00:00",
        }


def test_cache_get_warming_in_progress(
    harness: UnifiedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cache_tools, "_warming_status_provider", _Warmer())

    result = harness.ok("admin_cache_get", {"view": "warming"})

    assert result["warming"] == {
        "status": "warming",
        "is_warming": True,
        "operations_total": 4,
        "operations_completed": 1,
        "operations_skipped": 1,
        "operations_failed": 0,
        "progress_percent": 25.0,
    }
    assert result["summary"] == "Cache warming in progress: 25.0% (1 of 4)."


# ----------------------------------------------------------------------
# admin_cache_invalidate (U3.28)
# ----------------------------------------------------------------------


def test_cache_invalidate_spec_example(harness: UnifiedHarness) -> None:
    _seed_cache(harness.account_id, "email", 12)
    _seed_cache(harness.account_id, "event", 2)
    example = _example("admin_cache_invalidate")

    result = harness.ok("admin_cache_invalidate", example["input"])

    assert result == example["output"]
    stats = cache.get_cache_manager().get_stats()
    assert stats["entry_count"] == 2


def test_cache_invalidate_all_for_one_account(harness: UnifiedHarness) -> None:
    _seed_cache(harness.account_id, "email", 2)
    _seed_cache(harness.account_id, "drive_item", 1)
    _seed_cache("other-account", "email", 1)

    result = harness.ok(
        "admin_cache_invalidate",
        {"scope": "all", "account_id": harness.account_email},
    )

    assert result == {
        "scope": "all",
        "entries_removed": 3,
        "summary": "Removed 3 cached entries.",
    }
    assert cache.get_cache_manager().get_stats()["entry_count"] == 1


def test_cache_invalidate_single_entry_wording(harness: UnifiedHarness) -> None:
    _seed_cache(harness.account_id, "contact", 1)

    result = harness.ok("admin_cache_invalidate", {"scope": "contact"})

    assert result["summary"] == "Removed 1 cached contact entry."


# ----------------------------------------------------------------------
# admin_server_info (U3.29)
# ----------------------------------------------------------------------


def test_server_info_reports_running_configuration(harness: UnifiedHarness) -> None:
    result = harness.ok("admin_server_info", {})

    pkg_version = version("m365-mcp")
    assert result == {
        "version": pkg_version,
        "protocol_versions": list(SUPPORTED_PROTOCOL_VERSIONS),
        "toolsets_enabled": ["core", "extended", "admin"],
        "tool_count": 29,
        "cache_enabled": True,
        "summary": f"m365-mcp {pkg_version}, 29 tools.",
    }


def test_server_info_follows_toolsets_env(
    harness: UnifiedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("M365_MCP_TOOLSETS", "admin,core")

    result = harness.ok("admin_server_info", {})

    assert result["toolsets_enabled"] == ["core", "admin"]
    assert result["tool_count"] == 22


def test_server_info_spec_example_shape(harness: UnifiedHarness) -> None:
    example = _example("admin_server_info")

    result = harness.ok("admin_server_info", example["input"])

    assert set(result) == set(example["output"])
    for key in ("toolsets_enabled", "tool_count", "cache_enabled"):
        assert result[key] == example["output"][key]
    assert example["output"]["protocol_versions"][0] in result["protocol_versions"]
