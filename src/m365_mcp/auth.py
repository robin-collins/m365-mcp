import pathlib as pl
import json
import logging
import os
import sys
from typing import Any, NamedTuple

import msal

# Note: Environment variables should be loaded by the caller (server.py or authenticate.py)
# before importing this module

# Store token cache in user's home directory for proper permissions and portability
CACHE_FILE = pl.Path.home() / ".m365_mcp_token_cache.json"
METADATA_FILE = pl.Path.home() / ".m365_mcp_account_metadata.json"

# MSAL treats OIDC scopes such as offline_access as reserved and adds them
# internally, so callers must only provide Graph scopes.
SCOPES = ["https://graph.microsoft.com/.default"]
DEVICE_FLOW_SCOPES = SCOPES
INTERACTIVE_AUTH_ENV_VAR = "M365_MCP_INTERACTIVE_AUTH"

logger = logging.getLogger(__name__)


class Account(NamedTuple):
    username: str
    account_id: str
    account_type: str  # "personal", "work_school", or "unknown"


class ReauthenticationResult(NamedTuple):
    account: Account
    expires_in: int | None


class AccountRemovalResult(NamedTuple):
    account: Account
    token_cache_removed: bool
    metadata_removed: bool
    database_cache_removed: dict[str, int]


def _select_account(
    accounts: list[dict[str, str]],
    result: dict[str, Any],
    fallback: dict[str, str] | None,
) -> dict[str, str] | None:
    """Select the account that matches the token result, if possible."""
    if fallback:
        return fallback

    preferred_username = None
    id_token_claims = result.get("id_token_claims")
    if isinstance(id_token_claims, dict):
        preferred_username = id_token_claims.get("preferred_username")

    if preferred_username:
        for account in accounts:
            if account.get("username", "").lower() == preferred_username.lower():
                return account

    return accounts[0] if accounts else None


def _read_cache() -> str | None:
    try:
        return CACHE_FILE.read_text()
    except FileNotFoundError:
        return None


def _write_cache(content: str) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(content)


def _interactive_auth_enabled() -> bool:
    return os.getenv(INTERACTIVE_AUTH_ENV_VAR, "false").lower() == "true"


def _raise_interactive_auth_required(account_id: str | None) -> None:
    account_hint = f" for account_id '{account_id}'" if account_id else ""
    raise RuntimeError(
        f"No cached Microsoft access token is available{account_hint}. "
        "Run `uv run authenticate.py` to authenticate interactively before "
        "using MCP tools, or set M365_MCP_INTERACTIVE_AUTH=true only for an "
        "intentional interactive authentication process."
    )


def _build_app(
    tenant_id: str, cache: msal.SerializableTokenCache | None = None
) -> msal.PublicClientApplication:
    """Construct an MSAL PublicClientApplication with the shared cache.

    Args:
        tenant_id: Tenant segment for the authority (for example, "common",
            "consumers", or a specific directory ID).
        cache: Reusable token cache. If omitted, the cache will be hydrated
            from disk.

    Returns:
        Initialized PublicClientApplication.
    """

    client_id = os.getenv("M365_MCP_CLIENT_ID")
    if not client_id:
        raise ValueError("M365_MCP_CLIENT_ID environment variable is required")

    cache_instance = cache or msal.SerializableTokenCache()
    if cache is None:
        cache_content = _read_cache()
        if cache_content:
            cache_instance.deserialize(cache_content)

    authority = f"https://login.microsoftonline.com/{tenant_id}"

    return msal.PublicClientApplication(
        client_id, authority=authority, token_cache=cache_instance
    )


def _read_metadata() -> dict[str, dict]:
    """Read account metadata cache containing account types and other metadata.

    Returns:
        Dictionary mapping account_id to metadata dict with 'account_type' field.
    """
    try:
        content = METADATA_FILE.read_text()
        return json.loads(content)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_metadata(metadata: dict[str, dict]) -> None:
    """Write account metadata cache.

    Args:
        metadata: Dictionary mapping account_id to metadata dict.
    """
    METADATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    METADATA_FILE.write_text(json.dumps(metadata, indent=2))


