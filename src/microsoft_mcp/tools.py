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
def read_emails(count: int = 10, folder: str = "inbox", account_id: str | None = None) -> list[dict[str, Any]]:
    """Read emails from any folder (inbox, sentitems, drafts, etc)"""
    result = graph.request("GET", f"/me/mailFolders/{folder}/messages", account_id, params={"$top": count})
    return result["value"] if result else []


@mcp.tool  
def send_email(to: str, subject: str, body: str, account_id: str | None = None) -> str:
    """Send an email"""
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": to}}]
        }
    }
    graph.request("POST", "/me/sendMail", account_id, json=payload)
    return "sent"


@mcp.tool
def get_calendar_events(days: int = 7, account_id: str | None = None) -> list[dict[str, Any]]:
    """Get calendar events for next N days"""
    import datetime as dt
    start = dt.datetime.utcnow().isoformat() + "Z"
    end = (dt.datetime.utcnow() + dt.timedelta(days=days)).isoformat() + "Z"
    params = {
        "$filter": f"start/dateTime ge '{start}' and start/dateTime le '{end}'",
        "$orderby": "start/dateTime",
        "$top": days * 5
    }
    result = graph.request("GET", "/me/events", account_id, params=params)
    return result["value"] if result else []


@mcp.tool
def create_event(subject: str, start: str, end: str, attendees: list[str] | None = None, account_id: str | None = None) -> str:
    """Create calendar event (ISO datetime format for start/end)"""
    event = {
        "subject": subject,
        "start": {"dateTime": start, "timeZone": "UTC"},
        "end": {"dateTime": end, "timeZone": "UTC"},
    }
    if attendees:
        event["attendees"] = [{"emailAddress": {"address": a}, "type": "required"} for a in attendees]
    
    result = graph.request("POST", "/me/events", account_id, json=event)
    return result["id"] if result else "error"


@mcp.tool
def list_files(path: str = "/", account_id: str | None = None) -> list[dict[str, str]]:
    """List files in OneDrive folder"""
    endpoint = "/me/drive/root/children" if path == "/" else f"/me/drive/root:/{path}:/children"
    result = graph.request("GET", endpoint, account_id)
    
    return [
        {"name": item["name"], "id": item["id"], "type": "folder" if "folder" in item else "file"}
        for item in result.get("value", [])
    ] if result else []


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
def search(query: str, types: list[str] | None = None, account_id: str | None = None) -> list[dict[str, Any]]:
    """Search across emails, files, and events"""
    search_types = types or ["message", "event", "driveItem"]
    
    payload = {
        "requests": [{
            "entityTypes": search_types,
            "query": {"queryString": query},
            "from": 0,
            "size": 25
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