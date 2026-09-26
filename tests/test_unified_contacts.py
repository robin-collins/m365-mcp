"""Unified tools for the ``contact`` and ``contact_folder`` resources.

Covers the contact parts of m365_list, m365_get, m365_get_content (vCard),
m365_create, m365_update, m365_move and m365_delete (tasks U3.1-U3.8)
against the fake Graph.
"""

from __future__ import annotations

from typing import Any

import pytest

from m365_mcp.rate_limit import RateLimiter
from m365_mcp.tools.unified import common
from tests.unified_harness import UnifiedHarness

_CONFIRM_TEXT = (
    "Invalid confirm 'False': delete requires confirm=True to proceed. "
    "Expected: Explicit user confirmation"
)


@pytest.fixture(autouse=True)
def _fresh_rate_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give each test its own budget so deletes never hit the shared limit."""
    monkeypatch.setattr(common, "rate_limiter", RateLimiter())


def _seed_contact(harness: UnifiedHarness, contact_id: str, **fields: Any) -> None:
    contact = {
        "id": contact_id,
        "displayName": None,
        "givenName": None,
        "surname": None,
        "emailAddresses": [],
        "mobilePhone": None,
        "businessPhones": [],
        "homePhones": [],
        "companyName": None,
        "jobTitle": None,
        "department": None,
        "parentFolderId": "contacts-root",
    }
    contact.update(fields)
    harness.fake.contacts[contact_id] = contact


def _fail(status: int, code: str = "Boom") -> tuple[int, Any]:
    return status, {"error": {"code": code, "message": "failed"}}


# ----------------------------------------------------------------------
# m365_list
# ----------------------------------------------------------------------


def test_list_contacts_defaults_to_all_contacts(harness: UnifiedHarness) -> None:
    result = harness.ok("m365_list", {"resource": "contact"})

    assert result["resource"] == "contact"
    ids = {item["id"] for item in result["items"]}
    assert {"contact-jane", "contact-priya", "contact-anna"} <= ids
    assert result["has_more"] is False
    assert result["next_cursor"] is None
    assert harness.graph_calls("GET", "/me/contacts")
    jane = next(i for i in result["items"] if i["id"] == "contact-jane")
    assert jane["emails"] == ["jane.smith@example.com"]
    assert "contact" in result["summary"]


def test_list_contacts_in_folder(harness: UnifiedHarness) -> None:
    result = harness.ok(
        "m365_list", {"resource": "contact", "container_id": "cfolder-work"}
    )

    assert [item["id"] for item in result["items"]] == ["contact-priya"]
    assert harness.graph_calls("GET", "/me/contactFolders/cfolder-work/contacts")


def test_list_contacts_pages_with_cursor(harness: UnifiedHarness) -> None:
    first = harness.ok("m365_list", {"resource": "contact", "limit": 2})
    assert len(first["items"]) == 2
    assert first["has_more"] is True
    assert first["next_cursor"]

    second = harness.ok(
        "m365_list",
        {"resource": "contact", "limit": 2, "cursor": first["next_cursor"]},
    )
    assert len(second["items"]) == 2
    first_ids = {i["id"] for i in first["items"]}
    assert not first_ids & {i["id"] for i in second["items"]}


def test_list_contacts_cursor_from_other_request_is_refused(
    harness: UnifiedHarness,
) -> None:
    first = harness.ok("m365_list", {"resource": "contact", "limit": 2})

    text = harness.error(
        "m365_list",
        {"resource": "contact", "limit": 3, "cursor": first["next_cursor"]},
    )

    assert text == (
        "Invalid cursor: it does not match this request. "
        "Expected: repeat the call without cursor"
    )


def test_list_contact_folders(harness: UnifiedHarness) -> None:
    result = harness.ok("m365_list", {"resource": "contact_folder"})

    assert {i["id"] for i in result["items"]} == {"cfolder-family", "cfolder-work"}
    family = next(i for i in result["items"] if i["id"] == "cfolder-family")
    assert family == {
        "id": "cfolder-family",
        "display_name": "Family",
        "parent_id": "contacts-root",
    }
    assert harness.graph_calls("GET", "/me/contactFolders")


def test_list_contact_rejects_email_filter(harness: UnifiedHarness) -> None:
    text = harness.error(
        "m365_list", {"resource": "contact", "email_filter": {"unread": True}}
    )

    assert text == (
        "Invalid email_filter: only valid with resource='email'. "
        "Expected: remove email_filter or use resource='email'"
    )


# ----------------------------------------------------------------------
# m365_get
# ----------------------------------------------------------------------


def test_get_contact(harness: UnifiedHarness) -> None:
    result = harness.ok("m365_get", {"resource": "contact", "id": "contact-mark"})

    item = result["item"]
    assert item["id"] == "contact-mark"
    assert item["company_name"] == "Brown Engineering"
    assert item["business_phones"] == ["08 8111 2222"]
    assert item["department"] is None
    assert harness.graph_calls("GET", "/me/contacts/contact-mark")
    assert "Mark Brown" in result["summary"]


def test_get_contact_folder(harness: UnifiedHarness) -> None:
    result = harness.ok(
        "m365_get", {"resource": "contact_folder", "id": "cfolder-work"}
    )

    assert result["item"] == {
        "id": "cfolder-work",
        "display_name": "Work",
        "parent_id": "contacts-root",
    }
    assert harness.graph_calls("GET", "/me/contactFolders/cfolder-work")


def test_get_contact_requires_id(harness: UnifiedHarness) -> None:
    text = harness.error("m365_get", {"resource": "contact"})

    assert text == "Invalid id: required unless resource='drive_item' with path"


def test_get_missing_contact_is_actionable(harness: UnifiedHarness) -> None:
    text = harness.error("m365_get", {"resource": "contact", "id": "nope"})

    assert "No contact with that id" in text


# ----------------------------------------------------------------------
# m365_get_content (vCard)
# ----------------------------------------------------------------------


def test_get_content_vcard_example(harness: UnifiedHarness) -> None:
    _seed_contact(harness, "AQMkADAwATM3ZmYAZS1kCON", displayName="Jane Citizen")

    result = harness.ok(
        "m365_get_content",
        {"resource": "contact", "id": "AQMkADAwATM3ZmYAZS1kCON", "mode": "vcard"},
    )

    assert result == {
        "resource": "contact",
        "id": "AQMkADAwATM3ZmYAZS1kCON",
        "mode": "vcard",
        "saved_path": None,
        "size": None,
        "mime_type": "text/vcard",
        "download_url": None,
        "vcard": "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Jane Citizen\r\nEND:VCARD",
        "summary": "Exported Jane Citizen as vCard.",
    }
    assert harness.graph_calls("GET", "/me/contacts/AQMkADAwATM3ZmYAZS1kCON")


def test_get_content_vcard_full_contact_escapes_values(
    harness: UnifiedHarness,
) -> None:
    _seed_contact(
        harness,
        "contact-full",
        displayName="Smith, Jane",
        givenName="Jane",
        surname="Smith",
        emailAddresses=[{"address": "jane@example.com"}, {"address": "j@x.com"}],
        mobilePhone="0400 000 000",
        businessPhones=["08 1111 2222"],
        homePhones=["08 3333 4444"],
        companyName="Acme; Pty",
        department="Tax",
        jobTitle="Accountant",
    )

    vcard = harness.ok(
        "m365_get_content",
        {"resource": "contact", "id": "contact-full", "mode": "vcard"},
    )["vcard"]

    assert vcard.split("\r\n") == [
        "BEGIN:VCARD",
        "VERSION:3.0",
        "FN:Smith\\, Jane",
        "N:Smith;Jane;;;",
        "EMAIL;TYPE=INTERNET,PREF:jane@example.com",
        "EMAIL;TYPE=INTERNET:j@x.com",
        "TEL;TYPE=CELL:0400 000 000",
        "TEL;TYPE=WORK,VOICE:08 1111 2222",
        "TEL;TYPE=HOME,VOICE:08 3333 4444",
        "ORG:Acme\\; Pty;Tax",
        "TITLE:Accountant",
        "END:VCARD",
    ]


def test_get_content_vcard_mode_must_suit_resource(harness: UnifiedHarness) -> None:
    text = harness.error(
        "m365_get_content",
        {"resource": "contact", "id": "contact-jane", "mode": "download_url"},
    )

    assert text == (
        "Invalid mode 'download_url': not valid for resource 'contact'. Expected: vcard"
    )


# ----------------------------------------------------------------------
# m365_create
# ----------------------------------------------------------------------


def test_create_contact_in_folder_example(harness: UnifiedHarness) -> None:
    harness.fake.contact_folders["AQMkADAwATM3ZmYAZS1kCFLD"] = {
        "id": "AQMkADAwATM3ZmYAZS1kCFLD",
        "displayName": "Clients",
        "parentFolderId": "contacts-root",
    }

    result = harness.ok(
        "m365_create",
        {
            "resource": "contact",
            "contact": {
                "given_name": "Jane",
                "surname": "Citizen",
                "emails": ["jane@example.com"],
                "mobile_phone": "+61 400 000 000",
                "folder_id": "AQMkADAwATM3ZmYAZS1kCFLD",
            },
        },
    )

    item = result["item"]
    assert result["resource"] == "contact"
    assert item == {
        "id": item["id"],
        "display_name": "Jane Citizen",
        "given_name": "Jane",
        "surname": "Citizen",
        "emails": ["jane@example.com"],
        "mobile_phone": "+61 400 000 000",
        "business_phones": [],
        "home_phones": [],
        "company_name": None,
        "job_title": None,
        "department": None,
        "folder_id": "AQMkADAwATM3ZmYAZS1kCFLD",
    }
    assert result["summary"] == "Created contact Jane Citizen."
    (call,) = harness.graph_calls(
        "POST", "/me/contactFolders/AQMkADAwATM3ZmYAZS1kCFLD/contacts"
    )
    assert call.body == {
        "givenName": "Jane",
        "surname": "Citizen",
        "displayName": "Jane Citizen",
        "emailAddresses": [{"address": "jane@example.com", "name": "Jane Citizen"}],
        "mobilePhone": "+61 400 000 000",
    }


def test_create_contact_defaults_to_main_contacts(harness: UnifiedHarness) -> None:
    result = harness.ok(
        "m365_create",
        {
            "resource": "contact",
            "contact": {
                "given_name": "Bo",
                "display_name": "Bo the Builder",
                "business_phones": ["1", "2"],
                "home_phones": ["3"],
                "company_name": "Build Co",
                "job_title": "Builder",
                "department": "Works",
            },
        },
    )

    assert result["item"]["display_name"] == "Bo the Builder"
    (call,) = harness.graph_calls("POST", "/me/contacts")
    assert call.body == {
        "givenName": "Bo",
        "displayName": "Bo the Builder",
        "businessPhones": ["1", "2"],
        "homePhones": ["3"],
        "companyName": "Build Co",
        "jobTitle": "Builder",
        "department": "Works",
    }


def test_create_rejects_mismatched_sub_object(harness: UnifiedHarness) -> None:
    text = harness.error(
        "m365_create",
        {
            "resource": "calendar",
            "calendar": {"name": "Trips"},
            "contact": {"given_name": "Jane"},
        },
    )

    assert text == (
        "Invalid contact: resource is 'calendar'. "
        "Expected: supply only the 'calendar' object"
    )


def test_create_contact_folder_top_level(harness: UnifiedHarness) -> None:
    result = harness.ok(
        "m365_create",
        {"resource": "contact_folder", "contact_folder": {"display_name": "Club"}},
    )

    assert result["item"]["display_name"] == "Club"
    assert result["summary"] == "Created contact folder Club."
    (call,) = harness.graph_calls("POST", "/me/contactFolders")
    assert call.body == {"displayName": "Club"}


def test_create_contact_folder_under_parent(harness: UnifiedHarness) -> None:
    result = harness.ok(
        "m365_create",
        {
            "resource": "contact_folder",
            "contact_folder": {
                "display_name": "Cousins",
                "parent_id": "cfolder-family",
            },
        },
    )

    assert result["item"]["parent_id"] == "cfolder-family"
    (call,) = harness.graph_calls(
        "POST", "/me/contactFolders/cfolder-family/childFolders"
    )
    assert call.body == {"displayName": "Cousins"}


# ----------------------------------------------------------------------
# m365_update
# ----------------------------------------------------------------------


def test_update_contact_replaces_lists(harness: UnifiedHarness) -> None:
    result = harness.ok(
        "m365_update",
        {
            "resource": "contact",
            "id": "contact-mark",
            "contact_changes": {
                "job_title": "Principal Engineer",
                "business_phones": ["08 9999 0000"],
                "emails": ["mark@new.example"],
            },
        },
    )

    assert result == {
        "resource": "contact",
        "id": "contact-mark",
        "status": "updated",
        "changed_fields": ["job_title", "business_phones", "emails"],
        "summary": "Updated contact: job_title, business_phones, emails.",
    }
    (call,) = harness.graph_calls("PATCH", "/me/contacts/contact-mark")
    assert call.body == {
        "jobTitle": "Principal Engineer",
        "businessPhones": ["08 9999 0000"],
        "emailAddresses": [{"address": "mark@new.example"}],
    }
    assert harness.fake.contacts["contact-mark"]["businessPhones"] == ["08 9999 0000"]


def test_update_contact_rejects_other_changes_object(harness: UnifiedHarness) -> None:
    text = harness.error(
        "m365_update",
        {
            "resource": "contact",
            "id": "contact-mark",
            "email_changes": {"is_read": True},
        },
    )

    assert text == (
        "Invalid email_changes: resource is 'contact'. Expected: contact_changes"
    )


# ----------------------------------------------------------------------
# m365_move
# ----------------------------------------------------------------------


def test_move_contact_creates_copy_then_deletes_original(
    harness: UnifiedHarness,
) -> None:
    result = harness.ok(
        "m365_move",
        {"resource": "contact", "id": "contact-jane", "destination_id": "cfolder-work"},
    )

    assert result["status"] == "moved"
    assert result["previous_id"] == "contact-jane"
    assert result["destination_id"] == "cfolder-work"
    new_id = result["id"]
    assert new_id != "contact-jane"
    assert "contact-jane" not in harness.fake.contacts
    moved = harness.fake.contacts[new_id]
    assert moved["parentFolderId"] == "cfolder-work"
    assert moved["givenName"] == "Jane"
    assert moved["mobilePhone"] == "0412 111 222"
    (post,) = harness.graph_calls("POST", "/me/contactFolders/cfolder-work/contacts")
    assert "id" not in post.body
    assert "parentFolderId" not in post.body
    assert harness.graph_calls("DELETE", "/me/contacts/contact-jane")
    assert new_id in result["summary"]


def test_move_contact_to_default_folder(harness: UnifiedHarness) -> None:
    result = harness.ok(
        "m365_move",
        {"resource": "contact", "id": "contact-priya", "destination_id": "default"},
    )

    assert result["status"] == "moved"
    assert result["destination_id"] == "contacts-root"
    assert harness.graph_calls("POST", "/me/contacts")


def test_move_contact_reports_copied_not_removed(harness: UnifiedHarness) -> None:
    original = harness.fake._contact_item

    def refuse_delete(method, params, body, contact_id):
        if method == "DELETE":
            return _fail(403, "ErrorAccessDenied")
        return original(method, params, body, contact_id)

    harness.fake._contact_item = refuse_delete  # type: ignore[method-assign]

    result = harness.ok(
        "m365_move",
        {"resource": "contact", "id": "contact-jane", "destination_id": "cfolder-work"},
    )

    assert result["status"] == "copied_not_removed"
    assert result["previous_id"] == "contact-jane"
    assert result["id"] != "contact-jane"
    assert "contact-jane" in harness.fake.contacts
    assert result["id"] in result["summary"]
    assert "contact-jane" in result["summary"]


def test_move_contact_ambiguous_failure_is_not_retried(
    harness: UnifiedHarness,
) -> None:
    def broken(method, params, body, folder_id):
        return _fail(500, "InternalServerError")

    harness.fake._contact_folder_contacts = broken  # type: ignore[method-assign]

    text = harness.error(
        "m365_move",
        {"resource": "contact", "id": "contact-jane", "destination_id": "cfolder-work"},
    )

    assert text == "Outcome unknown: check the destination folder before retrying"
    assert len(harness.graph_calls("POST")) == 1
    assert not harness.graph_calls("DELETE")
    assert "contact-jane" in harness.fake.contacts


def test_move_requires_destination(harness: UnifiedHarness) -> None:
    text = harness.error("m365_move", {"resource": "contact", "id": "contact-jane"})

    assert text == "Invalid destination_id: required"


# ----------------------------------------------------------------------
# m365_delete
# ----------------------------------------------------------------------


def test_delete_contact_requires_confirm(harness: UnifiedHarness) -> None:
    text = harness.error(
        "m365_delete", {"resource": "contact", "id": "contact-sam", "confirm": False}
    )

    assert text == _CONFIRM_TEXT
    assert not harness.graph_calls("DELETE")


def test_delete_contact(harness: UnifiedHarness) -> None:
    result = harness.ok(
        "m365_delete", {"resource": "contact", "id": "contact-sam", "confirm": True}
    )

    assert result["resource"] == "contact"
    assert result["id"] == "contact-sam"
    assert result["status"] == "deleted"
    assert isinstance(result["recoverable"], bool)
    assert harness.graph_calls("DELETE", "/me/contacts/contact-sam")
    assert "contact-sam" not in harness.fake.contacts


def test_delete_contact_folder(harness: UnifiedHarness) -> None:
    result = harness.ok(
        "m365_delete",
        {"resource": "contact_folder", "id": "cfolder-work", "confirm": True},
    )

    assert result["status"] == "deleted"
    assert harness.graph_calls("DELETE", "/me/contactFolders/cfolder-work")


def test_delete_default_contact_folder_alias_is_refused(
    harness: UnifiedHarness,
) -> None:
    text = harness.error(
        "m365_delete",
        {"resource": "contact_folder", "id": "default", "confirm": True},
    )

    assert text == "Invalid id: the default contact folder cannot be deleted"
    assert not harness.graph_calls("DELETE")


def test_delete_rejects_cancellation_message(harness: UnifiedHarness) -> None:
    text = harness.error(
        "m365_delete",
        {
            "resource": "contact",
            "id": "contact-sam",
            "cancellation_message": "bye",
            "confirm": True,
        },
    )

    assert text == "Invalid cancellation_message: only valid for resource='event'"
