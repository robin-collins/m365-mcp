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


@pytest.mark.parametrize(
    ("tool", "args", "expected"),
    [
        (
            "m365_list",
            {"resource": "event", "email_filter": {"unread": True}},
            (
                "Invalid email_filter: only valid with resource='email'. Expected: "
                "remove email_filter or use resource='email'"
            ),
        ),
        (
            "m365_list",
            {"resource": "drive_item", "container_id": "root", "path": "/Docs"},
            (
                "Invalid path: cannot be combined with container_id. Expected: one of "
                "container_id or path"
            ),
        ),
        (
            "m365_get",
            {"resource": "email"},
            "Invalid id: required unless resource='drive_item' with path",
        ),
        (
            "m365_create",
            {"resource": "calendar", "contact": {"given_name": "A"}},
            (
                "Invalid contact: resource is 'calendar'. Expected: supply only the "
                "'calendar' object"
            ),
        ),
        (
            "m365_update",
            {"resource": "contact", "id": "c1", "email_changes": {"is_read": True}},
            "Invalid email_changes: resource is 'contact'. Expected: contact_changes",
        ),
        (
            "m365_move",
            {"resource": "email", "id": "m1"},
            "Invalid destination_id: required",
        ),
        (
            "m365_delete",
            {"resource": "email", "id": "m1", "confirm": False},
            (
                "Invalid confirm 'False': delete requires confirm=True to proceed. "
                "Expected: Explicit user confirmation"
            ),
        ),
        (
            "m365_delete",
            {
                "resource": "email",
                "id": "m1",
                "confirm": True,
                "cancellation_message": "x",
            },
            "Invalid cancellation_message: only valid for resource='event'",
        ),
        (
            "m365_get_content",
            {"resource": "drive_item", "id": "i1", "mode": "vcard"},
            (
                "Invalid mode 'vcard': not valid for resource 'drive_item'. Expected: "
                "download or download_url"
            ),
        ),
        (
            "m365_get_content",
            {"resource": "email", "id": "m1", "mode": "download", "save_path": "a"},
            "Invalid attachment_id: required for resource='email'",
        ),
    ],
)
def test_generic_rules_use_spec_text(harness, tool, args, expected) -> None:
    assert harness.error(tool, args) == expected


def test_cursor_round_trip_is_bound_to_the_request() -> None:
    args = {"resource": "email", "limit": 5, "refresh": True}
    cursor = common.encode_cursor(args, "acc", "email", offset=5)
    decoded = common.decode_cursor(
        {**args, "cursor": cursor, "refresh": False}, "acc", "email"
    )
    assert decoded.offset == 5
    with pytest.raises(ValidationError, match="does not match this request"):
        common.decode_cursor({**args, "limit": 6, "cursor": cursor}, "acc", "email")
