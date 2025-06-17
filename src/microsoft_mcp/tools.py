import base64
import datetime as dt
from typing import Any
from fastmcp import FastMCP
from . import graph, auth

mcp = FastMCP("microsoft-mcp")

_FOLDERS = {
    "inbox": "inbox",
    "sent": "sentitems",
    "sentitems": "sentitems",
    "drafts": "drafts",
    "deleted": "deleteditems",
    "deleteditems": "deleteditems",
    "junk": "junkemail",
    "archive": "archive",
}


@mcp.tool
def list_accounts() -> list[dict[str, str]]:
    """List all signed-in Microsoft accounts"""
    return [
        {"username": acc.username, "account_id": acc.account_id}
        for acc in auth.list_accounts()
    ]


@mcp.tool
def list_emails(
    account_id: str,
    folder: str = "inbox",
    limit: int = 10,
    include_body: bool = True,
) -> list[dict[str, Any]]:
    """List emails from specified folder"""
    folder_path = _FOLDERS.get(folder.lower(), folder)

    if include_body:
        select_fields = "id,subject,from,toRecipients,ccRecipients,receivedDateTime,hasAttachments,body,conversationId,isRead"
    else:
        select_fields = "id,subject,from,toRecipients,receivedDateTime,hasAttachments,conversationId,isRead"

    params = {
        "$top": limit,
        "$select": select_fields,
        "$orderby": "receivedDateTime desc",
    }

    result = graph.request(
        "GET", f"/me/mailFolders/{folder_path}/messages", account_id, params=params
    )
    if not result:
        raise ValueError(
            f"Failed to list emails from folder {folder_path} - no response"
        )
    if "value" not in result:
        raise ValueError(f"Unexpected response structure: {result}")
    return result["value"]


@mcp.tool
def get_email(email_id: str, account_id: str) -> dict[str, Any]:
    """Get full email details including attachments list"""
    params = {"$expand": "attachments"}
    result = graph.request("GET", f"/me/messages/{email_id}", account_id, params=params)
    if not result:
        raise ValueError(f"Email with ID {email_id} not found")
    return result


@mcp.tool
def create_email(
    account_id: str,
    to: str | list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    attachments: list[dict[str, str]] | None = None,
    send_immediately: bool = True,
) -> dict[str, Any]:
    """Create and optionally send an email"""
    to_list = [to] if isinstance(to, str) else to

    message = {
        "subject": subject,
        "body": {"contentType": "Text", "content": body},
        "toRecipients": [{"emailAddress": {"address": addr}} for addr in to_list],
    }

    if cc:
        message["ccRecipients"] = [{"emailAddress": {"address": addr}} for addr in cc]

    if attachments:
        message["attachments"] = [
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": att["name"],
                "contentBytes": att["content_base64"],
            }
            for att in attachments
        ]

    if send_immediately:
        graph.request("POST", "/me/sendMail", account_id, json={"message": message})
        return {"status": "sent"}
    else:
        result = graph.request("POST", "/me/messages", account_id, json=message)
        if not result:
            raise ValueError("Failed to create email draft")
        return result


@mcp.tool
def update_email(
    email_id: str, updates: dict[str, Any], account_id: str
) -> dict[str, Any]:
    """Update email properties (isRead, categories, flag, etc.)"""
    result = graph.request(
        "PATCH", f"/me/messages/{email_id}", account_id, json=updates
    )
    if not result:
        raise ValueError(f"Failed to update email {email_id} - no response")
    return result


@mcp.tool
def delete_email(email_id: str, account_id: str) -> dict[str, str]:
    """Delete an email"""
    graph.request("DELETE", f"/me/messages/{email_id}", account_id)
    return {"status": "deleted"}


@mcp.tool
def move_email(
    email_id: str, destination_folder: str, account_id: str
) -> dict[str, Any]:
    """Move email to another folder"""
    folder_path = _FOLDERS.get(destination_folder.lower(), destination_folder)

    folders = graph.request("GET", "/me/mailFolders", account_id)
    folder_id = None

    if not folders:
        raise ValueError("Failed to retrieve mail folders")
    if "value" not in folders:
        raise ValueError(f"Unexpected folder response structure: {folders}")

    for folder in folders["value"]:
        if folder["displayName"].lower() == folder_path.lower():
            folder_id = folder["id"]
            break

    if not folder_id:
        raise ValueError(f"Folder '{destination_folder}' not found")

    payload = {"destinationId": folder_id}
    result = graph.request(
        "POST", f"/me/messages/{email_id}/move", account_id, json=payload
    )
    if not result:
        raise ValueError("Failed to move email - no response from server")
    if "id" not in result:
        raise ValueError(f"Failed to move email - unexpected response: {result}")
    return {"status": "moved", "new_id": result["id"]}


