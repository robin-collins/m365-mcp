from __future__ import annotations

import os
import sys
from collections.abc import Iterable
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest
from msal import PublicClientApplication

from src.m365_mcp.services import accounts as account_service


def test_device_flow_scopes_exclude_msal_reserved_scopes() -> None:
    """MSAL adds OIDC scopes internally and rejects them as input."""

    assert "offline_access" not in account_service.auth.DEVICE_FLOW_SCOPES
    assert "openid" not in account_service.auth.DEVICE_FLOW_SCOPES
    assert "profile" not in account_service.auth.DEVICE_FLOW_SCOPES


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

        def acquire_token_silent_with_error(
            self,
            scopes: list[str],
            account: dict[str, str] | None = None,
            force_refresh: bool = False,
        ) -> dict[str, str]:
            captured["scopes"] = scopes
            captured["account"] = account
            return {"access_token": "cached-token"}

    captured: dict[str, Any] = {}
    fake_app = FakeApp()

    monkeypatch.setattr(account_service.auth, "get_app", lambda: (fake_app, "common"))

    token = account_service.auth.get_token("robin.f.collins@outlook.com")

    assert token == "cached-token"
    assert captured["scopes"] == account_service.auth.SCOPES
    assert captured["account"] == {
        "username": "Robin.F.Collins@outlook.com",
        "home_account_id": "acc-1",
    }


def test_get_token_fails_fast_when_interactive_auth_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Normal MCP token requests should not start blocking device flow."""

    class FakeApp:
        def get_accounts(self) -> list[dict[str, str]]:
            return []

        def acquire_token_silent_with_error(
            self,
            scopes: list[str],
            account: dict[str, str] | None = None,
            force_refresh: bool = False,
        ) -> None:
            return None

    def fail_device_flow(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Device flow should not start when interactive auth is disabled")

    monkeypatch.delenv(account_service.auth.INTERACTIVE_AUTH_ENV_VAR, raising=False)
    monkeypatch.setattr(account_service.auth, "get_app", lambda: (FakeApp(), "common"))
    monkeypatch.setattr(account_service.auth, "_initiate_device_flow", fail_device_flow)

    with pytest.raises(RuntimeError, match="uv run authenticate.py"):
        account_service.auth.get_token()


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

        def acquire_token_silent_with_error(
            self,
            scopes: list[str],
            account: dict[str, str] | None = None,
            force_refresh: bool = False,
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

    monkeypatch.setenv(account_service.auth.INTERACTIVE_AUTH_ENV_VAR, "true")
    monkeypatch.setattr(account_service.auth, "get_app", lambda: (fake_app, "common"))
    monkeypatch.setattr(
        account_service.auth,
        "_initiate_device_flow",
        fake_initiate_device_flow,
    )

    assert account_service.auth.get_token() == "token"
    assert calls == ["device_flow"]


class _SilentErrorApp:
    """Fake MSAL app whose silent acquisition returns a fixed result."""

    def __init__(self, result: dict[str, Any] | None) -> None:
        self.result = result
        self.force_refresh: bool | None = None

    def get_accounts(self) -> list[dict[str, str]]:
        return [{"username": "ada@example.com", "home_account_id": "acc-1"}]

    def acquire_token_silent_with_error(
        self,
        scopes: list[str],
        account: dict[str, str] | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any] | None:
        self.force_refresh = force_refresh
        return self.result


def test_get_token_reports_expired_sign_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An expired refresh token should say to sign in again, with the reason."""
    app = _SilentErrorApp(
        {
            "error": "invalid_grant",
            "error_description": "AADSTS70000: The grant is expired.\nTrace ID: x",
        }
    )
    monkeypatch.delenv(account_service.auth.INTERACTIVE_AUTH_ENV_VAR, raising=False)
    monkeypatch.setattr(account_service.auth, "get_app", lambda: (app, "common"))

    with pytest.raises(account_service.auth.SignInRequiredError) as excinfo:
        account_service.auth.get_token("acc-1")

    message = str(excinfo.value)
    assert "ada@example.com" in message
    assert "AADSTS70000" in message
    assert "Trace ID" not in message
    assert "uv run authenticate.py" in message


