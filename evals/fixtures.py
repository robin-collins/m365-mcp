"""Seed data for the fake Graph: one personal Microsoft account.

IDs are stable (``msg-003``, ``evt-sync``) so golden cases can name the
exact item a correct call must touch. Times are relative to the anchor
date (the day of the run), so "next Tuesday" and "last week" stay
meaningful whenever the harness runs.
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .fake_graph import FakeGraph

ME = {"name": "Alex Morgan", "address": "alex.morgan@outlook.com"}
JANE = {"name": "Jane Smith", "address": "jane.smith@example.com"}
MARK = {"name": "Mark Brown", "address": "mark.brown@example.com"}
PRIYA = {"name": "Priya Patel", "address": "priya.patel@example.com"}
SAM = {"name": "Sam Lee", "address": "sam.lee@example.com"}


def _recipients(*people: dict[str, str]) -> list[dict[str, Any]]:
    return [{"emailAddress": dict(p)} for p in people]


def _message(
    graph: FakeGraph,
    msg_id: str,
    folder: str,
    sender: dict[str, str],
    subject: str,
    body: str,
    days: int,
    hour: int = 9,
    *,
    to: list[dict[str, str]] | None = None,
    cc: list[dict[str, str]] | None = None,
    is_read: bool = True,
    importance: str = "normal",
    flagged: bool = False,
    categories: list[str] | None = None,
    classification: str = "focused",
    is_draft: bool = False,
) -> None:
    graph.messages[msg_id] = {
        "id": msg_id,
        "conversationId": f"conv-{msg_id}",
        "subject": subject,
        "body": {"contentType": "text", "content": body},
        "bodyPreview": body[:255],
        "from": {"emailAddress": dict(sender)},
        "sender": {"emailAddress": dict(sender)},
        "toRecipients": _recipients(*(to or [ME])),
        "ccRecipients": _recipients(*(cc or [])),
        "bccRecipients": [],
        "receivedDateTime": graph.at(days, hour),
        "sentDateTime": graph.at(days, hour),
        "isRead": is_read,
        "isDraft": is_draft,
        "hasAttachments": False,
        "importance": importance,
        "flag": {"flagStatus": "flagged" if flagged else "notFlagged"},
        "categories": categories or [],
        "parentFolderId": folder,
        "inferenceClassification": classification,
        "webLink": f"https://outlook.live.com/mail/item/{msg_id}",
    }


def _attach(graph: FakeGraph, msg_id: str, att_id: str, name: str, ctype: str) -> None:
    content = f"fake {name} content".encode()
    graph.attachments.setdefault(msg_id, []).append(
        {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "id": att_id,
            "name": name,
            "contentType": ctype,
            "size": len(content),
            "isInline": False,
            "contentBytes": base64.b64encode(content).decode(),
        }
    )
    graph.messages[msg_id]["hasAttachments"] = True


def _folder(
    graph: FakeGraph,
    folder_id: str,
    name: str,
    parent: str = "msgfolderroot",
    hidden: bool = False,
) -> None:
    graph.folders[folder_id] = {
        "id": folder_id,
        "displayName": name,
        "parentFolderId": parent,
        "childFolderCount": 0,
        "unreadItemCount": 0,
        "totalItemCount": 0,
        "isHidden": hidden,
    }


def _event(
    graph: FakeGraph,
    event_id: str,
    subject: str,
    days: int,
    start_hour: float,
    hours: float,
    *,
    calendar: str = "cal-default",
    location: str = "",
    body: str = "",
    organizer: dict[str, str] = ME,
    attendees: list[dict[str, str]] | None = None,
    response: str | None = None,
    show_as: str = "busy",
) -> None:
    start_minute = round((start_hour % 1) * 60)
    end_total = start_hour + hours
    end_minute = round((end_total % 1) * 60)
    is_organizer = organizer == ME
    graph.events[event_id] = {
        "id": event_id,
        "subject": subject,
        "start": {
            "dateTime": graph.at(days, int(start_hour), start_minute)[:-1] + ".0000000",
            "timeZone": "UTC",
        },
        "end": {
            "dateTime": graph.at(days, int(end_total), end_minute)[:-1] + ".0000000",
            "timeZone": "UTC",
        },
        "isAllDay": False,
        "location": {"displayName": location},
        "body": {"contentType": "text", "content": body},
        "bodyPreview": body[:255],
        "organizer": {"emailAddress": dict(organizer)},
        "isOrganizer": is_organizer,
        "attendees": [
            {
                "emailAddress": dict(a),
                "type": "required",
                "status": {"response": "none", "time": "0001-01-01T00:00:00Z"},
            }
            for a in (attendees or [])
        ],
        "responseStatus": {
            "response": response or ("organizer" if is_organizer else "notResponded")
        },
        "showAs": show_as,
        "calendarId": calendar,
        "type": "singleInstance",
        "webLink": f"https://outlook.live.com/calendar/item/{event_id}",
    }


def _contact(
    graph: FakeGraph,
    contact_id: str,
    given: str,
    surname: str,
    email: str | None,
    *,
    folder: str = "contacts-root",
    mobile: str | None = None,
    business: list[str] | None = None,
    company: str | None = None,
    job: str | None = None,
    display: str | None = None,
) -> None:
    graph.contacts[contact_id] = {
        "id": contact_id,
        "displayName": display or f"{given} {surname}".strip(),
        "givenName": given,
        "surname": surname,
        "emailAddresses": (
            [{"name": display or f"{given} {surname}".strip(), "address": email}]
            if email
            else []
        ),
        "mobilePhone": mobile,
        "businessPhones": business or [],
        "homePhones": [],
        "companyName": company,
        "jobTitle": job,
        "department": None,
        "parentFolderId": folder,
    }


def _drive(
    graph: FakeGraph,
    item_id: str,
    name: str,
    parent: str,
    *,
    folder: bool = False,
    size: int = 0,
    mime: str = "application/octet-stream",
    days: int = -30,
) -> None:
    item: dict[str, Any] = {
        "id": item_id,
        "name": name,
        "size": size,
        "createdDateTime": graph.at(days - 10),
        "lastModifiedDateTime": graph.at(days),
        "parentReference": {"id": parent},
        "webUrl": f"https://onedrive.live.com/?id={item_id}",
    }
    if folder:
        item["folder"] = {"childCount": 0}
    else:
        item["file"] = {"mimeType": mime}
        item["_content"] = f"fake contents of {name}".encode()
    graph.drive[item_id] = item


def seed(graph: FakeGraph) -> None:
    """Populate ``graph`` with the standard evaluation dataset."""
    # --- mail folders -------------------------------------------------
    for folder_id, name in [
        ("inbox", "Inbox"),
        ("sentitems", "Sent Items"),
        ("drafts", "Drafts"),
        ("deleteditems", "Deleted Items"),
        ("junkemail", "Junk Email"),
        ("archive", "Archive"),
    ]:
        _folder(graph, folder_id, name)
    _folder(graph, "folder-receipts", "Receipts")
    _folder(graph, "folder-old-projects", "Old Projects")
    _folder(graph, "folder-reading", "Reading")
    _folder(graph, "folder-family", "Family", parent="inbox")
    _folder(graph, "folder-school", "School", parent="folder-family")
    _folder(graph, "folder-conversation-history", "Conversation History", hidden=True)
    graph.folders["inbox"]["childFolderCount"] = 1
    graph.folders["folder-family"]["childFolderCount"] = 1

    # --- messages -----------------------------------------------------
    telstra = {"name": "Telstra", "address": "noreply@telstra.com.au"}
    plumber = {
        "name": "Acme Plumbing Accounts",
        "address": "accounts@acmeplumbing.example",
    }
    school = {
        "name": "Riverside Primary Office",
        "address": "office@riverside-primary.example",
    }
    amazon = {"name": "Amazon", "address": "shipment-tracking@amazon.example"}
    accountant = {"name": "Chen & Co Accountants", "address": "hello@chenco.example"}
    brief = {"name": "The Daily Brief", "address": "news@dailybrief.example"}

    _message(
        graph,
        "msg-001",
        "inbox",
        telstra,
        "Your NBN migration: new modem on the way",
        "Hi Alex, your Telstra NBN migration is booked. Your new modem will "
        "arrive within 5 business days. Migration date: next Wednesday.",
        -3,
        is_read=False,
    )
    _message(
        graph,
        "msg-002",
        "inbox",
        SAM,
        "Re: Telstra migration timeline",
        "Alex, Telstra told me the migration timeline is six weeks, and the "
        "old ADSL line gets cut on the migration date. Keep the old modem.",
        -40,
    )
    _message(
        graph,
        "msg-003",
        "inbox",
        JANE,
        "Dinner on Saturday?",
        "Hi Alex and Mark, would you like to come over for dinner on "
        "Saturday at 7pm? Let me know. Jane",
        -2,
        18,
        to=[ME],
        cc=[MARK],
        is_read=False,
    )
    _message(
        graph,
        "msg-004",
        "inbox",
        plumber,
        "Invoice INV-2291 from Acme Plumbing",
        "Please find attached invoice INV-2291 for the hot water service. "
        "Amount due: $480.00 within 14 days.",
        -5,
    )
    _attach(graph, "msg-004", "att-invoice", "INV-2291.pdf", "application/pdf")
    _message(
        graph,
        "msg-005",
        "inbox",
        amazon,
        "Your Amazon order has shipped",
        "Your order #114-2233 (USB-C charger) has shipped and arrives Friday.",
        -1,
        7,
        is_read=False,
    )
    _message(
        graph,
        "msg-006",
        "inbox",
        PRIYA,
        "Quarterly budget review",
        "Hi Alex, I reviewed the Q3 budget. We are 8% over on travel; can "
        "you trim it before Friday? Spreadsheet attached. Priya",
        -6,
        11,
        importance="high",
        flagged=True,
    )
    _attach(
        graph,
        "msg-006",
        "att-budget",
        "budget-q3.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    _message(
        graph,
        "msg-007",
        "inbox",
        school,
        "Excursion permission slip due Friday",
        "Dear parents, please sign the permission slip for the zoo "
        "excursion and return it by Friday.",
        -4,
        is_read=False,
    )
    _message(
        graph,
        "msg-008",
        "junkemail",
        {"name": "Prize Centre", "address": "winner@prizes.example"},
        "You won a prize!!!",
        "Click here to claim your prize now.",
        -2,
    )
    _message(
        graph,
        "msg-009",
        "junkemail",
        {"name": "Crypto Deals", "address": "deals@crypto.example"},
        "Double your crypto today",
        "Guaranteed returns, act fast.",
        -3,
        is_read=False,
    )
    _message(
        graph,
        "msg-010",
        "drafts",
        ME,
        "Holiday plans",
        "Hi Jane, we are thinking of Byron Bay in January. Keen?",
        -1,
        to=[JANE],
        is_draft=True,
    )
    _message(
        graph,
        "msg-011",
        "archive",
        accountant,
        "2025 tax return documents",
        "Attached are your lodged 2025 tax return documents.",
        -200,
    )
    _message(
        graph,
        "msg-012",
        "sentitems",
        ME,
        "Re: Quarterly budget review",
        "Thanks Priya, I'll look at travel this week.",
        -5,
        to=[PRIYA],
    )
    _message(
        graph,
        "msg-013",
        "deleteditems",
        {"name": "Old Newsletter", "address": "news@old.example"},
        "Last issue",
        "This is our final issue.",
        -30,
    )
    _message(
        graph,
        "msg-014",
        "folder-receipts",
        {"name": "Bunnings", "address": "receipts@bunnings.example"},
        "Your Bunnings receipt",
        "Receipt for garden hose $39.00.",
        -12,
    )
    _message(
        graph,
        "msg-015",
        "folder-family",
        JANE,
        "Photos from the beach",
        "Here are the beach photos from Sunday!",
        -8,
    )
    # Newsletter filler: makes the inbox realistically large and pushes
    # msg-002 beyond the newest 50 messages.
    topics = [
        "Markets steady ahead of rate decision",
        "Weekend weather outlook",
        "Five recipes for busy weeknights",
        "Tech roundup",
        "Sports wrap",
    ]
    for i in range(55):
        _message(
            graph,
            f"msg-news-{i:02d}",
            "inbox",
            brief,
            f"The Daily Brief #{900 + i}: {topics[i % len(topics)]}",
            ("Today's top stories. " * 40)
            + "Unsubscribe at any time from the newsletter settings page.",
            -(i // 4) - 1,
            6,
            classification="focused",
        )
    graph.folders["inbox"]["totalItemCount"] = sum(
        1 for m in graph.messages.values() if m["parentFolderId"] == "inbox"
    )
    graph.folders["inbox"]["unreadItemCount"] = sum(
        1
        for m in graph.messages.values()
        if m["parentFolderId"] == "inbox" and not m["isRead"]
    )

    # --- inbox rules --------------------------------------------------
    graph.rules["rule-news"] = {
        "id": "rule-news",
        "displayName": "Newsletters to Reading",
        "sequence": 1,
        "isEnabled": True,
        "hasError": False,
        "isReadOnly": False,
        "conditions": {"senderContains": ["dailybrief"]},
        "actions": {"moveToFolder": "folder-reading", "stopProcessingRules": True},
    }
    graph.rules["rule-boss"] = {
        "id": "rule-boss",
        "displayName": "Flag boss",
        "sequence": 2,
        "isEnabled": True,
        "hasError": False,
        "isReadOnly": False,
        "conditions": {"fromAddresses": [{"emailAddress": dict(PRIYA)}]},
        "actions": {"markImportance": "high"},
    }

    # --- calendars and events -----------------------------------------
    graph.calendars["cal-default"] = {
        "id": "cal-default",
        "name": "Calendar",
        "isDefaultCalendar": True,
        "canEdit": True,
        "color": "auto",
        "owner": dict(ME),
    }
    graph.calendars["cal-family"] = {
        "id": "cal-family",
        "name": "Family",
        "isDefaultCalendar": False,
        "canEdit": True,
        "color": "lightGreen",
        "owner": dict(ME),
    }
    graph.calendars["cal-roster"] = {
        "id": "cal-roster",
        "name": "Old Roster",
        "isDefaultCalendar": False,
        "canEdit": True,
        "color": "lightGray",
        "owner": dict(ME),
    }
    _event(
        graph,
        "evt-dentist",
        "Dentist appointment",
        1,
        10,
        1,
        location="Wilson Dental, King William St",
    )
    _event(
        graph,
        "evt-sync",
        "Project sync",
        2,
        14,
        1,
        location="Teams",
        organizer=PRIYA,
        attendees=[ME, MARK],
        body="Weekly project sync. Agenda: budget, travel.",
        response="notResponded",
        show_as="tentative",
    )
    _event(
        graph,
        "evt-planning",
        "Quarterly planning",
        4,
        13,
        1.5,
        location="Cafe Roma",
        attendees=[JANE, MARK],
        body="Plan Q4 priorities.",
    )
    _event(graph, "evt-gym", "Gym", 3, 7, 1, show_as="busy")
    _event(
        graph,
        "evt-birthday",
        "Mum's birthday dinner",
        6,
        18,
        3,
        calendar="cal-family",
        location="Home",
    )
    _event(graph, "evt-car", "Car service", -10, 8, 2, location="City Motors")
    for day in range(14):
        weekday = (graph.anchor.weekday() + day) % 7
        if weekday < 5:
            _event(
                graph,
                f"evt-standup-{day:02d}",
                "Team standup",
                day,
                9,
                0.5,
                location="Teams",
                organizer=MARK,
                attendees=[ME],
                response="accepted",
            )

    # --- contacts -----------------------------------------------------
    graph.contact_folders["cfolder-family"] = {
        "id": "cfolder-family",
        "displayName": "Family",
        "parentFolderId": "contacts-root",
    }
    graph.contact_folders["cfolder-work"] = {
        "id": "cfolder-work",
        "displayName": "Work",
        "parentFolderId": "contacts-root",
    }
    _contact(
        graph, "contact-jane", "Jane", "Smith", JANE["address"], mobile="0412 111 222"
    )
    _contact(
        graph,
        "contact-mark",
        "Mark",
        "Brown",
        MARK["address"],
        company="Brown Engineering",
        job="Engineer",
        business=["08 8111 2222"],
    )
    _contact(
        graph,
        "contact-priya",
        "Priya",
        "Patel",
        PRIYA["address"],
        folder="cfolder-work",
        company="Northwind",
        job="Finance Manager",
        mobile="0433 555 666",
    )
    _contact(graph, "contact-sam", "Sam", "Lee", SAM["address"])
    _contact(
        graph,
        "contact-dentist",
        "",
        "",
        "reception@wilsondental.example",
        display="Wilson Dental",
        business=["08 8000 1234"],
        company="Wilson Dental",
    )
    _contact(
        graph,
        "contact-anna",
        "Anna",
        "Smith",
        "anna.smith@example.com",
        folder="cfolder-family",
        mobile="0400 999 888",
    )

    # --- OneDrive -----------------------------------------------------
    graph.drive["root"] = {
        "id": "root",
        "name": "root",
        "folder": {"childCount": 0},
        "size": 0,
        "createdDateTime": graph.at(-900),
        "lastModifiedDateTime": graph.at(-1),
        "webUrl": "https://onedrive.live.com/",
        "root": {},
    }
    _drive(graph, "item-documents", "Documents", "root", folder=True)
    _drive(graph, "item-photos", "Photos", "root", folder=True)
    _drive(
        graph, "item-notes", "Notes.txt", "root", size=512, mime="text/plain", days=-2
    )
    _drive(graph, "item-tax", "Tax", "item-documents", folder=True)
    _drive(graph, "item-old", "Old", "item-documents", folder=True)
    _drive(
        graph,
        "item-budget",
        "budget.xlsx",
        "item-documents",
        size=48_213,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        days=-3,
    )
    _drive(
        graph,
        "item-cv",
        "CV.docx",
        "item-documents",
        size=31_004,
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    _drive(
        graph,
        "item-taxreturn",
        "2025-tax-return.pdf",
        "item-tax",
        size=402_112,
        mime="application/pdf",
        days=-200,
    )
    _drive(
        graph,
        "item-receipts2024",
        "receipts-2024.zip",
        "item-old",
        size=2_004_112,
        mime="application/zip",
        days=-300,
    )
    _drive(
        graph,
        "item-beach",
        "beach.jpg",
        "item-photos",
        size=3_200_000,
        mime="image/jpeg",
        days=-8,
    )