def _initiate_device_flow(
    app: msal.PublicClientApplication, tenant_id: str
) -> tuple[msal.PublicClientApplication, dict[str, Any]]:
    """Start a device code flow, retrying with a consumer authority if needed.

    If the configured authority rejects the flow in a way associated with
    personal-account scope handling, retry with the ``consumers`` authority
    while reusing the same token cache.
    """

    def _start(current_app: msal.PublicClientApplication) -> dict[str, Any]:
        flow = current_app.initiate_device_flow(scopes=DEVICE_FLOW_SCOPES)
        if "user_code" in flow:
            return flow

        error_message = flow.get(
            "error_description", flow.get("error", "Unknown error")
        )
        raise Exception(error_message)

    try:
        return app, _start(app)
    except Exception as exc:
        message = str(exc).lower()
        if "reserved" not in message and "offline_access" not in message:
            raise

        if tenant_id == "consumers":
            raise

        logger.warning(
            "Device flow rejected personal-account scope handling; "
            "retrying with the consumers authority",
        )

        cache = (
            app.token_cache
            if isinstance(app.token_cache, msal.SerializableTokenCache)
            else None
        )
        consumer_app = _build_app("consumers", cache=cache)
        return consumer_app, _start(consumer_app)


def _get_account_type(account_id: str, username: str) -> str:
    """Get or detect account type for an account.

    Args:
        account_id: Account identifier.
        username: User's principal name (email).

    Returns:
        Account type: "personal", "work_school", or "unknown"
    """
    # Check metadata cache first
    metadata = _read_metadata()
    if account_id in metadata and "account_type" in metadata[account_id]:
        return metadata[account_id]["account_type"]

    # Detect account type using domain checking
    # Note: Microsoft Graph API access tokens are opaque and cannot be decoded
    # We rely on username (UPN) domain matching for detection
    try:
        from m365_mcp.account_type import _check_upn_domain

        account_type = _check_upn_domain(username)

        if not account_type:
            logger.warning(
                f"Could not determine account type from username: {username}"
            )
            return "unknown"

        # Store in metadata cache
        if account_id not in metadata:
            metadata[account_id] = {}
        metadata[account_id]["account_type"] = account_type
        _write_metadata(metadata)

        logger.info(
            f"Account type detected and cached for {account_id}: {account_type}"
        )
        return account_type

    except Exception as e:
        logger.warning(f"Failed to detect account type for {account_id}: {e}")
        return "unknown"


def get_app() -> tuple[msal.PublicClientApplication, str]:
    tenant_id = os.getenv("M365_MCP_TENANT_ID", "common")
    app = _build_app(tenant_id)
    return app, tenant_id


def _account_matches_identifier(
    account: dict[str, str],
    account_identifier: str,
) -> bool:
    """Check whether an MSAL account matches an ID or username."""
    selector = account_identifier.lower()
    return (
        account.get("home_account_id", "").lower() == selector
        or account.get("username", "").lower() == selector
    )


def _find_cached_account(
    app: msal.PublicClientApplication, account_identifier: str | None = None
) -> dict[str, str]:
    """Find a cached MSAL account by ID or username.

    Args:
        app: MSAL public client application.
        account_identifier: Optional home account ID or username. If omitted,
            exactly one cached account must exist.

    Returns:
        The matching MSAL account dictionary.

    Raises:
        RuntimeError: If no accounts are cached.
        ValueError: If the account cannot be selected unambiguously.
    """
    accounts = app.get_accounts()
    if not accounts:
        raise RuntimeError(
            "No Microsoft accounts are configured. Run `uv run authenticate.py` "
            "to authenticate an account first."
        )

    if account_identifier:
        matches = [
            account
            for account in accounts
            if _account_matches_identifier(account, account_identifier)
        ]
        if not matches:
            raise ValueError(
                f"No configured account matches '{account_identifier}'. "
                "Use `uv run authenticate.py` to list accounts."
            )
        if len(matches) > 1:
            raise ValueError(
                f"Multiple accounts match '{account_identifier}'. "
                "Use the full account ID."
            )
        return matches[0]

    if len(accounts) > 1:
        raise ValueError(
            "Multiple accounts are configured. Provide an account ID or username."
        )

    return accounts[0]


