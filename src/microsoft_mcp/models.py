from typing import NamedTuple


class EmailAddress(NamedTuple):
    address: str
    name: str | None = None


class EmailMessage(NamedTuple):
    id: str
    subject: str
    from_address: EmailAddress
    body_content: str | None = None
    body_type: str = "Text"


class CalendarEvent(NamedTuple):
    id: str
    subject: str
    start: str
    end: str
    attendees: list[EmailAddress]


class DriveItem(NamedTuple):
    id: str
    name: str
    is_folder: bool
    web_url: str | None = None


class DriveInfo(NamedTuple):
    id: str
    drive_type: str
    quota_used: int | None = None
    quota_total: int | None = None
