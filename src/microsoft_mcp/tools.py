import base64
import datetime as dt
from typing import Any
from fastmcp import FastMCP
from . import graph, auth
from .drive_operations import (
    create_folder,
    move_item,
    delete_item,
)
from .email_utils import EmailBody
from .health import check_health

mcp = FastMCP("microsoft-mcp")


@mcp.tool
def list_signed_in_accounts() -> list[dict[str, str]]:
    """Show all Microsoft accounts signed in to this MCP server"""
    return [
        {"username": account.username, "account_id": account.home_account_id}
        for account in auth.list_accounts()
    ]


@mcp.tool
def read_latest_email(
    count: int = 5, account_id: str | None = None
) -> list[dict[str, str]]:
    """Return the N most-recent inbox messages (id, subject, sender)"""
    messages = graph.list_messages(top=count, account_id=account_id)
    return [
        {
            "id": msg["id"],
            "subject": msg["subject"],
            "from": msg["from"]["emailAddress"]["address"],
        }
        for msg in messages["value"]
    ]


@mcp.tool
def send_email(
    to: str, subject: str, body: str = "", account_id: str | None = None
) -> str:
    """Send a plain-text email via Outlook"""
    graph.send_mail(subject, body, to, account_id=account_id)
    return "sent"


@mcp.tool
def send_html_email(
    to: str | list[str],
    subject: str,
    body_html: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    account_id: str | None = None,
) -> str:
    """Send an HTML email via Outlook with optional CC/BCC recipients"""
    email_body = EmailBody(content=body_html, content_type="HTML")
    graph.send_mail(subject, email_body, to, cc=cc, bcc=bcc, account_id=account_id)
    return "sent"


@mcp.tool
def create_calendar_event(
    subject: str,
    start_iso: str,
    end_iso: str,
    attendees: list[str] | None = None,
    account_id: str | None = None,
) -> str:
    """Create an event in the default calendar and return its ID"""
    event = graph.create_event(
        subject, start_iso, end_iso, attendees, account_id=account_id
    )
    return event["id"]


@mcp.tool
def upcoming_events(
    days: int = 7, account_id: str | None = None
) -> list[dict[str, Any]]:
    """List next N days of events (UTC)"""
    now = dt.datetime.utcnow()
    end = now + dt.timedelta(days=days)
    events = graph.list_events(now, end, account_id=account_id)
    return events["value"]


@mcp.tool
def drive_info(account_id: str | None = None) -> dict[str, Any]:
    """Retrieve basic OneDrive metadata"""
    return graph.get_drive(account_id=account_id)


@mcp.tool
def list_files_in_root(
    max_items: int = 20, account_id: str | None = None
) -> list[dict[str, Any]]:
    """List file/folder names in the root of OneDrive"""
    items = graph.list_root_children(top=max_items, account_id=account_id)
    return [
        {"name": item["name"], "id": item["id"], "is_folder": "folder" in item}
        for item in items["value"]
    ]


@mcp.tool
def download_drive_item(item_id: str, account_id: str | None = None) -> str:
    """Download a OneDrive file; returns raw bytes (base64-encoded)"""
    data = graph.download_file(item_id, account_id=account_id)
    return base64.b64encode(data).decode()


@mcp.tool
def upload_drive_file(
    path: str, content_base64: str, account_id: str | None = None
) -> dict[str, str]:
    """Upload a file to OneDrive at the given path (e.g. 'notes/todo.txt')"""
    data = base64.b64decode(content_base64)
    info = graph.upload_file(path, data, account_id=account_id)
    return {"id": info["id"], "web_url": info["webUrl"]}


@mcp.tool
def create_drive_folder(
    parent_path: str, folder_name: str, account_id: str | None = None
) -> dict[str, str]:
    """Create a new folder in OneDrive"""
    result = create_folder(parent_path, folder_name, account_id)
    return {"id": result["id"], "name": result["name"]}


@mcp.tool
def delete_drive_item(item_id: str, account_id: str | None = None) -> str:
    """Delete a file or folder from OneDrive"""
    delete_item(item_id, account_id)
    return "deleted"


@mcp.tool
def move_drive_item(
    item_id: str,
    new_parent_id: str,
    new_name: str | None = None,
    account_id: str | None = None,
) -> dict[str, str]:
    """Move or rename a file/folder in OneDrive"""
    result = move_item(item_id, new_parent_id, new_name, account_id)
    return {"id": result["id"], "name": result["name"]}


@mcp.tool
def health_check(account_id: str | None = None) -> dict[str, Any]:
    """Check the health status of the Microsoft MCP server"""
    status = check_health(account_id)
    return {
        "healthy": status.healthy,
        "message": status.message,
        "checked_at": status.checked_at,
        "auth_status": status.auth_status,
        "api_status": status.api_status,
        "accounts_count": status.accounts_count,
    }
