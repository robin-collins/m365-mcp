from typing import Any
from ..mcp_instance import mcp
from .. import graph
from ..validators import (
    ValidationError,
    format_validation_error,
    require_confirm,
    validate_email_format,
    validate_json_payload,
    validate_limit,
)

ALLOWED_CONTACT_UPDATE_KEYS = {
    "givenName",
    "surname",
    "displayName",
    "emailAddresses",
    "businessPhones",
    "homePhones",
    "mobilePhone",
    "jobTitle",
    "companyName",
    "department",
}


def _normalise_phone_list(phones: Any, param_name: str) -> list[str]:
    """Validate and normalise phone number lists."""
    if not isinstance(phones, list):
        raise ValidationError(
            format_validation_error(
                param_name,
                phones,
                "must be a list of phone numbers",
                "List of non-empty strings",
            )
        )
    normalised: list[str] = []
    for index, phone in enumerate(phones):
        if not isinstance(phone, str):
            raise ValidationError(
                format_validation_error(
                    f"{param_name}[{index}]",
                    phone,
                    "must be a string",
                    "Phone number string",
                )
            )
        trimmed = phone.strip()
        if not trimmed:
            raise ValidationError(
                format_validation_error(
                    f"{param_name}[{index}]",
                    phone,
                    "cannot be empty",
                    "Non-empty phone number",
                )
            )
        normalised.append(trimmed)
    return normalised


def _normalise_email_addresses(addresses: Any) -> list[dict[str, str]]:
    """Validate and normalise contact email addresses."""
    if not isinstance(addresses, list):
        raise ValidationError(
            format_validation_error(
                "updates.emailAddresses",
                addresses,
                "must be a list of email objects",
                "List of {'address': str, 'name': str?}",
            )
        )
    result: list[dict[str, str]] = []
    for index, entry in enumerate(addresses):
        if isinstance(entry, str):
            result.append(
                {
                    "address": validate_email_format(
                        entry,
                        f"updates.emailAddresses[{index}]",
                    ),
                }
            )
            continue
        entry_payload = validate_json_payload(
            entry,
            required_keys=("address",),
            allowed_keys=("address", "name"),
            param_name=f"updates.emailAddresses[{index}]",
        )
        address = validate_email_format(
            entry_payload["address"],
            f"updates.emailAddresses[{index}].address",
        )
        normalised_entry: dict[str, str] = {"address": address}
        if "name" in entry_payload:
            name_value = entry_payload["name"]
            if not isinstance(name_value, str):
                raise ValidationError(
                    format_validation_error(
                        f"updates.emailAddresses[{index}].name",
                        name_value,
                        "must be a string",
                        "Display name string",
                    )
                )
            normalised_entry["name"] = name_value.strip()
        result.append(normalised_entry)
    return result


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
        limit: Maximum contacts to return (1-500, default: 50)

    Returns:
        List of contact objects
    """
    limit = validate_limit(limit, 1, 500, "limit")
    params = {"$top": limit}

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

    Allowed update keys: givenName, surname, displayName, emailAddresses,
    businessPhones, homePhones, mobilePhone, jobTitle, companyName, department.

    Args:
        contact_id: The contact ID to update
        updates: Dictionary with fields to update
        account_id: Microsoft account ID

    Returns:
        Updated contact object
    """
    payload = validate_json_payload(
        updates,
        allowed_keys=ALLOWED_CONTACT_UPDATE_KEYS,
        param_name="updates",
    )
    if not payload:
        raise ValidationError(
            format_validation_error(
                "updates",
                payload,
                "must include at least one field",
                f"Subset of {sorted(ALLOWED_CONTACT_UPDATE_KEYS)}",
            )
        )

    graph_updates: dict[str, Any] = {}

    for field in (
        "givenName",
        "surname",
        "displayName",
        "jobTitle",
        "companyName",
        "department",
    ):
        if field in payload:
            value = payload[field]
            if not isinstance(value, str):
                raise ValidationError(
                    format_validation_error(
                        f"updates.{field}",
                        value,
                        "must be a string",
                        "Text value",
                    )
                )
            graph_updates[field] = value.strip()

    if "emailAddresses" in payload:
        graph_updates["emailAddresses"] = _normalise_email_addresses(
            payload["emailAddresses"]
        )

    if "businessPhones" in payload:
        graph_updates["businessPhones"] = _normalise_phone_list(
            payload["businessPhones"],
            "updates.businessPhones",
        )

    if "homePhones" in payload:
        graph_updates["homePhones"] = _normalise_phone_list(
            payload["homePhones"],
            "updates.homePhones",
        )

    if "mobilePhone" in payload:
        mobile_phone = payload["mobilePhone"]
        if mobile_phone is None:
            graph_updates["mobilePhone"] = None
        elif not isinstance(mobile_phone, str):
            raise ValidationError(
                format_validation_error(
                    "updates.mobilePhone",
                    mobile_phone,
                    "must be a string",
                    "Phone number string",
                )
            )
        else:
            trimmed = mobile_phone.strip()
            if not trimmed:
                raise ValidationError(
                    format_validation_error(
                        "updates.mobilePhone",
                        mobile_phone,
                        "cannot be empty",
                        "Non-empty phone number",
                    )
                )
            graph_updates["mobilePhone"] = trimmed

    result = graph.request(
        "PATCH", f"/me/contacts/{contact_id}", account_id, json=graph_updates
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
