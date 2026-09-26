"""Tests for the server-side device-flow session store (task U2.11)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.m365_mcp import auth, auth_sessions
from src.m365_mcp.validators import ValidationError

PERSONAL_ID = f"00000000-0000-0000-1111-222233334444.{auth.PERSONAL_TENANT_ID}"
WORK_TENANT = "72f988bf-86f1-41af-91ab-2d7cd011db47"
DEVICE_CODE = "DAQABAAEAAAD--very-secret-device-code"
EXPIRED_MESSAGE = (
    "Invalid auth_session_id: unknown or expired. "
    "Expected: start again with account_auth_begin"
)


class Clock:
    """Injectable clock advanced by the tests."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakeApp:
    """MSAL stand-in whose poll outcome the test sets."""

    def __init__(self) -> None:
        self.outcome: dict[str, Any] = {"error": "authorization_pending"}
        self.accounts: list[dict[str, str]] = []
        self.polls: list[dict[str, Any]] = []
        self.exit_conditions: list[Any] = []

    def initiate_device_flow(self, scopes: list[str]) -> dict[str, Any]:
        return {
            "user_code": "PMQDYGWPS",
            "device_code": DEVICE_CODE,
            "verification_uri": "https://login.microsoft.com/device",
            "expires_in": 900,
            "interval": 5,
            "message": f"enter PMQDYGWPS ({DEVICE_CODE})",
        }

    def acquire_token_by_device_flow(
        self, flow: dict[str, Any], exit_condition: Any = None
    ) -> dict[str, Any]:
        self.polls.append(flow)
        self.exit_conditions.append(exit_condition)
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
def app(monkeypatch: pytest.MonkeyPatch) -> FakeApp:
    fake = FakeApp()
    monkeypatch.setattr(auth, "get_app", lambda: (fake, "consumers"))
    monkeypatch.setattr(auth, "_build_app", lambda tenant: fake)
    return fake


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(clock: Clock) -> auth_sessions.AuthSessionStore:
    return auth_sessions.AuthSessionStore(clock=clock)


def test_begin_returns_only_public_fields(app: FakeApp, store) -> None:
    started = store.begin()

    assert set(started) == {
        "auth_session_id",
        "verification_url",
        "user_code",
        "expires_in",
    }
    assert started["user_code"] == "PMQDYGWPS"
    assert started["verification_url"] == "https://login.microsoft.com/device"
    assert started["expires_in"] == 900
    assert DEVICE_CODE not in json.dumps(started)


def test_session_ids_are_opaque_and_unique(app: FakeApp, store) -> None:
    first = store.begin()["auth_session_id"]
    second = store.begin()["auth_session_id"]

    assert first != second
    assert first.startswith("as_") and len(first) >= 24
    assert DEVICE_CODE not in first and "PMQDYGWPS" not in first


def test_complete_pending_polls_once_without_blocking(app: FakeApp, store) -> None:
    session_id = store.begin()["auth_session_id"]

    result = store.complete(session_id)

    assert result == {"status": "pending", "account": None}
    assert len(app.polls) == 1
    assert app.exit_conditions[0] is not None
    assert app.exit_conditions[0](app.polls[0]) is True
    assert DEVICE_CODE not in json.dumps(result)


def test_complete_success_returns_account_and_is_single_use(
    app: FakeApp, store
) -> None:
    session_id = store.begin()["auth_session_id"]
    app.sign_in("ada@outlook.com", PERSONAL_ID, auth.PERSONAL_TENANT_ID)

    result = store.complete(session_id)

    assert result == {
        "status": "success",
        "account": {"account_id": PERSONAL_ID, "email": "ada@outlook.com"},
    }
    serialised = json.dumps(result)
    assert DEVICE_CODE not in serialised and "secret-access-token" not in serialised

    with pytest.raises(ValidationError) as excinfo:
        store.complete(session_id)
    assert str(excinfo.value) == EXPIRED_MESSAGE


def test_complete_rejects_work_account(app: FakeApp, store) -> None:
    session_id = store.begin()["auth_session_id"]
    app.sign_in("ada@contoso.com", f"oid.{WORK_TENANT}", WORK_TENANT)

    with pytest.raises(
        auth.PersonalAccountRequiredError,
        match="^Only personal Microsoft accounts are supported",
    ):
        store.complete(session_id)

    assert app.get_accounts() == []
    with pytest.raises(ValidationError):
        store.complete(session_id)


def test_session_expires_after_fifteen_minutes(
    app: FakeApp, store, clock: Clock
) -> None:
    session_id = store.begin()["auth_session_id"]

    clock.now += 15 * 60 - 1
    assert store.complete(session_id)["status"] == "pending"

    clock.now += 1
    with pytest.raises(ValidationError) as excinfo:
        store.complete(session_id)
    assert str(excinfo.value) == EXPIRED_MESSAGE
    assert len(app.polls) == 1


def test_unknown_session_is_rejected(app: FakeApp, store) -> None:
    with pytest.raises(ValidationError) as excinfo:
        store.complete("as_made_up")

    assert str(excinfo.value) == EXPIRED_MESSAGE
    assert app.polls == []


def test_msal_error_ends_session_without_leaking_flow(app: FakeApp, store) -> None:
    session_id = store.begin()["auth_session_id"]
    app.outcome = {"error": "expired_token", "error_description": "Code expired"}

    with pytest.raises(RuntimeError) as excinfo:
        store.complete(session_id)

    assert "Code expired" in str(excinfo.value)
    assert DEVICE_CODE not in str(excinfo.value)
    with pytest.raises(ValidationError):
        store.complete(session_id)


def test_expired_sessions_are_purged(app: FakeApp, store, clock: Clock) -> None:
    store.begin()
    clock.now += 15 * 60

    store.begin()

    assert len(store) == 1


def test_default_store_exists() -> None:
    assert isinstance(auth_sessions.store, auth_sessions.AuthSessionStore)
    assert auth_sessions.SESSION_TTL_SECONDS == 900
