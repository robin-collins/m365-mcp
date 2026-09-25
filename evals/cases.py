"""Golden prompts for the tool-surface evaluation (concept §16.2).

Each case states the acceptable first tools and the success calls for the
legacy 85-tool surface and for the unified 29-tool surface. IDs such as
``msg-003`` refer to ``evals/fixtures.py``. ``{sandbox}`` in a prompt is
replaced with the case's local sandbox folder.

Every fourth case (index 3, 7, 11, ...) is held out: it is not used when
tuning descriptions (task U4.1) and is reported separately.
"""

from __future__ import annotations

from typing import Any

from .grading import Case, Expectation


def c(tool: str, result_contains: str | None = None, **args: Any) -> dict[str, Any]:
    """Build a success alternative; ``__`` in keywords becomes ``.``."""
    alt: dict[str, Any] = {
        "tool": tool,
        "args": {k.replace("__", "."): v for k, v in args.items()},
    }
    if result_contains:
        alt["result_contains"] = result_contains
    return alt


def has(value: str) -> dict[str, str]:
    """Matcher: the argument contains ``value``."""
    return {"contains": value}


def one_of(*values: Any) -> dict[str, list[Any]]:
    """Matcher: the argument equals one of ``values``."""
    return {"any": list(values)}


PRESENT = {"present": True}

JUNK = one_of("junk", "junkemail", "junk email")
ARCHIVE = one_of("archive", "Archive")
FAMILY_MAIL = one_of("folder-family", "Family")
RECEIPTS_MAIL = one_of("folder-receipts", "Receipts")


def E(first: list[str], *success: dict[str, Any]) -> Expectation:
    """Shorthand for an expectation."""
    return Expectation(first=first, success=list(success))


def _case(
    cid: str,
    category: str,
    prompt: str,
    legacy: Expectation,
    unified: Expectation,
    **kwargs: Any,
) -> Case:
    return Case(
        id=cid,
        category=category,
        prompt=prompt,
        legacy=legacy,
        unified=unified,
        **kwargs,
    )


NO_TOOL = Expectation()

