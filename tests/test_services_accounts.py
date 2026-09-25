"""Unit tests for the account service layer."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pytest

from src.m365_mcp.services import accounts


def test_list_accounts_shapes_auth_accounts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Auth accounts become dicts whose legacy account_type is personal."""

    monkeypatch.setattr(
        accounts.auth,
        "list_accounts",
        lambda: [accounts.auth.Account(username="ada@example.com", account_id="acc-1")],
    )

    assert accounts.list_accounts() == [
        {
            "username": "ada@example.com",
            "account_id": "acc-1",
            "account_type": "personal",
        }
    ]


def test_begin_device_flow_returns_instructions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Device flow details and the flow cache are returned to the caller."""

    flow: dict[str, Any] = {"user_code": "ABCD-1234", "expires_in": 600}

    class FakeApp:
        def initiate_device_flow(self, scopes: Iterable[str]) -> dict[str, Any]:
            return flow

    monkeypatch.setattr(accounts.auth, "get_app", lambda: (FakeApp(), "common"))

    result = accounts.begin_device_flow()

    assert result["status"] == "authentication_required"
    assert result["device_code"] == "ABCD-1234"
    assert result["verification_url"] == "https://microsoft.com/devicelogin"
    assert result["expires_in"] == 600
    assert result["_flow_cache"] == str(flow)


def test_begin_device_flow_raises_without_user_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A flow without a user code raises with the MSAL error description."""

    monkeypatch.setattr(accounts.auth, "get_app", lambda: (object(), "common"))
    monkeypatch.setattr(
        accounts.auth,
        "_initiate_device_flow",
        lambda app, tenant_id: (app, {"error_description": "nope"}),
    )

    with pytest.raises(Exception, match="Failed to get device code: nope"):
        accounts.begin_device_flow()


def test_complete_device_flow_uses_flow_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The flow's recorded tenant is used to redeem the device code."""

    built: list[str] = []

    class FakeApp:
        def acquire_token_by_device_flow(
            self, flow: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            return {
                "id_token_claims": {
                    "preferred_username": "x@example.com",
                    "tid": accounts.auth.PERSONAL_TENANT_ID,
                }
            }

        def get_accounts(self) -> list[dict[str, str]]:
            return [{"username": "other@example.com", "home_account_id": "acc-9"}]

    def fake_build_app(tenant_id: str) -> FakeApp:
        built.append(tenant_id)
        return FakeApp()

    monkeypatch.setattr(accounts.auth, "_build_app", fake_build_app)
    flow_cache = {"device_code": "X", accounts.auth.DEVICE_FLOW_TENANT_KEY: "consumers"}

    result = accounts.complete_device_flow(str(flow_cache))

    assert built == ["consumers"]
    assert result["status"] == "success"
    assert result["account_id"] == "acc-9"
    assert result["account_type"] == "personal"


def test_complete_device_flow_reports_missing_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A token without any cached account yields an error status."""

    class FakeApp:
        def acquire_token_by_device_flow(
            self, flow: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            return {"access_token": "t"}

        def get_accounts(self) -> list[dict[str, str]]:
            return []

    monkeypatch.setattr(accounts.auth, "get_app", lambda: (FakeApp(), "common"))

    assert accounts.complete_device_flow(str({"device_code": "X"})) == {
        "status": "error",
        "message": "Authentication succeeded but no account was found",
    }


def test_complete_device_flow_rejects_invalid_cache() -> None:
    """Non-literal flow cache data raises ValueError."""

    with pytest.raises(ValueError, match="Invalid flow cache data"):
        accounts.complete_device_flow("not-a-dict")
