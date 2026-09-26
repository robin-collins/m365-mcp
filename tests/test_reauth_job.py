"""Tests for the scheduled re-auth job (``python -m m365_mcp.reauth_job``)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from m365_mcp import auth, reauth_job, reauth_schedule

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


def _account(email: str) -> auth.Account:
    return auth.Account(username=email, account_id=f"id-{email}")


@pytest.fixture
def state(tmp_path: Path) -> Path:
    return tmp_path / "state.json"


def test_refreshes_every_account_and_records_success(
    monkeypatch: pytest.MonkeyPatch, state: Path
) -> None:
    refreshed: list[str] = []
    monkeypatch.setattr(
        auth,
        "list_accounts",
        lambda: [_account("a@outlook.com"), _account("b@live.com")],
    )
    monkeypatch.setattr(
        auth,
        "reauthenticate_account",
        lambda account_id: refreshed.append(account_id),
    )
    ok, message = reauth_job.run_job(state_path=state, clock=lambda: NOW)
    assert ok is True and message == "Refreshed 2 accounts."
    assert refreshed == ["id-a@outlook.com", "id-b@live.com"]
    recorded = reauth_schedule.read_state(state)["last_run"]
    assert recorded == {
        "finished_at": NOW.isoformat(),
        "success": True,
        "message": "Refreshed 2 accounts.",
    }


def test_one_failure_fails_the_run_but_refreshes_the_rest(
    monkeypatch: pytest.MonkeyPatch, state: Path
) -> None:
    refreshed: list[str] = []

    def reauth(account_id: str) -> None:
        if account_id == "id-a@outlook.com":
            raise auth.SignInRequiredError("Sign in again for a@outlook.com.")
        refreshed.append(account_id)

    monkeypatch.setattr(
        auth,
        "list_accounts",
        lambda: [_account("a@outlook.com"), _account("b@live.com")],
    )
    monkeypatch.setattr(auth, "reauthenticate_account", reauth)
    ok, message = reauth_job.run_job(state_path=state, clock=lambda: NOW)
    assert ok is False
    assert "a@outlook.com" in message and "Sign in again" in message
    assert refreshed == ["id-b@live.com"]
    assert reauth_schedule.read_state(state)["last_run"]["success"] is False


def test_no_accounts_is_a_failure(monkeypatch: pytest.MonkeyPatch, state: Path) -> None:
    monkeypatch.setattr(auth, "list_accounts", list)
    ok, message = reauth_job.run_job(state_path=state, clock=lambda: NOW)
    assert ok is False and "No Microsoft account is signed in" in message


def test_unexpected_errors_are_recorded_not_raised(
    monkeypatch: pytest.MonkeyPatch, state: Path
) -> None:
    def boom() -> list[auth.Account]:
        raise OSError("token cache locked")

    monkeypatch.setattr(auth, "list_accounts", boom)
    ok, message = reauth_job.run_job(state_path=state, clock=lambda: NOW)
    assert ok is False and "token cache locked" in message
    assert reauth_schedule.read_state(state)["last_run"]["success"] is False


def test_main_exit_code(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(reauth_job, "run_job", lambda **_: (True, "ok"))
    monkeypatch.setattr(reauth_job, "_configure_logging", lambda: None)
    assert reauth_job.main([]) == 0
    monkeypatch.setattr(reauth_job, "run_job", lambda **_: (False, "bad"))
    assert reauth_job.main([]) == 1


def test_main_loads_the_env_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("M365_MCP_REAUTH_TEST_VALUE=loaded\n")
    monkeypatch.delenv("M365_MCP_REAUTH_TEST_VALUE", raising=False)
    monkeypatch.setattr(reauth_job, "run_job", lambda **_: (True, "ok"))
    monkeypatch.setattr(reauth_job, "_configure_logging", lambda: None)
    reauth_job.main(["--env-file", str(env_file)])
    import os

    assert os.environ["M365_MCP_REAUTH_TEST_VALUE"] == "loaded"
    monkeypatch.delenv("M365_MCP_REAUTH_TEST_VALUE", raising=False)
