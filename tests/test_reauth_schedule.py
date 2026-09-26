"""Tests for the weekly re-auth schedule manager (Task Scheduler and cron)."""

from __future__ import annotations

import base64
import json
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from m365_mcp import reauth_schedule as rs

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)  # a Saturday


def _done(stdout: str = "", returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def _grab(pattern: str, text: str) -> str:
    match = re.search(pattern, text)
    assert match is not None, pattern
    return match.group(1)


class FakeCron:
    """A stateful stand-in for the ``crontab`` command."""

    def __init__(self, table: str = "") -> None:
        self.table = table
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], input_text: str | None = None):
        self.calls.append(argv)
        if argv == ["crontab", "-l"]:
            if not self.table:
                return _done("", 1, "no crontab for user")
            return _done(self.table)
        if argv == ["crontab", "-"]:
            assert input_text is not None
            self.table = input_text
            return _done()
        raise AssertionError(argv)


class FakeWindows:
    """A stateful stand-in for the PowerShell ScheduledTasks cmdlets."""

    def __init__(self) -> None:
        self.task: dict[str, Any] | None = None
        self.scripts: list[str] = []
        self.last_run: str | None = None
        self.last_result = 267011

    def __call__(self, argv: list[str], input_text: str | None = None):
        assert argv[0].lower().endswith("powershell.exe") or argv[0] == "powershell"
        encoded = argv[argv.index("-EncodedCommand") + 1]
        script = base64.b64decode(encoded).decode("utf-16-le")
        self.scripts.append(script)
        if "Unregister-ScheduledTask" in script:
            self.task = None
            return _done()
        if "Register-ScheduledTask" in script:
            days = {
                "Monday": 2,
                "Tuesday": 4,
                "Wednesday": 8,
                "Thursday": 16,
                "Friday": 32,
                "Saturday": 64,
                "Sunday": 1,
            }
            day = _grab(r"-DaysOfWeek (\w+)", script)
            at = _grab(r"-At '(\d\d:\d\d)'", script)
            self.task = {
                "installed": True,
                "execute": _grab(r"-Execute '((?:[^']|'')*)'", script).replace(
                    "''", "'"
                ),
                "arguments": _grab(r"-Argument '((?:[^']|'')*)'", script).replace(
                    "''", "'"
                ),
                "days": days[day],
                "start": f"2026-09-27T{at}:00",
            }
            return _done()
        if "Get-ScheduledTask " in script or "Get-ScheduledTask\n" in script:
            if self.task is None:
                return _done(json.dumps({"installed": False}))
            return _done(
                json.dumps(
                    {
                        **self.task,
                        "next_run": "2026-09-27T09:00:00",
                        "last_run": self.last_run,
                        "last_result": self.last_result,
                    }
                )
            )
        raise AssertionError(script)


def _config(**overrides: Any) -> rs.ScheduleConfig:
    base: dict[str, Any] = {"enabled": True}
    base.update(overrides)
    return rs.ScheduleConfig(**base)


def _scheduler(backend, tmp_path: Path, cfg=None, now: datetime = NOW):
    return rs.Scheduler(
        cfg or _config(),
        backend,
        state_path=tmp_path / "state.json",
        clock=lambda: now,
        env_file=None,
    )


# ----------------------------------------------------------------------
# Configuration from the environment
# ----------------------------------------------------------------------


def test_config_defaults_to_not_configured() -> None:
    cfg = rs.ScheduleConfig.from_env({})
    assert cfg.enabled is None
    assert (cfg.day, cfg.time, cfg.task_name) == ("Sunday", "09:00", "M365-MCP-ReAuth")


@pytest.mark.parametrize(
    ("value", "expected"),
    [("true", True), ("TRUE", True), ("1", True), ("false", False), ("0", False)],
)
def test_config_reads_the_enable_flag(value: str, expected: bool) -> None:
    assert rs.ScheduleConfig.from_env({rs.ENV_ENABLE: value}).enabled is expected


def test_config_rejects_an_unrecognised_flag() -> None:
    with pytest.raises(ValueError, match="MCP_WEEKLY_RE_AUTH"):
        rs.ScheduleConfig.from_env({rs.ENV_ENABLE: "maybe"})


