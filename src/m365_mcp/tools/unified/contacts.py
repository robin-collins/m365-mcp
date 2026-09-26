"""Contact handlers: the ``contact`` and ``contact_folder`` resources of the
generic ``m365_*`` tools (tasks U3.1-U3.8).
"""

from __future__ import annotations

from typing import Any

import httpx
from fastmcp.exceptions import ToolError

from ...errors import DeadlineExceeded, GraphAPIError
from ...projections import project_contact, project_contact_folder
from ...services import contacts
from ...untrusted import sanitize_text
from ...validators import ValidationError
from .common import account, arg, check_rate, decode_cursor, encode_cursor, resource_op
from .drive import OUTCOME_UNKNOWN_DELETE, OUTCOME_UNKNOWN_MOVE, ambiguous_failure

Record = dict[str, Any]

# contact / contact_changes field -> Graph contact property
_CONTACT_FIELDS = {
    "given_name": "givenName",
    "surname": "surname",
    "display_name": "displayName",
    "mobile_phone": "mobilePhone",
    "business_phones": "businessPhones",
    "home_phones": "homePhones",
    "company_name": "companyName",
    "job_title": "jobTitle",
    "department": "department",
}


def _contact_body(fields: dict[str, Any], email_name: str | None = None) -> Record:
    """Convert contact fields to a Graph body (lists replace existing ones)."""
    body = {
        graph: fields[name] for name, graph in _CONTACT_FIELDS.items() if name in fields
    }
    if "emails" in fields:
        named = {"name": email_name} if email_name else {}
        body["emailAddresses"] = [
            {"address": address, **named} for address in fields["emails"]
        ]
    return body


def _label(record: Record) -> str:
    """Return a contact's display name for summaries."""
    name = record.get("display_name") or " ".join(
        part for part in (record.get("given_name"), record.get("surname")) if part
    )
    return sanitize_text(name) or record["id"]


def _page_result(
    args: dict[str, Any],
    account_id: str,
    resource: str,
    records: list[Record],
    next_link: str | None,
    summary: str,
) -> dict[str, Any]:
    next_cursor = (
        encode_cursor(args, account_id, resource, next_link=next_link)
        if next_link
        else None
    )
    summary += "; more available (pass next_cursor)." if next_cursor else "."
    return {
        "resource": resource,
        "items": records,
        "next_cursor": next_cursor,
        "has_more": next_cursor is not None,
        "summary": summary,
    }


