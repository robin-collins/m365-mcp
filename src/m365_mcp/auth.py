import pathlib as pl
import json
import logging
import os
import sys
import threading
from typing import Any, NamedTuple

import msal
import msal_extensions

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
# Flow key recording which tenant authority issued a device code, so the
# code is redeemed against the same authority.
DEVICE_FLOW_TENANT_KEY = "_m365_tenant_id"

# MSAL error codes meaning the refresh token can no longer be used and the
# user must sign in again (expired, revoked, or new consent required).
SIGN_IN_REQUIRED_ERRORS = frozenset(
    {"invalid_grant", "interaction_required", "consent_required", "login_required"}
)

logger = logging.getLogger(__name__)

# MSAL apps are reused across requests: constructing one performs a network
# tenant discovery call. The persisted cache reloads itself when another
# process (authenticate.py or a second server) updates the cache file.
_APP_LOCK = threading.Lock()
_APPS: dict[tuple[str, str], msal.PublicClientApplication] = {}
_TOKEN_CACHE: msal_extensions.PersistedTokenCache | None = None


class SignInRequiredError(RuntimeError):
    """Raised when an account has no usable refresh token and must sign in."""


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


def _get_token_cache() -> msal_extensions.PersistedTokenCache:
    """Return the shared file-backed token cache.

    The cache takes a cross-process file lock for every write and reloads
    from disk whenever the file was changed by another process, so refreshed
    (rotated) refresh tokens are never lost to a concurrent writer.
    """
    global _TOKEN_CACHE
    if _TOKEN_CACHE is None:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        persistence = msal_extensions.FilePersistence(str(CACHE_FILE))
        _TOKEN_CACHE = msal_extensions.PersistedTokenCache(persistence)
    return _TOKEN_CACHE


def _interactive_auth_enabled() -> bool:
    return os.getenv(INTERACTIVE_AUTH_ENV_VAR, "false").lower() == "true"


def _raise_interactive_auth_required(
    account_id: str | None, reason: str | None = None
) -> None:
    account_hint = f" for '{account_id}'" if account_id else ""
    reason_hint = f" Microsoft reported: {reason}." if reason else ""
    raise SignInRequiredError(
        f"Microsoft sign-in has expired or is missing{account_hint}."
        f"{reason_hint} Run `uv run authenticate.py` and sign in again "
        "before using MCP tools, or set M365_MCP_INTERACTIVE_AUTH=true only "
        "for an intentional interactive authentication process."
    )


def _describe_error(result: dict[str, Any]) -> str:
    """Return a one-line summary of an MSAL error result."""
    description = str(result.get("error_description", "no description"))
    return f"{result.get('error')} - {description.splitlines()[0]}"


def _build_app(tenant_id: str) -> msal.PublicClientApplication:
    """Return the shared MSAL PublicClientApplication for a tenant.

    Apps are created once per (client ID, tenant) and reused, because MSAL
    performs a network authority discovery each time an app is constructed.

    Args:
        tenant_id: Tenant segment for the authority (for example, "common",
            "consumers", or a specific directory ID).

    Returns:
        Initialized PublicClientApplication using the shared token cache.
    """

    client_id = os.getenv("M365_MCP_CLIENT_ID")
    if not client_id:
        raise ValueError("M365_MCP_CLIENT_ID environment variable is required")

    key = (client_id, tenant_id)
    with _APP_LOCK:
        app = _APPS.get(key)
        if app is None:
            app = msal.PublicClientApplication(
                client_id,
                authority=f"https://login.microsoftonline.com/{tenant_id}",
                token_cache=_get_token_cache(),
            )
            _APPS[key] = app
        return app


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

    def _start(
        current_app: msal.PublicClientApplication, current_tenant: str
    ) -> dict[str, Any]:
        flow = current_app.initiate_device_flow(scopes=DEVICE_FLOW_SCOPES)
        if "user_code" in flow:
            flow[DEVICE_FLOW_TENANT_KEY] = current_tenant
            return flow

        error_message = flow.get(
            "error_description", flow.get("error", "Unknown error")
        )
        raise Exception(error_message)

    try:
        return app, _start(app, tenant_id)
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

        consumer_app = _build_app("consumers")
        return consumer_app, _start(consumer_app, "consumers")


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


def get_token(account_id: str | None = None, force_refresh: bool = False) -> str:
    """Return a Graph access token, silently refreshing it when needed.

    MSAL returns the cached access token while it is valid and otherwise
    redeems the cached refresh token, persisting the rotated tokens.

    Args:
        account_id: Optional account ID or username. Defaults to the first
            cached account.
        force_refresh: Skip the cached access token and redeem the refresh
            token (used after Graph rejects a token with 401).

    Returns:
        A bearer access token for Microsoft Graph.

    Raises:
        SignInRequiredError: If the account must sign in again and
            interactive auth is disabled.
        RuntimeError: If the token service fails for another reason.
    """
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

    result = None
    if account is not None:
        result = app.acquire_token_silent_with_error(
            SCOPES, account=account, force_refresh=force_refresh
        )

    reason = None
    if result and "error" in result:
        reason = _describe_error(result)
        logger.warning("Silent token acquisition failed: %s", reason)
        if result.get("error") not in SIGN_IN_REQUIRED_ERRORS:
            # Transient/service errors: signing in again would not help.
            raise RuntimeError(
                f"Microsoft token refresh failed: {reason}. "
                "This is usually temporary; retry shortly."
            )
        result = None

    if not result:
        if not _interactive_auth_enabled():
            _raise_interactive_auth_required(
                account["username"] if account else account_id, reason
            )

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
        SignInRequiredError: If no refresh token is available or Microsoft
            reports that it has expired or been revoked.
        RuntimeError: If Microsoft rejects the silent refresh for another
            (usually transient) reason.
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
        raise SignInRequiredError(
            f"No cached refresh token is available for {account['username']}. "
            "Run `uv run authenticate.py` and sign in again."
        )

    if "error" in result:
        reason = _describe_error(result)
        if result.get("error") in SIGN_IN_REQUIRED_ERRORS:
            raise SignInRequiredError(
                f"Sign-in for {account['username']} has expired or been "
                f"revoked ({reason}). Run `uv run authenticate.py` and sign "
                "in again."
            )
        raise RuntimeError(f"Token refresh failed for {account['username']}: {reason}")

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

    # The persisted cache writes the removal to disk immediately.
    app.remove_account(account)
    token_cache_removed = True

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
