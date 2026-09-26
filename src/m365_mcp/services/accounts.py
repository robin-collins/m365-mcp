"""Account listing and device-flow orchestration over ``auth``."""

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