_RAW_CASES: list[Case] = [
    # ------------------------------------------------------------------
    # direct
    # ------------------------------------------------------------------
    _case(
        "d01",
        "direct",
        "Show my unread emails.",
        E(["email_list", "search_emails"], c("email_list"), c("search_emails")),
        E(["m365_list"], c("m365_list", resource="email", email_filter__unread=True)),
    ),
    _case(
        "d02",
        "direct",
        "List the folders in my mailbox.",
        E(
            ["emailfolders_list", "emailfolders_get_tree"],
            c("emailfolders_list"),
            c("emailfolders_get_tree"),
        ),
        E(["m365_list"], c("m365_list", resource="email_folder")),
    ),
    _case(
        "d03",
        "direct",
        "What's on my calendar in the next 7 days?",
        E(["calendar_list_events"], c("calendar_list_events")),
        E(["m365_list"], c("m365_list", resource="event")),
    ),
    _case(
        "d04",
        "direct",
        "Show me my contacts.",
        E(["contact_list"], c("contact_list")),
        E(["m365_list"], c("m365_list", resource="contact")),
    ),
    _case(
        "d05",
        "direct",
        "What's in my OneDrive Documents folder?",
        E(
            ["file_list", "folder_list"],
            c("file_list", path=has("Documents")),
            c("file_list", folder_id="item-documents"),
            c("folder_list", path=has("Documents")),
        ),
        E(
            ["m365_list"],
            c("m365_list", resource="drive_item", path=has("Documents")),
            c("m365_list", resource="drive_item", container_id="item-documents"),
        ),
    ),
    _case(
        "d06",
        "direct",
        "List my calendars.",
        E(["calendar_list_calendars"], c("calendar_list_calendars")),
        E(["m365_list"], c("m365_list", resource="calendar")),
    ),
    _case(
        "d07",
        "direct",
        "Show my inbox rules.",
        E(["emailrules_list"], c("emailrules_list")),
        E(["m365_list"], c("m365_list", resource="email_rule")),
    ),
    _case(
        "d08",
        "direct",
        "Find the email about the Telstra NBN migration.",
        E(
            ["search_emails", "search_unified"],
            c("search_emails", query=has("telstra")),
            c("search_emails", query=has("migration")),
        ),
        E(
            ["m365_search"],
            c("m365_search", query=has("telstra")),
            c("m365_search", query=has("migration")),
        ),
    ),
    _case(
        "d09",
        "direct",
        "Search my OneDrive for budget.",
        E(["search_files", "search_unified"], c("search_files", query=has("budget"))),
        E(["m365_search"], c("m365_search", query=has("budget"))),
    ),
    _case(
        "d10",
        "direct",
        "Find Priya's contact details.",
        E(
            ["search_contacts", "contact_list", "search_unified"],
            c("search_contacts", query=has("priya")),
            c("contact_get", contact_id="contact-priya"),
        ),
        E(
            ["m365_search", "m365_list"],
            c("m365_search", query=has("priya")),
            c("m365_get", resource="contact", id="contact-priya"),
        ),
    ),
    _case(
        "d11",
        "direct",
        "Create a mail folder called Receipts 2026.",
        E(
            ["emailfolders_create"],
            c("emailfolders_create", display_name="Receipts 2026"),
        ),
        E(
            ["m365_create"],
            c(
                "m365_create",
                resource="email_folder",
                email_folder__display_name="Receipts 2026",
            ),
        ),
    ),
    _case(
        "d12",
        "direct",
        "Create a new calendar named Gym.",
        E(["calendar_create_calendar"], c("calendar_create_calendar", name="Gym")),
        E(["m365_create"], c("m365_create", resource="calendar", calendar__name="Gym")),
    ),
    _case(
        "d13",
        "direct",
        "Add a contact: Tom Nguyen, tom.nguyen@example.com, mobile 0412 345 678.",
        E(["contact_create"], c("contact_create", given_name="Tom")),
        E(
            ["m365_create"],
            c("m365_create", resource="contact", contact__given_name="Tom"),
        ),
    ),
    _case(
        "d14",
        "direct",
        "Create a folder called Receipts inside my OneDrive Documents folder.",
        E(
            ["folder_create", "folder_get", "folder_list", "file_list"],
            c("folder_create", name="Receipts"),
        ),
        E(
            ["m365_create", "m365_list", "m365_get"],
            c("m365_create", resource="drive_item", drive_folder__name="Receipts"),
        ),
    ),
    _case(
        "d15",
        "direct",
        "Mark the Amazon shipping email as read.",
        E(
            ["search_emails", "email_list"],
            c("email_mark_read", email_id="msg-005"),
            c("email_update", email_id="msg-005"),
        ),
        E(
            ["m365_search", "m365_list"],
            c(
                "m365_update",
                resource="email",
                id="msg-005",
                email_changes__is_read=True,
            ),
        ),
    ),
    _case(
        "d16",
        "direct",
        "Flag the plumbing invoice email for follow-up.",
        E(
            ["search_emails", "email_list"],
            c("email_flag", email_id="msg-004"),
            c("email_update", email_id="msg-004"),
        ),
        E(
            ["m365_search", "m365_list"],
            c(
                "m365_update",
                resource="email",
                id="msg-004",
                email_changes__flag__status="flagged",
            ),
        ),
    ),
    _case(
        "d17",
        "direct",
        "Archive the Amazon order email.",
        E(
            ["search_emails", "email_list"],
            c("email_archive", email_id="msg-005"),
            c("email_move", email_id="msg-005", destination_folder=ARCHIVE),
        ),
        E(
            ["m365_search", "m365_list"],
            c("m365_move", resource="email", id="msg-005", destination_id=ARCHIVE),
        ),
    ),
    _case(
        "d18",
        "direct",
        "Rename Notes.txt in my OneDrive to Shopping list.txt.",
        E(
            ["search_files", "file_list"],
            c("file_rename", file_id="item-notes", new_name="Shopping list.txt"),
        ),
        E(
            ["m365_search", "m365_list", "m365_get"],
            c(
                "m365_update",
                resource="drive_item",
                id="item-notes",
                drive_item_changes__name="Shopping list.txt",
            ),
        ),
    ),
    _case(
        "d19",
        "direct",
        "Draft an email to jane.smith@example.com saying I'll bring dessert on "
        "Saturday. Don't send it.",
        E(["email_create_draft"], c("email_create_draft", to=has("jane.smith"))),
        E(["email_create_draft"], c("email_create_draft", to=has("jane.smith"))),
    ),
    _case(
        "d20",
        "direct",
        "Send an email to sam.lee@example.com with the subject 'Modem arrived' "
        "saying the new modem arrived today.",
        E(["email_send"], c("email_send", to=has("sam.lee"))),
        E(["email_send"], c("email_send", mode="new", to=has("sam.lee"))),
        side_effect=True,
    ),
    _case(
        "d21",
        "direct",
        "Reply to Jane's dinner email and say Saturday works for me.",
        E(["search_emails", "email_list"], c("email_reply", email_id="msg-003")),
        E(
            ["m365_search", "m365_list"],
            c("email_reply", email_id="msg-003", mode="sender"),
        ),
        side_effect=True,
    ),
    _case(
        "d22",
        "direct",
        "Reply all to Jane's dinner invitation: count me in!",
        E(["search_emails", "email_list"], c("email_reply_all", email_id="msg-003")),
        E(
            ["m365_search", "m365_list"],
            c("email_reply", email_id="msg-003", mode="all"),
        ),
        side_effect=True,
    ),
    _case(
        "d23",
        "direct",
        "Forward the Acme Plumbing invoice email to bookkeeper@chenco.example.",
        E(
            ["search_emails", "email_list"],
            c("email_forward", email_id="msg-004", to=has("bookkeeper@chenco")),
        ),
        E(
            ["m365_search", "m365_list"],
            c("email_forward", email_id="msg-004", to=has("bookkeeper@chenco")),
        ),
        side_effect=True,
    ),
    _case(
        "d24",
        "direct",
        "Delete the 'You won a prize' email in my junk folder.",
        E(["search_emails", "email_list"], c("email_delete", email_id="msg-008")),
        E(
            ["m365_search", "m365_list"],
            c("m365_delete", resource="email", id="msg-008"),
        ),
        side_effect=True,
    ),
    _case(
        "d25",
        "direct",
        "Add a dentist check-up to my calendar next Tuesday at 3pm for an hour.",
        E(
            ["calendar_create_event"],
            c("calendar_create_event", subject=has("dentist")),
        ),
        E(
            ["calendar_create_event"],
            c("calendar_create_event", subject=has("dentist")),
        ),
    ),
    _case(
        "d26",
        "direct",
        "Accept the Project sync meeting invitation.",
        E(
            ["calendar_list_events", "search_events"],
            c("calendar_respond_event", event_id="evt-sync", response=one_of("accept")),
        ),
        E(
            ["m365_search", "m365_list"],
            c("calendar_respond", event_id="evt-sync", action="accept"),
        ),
        side_effect=True,
    ),
    _case(
        "d27",
        "direct",
        "Decline the Project sync meeting.",
        E(
            ["calendar_list_events", "search_events"],
            c(
                "calendar_respond_event",
                event_id="evt-sync",
                response=one_of("decline"),
            ),
        ),
        E(
            ["m365_search", "m365_list"],
            c("calendar_respond", event_id="evt-sync", action="decline"),
        ),
        side_effect=True,
    ),
    _case(
        "d28",
        "direct",
        "When am I free for an hour on Thursday?",
        E(
            [
                "calendar_check_availability",
                "calendar_get_free_busy",
                "calendar_list_events",
            ],
            c("calendar_check_availability"),
            c("calendar_get_free_busy"),
            c("calendar_list_events"),
        ),
        E(
            ["calendar_find_availability"],
            c("calendar_find_availability", slot_minutes=60),
        ),
    ),
    _case(
        "d29",
        "direct",
        "Share budget.xlsx from my OneDrive with a view-only link.",
        E(
            ["search_files", "file_list"],
            c(
                "file_share",
                file_id="item-budget",
                permission_type=one_of("view", None),
            ),
        ),
        E(
            ["m365_search", "m365_list", "m365_get"],
            c("drive_share", item_id="item-budget", mode="link", link_type="view"),
        ),
        side_effect=True,
    ),
    _case(
        "d30",
        "direct",
        "Get me a download link for CV.docx in OneDrive.",
        E(["search_files", "file_list"], c("file_download_url", file_id="item-cv")),
        E(
            ["m365_search", "m365_list", "m365_get"],
            c(
                "m365_get_content",
                resource="drive_item",
                id="item-cv",
                mode="download_url",
            ),
        ),
    ),
    _case(
        "d31",
        "direct",
        "Copy budget.xlsx into my OneDrive Tax folder.",
        E(
            ["search_files", "file_list", "folder_list"],
            c("file_copy", file_id="item-budget", destination_folder_id="item-tax"),
        ),
        E(
            ["m365_search", "m365_list", "m365_get"],
            c("drive_copy", item_id="item-budget", destination_id="item-tax"),
            c("drive_copy", item_id="item-budget", destination_path=has("Tax")),
        ),
    ),
    _case(
        "d32",
        "direct",
        "Move CV.docx into the Old folder in OneDrive.",
        E(
            ["search_files", "file_list", "folder_list"],
            c("file_move", file_id="item-cv", destination_folder_id="item-old"),
        ),
        E(
            ["m365_search", "m365_list", "m365_get"],
            c(
                "m365_move",
                resource="drive_item",
                id="item-cv",
                destination_id="item-old",
            ),
            c(
                "m365_move",
                resource="drive_item",
                id="item-cv",
                destination_path=has("Old"),
            ),
        ),
    ),
    _case(
        "d33",
        "direct",
        "Mark everything in my Junk Email folder as read.",
        E(
            ["emailfolders_mark_all_as_read", "emailfolders_list"],
            c("emailfolders_mark_all_as_read", folder_id=JUNK),
        ),
        E(
            ["email_folder_mark_all_read", "m365_list"],
            c("email_folder_mark_all_read", folder_id=JUNK),
        ),
    ),
    _case(
        "d34",
        "direct",
        "Empty my junk email folder.",
        E(
            ["emailfolders_empty", "emailfolders_list"],
            c("emailfolders_empty", folder_id=JUNK),
        ),
        E(["email_folder_empty", "m365_list"], c("email_folder_empty", folder_id=JUNK)),
        side_effect=True,
    ),
    _case(
        "d35",
        "direct",
        "Export Jane Smith's contact as a vCard.",
        E(
            ["search_contacts", "contact_list"],
            c("contact_export", contact_id="contact-jane"),
        ),
        E(
            ["m365_search", "m365_list"],
            c("m365_get_content", resource="contact", id="contact-jane", mode="vcard"),
        ),
    ),
    _case(
        "d36",
        "direct",
        "Show me the full text of the quarterly budget review email.",
        E(["search_emails", "email_list"], c("email_get", email_id="msg-006")),
        E(["m365_search", "m365_list"], c("m365_get", resource="email", id="msg-006")),
    ),
    _case(
        "d37",
        "direct",
        "Save the PDF attached to the Acme Plumbing invoice email into {sandbox}.",
        E(
            ["search_emails", "email_list"],
            c("email_get_attachment", email_id="msg-004", attachment_id="att-invoice"),
        ),
        E(
            ["m365_search", "m365_list"],
            c(
                "m365_get_content",
                resource="email",
                id="msg-004",
                mode="download",
                attachment_id="att-invoice",
            ),
        ),
    ),
    _case(
        "d38",
        "direct",
        "Upload {sandbox}/report.pdf to my OneDrive Documents folder.",
        E(["file_create"], c("file_create", onedrive_path=has("Documents"))),
        E(
            ["drive_upload"],
            c("drive_upload", parent_path=has("Documents")),
            c("drive_upload", parent_id="item-documents"),
        ),
    ),
    _case(
        "d39",
        "direct",
        "Create an inbox rule that moves email from news@dailybrief.example "
        "into my Reading folder.",
        E(["emailrules_create", "emailfolders_list"], c("emailrules_create")),
        E(["email_rule_manage", "m365_list"], c("email_rule_manage", action="create")),
    ),
    _case(
        "d40",
        "direct",
        "Turn off my 'Flag boss' inbox rule.",
        E(
            ["emailrules_list"],
            c("emailrules_update", rule_id="rule-boss", is_enabled=False),
        ),
        E(
            ["m365_list"],
            c(
                "email_rule_manage",
                action="set_enabled",
                rule_id="rule-boss",
                is_enabled=False,
            ),
            c(
                "email_rule_manage",
                action="update",
                rule_id="rule-boss",
                rule__is_enabled=False,
            ),
        ),
    ),
    _case(
        "d41",
        "direct",
        "Move my 'Flag boss' rule to the top of the rule list.",
        E(["emailrules_list"], c("emailrules_move_top", rule_id="rule-boss")),
        E(
            ["m365_list"],
            c(
                "email_rule_manage",
                action="reorder",
                rule_id="rule-boss",
                position="top",
            ),
        ),
    ),
    _case(
        "d42",
        "direct",
        "Forward the Project sync invitation to mark.brown@example.com.",
        E(
            ["calendar_list_events", "search_events"],
            c("calendar_forward_event", event_id="evt-sync", to=has("mark.brown")),
        ),
        E(
            ["m365_search", "m365_list"],
            c("calendar_forward", event_id="evt-sync", to=has("mark.brown")),
        ),
        side_effect=True,
    ),
    _case(
        "d43",
        "direct",
        "Cancel the Quarterly planning meeting I organised.",
        E(
            ["calendar_list_events", "search_events"],
            c("calendar_delete_event", event_id="evt-planning"),
        ),
        E(
            ["m365_search", "m365_list"],
            c("m365_delete", resource="event", id="evt-planning"),
        ),
        side_effect=True,
    ),
    _case(
        "d44",
        "direct",
        "Move the Quarterly planning meeting to start at 3pm on the same day.",
        E(
            ["calendar_list_events", "search_events"],
            c("calendar_update_event", event_id="evt-planning"),
        ),
        E(
            ["m365_search", "m365_list"],
            c("calendar_update_event", event_id="evt-planning", changes__start=PRESENT),
        ),
        side_effect=True,
    ),
    _case(
        "d45",
        "direct",
        "Put Jane Smith in my Family contacts folder.",
        E(
            ["search_contacts", "contact_list"],
            c(
                "contact_add_to_list",
                contact_id="contact-jane",
                list_id="cfolder-family",
            ),
        ),
        E(
            ["m365_search", "m365_list"],
            c(
                "m365_move",
                resource="contact",
                id="contact-jane",
                destination_id="cfolder-family",
            ),
        ),
    ),
    _case(
        "d46",
        "direct",
        "Rename the 'Old Projects' mail folder to 'Archive 2024'.",
        E(
            ["emailfolders_list", "emailfolders_get_tree"],
            c(
                "emailfolders_rename",
                folder_id="folder-old-projects",
                new_display_name="Archive 2024",
            ),
        ),
        E(
            ["m365_list"],
            c(
                "m365_update",
                resource="email_folder",
                id="folder-old-projects",
                email_folder_changes__display_name="Archive 2024",
            ),
        ),
    ),
    _case(
        "d47",
        "direct",
        "Delete my 'Old Roster' calendar.",
        E(
            ["calendar_list_calendars"],
            c("calendar_delete_calendar", calendar_id="cal-roster"),
        ),
        E(["m365_list"], c("m365_delete", resource="calendar", id="cal-roster")),
        side_effect=True,
    ),
    _case(
        "d48",
        "direct",
        "Update Mark Brown's job title to Senior Engineer.",
        E(
            ["search_contacts", "contact_list"],
            c("contact_update", contact_id="contact-mark"),
        ),
        E(
            ["m365_search", "m365_list"],
            c(
                "m365_update",
                resource="contact",
                id="contact-mark",
                contact_changes__job_title="Senior Engineer",
            ),
        ),
    ),
    _case(
        "d49",
        "direct",
        "Show me the folder tree of my OneDrive.",
        E(["folder_get_tree"], c("folder_get_tree")),
        E(["m365_list"], c("m365_list", resource="drive_item", recursive=True)),
    ),
    _case(
        "d50",
        "direct",
        "Show my whole mailbox folder hierarchy, including subfolders.",
        E(["emailfolders_get_tree"], c("emailfolders_get_tree")),
        E(["m365_list"], c("m365_list", resource="email_folder", recursive=True)),
    ),
    # ------------------------------------------------------------------
    # indirect
    # ------------------------------------------------------------------
    _case(
        "i01",
        "indirect",
        "Did the plumber ever send me their invoice?",
        E(
            ["search_emails", "email_list", "search_unified"],
            c("search_emails", result_contains="msg-004"),
            c("email_list", result_contains="msg-004"),
        ),
        E(
            ["m365_search", "m365_list"],
            c("m365_search", result_contains="msg-004"),
            c("m365_list", result_contains="msg-004"),
        ),
    ),
    _case(
        "i02",
        "indirect",
        "Anything from my kid's school that I haven't looked at yet?",
        E(
            ["search_emails", "email_list"],
            c("search_emails", result_contains="msg-007"),
            c("email_list", result_contains="msg-007"),
        ),
        E(
            ["m365_search", "m365_list"],
            c("m365_search", result_contains="msg-007"),
            c("m365_list", result_contains="msg-007"),
        ),
    ),
    _case(
        "i03",
        "indirect",
        "Am I double-booked anywhere this week?",
        E(
            ["calendar_list_events", "calendar_check_availability"],
            c("calendar_list_events"),
            c("calendar_check_availability"),
        ),
        E(
            ["m365_list", "calendar_find_availability"],
            c("m365_list", resource="event"),
            c("calendar_find_availability"),
        ),
    ),
    _case(
        "i04",
        "indirect",
        "What's Sam's email address?",
        E(
            ["search_contacts", "contact_list"],
            c("search_contacts", result_contains="sam.lee@example.com"),
            c("contact_list", result_contains="sam.lee@example.com"),
        ),
        E(
            ["m365_search", "m365_list"],
            c("m365_search", result_contains="sam.lee@example.com"),
            c("m365_list", result_contains="sam.lee@example.com"),
        ),
    ),
    _case(
        "i05",
        "indirect",
        "I need the 2025 tax return PDF from OneDrive on this computer. Put it in {sandbox}.",
        E(
            ["search_files", "file_list", "folder_list"],
            c("file_get", file_id="item-taxreturn"),
        ),
        E(
            ["m365_search", "m365_list"],
            c(
                "m365_get_content",
                resource="drive_item",
                id="item-taxreturn",
                mode="download",
            ),
        ),
    ),
    _case(
        "i06",
        "indirect",
        "Let Jane know by email that I'm running 10 minutes late.",
        E(
            ["search_contacts", "contact_list", "email_send", "search_emails"],
            c("email_send", to=has("jane.smith")),
            c("email_reply", email_id="msg-003"),
        ),
        E(
            ["m365_search", "m365_list", "email_send"],
            c("email_send", to=has("jane.smith")),
            c("email_reply", email_id="msg-003"),
        ),
        side_effect=True,
    ),
    _case(
        "i07",
        "indirect",
        "Tell the Project sync organiser I'll probably come but might not make it.",
        E(
            ["calendar_list_events", "search_events"],
            c(
                "calendar_respond_event",
                event_id="evt-sync",
                response=one_of("tentativelyAccept", "tentative"),
            ),
        ),
        E(
            ["m365_search", "m365_list"],
            c("calendar_respond", event_id="evt-sync", action="tentative"),
        ),
        side_effect=True,
    ),
    _case(
        "i08",
        "indirect",
        "Clean out the spam folder, I don't need any of it.",
        E(
            ["emailfolders_empty", "emailfolders_list", "email_list"],
            c("emailfolders_empty", folder_id=JUNK),
        ),
        E(["email_folder_empty", "m365_list"], c("email_folder_empty", folder_id=JUNK)),
        side_effect=True,
    ),
    _case(
        "i09",
        "indirect",
        "I've caught up on my inbox, clear the unread count.",
        E(
            ["emailfolders_mark_all_as_read"],
            c("emailfolders_mark_all_as_read", folder_id=one_of("inbox", "Inbox")),
        ),
        E(
            ["email_folder_mark_all_read"],
            c("email_folder_mark_all_read", folder_id=one_of("inbox", "Inbox")),
        ),
    ),
    _case(
        "i10",
        "indirect",
        "Block out this Friday afternoon, 1 to 5pm, for focus time.",
        E(["calendar_create_event"], c("calendar_create_event")),
        E(
            ["calendar_create_event"],
            c("calendar_create_event", attendees={"absent": True}),
        ),
    ),
    _case(
        "i11",
        "indirect",
        "The dentist's phone number changed to 08 8123 4567. Update it.",
        E(
            ["search_contacts", "contact_list"],
            c("contact_update", contact_id="contact-dentist"),
        ),
        E(
            ["m365_search", "m365_list"],
            c("m365_update", resource="contact", id="contact-dentist"),
        ),
    ),
    _case(
        "i12",
        "indirect",
        "Where did I put my CV?",
        E(
            ["search_files", "search_unified", "file_list"],
            c("search_files", result_contains="item-cv"),
            c("search_unified", result_contains="item-cv"),
        ),
        E(["m365_search"], c("m365_search", result_contains="item-cv")),
    ),
    _case(
        "i13",
        "indirect",
        "Get rid of the Old folder inside Documents on OneDrive.",
        E(
            ["folder_list", "file_list", "search_files", "folder_get"],
            c("folder_delete", folder_id="item-old"),
            c("file_delete", file_id="item-old"),
        ),
        E(
            ["m365_list", "m365_search", "m365_get"],
            c("m365_delete", resource="drive_item", id="item-old"),
        ),
        side_effect=True,
    ),
    _case(
        "i14",
        "indirect",
        "Make sure anything from office@riverside-primary.example is automatically "
        "marked high importance.",
        E(["emailrules_create"], c("emailrules_create")),
        E(["email_rule_manage"], c("email_rule_manage", action="create")),
    ),
    _case(
        "i15",
        "indirect",
        "Let Mark (mark.brown@example.com) edit the budget spreadsheet in my OneDrive.",
        E(["search_files", "file_list"], c("file_share", file_id="item-budget")),
        E(
            ["m365_search", "m365_list"],
            c("drive_share", item_id="item-budget", mode="invite", role="write"),
            c("drive_share", item_id="item-budget", mode="link", link_type="edit"),
        ),
        side_effect=True,
    ),
    _case(
        "i16",
        "indirect",
        "What did Priya say about the budget?",
        E(
            ["search_emails", "email_list"],
            c("search_emails", result_contains="msg-006"),
            c("email_get", email_id="msg-006"),
        ),
        E(
            ["m365_search", "m365_list"],
            c("m365_search", result_contains="msg-006"),
            c("m365_get", resource="email", id="msg-006"),
        ),
    ),
    _case(
        "i17",
        "indirect",
        "Remind me what time my dentist appointment is.",
        E(
            ["search_events", "calendar_list_events"],
            c("search_events", result_contains="evt-dentist"),
            c("calendar_list_events", result_contains="evt-dentist"),
        ),
        E(
            ["m365_search", "m365_list"],
            c("m365_search", result_contains="evt-dentist"),
            c("m365_list", result_contains="evt-dentist"),
        ),
    ),
    _case(
        "i18",
        "indirect",
        "Who's coming to the Quarterly planning meeting?",
        E(
            ["calendar_list_events", "search_events"],
            c("calendar_get_event", event_id="evt-planning"),
            c(
                "calendar_list_events",
                include_details=True,
                result_contains="jane.smith",
            ),
        ),
        E(
            ["m365_search", "m365_list"],
            c("m365_get", resource="event", id="evt-planning"),
        ),
    ),
    _case(
        "i19",
        "indirect",
        "Find Sam's email from last month about the Telstra migration timeline.",
        E(
            ["search_emails", "email_list"],
            c("search_emails", result_contains="msg-002"),
            c("email_get", email_id="msg-002"),
        ),
        E(
            ["m365_search", "m365_list"],
            c("m365_search", result_contains="msg-002"),
            c("m365_list", result_contains="msg-002"),
        ),
    ),
    _case(
        "i20",
        "indirect",
        "How much do I owe the plumber?",
        E(
            ["search_emails", "email_list"],
            c("search_emails", result_contains="480"),
            c("email_get", email_id="msg-004"),
        ),
        E(
            ["m365_search", "m365_list"],
            c("m365_search", result_contains="480"),
            c("m365_get", resource="email", id="msg-004"),
        ),
    ),
    # ------------------------------------------------------------------
    # competing tools
    # ------------------------------------------------------------------
    _case(
        "c01",
        "competing",
        "Show me the emails in my Receipts folder.",
        E(
            ["email_list", "emailfolders_list"],
            c("email_list", folder_id="folder-receipts"),
            c("email_list", folder=one_of("Receipts", "folder-receipts")),
        ),
        E(["m365_list"], c("m365_list", resource="email", container_id=RECEIPTS_MAIL)),
    ),
    _case(
        "c02",
        "competing",
        "Find emails that mention the permission slip.",
        E(
            ["search_emails", "search_unified"],
            c("search_emails", query=has("permission")),
        ),
        E(["m365_search"], c("m365_search", query=has("permission"))),
    ),
    _case(
        "c03",
        "competing",
        "Open the Documents folder in OneDrive.",
        E(
            ["file_list", "folder_list", "folder_get"],
            c("file_list", path=has("Documents")),
            c("folder_list", path=has("Documents")),
            c("folder_get", path=has("Documents")),
            c("file_list", folder_id="item-documents"),
        ),
        E(
            ["m365_list", "m365_get"],
            c("m365_list", resource="drive_item", path=has("Documents")),
            c("m365_list", resource="drive_item", container_id="item-documents"),
        ),
    ),
    _case(
        "c04",
        "competing",
        "Show me what's in my Family mail folder.",
        E(
            ["email_list", "emailfolders_list", "emailfolders_get_tree"],
            c("email_list", folder_id="folder-family"),
            c("email_list", folder=FAMILY_MAIL),
        ),
        E(["m365_list"], c("m365_list", resource="email", container_id=FAMILY_MAIL)),
    ),
    _case(
        "c05",
        "competing",
        "Move the plumbing invoice email into my Receipts mail folder.",
        E(
            ["search_emails", "email_list", "emailfolders_list"],
            c("email_move", email_id="msg-004", destination_folder=RECEIPTS_MAIL),
        ),
        E(
            ["m365_search", "m365_list"],
            c(
                "m365_move",
                resource="email",
                id="msg-004",
                destination_id="folder-receipts",
            ),
        ),
    ),
    _case(
        "c06",
        "competing",
        "Mark the school excursion email as unread again.",
        E(
            ["search_emails", "email_list"],
            c("email_mark_read", email_id="msg-007", is_read=False),
            c("email_update", email_id="msg-007"),
        ),
        E(
            ["m365_search", "m365_list"],
            c(
                "m365_update",
                resource="email",
                id="msg-007",
                email_changes__is_read=False,
            ),
        ),
    ),
    _case(
        "c07",
        "competing",
        "Create a folder called Kids in my mailbox.",
        E(["emailfolders_create"], c("emailfolders_create", display_name="Kids")),
        E(
            ["m365_create"],
            c(
                "m365_create",
                resource="email_folder",
                email_folder__display_name="Kids",
            ),
        ),
    ),
    _case(
        "c08",
        "competing",
        "Create a folder called Kids in my OneDrive.",
        E(["folder_create"], c("folder_create", name="Kids")),
        E(
            ["m365_create"],
            c("m365_create", resource="drive_item", drive_folder__name="Kids"),
        ),
    ),
    _case(
        "c09",
        "competing",
        "Rename the Tax folder in OneDrive to Taxes.",
        E(
            ["folder_list", "file_list", "search_files", "folder_get"],
            c("folder_rename", folder_id="item-tax", new_name="Taxes"),
            c("file_rename", file_id="item-tax", new_name="Taxes"),
        ),
        E(
            ["m365_list", "m365_search", "m365_get"],
            c(
                "m365_update",
                resource="drive_item",
                id="item-tax",
                drive_item_changes__name="Taxes",
            ),
        ),
    ),
    _case(
        "c10",
        "competing",
        "Move the Tax folder in OneDrive up to the top level.",
        E(
            ["folder_list", "file_list", "search_files", "folder_get"],
            c("folder_move", folder_id="item-tax", destination_folder_id="root"),
            c("file_move", file_id="item-tax", destination_folder_id="root"),
        ),
        E(
            ["m365_list", "m365_search", "m365_get"],
            c("m365_move", resource="drive_item", id="item-tax", destination_id="root"),
            c("m365_move", resource="drive_item", id="item-tax", destination_path="/"),
        ),
    ),
    _case(
        "c11",
        "competing",
        "Show me emails from Priya.",
        E(
            ["search_emails", "email_list"],
            c("search_emails", result_contains="msg-006"),
            c("email_list", result_contains="msg-006"),
        ),
        E(
            ["m365_list", "m365_search"],
            c("m365_list", resource="email", email_filter__from=has("priya")),
            c("m365_search", result_contains="msg-006"),
        ),
    ),
    _case(
        "c12",
        "competing",
        "Search my calendar for anything about the dentist.",
        E(
            ["search_events", "search_unified"],
            c("search_events", query=has("dentist")),
        ),
        E(["m365_search"], c("m365_search", query=has("dentist"))),
    ),
    _case(
        "c13",
        "competing",
        "Show me the emails I received yesterday.",
        E(["email_list", "search_emails"], c("email_list")),
        E(
            ["m365_list"],
            c("m365_list", resource="email", email_filter__received_after=PRESENT),
        ),
    ),
    _case(
        "c14",
        "competing",
        "What files are in my OneDrive Tax folder?",
        E(
            ["file_list", "folder_list", "search_files"],
            c("file_list", path=has("Tax")),
            c("file_list", folder_id="item-tax"),
        ),
        E(
            ["m365_list", "m365_search"],
            c("m365_list", resource="drive_item", path=has("Tax")),
            c("m365_list", resource="drive_item", container_id="item-tax"),
        ),
    ),
    _case(
        "c15",
        "competing",
        "Find my contacts with the surname Smith.",
        E(
            ["search_contacts", "contact_list"],
            c("search_contacts", query=has("smith")),
            c("contact_list"),
        ),
        E(["m365_search", "m365_list"], c("m365_search", query=has("smith"))),
    ),
    _case(
        "c16",
        "competing",
        "Send the draft email about holiday plans that I wrote.",
        E(["email_list", "search_emails"], c("email_send", to=has("jane.smith"))),
        E(
            ["m365_list", "m365_search"],
            c("email_send", mode="draft", draft_id="msg-010"),
        ),
        side_effect=True,
    ),
    _case(
        "c17",
        "competing",
        "Delete my draft about holiday plans.",
        E(["email_list", "search_emails"], c("email_delete", email_id="msg-010")),
        E(
            ["m365_list", "m365_search"],
            c("m365_delete", resource="email", id="msg-010"),
        ),
        side_effect=True,
    ),
    _case(
        "c18",
        "competing",
        "How big is budget.xlsx and when was it last changed?",
        E(
            ["search_files", "file_list"],
            c("search_files", result_contains="item-budget"),
            c("file_list", result_contains="item-budget"),
        ),
        E(
            ["m365_search", "m365_list", "m365_get"],
            c("m365_get", resource="drive_item", id="item-budget"),
            c("m365_get", resource="drive_item", path=has("budget.xlsx")),
            c("m365_search", result_contains="item-budget"),
            c("m365_list", result_contains="item-budget"),
        ),
    ),
    _case(
        "c19",
        "competing",
        "Download budget.xlsx from OneDrive into {sandbox}.",
        E(["search_files", "file_list"], c("file_get", file_id="item-budget")),
        E(
            ["m365_search", "m365_list", "m365_get", "m365_get_content"],
            c(
                "m365_get_content",
                resource="drive_item",
                id="item-budget",
                mode="download",
            ),
        ),
    ),
    _case(
        "c20",
        "competing",
        "Replace the contents of Notes.txt in OneDrive with {sandbox}/notes-new.txt.",
        E(["search_files", "file_list"], c("file_update", file_id="item-notes")),
        E(
            ["m365_search", "m365_list", "m365_get", "drive_upload"],
            c("drive_upload", item_id="item-notes"),
            c("drive_upload", if_exists="replace", name="Notes.txt"),
        ),
    ),
    _case(
        "c21",
        "competing",
        "Show the attendees of the Project sync meeting.",
        E(
            ["calendar_list_events", "search_events"],
            c("calendar_get_event", event_id="evt-sync"),
        ),
        E(["m365_search", "m365_list"], c("m365_get", resource="event", id="evt-sync")),
    ),
    _case(
        "c22",
        "competing",
        "Move Priya's contact out of the Work folder into Family.",
        E(
            ["search_contacts", "contact_list"],
            c(
                "contact_add_to_list",
                contact_id="contact-priya",
                list_id="cfolder-family",
            ),
        ),
        E(
            ["m365_search", "m365_list"],
            c(
                "m365_move",
                resource="contact",
                id="contact-priya",
                destination_id="cfolder-family",
            ),
        ),
    ),
    _case(
        "c23",
        "competing",
        "Rename my Receipts mail folder to Bills.",
        E(
            ["emailfolders_list", "emailfolders_get_tree"],
            c(
                "emailfolders_rename",
                folder_id="folder-receipts",
                new_display_name="Bills",
            ),
        ),
        E(
            ["m365_list"],
            c(
                "m365_update",
                resource="email_folder",
                id="folder-receipts",
                email_folder_changes__display_name="Bills",
            ),
        ),
    ),
    _case(
        "c24",
        "competing",
        "Move my Reading mail folder inside the Inbox.",
        E(
            ["emailfolders_list", "emailfolders_get_tree"],
            c(
                "emailfolders_move",
                folder_id="folder-reading",
                destination_folder_id=one_of("inbox", "Inbox"),
            ),
        ),
        E(
            ["m365_list"],
            c(
                "m365_move",
                resource="email_folder",
                id="folder-reading",
                destination_id=one_of("inbox", "Inbox"),
            ),
        ),
    ),
    _case(
        "c25",
        "competing",
        "Show me the email folders inside my Family folder.",
        E(
            ["emailfolders_list", "emailfolders_get_tree"],
            c("emailfolders_list", parent_folder_id="folder-family"),
            c("emailfolders_get_tree"),
        ),
        E(
            ["m365_list"],
            c("m365_list", resource="email_folder", container_id=FAMILY_MAIL),
            c("m365_list", resource="email_folder", recursive=True),
        ),
    ),
    # ------------------------------------------------------------------
    # ambiguous
    # ------------------------------------------------------------------
    _case(
        "a01",
        "ambiguous",
        "Delete the email from Jane.",
        E(["search_emails", "email_list"], c("email_delete", email_id="msg-003")),
        E(
            ["m365_search", "m365_list"],
            c("m365_delete", resource="email", id="msg-003"),
        ),
        side_effect=True,
        clarify_ok=True,
    ),
    _case(
        "a02", "ambiguous", "Move it to the archive.", NO_TOOL, NO_TOOL, clarify_ok=True
    ),
    _case(
        "a03",
        "ambiguous",
        "Schedule a meeting with Jane next week.",
        E(
            [
                "calendar_create_event",
                "calendar_list_events",
                "calendar_check_availability",
            ],
            c("calendar_create_event", attendees=has("jane.smith")),
        ),
        E(
            ["calendar_create_event", "calendar_find_availability", "m365_list"],
            c("calendar_create_event", attendees=PRESENT),
        ),
        side_effect=True,
        clarify_ok=True,
        followups=[
            (
                "Tuesday at 10am for 30 minutes, jane.smith@example.com, "
                "subject 'Catch-up'."
            )
        ],
    ),
    _case(
        "a04",
        "ambiguous",
        "Share the document with Mark.",
        NO_TOOL,
        NO_TOOL,
        clarify_ok=True,
    ),
    _case(
        "a05", "ambiguous", "Reply to that email.", NO_TOOL, NO_TOOL, clarify_ok=True
    ),
    _case(
        "a06", "ambiguous", "Clean up my calendar.", NO_TOOL, NO_TOOL, clarify_ok=True
    ),
    _case(
        "a07",
        "ambiguous",
        "Send Priya the budget.",
        E(
            ["search_files", "search_emails", "search_contacts"],
            c("file_share", file_id="item-budget"),
            c("email_send", to=has("priya")),
            c("email_forward", email_id="msg-006"),
        ),
        E(
            ["m365_search", "m365_list"],
            c("drive_share", item_id="item-budget"),
            c("email_send", to=has("priya")),
            c("email_forward", to=has("priya")),
        ),
        side_effect=True,
        clarify_ok=True,
    ),
    _case(
        "a08",
        "ambiguous",
        "Delete the Smith contact.",
        E(
            ["search_contacts", "contact_list"],
            c("contact_delete", contact_id="contact-anna"),
        ),
        E(
            ["m365_search", "m365_list"],
            c("m365_delete", resource="contact", id="contact-anna"),
        ),
        side_effect=True,
        clarify_ok=True,
    ),
    _case(
        "a09",
        "ambiguous",
        "Put the meeting in the calendar.",
        NO_TOOL,
        NO_TOOL,
        clarify_ok=True,
    ),
    _case(
        "a10", "ambiguous", "Forward the invoice.", NO_TOOL, NO_TOOL, clarify_ok=True
    ),
    # ------------------------------------------------------------------
    # no tool
    # ------------------------------------------------------------------
    _case(
        "n01",
        "no_tool",
        "What's the capital of France?",
        NO_TOOL,
        NO_TOOL,
        no_tool=True,
    ),
    _case(
        "n02",
        "no_tool",
        "Give me a short template for a polite out-of-office message.",
        NO_TOOL,
        NO_TOOL,
        no_tool=True,
    ),
    _case(
        "n03",
        "no_tool",
        "If it's 3pm in Adelaide, what time is it in London?",
        NO_TOOL,
        NO_TOOL,
        no_tool=True,
    ),
    _case(
        "n04",
        "no_tool",
        "What's the difference between CC and BCC?",
        NO_TOOL,
        NO_TOOL,
        no_tool=True,
    ),
    _case(
        "n05",
        "no_tool",
        "Tell me a joke about spreadsheets.",
        NO_TOOL,
        NO_TOOL,
        no_tool=True,
    ),
    _case(
        "n06",
        "no_tool",
        "Write a haiku about Monday mornings.",
        NO_TOOL,
        NO_TOOL,
        no_tool=True,
    ),
    _case(
        "n07",
        "no_tool",
        "In general, how does a recycle bin work in cloud storage?",
        NO_TOOL,
        NO_TOOL,
        no_tool=True,
    ),
    _case(
        "n08",
        "no_tool",
        "Rewrite this more politely: 'Send me the report now.'",
        NO_TOOL,
        NO_TOOL,
        no_tool=True,
    ),
    _case(
        "n09",
        "no_tool",
        "What does 'reply all' do in email?",
        NO_TOOL,
        NO_TOOL,
        no_tool=True,
    ),
    _case(
        "n10",
        "no_tool",
        "How many minutes are in 3.5 hours?",
        NO_TOOL,
        NO_TOOL,
        no_tool=True,
    ),
]


def _assign_splits(cases: list[Case]) -> list[Case]:
    for index, case in enumerate(cases):
        case.split = "heldout" if index % 4 == 3 else "dev"
    return cases


CASES: list[Case] = _assign_splits(_RAW_CASES)

# A fixed 10-case smoke set covering every category.
SMOKE_IDS = ("d01", "d08", "d21", "d28", "i01", "c01", "c07", "c08", "a02", "n01")


def select(split: str) -> list[Case]:
    """Return the cases for ``split``: dev, heldout, all or smoke."""
    if split == "all":
        return list(CASES)
    if split == "smoke":
        return [c for c in CASES if c.id in SMOKE_IDS]
    return [c for c in CASES if c.split == split]