def _account_from_msal(account: dict[str, str], detect_type: bool = True) -> Account:
    """Convert an MSAL account dictionary into this module's public Account."""
    account_id = account["home_account_id"]
    username = account["username"]
    if detect_type:
        account_type = _get_account_type(account_id, username)
    else:
        metadata = _read_metadata()
        account_type = metadata.get(account_id, {}).get("account_type", "unknown")

    return Account(
        username=username,
        account_id=account_id,
        account_type=account_type,
    )


def _save_token_cache_if_changed(app: msal.PublicClientApplication) -> bool:
    """Persist the MSAL token cache when it has changed."""
    cache = app.token_cache
    if isinstance(cache, msal.SerializableTokenCache) and cache.has_state_changed:
        _write_cache(cache.serialize())
        return True
    return False


def get_token(account_id: str | None = None, force_refresh: bool = False) -> str:
    app, tenant_id = get_app()

    accounts = app.get_accounts()
    account = None

    if account_id:
        account = next(
            (a for a in accounts if _account_matches_identifier(a, account_id)),
            None,
        )
    elif accounts:
        account = accounts[0]

    if account_id and account is None:
        _raise_interactive_auth_required(account_id)

    silent_kwargs = {"force_refresh": True} if force_refresh else {}
    result = app.acquire_token_silent(SCOPES, account=account, **silent_kwargs)

    if result and "error" in result:
        logger.warning(
            "Silent token acquisition failed: %s - %s",
            result.get("error"),
            result.get("error_description", "no description"),
        )
        result = None

    if not result:
        if not _interactive_auth_enabled():
            _raise_interactive_auth_required(account_id)

        app, flow = _initiate_device_flow(app, tenant_id)
        verification_uri = flow.get(
            "verification_uri",
            flow.get("verification_url", "https://microsoft.com/devicelogin"),
        )
        print(
            f"\nTo authenticate:\n1. Visit {verification_uri}\n2. Enter code: {flow['user_code']}",
            file=sys.stderr,
        )
        result = app.acquire_token_by_device_flow(flow)
        accounts = app.get_accounts()
        account = _select_account(accounts, result, account)
    else:
        account = _select_account(accounts, result, account)

    if "error" in result:
        raise Exception(
            f"Auth failed: {result.get('error_description', result['error'])}"
        )

    _save_token_cache_if_changed(app)

    # Detect and cache account type for this account
    if account:
        _get_account_type(account["home_account_id"], account["username"])

    return result["access_token"]


def list_accounts() -> list[Account]:
    """List all authenticated Microsoft accounts with their types.

    Returns:
        List of Account objects with username, account_id, and account_type.
        Account type will be "unknown" if not yet detected.
    """
    app, _ = get_app()
    metadata = _read_metadata()

    accounts = []
    for a in app.get_accounts():
        account_id = a["home_account_id"]
        # Get account type from metadata cache, default to "unknown"
        account_type = metadata.get(account_id, {}).get("account_type", "unknown")
        accounts.append(
            Account(
                username=a["username"],
                account_id=account_id,
                account_type=account_type,
            )
        )

    return accounts