def _count(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


# ----------------------------------------------------------------------
# m365_list
# ----------------------------------------------------------------------


@resource_op("m365_list", "contact")
def list_contacts(args: dict[str, Any]) -> dict[str, Any]:
    """List contacts: all contacts, or one contact folder's."""
    account_id = account(args)
    folder_id = args.get("container_id")
    check_rate(account_id, "normal")
    cursor = decode_cursor(args, account_id, "contact")
    items, next_link = contacts.list_contacts_page(
        account_id,
        folder_id=folder_id,
        limit=arg(args, "m365_list", "limit"),
        next_link=cursor.next_link if cursor else None,
    )
    records = [project_contact(item) for item in items]
    where = f"contact folder {folder_id}" if folder_id else "your contacts"
    summary = f"Returned {_count(len(records), 'contact')} from {where}"
    return _page_result(args, account_id, "contact", records, next_link, summary)


@resource_op("m365_list", "contact_folder")
def list_contact_folders(args: dict[str, Any]) -> dict[str, Any]:
    """List the contact folders."""
    account_id = account(args)
    check_rate(account_id, "normal")
    cursor = decode_cursor(args, account_id, "contact_folder")
    items, next_link = contacts.list_contact_folders_page(
        account_id,
        limit=arg(args, "m365_list", "limit"),
        next_link=cursor.next_link if cursor else None,
    )
    records = [project_contact_folder(item) for item in items]
    summary = f"Returned {_count(len(records), 'contact folder')}"
    return _page_result(args, account_id, "contact_folder", records, next_link, summary)


# ----------------------------------------------------------------------
# m365_get
# ----------------------------------------------------------------------


@resource_op("m365_get", "contact")
def get_contact(args: dict[str, Any]) -> dict[str, Any]:
    """Read one contact."""
    account_id = account(args)
    check_rate(account_id, "normal")
    record = project_contact(contacts.get_contact_item(account_id, args["id"]))
    return {
        "resource": "contact",
        "item": record,
        "summary": f"Contact {_label(record)}.",
    }


@resource_op("m365_get", "contact_folder")
def get_contact_folder(args: dict[str, Any]) -> dict[str, Any]:
    """Read one contact folder."""
    account_id = account(args)
    check_rate(account_id, "normal")
    record = project_contact_folder(contacts.get_contact_folder(account_id, args["id"]))
    return {
        "resource": "contact_folder",
        "item": record,
        "summary": f"Contact folder {sanitize_text(record['display_name'])}.",
    }


# ----------------------------------------------------------------------
# m365_get_content (vCard)
# ----------------------------------------------------------------------


@resource_op("m365_get_content", "contact")
def export_vcard(args: dict[str, Any]) -> dict[str, Any]:
    """Export a contact as a vCard 3.0 document."""
    account_id = account(args)
    check_rate(account_id, "normal")
    contact = contacts.get_contact_item(account_id, args["id"])
    return {
        "resource": "contact",
        "id": args["id"],
        "mode": "vcard",
        "saved_path": None,
        "size": None,
        "mime_type": "text/vcard",
        "download_url": None,
        "vcard": contacts.render_vcard(contact),
        "summary": f"Exported {_label(project_contact(contact))} as vCard.",
    }


# ----------------------------------------------------------------------
# m365_create
# ----------------------------------------------------------------------


@resource_op("m365_create", "contact")
def create_contact(args: dict[str, Any]) -> dict[str, Any]:
    """Create a contact in the main Contacts folder or a contact folder."""
    fields = dict(args["contact"])
    folder_id = fields.pop("folder_id", None)
    if "display_name" not in fields:
        default = " ".join(
            part for part in (fields.get("given_name"), fields.get("surname")) if part
        )
        fields["display_name"] = default
    account_id = account(args)
    check_rate(account_id, "normal")
    body = _contact_body(fields, email_name=fields["display_name"] or None)
    record = project_contact(
        contacts.create_contact_item(account_id, body, folder_id=folder_id)
    )
    return {
        "resource": "contact",
        "item": record,
        "summary": f"Created contact {_label(record)}.",
    }


@resource_op("m365_create", "contact_folder")
def create_contact_folder(args: dict[str, Any]) -> dict[str, Any]:
    """Create a contact folder at the top level or under a parent."""
    folder = args["contact_folder"]
    account_id = account(args)
    check_rate(account_id, "normal")
    record = project_contact_folder(
        contacts.create_contact_folder(
            account_id, folder["display_name"], parent_id=folder.get("parent_id")
        )
    )
    return {
        "resource": "contact_folder",
        "item": record,
        "summary": f"Created contact folder {sanitize_text(record['display_name'])}.",
    }


# ----------------------------------------------------------------------
# m365_update
# ----------------------------------------------------------------------


@resource_op("m365_update", "contact")
def update_contact(args: dict[str, Any]) -> dict[str, Any]:
    """Change contact fields; supplied lists replace the existing lists."""
    changes = args["contact_changes"]
    account_id = account(args)
    check_rate(account_id, "normal")
    contacts.patch_contact(account_id, args["id"], _contact_body(changes))
    fields = list(changes)
    return {
        "resource": "contact",
        "id": args["id"],
        "status": "updated",
        "changed_fields": fields,
        "summary": f"Updated contact: {', '.join(fields)}.",
    }


# ----------------------------------------------------------------------
# m365_move (emulated: create in destination, then delete the original)
# ----------------------------------------------------------------------


@resource_op("m365_move", "contact")
def move_contact(args: dict[str, Any]) -> dict[str, Any]:
    """Move a contact by recreating it in the destination folder.

    If the original cannot be deleted afterwards, the result reports
    ``copied_not_removed`` with both IDs instead of failing.
    """
    account_id = account(args)
    contact_id = args["id"]
    destination = args["destination_id"]
    check_rate(account_id, "normal")
    original = contacts.get_contact_item(account_id, contact_id)
    try:
        created = contacts.create_contact_item(
            account_id, contacts.contact_copy_body(original), folder_id=destination
        )
    except (GraphAPIError, httpx.TransportError) as exc:
        if ambiguous_failure(exc):
            raise ToolError(OUTCOME_UNKNOWN_MOVE) from None
        raise
    new_id = created["id"]
    name = _label(project_contact(original))
    try:
        contacts.delete_contact_item(account_id, contact_id)
    except (GraphAPIError, httpx.HTTPError, DeadlineExceeded):
        status = "copied_not_removed"
        summary = (
            f"Copied contact {name} to the destination (new id {new_id}) but "
            f"could not remove the original ({contact_id}); delete it with "
            "m365_delete if it is no longer needed."
        )
    else:
        status = "moved"
        summary = f"Moved contact {name} (new id {new_id})."
    return {
        "resource": "contact",
        "previous_id": contact_id,
        "id": new_id,
        "status": status,
        "destination_id": created.get("parentFolderId") or destination,
        "summary": summary,
    }


# ----------------------------------------------------------------------
# m365_delete
# ----------------------------------------------------------------------


def _delete(account_id: str, delete: Any, item_id: str) -> None:
    check_rate(account_id, "sensitive")
    try:
        delete(account_id, item_id)
    except (GraphAPIError, httpx.TransportError) as exc:
        if ambiguous_failure(exc):
            raise ToolError(OUTCOME_UNKNOWN_DELETE) from None
        raise


@resource_op("m365_delete", "contact")
def delete_contact(args: dict[str, Any]) -> dict[str, Any]:
    """Delete a contact."""
    account_id = account(args)
    _delete(account_id, contacts.delete_contact_item, args["id"])
    return {
        "resource": "contact",
        "id": args["id"],
        "status": "deleted",
        "recoverable": False,
        "summary": f"Deleted contact {args['id']}.",
    }


@resource_op("m365_delete", "contact_folder")
def delete_contact_folder(args: dict[str, Any]) -> dict[str, Any]:
    """Delete a contact folder and its contacts; the alias is refused."""
    if args["id"].lower() == contacts.DEFAULT_CONTACT_FOLDER:
        raise ValidationError(
            "Invalid id: the default contact folder cannot be deleted"
        )
    account_id = account(args)
    _delete(account_id, contacts.delete_contact_folder, args["id"])
    return {
        "resource": "contact_folder",
        "id": args["id"],
        "status": "deleted",
        "recoverable": False,
        "summary": f"Deleted contact folder {args['id']} and its contacts.",
    }
