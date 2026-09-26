import logging
import os
import pathlib as pl
import sys
import threading
from typing import Any, NamedTuple

import msal
import msal_extensions

# Note: Environment variables should be loaded by the caller (server.py or authenticate.py)
# before importing this module

# Store token cache in user's home directory for proper permissions and portability
CACHE_FILE = pl.Path.home() / ".m365_mcp_token_cache.json"

# MSAL treats OIDC scopes such as offline_access as reserved and adds them
# internally, so callers must only provide Graph scopes.
SCOPES = ["https://graph.microsoft.com/.default"]
DEVICE_FLOW_SCOPES = SCOPES
INTERACTIVE_AUTH_ENV_VAR = "M365_MCP_INTERACTIVE_AUTH"
# Flow key recording which tenant authority issued a device code, so the
# code is redeemed against the same authority.
DEVICE_FLOW_TENANT_KEY = "_m365_tenant_id"
# Only personal Microsoft accounts are supported (concept D1). Every
# personal account's home tenant is the fixed Microsoft-account tenant.
DEFAULT_TENANT_ID = "consumers"
PERSONAL_TENANT_ID = "9188040d-6c67-4c5b-b112-36a304b66dad"

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


class AuthenticationError(RuntimeError):
    """Raised when a device-code or MSAL sign-in attempt fails."""


class SignInRequiredError(RuntimeError):
    """Raised when an account has no usable refresh token and must sign in."""


class PersonalAccountRequiredError(ValueError):
    """Raised when a work or school account completes sign-in."""


class Account(NamedTuple):
    username: str
    account_id: str


class ReauthenticationResult(NamedTuple):
    account: Account
    expires_in: int | None


class AccountRemovalResult(NamedTuple):
    account: Account
    token_cache_removed: bool
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
        tenant_id: Tenant segment for the authority (for example,
            "consumers").

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
        raise AuthenticationError(error_message)

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


def get_app() -> tuple[msal.PublicClientApplication, str]:
    """Return the MSAL app for the configured authority and its tenant.

    ``M365_MCP_TENANT_ID`` defaults to ``consumers`` (personal accounts).
    """
    tenant_id = os.getenv("M365_MCP_TENANT_ID", DEFAULT_TENANT_ID)
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


def _account_from_msal(account: dict[str, str]) -> Account:
    """Convert an MSAL account dictionary into this module's public Account."""
    return Account(username=account["username"], account_id=account["home_account_id"])


def _home_tenant(result: dict[str, Any], account: dict[str, str]) -> str:
    """Return the home tenant of a signed-in account.

    The id_token ``tid`` claim is preferred; MSAL's ``home_account_id``
    (``<object id>.<tenant id>``) is the fallback.
    """
    claims = result.get("id_token_claims")
    if isinstance(claims, dict) and claims.get("tid"):
        return str(claims["tid"]).lower()
    return account.get("home_account_id", "").rpartition(".")[2].lower()


def finish_device_flow_sign_in(
    app: msal.PublicClientApplication, result: dict[str, Any]
) -> Account:
    """Return the account a successful device flow signed in.

    Work and school accounts are removed from the token cache again and
    rejected, because only personal Microsoft accounts are supported.

    Args:
        app: MSAL app that redeemed the device code.
        result: Successful MSAL token result from the device flow.

    Returns:
        The signed-in personal account.

    Raises:
        PersonalAccountRequiredError: If a work or school account signed in.
        RuntimeError: If MSAL cached no account for the sign-in.
    """
    accounts = app.get_accounts()
    if not accounts:
        raise RuntimeError("Authentication succeeded but no account was found")

    claims = result.get("id_token_claims")
    username = claims.get("preferred_username", "") if isinstance(claims, dict) else ""
    account = next(
        (a for a in accounts if a.get("username", "").lower() == username.lower()),
        accounts[-1],
    )

    if _home_tenant(result, account) != PERSONAL_TENANT_ID:
        app.remove_account(account)
        raise PersonalAccountRequiredError(
            "Only personal Microsoft accounts are supported. "
            f"{account.get('username', 'This account')} is a work or school "
            "account; sign in with a personal account (for example "
            "outlook.com, hotmail.com or live.com)."
        )

    return _account_from_msal(account)


def poll_device_flow_once(
    flow: dict[str, Any],
) -> tuple[msal.PublicClientApplication, dict[str, Any]]:
    """Poll a device flow once without blocking until it expires.

    The code is redeemed with the authority that issued it (the flow may
    have fallen back to the consumers authority).

    Args:
        flow: MSAL device flow from ``_initiate_device_flow``.

    Returns:
        The MSAL app used and its token result (an ``error`` of
        ``authorization_pending`` means the user has not finished).
    """
    flow_tenant = flow.get(DEVICE_FLOW_TENANT_KEY)
    if flow_tenant:
        app = _build_app(flow_tenant)
    else:
        app, _tenant_id = get_app()
    result = app.acquire_token_by_device_flow(flow, exit_condition=lambda _flow: True)
    return app, result


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
        raise AuthenticationError(
            f"Auth failed: {result.get('error_description', result['error'])}"
        )

    return result["access_token"]


def list_accounts() -> list[Account]:
    """List all authenticated Microsoft accounts.

    Returns:
        List of Account objects with username and account_id.
    """
    app, _ = get_app()
    return [_account_from_msal(a) for a in app.get_accounts()]


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
    """Remove an account, its cached token and its data cache.

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
    removed_account = _account_from_msal(account)

    # The persisted cache writes the removal to disk immediately.
    app.remove_account(account)
    token_cache_removed = True

    database_cache_removed = _remove_account_database_cache(removed_account.account_id)

    return AccountRemovalResult(
        account=removed_account,
        token_cache_removed=token_cache_removed,
        database_cache_removed=database_cache_removed,
    )


def authenticate_new_account() -> Account:
    """Authenticate a new personal account interactively.

    Returns:
        The signed-in account.

    Raises:
        PersonalAccountRequiredError: If a work or school account signed in.
        AuthenticationError: If the device flow fails.
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
    print("3. Sign in with your personal Microsoft account", file=sys.stderr)
    print("\nWaiting for authentication...", file=sys.stderr)

    result = app.acquire_token_by_device_flow(flow)

    if "error" in result:
        raise AuthenticationError(
            f"Auth failed: {result.get('error_description', result['error'])}"
        )

    return finish_device_flow_sign_in(app, result)