def test_config_reads_day_time_and_interval() -> None:
    cfg = rs.ScheduleConfig.from_env(
        {
            rs.ENV_ENABLE: "true",
            rs.ENV_DAY: "friday",
            rs.ENV_TIME: "07:30",
            rs.ENV_CHECK_HOURS: "12",
        }
    )
    assert (cfg.day, cfg.time, cfg.check_hours) == ("Friday", "07:30", 12.0)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        (rs.ENV_DAY, "Someday"),
        (rs.ENV_TIME, "25:00"),
        (rs.ENV_TIME, "9am"),
        (rs.ENV_CHECK_HOURS, "0"),
        (rs.ENV_CHECK_HOURS, "soon"),
    ],
)
def test_config_rejects_bad_values(key: str, value: str) -> None:
    with pytest.raises(ValueError, match=key):
        rs.ScheduleConfig.from_env({rs.ENV_ENABLE: "true", key: value})


# ----------------------------------------------------------------------
# Backend selection
# ----------------------------------------------------------------------


def test_backend_by_platform() -> None:
    assert isinstance(rs.detect_backend(platform="win32"), rs.WindowsBackend)
    assert isinstance(rs.detect_backend(platform="linux"), rs.CronBackend)
    assert isinstance(rs.detect_backend(platform="darwin"), rs.CronBackend)
    assert rs.detect_backend(platform="plan9") is None


def test_job_command_uses_this_interpreter_and_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    command = rs.job_command(env_file)
    assert command[1:3] == ["-m", "m365_mcp.reauth_job"]
    assert command[-2:] == ["--env-file", str(env_file)]
    assert rs.job_command(None)[-1] == "m365_mcp.reauth_job"


# ----------------------------------------------------------------------
# Cron backend
# ----------------------------------------------------------------------


def test_cron_install_writes_one_marked_line_and_keeps_other_entries(
    tmp_path: Path,
) -> None:
    cron = FakeCron("0 1 * * * backup.sh\n")
    scheduler = _scheduler(rs.CronBackend(run=cron), tmp_path)
    result = scheduler.install()
    assert result["changed"] is True
    lines = cron.table.splitlines()
    assert lines[0] == "0 1 * * * backup.sh"
    (entry,) = [line for line in lines if rs.MARKER in line]
    assert entry.startswith("0 9 * * 0 ")  # Sunday 09:00
    assert "m365_mcp.reauth_job" in entry
    assert cron.table.endswith("\n")


def test_cron_install_twice_is_a_no_op(tmp_path: Path) -> None:
    cron = FakeCron()
    scheduler = _scheduler(rs.CronBackend(run=cron), tmp_path)
    scheduler.install()
    before = cron.table
    assert scheduler.install()["changed"] is False
    assert cron.table == before


def test_cron_install_repairs_a_drifted_line(tmp_path: Path) -> None:
    cron = FakeCron()
    scheduler = _scheduler(rs.CronBackend(run=cron), tmp_path)
    scheduler.install()
    cron.table = cron.table.replace("0 9 * * 0", "30 4 * * 3")
    status = scheduler.status()
    assert status["installed"] is True
    assert status["matches_expected"] is False
    assert any("differs" in p for p in status["problems"])
    assert scheduler.install()["changed"] is True
    assert scheduler.status()["matches_expected"] is True


def test_cron_remove_deletes_only_our_line(tmp_path: Path) -> None:
    cron = FakeCron("0 1 * * * backup.sh\n")
    scheduler = _scheduler(rs.CronBackend(run=cron), tmp_path)
    scheduler.install()
    assert scheduler.remove()["changed"] is True
    assert cron.table == "0 1 * * * backup.sh\n"
    assert scheduler.remove()["changed"] is False


def test_cron_reports_schedule_and_next_run(tmp_path: Path) -> None:
    cron = FakeCron()
    scheduler = _scheduler(rs.CronBackend(run=cron), tmp_path)
    scheduler.install()
    status = scheduler.status()
    assert status["backend"] == "cron"
    assert status["schedule"] == {"day": "Sunday", "time": "09:00"}
    assert status["next_run"].startswith("2026-09-27T09:00")


# ----------------------------------------------------------------------
# Windows Task Scheduler backend
# ----------------------------------------------------------------------


