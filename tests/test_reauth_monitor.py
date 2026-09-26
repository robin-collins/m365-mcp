"""Tests for the server's weekly re-auth schedule monitor."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from m365_mcp import reauth_schedule as rs
from tests.test_reauth_schedule import NOW, FakeCron


def _scheduler(tmp_path: Path, cron: FakeCron, **cfg: Any) -> rs.Scheduler:
    return rs.Scheduler(
        rs.ScheduleConfig(**cfg),
        rs.CronBackend(run=cron),
        state_path=tmp_path / "state.json",
        clock=lambda: NOW,
    )


class _Stop(Exception):
    pass


async def _run_until_stopped(scheduler: rs.Scheduler, sleeps: int) -> list[float]:
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        if len(slept) >= sleeps:
            raise _Stop

    with pytest.raises(_Stop):
        await rs.monitor(scheduler, sleep=fake_sleep)
    return slept


@pytest.mark.asyncio
async def test_enabled_installs_then_rechecks_on_the_interval(tmp_path: Path) -> None:
    cron = FakeCron()
    scheduler = _scheduler(tmp_path, cron, enabled=True, check_hours=6)
    slept = await _run_until_stopped(scheduler, sleeps=1)
    assert slept == [6 * 3600]
    assert rs.MARKER in cron.table


@pytest.mark.asyncio
async def test_enabled_repairs_a_line_removed_between_checks(tmp_path: Path) -> None:
    cron = FakeCron()
    scheduler = _scheduler(tmp_path, cron, enabled=True)
    calls = 0

    async def fake_sleep(seconds: float) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            cron.table = ""  # someone deleted the job
        else:
            raise _Stop

    with pytest.raises(_Stop):
        await rs.monitor(scheduler, sleep=fake_sleep)
    assert rs.MARKER in cron.table


@pytest.mark.asyncio
async def test_disabled_removes_once_and_stops(tmp_path: Path) -> None:
    cron = FakeCron()
    _scheduler(tmp_path, cron, enabled=True).install()
    await rs.monitor(_scheduler(tmp_path, cron, enabled=False))
    assert rs.MARKER not in cron.table


@pytest.mark.asyncio
async def test_problems_are_logged_as_warnings(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cron = FakeCron()
    scheduler = _scheduler(tmp_path, cron, enabled=True)
    scheduler.install()
    rs.record_run(
        tmp_path / "state.json",
        finished_at=NOW,
        success=False,
        message="Sign in again.",
    )
    with caplog.at_level("WARNING", logger="m365_mcp.reauth_schedule"):
        await _run_until_stopped(scheduler, sleeps=1)
    assert any("Sign in again." in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_unexpected_errors_never_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scheduler = _scheduler(tmp_path, FakeCron(), enabled=True)

    def boom() -> dict[str, Any]:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(scheduler, "reconcile", boom)
    slept = await _run_until_stopped(scheduler, sleeps=2)
    assert len(slept) == 2


@pytest.mark.asyncio
async def test_server_starts_the_monitor_only_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # m365_mcp, not src.m365_mcp: the monkeypatches below must hit the same
    # module objects the server uses, or the real scheduler would run.
    from m365_mcp import server

    monkeypatch.delenv(rs.ENV_ENABLE, raising=False)
    assert server._start_reauth_monitor() is None

    monkeypatch.setenv(rs.ENV_ENABLE, "maybe")
    assert server._start_reauth_monitor() is None  # invalid: logged, not fatal

    started: list[rs.Scheduler] = []

    async def fake_monitor(scheduler: rs.Scheduler) -> None:
        started.append(scheduler)

    monkeypatch.setattr(rs, "monitor", fake_monitor)
    monkeypatch.setenv(rs.ENV_ENABLE, "true")
    task = server._start_reauth_monitor()
    assert task is not None
    await task
    assert started and started[0].cfg.enabled is True
