"""Account listing and device-flow orchestration over ``auth``."""

import ast
from typing import Any

from .. import auth


def list_accounts() -> list[dict[str, str]]:
    """List signed-in accounts as plain dictionaries.

    Returns:
        One dictionary per account with ``username``, ``account_id`` and
        ``account_type`` keys.
    """
    return [
        {
            "username": acc.username,
            "account_id": acc.account_id,
            "account_type": acc.account_type,
        }
        for acc in auth.list_accounts()
    ]


def begin_device_flow() -> dict[str, Any]:
    """Start device-flow authentication for a new account.

    Returns:
        Sign-in instructions, the device code, verification URL, expiry
        and the serialised flow under ``_flow_cache``.

    Raises:
        Exception: If MSAL does not return a device code.
    """
    app, tenant_id = auth.get_app()
    app, flow = auth._initiate_device_flow(app, tenant_id)

    if "user_code" not in flow:
        error_msg = flow.get("error_description", "Unknown error")
        raise Exception(f"Failed to get device code: {error_msg}")

    verification_url = flow.get(
        "verification_uri",
        flow.get("verification_url", "https://microsoft.com/devicelogin"),
    )

    return {
        "status": "authentication_required",
        "instructions": "To authenticate a new Microsoft account:",
        "step1": f"Visit: {verification_url}",
        "step2": f"Enter code: {flow['user_code']}",
        "step3": "Sign in with the Microsoft account you want to add",
        "step4": "After authenticating, use the 'complete_authentication' tool to finish the process",
        "device_code": flow["user_code"],
        "verification_url": verification_url,
        "expires_in": flow.get("expires_in", 900),
        "_flow_cache": str(flow),
    }


def complete_device_flow(flow_cache: str) -> dict[str, Any]:
    """Poll once to complete a device flow started by ``begin_device_flow``.

    Args:
        flow_cache: The ``_flow_cache`` string returned when the flow began.

    Returns:
        A ``success`` result with the account details, a ``pending`` status
        while the user has not finished signing in, or an ``error`` status
        if no account was cached.

    Raises:
        ValueError: If ``flow_cache`` is not a valid literal mapping.
        Exception: If MSAL reports an error other than a pending sign-in.
    """
    try:
        flow = ast.literal_eval(flow_cache)
    except (ValueError, SyntaxError):
        raise ValueError("Invalid flow cache data")

    # Redeem the code with the same authority that issued it (the device
    # flow may have fallen back to the consumers authority).
    flow_tenant = flow.get(auth.DEVICE_FLOW_TENANT_KEY)
    if flow_tenant:
        app = auth._build_app(flow_tenant)
    else:
        app, _tenant_id = auth.get_app()
    # Poll once instead of blocking until the device code expires.
    result = app.acquire_token_by_device_flow(flow, exit_condition=lambda _flow: True)

    if "error" in result:
        error_msg = result.get("error_description", result["error"])
        if result["error"] == "authorization_pending":
            return {
                "status": "pending",
                "message": "Authentication is still pending. The user needs to complete the authentication process.",
                "instructions": "Please ensure you've visited the URL and entered the code, then try again.",
            }
        raise Exception(f"Authentication failed: {error_msg}")

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
        account_type = auth._get_account_type(account_id, matched_account["username"])

        return {
            "status": "success",
            "username": matched_account["username"],
            "account_id": account_id,
            "account_type": account_type,
            "message": f"Successfully authenticated {matched_account['username']}",
        }

    return {
        "status": "error",
        "message": "Authentication succeeded but no account was found",
    }
