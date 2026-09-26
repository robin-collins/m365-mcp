"""Tests for optional ``account_id`` resolution (task U2.10, concept D6)."""

from __future__ import annotations

import pytest

from src.m365_mcp.auth import Account, SignInRequiredError
from src.m365_mcp.services import accounts
from src.m365_mcp.validators import ValidationError

ADA = Account(username="Ada@Example.com", account_id="acc-1")
GRACE = Account(username="grace@example.com", account_id="acc-2")


@pytest.fixture
def signed_in(monkeypatch: pytest.MonkeyPatch):
    """Return a setter that fixes the signed-in accounts."""

    def _set(*signed: Account) -> None:
        monkeypatch.setattr(accounts.auth, "list_accounts", lambda: list(signed))

    return _set


def test_zero_accounts_points_to_authenticate_script(signed_in) -> None:
    signed_in()

    with pytest.raises(SignInRequiredError, match="uv run authenticate.py"):
        accounts.resolve_account_id(None)


def test_zero_accounts_with_explicit_value_points_to_authenticate_script(
    signed_in,
) -> None:
    signed_in()

    with pytest.raises(SignInRequiredError, match="uv run authenticate.py"):
        accounts.resolve_account_id("acc-1")


def test_one_account_is_the_default(signed_in) -> None:
    signed_in(ADA)

    assert accounts.resolve_account_id(None) == "acc-1"


def test_one_account_accepts_id(signed_in) -> None:
    signed_in(ADA)

    assert accounts.resolve_account_id("acc-1") == "acc-1"


def test_email_match_is_case_insensitive(signed_in) -> None:
    signed_in(ADA, GRACE)

    assert accounts.resolve_account_id("ada@EXAMPLE.com") == "acc-1"
    assert accounts.resolve_account_id(" GRACE@example.com ") == "acc-2"


def test_two_accounts_require_a_choice_and_list_them(signed_in) -> None:
    signed_in(ADA, GRACE)

    with pytest.raises(ValidationError) as excinfo:
        accounts.resolve_account_id(None)

    message = str(excinfo.value)
    assert message.startswith("Invalid account_id")
    assert "acc-1 (Ada@Example.com)" in message
    assert "acc-2 (grace@example.com)" in message


def test_two_accounts_accept_id(signed_in) -> None:
    signed_in(ADA, GRACE)

    assert accounts.resolve_account_id("acc-2") == "acc-2"


def test_unknown_value_lists_valid_accounts(signed_in) -> None:
    signed_in(ADA, GRACE)

    with pytest.raises(ValidationError) as excinfo:
        accounts.resolve_account_id("nobody@example.com")

    message = str(excinfo.value)
    assert "no signed-in account matches" in message
    assert "Expected: one of acc-1 (Ada@Example.com), acc-2 (grace@example.com)" in (
        message
    )


def test_blank_value_is_rejected(signed_in) -> None:
    signed_in(ADA)

    with pytest.raises(ValidationError, match="cannot be empty"):
        accounts.resolve_account_id("   ")