def test_get_token_transient_error_is_not_sign_in_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Service errors must not tell the user to sign in or start device flow."""
    app = _SilentErrorApp(
        {"error": "temporarily_unavailable", "error_description": "busy"}
    )

    def fail_device_flow(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Device flow should not start for transient errors")

    monkeypatch.setenv(account_service.auth.INTERACTIVE_AUTH_ENV_VAR, "true")
    monkeypatch.setattr(account_service.auth, "get_app", lambda: (app, "common"))
    monkeypatch.setattr(account_service.auth, "_initiate_device_flow", fail_device_flow)

    with pytest.raises(RuntimeError, match="temporarily_unavailable") as excinfo:
        account_service.auth.get_token("acc-1")

    assert not isinstance(excinfo.value, account_service.auth.SignInRequiredError)


def test_get_token_passes_force_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    """force_refresh must reach MSAL so a 401 retry redeems the refresh token."""
    app = _SilentErrorApp({"access_token": "fresh"})
    monkeypatch.setattr(account_service.auth, "get_app", lambda: (app, "common"))

    assert account_service.auth.get_token("acc-1", force_refresh=True) == "fresh"
    assert app.force_refresh is True


def test_build_app_reuses_app_per_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    """MSAL apps are reused because construction performs network discovery."""
    created: list[str] = []

    def fake_app(client_id: str, authority: str, token_cache: Any) -> object:
        created.append(authority)
        return object()

    monkeypatch.setenv("M365_MCP_CLIENT_ID", "client-id")
    monkeypatch.setattr(account_service.auth, "_APPS", {})
    monkeypatch.setattr(account_service.auth, "_get_token_cache", lambda: None)
    monkeypatch.setattr(account_service.auth.msal, "PublicClientApplication", fake_app)

    first = account_service.auth._build_app("common")
    assert account_service.auth._build_app("common") is first
    assert account_service.auth._build_app("consumers") is not first
    assert created == [
        "https://login.microsoftonline.com/common",
        "https://login.microsoftonline.com/consumers",
    ]


def test_reauthenticate_account_reports_expired_sign_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--re-auth distinguishes an expired sign-in from other failures."""
    app = _SilentErrorApp(
        {"error": "invalid_grant", "error_description": "AADSTS70000: expired"}
    )
    monkeypatch.setattr(account_service.auth, "get_app", lambda: (app, "common"))

    with pytest.raises(account_service.auth.SignInRequiredError, match="AADSTS70000"):
        account_service.auth.reauthenticate_account("acc-1")


def test_reauthenticate_account_force_refreshes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--re-auth should exercise MSAL refresh-token renewal."""

    class FakeApp:
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

    monkeypatch.setattr(account_service.auth, "get_app", lambda: (FakeApp(), "common"))

    result = account_service.auth.reauthenticate_account("acc-1")

    assert captured["scopes"] == account_service.auth.SCOPES
    assert captured["account"]["home_account_id"] == "acc-1"
    assert captured["force_refresh"] is True
    assert result.expires_in == 3600
    assert result.account.account_id == "acc-1"


def test_remove_account_clears_tokens_and_database_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Removing an account should clear every local cache layer."""

    class FakeApp:
        def get_accounts(self) -> list[dict[str, str]]:
            return [
                {"username": "ada@example.com", "home_account_id": "acc-1"},
                {"username": "grace@example.com", "home_account_id": "acc-2"},
            ]

        def remove_account(self, account: dict[str, str]) -> None:
            removed_accounts.append(account)

    removed_accounts: list[dict[str, str]] = []
    database_counts = {
        "cache_entries": 2,
        "cache_tasks": 1,
        "cache_invalidation": 1,
    }

    monkeypatch.setattr(account_service.auth, "get_app", lambda: (FakeApp(), "common"))
    monkeypatch.setattr(
        account_service.auth,
        "_remove_account_database_cache",
        lambda account_id: database_counts,
    )

    result = account_service.auth.remove_account("ada@example.com")

    assert removed_accounts == [
        {"username": "ada@example.com", "home_account_id": "acc-1"}
    ]
    assert result.account.username == "ada@example.com"
    assert result.account.account_id == "acc-1"
    assert result.token_cache_removed is True
    assert result.database_cache_removed == database_counts


