"""Account listing and device-flow orchestration over ``auth``."""

import ast
from typing import Any

from .. import auth
from ..validators import (
    ValidationError,
    format_validation_error,
    validate_account_id,
)


def resolve_account_id(account_id: str | None) -> str:
    """Resolve an optional account ID or email to a signed-in account ID.

    Omitted means the only signed-in account. With several accounts, the
    caller must choose one; the error lists each ID and email.

    Args:
        account_id: Account ID or email address (case-insensitive), or
            ``None`` to use the only signed-in account.

    Returns:
        The account ID of the selected signed-in account.

    Raises:
        auth.SignInRequiredError: If no account is signed in.
        ValidationError: If the value is blank or matches no account, or
            if it is omitted while several accounts are signed in.
    """
    signed_in = auth.list_accounts()
    if not signed_in:
        raise auth.SignInRequiredError(
            "No Microsoft account is signed in. Run `uv run authenticate.py` "
            "to sign in, then retry."
        )

    choices = "one of " + ", ".join(
        f"{acc.account_id} ({acc.username})" for acc in signed_in
    )
    if account_id is None:
        if len(signed_in) == 1:
            return signed_in[0].account_id
        raise ValidationError(
            format_validation_error(
                "account_id", "", "several accounts are signed in", choices
            )
        )

    selector = validate_account_id(account_id).lower()
    for acc in signed_in:
        if selector in (acc.account_id.lower(), acc.username.lower()):
            return acc.account_id
    raise ValidationError(
        format_validation_error(
            "account_id", account_id, "no signed-in account matches", choices
        )
    )


def list_accounts() -> list[dict[str, str]]:
    """List signed-in accounts as plain dictionaries.

    Returns:
        One dictionary per account with ``username``, ``account_id`` and
        ``account_type`` keys. Only personal accounts are supported, so
        ``account_type`` is always ``"personal"`` (legacy output shape).
    """
    return [
        {
            "username": acc.username,
            "account_id": acc.account_id,
            "account_type": "personal",
        }
        for acc in auth.list_accounts()
    ]


def list_account_records() -> list[dict[str, str | None]]:
    """List signed-in accounts as ``account_list`` records.

    Returns:
        One ``{"account_id", "email", "display_name"}`` dictionary per
        account. ``display_name`` is ``None`` unless the account object
        carries one (the MSAL cache does not record it today).
    """
    return [
        {
            "account_id": acc.account_id,
            "email": acc.username,
            "display_name": getattr(acc, "display_name", None),
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
        auth.PersonalAccountRequiredError: If a work or school account
            signed in.
        Exception: If MSAL reports an error other than a pending sign-in.
    """
    try:
        flow = ast.literal_eval(flow_cache)
    except (ValueError, SyntaxError):
        raise ValueError("Invalid flow cache data")

    app, result = auth.poll_device_flow_once(flow)

    if "error" in result:
        error_msg = result.get("error_description", result["error"])
        if result["error"] == "authorization_pending":
            return {
                "status": "pending",
                "message": "Authentication is still pending. The user needs to complete the authentication process.",
                "instructions": "Please ensure you've visited the URL and entered the code, then try again.",
            }
        raise Exception(f"Authentication failed: {error_msg}")

    if not app.get_accounts():
        return {
            "status": "error",
            "message": "Authentication succeeded but no account was found",
        }

    account = auth.finish_device_flow_sign_in(app, result)
    return {
        "status": "success",
        "username": account.username,
        "account_id": account.account_id,
        "account_type": "personal",
        "message": f"Successfully authenticated {account.username}",
    }
