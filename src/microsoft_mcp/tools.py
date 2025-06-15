import base64
from typing import Any
from fastmcp import FastMCP
from . import graph, auth

mcp = FastMCP("microsoft-mcp")


@mcp.tool
def list_accounts() -> list[dict[str, str]]:
    """List all signed-in Microsoft accounts"""
    return [
        {"username": acc.username, "account_id": acc.account_id}
        for acc in auth.list_accounts()
    ]


@mcp.tool
def read_emails(
    count: int = 10, 
    folder: str = "inbox", 
    include_body: bool = True,
    account_id: str | None = None
) -> list[dict[str, Any]]:
    """Read emails with full details including body content"""
    params = {
        "$top": count,
        "$select": "id,subject,from,toRecipients,ccRecipients,receivedDateTime,hasAttachments,body,conversationId,isRead"
    }
    result = graph.request("GET", f"/me/mailFolders/{folder}/messages", account_id, params=params)
    return result["value"] if result else []


@mcp.tool
def get_email(email_id: str, account_id: str | None = None) -> dict[str, Any]:
    """Get full email details including attachments list"""
    params = {"$expand": "attachments"}
    result = graph.request("GET", f"/me/messages/{email_id}", account_id, params=params)
    return result or {}


@mcp.tool
def reply_to_email(
    email_id: str,
    body: str,
    reply_all: bool = False,
    account_id: str | None = None
) -> str:
    """Reply to an email maintaining thread context"""
    endpoint = f"/me/messages/{email_id}/{'replyAll' if reply_all else 'reply'}"
    payload = {
        "message": {
            "body": {"contentType": "Text", "content": body}
        }
    }
    graph.request("POST", endpoint, account_id, json=payload)
    return "sent"


@mcp.tool
def mark_email_read(email_id: str, is_read: bool = True, account_id: str | None = None) -> str:
    """Mark email as read or unread"""
    payload = {"isRead": is_read}
    graph.request("PATCH", f"/me/messages/{email_id}", account_id, json=payload)
    return "updated"


@mcp.tool
def move_email(email_id: str, destination_folder: str, account_id: str | None = None) -> str:
    """Move email to another folder (drafts, sentitems, deleteditems, etc)"""
    folders = graph.request("GET", "/me/mailFolders", account_id)
    folder_id = None
    
    if folders and "value" in folders:
        for folder in folders["value"]:
            if folder["displayName"].lower() == destination_folder.lower():
                folder_id = folder["id"]
                break
    
    if not folder_id:
        return f"folder '{destination_folder}' not found"
    
    payload = {"destinationId": folder_id}
    graph.request("POST", f"/me/messages/{email_id}/move", account_id, json=payload)
    return "moved"


@mcp.tool
def download_attachment(email_id: str, attachment_id: str, account_id: str | None = None) -> str:
    """Download email attachment as base64"""
    result = graph.request("GET", f"/me/messages/{email_id}/attachments/{attachment_id}", account_id)
    if result and "contentBytes" in result:
        return result["contentBytes"]
    return ""


@mcp.tool  
def send_email(
    to: str | list[str], 
    subject: str, 
    body: str,
    cc: list[str] | None = None,
    attachments: list[dict[str, str]] | None = None,
    account_id: str | None = None
) -> str:
    """Send email with optional CC and attachments (attachments = [{"name": "file.txt", "content_base64": "..."}])"""
    to_list = [to] if isinstance(to, str) else to
    
    message = {
        "subject": subject,
        "body": {"contentType": "Text", "content": body},
        "toRecipients": [{"emailAddress": {"address": addr}} for addr in to_list]
    }
    
    if cc:
        message["ccRecipients"] = [{"emailAddress": {"address": addr}} for addr in cc]
    
    if attachments:
        message["attachments"] = [
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": att["name"],
                "contentBytes": att["content_base64"]
            }
            for att in attachments
        ]
    
    payload = {"message": message}
    graph.request("POST", "/me/sendMail", account_id, json=payload)
    return "sent"


@mcp.tool
def get_calendar_events(
    days: int = 7, 
    include_details: bool = True,
    account_id: str | None = None
) -> list[dict[str, Any]]:
    """Get calendar events with full details"""
    import datetime as dt
    start = dt.datetime.utcnow().isoformat() + "Z"
    end = (dt.datetime.utcnow() + dt.timedelta(days=days)).isoformat() + "Z"
    
    params = {
        "$filter": f"start/dateTime ge '{start}' and start/dateTime le '{end}'",
        "$orderby": "start/dateTime",
        "$top": 50
    }
    
    if include_details:
        params["$select"] = "id,subject,start,end,location,body,attendees,organizer,isAllDay,recurrence,onlineMeeting"
    
    result = graph.request("GET", "/me/events", account_id, params=params)
    return result["value"] if result else []


@mcp.tool
def check_availability(
    start: str,
    end: str,
    attendees: list[str] | None = None,
    account_id: str | None = None
) -> dict[str, Any]:
    """Check free/busy availability for scheduling"""
    schedules = [graph.request("GET", "/me", account_id).get("mail", "")]
    if attendees:
        schedules.extend(attendees)
    
    payload = {
        "schedules": schedules,
        "startTime": {"dateTime": start, "timeZone": "UTC"},
        "endTime": {"dateTime": end, "timeZone": "UTC"},
        "availabilityViewInterval": 30
    }
    
    result = graph.request("POST", "/me/calendar/getSchedule", account_id, json=payload)
    return result or {}