@mcp.tool
def reply_email(
    account_id: str, email_id: str, body: str, reply_all: bool = False
) -> dict[str, str]:
    """Reply to an email"""
    endpoint = f"/me/messages/{email_id}/{'replyAll' if reply_all else 'reply'}"
    payload = {"message": {"body": {"contentType": "Text", "content": body}}}
    graph.request("POST", endpoint, account_id, json=payload)
    return {"status": "sent"}


@mcp.tool
def list_events(
    account_id: str,
    days_ahead: int = 7,
    days_back: int = 0,
    include_details: bool = True,
) -> list[dict[str, Any]]:
    """List calendar events within specified date range"""
    start = (dt.datetime.utcnow() - dt.timedelta(days=days_back)).isoformat() + "Z"
    end = (dt.datetime.utcnow() + dt.timedelta(days=days_ahead)).isoformat() + "Z"

    params = {
        "$filter": f"start/dateTime ge '{start}' and start/dateTime le '{end}'",
        "$orderby": "start/dateTime",
        "$top": 100,
    }

    if include_details:
        params["$select"] = (
            "id,subject,start,end,location,body,attendees,organizer,isAllDay,recurrence,onlineMeeting"
        )
    else:
        params["$select"] = "id,subject,start,end,location,organizer"

    result = graph.request("GET", "/me/events", account_id, params=params)
    return result["value"] if result else []


@mcp.tool
def get_event(event_id: str, account_id: str) -> dict[str, Any]:
    """Get full event details"""
    result = graph.request("GET", f"/me/events/{event_id}", account_id)
    if not result:
        raise ValueError(f"Event with ID {event_id} not found")
    return result


@mcp.tool
def create_event(
    account_id: str,
    subject: str,
    start: str,
    end: str,
    location: str | None = None,
    body: str | None = None,
    attendees: list[str] | None = None,
    timezone: str = "UTC",
) -> dict[str, Any]:
    """Create a calendar event"""
    event = {
        "subject": subject,
        "start": {"dateTime": start, "timeZone": timezone},
        "end": {"dateTime": end, "timeZone": timezone},
    }

    if location:
        event["location"] = {"displayName": location}

    if body:
        event["body"] = {"contentType": "Text", "content": body}

    if attendees:
        event["attendees"] = [
            {"emailAddress": {"address": a}, "type": "required"} for a in attendees
        ]

    result = graph.request("POST", "/me/events", account_id, json=event)
    if not result:
        raise ValueError("Failed to create event")
    return result


@mcp.tool
def update_event(
    event_id: str, updates: dict[str, Any], account_id: str
) -> dict[str, Any]:
    """Update event properties"""
    formatted_updates = {}

    if "subject" in updates:
        formatted_updates["subject"] = updates["subject"]
    if "start" in updates:
        formatted_updates["start"] = {
            "dateTime": updates["start"],
            "timeZone": updates.get("timezone", "UTC"),
        }
    if "end" in updates:
        formatted_updates["end"] = {
            "dateTime": updates["end"],
            "timeZone": updates.get("timezone", "UTC"),
        }
    if "location" in updates:
        formatted_updates["location"] = {"displayName": updates["location"]}
    if "body" in updates:
        formatted_updates["body"] = {"contentType": "Text", "content": updates["body"]}

    result = graph.request(
        "PATCH", f"/me/events/{event_id}", account_id, json=formatted_updates
    )
    return result or {"status": "updated"}


@mcp.tool
def delete_event(
    account_id: str, event_id: str, send_cancellation: bool = True
) -> dict[str, str]:
    """Delete or cancel a calendar event"""
    if send_cancellation:
        graph.request("POST", f"/me/events/{event_id}/cancel", account_id, json={})
    else:
        graph.request("DELETE", f"/me/events/{event_id}", account_id)
    return {"status": "deleted"}


