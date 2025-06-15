import os
import msal
import pathlib as pl
from typing import NamedTuple

CLIENT_ID = os.getenv("MICROSOFT_MCP_CLIENT_ID")
TENANT_ID = os.getenv("MICROSOFT_MCP_TENANT_ID", "common")
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = ["https://graph.microsoft.com/.default"]
CACHE_FILE = pl.Path.home() / ".microsoft_mcp_token_cache.json"


class Account(NamedTuple):
    username: str
    account_id: str


def get_app() -> msal.PublicClientApplication:
    cache = msal.SerializableTokenCache()
    if CACHE_FILE.exists():
        cache.deserialize(CACHE_FILE.read_text())
    
    app = msal.PublicClientApplication(
        CLIENT_ID, authority=AUTHORITY, token_cache=cache
    )
    
    if cache.has_state_changed:
        CACHE_FILE.write_text(cache.serialize())
    
    return app


def get_token(account_id: str | None = None) -> str:
    app = get_app()
    
    accounts = app.get_accounts()
    account = None
    
    if account_id:
        account = next((a for a in accounts if a["home_account_id"] == account_id), None)
    elif accounts:
        account = accounts[0]
    
    result = app.acquire_token_silent(SCOPES, account=account)
    
    if not result:
        flow = app.initiate_device_flow(scopes=SCOPES)
        print(f"\nTo authenticate:\n1. Visit {flow['verification_uri']}\n2. Enter code: {flow['user_code']}")
        result = app.acquire_token_by_device_flow(flow)
    
    if "error" in result:
        raise Exception(f"Auth failed: {result.get('error_description', result['error'])}")
    
    cache = app.token_cache
    if cache.has_state_changed:
        CACHE_FILE.write_text(cache.serialize())
    
    return result["access_token"]


def list_accounts() -> list[Account]:
    app = get_app()
    return [
        Account(username=a["username"], account_id=a["home_account_id"])
        for a in app.get_accounts()
    ]