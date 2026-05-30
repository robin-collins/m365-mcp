from __future__ import annotations

import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from src.m365_mcp.tools import account as account_tools


def test_account_list_serialises_namedtuple(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure account_list exposes username/account_id/account_type triples."""

    accounts = [
        account_tools.auth.Account(
            username="ada@example.com", account_id="acc-1", account_type="work_school"
        ),
        account_tools.auth.Account(
            username="grace@example.com", account_id="acc-2", account_type="personal"
        ),
    ]
    monkeypatch.setattr(account_tools.auth, "list_accounts", lambda: accounts)

    result = account_tools.account_list.fn()

    assert result == [
        {
            "username": "ada@example.com",
            "account_id": "acc-1",
            "account_type": "work_school",
        },
        {
            "username": "grace@example.com",
            "account_id": "acc-2",
            "account_type": "personal",
        },
    ]


def test_account_authenticate_returns_flow_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify device flow details are surfaced when authentication begins."""

    flow: dict[str, Any] = {
        "user_code": "ABCD-1234",
        "verification_uri": "https://microsoft.com/devicelogin",
        "expires_in": 900,
    }

    class FakeApp:
        def initiate_device_flow(self, scopes: Iterable[str]) -> dict[str, Any]:
            self.scopes = list(scopes)  # type: ignore[attr-defined]
            return flow

    fake_app = FakeApp()
    monkeypatch.setattr(account_tools.auth, "get_app", lambda: (fake_app, "common"))

    result = account_tools.account_authenticate.fn()

    assert result["status"] == "authentication_required"
    assert result["device_code"] == flow["user_code"]
    assert result["verification_url"] == flow["verification_uri"]
    assert result["_flow_cache"] == str(flow)
    assert fake_app.scopes == account_tools.auth.DEVICE_FLOW_SCOPES


def test_device_flow_scopes_request_offline_access() -> None:
    """Device flow must request refresh tokens for silent renewal."""

    assert "offline_access" in account_tools.auth.DEVICE_FLOW_SCOPES


def test_get_token_accepts_username_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Allow tool calls to select cached accounts by username/email."""

    class FakeApp:
        def __init__(self) -> None:
            self.token_cache = object()

        def get_accounts(self) -> list[dict[str, str]]:
            return [
                {
                    "username": "Robin.F.Collins@outlook.com",
                    "home_account_id": "acc-1",
                }
            ]

        def acquire_token_silent(
            self,
            scopes: list[str],
            account: dict[str, str] | None = None,
        ) -> dict[str, str]:
            captured["scopes"] = scopes
            captured["account"] = account
            return {"access_token": "cached-token"}

    captured: dict[str, Any] = {}
    fake_app = FakeApp()

    monkeypatch.setattr(account_tools.auth, "get_app", lambda: (fake_app, "common"))
    monkeypatch.setattr(
        account_tools.auth,
        "_get_account_type",
        lambda account_id, username: "personal",
    )

    token = account_tools.auth.get_token("robin.f.collins@outlook.com")

    assert token == "cached-token"
    assert captured["scopes"] == account_tools.auth.SCOPES
    assert captured["account"] == {
        "username": "Robin.F.Collins@outlook.com",
        "home_account_id": "acc-1",
    }


def test_account_authenticate_raises_when_flow_missing_user_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guard against malformed device flow payloads."""

    class FakeApp:
        pass

    fake_app = FakeApp()

    def fake_initiate_device_flow(
        app: FakeApp,
        tenant_id: str,
    ) -> tuple[FakeApp, dict[str, str]]:
        assert app is fake_app
        assert tenant_id == "common"
        return app, {"error_description": "User code unavailable"}

    monkeypatch.setattr(account_tools.auth, "get_app", lambda: (fake_app, "common"))
    monkeypatch.setattr(
        account_tools.auth,
        "_initiate_device_flow",
        fake_initiate_device_flow,
    )

    with pytest.raises(Exception, match="Failed to get device code"):
        account_tools.account_authenticate.fn()


def test_account_complete_auth_rejects_invalid_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure flow cache must be a literal mapping."""

    monkeypatch.setattr(account_tools.auth, "get_app", lambda: (None, "common"))

    with pytest.raises(ValueError, match="Invalid flow cache"):
        account_tools.account_complete_auth.fn("not-a-dict")


def test_account_complete_auth_returns_pending_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Map authorization_pending responses to a pending status."""

    flow_cache = {"device_code": "ABCD"}

    class FakeApp:
        token_cache = object()

        def acquire_token_by_device_flow(self, flow: dict[str, Any]) -> dict[str, str]:
            self.flow = flow  # type: ignore[attr-defined]
            return {
                "error": "authorization_pending",
                "error_description": "authorization_pending",
            }

        def get_accounts(self) -> list[dict[str, str]]:
            return []

    monkeypatch.setattr(account_tools.auth, "get_app", lambda: (FakeApp(), "common"))

    result = account_tools.account_complete_auth.fn(str(flow_cache))

    assert result["status"] == "pending"
    assert "Authentication is still pending" in result["message"]


def test_account_complete_auth_returns_success_and_writes_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful completion returns matched account details including account type."""

    flow_cache = {"device_code": "EFGH"}

    class FakeCacheBase:
        has_state_changed: bool = True

        def serialize(self) -> str:
            return "base-cache"

    monkeypatch.setattr(
        account_tools.auth.msal,
        "SerializableTokenCache",
        FakeCacheBase,
    )

    @dataclass
    class FakeCache(FakeCacheBase):
        def serialize(self) -> str:
            return "cache"

    class FakeApp:
        def __init__(self) -> None:
            self.token_cache = FakeCache()

        def acquire_token_by_device_flow(self, flow: dict[str, Any]) -> dict[str, Any]:
            return {
                "id_token_claims": {"preferred_username": "ada@example.com"},
                "access_token": "fake-access-token",
            }

        def get_accounts(self) -> list[dict[str, str]]:
            return [
                {"username": "ada@example.com", "home_account_id": "acc-1"},
                {"username": "grace@example.com", "home_account_id": "acc-2"},
            ]

    writes: list[str] = []

    def fake_write_cache(content: str) -> None:
        writes.append(content)

    def fake_get_account_type(account_id: str, username: str) -> str:
        return "work_school"

    monkeypatch.setattr(account_tools.auth, "get_app", lambda: (FakeApp(), "common"))
    monkeypatch.setattr(account_tools.auth, "_write_cache", fake_write_cache)
    monkeypatch.setattr(account_tools.auth, "_get_account_type", fake_get_account_type)

    result = account_tools.account_complete_auth.fn(str(flow_cache))

    assert result == {
        "status": "success",
        "username": "ada@example.com",
        "account_id": "acc-1",
        "account_type": "work_school",
        "message": "Successfully authenticated ada@example.com",
    }
    assert writes == ["cache"]


def test_get_token_fails_fast_when_interactive_auth_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Normal MCP token requests should not start blocking device flow."""

    class FakeApp:
        def get_accounts(self) -> list[dict[str, str]]:
            return []

        def acquire_token_silent(
            self,
            scopes: list[str],
            account: dict[str, str] | None = None,
        ) -> None:
            return None

    def fail_device_flow(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Device flow should not start when interactive auth is disabled")

    monkeypatch.delenv(account_tools.auth.INTERACTIVE_AUTH_ENV_VAR, raising=False)
    monkeypatch.setattr(account_tools.auth, "get_app", lambda: (FakeApp(), "common"))
    monkeypatch.setattr(account_tools.auth, "_initiate_device_flow", fail_device_flow)

    with pytest.raises(RuntimeError, match="uv run authenticate.py"):
        account_tools.auth.get_token()


def test_get_token_allows_device_flow_when_interactive_auth_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Intentional interactive auth can still use device code flow."""
    flow = {"user_code": "ABCD", "verification_uri": "https://example.test/device"}
    calls: list[str] = []

    class FakeApp:
        token_cache = object()

        def get_accounts(self) -> list[dict[str, str]]:
            return [{"username": "ada@example.com", "home_account_id": "acc-1"}]

        def acquire_token_silent(
            self,
            scopes: list[str],
            account: dict[str, str] | None = None,
        ) -> None:
            return None

        def acquire_token_by_device_flow(
            self,
            received_flow: dict[str, str],
        ) -> dict[str, Any]:
            assert received_flow is flow
            calls.append("device_flow")
            return {
                "access_token": "token",
                "id_token_claims": {"preferred_username": "ada@example.com"},
            }

    fake_app = FakeApp()

    def fake_initiate_device_flow(
        app: FakeApp,
        tenant_id: str,
    ) -> tuple[FakeApp, dict[str, str]]:
        assert app is fake_app
        assert tenant_id == "common"
        return app, flow

    monkeypatch.setenv(account_tools.auth.INTERACTIVE_AUTH_ENV_VAR, "true")
    monkeypatch.setattr(account_tools.auth, "get_app", lambda: (fake_app, "common"))
    monkeypatch.setattr(
        account_tools.auth,
        "_initiate_device_flow",
        fake_initiate_device_flow,
    )

    assert account_tools.auth.get_token() == "token"
    assert calls == ["device_flow"]


def test_reauthenticate_account_force_refreshes_and_writes_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--re-auth should exercise MSAL refresh-token renewal."""

    class FakeCacheBase:
        has_state_changed = True

        def serialize(self) -> str:
            return "cache"

    class FakeApp:
        def __init__(self) -> None:
            self.token_cache = FakeCacheBase()

        def get_accounts(self) -> list[dict[str, str]]:
            return [{"username": "ada@example.com", "home_account_id": "acc-1"}]

        def acquire_token_silent_with_error(
            self,
            scopes: list[str],
            account: dict[str, str],
            force_refresh: bool = False,
        ) -> dict[str, Any]:
            captured["scopes"] = scopes
            captured["account"] = account
            captured["force_refresh"] = force_refresh
            return {"access_token": "new-token", "expires_in": 3600}

    captured: dict[str, Any] = {}
    writes: list[str] = []

    monkeypatch.setattr(
        account_tools.auth.msal,
        "SerializableTokenCache",
        FakeCacheBase,
    )
    monkeypatch.setattr(account_tools.auth, "get_app", lambda: (FakeApp(), "common"))
    monkeypatch.setattr(account_tools.auth, "_write_cache", writes.append)
    monkeypatch.setattr(
        account_tools.auth,
        "_get_account_type",
        lambda account_id, username: "work_school",
    )

    result = account_tools.auth.reauthenticate_account("acc-1")

    assert captured["scopes"] == account_tools.auth.SCOPES
    assert captured["account"]["home_account_id"] == "acc-1"
    assert captured["force_refresh"] is True
    assert writes == ["cache"]
    assert result.expires_in == 3600
    assert result.account.account_id == "acc-1"
    assert result.account.account_type == "work_school"


def test_remove_account_clears_tokens_metadata_and_database_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Removing an account should clear every local cache layer."""

    class FakeCacheBase:
        has_state_changed = True

        def serialize(self) -> str:
            return "cache"

    class FakeApp:
        def __init__(self) -> None:
            self.token_cache = FakeCacheBase()

        def get_accounts(self) -> list[dict[str, str]]:
            return [
                {"username": "ada@example.com", "home_account_id": "acc-1"},
                {"username": "grace@example.com", "home_account_id": "acc-2"},
            ]

        def remove_account(self, account: dict[str, str]) -> None:
            removed_accounts.append(account)

    removed_accounts: list[dict[str, str]] = []
    writes: list[str] = []
    metadata_writes: list[dict[str, dict[str, str]]] = []
    metadata = {
        "acc-1": {"account_type": "personal"},
        "acc-2": {"account_type": "work_school"},
    }
    database_counts = {
        "cache_entries": 2,
        "cache_tasks": 1,
        "cache_invalidation": 1,
    }

    monkeypatch.setattr(
        account_tools.auth.msal,
        "SerializableTokenCache",
        FakeCacheBase,
    )
    monkeypatch.setattr(account_tools.auth, "get_app", lambda: (FakeApp(), "common"))
    monkeypatch.setattr(account_tools.auth, "_write_cache", writes.append)
    monkeypatch.setattr(account_tools.auth, "_read_metadata", lambda: metadata.copy())
    monkeypatch.setattr(account_tools.auth, "_write_metadata", metadata_writes.append)
    monkeypatch.setattr(
        account_tools.auth,
        "_remove_account_database_cache",
        lambda account_id: database_counts,
    )

    result = account_tools.auth.remove_account("ada@example.com")

    assert removed_accounts == [
        {"username": "ada@example.com", "home_account_id": "acc-1"}
    ]
    assert writes == ["cache"]
    assert metadata_writes == [{"acc-2": {"account_type": "work_school"}}]
    assert result.account.username == "ada@example.com"
    assert result.account.account_id == "acc-1"
    assert result.account.account_type == "personal"
    assert result.token_cache_removed is True
    assert result.metadata_removed is True
    assert result.database_cache_removed == database_counts


def test_authenticate_script_enables_interactive_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The standalone authentication script should opt into interactive auth."""
    import authenticate

    fake_auth = ModuleType("m365_mcp.auth")

    def fake_list_accounts() -> list[Any]:
        assert os.environ[account_tools.auth.INTERACTIVE_AUTH_ENV_VAR] == "true"
        return []

    fake_auth.list_accounts = fake_list_accounts  # type: ignore[attr-defined]
    fake_package = ModuleType("m365_mcp")
    fake_package.auth = fake_auth  # type: ignore[attr-defined]

    monkeypatch.delenv(account_tools.auth.INTERACTIVE_AUTH_ENV_VAR, raising=False)
    monkeypatch.setenv("M365_MCP_CLIENT_ID", "client-id")
    monkeypatch.setitem(sys.modules, "m365_mcp", fake_package)
    monkeypatch.setitem(sys.modules, "m365_mcp.auth", fake_auth)
    monkeypatch.setattr(
        authenticate,
        "_parse_arguments",
        lambda: SimpleNamespace(env_file=Path("__missing_env__")),
    )
    monkeypatch.setattr("builtins.input", lambda prompt: "n")

    authenticate.main()


def test_authenticate_script_reauth_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The standalone script should route --re-auth to the refresh helper."""
    import authenticate

    account = SimpleNamespace(
        username="ada@example.com",
        account_id="acc-1",
        account_type="personal",
    )
    refresh_result = SimpleNamespace(account=account, expires_in=3600)
    calls: list[str] = []

    fake_auth = ModuleType("m365_mcp.auth")
    fake_auth.list_accounts = lambda: [account]  # type: ignore[attr-defined]

    def fake_reauthenticate_account(account_id: str) -> Any:
        calls.append(account_id)
        return refresh_result

    fake_auth.reauthenticate_account = fake_reauthenticate_account  # type: ignore[attr-defined]
    fake_package = ModuleType("m365_mcp")
    fake_package.auth = fake_auth  # type: ignore[attr-defined]

    monkeypatch.setenv("M365_MCP_CLIENT_ID", "client-id")
    monkeypatch.setitem(sys.modules, "m365_mcp", fake_package)
    monkeypatch.setitem(sys.modules, "m365_mcp.auth", fake_auth)
    monkeypatch.setattr(
        authenticate,
        "_parse_arguments",
        lambda: SimpleNamespace(
            env_file=Path("__missing_env__"),
            re_auth="acc-1",
            remove=None,
            yes=False,
        ),
    )

    assert authenticate.main() == 0
    assert calls == ["acc-1"]


def test_authenticate_script_remove_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The standalone script should route --remove to account removal."""
    import authenticate

    account = SimpleNamespace(
        username="ada@example.com",
        account_id="acc-1",
        account_type="personal",
    )
    remove_result = SimpleNamespace(
        account=account,
        token_cache_removed=True,
        metadata_removed=True,
        database_cache_removed={
            "cache_entries": 3,
            "cache_tasks": 1,
            "cache_invalidation": 1,
        },
    )
    calls: list[str] = []

    fake_auth = ModuleType("m365_mcp.auth")
    fake_auth.list_accounts = lambda: [account]  # type: ignore[attr-defined]

    def fake_remove_account(account_id: str) -> Any:
        calls.append(account_id)
        return remove_result

    fake_auth.remove_account = fake_remove_account  # type: ignore[attr-defined]
    fake_package = ModuleType("m365_mcp")
    fake_package.auth = fake_auth  # type: ignore[attr-defined]

    monkeypatch.setenv("M365_MCP_CLIENT_ID", "client-id")
    monkeypatch.setitem(sys.modules, "m365_mcp", fake_package)
    monkeypatch.setitem(sys.modules, "m365_mcp.auth", fake_auth)
    monkeypatch.setattr(
        authenticate,
        "_parse_arguments",
        lambda: SimpleNamespace(
            env_file=Path("__missing_env__"),
            re_auth=None,
            remove="acc-1",
            yes=True,
        ),
    )

    assert authenticate.main() == 0
    assert calls == ["acc-1"]