def test_windows_install_registers_a_weekly_task(tmp_path: Path) -> None:
    windows = FakeWindows()
    scheduler = _scheduler(
        rs.WindowsBackend(run=windows), tmp_path, _config(day="Friday", time="07:30")
    )
    assert scheduler.install()["changed"] is True
    assert windows.task is not None
    assert windows.task["days"] == 32 and windows.task["start"].endswith("T07:30:00")
    assert "m365_mcp.reauth_job" in windows.task["arguments"]
    status = scheduler.status()
    assert status["backend"] == "windows_task_scheduler"
    assert status["schedule"] == {"day": "Friday", "time": "07:30"}
    assert status["matches_expected"] is True


def test_windows_quotes_are_escaped_in_the_script(tmp_path: Path) -> None:
    windows = FakeWindows()
    env_file = tmp_path / "it's .env"
    scheduler = rs.Scheduler(
        _config(),
        rs.WindowsBackend(run=windows),
        state_path=tmp_path / "s.json",
        clock=lambda: NOW,
        env_file=env_file,
    )
    scheduler.install()
    assert windows.task is not None
    assert str(env_file) in windows.task["arguments"]
    assert scheduler.status()["matches_expected"] is True


def test_windows_remove(tmp_path: Path) -> None:
    windows = FakeWindows()
    scheduler = _scheduler(rs.WindowsBackend(run=windows), tmp_path)
    scheduler.install()
    assert scheduler.remove()["changed"] is True
    assert windows.task is None
    assert scheduler.remove()["changed"] is False


def test_windows_uses_the_scheduler_last_result_when_no_state(tmp_path: Path) -> None:
    windows = FakeWindows()
    scheduler = _scheduler(rs.WindowsBackend(run=windows), tmp_path)
    scheduler.install()
    windows.last_run = "2026-09-24T09:00:00"
    windows.last_result = 1
    status = scheduler.status()
    assert status["last_run"]["success"] is False
    assert any("failed" in p for p in status["problems"])


# ----------------------------------------------------------------------
# Health checks (shared by both backends)
# ----------------------------------------------------------------------


def _installed(tmp_path: Path, now: datetime = NOW) -> rs.Scheduler:
    scheduler = _scheduler(rs.CronBackend(run=FakeCron()), tmp_path, now=now)
    scheduler.install()
    return scheduler


def test_fresh_install_is_healthy_before_its_first_run(tmp_path: Path) -> None:
    status = _installed(tmp_path).status()
    assert status["healthy"] is True and status["problems"] == []
    assert status["last_run"] is None


def test_enabled_but_not_installed_is_a_problem(tmp_path: Path) -> None:
    status = _scheduler(rs.CronBackend(run=FakeCron()), tmp_path).status()
    assert status["installed"] is False and status["healthy"] is False
    assert any("not installed" in p for p in status["problems"])


def test_successful_recent_run_is_healthy(tmp_path: Path) -> None:
    scheduler = _installed(tmp_path)
    rs.record_run(
        tmp_path / "state.json",
        finished_at=NOW - timedelta(days=2),
        success=True,
        message="Refreshed 1 account.",
    )
    status = scheduler.status()
    assert status["healthy"] is True
    assert status["last_run"]["success"] is True


def test_failed_last_run_is_reported_with_its_message(tmp_path: Path) -> None:
    scheduler = _installed(tmp_path)
    rs.record_run(
        tmp_path / "state.json",
        finished_at=NOW - timedelta(days=1),
        success=False,
        message="Sign in again.",
    )
    status = scheduler.status()
    assert status["healthy"] is False
    assert any("Sign in again." in p for p in status["problems"])


def test_overdue_run_is_reported(tmp_path: Path) -> None:
    scheduler = _installed(tmp_path)
    rs.record_run(
        tmp_path / "state.json",
        finished_at=NOW - timedelta(days=20),
        success=True,
        message="ok",
    )
    status = scheduler.status()
    assert any("20 days ago" in p for p in status["problems"])


def test_never_run_after_more_than_a_week_is_reported(tmp_path: Path) -> None:
    cron = FakeCron()
    early = _scheduler(rs.CronBackend(run=cron), tmp_path, now=NOW - timedelta(days=10))
    early.install()
    later = _scheduler(rs.CronBackend(run=cron), tmp_path)
    assert any("has not run" in p for p in later.status()["problems"])


