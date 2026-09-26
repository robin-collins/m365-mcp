"""Tests for the ``admin_reauth_schedule`` tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from m365_mcp import reauth_schedule as rs
from tests.test_reauth_schedule import NOW, FakeCron
from tests.unified_harness import UnifiedHarness


@pytest.fixture
def cron(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeCron:
    """Point the tool at a fake crontab and a temporary state file."""
    fake = FakeCron()

    def build(cls: type[rs.Scheduler]) -> rs.Scheduler:
        return cls(
            rs.ScheduleConfig.from_env(),
            rs.CronBackend(run=fake),
            state_path=tmp_path / "state.json",
            clock=lambda: NOW,
        )

    monkeypatch.setattr(rs.Scheduler, "from_environment", classmethod(build))
    return fake


CONFIRM_TEXT = (
    "Invalid confirm 'False': {what} the schedule requires confirm=True to "
    "proceed. Expected: Explicit user confirmation"
)


@pytest.mark.parametrize(
    ("action", "what"), [("install", "installing"), ("remove", "removing")]
)
def test_changes_need_confirm(
    harness: UnifiedHarness, cron: FakeCron, action: str, what: str
) -> None:
    text = harness.error("admin_reauth_schedule", {"action": action})
    assert CONFIRM_TEXT.format(what=what) in text
    assert cron.table == "" and cron.calls == []


def test_status_needs_no_confirm_and_reports_not_installed(
    harness: UnifiedHarness, cron: FakeCron, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(rs.ENV_ENABLE, "true")
    result = harness.ok("admin_reauth_schedule", {"action": "status"})
    assert result["action"] == "status" and result["changed"] is False
    assert result["installed"] is False and result["healthy"] is False
    assert result["configured"] is True and result["backend"] == "cron"
    assert result["summary"].startswith("Weekly re-auth is not installed.")


def test_install_then_status_then_remove(
    harness: UnifiedHarness, cron: FakeCron, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(rs.ENV_ENABLE, "true")
    monkeypatch.setenv(rs.ENV_DAY, "Friday")
    monkeypatch.setenv(rs.ENV_TIME, "07:30")

    installed = harness.ok(
        "admin_reauth_schedule", {"action": "install", "confirm": True}
    )
    assert installed["changed"] is True and installed["installed"] is True
    assert installed["schedule"] == {"day": "Friday", "time": "07:30"}
    assert installed["summary"] == "Installed the weekly re-auth job (Friday 07:30)."
    assert "30 7 * * 5" in cron.table

    again = harness.ok("admin_reauth_schedule", {"action": "install", "confirm": True})
    assert again["changed"] is False
    assert "already installed and correct" in again["summary"]

    status = harness.ok("admin_reauth_schedule", {"action": "status"})
    assert status["healthy"] is True and status["problems"] == []
    assert (
        status["summary"] == "Weekly re-auth is installed (Friday 07:30) and healthy."
    )

    removed = harness.ok("admin_reauth_schedule", {"action": "remove", "confirm": True})
    assert removed["changed"] is True and removed["installed"] is False
    assert removed["summary"] == "Removed the weekly re-auth job."
    assert rs.MARKER not in cron.table

    nothing = harness.ok("admin_reauth_schedule", {"action": "remove", "confirm": True})
    assert nothing["summary"] == "No weekly re-auth job was installed."


def test_install_without_the_env_var_says_how_to_keep_it(
    harness: UnifiedHarness, cron: FakeCron, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(rs.ENV_ENABLE, raising=False)
    result = harness.ok("admin_reauth_schedule", {"action": "install", "confirm": True})
    assert "Set MCP_WEEKLY_RE_AUTH=true" in result["summary"]
    assert result["configured"] is None


def test_status_reports_problems(
    harness: UnifiedHarness,
    cron: FakeCron,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(rs.ENV_ENABLE, "true")
    harness.ok("admin_reauth_schedule", {"action": "install", "confirm": True})
    rs.record_run(
        tmp_path / "state.json",
        finished_at=NOW,
        success=False,
        message="Sign in again.",
    )
    result = harness.ok("admin_reauth_schedule", {"action": "status"})
    assert result["healthy"] is False
    assert result["last_run"]["success"] is False
    assert "Sign in again." in result["problems"][0]
    assert result["summary"].startswith(
        "Weekly re-auth is installed (Sunday 09:00) with 1 problem"
    )


def test_invalid_configuration_is_reported(
    harness: UnifiedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(rs.ENV_ENABLE, "maybe")
    text = harness.error("admin_reauth_schedule", {"action": "status"})
    assert "MCP_WEEKLY_RE_AUTH must be true or false" in text


def test_scheduler_failure_is_reported(
    harness: UnifiedHarness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def broken(argv, input_text=None):
        import subprocess

        return subprocess.CompletedProcess(argv, 2, "", "crontab: permission denied")

    def build(cls: type[rs.Scheduler]) -> rs.Scheduler:
        return cls(
            rs.ScheduleConfig(enabled=True),
            rs.CronBackend(run=broken),
            state_path=tmp_path / "s.json",
        )

    monkeypatch.setattr(rs.Scheduler, "from_environment", classmethod(build))
    text = harness.error(
        "admin_reauth_schedule", {"action": "install", "confirm": True}
    )
    assert "permission denied" in text


def test_spec_examples_match_the_handler_shape(
    harness: UnifiedHarness, cron: FakeCron, monkeypatch: pytest.MonkeyPatch
) -> None:
    from m365_mcp.tool_specs import load_tool_spec

    monkeypatch.setenv(rs.ENV_ENABLE, "true")
    result = harness.ok("admin_reauth_schedule", {"action": "status"})
    for example in load_tool_spec("admin_reauth_schedule")["examples"]:
        assert set(result) == set(example["output"])
