"""The scheduled job: refresh every signed-in account's token.

Run by the weekly task installed by ``reauth_schedule``::

    python -m m365_mcp.reauth_job [--env-file PATH]

It force-refreshes each account so the refresh token never expires from
disuse, records the outcome in the state file the health check reads, and
exits 0 only if every account refreshed. It prints nothing (it may run under
``pythonw``); details go to ``~/.m365_mcp_reauth.log``.
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from . import reauth_schedule

logger = logging.getLogger("m365_mcp.reauth_job")


def _now() -> datetime:
    return datetime.now().astimezone()


def run_job(
    *,
    state_path: Path = reauth_schedule.STATE_PATH,
    clock: Callable[[], datetime] = _now,
) -> tuple[bool, str]:
    """Refresh every signed-in account and record the outcome.

    Args:
        state_path: State file that receives the outcome.
        clock: Time source.

    Returns:
        ``(success, message)``; ``success`` is true only if at least one
        account exists and all of them refreshed.
    """
    # Imported here so the env file is loaded before auth reads the client ID.
    from . import auth

    failures: list[str] = []
    refreshed = 0
    try:
        accounts = auth.list_accounts()
        if not accounts:
            failures.append(
                "No Microsoft account is signed in; run `uv run authenticate.py`."
            )
        for account in accounts:
            try:
                auth.reauthenticate_account(account.account_id)
                refreshed += 1
            except Exception as exc:  # noqa: BLE001 - recorded, then next account
                logger.warning("Refresh failed for %s: %s", account.username, exc)
                failures.append(f"{account.username}: {exc}")
    except Exception as exc:
        logger.exception("Re-auth job failed")
        failures.append(str(exc))

    success = not failures
    noun = "account" if refreshed == 1 else "accounts"
    message = f"Refreshed {refreshed} {noun}." if success else " ".join(failures)
    reauth_schedule.record_run(
        state_path, finished_at=clock(), success=success, message=message
    )
    logger.info("Re-auth job finished: %s", message)
    return success, message


def _configure_logging() -> None:
    try:
        logging.basicConfig(
            filename=reauth_schedule.LOG_PATH,
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
        )
    except OSError:
        logging.disable(logging.CRITICAL)


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``python -m m365_mcp.reauth_job``.

    Args:
        argv: Arguments (default ``sys.argv[1:]``).

    Returns:
        0 if every account refreshed, otherwise 1.
    """
    parser = argparse.ArgumentParser(description="Refresh M365 MCP tokens.")
    parser.add_argument("--env-file", type=Path, default=None)
    args = parser.parse_args(argv)
    _configure_logging()
    if args.env_file is not None and args.env_file.exists():
        load_dotenv(dotenv_path=args.env_file)
    success, _message = run_job()
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
