import os
import pathlib as pl
import msal
from typing import NamedTuple
from dotenv import load_dotenv
from .exceptions import (
    AuthenticationError,
    DeviceCodeAuthRequired,
    TokenAcquisitionError,
    DeviceCodeFlow,
)

load_dotenv()

CLIENT_ID = os.getenv("MICROSOFT_MCP_CLIENT_ID")
TENANT_ID = os.getenv("MICROSOFT_MCP_TENANT_ID", "common")
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = ["https://graph.microsoft.com/.default"]

_CACHE = pl.Path.home() / ".microsoft_mcp_token_cache.json"


class AccountInfo(NamedTuple):
    username: str
    home_account_id: str
    environment: str
    local_account_id: str


def _load_token_cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if _CACHE.exists():
        cache.deserialize(_CACHE.read_text())
    return cache


def _build_app() -> tuple[msal.PublicClientApplication, msal.SerializableTokenCache]:
    if not CLIENT_ID:
        raise AuthenticationError(
            "MICROSOFT_MCP_CLIENT_ID environment variable is required"
        )

    cache = _load_token_cache()
    app = msal.PublicClientApplication(
        CLIENT_ID, authority=AUTHORITY, token_cache=cache
    )
    return app, cache


def _save_cache(cache: msal.SerializableTokenCache) -> None:
    if cache.has_state_changed:
        _CACHE.write_text(cache.serialize())


def _find_account(
    app: msal.PublicClientApplication, account_id: str | None
) -> dict[str, str] | None:
    if account_id:
        for account in app.get_accounts():
            if account["home_account_id"] == account_id:
                return account
        return None
    accounts = app.get_accounts()
    return next(iter(accounts), None) if accounts else None


def _acquire_token_silent(
    app: msal.PublicClientApplication, account: dict[str, str] | None
) -> dict[str, str] | None:
    return app.acquire_token_silent(SCOPES, account=account)


def _initiate_device_flow(app: msal.PublicClientApplication) -> DeviceCodeFlow:
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise TokenAcquisitionError("Device-code flow failed")

    return DeviceCodeFlow(
        verification_uri=flow["verification_uri"],
        user_code=flow["user_code"],
        message=(
            f"Microsoft authentication required. Please tell the user to:\n"
            f"1. Visit {flow['verification_uri']}\n"
            f"2. Enter code: {flow['user_code']}\n"
            f"3. Sign in with their Microsoft account\n"
            f"4. Try the operation again after signing in"
        ),
    )


def get_access_token(account_id: str | None = None) -> str:
    app, cache = _build_app()
    account = _find_account(app, account_id)
    result = _acquire_token_silent(app, account)

    if not result:
        device_flow = _initiate_device_flow(app)
        raise DeviceCodeAuthRequired(device_flow.message)

    if "access_token" not in result:
        raise TokenAcquisitionError(f"Auth error: {result.get('error_description')}")

    _save_cache(cache)
    return result["access_token"]


def list_accounts() -> list[AccountInfo]:
    app, _ = _build_app()
    return [
        AccountInfo(
            username=a["username"],
            home_account_id=a["home_account_id"],
            environment=a["environment"],
            local_account_id=a["local_account_id"],
        )
        for a in app.get_accounts()
    ]


def auth_header(account_id: str | None = None) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {get_access_token(account_id)}",
        "Content-Type": "application/json",
    }
