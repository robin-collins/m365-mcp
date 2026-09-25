"""Contacts service: Microsoft Graph logic for Outlook contacts."""

from datetime import datetime, timezone
from typing import Any

from .. import graph
from ..cache import CacheManager

_CONTACT_COPY_EXCLUDED_KEYS = (
    "id",
    "@odata.context",
    "@odata.etag",
    "createdDateTime",
    "lastModifiedDateTime",
)


def _cache_manager() -> CacheManager:
    """Return the shared cache manager.

    The singleton currently lives in ``tools.cache_tools``; it is imported
    lazily so this module does not import the tool layer at load time.
    """
    from ..cache import get_cache_manager

    return get_cache_manager()


def list_contacts(
    account_id: str,
    *,
    limit: int = 50,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """List the account's contacts, using the cache when allowed.

    Args:
        account_id: Microsoft account ID.
        limit: Maximum number of contacts to return (already validated).
        use_cache: Whether to read and write the cache.
        force_refresh: Skip the cache read and fetch from Graph.

    Returns:
        Contact objects, each annotated with ``_cache_status`` (and
        ``_cached_at`` when fetched from Graph).
    """
    cache_params = {
        "limit": limit,
    }

    if use_cache and not force_refresh:
        try:
            cache_manager = _cache_manager()
            cached_result = cache_manager.get_cached(
                account_id, "contact_list", cache_params
            )

            if cached_result:
                data, state = cached_result
                for contact in data:
                    contact["_cache_status"] = state.value
                return data
        except Exception:
            # If cache fails, continue to API call
            pass

    params = {"$top": limit}
    contacts = list(
        graph.request_paginated("/me/contacts", account_id, params=params, limit=limit)
    )

    cached_at = datetime.now(timezone.utc).isoformat()
    for contact in contacts:
        contact["_cache_status"] = "fresh"
        contact["_cached_at"] = cached_at

    if use_cache:
        try:
            cache_manager = _cache_manager()
            cache_manager.set_cached(account_id, "contact_list", cache_params, contacts)
        except Exception:
            # If cache storage fails, still return the result
            pass

    return contacts


def get_contact(
    account_id: str,
    *,
    contact_id: str,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Get one contact, using the cache when allowed.

    Args:
        account_id: Microsoft account ID.
        contact_id: The contact ID.
        use_cache: Whether to read and write the cache.
        force_refresh: Skip the cache read and fetch from Graph.

    Returns:
        Contact details annotated with ``_cache_status`` (and
        ``_cached_at`` when fetched from Graph).

    Raises:
        ValueError: If Graph returns no contact.
    """
    cache_params = {
        "contact_id": contact_id,
    }

    if use_cache and not force_refresh:
        try:
            cache_manager = _cache_manager()
            cached_result = cache_manager.get_cached(
                account_id, "contact_get", cache_params
            )

            if cached_result:
                data, state = cached_result
                data["_cache_status"] = state.value
                return data
        except Exception:
            # If cache fails, continue to API call
            pass

    result = graph.request("GET", f"/me/contacts/{contact_id}", account_id)
    if not result:
        raise ValueError(f"Contact with ID {contact_id} not found")

    result["_cache_status"] = "miss"  # Fresh from API
    result["_cached_at"] = datetime.now(timezone.utc).isoformat()

    if use_cache:
        try:
            cache_manager = _cache_manager()
            cache_manager.set_cached(account_id, "contact_get", cache_params, result)
        except Exception:
            # If cache storage fails, still return the result
            pass

    return result


def create_contact(
    account_id: str,
    *,
    given_name: str,
    surname: str | None = None,
    email_addresses: str | list[str] | None = None,
    phone_numbers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Create a contact.

    Args:
        account_id: Microsoft account ID.
        given_name: First name.
        surname: Last name.
        email_addresses: One address or a list of addresses.
        phone_numbers: Phone numbers keyed by ``business``, ``home`` or
            ``mobile``.

    Returns:
        The created contact object.

    Raises:
        ValueError: If Graph returns no contact.
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

    # Note: Cache invalidation happens automatically via TTL (20min for contact_list)

    return result


def update_contact(
    account_id: str,
    *,
    contact_id: str,
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Patch a contact with already-validated Graph fields.

    Args:
        account_id: Microsoft account ID.
        contact_id: The contact ID to update.
        updates: Graph contact fields to patch.

    Returns:
        The updated contact, or ``{"status": "updated"}`` when Graph
        returns no body.
    """
    result = graph.request(
        "PATCH", f"/me/contacts/{contact_id}", account_id, json=updates
    )

    # Note: Cache invalidation happens automatically via TTL (20min for contact_list)

    return result or {"status": "updated"}


def delete_contact(account_id: str, *, contact_id: str) -> dict[str, str]:
    """Delete a contact permanently.

    Args:
        account_id: Microsoft account ID.
        contact_id: The contact ID to delete.

    Returns:
        ``{"status": "deleted"}``.
    """
    graph.request("DELETE", f"/me/contacts/{contact_id}", account_id)

    # Note: Cache invalidation happens automatically via TTL (20min for contact_list)

    return {"status": "deleted"}


def create_contact_list(account_id: str, *, display_name: str) -> dict[str, Any]:
    """Create a contact folder (list).

    Args:
        account_id: Microsoft account ID.
        display_name: Validated, stripped folder name.

    Returns:
        The created contact folder object.

    Raises:
        ValueError: If Graph returns no folder.
    """
    payload = {"displayName": display_name}

    result = graph.request("POST", "/me/contactFolders", account_id, json=payload)
    if not result:
        raise ValueError("Failed to create contact list")

    return result


def add_contact_to_list(
    account_id: str,
    *,
    contact_id: str,
    list_id: str,
) -> dict[str, Any]:
    """Copy an existing contact into a contact folder (list).

    Args:
        account_id: Microsoft account ID.
        contact_id: The contact ID to copy.
        list_id: The target contact folder ID.

    Returns:
        The copy of the contact created in the folder.

    Raises:
        ValueError: If the contact is not found or the copy fails.
    """
    contact = graph.request("GET", f"/me/contacts/{contact_id}", account_id)
    if not contact:
        raise ValueError(f"Contact with ID {contact_id} not found")

    # Remove system fields that shouldn't be copied
    contact_copy = {
        k: v for k, v in contact.items() if k not in _CONTACT_COPY_EXCLUDED_KEYS
    }

    result = graph.request(
        "POST",
        f"/me/contactFolders/{list_id}/contacts",
        account_id,
        json=contact_copy,
    )
    if not result:
        raise ValueError(f"Failed to add contact to list {list_id}")

    return result


def export_contact_vcard(account_id: str, *, contact_id: str) -> dict[str, Any]:
    """Export a contact as a vCard 3.0 document.

    Args:
        account_id: Microsoft account ID.
        contact_id: The contact ID to export.

    Returns:
        Dictionary with ``contact_id``, ``display_name``, ``format``,
        ``vcard`` and ``size_bytes``.

    Raises:
        ValueError: If the contact is not found.
    """
    contact = graph.request("GET", f"/me/contacts/{contact_id}", account_id)
    if not contact:
        raise ValueError(f"Contact with ID {contact_id} not found")

    # Build vCard format (version 3.0)
    vcard_lines = ["BEGIN:VCARD", "VERSION:3.0"]

    # Add name fields
    given_name = contact.get("givenName", "")
    surname = contact.get("surname", "")
    display_name = contact.get("displayName", f"{given_name} {surname}".strip())

    if display_name:
        vcard_lines.append(f"FN:{display_name}")

    if given_name or surname:
        # Format: surname;given_name;middle;prefix;suffix
        vcard_lines.append(f"N:{surname};{given_name};;;")

    # Add email addresses
    email_addresses = contact.get("emailAddresses", [])
    for idx, email_obj in enumerate(email_addresses):
        if isinstance(email_obj, dict) and "address" in email_obj:
            email_type = "INTERNET" if idx == 0 else f"INTERNET,type=OTHER{idx}"
            vcard_lines.append(f"EMAIL;type={email_type}:{email_obj['address']}")

    # Add phone numbers
    business_phones = contact.get("businessPhones", [])
    for phone in business_phones:
        vcard_lines.append(f"TEL;type=WORK,VOICE:{phone}")

    home_phones = contact.get("homePhones", [])
    for phone in home_phones:
        vcard_lines.append(f"TEL;type=HOME,VOICE:{phone}")

    mobile_phone = contact.get("mobilePhone")
    if mobile_phone:
        vcard_lines.append(f"TEL;type=CELL:{mobile_phone}")

    # Add organization information
    company_name = contact.get("companyName")
    department = contact.get("department")
    if company_name or department:
        org_value = f"{company_name or ''};{department or ''}"
        vcard_lines.append(f"ORG:{org_value}")

    job_title = contact.get("jobTitle")
    if job_title:
        vcard_lines.append(f"TITLE:{job_title}")

    # Add business address if available
    business_address = contact.get("businessAddress")
    if business_address and isinstance(business_address, dict):
        street = business_address.get("street", "")
        city = business_address.get("city", "")
        state = business_address.get("state", "")
        postal_code = business_address.get("postalCode", "")
        country = business_address.get("countryOrRegion", "")
        # Format: POBox;Extended;Street;City;State;PostalCode;Country
        vcard_lines.append(
            f"ADR;type=WORK:;;{street};{city};{state};{postal_code};{country}"
        )

    # Add home address if available
    home_address = contact.get("homeAddress")
    if home_address and isinstance(home_address, dict):
        street = home_address.get("street", "")
        city = home_address.get("city", "")
        state = home_address.get("state", "")
        postal_code = home_address.get("postalCode", "")
        country = home_address.get("countryOrRegion", "")
        vcard_lines.append(
            f"ADR;type=HOME:;;{street};{city};{state};{postal_code};{country}"
        )

    vcard_lines.append("END:VCARD")

    # Join lines with CRLF as per vCard spec
    vcard_content = "\r\n".join(vcard_lines)

    return {
        "contact_id": contact_id,
        "display_name": display_name,
        "format": "vcard",
        "vcard": vcard_content,
        "size_bytes": len(vcard_content.encode("utf-8")),
    }
