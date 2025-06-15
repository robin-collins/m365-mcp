import httpx
import datetime as dt
from typing import Any
from .auth import auth_header
from .http_utils import retry_with_backoff
from .email_utils import EmailBody, Attachment, build_email_payload
from .calendar_utils import (
    EventReminder,
    RecurrencePattern,
    RecurrenceRange,
    build_event_payload,
)
from .logging_config import setup_logging, log_request, log_response

logger = setup_logging()

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _build_request_params(
    method: str,
    path: str,
    account_id: str | None,
    params: dict[str, Any] | None,
    data: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "method": method,
        "url": f"{GRAPH_BASE}{path}",
        "headers": auth_header(account_id),
        "params": params,
        "json": data,
    }


def _execute_request(
    client: httpx.Client, request_params: dict[str, Any]
) -> httpx.Response:
    log_request(
        logger,
        request_params["method"],
        request_params["url"],
        request_params.get("json"),
    )
    response = client.request(**request_params)
    response.raise_for_status()
    log_response(
        logger, response.status_code, response.json() if response.content else None
    )
    return response


def _parse_response(response: httpx.Response) -> dict[str, Any] | None:
    if response.status_code == 204 or not response.content:
        return None
    return response.json()


def _request(
    method: str,
    path: str,
    account_id: str | None = None,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    request_params = _build_request_params(method, path, account_id, params, data)

    def make_request() -> dict[str, Any] | None:
        with httpx.Client(timeout=15) as client:
            response = _execute_request(client, request_params)
            return _parse_response(response)

    return retry_with_backoff(make_request)


def list_messages(top: int = 10, account_id: str | None = None) -> dict[str, Any]:
    result = _request(
        "GET",
        "/me/mailFolders/Inbox/messages",
        account_id=account_id,
        params={"$top": top},
    )
    return result or {}


def send_mail(
    subject: str,
    body: str | EmailBody,
    to: str | list[str],
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    attachments: list[Attachment] | None = None,
    account_id: str | None = None,
) -> None:
    if isinstance(body, str):
        body = EmailBody(content=body, content_type="Text")

    to_recipients = [to] if isinstance(to, str) else to

    data = build_email_payload(
        subject=subject,
        body=body,
        to_recipients=to_recipients,
        cc_recipients=cc,
        bcc_recipients=bcc,
        attachments=attachments,
    )

    _request("POST", "/me/sendMail", account_id=account_id, data=data)


def list_events(
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
    top: int = 10,
    account_id: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"$top": top}
    if start and end:
        params["startDateTime"] = start.isoformat()
        params["endDateTime"] = end.isoformat()
    result = _request("GET", "/me/calendarView", account_id=account_id, params=params)
    return result or {}


def create_event(
    subject: str,
    start: str,
    end: str,
    attendees: list[str] | None = None,
    timezone: str = "UTC",
    location: str | None = None,
    body: str | None = None,
    reminders: list[EventReminder] | None = None,
    recurrence: tuple[RecurrencePattern, RecurrenceRange] | None = None,
    account_id: str | None = None,
) -> dict[str, Any]:
    data = build_event_payload(
        subject=subject,
        start_datetime=start,
        end_datetime=end,
        timezone=timezone,
        location=location,
        body_content=body,
        attendees=attendees,
        reminders=reminders,
        recurrence=recurrence,
    )
    result = _request("POST", "/me/events", account_id=account_id, data=data)
    return result or {}


def get_drive(account_id: str | None = None) -> dict[str, Any]:
    result = _request("GET", "/me/drive", account_id=account_id)
    return result or {}


def list_root_children(top: int = 20, account_id: str | None = None) -> dict[str, Any]:
    result = _request(
        "GET", "/me/drive/root/children", account_id=account_id, params={"$top": top}
    )
    return result or {}


def download_file(item_id: str, account_id: str | None = None) -> bytes:
    def download() -> bytes:
        with httpx.Client(
            timeout=30, headers=auth_header(account_id), follow_redirects=True
        ) as client:
            response = client.get(f"{GRAPH_BASE}/me/drive/items/{item_id}/content")
            response.raise_for_status()
            return response.content

    return retry_with_backoff(download)


def upload_file(
    path: str, content: bytes, account_id: str | None = None
) -> dict[str, Any]:
    url_path = f"/me/drive/root:/{path}:/content"

    def upload() -> dict[str, Any]:
        with httpx.Client(timeout=30, headers=auth_header(account_id)) as client:
            response = client.put(f"{GRAPH_BASE}{url_path}", content=content)
            response.raise_for_status()
            return response.json()

    return retry_with_backoff(upload)