@mcp.tool
def respond_event(
    account_id: str,
    event_id: str,
    response: str = "accept",
    message: str | None = None,
) -> dict[str, str]:
    """Respond to event invitation (accept, decline, tentativelyAccept)"""
    payload: dict[str, Any] = {"sendResponse": True}
    if message:
        payload["comment"] = message

    graph.request("POST", f"/me/events/{event_id}/{response}", account_id, json=payload)
    return {"status": response}


@mcp.tool
def check_availability(
    account_id: str,
    start: str,
    end: str,
    attendees: list[str] | None = None,
) -> dict[str, Any]:
    """Check calendar availability for scheduling"""
    me_info = graph.request("GET", "/me", account_id)
    if not me_info or "mail" not in me_info:
        raise ValueError("Failed to get user email address")
    schedules = [me_info["mail"]]
    if attendees:
        schedules.extend(attendees)

    payload = {
        "schedules": schedules,
        "startTime": {"dateTime": start, "timeZone": "UTC"},
        "endTime": {"dateTime": end, "timeZone": "UTC"},
        "availabilityViewInterval": 30,
    }

    result = graph.request("POST", "/me/calendar/getSchedule", account_id, json=payload)
    if not result:
        raise ValueError("Failed to check availability")
    return result


@mcp.tool
def list_contacts(account_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """List contacts"""
    params = {"$top": limit}
    result = graph.request("GET", "/me/contacts", account_id, params=params)
    return result["value"] if result else []


@mcp.tool
def get_contact(contact_id: str, account_id: str) -> dict[str, Any]:
    """Get contact details"""
    result = graph.request("GET", f"/me/contacts/{contact_id}", account_id)
    if not result:
        raise ValueError(f"Contact with ID {contact_id} not found")
    return result


@mcp.tool
def create_contact(
    account_id: str,
    given_name: str,
    surname: str | None = None,
    email_addresses: list[str] | None = None,
    phone_numbers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Create a new contact"""
    contact: dict[str, Any] = {"givenName": given_name}

    if surname:
        contact["surname"] = surname

    if email_addresses:
        contact["emailAddresses"] = [
            {"address": email, "name": f"{given_name} {surname or ''}".strip()}
            for email in email_addresses
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


@mcp.tool
def update_contact(
    contact_id: str, updates: dict[str, Any], account_id: str
) -> dict[str, Any]:
    """Update contact information"""
    result = graph.request(
        "PATCH", f"/me/contacts/{contact_id}", account_id, json=updates
    )
    return result or {"status": "updated"}


@mcp.tool
def delete_contact(contact_id: str, account_id: str) -> dict[str, str]:
    """Delete a contact"""
    graph.request("DELETE", f"/me/contacts/{contact_id}", account_id)
    return {"status": "deleted"}


@mcp.tool
def list_files(
    account_id: str, path: str = "/", limit: int = 50
) -> list[dict[str, Any]]:
    """List files and folders in OneDrive"""
    endpoint = (
        "/me/drive/root/children"
        if path == "/"
        else f"/me/drive/root:/{path}:/children"
    )
    params = {
        "$top": limit,
        "$select": "id,name,size,lastModifiedDateTime,folder,file,@microsoft.graph.downloadUrl",
    }

    result = graph.request("GET", endpoint, account_id, params=params)

    if result and "value" in result:
        return [
            {
                "id": item["id"],
                "name": item["name"],
                "type": "folder" if "folder" in item else "file",
                "size": item.get("size", 0),
                "modified": item.get("lastModifiedDateTime"),
                "download_url": item.get("@microsoft.graph.downloadUrl"),
            }
            for item in result["value"]
        ]
    return []


@mcp.tool
def get_file(file_id: str, account_id: str) -> dict[str, Any]:
    """Get file metadata and content as base64"""
    metadata = graph.request("GET", f"/me/drive/items/{file_id}", account_id)
    content = graph.download_raw(f"/me/drive/items/{file_id}/content", account_id)

    return {"metadata": metadata, "content_base64": base64.b64encode(content).decode()}


@mcp.tool
def create_file(path: str, content_base64: str, account_id: str) -> dict[str, Any]:
    """Create or upload a file to OneDrive"""
    data = base64.b64decode(content_base64)
    result = graph.request(
        "PUT", f"/me/drive/root:/{path}:/content", account_id, data=data
    )
    if not result:
        raise ValueError(f"Failed to create file at path: {path}")
    return result


@mcp.tool
def update_file(file_id: str, content_base64: str, account_id: str) -> dict[str, Any]:
    """Update file content"""
    data = base64.b64decode(content_base64)
    result = graph.request(
        "PUT", f"/me/drive/items/{file_id}/content", account_id, data=data
    )
    if not result:
        raise ValueError(f"Failed to update file with ID: {file_id}")
    return result


@mcp.tool
def delete_file(file_id: str, account_id: str) -> dict[str, str]:
    """Delete a file or folder"""
    graph.request("DELETE", f"/me/drive/items/{file_id}", account_id)
    return {"status": "deleted"}


@mcp.tool
def get_attachment(
    email_id: str, attachment_id: str, account_id: str
) -> dict[str, Any]:
    """Get email attachment details and content"""
    result = graph.request(
        "GET", f"/me/messages/{email_id}/attachments/{attachment_id}", account_id
    )

    if not result:
        raise ValueError("Attachment not found")

    if "contentBytes" not in result:
        raise ValueError("Attachment content not available")

    return {
        "name": result.get("name", "unknown"),
        "content_type": result.get("contentType", "application/octet-stream"),
        "size": result.get("size", 0),
        "content_base64": result["contentBytes"],
    }


@mcp.tool
def search_files(
    query: str,
    account_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Search for files in OneDrive using query string"""
    params = {
        "$top": limit,
        "$select": "id,name,size,lastModifiedDateTime,folder,file,@microsoft.graph.downloadUrl",
    }

    result = graph.request(
        "GET", f"/me/drive/root/search(q='{query}')", account_id, params=params
    )

    if result and "value" in result:
        return [
            {
                "id": item["id"],
                "name": item["name"],
                "type": "folder" if "folder" in item else "file",
                "size": item.get("size", 0),
                "modified": item.get("lastModifiedDateTime"),
                "download_url": item.get("@microsoft.graph.downloadUrl"),
            }
            for item in result["value"]
        ]
    return []


@mcp.tool
def search_emails(
    query: str,
    account_id: str,
    limit: int = 50,
    folder: str | None = None,
) -> list[dict[str, Any]]:
    """Search emails using Microsoft Graph $search parameter

    This is an alternative to the universal search function, specifically for emails.
    It uses the $search parameter on the messages endpoint which may work better
    for email-specific searches.
    """
    params = {
        "$search": f'"{query}"',
        "$top": limit,
        "$select": "id,subject,from,toRecipients,receivedDateTime,hasAttachments,body,conversationId,isRead",
    }

    if folder:
        folder_path = _FOLDERS.get(folder.lower(), folder)
        endpoint = f"/me/mailFolders/{folder_path}/messages"
    else:
        endpoint = "/me/messages"

    result = graph.request("GET", endpoint, account_id, params=params)
    return result["value"] if result else []


@mcp.tool
def search_events(
    query: str,
    account_id: str,
    days_ahead: int = 365,
    days_back: int = 365,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Search calendar events by keyword in subject, body, or location"""
    start = (dt.datetime.utcnow() - dt.timedelta(days=days_back)).isoformat() + "Z"
    end = (dt.datetime.utcnow() + dt.timedelta(days=days_ahead)).isoformat() + "Z"

    params = {
        "$filter": f"(contains(subject,'{query}') or contains(body/content,'{query}') or contains(location/displayName,'{query}')) and start/dateTime ge '{start}' and start/dateTime le '{end}'",
        "$top": limit,
        "$select": "id,subject,start,end,location,body,attendees,organizer,isAllDay,recurrence,onlineMeeting",
    }

    result = graph.request("GET", "/me/events", account_id, params=params)
    if not result:
        raise ValueError("Failed to search events - no response")
    if "value" not in result:
        raise ValueError(f"Unexpected response structure: {result}")
    return result["value"]


@mcp.tool
def search_contacts(
    query: str,
    account_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Search contacts by name, email, or phone number"""
    params = {
        "$filter": f"contains(displayName,'{query}') or contains(givenName,'{query}') or contains(surname,'{query}') or contains(emailAddresses/any(e:e/address),'{query}')",
        "$top": limit,
    }

    result = graph.request("GET", "/me/contacts", account_id, params=params)
    if not result:
        raise ValueError("Failed to search contacts - no response")
    if "value" not in result:
        raise ValueError(f"Unexpected response structure: {result}")
    return result["value"]
