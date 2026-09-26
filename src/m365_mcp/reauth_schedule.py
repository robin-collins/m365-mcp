"""Weekly re-authentication schedule (Windows Task Scheduler or cron).

A personal account's refresh token expires after 90 days without use. This
module installs, removes and health-checks a weekly job that runs
``python -m m365_mcp.reauth_job`` (a forced token refresh for every
signed-in account), so the token never goes stale.

It never imports FastMCP. ``Scheduler`` is the facade used by the server
(startup and periodic checks) and by the ``admin_reauth_schedule`` tool.

Configuration (environment):

- ``MCP_WEEKLY_RE_AUTH``: ``true`` keeps the job installed and repaired,
  ``false`` removes it, unset leaves any existing job alone.
- ``MCP_RE_AUTH_DAY`` (default ``Sunday``) and ``MCP_RE_AUTH_TIME``
  (default ``09:00``, 24-hour local time).
- ``MCP_RE_AUTH_CHECK_HOURS`` (default ``6``): interval of the server's
  background health check.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import shlex
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

ENV_ENABLE = "MCP_WEEKLY_RE_AUTH"
ENV_DAY = "MCP_RE_AUTH_DAY"
ENV_TIME = "MCP_RE_AUTH_TIME"
ENV_CHECK_HOURS = "MCP_RE_AUTH_CHECK_HOURS"
ENV_ENV_FILE = "M365_MCP_ENV_FILE"
# Set to 1 (the test suite does) to make every real scheduler command fail,
# so nothing can register a task or edit the crontab by accident.
ENV_LOCK = "M365_MCP_SCHEDULER_LOCKED"

TASK_NAME = "M365-MCP-ReAuth"
MARKER = "m365-mcp-reauth"
DAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
# A weekly job that has not finished within this long has been missed.
OVERDUE_AFTER = timedelta(days=8)
STATE_PATH = Path.home() / ".m365_mcp_reauth_state.json"
LOG_PATH = Path.home() / ".m365_mcp_reauth.log"

_TRUE = {"true", "1", "yes", "on"}
_FALSE = {"false", "0", "no", "off"}
_WINDOWS_DAY_BITS = {
    "Sunday": 1,
    "Monday": 2,
    "Tuesday": 4,
    "Wednesday": 8,
    "Thursday": 16,
    "Friday": 32,
    "Saturday": 64,
}
_TIME = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")

Runner = Callable[[list[str], str | None], "subprocess.CompletedProcess[str]"]


class ScheduleError(RuntimeError):
    """Raised when the operating-system scheduler cannot be used."""


@dataclass(frozen=True)
class ScheduleConfig:
    """What the operator wants, read from the environment.

    Attributes:
        enabled: ``True`` install and repair, ``False`` remove, ``None``
            not configured (leave things as they are).
        day: Day of the week the job runs.
        time: ``HH:MM`` local time the job runs.
        task_name: Task Scheduler task name.
        check_hours: Interval of the server's background health check.
    """

    enabled: bool | None
    day: str = "Sunday"
    time: str = "09:00"
    task_name: str = TASK_NAME
    check_hours: float = 6.0

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ScheduleConfig:
        """Read and validate the configuration.

        Args:
            env: Environment mapping; defaults to ``os.environ``.

        Returns:
            The parsed configuration.

        Raises:
            ValueError: If a variable holds an unusable value; the message
                names the variable.
        """
        env = os.environ if env is None else env
        raw = env.get(ENV_ENABLE, "").strip().lower()
        if not raw:
            enabled = None
        elif raw in _TRUE:
            enabled = True
        elif raw in _FALSE:
            enabled = False
        else:
            raise ValueError(f"{ENV_ENABLE} must be true or false, not '{raw}'")

        day = env.get(ENV_DAY, "Sunday").strip().capitalize()
        if day not in DAYS:
            raise ValueError(f"{ENV_DAY} must be a day of the week, not '{day}'")
        time = env.get(ENV_TIME, "09:00").strip()
        if not _TIME.fullmatch(time):
            raise ValueError(f"{ENV_TIME} must be HH:MM (24-hour), not '{time}'")
        raw_hours = env.get(ENV_CHECK_HOURS, "6").strip()
        try:
            hours = float(raw_hours)
        except ValueError:
            hours = 0.0
        if hours <= 0:
            raise ValueError(
                f"{ENV_CHECK_HOURS} must be a positive number of hours, "
                f"not '{raw_hours}'"
            )
        return cls(enabled=enabled, day=day, time=time, check_hours=hours)


# ----------------------------------------------------------------------
# State file (written by the install and by the job)
# ----------------------------------------------------------------------


def read_state(path: Path = STATE_PATH) -> dict[str, Any]:
    """Return the saved state, or ``{}`` if missing or unreadable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(path: Path, state: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def record_run(
    path: Path, *, finished_at: datetime, success: bool, message: str
) -> None:
    """Record the outcome of a job run.

    Args:
        path: State file.
        finished_at: When the run finished (timezone-aware).
        success: Whether every account refreshed.
        message: One-line outcome shown by the status check.
    """
    state = read_state(path)
    state["last_run"] = {
        "finished_at": finished_at.isoformat(),
        "success": success,
        "message": message,
    }
    _write_state(path, state)


# ----------------------------------------------------------------------
# Backends
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Installed:
    """A job as the operating-system scheduler reports it."""

    command: str
    day: str
    time: str
    next_run: datetime | None = None
    last_run: datetime | None = None
    last_result: int | None = None


class Backend(Protocol):
    """An operating-system scheduler."""

    name: str
    run: Runner

    def expected_command(self, command: list[str]) -> str: ...

    def read(self, cfg: ScheduleConfig) -> Installed | None: ...

    def install(self, cfg: ScheduleConfig, command: list[str]) -> None: ...

    def remove(self, cfg: ScheduleConfig) -> bool: ...


def _default_run(
    argv: list[str], input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    if os.environ.get(ENV_LOCK) == "1":
        raise ScheduleError(
            f"refusing to run {argv[0]}: the scheduler is locked ({ENV_LOCK}=1)"
        )
    try:
        return subprocess.run(
            argv,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ScheduleError(f"could not run {argv[0]}: {exc}") from exc


def _fail(what: str, proc: subprocess.CompletedProcess[str]) -> ScheduleError:
    detail = (
        proc.stderr or proc.stdout or ""
    ).strip() or f"exit code {proc.returncode}"
    return ScheduleError(f"{what}: {detail}")


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class WindowsBackend:
    """Windows Task Scheduler, driven through PowerShell's ScheduledTasks."""

    name = "windows_task_scheduler"

    def __init__(self, run: Runner = _default_run) -> None:
        self.run = run

    def _powershell(self, script: str) -> subprocess.CompletedProcess[str]:
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        argv = [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded,
        ]
        return self.run(argv, None)

    def expected_command(self, command: list[str]) -> str:
        return f"{command[0]} {subprocess.list2cmdline(command[1:])}".strip()

    def read(self, cfg: ScheduleConfig) -> Installed | None:
        name = _ps_quote(cfg.task_name)
        script = f"""$ErrorActionPreference = 'Stop'
$t = Get-ScheduledTask -TaskName {name} -ErrorAction SilentlyContinue
if (-not $t) {{ '{{"installed":false}}'; return }}
$i = Get-ScheduledTaskInfo -TaskName {name}
$trigger = $t.Triggers | Select-Object -First 1
$act = $t.Actions | Select-Object -First 1
function Iso($d) {{ if ($d -and $d.Year -gt 2000) {{ $d.ToString('s') }} else {{ $null }} }}
[pscustomobject]@{{
  installed = $true
  execute = $act.Execute
  arguments = $act.Arguments
  days = [int]$trigger.DaysOfWeek
  start = [string]$trigger.StartBoundary
  next_run = (Iso $i.NextRunTime)
  last_run = (Iso $i.LastRunTime)
  last_result = [int]$i.LastTaskResult
}} | ConvertTo-Json -Compress
"""
        proc = self._powershell(script)
        if proc.returncode != 0:
            raise _fail("could not read the scheduled task", proc)
        try:
            data = json.loads(proc.stdout.strip() or "{}")
        except ValueError as exc:
            raise ScheduleError(f"unreadable scheduler output: {exc}") from exc
        if not data.get("installed"):
            return None
        bits = int(data.get("days") or 0)
        days = [d for d, bit in _WINDOWS_DAY_BITS.items() if bits & bit]
        start = str(data.get("start") or "")
        return Installed(
            command=f"{data.get('execute') or ''} {data.get('arguments') or ''}".strip(),
            day=days[0] if len(days) == 1 else "multiple days",
            time=start[11:16] if len(start) >= 16 else "",
            next_run=_local(data.get("next_run")),
            last_run=_local(data.get("last_run")),
            last_result=data.get("last_result"),
        )

    def install(self, cfg: ScheduleConfig, command: list[str]) -> None:
        script = f"""$ErrorActionPreference = 'Stop'
$action = New-ScheduledTaskAction -Execute {_ps_quote(command[0])} -Argument {_ps_quote(subprocess.list2cmdline(command[1:]))}
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek {cfg.day} -At {_ps_quote(cfg.time)}
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable
Register-ScheduledTask -TaskName {_ps_quote(cfg.task_name)} -Action $action -Trigger $trigger -Settings $settings -Description {_ps_quote("Refresh M365 MCP tokens so they never expire from disuse")} -Force | Out-Null
"""
        proc = self._powershell(script)
        if proc.returncode != 0:
            raise _fail("could not register the scheduled task", proc)

    def remove(self, cfg: ScheduleConfig) -> bool:
        if self.read(cfg) is None:
            return False
        script = (
            "$ErrorActionPreference = 'Stop'\n"
            f"Unregister-ScheduledTask -TaskName {_ps_quote(cfg.task_name)} "
            "-Confirm:$false\n"
        )
        proc = self._powershell(script)
        if proc.returncode != 0:
            raise _fail("could not remove the scheduled task", proc)
        return True


def _local(value: Any) -> datetime | None:
    """Parse a naive local ISO timestamp from PowerShell into an aware one."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).astimezone()
    except ValueError:
        return None


class CronBackend:
    """The user's crontab (Linux, macOS)."""

    name = "cron"

    def __init__(self, run: Runner = _default_run, log_path: Path = LOG_PATH) -> None:
        self.run = run
        self.log_path = log_path

    def _table(self) -> list[str]:
        proc = self.run(["crontab", "-l"], None)
        if proc.returncode != 0:
            if "no crontab" in (proc.stderr or "").lower():
                return []
            raise _fail("could not read the crontab", proc)
        return proc.stdout.splitlines()

    def _write(self, lines: list[str]) -> None:
        text = "\n".join(lines) + "\n" if lines else ""
        proc = self.run(["crontab", "-"], text)
        if proc.returncode != 0:
            raise _fail("could not write the crontab", proc)

    def expected_command(self, command: list[str]) -> str:
        return f"{shlex.join(command)} >> {shlex.quote(str(self.log_path))} 2>&1"

    def _line(self, cfg: ScheduleConfig, command: list[str]) -> str:
        hour, minute = cfg.time.split(":")
        dow = (DAYS.index(cfg.day) + 1) % 7  # cron: Sunday is 0
        return (
            f"{int(minute)} {int(hour)} * * {dow} "
            f"{self.expected_command(command)} # {MARKER}"
        )

    def read(self, cfg: ScheduleConfig) -> Installed | None:
        for line in self._table():
            if not line.rstrip().endswith(f"# {MARKER}"):
                continue
            match = re.match(
                rf"^(\d+) (\d+) \S+ \S+ (\S+) (.*) # {MARKER}\s*$", line.strip()
            )
            if not match:
                return Installed(command=line, day="unknown", time="")
            minute, hour, dow, command = match.groups()
            day = DAYS[(int(dow) - 1) % 7] if dow.isdigit() else dow
            return Installed(
                command=command, day=day, time=f"{int(hour):02d}:{int(minute):02d}"
            )
        return None

    def install(self, cfg: ScheduleConfig, command: list[str]) -> None:
        kept = [
            line for line in self._table() if not line.rstrip().endswith(f"# {MARKER}")
        ]
        self._write([*kept, self._line(cfg, command)])

    def remove(self, cfg: ScheduleConfig) -> bool:
        table = self._table()
        kept = [line for line in table if not line.rstrip().endswith(f"# {MARKER}")]
        if len(kept) == len(table):
            return False
        self._write(kept)
        return True


def detect_backend(
    run: Runner = _default_run, platform: str | None = None
) -> Backend | None:
    """Pick the scheduler for this operating system.

    Args:
        run: Command runner (replaced in tests).
        platform: ``sys.platform`` override.

    Returns:
        A backend, or ``None`` on platforms without one.
    """
    platform = sys.platform if platform is None else platform
    if platform == "win32":
        return WindowsBackend(run=run)
    if platform.startswith("linux") or platform == "darwin":
        return CronBackend(run=run)
    return None


def job_command(env_file: Path | None) -> list[str]:
    """Return the command the scheduler runs.

    Uses this interpreter (so the virtualenv is kept) and, on Windows,
    ``pythonw.exe`` when present so no console window opens.

    Args:
        env_file: The ``.env`` the server loaded; passed on so the job finds
            ``M365_MCP_CLIENT_ID``.

    Returns:
        The argument vector.
    """
    exe = Path(sys.executable)
    if sys.platform == "win32":
        windowed = exe.with_name("pythonw.exe")
        if windowed.exists():
            exe = windowed
    command = [str(exe), "-m", "m365_mcp.reauth_job"]
    if env_file is not None:
        command += ["--env-file", str(env_file)]
    return command


# ----------------------------------------------------------------------
# Facade
# ----------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now().astimezone()


def _next_weekly(now: datetime, day: str, time: str) -> datetime:
    hour, minute = (int(part) for part in time.split(":"))
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    ahead = (DAYS.index(day) - candidate.weekday()) % 7
    candidate += timedelta(days=ahead)
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate


class Scheduler:
    """Install, remove and check the weekly re-auth job."""

    def __init__(
        self,
        cfg: ScheduleConfig,
        backend: Backend | None,
        *,
        state_path: Path = STATE_PATH,
        clock: Callable[[], datetime] = _now,
        env_file: Path | None = None,
    ) -> None:
        self.cfg = cfg
        self.backend = backend
        self.state_path = state_path
        self.clock = clock
        self.env_file = env_file

    @classmethod
    def from_environment(cls) -> Scheduler:
        """Build a scheduler from ``MCP_WEEKLY_RE_AUTH`` and friends.

        Returns:
            The scheduler for this process.

        Raises:
            ValueError: If a configuration variable is invalid.
        """
        raw = os.environ.get(ENV_ENV_FILE)
        return cls(
            ScheduleConfig.from_env(),
            detect_backend(),
            env_file=Path(raw) if raw else None,
        )

    def _command(self) -> list[str]:
        return job_command(self.env_file)

    def _unsupported(self) -> ScheduleError:
        return ScheduleError(
            f"Scheduled re-authentication is not supported on {sys.platform}"
        )

    def status(self, extra_problems: list[str] | None = None) -> dict[str, Any]:
        """Report the schedule and its health.

        Args:
            extra_problems: Problems found by the caller (for example a
                failed repair) to include.

        Returns:
            A dictionary shaped like the ``admin_reauth_schedule`` result.
        """
        cfg = self.cfg
        now = self.clock()
        problems = list(extra_problems or [])
        installed: Installed | None = None
        if self.backend is None:
            if cfg.enabled:
                problems.append(str(self._unsupported()))
        else:
            try:
                installed = self.backend.read(cfg)
            except ScheduleError as exc:
                problems.append(f"could not read the schedule: {exc}")

        matches: bool | None = None
        schedule = None
        next_run = None
        if installed is not None and self.backend is not None:
            schedule = {"day": installed.day, "time": installed.time}
            expected = self.backend.expected_command(self._command())
            matches = (
                installed.command == expected
                and installed.day == cfg.day
                and installed.time == cfg.time
            )
            next_run = installed.next_run or (
                _next_weekly(now, installed.day, installed.time)
                if installed.day in DAYS and installed.time
                else None
            )
            if cfg.enabled and not matches:
                problems.append(
                    "the installed task differs from the expected settings "
                    f"(expected {cfg.day} {cfg.time}, found "
                    f"{installed.day} {installed.time}"
                    + ("" if installed.command == expected else "; the command differs")
                    + ")"
                )
        unreadable = any("could not read" in p for p in problems)
        if (
            cfg.enabled
            and self.backend is not None
            and installed is None
            and not unreadable
        ):
            problems.append(f"{ENV_ENABLE} is true but the task is not installed")
        if installed is not None and cfg.enabled is not True:
            problems.append(
                f"the task is installed but {ENV_ENABLE} is not true "
                "(remove the task, or set the variable)"
            )

        last_run = self._last_run(installed)
        if installed is not None:
            problems.extend(self._run_problems(last_run, now))

        return {
            "supported": self.backend is not None,
            "backend": self.backend.name if self.backend else "none",
            "task_name": cfg.task_name,
            "configured": cfg.enabled,
            "installed": installed is not None,
            "schedule": schedule,
            "matches_expected": matches,
            "next_run": next_run.isoformat() if next_run else None,
            "last_run": last_run,
            "healthy": not problems,
            "problems": problems,
        }

    def _last_run(self, installed: Installed | None) -> dict[str, Any] | None:
        recorded = read_state(self.state_path).get("last_run")
        if isinstance(recorded, dict) and recorded.get("finished_at"):
            return {
                "finished_at": str(recorded["finished_at"]),
                "success": bool(recorded.get("success")),
                "message": str(recorded.get("message") or ""),
            }
        if installed is not None and installed.last_run is not None:
            ok = installed.last_result == 0
            return {
                "finished_at": installed.last_run.isoformat(),
                "success": ok,
                "message": (
                    "The scheduler reports success."
                    if ok
                    else f"The scheduler reports result code {installed.last_result}."
                ),
            }
        return None

    def _run_problems(
        self, last_run: dict[str, Any] | None, now: datetime
    ) -> list[str]:
        if last_run is None:
            installed_at = read_state(self.state_path).get("installed_at")
            try:
                since = now - datetime.fromisoformat(str(installed_at))
            except (TypeError, ValueError):
                return []
            if since > OVERDUE_AFTER:
                return [
                    (
                        f"the job has not run in the {since.days} days since it "
                        "was installed"
                    )
                ]
            return []
        problems: list[str] = []
        if not last_run["success"]:
            problems.append(f"the last run failed: {last_run['message']}")
        try:
            age = now - datetime.fromisoformat(last_run["finished_at"])
        except ValueError:
            return problems
        if age > OVERDUE_AFTER:
            problems.append(
                f"the last run was {age.days} days ago (expected at least weekly)"
            )
        return problems

    def install(self) -> dict[str, Any]:
        """Install the job, or repair it if it differs from the settings.

        Returns:
            ``changed`` (whether the scheduler was modified) and the new
            ``status``.

        Raises:
            ScheduleError: If the platform has no scheduler or it fails.
        """
        if self.backend is None:
            raise self._unsupported()
        command = self._command()
        current = self.backend.read(self.cfg)
        wanted = self.backend.expected_command(command)
        if (
            current is not None
            and current.command == wanted
            and (current.day, current.time) == (self.cfg.day, self.cfg.time)
        ):
            return {"changed": False, "status": self.status()}
        self.backend.install(self.cfg, command)
        state = read_state(self.state_path)
        state["installed_at"] = self.clock().isoformat()
        _write_state(self.state_path, state)
        return {"changed": True, "status": self.status()}

    def remove(self) -> dict[str, Any]:
        """Remove the job.

        Returns:
            ``changed`` (whether a job was removed) and the new ``status``.

        Raises:
            ScheduleError: If the platform has no scheduler or it fails.
        """
        if self.backend is None:
            raise self._unsupported()
        changed = self.backend.remove(self.cfg)
        return {"changed": changed, "status": self.status()}

    def reconcile(self) -> dict[str, Any]:
        """Bring the scheduler in line with ``MCP_WEEKLY_RE_AUTH``.

        ``true`` installs a missing job and repairs a drifted one, ``false``
        removes an existing job, unset does nothing. Failures are reported
        in the returned status instead of raised, so a periodic check never
        stops the server.

        Returns:
            ``actions`` taken (``installed``, ``repaired``, ``removed``) and
            the resulting ``status``.
        """
        actions: list[str] = []
        errors: list[str] = []
        if self.backend is not None and self.cfg.enabled is not None:
            try:
                current = self.backend.read(self.cfg)
                if self.cfg.enabled:
                    outcome = self.install()
                    if outcome["changed"]:
                        actions.append("repaired" if current else "installed")
                elif current is not None and self.backend.remove(self.cfg):
                    actions.append("removed")
            except ScheduleError as exc:
                errors.append(f"could not update the schedule: {exc}")
        return {"actions": actions, "status": self.status(extra_problems=errors)}


async def monitor(
    scheduler: Scheduler,
    *,
    sleep: Callable[[float], Any] = asyncio.sleep,
) -> None:
    """Keep the job installed and healthy while the server runs.

    Reconciles at once (install, repair or remove per
    ``MCP_WEEKLY_RE_AUTH``), then every ``check_hours`` when the variable is
    ``true``; ``false`` reconciles once and returns. Problems are logged as
    warnings each time they are found; nothing here raises.

    Args:
        scheduler: The scheduler to keep in line with the configuration.
        sleep: Awaitable sleep (replaced in tests).
    """

    def check() -> None:
        try:
            outcome = scheduler.reconcile()
        except Exception:
            logger.exception("Re-auth schedule check failed")
            return
        for action in outcome["actions"]:
            logger.info("Weekly re-auth job %s", action)
        for problem in outcome["status"]["problems"]:
            logger.warning("Weekly re-auth: %s", problem)

    while True:
        await asyncio.to_thread(check)
        if scheduler.cfg.enabled is not True:
            return
        await sleep(scheduler.cfg.check_hours * 3600)
