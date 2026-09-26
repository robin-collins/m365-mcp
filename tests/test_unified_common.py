"""Tests for the shared unified-handler plumbing."""

from __future__ import annotations

import pytest

from m365_mcp.tools.unified import common
from m365_mcp.validators import ValidationError


def test_require_confirm_uses_spec_text() -> None:
    with pytest.raises(ValidationError) as info:
        common.require_confirm({}, "delete")
    assert str(info.value) == (
        "Invalid confirm 'False': delete requires confirm=True to proceed. "
        "Expected: Explicit user confirmation"
    )
    common.require_confirm({"confirm": True}, "delete")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "inbox"),
        ("Inbox", "inbox"),
        ("sent", "sentitems"),
        ("deleted", "deleteditems"),
        ("junk", "junkemail"),
        ("archive", "archive"),
        ("root", "msgfolderroot"),
        ("sentitems", "sentitems"),
        ("AAMkAGI2TG93AAA=", "AAMkAGI2TG93AAA="),
        ("folder-receipts", "folder-receipts"),
    ],
)
def test_resolve_mail_folder(value, expected) -> None:
    assert common.resolve_mail_folder(value, "container_id") == expected


def test_unknown_alias_is_rejected_with_spec_text() -> None:
    with pytest.raises(ValidationError) as info:
        common.resolve_mail_folder("Inbx", "container_id")
    assert str(info.value) == (
        "Invalid container_id 'Inbx': unknown folder alias. Expected: a folder "
        "ID or one of inbox, sent, drafts, deleted, junk, archive"
    )


def test_resource_op_rejects_resources_outside_the_spec_enum() -> None:
    with pytest.raises(KeyError):
        common.resource_op("m365_create", "email")
    with pytest.raises(KeyError):
        common.resource_op("email_send", "email")


def test_arg_reads_spec_defaults() -> None:
    assert common.arg({}, "m365_list", "limit") == 20
    assert common.arg({"limit": 5}, "m365_list", "limit") == 5


def test_account_defaults_to_the_single_signed_in_account(harness) -> None:
    assert common.account({}) == harness.account_id
    assert common.account({"account_id": harness.account_email.upper()}) == (
        harness.account_id
    )