def test_installed_but_not_configured_is_flagged(tmp_path: Path) -> None:
    scheduler = _installed(tmp_path)
    off = _scheduler(scheduler.backend, tmp_path, cfg=rs.ScheduleConfig(enabled=None))
    status = off.status()
    assert status["configured"] is None
    assert any("MCP_WEEKLY_RE_AUTH" in p for p in status["problems"])


def test_unconfigured_and_absent_is_quietly_healthy(tmp_path: Path) -> None:
    off = _scheduler(
        rs.CronBackend(run=FakeCron()), tmp_path, cfg=rs.ScheduleConfig(enabled=None)
    )
    status = off.status()
    assert status["healthy"] is True and status["problems"] == []


def test_unsupported_platform(tmp_path: Path) -> None:
    scheduler = _scheduler(None, tmp_path)
    status = scheduler.status()
    assert status["supported"] is False and status["backend"] == "none"
    assert any("not supported" in p for p in status["problems"])
    with pytest.raises(rs.ScheduleError, match="not supported"):
        scheduler.install()


def test_backend_failure_surfaces_as_schedule_error(tmp_path: Path) -> None:
    def broken(argv, input_text=None):
        return _done("", 2, "crontab: permission denied")

    scheduler = _scheduler(rs.CronBackend(run=broken), tmp_path)
    with pytest.raises(rs.ScheduleError, match="permission denied"):
        scheduler.install()


# ----------------------------------------------------------------------
# Reconcile (startup and periodic checks)
# ----------------------------------------------------------------------


def test_reconcile_installs_when_enabled_and_missing(tmp_path: Path) -> None:
    cron = FakeCron()
    scheduler = _scheduler(rs.CronBackend(run=cron), tmp_path)
    result = scheduler.reconcile()
    assert result["actions"] == ["installed"]
    assert rs.MARKER in cron.table


def test_reconcile_repairs_drift_and_then_settles(tmp_path: Path) -> None:
    cron = FakeCron()
    scheduler = _scheduler(rs.CronBackend(run=cron), tmp_path)
    scheduler.install()
    cron.table = cron.table.replace("0 9 * * 0", "1 1 * * 1")
    assert scheduler.reconcile()["actions"] == ["repaired"]
    assert scheduler.reconcile()["actions"] == []


def test_reconcile_removes_when_explicitly_disabled(tmp_path: Path) -> None:
    cron = FakeCron()
    _scheduler(rs.CronBackend(run=cron), tmp_path).install()
    off = _scheduler(
        rs.CronBackend(run=cron), tmp_path, cfg=rs.ScheduleConfig(enabled=False)
    )
    assert off.reconcile()["actions"] == ["removed"]
    assert rs.MARKER not in cron.table


def test_reconcile_leaves_an_unconfigured_install_alone(tmp_path: Path) -> None:
    cron = FakeCron()
    _scheduler(rs.CronBackend(run=cron), tmp_path).install()
    unset = _scheduler(
        rs.CronBackend(run=cron), tmp_path, cfg=rs.ScheduleConfig(enabled=None)
    )
    assert unset.reconcile()["actions"] == []
    assert rs.MARKER in cron.table


def test_reconcile_reports_failures_instead_of_raising(tmp_path: Path) -> None:
    def broken(argv, input_text=None):
        return _done("", 2, "denied")

    result = _scheduler(rs.CronBackend(run=broken), tmp_path).reconcile()
    assert result["actions"] == []
    assert result["status"]["healthy"] is False
    assert any("denied" in p for p in result["status"]["problems"])


# ----------------------------------------------------------------------
# State file
# ----------------------------------------------------------------------


def test_state_file_round_trip_and_corruption(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    assert rs.read_state(path) == {}
    rs.record_run(path, finished_at=NOW, success=True, message="ok")
    assert rs.read_state(path)["last_run"]["success"] is True
    path.write_text("{not json")
    assert rs.read_state(path) == {}


def test_the_real_scheduler_is_locked_under_pytest() -> None:
    """A test must never register a task or edit the real crontab."""
    import os

    assert os.environ[rs.ENV_LOCK] == "1"
    with pytest.raises(rs.ScheduleError, match="locked"):
        rs._default_run(["crontab", "-l"])
    with pytest.raises(rs.ScheduleError, match="locked"):
        (rs.detect_backend() or pytest.fail("no backend")).read(
            rs.ScheduleConfig(enabled=True)
        )
