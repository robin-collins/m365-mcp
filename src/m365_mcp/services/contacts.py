"""Contacts service: Microsoft Graph logic for Outlook contacts."""

from typing import Any

from .. import graph

# ----------------------------------------------------------------------
# Unified tool surface (m365_* contact and contact_folder resources)
# ----------------------------------------------------------------------

# Contact folder alias for the main Contacts folder (concept §5).
DEFAULT_CONTACT_FOLDER = "default"

# Graph fields never copied when a contact is recreated in another folder.
_MOVE_EXCLUDED_KEYS = frozenset(
    {"id", "changeKey", "parentFolderId", "createdDateTime", "lastModifiedDateTime"}
)

# vCard 3.0 (RFC 2426) text escaping, applied in this order.
_VCARD_ESCAPES = (
    ("\\", "\\\\"),
    ("\r\n", "\\n"),
    ("\n", "\\n"),
    (",", "\\,"),
    (";", "\\;"),
)


def _contacts_collection(folder_id: str | None) -> str:
    """Return the contacts endpoint of a folder (``None``: main contacts)."""
    if folder_id is None or folder_id == DEFAULT_CONTACT_FOLDER:
        return "/me/contacts"
    return f"/me/contactFolders/{folder_id}/contacts"


def _page(
    account_id: str, path: str, params: dict[str, Any], next_link: str | None
) -> tuple[list[dict[str, Any]], str | None]:
    """Read one page of a Graph collection (first page or a nextLink)."""
    if next_link:
        result = graph.request("GET", next_link.replace(graph.BASE_URL, ""), account_id)
    else:
        result = graph.request("GET", path, account_id, params=params)
    result = result or {}
    return list(result.get("value") or []), result.get("@odata.nextLink")


