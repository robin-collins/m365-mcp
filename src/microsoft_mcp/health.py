from typing import NamedTuple
from datetime import datetime
from .auth import list_accounts, get_access_token
from .graph import _request
from .exceptions import AuthenticationError, GraphAPIError


class HealthStatus(NamedTuple):
    healthy: bool
    message: str
    checked_at: str
    auth_status: str
    api_status: str
    accounts_count: int


def _check_auth_health() -> tuple[bool, str, int]:
    try:
        accounts = list_accounts()
        accounts_count = len(accounts)

        if accounts_count == 0:
            return False, "No accounts authenticated", 0

        return True, f"{accounts_count} account(s) authenticated", accounts_count
    except Exception as e:
        return False, f"Auth check failed: {str(e)}", 0


def _check_api_health(account_id: str | None = None) -> tuple[bool, str]:
    try:
        get_access_token(account_id)
        result = _request("GET", "/me", account_id=account_id)

        if result:
            return True, "API connection successful"
        return False, "API returned empty response"
    except AuthenticationError as e:
        return False, f"Authentication failed: {str(e)}"
    except GraphAPIError as e:
        return False, f"API error: {str(e)}"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"


def check_health(account_id: str | None = None) -> HealthStatus:
    auth_healthy, auth_message, accounts_count = _check_auth_health()

    if auth_healthy and accounts_count > 0:
        api_healthy, api_message = _check_api_health(account_id)
    else:
        api_healthy = False
        api_message = "Skipped - no authenticated accounts"

    overall_healthy = auth_healthy and api_healthy

    if overall_healthy:
        message = "All systems operational"
    else:
        message = "Some systems are not operational"

    return HealthStatus(
        healthy=overall_healthy,
        message=message,
        checked_at=datetime.utcnow().isoformat(),
        auth_status=auth_message,
        api_status=api_message,
        accounts_count=accounts_count,
    )
