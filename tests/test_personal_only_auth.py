"""Tests for personal-only sign-in (task U2.11, concept D1)."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest

from src.m365_mcp import auth

WORK_TENANT = "72f988bf-86f1-41af-91ab-2d7cd011db47"
PERSONAL_ID = f"00000000-0000-0000-1111-222233334444.{auth.PERSONAL_TENANT_ID}"
WORK_ID = f"aaaa-bbbb.{WORK_TENANT}"


class FakeApp:
    """Minimal MSAL app holding one cached account after sign-in."""

    def __init__(self, account: dict[str, str], tid: str | None) -> None:
        self.accounts = [account]
        self.tid = tid
        self.removed: list[dict[str, str]] = []

    def get_accounts(self) -> list[dict[str, str]]:
        return list(self.accounts)

    def remove_account(self, account: dict[str, str]) -> None:
        self.removed.append(account)
        self.accounts.remove(account)

    def result(self) -> dict[str, Any]:
        claims: dict[str, Any] = {
            "preferred_username": self.accounts[0]["username"],
        }
        if self.tid is not None:
            claims["tid"] = self.tid
        return {"access_token": "secret-token", "id_token_claims": claims}

    def acquire_token_by_device_flow(
        self, flow: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        return self.result()


def _work_app() -> FakeApp:
    return FakeApp(
        {"username": "ada@contoso.com", "home_account_id": WORK_ID}, WORK_TENANT
    )


def _personal_app(tid: str | None = auth.PERSONAL_TENANT_ID) -> FakeApp:
    return FakeApp({"username": "ada@outlook.com", "home_account_id": PERSONAL_ID}, tid)


def test_default_authority_is_consumers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("M365_MCP_TENANT_ID", raising=False)
    built: list[str] = []
    monkeypatch.setattr(auth, "_build_app", lambda tenant: built.append(tenant))

    _app, tenant = auth.get_app()

    assert tenant == "consumers"
    assert built == ["consumers"]


def test_env_example_documents_consumers_default() -> None:
    text = (Path(__file__).resolve().parents[1] / ".env.example").read_text(
        encoding="utf-8"
    )

    assert 'defaults to "consumers"' in text
    assert "# M365_MCP_TENANT_ID=consumers" in text


def test_account_type_module_is_removed() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("src.m365_mcp.account_type")


def test_account_has_no_account_type_metadata() -> None:
    assert auth.Account._fields == ("username", "account_id")
    assert not hasattr(auth, "METADATA_FILE")
    assert not hasattr(auth, "_get_account_type")


def test_finish_sign_in_rejects_work_account_and_forgets_it() -> None:
    app = _work_app()

    with pytest.raises(
        auth.PersonalAccountRequiredError,
        match="^Only personal Microsoft accounts are supported",
    ):
        auth.finish_device_flow_sign_in(app, app.result())  # type: ignore[arg-type]

    assert app.removed and app.get_accounts() == []


def test_finish_sign_in_rejects_work_account_by_home_account_id() -> None:
    app = FakeApp({"username": "ada@contoso.com", "home_account_id": WORK_ID}, None)

    with pytest.raises(auth.PersonalAccountRequiredError):
        auth.finish_device_flow_sign_in(app, app.result())  # type: ignore[arg-type]


def test_finish_sign_in_accepts_personal_account() -> None:
    app = _personal_app()

    account = auth.finish_device_flow_sign_in(app, app.result())  # type: ignore[arg-type]

    assert account == auth.Account(username="ada@outlook.com", account_id=PERSONAL_ID)
    assert app.removed == []


def test_finish_sign_in_accepts_personal_account_without_tid_claim() -> None:
    app = _personal_app(tid=None)

    account = auth.finish_device_flow_sign_in(app, app.result())  # type: ignore[arg-type]

    assert account.account_id == PERSONAL_ID


def test_authenticate_new_account_rejects_work_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _work_app()
    monkeypatch.setattr(auth, "get_app", lambda: (app, "consumers"))
    monkeypatch.setattr(
        auth,
        "_initiate_device_flow",
        lambda a, t: (a, {"user_code": "CODE", "device_code": "dc"}),
    )

    with pytest.raises(auth.PersonalAccountRequiredError):
        auth.authenticate_new_account()
