import time
import threading
from datetime import datetime, timedelta
from typing import NamedTuple
from .auth import _build_app, _save_cache, SCOPES
from .logging_config import setup_logging


logger = setup_logging()


class TokenInfo(NamedTuple):
    access_token: str
    expires_at: datetime
    account_id: str


class TokenRefreshManager:
    def __init__(self, refresh_threshold_minutes: int = 5):
        self._tokens: dict[str, TokenInfo] = {}
        self._refresh_threshold = timedelta(minutes=refresh_threshold_minutes)
        self._refresh_thread: threading.Thread | None = None
        self._stop_refresh = threading.Event()

    def start(self) -> None:
        if self._refresh_thread is None or not self._refresh_thread.is_alive():
            self._stop_refresh.clear()
            self._refresh_thread = threading.Thread(
                target=self._refresh_loop, daemon=True
            )
            self._refresh_thread.start()
            logger.info("Token refresh manager started")

    def stop(self) -> None:
        self._stop_refresh.set()
        if self._refresh_thread:
            self._refresh_thread.join(timeout=5)
        logger.info("Token refresh manager stopped")

    def _refresh_loop(self) -> None:
        while not self._stop_refresh.is_set():
            try:
                self._check_and_refresh_tokens()
                time.sleep(60)  # Check every minute
            except Exception as e:
                logger.error(f"Error in token refresh loop: {e}")

    def _check_and_refresh_tokens(self) -> None:
        app, cache = _build_app()
        accounts = app.get_accounts()

        for account in accounts:
            account_id = account["home_account_id"]

            if self._should_refresh_token(account_id):
                self._refresh_token(app, account, cache)

    def _should_refresh_token(self, account_id: str) -> bool:
        if account_id not in self._tokens:
            return True

        token_info = self._tokens[account_id]
        time_until_expiry = token_info.expires_at - datetime.utcnow()

        return time_until_expiry <= self._refresh_threshold

    def _refresh_token(self, app, account, cache) -> None:
        try:
            result = app.acquire_token_silent(SCOPES, account=account)

            if result and "access_token" in result:
                expires_in = result.get("expires_in", 3600)
                expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

                self._tokens[account["home_account_id"]] = TokenInfo(
                    access_token=result["access_token"],
                    expires_at=expires_at,
                    account_id=account["home_account_id"],
                )

                _save_cache(cache)
                logger.debug(f"Refreshed token for account {account['username']}")
        except Exception as e:
            logger.error(f"Failed to refresh token for {account['username']}: {e}")


_manager = TokenRefreshManager()


def start_token_refresh() -> None:
    _manager.start()


def stop_token_refresh() -> None:
    _manager.stop()