def test_authenticate_script_enables_interactive_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The standalone authentication script should opt into interactive auth."""
    import authenticate

    fake_auth = ModuleType("m365_mcp.auth")

    def fake_list_accounts() -> list[Any]:
        assert os.environ[account_service.auth.INTERACTIVE_AUTH_ENV_VAR] == "true"
        return []

    fake_auth.list_accounts = fake_list_accounts  # type: ignore[attr-defined]
    fake_package = ModuleType("m365_mcp")
    fake_package.auth = fake_auth  # type: ignore[attr-defined]

    monkeypatch.delenv(account_service.auth.INTERACTIVE_AUTH_ENV_VAR, raising=False)
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
    )
    remove_result = SimpleNamespace(
        account=account,
        token_cache_removed=True,
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


def _install_fake_auth(monkeypatch: pytest.MonkeyPatch, fake_auth: ModuleType) -> None:
    fake_package = ModuleType("m365_mcp")
    fake_package.auth = fake_auth  # type: ignore[attr-defined]
    monkeypatch.setenv("M365_MCP_CLIENT_ID", "client-id")
    monkeypatch.setitem(sys.modules, "m365_mcp", fake_package)
    monkeypatch.setitem(sys.modules, "m365_mcp.auth", fake_auth)


def _expired_account_auth(signed_in: list[str]) -> ModuleType:
    """Fake auth module with one account whose refresh token has expired."""
    account = SimpleNamespace(username="ada@example.com", account_id="acc-1")
    fake_auth = ModuleType("m365_mcp.auth")
    fake_auth.SignInRequiredError = account_service.auth.SignInRequiredError  # type: ignore[attr-defined]
    fake_auth.list_accounts = lambda: [account]  # type: ignore[attr-defined]

    def fake_reauthenticate_account(account_id: str) -> Any:
        if not signed_in:
            raise account_service.auth.SignInRequiredError("grant is expired")
        return SimpleNamespace(account=account, expires_in=3600)

    def fake_authenticate_new_account() -> Any:
        signed_in.append("ada@example.com")
        return account

    fake_auth.reauthenticate_account = fake_reauthenticate_account  # type: ignore[attr-defined]
    fake_auth.authenticate_new_account = fake_authenticate_new_account  # type: ignore[attr-defined]
    return fake_auth


def _run_default_script(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> int:
    import authenticate

    monkeypatch.setattr(
        authenticate,
        "_parse_arguments",
        lambda: SimpleNamespace(
            env_file=Path("__missing_env__"), re_auth=None, remove=None, yes=False
        ),
    )
    replies = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt: next(replies))
    return authenticate.main()


def test_authenticate_script_offers_sign_in_for_expired_account(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An expired account is detected and can be re-signed in directly."""
    signed_in: list[str] = []
    _install_fake_auth(monkeypatch, _expired_account_auth(signed_in))

    # "y" to re-sign-in ada, "n" to adding another account.
    assert _run_default_script(monkeypatch, ["y", "n"]) == 0

    output = capsys.readouterr().out
    assert signed_in == ["ada@example.com"]
    assert "✗ ada@example.com: grant is expired" in output
    assert "[✓ ready]" in output
    assert "Authentication complete!" in output


def test_authenticate_script_does_not_report_success_for_expired_account(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Declining to sign in again must not print a success message."""
    signed_in: list[str] = []
    _install_fake_auth(monkeypatch, _expired_account_auth(signed_in))

    assert _run_default_script(monkeypatch, ["n", "n"]) == 1

    output = capsys.readouterr().out
    assert signed_in == []
    assert "[✗ NOT USABLE]" in output
    assert "Authentication complete!" not in output


def test_authenticate_script_reauth_reports_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--re-auth exits non-zero with a message instead of a traceback."""
    import authenticate

    _install_fake_auth(monkeypatch, _expired_account_auth([]))
    monkeypatch.setattr(
        authenticate,
        "_parse_arguments",
        lambda: SimpleNamespace(
            env_file=Path("__missing_env__"), re_auth="acc-1", remove=None, yes=False
        ),
    )

    assert authenticate.main() == 1
    assert "grant is expired" in capsys.readouterr().out


def test_device_flow_records_issuing_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    """A consumers fallback must be remembered on the flow."""

    class FakeApp:
        def __init__(self, reject: bool) -> None:
            self.reject = reject

        def initiate_device_flow(self, scopes: Iterable[str]) -> dict[str, Any]:
            if self.reject:
                return {"error": "invalid_scope", "error_description": "reserved"}
            return {"user_code": "ABCD", "device_code": "dc"}

    consumer_app = FakeApp(reject=False)
    monkeypatch.setattr(
        account_service.auth, "_build_app", lambda tenant_id: consumer_app
    )

    app, flow = account_service.auth._initiate_device_flow(
        cast(PublicClientApplication, FakeApp(True)), "common"
    )

    assert app is consumer_app
    assert flow[account_service.auth.DEVICE_FLOW_TENANT_KEY] == "consumers"