def list_contacts_page(
    account_id: str,
    *,
    folder_id: str | None = None,
    limit: int = 20,
    next_link: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Read one page of contacts, ordered by display name.

    Args:
        account_id: Microsoft account ID.
        folder_id: Contact folder ID, ``"default"`` or ``None`` for
            ``/me/contacts``.
        limit: Page size.
        next_link: Graph ``@odata.nextLink`` from the previous page.

    Returns:
        The Graph contacts on this page and the next page's link, if any.
    """
    params = {"$top": limit, "$orderby": "displayName"}
    return _page(account_id, _contacts_collection(folder_id), params, next_link)


def list_contact_folders_page(
    account_id: str,
    *,
    limit: int = 20,
    next_link: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Read one page of the top-level contact folders.

    Args:
        account_id: Microsoft account ID.
        limit: Page size.
        next_link: Graph ``@odata.nextLink`` from the previous page.

    Returns:
        The Graph contact folders on this page and the next page's link.
    """
    return _page(account_id, "/me/contactFolders", {"$top": limit}, next_link)


def get_contact_item(account_id: str, contact_id: str) -> dict[str, Any]:
    """Read one contact (``GET /me/contacts/{id}``) without caching.

    Args:
        account_id: Microsoft account ID.
        contact_id: Contact ID.

    Returns:
        The Graph contact.
    """
    return graph.request("GET", f"/me/contacts/{contact_id}", account_id) or {}


def get_contact_folder(account_id: str, folder_id: str) -> dict[str, Any]:
    """Read one contact folder (``GET /me/contactFolders/{id}``).

    Args:
        account_id: Microsoft account ID.
        folder_id: Contact folder ID.

    Returns:
        The Graph contact folder.
    """
    return graph.request("GET", f"/me/contactFolders/{folder_id}", account_id) or {}


def create_contact_item(
    account_id: str, body: dict[str, Any], *, folder_id: str | None = None
) -> dict[str, Any]:
    """Create a contact from a Graph body, optionally in a folder.

    Args:
        account_id: Microsoft account ID.
        body: Graph contact fields.
        folder_id: Contact folder ID, ``"default"`` or ``None`` for the
            main Contacts folder.

    Returns:
        The created Graph contact.
    """
    path = _contacts_collection(folder_id)
    return graph.request("POST", path, account_id, json=body) or {}


def create_contact_folder(
    account_id: str, display_name: str, *, parent_id: str | None = None
) -> dict[str, Any]:
    """Create a contact folder at the top level or under ``parent_id``.

    Args:
        account_id: Microsoft account ID.
        display_name: Folder name.
        parent_id: Parent contact folder ID, or ``None`` for the top level.

    Returns:
        The created Graph contact folder.
    """
    path = (
        f"/me/contactFolders/{parent_id}/childFolders"
        if parent_id
        else "/me/contactFolders"
    )
    body = {"displayName": display_name}
    return graph.request("POST", path, account_id, json=body) or {}


def patch_contact(
    account_id: str, contact_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    """Patch a contact (``PATCH /me/contacts/{id}``).

    Args:
        account_id: Microsoft account ID.
        contact_id: Contact ID.
        body: Graph contact fields to change.

    Returns:
        The updated Graph contact (empty when Graph returns no body).
    """
    path = f"/me/contacts/{contact_id}"
    return graph.request("PATCH", path, account_id, json=body) or {}


def delete_contact_item(account_id: str, contact_id: str) -> None:
    """Delete a contact (``DELETE /me/contacts/{id}``)."""
    graph.request("DELETE", f"/me/contacts/{contact_id}", account_id)


def delete_contact_folder(account_id: str, folder_id: str) -> None:
    """Delete a contact folder (``DELETE /me/contactFolders/{id}``)."""
    graph.request("DELETE", f"/me/contactFolders/{folder_id}", account_id)


def contact_copy_body(contact: dict[str, Any]) -> dict[str, Any]:
    """Return the writable fields of a Graph contact, for recreating it.

    Args:
        contact: Graph contact as read with ``GET /me/contacts/{id}``.

    Returns:
        The contact without its ID, folder, timestamps and ``@odata`` keys.
    """
    return {
        key: value
        for key, value in contact.items()
        if key not in _MOVE_EXCLUDED_KEYS and not key.startswith("@odata")
    }


def _vcard_text(value: str) -> str:
    for raw, escaped in _VCARD_ESCAPES:
        value = value.replace(raw, escaped)
    return value


def render_vcard(contact: dict[str, Any]) -> str:
    """Render a Graph contact as a vCard 3.0 document (RFC 2426).

    Values are escaped (backslash, comma, semicolon, newline); ``N`` is
    written only when the contact has a given name or surname.

    Args:
        contact: Graph contact.

    Returns:
        The vCard with CRLF line breaks and no trailing line break.
    """
    given = contact.get("givenName") or ""
    surname = contact.get("surname") or ""
    display = contact.get("displayName") or f"{given} {surname}".strip()
    lines = ["BEGIN:VCARD", "VERSION:3.0", f"FN:{_vcard_text(display)}"]
    if given or surname:
        lines.append(f"N:{_vcard_text(surname)};{_vcard_text(given)};;;")
    emails = [
        e["address"] for e in contact.get("emailAddresses") or [] if e.get("address")
    ]
    for index, address in enumerate(emails):
        kind = "INTERNET,PREF" if index == 0 else "INTERNET"
        lines.append(f"EMAIL;TYPE={kind}:{_vcard_text(address)}")
    if contact.get("mobilePhone"):
        lines.append(f"TEL;TYPE=CELL:{_vcard_text(contact['mobilePhone'])}")
    for phone in contact.get("businessPhones") or []:
        lines.append(f"TEL;TYPE=WORK,VOICE:{_vcard_text(phone)}")
    for phone in contact.get("homePhones") or []:
        lines.append(f"TEL;TYPE=HOME,VOICE:{_vcard_text(phone)}")
    company = contact.get("companyName") or ""
    department = contact.get("department") or ""
    if company or department:
        lines.append(f"ORG:{_vcard_text(company)};{_vcard_text(department)}")
    if contact.get("jobTitle"):
        lines.append(f"TITLE:{_vcard_text(contact['jobTitle'])}")
    lines.append("END:VCARD")
    return "\r\n".join(lines)