@mcp.tool
def create_event(
    subject: str, 
    start: str, 
    end: str,
    location: str | None = None,
    body: str | None = None,
    attendees: list[str] | None = None,
    timezone: str = "UTC",
    account_id: str | None = None
) -> str:
    """Create calendar event with full details"""
    event = {
        "subject": subject,
        "start": {"dateTime": start, "timeZone": timezone},
        "end": {"dateTime": end, "timeZone": timezone}
    }
    
    if location:
        event["location"] = {"displayName": location}
    
    if body:
        event["body"] = {"contentType": "Text", "content": body}
    
    if attendees:
        event["attendees"] = [
            {"emailAddress": {"address": a}, "type": "required"} 
            for a in attendees
        ]
    
    result = graph.request("POST", "/me/events", account_id, json=event)
    return result["id"] if result else "error"


@mcp.tool
def update_event(
    event_id: str,
    subject: str | None = None,
    start: str | None = None,
    end: str | None = None,
    location: str | None = None,
    body: str | None = None,
    account_id: str | None = None
) -> str:
    """Update existing calendar event"""
    updates = {}
    
    if subject:
        updates["subject"] = subject
    if start:
        updates["start"] = {"dateTime": start, "timeZone": "UTC"}
    if end:
        updates["end"] = {"dateTime": end, "timeZone": "UTC"}
    if location:
        updates["location"] = {"displayName": location}
    if body:
        updates["body"] = {"contentType": "Text", "content": body}
    
    graph.request("PATCH", f"/me/events/{event_id}", account_id, json=updates)
    return "updated"


@mcp.tool
def delete_event(event_id: str, send_cancellation: bool = True, account_id: str | None = None) -> str:
    """Delete/cancel calendar event"""
    if send_cancellation:
        graph.request("POST", f"/me/events/{event_id}/cancel", account_id, json={})
    else:
        graph.request("DELETE", f"/me/events/{event_id}", account_id)
    return "deleted"


@mcp.tool
def respond_to_event(
    event_id: str,
    response: str = "accept",
    message: str | None = None,
    account_id: str | None = None
) -> str:
    """Respond to meeting invitation (accept, decline, tentativelyAccept)"""
    payload = {"sendResponse": True}
    if message:
        payload["comment"] = message
    
    graph.request("POST", f"/me/events/{event_id}/{response}", account_id, json=payload)
    return response


@mcp.tool
def get_contacts(search: str | None = None, limit: int = 50, account_id: str | None = None) -> list[dict[str, Any]]:
    """Get contacts/people with email addresses"""
    if search:
        params = {"$search": f'"{search}"', "$top": limit}
        result = graph.request("GET", "/me/people", account_id, params=params)
    else:
        params = {"$top": limit}
        result = graph.request("GET", "/me/contacts", account_id, params=params)
    
    return result["value"] if result else []


@mcp.tool
def list_files(
    path: str = "/",
    next_link: str | None = None,
    account_id: str | None = None
) -> dict[str, Any]:
    """List files with pagination support (returns items and @odata.nextLink)"""
    if next_link:
        result = graph.request("GET", next_link.replace("https://graph.microsoft.com/v1.0", ""), account_id)
    else:
        endpoint = "/me/drive/root/children" if path == "/" else f"/me/drive/root:/{path}:/children"
        params = {"$top": 50, "$select": "id,name,size,lastModifiedDateTime,folder,file"}
        result = graph.request("GET", endpoint, account_id, params=params)
    
    if result:
        return {
            "items": [
                {
                    "name": item["name"],
                    "id": item["id"],
                    "type": "folder" if "folder" in item else "file",
                    "size": item.get("size", 0),
                    "modified": item.get("lastModifiedDateTime", "")
                }
                for item in result.get("value", [])
            ],
            "next_link": result.get("@odata.nextLink")
        }
    return {"items": [], "next_link": None}


@mcp.tool
def download_file(file_id: str, account_id: str | None = None) -> str:
    """Download file content as base64"""
    content = graph.download_raw(f"/me/drive/items/{file_id}/content", account_id)
    return base64.b64encode(content).decode()


@mcp.tool
def upload_file(path: str, content_base64: str, account_id: str | None = None) -> dict[str, str]:
    """Upload file to OneDrive"""
    data = base64.b64decode(content_base64)
    result = graph.request("PUT", f"/me/drive/root:/{path}:/content", account_id, data=data)
    return {"id": result["id"], "name": result["name"]} if result else {"error": "upload failed"}


@mcp.tool
def delete_file(file_id: str, account_id: str | None = None) -> str:
    """Delete file or folder"""
    graph.request("DELETE", f"/me/drive/items/{file_id}", account_id)
    return "deleted"


@mcp.tool
def search(
    query: str,
    types: list[str] | None = None,
    limit: int = 25,
    account_id: str | None = None
) -> list[dict[str, Any]]:
    """Search across emails, files, events, and people"""
    search_types = types or ["message", "event", "driveItem", "person"]
    
    payload = {
        "requests": [{
            "entityTypes": search_types,
            "query": {"queryString": query},
            "from": 0,
            "size": limit
        }]
    }
    
    try:
        result = graph.request("POST", "/search/query", account_id, json=payload)
        if result and "value" in result:
            hits = []
            for response in result["value"]:
                for container in response.get("hitsContainers", []):
                    hits.extend(container.get("hits", []))
            return hits
    except Exception:
        pass
    
    return []