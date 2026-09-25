from ..mcp_instance import mcp
from ..services import accounts


# account_list
@mcp.tool(
    name="account_list",
    annotations={
        "title": "List Accounts",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "account", "safety_level": "safe"},
)
def account_list() -> list[dict[str, str]]:
    """📖 List all signed-in Microsoft accounts (read-only, safe for unsupervised use)

    Returns a list of authenticated Microsoft accounts with their usernames, account IDs,
    and account types (personal or work/school).

    Returns:
        List of account dictionaries with:
        - username: Account email/username
        - account_id: Unique account identifier
        - account_type: "personal", "work_school", or "unknown"

    Example:
        [
            {
                "username": "user@outlook.com",
                "account_id": "abc123...",
                "account_type": "personal"
            },
            {
                "username": "user@contoso.com",
                "account_id": "def456...",
                "account_type": "work_school"
            }
        ]
    """
    return accounts.list_accounts()


# account_authenticate
@mcp.tool(
    name="account_authenticate",
    annotations={
        "title": "Authenticate Account",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    meta={"category": "account", "safety_level": "moderate"},
)
def account_authenticate() -> dict[str, str]:
    """✏️ Authenticate a new Microsoft account using device flow (requires user confirmation recommended)

    Initiates device flow authentication for adding a new Microsoft account.
    Returns authentication instructions with a device code and verification URL.

    The user must:
    1. Visit the verification URL
    2. Enter the device code
    3. Sign in with their Microsoft account
    4. Use account_complete_auth to finish the process
    """
    return accounts.begin_device_flow()


# account_complete_auth
@mcp.tool(
    name="account_complete_auth",
    annotations={
        "title": "Complete Authentication",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    meta={"category": "account", "safety_level": "moderate"},
)
def account_complete_auth(flow_cache: str) -> dict[str, str]:
    """✏️ Complete device flow authentication (requires user confirmation recommended)

    Completes the authentication process after the user has entered the device code
    at the verification URL.

    Args:
        flow_cache: The flow data returned from account_authenticate (the _flow_cache field)

    Returns:
        Account information if authentication was successful, or pending status if
        the user hasn't completed authentication yet.
    """
    return accounts.complete_device_flow(flow_cache)