def reauthenticate_account(account_id: str | None = None) -> ReauthenticationResult:
    """Force-refresh a cached account token using MSAL's refresh token.

    Args:
        account_id: Optional account ID or username to refresh. Required when
            multiple accounts are configured.

    Returns:
        Account details and the token lifetime in seconds, when provided by MSAL.

    Raises:
        RuntimeError: If no refresh token is available or Microsoft rejects the
            silent refresh.
        ValueError: If the account cannot be selected.
    """
    app, _tenant_id = get_app()
    account = _find_cached_account(app, account_id)

    result = app.acquire_token_silent_with_error(
        SCOPES,
        account=account,
        force_refresh=True,
    )
    if not result:
        raise RuntimeError(
            f"No cached refresh token is available for {account['username']}. "
            "Run `uv run authenticate.py --remove` for this account, then "
            "`uv run authenticate.py` to sign in again."
        )

    if "error" in result:
        error = result.get("error")
        description = result.get("error_description", "no description")
        raise RuntimeError(
            f"Token refresh failed for {account['username']}: {error} - {description}"
        )

    _save_token_cache_if_changed(app)
    refreshed_account = _account_from_msal(account)
    expires_in = result.get("expires_in")
    return ReauthenticationResult(
        account=refreshed_account,
        expires_in=expires_in if isinstance(expires_in, int) else None,
    )


def _remove_account_database_cache(account_id: str) -> dict[str, int]:
    """Remove per-account entries from the encrypted database cache."""
    from .cache import CacheManager
    from .cache_config import CACHE_DB_PATH

    cache_path = pl.Path(CACHE_DB_PATH)
    if not cache_path.exists():
        return {
            "cache_entries": 0,
            "cache_tasks": 0,
            "cache_invalidation": 0,
        }

    cache_manager = CacheManager()
    try:
        return cache_manager.remove_account_cache(account_id)
    finally:
        cache_manager.close()


def remove_account(account_id: str) -> AccountRemovalResult:
    """Remove an account and its cached token, metadata, and data cache.

    Args:
        account_id: Account ID or username to remove.

    Returns:
        Details about the removed account and cache rows deleted.

    Raises:
        RuntimeError: If no configured accounts exist.
        ValueError: If the account cannot be selected.
    """
    app, _tenant_id = get_app()
    account = _find_cached_account(app, account_id)
    removed_account = _account_from_msal(account, detect_type=False)

    app.remove_account(account)
    token_cache_removed = _save_token_cache_if_changed(app)

    metadata = _read_metadata()
    metadata_removed = metadata.pop(removed_account.account_id, None) is not None
    if metadata_removed:
        _write_metadata(metadata)

    database_cache_removed = _remove_account_database_cache(removed_account.account_id)

    return AccountRemovalResult(
        account=removed_account,
        token_cache_removed=token_cache_removed,
        metadata_removed=metadata_removed,
        database_cache_removed=database_cache_removed,
    )


def authenticate_new_account() -> Account | None:
    """Authenticate a new account interactively and detect its type.

    Returns:
        Account object with username, account_id, and detected account_type,
        or None if authentication failed.
    """
    app, tenant_id = get_app()

    app, flow = _initiate_device_flow(app, tenant_id)

    print("\nTo authenticate:", file=sys.stderr)
    verification_url = flow.get(
        "verification_uri",
        flow.get("verification_url", "https://microsoft.com/devicelogin"),
    )
    print(f"1. Visit: {verification_url}", file=sys.stderr)
    print(f"2. Enter code: {flow['user_code']}", file=sys.stderr)
    print("3. Sign in with your Microsoft account", file=sys.stderr)
    print("\nWaiting for authentication...", file=sys.stderr)

    result = app.acquire_token_by_device_flow(flow)

    if "error" in result:
        raise Exception(
            f"Auth failed: {result.get('error_description', result['error'])}"
        )

    cache = app.token_cache
    if isinstance(cache, msal.SerializableTokenCache) and cache.has_state_changed:
        _write_cache(cache.serialize())

    # Get the newly added account
    accounts = app.get_accounts()
    if accounts:
        # Find the account that matches the token we just got
        matched_account = None
        for account in accounts:
            if (
                account.get("username", "").lower()
                == result.get("id_token_claims", {})
                .get("preferred_username", "")
                .lower()
            ):
                matched_account = account
                break

        # If exact match not found, use the last account
        if not matched_account:
            matched_account = accounts[-1]

        # Detect and cache account type
        account_id = matched_account["home_account_id"]
        account_type = _get_account_type(account_id, matched_account["username"])

        return Account(
            username=matched_account["username"],
            account_id=account_id,
            account_type=account_type,
        )

    return None
