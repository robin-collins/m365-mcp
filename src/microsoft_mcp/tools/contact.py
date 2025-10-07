from typing import Any
from ..mcp_instance import mcp
from .. import graph
from ..validators import require_confirm


# contact_list
@mcp.tool(
    name="contact_list",
    annotations={
        "title": "List Contacts",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "contact", "safety_level": "safe"},
)
def contact_list(account_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """📖 List contacts (read-only, safe for unsupervised use)

    Returns contacts with names, email addresses, and phone numbers.

    Args:
        account_id: Microsoft account ID
        limit: Maximum contacts to return (default: 50)

    Returns:
        List of contact objects
    """
    params = {"$top": min(limit, 100)}

    contacts = list(
        graph.request_paginated("/me/contacts", account_id, params=params, limit=limit)
    )

    return contacts


# contact_get
@mcp.tool(
    name="contact_get",
    annotations={
        "title": "Get Contact",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "contact", "safety_level": "safe"},
)
def contact_get(contact_id: str, account_id: str) -> dict[str, Any]:
    """📖 Get contact details (read-only, safe for unsupervised use)

    Returns complete contact information including all fields.

    Args:
        contact_id: The contact ID
        account_id: Microsoft account ID

    Returns:
        Complete contact object
    """
    result = graph.request("GET", f"/me/contacts/{contact_id}", account_id)
    if not result:
        raise ValueError(f"Contact with ID {contact_id} not found")
    return result


# contact_create
@mcp.tool(
    name="contact_create",
    annotations={
        "title": "Create Contact",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    meta={"category": "contact", "safety_level": "moderate"},
)
def contact_create(
    account_id: str,
    given_name: str,
    surname: str | None = None,
    email_addresses: str | list[str] | None = None,
    phone_numbers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """✏️ Create a new contact (requires user confirmation recommended)

    Creates a contact with name, email addresses, and phone numbers.

    Args:
        account_id: Microsoft account ID
        given_name: First name (required)
        surname: Last name (optional)
        email_addresses: Email address(es) (optional)
        phone_numbers: Phone numbers dict with keys: business, home, mobile (optional)

    Returns:
        Created contact object with ID
    """
    contact: dict[str, Any] = {"givenName": given_name}

    if surname:
        contact["surname"] = surname

    if email_addresses:
        email_list = (
            [email_addresses] if isinstance(email_addresses, str) else email_addresses
        )
        contact["emailAddresses"] = [
            {"address": email, "name": f"{given_name} {surname or ''}".strip()}
            for email in email_list
        ]

    if phone_numbers:
        if "business" in phone_numbers:
            contact["businessPhones"] = [phone_numbers["business"]]
        if "home" in phone_numbers:
            contact["homePhones"] = [phone_numbers["home"]]
        if "mobile" in phone_numbers:
            contact["mobilePhone"] = phone_numbers["mobile"]

    result = graph.request("POST", "/me/contacts", account_id, json=contact)
    if not result:
        raise ValueError("Failed to create contact")
    return result


# contact_update
@mcp.tool(
    name="contact_update",
    annotations={
        "title": "Update Contact",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "contact", "safety_level": "moderate"},
)
def contact_update(
    contact_id: str, updates: dict[str, Any], account_id: str
) -> dict[str, Any]:
    """✏️ Update contact information (requires user confirmation recommended)

    Modifies contact fields like name, email, or phone numbers.

    Args:
        contact_id: The contact ID to update
        updates: Dictionary with fields to update
        account_id: Microsoft account ID

    Returns:
        Updated contact object
    """
    result = graph.request(
        "PATCH", f"/me/contacts/{contact_id}", account_id, json=updates
    )
    return result or {"status": "updated"}


# contact_delete
@mcp.tool(
    name="contact_delete",
    annotations={
        "title": "Delete Contact",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={
        "category": "contact",
        "safety_level": "critical",
        "requires_confirmation": True,
    },
)
def contact_delete(
    contact_id: str, account_id: str, confirm: bool = False
) -> dict[str, str]:
    """🔴 Delete a contact permanently (always require user confirmation)

    WARNING: This action permanently deletes the contact and cannot be undone.

    Args:
        contact_id: The contact to delete
        account_id: Microsoft account ID
        confirm: Must be True to confirm deletion (prevents accidents)

    Returns:
        Status confirmation
    """
    require_confirm(confirm, "delete contact")
    graph.request("DELETE", f"/me/contacts/{contact_id}", account_id)
    return {"status": "deleted"}
