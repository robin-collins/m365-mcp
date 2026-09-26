#!/usr/bin/env python3
"""Build the unified-tool specification (source of truth for v1.0.0).

Authoring source for every tool in UNIFIED_TOOLS_CONCEPT.md. Running it
writes, under ``docs/unified-tools/``:

- ``tools/<tool>.json``: one complete MCP tool definition per tool (name,
  title, description, annotations, meta, inputSchema, outputSchema) plus the
  Graph calls, server-side validation rules, the legacy tools it replaces,
  and validated examples.
- ``index.json``: tool order, tiers and counts.
- ``legacy_mapping.json``: every one of the 85 legacy tools and its
  replacement.
- ``SCHEMA_REFERENCE.md``: the human-readable reference generated from the
  above.

``tools/<tool>.json`` and ``index.json`` are also written, byte for byte, to
``src/m365_mcp/tool_specs/`` so the server can load them as package data.

Edit this file, never the generated output. ``--check`` exits with status 1
when any generated file (docs or package copy) is stale (used by
``tests/test_unified_tool_specs.py``).

Usage:
    uv run python scripts/build_unified_tool_specs.py [--check]
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs" / "unified-tools"
PKG_DIR = ROOT / "src" / "m365_mcp" / "tool_specs"
SPEC_VERSION = "1.0.0"
SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

Schema = dict[str, Any]

# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------


def obj(
    properties: dict[str, Schema],
    required: list[str] | None = None,
    description: str | None = None,
    defs: dict[str, Schema] | None = None,
    **extra: Any,
) -> Schema:
    """Closed object schema (additionalProperties: false)."""
    schema: Schema = {"type": "object"}
    if description:
        schema["description"] = description
    schema["properties"] = properties
    if required:
        schema["required"] = required
    schema["additionalProperties"] = False
    schema.update(extra)
    if defs:
        schema["$defs"] = defs
    return schema


def string(description: str, **extra: Any) -> Schema:
    return {"type": "string", "description": description, **extra}


def enum(values: list[str], description: str, **extra: Any) -> Schema:
    return {"type": "string", "enum": values, "description": description, **extra}


def boolean(description: str, default: bool | None = None) -> Schema:
    schema: Schema = {"type": "boolean", "description": description}
    if default is not None:
        schema["default"] = default
    return schema


def integer(
    description: str, minimum: int, maximum: int, default: int | None = None
) -> Schema:
    schema: Schema = {
        "type": "integer",
        "description": description,
        "minimum": minimum,
        "maximum": maximum,
    }
    if default is not None:
        schema["default"] = default
    return schema


def array(items: Schema, description: str, **extra: Any) -> Schema:
    return {"type": "array", "description": description, "items": items, **extra}


def nullable(schema: Schema) -> Schema:
    """Output-only: allow null (for fields Graph may omit)."""
    return {"anyOf": [schema, {"type": "null"}]}


def ref(name: str) -> Schema:
    return {"$ref": f"#/$defs/{name}"}


# ---------------------------------------------------------------------------
# Shared input fragments
# ---------------------------------------------------------------------------

ACCOUNT_ID = string(
    "Account ID or email address. Omit when only one account is signed in.",
    minLength=1,
    maxLength=320,
)
EMAIL_ADDRESS: Schema = {
    "type": "string",
    "format": "email",
    "minLength": 3,
    "maxLength": 320,
    "description": "Email address, e.g. jane@example.com.",
}
DATETIME = string(
    "RFC 3339 date-time with offset, e.g. 2026-10-01T09:00:00+09:30.",
    format="date-time",
)
TIME_ZONE = string(
    "IANA time-zone name, e.g. Australia/Adelaide. Defaults to the mailbox time zone.",
    minLength=1,
    maxLength=64,
)
CURSOR = string(
    "next_cursor from the previous page; keep all other arguments the same.",
    minLength=1,
    maxLength=8192,
)
REFRESH = boolean("Bypass the cache and fetch fresh data.", False)
BODY_FORMAT = enum(
    ["text", "html"], "Format of the body text you supply.", default="text"
)
IMPORTANCE = enum(["low", "normal", "high"], "Message importance.")
LOCAL_PATH = string(
    "Local file path inside the server's allowed folders. Hidden and "
    "secret files are refused.",
    minLength=1,
    maxLength=4096,
)
ATTACHMENTS = array(
    LOCAL_PATH,
    "Local files to attach: at most 10, each at most 25 MB.",
    maxItems=10,
    uniqueItems=True,
)
MAIL_FOLDER_REF = string(
    "Mail folder ID, or one of the aliases inbox, sent, drafts, deleted, "
    "junk, archive.",
    minLength=1,
    maxLength=1024,
)


def item_id(description: str) -> Schema:
    return string(description, minLength=1, maxLength=1024)


def recipients(description: str, min_items: int = 0, max_items: int = 500) -> Schema:
    schema = array(EMAIL_ADDRESS, description, maxItems=max_items, uniqueItems=True)
    if min_items:
        schema["minItems"] = min_items
    return schema


def confirm(what: str) -> Schema:
    return boolean(
        f"Must be true to {what}; set only after the user approves.",
        False,
    )


def limit(default: int = 20, maximum: int = 50) -> Schema:
    return integer("Maximum number of items to return.", 1, maximum, default)


CONTACT_FIELDS: dict[str, Schema] = {
    "given_name": string("First name.", minLength=1, maxLength=255),
    "surname": string("Last name.", maxLength=255),
    "display_name": string(
        "Name shown in Outlook. Defaults to given_name + surname.", maxLength=255
    ),
    "emails": array(
        EMAIL_ADDRESS, "Email addresses (at most 3).", maxItems=3, uniqueItems=True
    ),
    "mobile_phone": string("Mobile phone number.", maxLength=64),
    "business_phones": array(
        string("Phone number.", maxLength=64),
        "Business phone numbers.",
        maxItems=5,
    ),
    "home_phones": array(
        string("Phone number.", maxLength=64), "Home phone numbers.", maxItems=5
    ),
    "company_name": string("Company.", maxLength=255),
    "job_title": string("Job title.", maxLength=255),
    "department": string("Department.", maxLength=255),
}

ATTENDEE_INPUT = obj(
    {
        "address": EMAIL_ADDRESS,
        "name": string("Display name.", maxLength=255),
        "type": enum(["required", "optional"], "Attendance type.", default="required"),
    },
    ["address"],
    "Meeting attendee.",
)
SHOW_AS = enum(
    ["free", "tentative", "busy", "oof", "workingElsewhere"],
    "How the time shows in your calendar.",
)

_STRING_LIST = array(
    string("Text to match.", minLength=1, maxLength=255),
    "Any of these strings.",
    minItems=1,
    maxItems=50,
)
_ADDRESS_LIST = array(EMAIL_ADDRESS, "Any of these addresses.", minItems=1, maxItems=50)
RULE_PREDICATES = obj(
    {
        "subject_contains": _STRING_LIST,
        "body_contains": _STRING_LIST,
        "body_or_subject_contains": _STRING_LIST,
        "sender_contains": _STRING_LIST,
        "recipient_contains": _STRING_LIST,
        "header_contains": _STRING_LIST,
        "categories": _STRING_LIST,
        "from_addresses": _ADDRESS_LIST,
        "sent_to_addresses": _ADDRESS_LIST,
        "has_attachments": boolean("Message has attachments."),
        "importance": enum(["low", "normal", "high"], "Message importance."),
        "sensitivity": enum(
            ["normal", "personal", "private", "confidential"],
            "Message sensitivity.",
        ),
        "message_action_flag": enum(
            [
                "any",
                "call",
                "doNotForward",
                "followUp",
                "fyi",
                "forward",
                "noResponseNecessary",
                "read",
                "reply",
                "replyToAll",
                "review",
            ],
            "Flag-for-action value on the message.",
        ),
        "within_size_range": obj(
            {
                "minimum_kb": integer("Minimum size in KB.", 0, 2147483647),
                "maximum_kb": integer("Maximum size in KB.", 0, 2147483647),
            },
            None,
            "Message size range in kilobytes.",
            minProperties=1,
        ),
        "is_approval_request": boolean("Message is an approval request."),
        "is_automatic_forward": boolean("Message was auto-forwarded."),
        "is_automatic_reply": boolean("Message is an automatic reply."),
        "is_encrypted": boolean("Message is encrypted."),
        "is_meeting_request": boolean("Message is a meeting request."),
        "is_meeting_response": boolean("Message is a meeting response."),
        "is_non_delivery_report": boolean("Message is a non-delivery report."),
        "is_permission_controlled": boolean("Message is rights-protected."),
        "is_read_receipt": boolean("Message is a read receipt."),
        "is_signed": boolean("Message is S/MIME signed."),
        "is_voicemail": boolean("Message is a voicemail."),
        "not_sent_to_me": boolean("You are not a recipient."),
        "sent_cc_me": boolean("You are in Cc."),
        "sent_only_to_me": boolean("You are the only recipient."),
        "sent_to_me": boolean("You are in To."),
        "sent_to_or_cc_me": boolean("You are in To or Cc."),
    },
    None,
    "Rule conditions (all must match). Names map 1:1 to Graph "
    "messageRulePredicates in camelCase.",
    minProperties=1,
)
RULE_ACTIONS = obj(
    {
        "move_to_folder": item_id("Mail folder ID to move the message to."),
        "copy_to_folder": item_id("Mail folder ID to copy the message to."),
        "assign_categories": _STRING_LIST,
        "mark_as_read": boolean("Mark the message as read."),
        "mark_importance": enum(["low", "normal", "high"], "Set importance."),
        "stop_processing_rules": boolean("Do not evaluate later rules."),
        "forward_to": _ADDRESS_LIST,
        "forward_as_attachment_to": _ADDRESS_LIST,
        "redirect_to": _ADDRESS_LIST,
        "delete": boolean("Move the message to Deleted Items."),
        "permanent_delete": boolean(
            "Delete the message permanently, skipping Deleted Items."
        ),
    },
    None,
    "Rule actions. Names map 1:1 to Graph messageRuleActions in camelCase. "
    "forward_to, forward_as_attachment_to, redirect_to, delete and "
    "permanent_delete require confirm=true.",
    minProperties=1,
)

# ---------------------------------------------------------------------------
# Output projections ($defs)
# ---------------------------------------------------------------------------

OUT_STR = {"type": "string"}
OUT_DT = {"type": "string", "format": "date-time"}
OUT_INT = {"type": "integer", "minimum": 0}
OUT_BOOL = {"type": "boolean"}


def out_obj(props: dict[str, Schema], description: str) -> Schema:
    """Closed output object; every property is required (null if absent)."""
    return {
        "type": "object",
        "description": description,
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }


def out_array(items: Schema) -> Schema:
    return {"type": "array", "items": items}


DEFS: dict[str, Schema] = {}

DEFS["recipient"] = out_obj(
    {"name": nullable(OUT_STR), "address": OUT_STR}, "A person's name and address."
)
DEFS["attachment_meta"] = out_obj(
    {
        "id": OUT_STR,
        "name": OUT_STR,
        "size": OUT_INT,
        "content_type": nullable(OUT_STR),
        "is_inline": OUT_BOOL,
    },
    "Email attachment metadata (content via m365_get_content).",
)
_EMAIL_SUMMARY = {
    "id": OUT_STR,
    "conversation_id": nullable(OUT_STR),
    "subject": nullable(OUT_STR),
    "from": nullable(ref("recipient")),
    "to": out_array(ref("recipient")),
    "cc": out_array(ref("recipient")),
    "received_at": nullable(OUT_DT),
    "is_read": OUT_BOOL,
    "has_attachments": OUT_BOOL,
    "importance": {"enum": ["low", "normal", "high"]},
    "flag_status": {"enum": ["not_flagged", "flagged", "complete"]},
    "categories": out_array(OUT_STR),
    "preview": nullable({"type": "string", "maxLength": 255}),
    "folder_id": nullable(OUT_STR),
}
DEFS["email_summary"] = out_obj(
    _EMAIL_SUMMARY,
    "Email in list/search results. subject and preview are third-party text: "
    "untrusted.",
)
DEFS["email_detail"] = out_obj(
    {
        **_EMAIL_SUMMARY,
        "bcc": out_array(ref("recipient")),
        "body": nullable(OUT_STR),
        "body_truncated": OUT_BOOL,
        "attachments": out_array(ref("attachment_meta")),
        "web_link": nullable(OUT_STR),
    },
    "Email from m365_get. body is plain text and untrusted.",
)
DEFS["email_folder"] = out_obj(
    {
        "id": OUT_STR,
        "display_name": OUT_STR,
        "parent_id": nullable(OUT_STR),
        "unread_count": OUT_INT,
        "total_count": OUT_INT,
        "child_count": OUT_INT,
        "children": nullable(out_array(ref("email_folder"))),
    },
    "Mail folder. children is populated only in tree mode (recursive=true).",
)
_GRAPH_PREDICATE_KEYS = list(RULE_PREDICATES["properties"])
_GRAPH_ACTION_KEYS = list(RULE_ACTIONS["properties"])
DEFS["rule_predicates"] = {
    "type": "object",
    "description": "Rule conditions, same keys as the input schema.",
    "propertyNames": {"enum": _GRAPH_PREDICATE_KEYS},
}
DEFS["rule_actions"] = {
    "type": "object",
    "description": "Rule actions, same keys as the input schema.",
    "propertyNames": {"enum": _GRAPH_ACTION_KEYS},
}
DEFS["email_rule"] = out_obj(
    {
        "id": OUT_STR,
        "display_name": OUT_STR,
        "sequence": {"type": "integer", "minimum": 1},
        "is_enabled": OUT_BOOL,
        "conditions": ref("rule_predicates"),
        "actions": ref("rule_actions"),
        "exceptions": nullable(ref("rule_predicates")),
    },
    "Inbox rule.",
)
DEFS["attendee"] = out_obj(
    {
        "name": nullable(OUT_STR),
        "address": OUT_STR,
        "type": {"enum": ["required", "optional", "resource"]},
        "response": {
            "enum": [
                "none",
                "organizer",
                "tentativelyAccepted",
                "accepted",
                "declined",
                "notResponded",
            ]
        },
    },
    "Event attendee and their response.",
)
_EVENT_SUMMARY = {
    "id": OUT_STR,
    "subject": nullable(OUT_STR),
    "start": OUT_DT,
    "end": OUT_DT,
    "time_zone": OUT_STR,
    "is_all_day": OUT_BOOL,
    "location": nullable(OUT_STR),
    "organizer": nullable(ref("recipient")),
    "is_organizer": OUT_BOOL,
    "my_response": {
        "enum": [
            "none",
            "organizer",
            "tentativelyAccepted",
            "accepted",
            "declined",
            "notResponded",
        ]
    },
    "show_as": {
        "enum": ["free", "tentative", "busy", "oof", "workingElsewhere", "unknown"]
    },
    "attendee_count": OUT_INT,
    "calendar_id": nullable(OUT_STR),
    "preview": nullable({"type": "string", "maxLength": 255}),
}
DEFS["event_summary"] = out_obj(
    _EVENT_SUMMARY,
    "Event in list/search results. subject, location and preview are untrusted.",
)
DEFS["event_detail"] = out_obj(
    {
        **_EVENT_SUMMARY,
        "body": nullable(OUT_STR),
        "body_truncated": OUT_BOOL,
        "attendees": out_array(ref("attendee")),
        "web_link": nullable(OUT_STR),
        "recurrence": nullable(OUT_STR),
    },
    "Event from m365_get. recurrence is a read-only human summary.",
)
DEFS["calendar"] = out_obj(
    {
        "id": OUT_STR,
        "name": OUT_STR,
        "is_default": OUT_BOOL,
        "can_edit": OUT_BOOL,
        "color": nullable(OUT_STR),
    },
    "Calendar.",
)
DEFS["contact"] = out_obj(
    {
        "id": OUT_STR,
        "display_name": nullable(OUT_STR),
        "given_name": nullable(OUT_STR),
        "surname": nullable(OUT_STR),
        "emails": out_array(OUT_STR),
        "mobile_phone": nullable(OUT_STR),
        "business_phones": out_array(OUT_STR),
        "home_phones": out_array(OUT_STR),
        "company_name": nullable(OUT_STR),
        "job_title": nullable(OUT_STR),
        "department": nullable(OUT_STR),
        "folder_id": nullable(OUT_STR),
    },
    "Contact.",
)
DEFS["contact_folder"] = out_obj(
    {"id": OUT_STR, "display_name": OUT_STR, "parent_id": nullable(OUT_STR)},
    "Contact folder.",
)
DEFS["drive_item"] = out_obj(
    {
        "id": OUT_STR,
        "name": OUT_STR,
        "item_type": {"enum": ["file", "folder"]},
        "path": nullable(OUT_STR),
        "parent_id": nullable(OUT_STR),
        "size": OUT_INT,
        "modified_at": nullable(OUT_DT),
        "created_at": nullable(OUT_DT),
        "mime_type": nullable(OUT_STR),
        "child_count": nullable(OUT_INT),
        "web_url": nullable(OUT_STR),
        "shared": OUT_BOOL,
        "children": nullable(out_array(ref("drive_item"))),
    },
    "OneDrive file or folder. children is populated only in tree mode.",
)
DEFS["operation"] = out_obj(
    {
        "operation_id": OUT_STR,
        "status": {"enum": ["in_progress", "completed", "failed"]},
        "percent_complete": nullable({"type": "number", "minimum": 0, "maximum": 100}),
        "resource_id": nullable(OUT_STR),
        "error": nullable(OUT_STR),
    },
    "Status of a background OneDrive copy.",
)

SUMMARY = {
    "type": "string",
    "description": (
        "One-line human summary. The tool's text content is this result "
        "serialized as JSON (summary included), so a client that ignores "
        "structuredContent still sees every field."
    ),
}
NEXT_CURSOR = nullable(OUT_STR)


def collect_defs(schema: Schema) -> dict[str, Schema]:
    """Return every $def referenced (transitively) by a schema."""
    needed: dict[str, Schema] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            target = node.get("$ref")
            if isinstance(target, str) and target.startswith("#/$defs/"):
                name = target.rsplit("/", 1)[1]
                if name not in needed:
                    needed[name] = DEFS[name]
                    walk(DEFS[name])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    return {name: needed[name] for name in sorted(needed)}


def output(props: dict[str, Schema], description: str) -> Schema:
    schema = out_obj({**props, "summary": SUMMARY}, description)
    defs = collect_defs(schema)
    if defs:
        schema["$defs"] = defs
    return schema


def any_of(*names: str) -> Schema:
    return {"anyOf": [ref(name) for name in names]}


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = []


def tool(
    *,
    name: str,
    title: str,
    tier: str,
    category: str,
    safety: str,
    confirm_mode: str,
    description: str,
    input_schema: Schema,
    output_schema: Schema,
    read_only: bool,
    destructive: bool,
    idempotent: bool,
    graph: list[str],
    rules: list[tuple[str, str]],
    replaces: list[str],
    examples: list[dict[str, Any]],
    confirm_rule: str | None = None,
) -> None:
    TOOLS.append(
        {
            "name": name,
            "title": title,
            "description": description,
            "annotations": {
                "title": title,
                "readOnlyHint": read_only,
                "destructiveHint": destructive,
                "idempotentHint": idempotent,
                "openWorldHint": True,
            },
            "meta": {
                "category": category,
                "tier": tier,
                "safety_level": safety,
                "confirm": confirm_mode,
                "confirm_rule": confirm_rule,
            },
            "inputSchema": {"$schema": SCHEMA_DIALECT, **input_schema},
            "outputSchema": {"$schema": SCHEMA_DIALECT, **output_schema},
            "graph_calls": graph,
            "validation_rules": [{"rule": r, "error": e} for r, e in rules],
            "replaces": replaces,
            "examples": examples,
        }
    )


LIST_RESOURCES = [
    "email",
    "email_folder",
    "email_rule",
    "event",
    "calendar",
    "contact",
    "contact_folder",
    "drive_item",
]

# ---- m365_list -------------------------------------------------------------
tool(
    name="m365_list",
    title="List Items",
    tier="core",
    category="m365",
    safety="safe",
    confirm_mode="never",
    read_only=True,
    destructive=False,
    idempotent=True,
    description=(
        "Browse items of one type in a known place: emails in a mail folder, "
        "events in a time window, calendars, contacts, contact folders, mail "
        "folders, inbox rules, or files in a OneDrive folder (optionally as a "
        "tree). Use this when you know where to look. Use m365_search to find "
        "items by text, and m365_get when you already have an ID. Returns "
        "compact items plus next_cursor for more."
    ),
    input_schema=obj(
        {
            "resource": enum(LIST_RESOURCES, "Type of item to list."),
            "account_id": ACCOUNT_ID,
            "container_id": item_id(
                "Where to list. email: mail folder ID or alias (default inbox). "
                "email_folder: parent folder (default: top level). event: "
                "calendar ID (default: your default calendar). contact: contact "
                "folder ID (default: all contacts). drive_item: parent folder ID "
                "(default: OneDrive root). Not used for calendar, contact_folder "
                "and email_rule."
            ),
            "path": string(
                "drive_item only: OneDrive folder path instead of container_id, "
                "e.g. /Documents/Tax.",
                minLength=1,
                maxLength=2048,
            ),
            "email_filter": obj(
                {
                    "unread": boolean("Only unread (true) or only read (false)."),
                    "from": EMAIL_ADDRESS,
                    "received_after": DATETIME,
                    "received_before": DATETIME,
                    "has_attachments": boolean("Only messages with attachments."),
                    "importance": IMPORTANCE,
                    "flagged": boolean("Only flagged messages."),
                    "category": string(
                        "Only messages with this category.", minLength=1, maxLength=255
                    ),
                },
                None,
                "email only: filters applied by Microsoft 365 (all must match).",
                minProperties=1,
            ),
            "start": {
                **DATETIME,
                "description": "event only: window start (default now). "
                "RFC 3339 with offset.",
            },
            "end": {
                **DATETIME,
                "description": "event only: window end (default start + 7 days; "
                "at most 366 days after start).",
            },
            "item_type": enum(
                ["file", "folder", "all"],
                "drive_item only: which kinds of item to return.",
                default="all",
            ),
            "recursive": boolean(
                "email_folder and drive_item only: return a nested tree of "
                "folders instead of one level.",
                False,
            ),
            "max_depth": integer("Tree depth when recursive=true.", 1, 10, 3),
            "include_hidden": boolean(
                "email_folder only: include hidden folders.", False
            ),
            "limit": limit(),
            "cursor": CURSOR,
            "refresh": REFRESH,
        },
        ["resource"],
    ),
    output_schema=output(
        {
            "resource": {"enum": LIST_RESOURCES},
            "items": out_array(
                any_of(
                    "email_summary",
                    "email_folder",
                    "email_rule",
                    "event_summary",
                    "calendar",
                    "contact",
                    "contact_folder",
                    "drive_item",
                )
            ),
            "next_cursor": NEXT_CURSOR,
            "has_more": OUT_BOOL,
        },
        "Page of items of the requested resource type.",
    ),
    graph=[
        (
            "email: GET /me/mailFolders/{id}/messages ($filter from email_filter, "
            "$orderby receivedDateTime desc, $select projection)"
        ),
        (
            "email_folder: GET /me/mailFolders[/{id}/childFolders] (recursive: "
            "walk childFolders to max_depth)"
        ),
        "email_rule: GET /me/mailFolders/inbox/messageRules",
        "event: GET /me/calendars/{id}/calendarView?startDateTime&endDateTime",
        "calendar: GET /me/calendars",
        "contact: GET /me/contacts or /me/contactFolders/{id}/contacts",
        "contact_folder: GET /me/contactFolders",
        (
            "drive_item: GET /me/drive/items/{id}/children or "
            "/me/drive/root:{path}:/children (recursive: walk folders)"
        ),
    ],
    rules=[
        (
            "Parameters that do not apply to the chosen resource are rejected.",
            (
                "Invalid email_filter: only valid with resource='email'. Expected: "
                "remove email_filter or use resource='email'"
            ),
        ),
        (
            "container_id and path are mutually exclusive.",
            (
                "Invalid path: cannot be combined with container_id. Expected: one "
                "of container_id or path"
            ),
        ),
        (
            "event window: end must be after start and at most 366 days later.",
            (
                "Invalid end: must be after start and within 366 days. Expected: a "
                "later RFC 3339 date-time"
            ),
        ),
        (
            "received_before must be after received_after.",
            "Invalid received_before: must be after received_after",
        ),
        (
            (
                "cursor must come from the same request (resource, account and "
                "filters) and be less than 24 hours old."
            ),
            (
                "Invalid cursor: it does not match this request. Expected: repeat "
                "the call without cursor"
            ),
        ),
        (
            "Unknown mail folder aliases are rejected.",
            (
                "Invalid container_id 'Inbx': unknown folder alias. Expected: a "
                "folder ID or one of inbox, sent, drafts, deleted, junk, archive"
            ),
        ),
    ],
    replaces=[
        "email_list",
        "emailfolders_list",
        "emailfolders_get_tree",
        "emailrules_list",
        "calendar_list_events",
        "calendar_list_calendars",
        "contact_list",
        "file_list",
        "folder_list",
        "folder_get_tree",
    ],
    examples=[
        {
            "title": "Unread emails from one sender this month",
            "input": {
                "resource": "email",
                "email_filter": {
                    "unread": True,
                    "from": "billing@example.com",
                    "received_after": "2026-09-01T00:00:00+09:30",
                },
                "limit": 1,
            },
            "output": {
                "resource": "email",
                "items": [
                    {
                        "id": "AQMkADAwATM3ZmYAZS1k",
                        "conversation_id": "AQQkADAwATM3ZmYAZS1",
                        "subject": "Your September invoice",
                        "from": {
                            "name": "Example Billing",
                            "address": "billing@example.com",
                        },
                        "to": [{"name": "Robin", "address": "robin@example.com"}],
                        "cc": [],
                        "received_at": "2026-09-20T08:15:00+09:30",
                        "is_read": False,
                        "has_attachments": True,
                        "importance": "normal",
                        "flag_status": "not_flagged",
                        "categories": [],
                        "preview": "Your invoice for September is attached.",
                        "folder_id": "AQMkADAwATM3ZmYAZS1kAC4AAAM",
                    }
                ],
                "next_cursor": "eyJ2IjoxLCJyIjoiZW1haWwifQ",
                "has_more": True,
                "summary": "Returned 1 email from inbox; more available (pass next_cursor).",
            },
        }
    ],
)

# ---- m365_get --------------------------------------------------------------
GET_RESOURCES = LIST_RESOURCES + ["operation"]
tool(
    name="m365_get",
    title="Get Item",
    tier="core",
    category="m365",
    safety="safe",
    confirm_mode="never",
    read_only=True,
    destructive=False,
    idempotent=True,
    description=(
        "Read one item whose ID you already have: an email with its body, an "
        "event with attendees, a contact, a mail or contact folder, an inbox "
        "rule, a calendar, a OneDrive item's details, or the status of a copy "
        "started with drive_copy (resource='operation'). Use m365_list or "
        "m365_search to find IDs. Use m365_get_content to download files or "
        "attachments. Returns the item."
    ),
    input_schema=obj(
        {
            "resource": enum(GET_RESOURCES, "Type of item."),
            "account_id": ACCOUNT_ID,
            "id": item_id(
                "Item ID from a previous result (for operation: the "
                "operation_id). Aliases are accepted for email_folder, calendar "
                "(default) and drive_item (root)."
            ),
            "path": string(
                "drive_item only: OneDrive path instead of id.",
                minLength=1,
                maxLength=2048,
            ),
            "include_body": boolean("email and event: include the body text.", True),
            "body_max_chars": integer(
                "email and event: truncate the body after this many characters.",
                500,
                100000,
                20000,
            ),
            "refresh": REFRESH,
        },
        ["resource"],
    ),
    output_schema=output(
        {
            "resource": {"enum": GET_RESOURCES},
            "item": any_of(
                "email_detail",
                "email_folder",
                "email_rule",
                "event_detail",
                "calendar",
                "contact",
                "contact_folder",
                "drive_item",
                "operation",
            ),
        },
        "The requested item.",
    ),
    graph=[
        (
            "email: GET /me/messages/{id}?$expand=attachments($select=id,name,size,"
            'contentType,isInline) with Prefer: outlook.body-content-type="text"'
        ),
        "email_folder: GET /me/mailFolders/{id}",
        "email_rule: GET /me/mailFolders/inbox/messageRules/{id}",
        "event: GET /me/events/{id}",
        "calendar: GET /me/calendars/{id} or /me/calendar",
        "contact: GET /me/contacts/{id}",
        "contact_folder: GET /me/contactFolders/{id}",
        "drive_item: GET /me/drive/items/{id} or /me/drive/root:{path}",
        "operation: GET {stored monitor URL} (no Authorization header)",
    ],
    rules=[
        (
            "Exactly one of id or path (path only for drive_item).",
            "Invalid id: required unless resource='drive_item' with path",
        ),
        (
            "Unknown or expired operation IDs are rejected.",
            (
                "Invalid id: unknown operation. Expected: an operation_id returned "
                "by drive_copy in the last 24 hours"
            ),
        ),
    ],
    replaces=[
        "email_get",
        "emailfolders_get",
        "emailrules_get",
        "calendar_get_event",
        "contact_get",
        "folder_get",
        "file_get (details)",
    ],
    examples=[
        {
            "title": "Check a copy operation",
            "input": {"resource": "operation", "id": "op_7f3c2a"},
            "output": {
                "resource": "operation",
                "item": {
                    "operation_id": "op_7f3c2a",
                    "status": "completed",
                    "percent_complete": 100,
                    "resource_id": "01ABCDEF2345",
                    "error": None,
                },
                "summary": "Copy completed; new item id 01ABCDEF2345.",
            },
        }
    ],
)

# ---- m365_search -----------------------------------------------------------
SEARCH_RESOURCES = ["email", "event", "contact", "drive_item"]
tool(
    name="m365_search",
    title="Search",
    tier="core",
    category="m365",
    safety="safe",
    confirm_mode="never",
    read_only=True,
    destructive=False,
    idempotent=True,
    description=(
        "Find emails, events, contacts or OneDrive files by free text when "
        "you do not know where they are. Search one type or several at once. "
        "Do not use it to browse a folder (m365_list) or open a known ID "
        "(m365_get). Returns matching items labelled by resource, newest "
        "first, plus next_cursor."
    ),
    input_schema=obj(
        {
            "query": string(
                "Words to search for. Plain text; the server handles quoting.",
                minLength=1,
                maxLength=256,
            ),
            "resources": array(
                enum(SEARCH_RESOURCES, "Resource type."),
                "Which item types to search. Default: all four.",
                minItems=1,
                maxItems=4,
                uniqueItems=True,
            ),
            "account_id": ACCOUNT_ID,
            "email_folder_id": MAIL_FOLDER_REF,
            "event_start": {
                **DATETIME,
                "description": "Event search window start (default: 90 days ago).",
            },
            "event_end": {
                **DATETIME,
                "description": "Event search window end (default: 365 days ahead).",
            },
            "limit": limit(),
            "cursor": CURSOR,
        },
        ["query"],
    ),
    output_schema=output(
        {
            "query": OUT_STR,
            "items": out_array(
                out_obj(
                    {
                        "resource": {"enum": SEARCH_RESOURCES},
                        "item": any_of(
                            "email_summary", "event_summary", "contact", "drive_item"
                        ),
                    },
                    "One match and its resource type.",
                )
            ),
            "next_cursor": NEXT_CURSOR,
            "has_more": OUT_BOOL,
        },
        "Matches across the requested resource types.",
    ),
    graph=[
        (
            'email: GET /me/messages?$search="{query}" (or '
            "/me/mailFolders/{id}/messages) — whole mailbox, paged"
        ),
        (
            "event: GET /me/calendarView over the window, matched server-side on "
            "subject, location, preview and organiser"
        ),
        (
            "contact: GET /me/contacts?$filter=startswith(displayName,'q') or "
            "startswith(givenName,'q') or startswith(surname,'q'), plus email match"
        ),
        "drive_item: GET /me/drive/root/search(q='{query}')",
    ],
    rules=[
        (
            (
                "email_folder_id only when resources includes email; event_start / "
                "event_end only when resources includes event."
            ),
            "Invalid email_folder_id: only valid when resources includes 'email'",
        ),
        (
            "event_end after event_start, span at most 731 days.",
            "Invalid event_end: must be after event_start and within 731 days",
        ),
        (
            "The query is escaped for OData string literals and $search quoting.",
            "(no error; injection-safe by construction)",
        ),
    ],
    replaces=[
        "search_emails",
        "search_events",
        "search_contacts",
        "search_files",
        "search_unified",
    ],
    examples=[
        {
            "title": "Search mail and files together",
            "input": {
                "query": "tax return",
                "resources": ["email", "drive_item"],
                "limit": 1,
            },
            "output": {
                "query": "tax return",
                "items": [
                    {
                        "resource": "drive_item",
                        "item": {
                            "id": "01ABCDEF2345",
                            "name": "Tax return 2026.pdf",
                            "item_type": "file",
                            "path": "/Documents/Tax",
                            "parent_id": "01ABCDEF0001",
                            "size": 482113,
                            "modified_at": "2026-08-30T10:00:00+09:30",
                            "created_at": "2026-08-30T10:00:00+09:30",
                            "mime_type": "application/pdf",
                            "child_count": None,
                            "web_url": "https://onedrive.live.com/?id=01ABCDEF2345",
                            "shared": False,
                            "children": None,
                        },
                    }
                ],
                "next_cursor": "eyJ2IjoxLCJyIjoic2VhcmNoIn0",
                "has_more": True,
                "summary": "Returned 1 match (drive_item: 1); more available.",
            },
        }
    ],
)

# ---- m365_get_content ------------------------------------------------------
tool(
    name="m365_get_content",
    title="Get Content",
    tier="core",
    category="m365",
    safety="moderate",
    confirm_mode="never",
    read_only=False,
    destructive=False,
    idempotent=True,
    description=(
        "Get the content of an item rather than its details: save a OneDrive "
        "file or an email attachment to a local file (mode='download'), get a "
        "temporary download link for a OneDrive file (mode='download_url'), "
        "or export a contact as a vCard (mode='vcard'). Writes to the local "
        "disk only inside the allowed folders. Use m365_get for item details."
    ),
    input_schema=obj(
        {
            "resource": enum(["drive_item", "email", "contact"], "Type of item."),
            "account_id": ACCOUNT_ID,
            "id": item_id("OneDrive item ID, email ID or contact ID."),
            "mode": enum(
                ["download", "download_url", "vcard"],
                "download: drive_item file or email attachment to save_path. "
                "download_url: drive_item file only. vcard: contact only.",
            ),
            "attachment_id": item_id(
                "email + download only: attachment ID from m365_get(resource='email')."
            ),
            "save_path": LOCAL_PATH,
            "overwrite": boolean("Replace save_path if it already exists.", False),
        },
        ["resource", "id", "mode"],
    ),
    output_schema=output(
        {
            "resource": {"enum": ["drive_item", "email", "contact"]},
            "id": OUT_STR,
            "mode": {"enum": ["download", "download_url", "vcard"]},
            "saved_path": nullable(OUT_STR),
            "size": nullable(OUT_INT),
            "mime_type": nullable(OUT_STR),
            "download_url": nullable(OUT_STR),
            "vcard": nullable(OUT_STR),
        },
        "Content result; fields that do not apply to the mode are null. "
        "download_url is a short-lived pre-authenticated link: treat it as a "
        "secret.",
    ),
    graph=[
        (
            "drive_item download: GET /me/drive/items/{id} then stream "
            "@microsoft.graph.downloadUrl to save_path (≤ MCP_FILE_DOWNLOAD_MAX_MB)"
        ),
        (
            "drive_item download_url: GET /me/drive/items/{id}?$select=id,name,size,"
            "@microsoft.graph.downloadUrl"
        ),
        (
            "email download: GET /me/messages/{id}/attachments/{attachment_id} "
            "(fileAttachment, ≤ 25 MB)"
        ),
        "contact vcard: GET /me/contacts/{id}, rendered as vCard 3.0",
    ],
    rules=[
        (
            (
                "mode must suit the resource (download: drive_item or email; "
                "download_url: drive_item; vcard: contact)."
            ),
            (
                "Invalid mode 'vcard': not valid for resource 'drive_item'. "
                "Expected: download or download_url"
            ),
        ),
        (
            (
                "save_path is required for download and must be inside the allowed "
                "roots and not deny-listed."
            ),
            (
                "Invalid save_path: outside allowed folders. Expected: a path under "
                "the working directory, temp directory or MCP_FILE_ALLOWED_ROOTS"
            ),
        ),
        (
            "attachment_id is required for email download.",
            "Invalid attachment_id: required for resource='email'",
        ),
        (
            "Existing files are not replaced unless overwrite=true.",
            "Invalid save_path: file exists. Expected: overwrite=true or another path",
        ),
        (
            "Folders cannot be downloaded.",
            "Invalid id: item is a folder. Expected: a file",
        ),
    ],
    replaces=[
        "file_get (download)",
        "file_download_url",
        "email_get_attachment",
        "contact_export",
    ],
    examples=[
        {
            "title": "Export a contact",
            "input": {
                "resource": "contact",
                "id": "AQMkADAwATM3ZmYAZS1kCON",
                "mode": "vcard",
            },
            "output": {
                "resource": "contact",
                "id": "AQMkADAwATM3ZmYAZS1kCON",
                "mode": "vcard",
                "saved_path": None,
                "size": None,
                "mime_type": "text/vcard",
                "download_url": None,
                "vcard": "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Jane Citizen\r\nEND:VCARD",
                "summary": "Exported Jane Citizen as vCard.",
            },
        }
    ],
)

# ---- m365_create -----------------------------------------------------------
CREATE_RESOURCES = [
    "email_folder",
    "calendar",
    "contact",
    "contact_folder",
    "drive_item",
]
tool(
    name="m365_create",
    title="Create Item",
    tier="core",
    category="m365",
    safety="moderate",
    confirm_mode="never",
    read_only=False,
    destructive=False,
    idempotent=False,
    description=(
        "Create a mail folder, calendar, contact, contact folder or OneDrive "
        "folder. Supply the sub-object that matches resource. Not for emails "
        "(email_create_draft), events (calendar_create_event), inbox rules "
        "(email_rule_manage) or uploading files (drive_upload). Returns the "
        "created item."
    ),
    input_schema=obj(
        {
            "resource": enum(CREATE_RESOURCES, "Type of item to create."),
            "account_id": ACCOUNT_ID,
            "email_folder": obj(
                {
                    "display_name": string("Folder name.", minLength=1, maxLength=255),
                    "parent_id": item_id(
                        "Parent mail folder ID or alias (default: top level)."
                    ),
                },
                ["display_name"],
                "Required when resource='email_folder'.",
            ),
            "calendar": obj(
                {"name": string("Calendar name.", minLength=1, maxLength=255)},
                ["name"],
                "Required when resource='calendar'.",
            ),
            "contact": obj(
                {
                    **CONTACT_FIELDS,
                    "folder_id": item_id(
                        "Contact folder ID (default: your main Contacts)."
                    ),
                },
                ["given_name"],
                "Required when resource='contact'.",
            ),
            "contact_folder": obj(
                {
                    "display_name": string("Folder name.", minLength=1, maxLength=255),
                    "parent_id": item_id(
                        "Parent contact folder ID (default: top level)."
                    ),
                },
                ["display_name"],
                "Required when resource='contact_folder'.",
            ),
            "drive_folder": obj(
                {
                    "name": string("Folder name.", minLength=1, maxLength=255),
                    "parent_id": item_id("Parent folder ID (default: OneDrive root)."),
                    "parent_path": string(
                        "Parent folder path instead of parent_id, e.g. /Documents.",
                        minLength=1,
                        maxLength=2048,
                    ),
                    "if_exists": enum(
                        ["fail", "rename"],
                        "What to do if a folder with this name exists.",
                        default="fail",
                    ),
                },
                ["name"],
                "Required when resource='drive_item' (creates a folder).",
            ),
        },
        ["resource"],
    ),
    output_schema=output(
        {
            "resource": {"enum": CREATE_RESOURCES},
            "item": any_of(
                "email_folder", "calendar", "contact", "contact_folder", "drive_item"
            ),
        },
        "The created item.",
    ),
    graph=[
        "email_folder: POST /me/mailFolders or /me/mailFolders/{parent}/childFolders",
        "calendar: POST /me/calendars",
        "contact: POST /me/contacts or /me/contactFolders/{id}/contacts",
        (
            "contact_folder: POST /me/contactFolders or "
            "/me/contactFolders/{parent}/childFolders"
        ),
        (
            "drive_item: POST /me/drive/items/{parent}/children with folder facet "
            "and @microsoft.graph.conflictBehavior"
        ),
    ],
    rules=[
        (
            "Exactly one sub-object, and it must match resource.",
            (
                "Invalid contact: resource is 'calendar'. Expected: supply only the "
                "'calendar' object"
            ),
        ),
        (
            "drive_folder.parent_id and parent_path are mutually exclusive.",
            "Invalid parent_path: cannot be combined with parent_id",
        ),
        (
            "Name conflicts fail unless if_exists='rename'.",
            (
                "A folder named 'Tax' already exists there. Expected: another name "
                "or if_exists='rename'"
            ),
        ),
    ],
    replaces=[
        "emailfolders_create",
        "calendar_create_calendar",
        "contact_create",
        "contact_create_list",
        "folder_create",
    ],
    examples=[
        {
            "title": "Create a contact in a folder",
            "input": {
                "resource": "contact",
                "contact": {
                    "given_name": "Jane",
                    "surname": "Citizen",
                    "emails": ["jane@example.com"],
                    "mobile_phone": "+61 400 000 000",
                    "folder_id": "AQMkADAwATM3ZmYAZS1kCFLD",
                },
            },
            "output": {
                "resource": "contact",
                "item": {
                    "id": "AQMkADAwATM3ZmYAZS1kCON",
                    "display_name": "Jane Citizen",
                    "given_name": "Jane",
                    "surname": "Citizen",
                    "emails": ["jane@example.com"],
                    "mobile_phone": "+61 400 000 000",
                    "business_phones": [],
                    "home_phones": [],
                    "company_name": None,
                    "job_title": None,
                    "department": None,
                    "folder_id": "AQMkADAwATM3ZmYAZS1kCFLD",
                },
                "summary": "Created contact Jane Citizen.",
            },
        }
    ],
)

# ---- m365_update -----------------------------------------------------------
UPDATE_RESOURCES = ["email", "email_folder", "contact", "drive_item"]
_CATEGORY_LIST = array(
    string("Category name.", minLength=1, maxLength=255),
    "Category names.",
    minItems=1,
    maxItems=25,
    uniqueItems=True,
)
tool(
    name="m365_update",
    title="Update Item",
    tier="core",
    category="m365",
    safety="moderate",
    confirm_mode="never",
    read_only=False,
    destructive=False,
    idempotent=True,
    description=(
        "Change properties of an existing email, mail folder, contact or "
        "OneDrive item: mark read or unread, flag, set importance or "
        "categories, Focused/Other, rename folders and files, or edit contact "
        "details. Supply the *_changes object that matches resource. Not for "
        "events (calendar_update_event), inbox rules (email_rule_manage) or "
        "file contents (drive_upload). Returns the changed field names."
    ),
    input_schema=obj(
        {
            "resource": enum(UPDATE_RESOURCES, "Type of item."),
            "account_id": ACCOUNT_ID,
            "id": item_id("Item ID."),
            "email_changes": obj(
                {
                    "is_read": boolean("Mark read (true) or unread (false)."),
                    "flag": obj(
                        {
                            "status": enum(
                                ["not_flagged", "flagged", "complete"], "Flag state."
                            ),
                            "start_at": DATETIME,
                            "due_at": DATETIME,
                        },
                        ["status"],
                        "Follow-up flag.",
                    ),
                    "importance": IMPORTANCE,
                    "categories_add": _CATEGORY_LIST,
                    "categories_remove": _CATEGORY_LIST,
                    "categories_set": {
                        **_CATEGORY_LIST,
                        "minItems": 0,
                        "description": "Replace all categories (empty list clears them).",
                    },
                    "inference_classification": enum(
                        ["focused", "other"], "Focused Inbox placement."
                    ),
                },
                None,
                "Required when resource='email'.",
                minProperties=1,
            ),
            "email_folder_changes": obj(
                {
                    "display_name": string(
                        "New folder name.", minLength=1, maxLength=255
                    )
                },
                ["display_name"],
                "Required when resource='email_folder'.",
            ),
            "contact_changes": obj(
                dict(CONTACT_FIELDS),
                None,
                "Required when resource='contact'. Only supplied fields change; "
                "lists replace the existing list.",
                minProperties=1,
            ),
            "drive_item_changes": obj(
                {
                    "name": string(
                        "New name, including extension.", minLength=1, maxLength=255
                    )
                },
                ["name"],
                "Required when resource='drive_item'.",
            ),
        },
        ["resource", "id"],
    ),
    output_schema=output(
        {
            "resource": {"enum": UPDATE_RESOURCES},
            "id": OUT_STR,
            "status": {"const": "updated"},
            "changed_fields": out_array(OUT_STR),
        },
        "Which fields changed.",
    ),
    graph=[
        (
            "email: PATCH /me/messages/{id} (isRead, flag, importance, categories, "
            "inferenceClassification; add/remove reads current categories first)"
        ),
        "email_folder: PATCH /me/mailFolders/{id}",
        "contact: PATCH /me/contacts/{id}",
        "drive_item: PATCH /me/drive/items/{id} {name}",
    ],
    rules=[
        (
            "Exactly one *_changes object, matching resource.",
            "Invalid email_changes: resource is 'contact'. Expected: contact_changes",
        ),
        (
            (
                "categories_set cannot be combined with categories_add or "
                "categories_remove."
            ),
            (
                "Invalid categories_set: cannot be combined with categories_add or "
                "categories_remove"
            ),
        ),
        (
            "Well-known mail folders cannot be renamed.",
            "Invalid id: inbox cannot be renamed",
        ),
        (
            "The OneDrive root cannot be renamed.",
            "Invalid id: the OneDrive root cannot be renamed",
        ),
    ],
    replaces=[
        "email_update",
        "email_mark_read",
        "email_flag",
        "email_add_category",
        "emailfolders_rename",
        "contact_update",
        "file_rename",
        "folder_rename",
    ],
    examples=[
        {
            "title": "Mark read and add a category",
            "input": {
                "resource": "email",
                "id": "AQMkADAwATM3ZmYAZS1k",
                "email_changes": {"is_read": True, "categories_add": ["Bills"]},
            },
            "output": {
                "resource": "email",
                "id": "AQMkADAwATM3ZmYAZS1k",
                "status": "updated",
                "changed_fields": ["is_read", "categories"],
                "summary": "Updated email: is_read, categories.",
            },
        }
    ],
)

# ---- m365_move -------------------------------------------------------------
MOVE_RESOURCES = ["email", "email_folder", "contact", "drive_item"]
tool(
    name="m365_move",
    title="Move Item",
    tier="core",
    category="m365",
    safety="moderate",
    confirm_mode="never",
    read_only=False,
    destructive=False,
    idempotent=False,
    description=(
        "Move an email, mail folder, contact or OneDrive item to another "
        "folder. Moving an email to 'archive' archives it; moving a contact "
        "places it in a contact folder. Moved emails and contacts get a new "
        "ID, which is returned: use it for later calls."
    ),
    input_schema=obj(
        {
            "resource": enum(MOVE_RESOURCES, "Type of item."),
            "account_id": ACCOUNT_ID,
            "id": item_id("Item to move."),
            "destination_id": item_id(
                "Destination folder. email: mail folder ID or alias (archive, "
                "inbox, junk, deleted, drafts, sent). email_folder: mail folder "
                "ID or 'root'. contact: contact folder ID or 'default'. "
                "drive_item: folder ID or 'root'."
            ),
            "destination_path": string(
                "drive_item only: destination folder path instead of destination_id.",
                minLength=1,
                maxLength=2048,
            ),
            "new_name": string(
                "drive_item only: rename while moving.", minLength=1, maxLength=255
            ),
        },
        ["resource", "id"],
    ),
    output_schema=output(
        {
            "resource": {"enum": MOVE_RESOURCES},
            "previous_id": OUT_STR,
            "id": OUT_STR,
            "status": {"enum": ["moved", "copied_not_removed"]},
            "destination_id": OUT_STR,
        },
        "Move result. status 'copied_not_removed' (contacts only) means the "
        "copy exists but deleting the original failed; both IDs are valid.",
    ),
    graph=[
        "email: POST /me/messages/{id}/move {destinationId} (returns new id)",
        "email_folder: POST /me/mailFolders/{id}/move {destinationId}",
        (
            "contact: POST /me/contactFolders/{dest}/contacts (copy of fields) then "
            "DELETE /me/contacts/{id}"
        ),
        "drive_item: PATCH /me/drive/items/{id} {parentReference, name?}",
    ],
    rules=[
        (
            (
                "Exactly one of destination_id or destination_path (path only for "
                "drive_item)."
            ),
            "Invalid destination_id: required",
        ),
        (
            "A folder cannot be moved into itself or its own subfolder.",
            "Invalid destination_id: is inside the folder being moved",
        ),
        (
            (
                "Not retried after an ambiguous failure; the error says to check "
                "the destination first."
            ),
            "Outcome unknown: check the destination folder before retrying",
        ),
    ],
    replaces=[
        "email_move",
        "email_archive",
        "emailfolders_move",
        "contact_add_to_list",
        "file_move",
        "folder_move",
    ],
    examples=[
        {
            "title": "Archive an email",
            "input": {
                "resource": "email",
                "id": "AQMkADAwATM3ZmYAZS1k",
                "destination_id": "archive",
            },
            "output": {
                "resource": "email",
                "previous_id": "AQMkADAwATM3ZmYAZS1k",
                "id": "AQMkADAwATM3ZmYAZS2m",
                "status": "moved",
                "destination_id": "AQMkADAwATM3ZmYAZS1kARCH",
                "summary": "Moved email to Archive (new id AQMkADAwATM3ZmYAZS2m).",
            },
        }
    ],
)

# ---- m365_delete -----------------------------------------------------------
DELETE_RESOURCES = [
    "email",
    "email_folder",
    "email_rule",
    "event",
    "calendar",
    "contact",
    "contact_folder",
    "drive_item",
]
tool(
    name="m365_delete",
    title="Delete Item",
    tier="core",
    category="m365",
    safety="critical",
    confirm_mode="always",
    confirm_rule="Always required.",
    read_only=False,
    destructive=True,
    idempotent=False,
    description=(
        "Delete one email, mail folder, inbox rule, event, calendar, contact, "
        "contact folder or OneDrive item. Always requires confirm=true after "
        "the user approves. Deleting a meeting you organise sends "
        "cancellations to its attendees. OneDrive items go to the recycle "
        "bin. Returns what happened and whether it can be recovered."
    ),
    input_schema=obj(
        {
            "resource": enum(DELETE_RESOURCES, "Type of item."),
            "account_id": ACCOUNT_ID,
            "id": item_id("Item ID. Aliases are not accepted."),
            "cancellation_message": string(
                "event only: note sent with the cancellation when you organise "
                "the meeting.",
                maxLength=2000,
            ),
            "confirm": confirm("delete this item"),
        },
        ["resource", "id", "confirm"],
    ),
    output_schema=output(
        {
            "resource": {"enum": DELETE_RESOURCES},
            "id": OUT_STR,
            "status": {"enum": ["deleted", "cancelled_and_deleted"]},
            "recoverable": OUT_BOOL,
        },
        "Delete result. recoverable is true only where Graph documents "
        "recovery (OneDrive recycle bin).",
    ),
    graph=[
        "email: DELETE /me/messages/{id}",
        "email_folder: DELETE /me/mailFolders/{id}",
        "email_rule: DELETE /me/mailFolders/inbox/messageRules/{id}",
        (
            "event: organiser with attendees: POST /me/events/{id}/cancel "
            "{comment}; otherwise DELETE /me/events/{id}"
        ),
        "calendar: DELETE /me/calendars/{id}",
        "contact: DELETE /me/contacts/{id}",
        "contact_folder: DELETE /me/contactFolders/{id}",
        "drive_item: DELETE /me/drive/items/{id} (recycle bin)",
    ],
    rules=[
        (
            "confirm must be true.",
            (
                "Invalid confirm 'False': delete requires confirm=True to proceed. "
                "Expected: Explicit user confirmation"
            ),
        ),
        (
            (
                "Aliases and protected items are refused: well-known mail folders, "
                "the default calendar, the OneDrive root."
            ),
            "Invalid id: the default calendar cannot be deleted",
        ),
        (
            "cancellation_message only for resource='event'.",
            "Invalid cancellation_message: only valid for resource='event'",
        ),
        (
            "Never retried after an ambiguous failure.",
            "Outcome unknown: check whether the item still exists before retrying",
        ),
    ],
    replaces=[
        "email_delete",
        "emailfolders_delete",
        "emailrules_delete",
        "calendar_delete_event",
        "calendar_delete_calendar",
        "contact_delete",
        "file_delete",
        "folder_delete",
    ],
    examples=[
        {
            "title": "Delete a OneDrive file",
            "input": {"resource": "drive_item", "id": "01ABCDEF2345", "confirm": True},
            "output": {
                "resource": "drive_item",
                "id": "01ABCDEF2345",
                "status": "deleted",
                "recoverable": True,
                "summary": "Moved 'Tax return 2026.pdf' to the OneDrive recycle bin.",
            },
        }
    ],
)

# ---- email_create_draft ----------------------------------------------------
MESSAGE_FIELDS: dict[str, Schema] = {
    "to": recipients("Recipients (To).", 1),
    "cc": recipients("Cc recipients."),
    "bcc": recipients("Bcc recipients."),
    "subject": string("Subject line.", minLength=1, maxLength=998),
    "body": string("Message body.", maxLength=1000000),
    "body_format": BODY_FORMAT,
    "attachments": ATTACHMENTS,
    "importance": IMPORTANCE,
}
tool(
    name="email_create_draft",
    title="Create Email Draft",
    tier="core",
    category="email",
    safety="moderate",
    confirm_mode="never",
    read_only=False,
    destructive=False,
    idempotent=False,
    description=(
        "Create an unsent email draft to review, then send later with "
        "email_send(mode='draft'). Sends nothing. Returns the draft ID."
    ),
    input_schema=obj(
        {"account_id": ACCOUNT_ID, **MESSAGE_FIELDS},
        ["to", "subject", "body"],
    ),
    output_schema=output(
        {
            "draft_id": OUT_STR,
            "subject": OUT_STR,
            "to": out_array(OUT_STR),
            "cc": out_array(OUT_STR),
            "bcc": out_array(OUT_STR),
            "attachment_count": OUT_INT,
            "web_link": nullable(OUT_STR),
        },
        "The created draft.",
    ),
    graph=[
        "POST /me/messages (draft)",
        "attachments < 3 MB: POST /me/messages/{id}/attachments",
        (
            "attachments ≥ 3 MB: POST /me/messages/{id}/attachments/createUploadSession "
            "then chunked PUT (no Authorization header)"
        ),
    ],
    rules=[
        (
            "At most 500 unique recipients across to, cc and bcc.",
            "Invalid to: more than 500 recipients in total",
        ),
        (
            "Attachments: at most 10 files, 25 MB each, inside allowed roots.",
            "Invalid attachments: 'report.zip' is 31 MB. Expected: at most 25 MB",
        ),
    ],
    replaces=["email_create_draft"],
    examples=[
        {
            "title": "Draft a note",
            "input": {
                "to": ["jane@example.com"],
                "subject": "Weekend",
                "body": "Are you free Saturday?",
            },
            "output": {
                "draft_id": "AQMkADAwATM3ZmYAZS1kDRFT",
                "subject": "Weekend",
                "to": ["jane@example.com"],
                "cc": [],
                "bcc": [],
                "attachment_count": 0,
                "web_link": "https://outlook.live.com/owa/?ItemID=AQMkADAwATM3ZmYAZS1kDRFT",
                "summary": "Draft 'Weekend' created for jane@example.com (not sent).",
            },
        }
    ],
)

# ---- email_send ------------------------------------------------------------
tool(
    name="email_send",
    title="Send Email",
    tier="core",
    category="email",
    safety="dangerous",
    confirm_mode="always",
    confirm_rule="Always required.",
    read_only=False,
    destructive=False,
    idempotent=False,
    description=(
        "Send an email now: a new message (mode='new') or a draft you created "
        "earlier (mode='draft'). Requires confirm=true after the user approves "
        "the recipients and content. Cannot be undone. Never infer "
        "recipients."
    ),
    input_schema=obj(
        {
            "mode": enum(["new", "draft"], "Send a new message or an existing draft."),
            "account_id": ACCOUNT_ID,
            **MESSAGE_FIELDS,
            "save_to_sent": boolean("mode='new': keep a copy in Sent Items.", True),
            "draft_id": item_id("mode='draft': draft ID from email_create_draft."),
            "confirm": confirm("send this email"),
        },
        ["mode", "confirm"],
    ),
    output_schema=output(
        {
            "status": {"const": "sent"},
            "mode": {"enum": ["new", "draft"]},
            "draft_id": nullable(OUT_STR),
            "recipient_count": OUT_INT,
            "sent_at": OUT_DT,
        },
        "Send confirmation.",
    ),
    graph=[
        "new without attachments ≥ 3 MB: POST /me/sendMail {message, saveToSentItems}",
        (
            "new with large attachments: POST /me/messages → upload sessions → "
            "POST /me/messages/{id}/send"
        ),
        "draft: POST /me/messages/{draft_id}/send",
    ],
    rules=[
        (
            (
                "mode='new' requires to, subject and body; mode='draft' requires "
                "draft_id and forbids message fields."
            ),
            "Invalid draft_id: required when mode='draft'",
        ),
        (
            "confirm must be true.",
            (
                "Invalid confirm 'False': send email requires confirm=True to proceed. "
                "Expected: Explicit user confirmation"
            ),
        ),
        (
            "Never retried after a timeout or ambiguous 5xx.",
            "Outcome unknown: check Sent Items before retrying",
        ),
    ],
    replaces=["email_send"],
    examples=[
        {
            "title": "Send a reviewed draft",
            "input": {
                "mode": "draft",
                "draft_id": "AQMkADAwATM3ZmYAZS1kDRFT",
                "confirm": True,
            },
            "output": {
                "status": "sent",
                "mode": "draft",
                "draft_id": "AQMkADAwATM3ZmYAZS1kDRFT",
                "recipient_count": 1,
                "sent_at": "2026-09-26T10:05:00+09:30",
                "summary": "Sent 'Weekend' to 1 recipient.",
            },
        }
    ],
)

# ---- email_reply -----------------------------------------------------------
tool(
    name="email_reply",
    title="Reply to Email",
    tier="core",
    category="email",
    safety="dangerous",
    confirm_mode="always",
    confirm_rule="Always required.",
    read_only=False,
    destructive=False,
    idempotent=False,
    description=(
        "Reply to an email, either to the sender only (mode='sender') or to "
        "everyone on it (mode='all'). Requires confirm=true after the user "
        "approves the reply. Returns the conversation the reply joined."
    ),
    input_schema=obj(
        {
            "email_id": item_id("Email to reply to."),
            "mode": enum(
                ["sender", "all"], "sender: reply to the sender. all: reply all."
            ),
            "account_id": ACCOUNT_ID,
            "body": string("Reply text.", minLength=1, maxLength=1000000),
            "body_format": BODY_FORMAT,
            "cc": recipients("Extra Cc recipients."),
            "attachments": ATTACHMENTS,
            "confirm": confirm("send this reply"),
        },
        ["email_id", "mode", "body", "confirm"],
    ),
    output_schema=output(
        {
            "status": {"const": "sent"},
            "mode": {"enum": ["sender", "all"]},
            "in_reply_to": OUT_STR,
            "conversation_id": nullable(OUT_STR),
        },
        "Reply confirmation.",
    ),
    graph=[
        "plain: POST /me/messages/{id}/reply or /replyAll {comment}",
        (
            "with cc/attachments: POST /createReply or /createReplyAll → PATCH → "
            "attachments → POST /send"
        ),
    ],
    rules=[
        (
            "confirm must be true.",
            "Invalid confirm 'False': reply requires confirm=True to proceed. Expected: Explicit user confirmation",
        ),
        (
            "Never retried after an ambiguous failure.",
            "Outcome unknown: check Sent Items before retrying",
        ),
    ],
    replaces=["email_reply", "email_reply_all"],
    examples=[
        {
            "title": "Reply all",
            "input": {
                "email_id": "AQMkADAwATM3ZmYAZS1k",
                "mode": "all",
                "body": "Tuesday works for me.",
                "confirm": True,
            },
            "output": {
                "status": "sent",
                "mode": "all",
                "in_reply_to": "AQMkADAwATM3ZmYAZS1k",
                "conversation_id": "AQQkADAwATM3ZmYAZS1",
                "summary": "Replied to all on 'Planning meeting'.",
            },
        }
    ],
)

# ---- email_forward ---------------------------------------------------------
tool(
    name="email_forward",
    title="Forward Email",
    tier="core",
    category="email",
    safety="dangerous",
    confirm_mode="always",
    confirm_rule="Always required.",
    read_only=False,
    destructive=False,
    idempotent=False,
    description=(
        "Forward an email to recipients the user names, with an optional "
        "note. Requires confirm=true after the user approves. Never infer "
        "recipients from other context."
    ),
    input_schema=obj(
        {
            "email_id": item_id("Email to forward."),
            "to": recipients("Recipients.", 1),
            "account_id": ACCOUNT_ID,
            "cc": recipients("Cc recipients."),
            "bcc": recipients("Bcc recipients."),
            "comment": string("Note above the forwarded message.", maxLength=100000),
            "attachments": ATTACHMENTS,
            "confirm": confirm("forward this email"),
        },
        ["email_id", "to", "confirm"],
    ),
    output_schema=output(
        {
            "status": {"const": "sent"},
            "forwarded_id": OUT_STR,
            "recipient_count": OUT_INT,
        },
        "Forward confirmation.",
    ),
    graph=[
        "plain: POST /me/messages/{id}/forward {toRecipients, comment}",
        "with cc/bcc/attachments: POST /createForward → PATCH → attachments → POST /send",
    ],
    rules=[
        (
            "confirm must be true.",
            "Invalid confirm 'False': forward requires confirm=True to proceed. Expected: Explicit user confirmation",
        ),
        (
            "Never retried after an ambiguous failure.",
            "Outcome unknown: check Sent Items before retrying",
        ),
    ],
    replaces=["email_forward"],
    examples=[
        {
            "title": "Forward with a note",
            "input": {
                "email_id": "AQMkADAwATM3ZmYAZS1k",
                "to": ["accountant@example.com"],
                "comment": "For our records.",
                "confirm": True,
            },
            "output": {
                "status": "sent",
                "forwarded_id": "AQMkADAwATM3ZmYAZS1k",
                "recipient_count": 1,
                "summary": "Forwarded 'Your September invoice' to 1 recipient.",
            },
        }
    ],
)

# ---- email_folder_mark_all_read -------------------------------------------
tool(
    name="email_folder_mark_all_read",
    title="Mark Folder Read",
    tier="extended",
    category="email",
    safety="moderate",
    confirm_mode="never",
    read_only=False,
    destructive=False,
    idempotent=True,
    description=(
        "Mark every unread message in one mail folder as read, up to "
        "max_messages per call. If remaining_unread is above zero, call "
        "again. Use m365_update for a single message."
    ),
    input_schema=obj(
        {
            "folder_id": MAIL_FOLDER_REF,
            "account_id": ACCOUNT_ID,
            "max_messages": integer(
                "Most messages to change in this call.", 1, 5000, 1000
            ),
        },
        ["folder_id"],
    ),
    output_schema=output(
        {"folder_id": OUT_STR, "marked": OUT_INT, "remaining_unread": OUT_INT},
        "Progress.",
    ),
    graph=[
        "GET /me/mailFolders/{id}/messages?$filter=isRead eq false&$select=id (paged)",
        "POST /$batch (20 × PATCH /me/messages/{id} {isRead:true} per batch)",
    ],
    rules=[
        ("Unknown aliases rejected.", "Invalid folder_id 'Inbx': unknown folder alias")
    ],
    replaces=["emailfolders_mark_all_as_read"],
    examples=[
        {
            "title": "Mark junk read",
            "input": {"folder_id": "junk"},
            "output": {
                "folder_id": "AQMkADAwATM3ZmYAZS1kJUNK",
                "marked": 42,
                "remaining_unread": 0,
                "summary": "Marked 42 messages read in Junk Email.",
            },
        }
    ],
)

# ---- email_folder_empty ----------------------------------------------------
tool(
    name="email_folder_empty",
    title="Empty Mail Folder",
    tier="extended",
    category="email",
    safety="critical",
    confirm_mode="always",
    confirm_rule="Always required.",
    read_only=False,
    destructive=True,
    idempotent=True,
    description=(
        "Delete all messages in one mail folder, such as Junk Email or "
        "Deleted Items, up to max_messages per call. Subfolders are kept. "
        "Requires confirm=true after the user approves. Deleted messages "
        "cannot be restored with these tools."
    ),
    input_schema=obj(
        {
            "folder_id": MAIL_FOLDER_REF,
            "account_id": ACCOUNT_ID,
            "max_messages": integer(
                "Most messages to delete in this call.", 1, 5000, 1000
            ),
            "confirm": confirm("delete every message in this folder"),
        },
        ["folder_id", "confirm"],
    ),
    output_schema=output(
        {"folder_id": OUT_STR, "deleted": OUT_INT, "remaining": OUT_INT},
        "Progress.",
    ),
    graph=[
        "GET /me/mailFolders/{id}/messages?$select=id (paged)",
        "POST /$batch (20 × DELETE /me/messages/{id} per batch)",
    ],
    rules=[
        (
            "confirm must be true.",
            "Invalid confirm 'False': empty folder requires confirm=True to proceed. Expected: Explicit user confirmation",
        ),
        (
            "Partial batch failures are reported, not retried blindly.",
            "Deleted 180 of 200; 20 failed (see remaining). Call again to retry the rest",
        ),
    ],
    replaces=["emailfolders_empty"],
    examples=[
        {
            "title": "Empty Deleted Items",
            "input": {"folder_id": "deleted", "confirm": True},
            "output": {
                "folder_id": "AQMkADAwATM3ZmYAZS1kDEL",
                "deleted": 318,
                "remaining": 0,
                "summary": "Deleted 318 messages from Deleted Items.",
            },
        }
    ],
)

# ---- email_rule_manage -----------------------------------------------------
RULE_INPUT = obj(
    {
        "display_name": string("Rule name.", minLength=1, maxLength=255),
        "conditions": {
            "$ref": "#/$defs/rule_predicates_input",
            "description": "Conditions that must all match.",
        },
        "actions": RULE_ACTIONS,
        "exceptions": {
            "$ref": "#/$defs/rule_predicates_input",
            "description": "Conditions that stop the rule applying.",
        },
        "is_enabled": boolean("Whether the rule runs.", True),
        "sequence": integer("Run order (1 runs first).", 1, 1000),
    },
    None,
    "Rule definition. create requires display_name, conditions and actions; "
    "update applies only the supplied fields.",
    minProperties=1,
)
tool(
    name="email_rule_manage",
    title="Manage Inbox Rule",
    tier="extended",
    category="email",
    safety="dangerous",
    confirm_mode="conditional",
    confirm_rule=(
        "Required when the resulting rule forwards, redirects or deletes mail "
        "(forward_to, forward_as_attachment_to, redirect_to, delete, "
        "permanent_delete)."
    ),
    read_only=False,
    destructive=False,
    idempotent=False,
    description=(
        "Create, change, enable or disable, or reorder an Inbox rule. Rules "
        "that forward, redirect or delete mail require confirm=true because "
        "they act silently on future mail. Read rules with m365_list or "
        "m365_get; delete one with m365_delete. Returns the rule."
    ),
    input_schema=obj(
        {
            "action": enum(
                ["create", "update", "set_enabled", "reorder"], "What to do."
            ),
            "account_id": ACCOUNT_ID,
            "rule_id": item_id("Existing rule (update, set_enabled, reorder)."),
            "rule": RULE_INPUT,
            "is_enabled": boolean(
                "set_enabled: turn the rule on (true) or off (false)."
            ),
            "position": enum(
                ["top", "bottom", "up", "down", "before", "after"],
                "reorder: new position. before/after need relative_to_rule_id.",
            ),
            "relative_to_rule_id": item_id(
                "reorder with before/after: the other rule."
            ),
            "confirm": confirm("save a rule that forwards, redirects or deletes mail"),
        },
        ["action"],
        defs={"rule_predicates_input": RULE_PREDICATES},
    ),
    output_schema=output(
        {
            "action": {"enum": ["create", "update", "set_enabled", "reorder"]},
            "rule": ref("email_rule"),
        },
        "The rule after the change.",
    ),
    graph=[
        "create: POST /me/mailFolders/inbox/messageRules",
        "update / set_enabled: PATCH /me/mailFolders/inbox/messageRules/{id}",
        "reorder: GET all rules, then PATCH sequence on each rule whose position changes",
    ],
    rules=[
        (
            "create needs rule.display_name, rule.conditions and rule.actions.",
            "Invalid rule: create requires display_name, conditions and actions",
        ),
        (
            "update / set_enabled / reorder need rule_id.",
            "Invalid rule_id: required for action 'reorder'",
        ),
        (
            "before/after need relative_to_rule_id, which must differ from rule_id.",
            "Invalid relative_to_rule_id: required for position 'before'",
        ),
        (
            "move_to_folder / copy_to_folder must be existing mail folder IDs.",
            "Invalid move_to_folder: folder not found",
        ),
        (
            "confirm required when the resulting rule forwards, redirects or deletes.",
            "Invalid confirm 'False': a rule that forwards mail requires confirm=True to proceed. Expected: Explicit user confirmation",
        ),
    ],
    replaces=[
        "emailrules_create",
        "emailrules_update",
        "emailrules_move_top",
        "emailrules_move_bottom",
        "emailrules_move_up",
        "emailrules_move_down",
    ],
    examples=[
        {
            "title": "File bills into a folder",
            "input": {
                "action": "create",
                "rule": {
                    "display_name": "Bills",
                    "conditions": {"from_addresses": ["billing@example.com"]},
                    "actions": {
                        "move_to_folder": "AQMkADAwATM3ZmYAZS1kBILL",
                        "stop_processing_rules": True,
                    },
                },
            },
            "output": {
                "action": "create",
                "rule": {
                    "id": "AQAAAJ5dZqA=",
                    "display_name": "Bills",
                    "sequence": 3,
                    "is_enabled": True,
                    "conditions": {"from_addresses": ["billing@example.com"]},
                    "actions": {
                        "move_to_folder": "AQMkADAwATM3ZmYAZS1kBILL",
                        "stop_processing_rules": True,
                    },
                    "exceptions": None,
                },
                "summary": "Created rule 'Bills' (position 3).",
            },
        }
    ],
)

# ---- calendar_create_event -------------------------------------------------
EVENT_FIELDS: dict[str, Schema] = {
    "subject": string("Title.", minLength=1, maxLength=255),
    "start": DATETIME,
    "end": DATETIME,
    "time_zone": TIME_ZONE,
    "is_all_day": boolean("All-day event (start and end at midnight in time_zone)."),
    "location": string("Location text.", maxLength=255),
    "body": string("Description.", maxLength=100000),
    "body_format": BODY_FORMAT,
    "reminder_minutes": integer("Reminder before start, in minutes.", 0, 40320),
    "show_as": SHOW_AS,
}
tool(
    name="calendar_create_event",
    title="Create Event",
    tier="core",
    category="calendar",
    safety="dangerous",
    confirm_mode="conditional",
    confirm_rule="Required when attendees is non-empty (Outlook emails each attendee an invitation).",
    read_only=False,
    destructive=False,
    idempotent=False,
    description=(
        "Add an event to your calendar. With attendees, Outlook emails them "
        "an invitation, so confirm=true is then required. Without attendees "
        "it is a private appointment and needs no confirmation. Returns the "
        "event."
    ),
    input_schema=obj(
        {
            "account_id": ACCOUNT_ID,
            **EVENT_FIELDS,
            "attendees": array(ATTENDEE_INPUT, "People to invite.", maxItems=500),
            "calendar_id": item_id("Calendar ID (default: your default calendar)."),
            "confirm": confirm("send invitations to the attendees"),
        },
        ["subject", "start", "end"],
    ),
    output_schema=output(
        {"event": ref("event_detail"), "invitations_sent": OUT_BOOL},
        "The created event.",
    ),
    graph=["POST /me/events or /me/calendars/{id}/events (Prefer: outlook.timezone)"],
    rules=[
        ("end must be after start.", "Invalid end: must be after start"),
        (
            "confirm required when attendees is non-empty.",
            "Invalid confirm 'False': inviting attendees requires confirm=True to proceed. Expected: Explicit user confirmation",
        ),
        (
            "Never retried after an ambiguous failure.",
            "Outcome unknown: check your calendar before retrying",
        ),
    ],
    replaces=["calendar_create_event"],
    examples=[
        {
            "title": "Private appointment",
            "input": {
                "subject": "Dentist",
                "start": "2026-10-02T09:00:00+09:30",
                "end": "2026-10-02T10:00:00+09:30",
                "location": "City Dental",
            },
            "output": {
                "event": {
                    "id": "AAMkADAwATM3EVT",
                    "subject": "Dentist",
                    "start": "2026-10-02T09:00:00+09:30",
                    "end": "2026-10-02T10:00:00+09:30",
                    "time_zone": "Australia/Adelaide",
                    "is_all_day": False,
                    "location": "City Dental",
                    "organizer": {"name": "Robin", "address": "robin@example.com"},
                    "is_organizer": True,
                    "my_response": "organizer",
                    "show_as": "busy",
                    "attendee_count": 0,
                    "calendar_id": "AAMkADAwATM3CAL",
                    "preview": None,
                    "body": None,
                    "body_truncated": False,
                    "attendees": [],
                    "web_link": "https://outlook.live.com/calendar/item/AAMkADAwATM3EVT",
                    "recurrence": None,
                },
                "invitations_sent": False,
                "summary": "Created 'Dentist' on 2 Oct 09:00–10:00 (no invitations sent).",
            },
        }
    ],
)

# ---- calendar_update_event -------------------------------------------------
tool(
    name="calendar_update_event",
    title="Update Event",
    tier="core",
    category="calendar",
    safety="dangerous",
    confirm_mode="conditional",
    confirm_rule="Required when the event has attendees or the change adds any (Outlook emails them an update).",
    read_only=False,
    destructive=False,
    idempotent=True,
    description=(
        "Change an event's time, title, location, description, reminder or "
        "attendees. If the event has attendees, or you add some, Outlook "
        "emails them an update, so confirm=true is then required. Returns "
        "the updated event."
    ),
    input_schema=obj(
        {
            "event_id": item_id("Event to change."),
            "account_id": ACCOUNT_ID,
            "changes": obj(
                {
                    **EVENT_FIELDS,
                    "attendees_set": array(
                        ATTENDEE_INPUT, "Replace the attendee list.", maxItems=500
                    ),
                    "attendees_add": array(
                        ATTENDEE_INPUT, "Attendees to add.", minItems=1, maxItems=500
                    ),
                    "attendees_remove": recipients("Attendee addresses to remove.", 1),
                },
                None,
                "Fields to change (at least one).",
                minProperties=1,
            ),
            "confirm": confirm("send updates to the attendees"),
        },
        ["event_id", "changes"],
    ),
    output_schema=output(
        {
            "event": ref("event_detail"),
            "attendees_notified": OUT_BOOL,
            "changed_fields": out_array(OUT_STR),
        },
        "The updated event.",
    ),
    graph=["GET /me/events/{id} (to detect attendees)", "PATCH /me/events/{id}"],
    rules=[
        (
            "attendees_set cannot be combined with attendees_add or attendees_remove.",
            "Invalid attendees_set: cannot be combined with attendees_add or attendees_remove",
        ),
        ("Resulting end must be after start.", "Invalid end: must be after start"),
        (
            "Only the organiser can change time, attendees or location of a meeting.",
            "You are not the organiser of this meeting. Expected: use calendar_respond to propose a new time",
        ),
        (
            "confirm required when attendees are affected.",
            "Invalid confirm 'False': updating a meeting with attendees requires confirm=True to proceed. Expected: Explicit user confirmation",
        ),
    ],
    replaces=["calendar_update_event"],
    examples=[
        {
            "title": "Move a private appointment",
            "input": {
                "event_id": "AAMkADAwATM3EVT",
                "changes": {
                    "start": "2026-10-02T11:00:00+09:30",
                    "end": "2026-10-02T12:00:00+09:30",
                },
            },
            "output": {
                "event": {
                    "id": "AAMkADAwATM3EVT",
                    "subject": "Dentist",
                    "start": "2026-10-02T11:00:00+09:30",
                    "end": "2026-10-02T12:00:00+09:30",
                    "time_zone": "Australia/Adelaide",
                    "is_all_day": False,
                    "location": "City Dental",
                    "organizer": {"name": "Robin", "address": "robin@example.com"},
                    "is_organizer": True,
                    "my_response": "organizer",
                    "show_as": "busy",
                    "attendee_count": 0,
                    "calendar_id": "AAMkADAwATM3CAL",
                    "preview": None,
                    "body": None,
                    "body_truncated": False,
                    "attendees": [],
                    "web_link": "https://outlook.live.com/calendar/item/AAMkADAwATM3EVT",
                    "recurrence": None,
                },
                "attendees_notified": False,
                "changed_fields": ["start", "end"],
                "summary": "Moved 'Dentist' to 2 Oct 11:00–12:00.",
            },
        }
    ],
)

# ---- calendar_respond ------------------------------------------------------
tool(
    name="calendar_respond",
    title="Respond to Invitation",
    tier="core",
    category="calendar",
    safety="dangerous",
    confirm_mode="conditional",
    confirm_rule="Required when send_response is true (the organiser is emailed).",
    read_only=False,
    destructive=False,
    idempotent=False,
    description=(
        "Accept, tentatively accept or decline a meeting invitation, "
        "optionally proposing a new time (with tentative or decline). When a "
        "response is emailed to the organiser (the default), confirm=true is "
        "required."
    ),
    input_schema=obj(
        {
            "event_id": item_id("Invitation's event ID."),
            "action": enum(["accept", "tentative", "decline"], "Your response."),
            "account_id": ACCOUNT_ID,
            "comment": string("Message to the organiser.", maxLength=2000),
            "send_response": boolean("Email the response to the organiser.", True),
            "proposed_start": {
                **DATETIME,
                "description": "Proposed new start (tentative or decline only).",
            },
            "proposed_end": {
                **DATETIME,
                "description": "Proposed new end (tentative or decline only).",
            },
            "confirm": confirm("send this response to the organiser"),
        },
        ["event_id", "action"],
    ),
    output_schema=output(
        {
            "event_id": OUT_STR,
            "action": {"enum": ["accept", "tentative", "decline"]},
            "response_sent": OUT_BOOL,
            "proposed_start": nullable(OUT_DT),
            "proposed_end": nullable(OUT_DT),
        },
        "Response result.",
    ),
    graph=[
        "POST /me/events/{id}/accept | /tentativelyAccept | /decline {comment, sendResponse, proposedNewTime?}"
    ],
    rules=[
        (
            "proposed_start and proposed_end come together, only with tentative or decline, end after start.",
            "Invalid proposed_end: required with proposed_start",
        ),
        (
            "You cannot respond to your own meeting.",
            "You organise this meeting; there is nothing to respond to",
        ),
        (
            "confirm required when send_response is true.",
            "Invalid confirm 'False': sending a response requires confirm=True to proceed. Expected: Explicit user confirmation",
        ),
    ],
    replaces=["calendar_respond_event", "calendar_propose_new_time"],
    examples=[
        {
            "title": "Decline and propose another time",
            "input": {
                "event_id": "AAMkADAwATM3INV",
                "action": "decline",
                "comment": "Can we do Thursday?",
                "proposed_start": "2026-10-08T14:00:00+09:30",
                "proposed_end": "2026-10-08T15:00:00+09:30",
                "confirm": True,
            },
            "output": {
                "event_id": "AAMkADAwATM3INV",
                "action": "decline",
                "response_sent": True,
                "proposed_start": "2026-10-08T14:00:00+09:30",
                "proposed_end": "2026-10-08T15:00:00+09:30",
                "summary": "Declined 'Book club' and proposed 8 Oct 14:00–15:00.",
            },
        }
    ],
)

# ---- calendar_forward ------------------------------------------------------
tool(
    name="calendar_forward",
    title="Forward Invitation",
    tier="extended",
    category="calendar",
    safety="dangerous",
    confirm_mode="always",
    confirm_rule="Always required.",
    read_only=False,
    destructive=False,
    idempotent=False,
    description=(
        "Forward a meeting invitation to people the user names, with an "
        "optional note. Requires confirm=true after the user approves."
    ),
    input_schema=obj(
        {
            "event_id": item_id("Event to forward."),
            "to": recipients("Recipients.", 1, 100),
            "account_id": ACCOUNT_ID,
            "comment": string("Note to include.", maxLength=2000),
            "confirm": confirm("forward this invitation"),
        },
        ["event_id", "to", "confirm"],
    ),
    output_schema=output(
        {
            "event_id": OUT_STR,
            "status": {"const": "forwarded"},
            "recipient_count": OUT_INT,
        },
        "Forward result.",
    ),
    graph=["POST /me/events/{id}/forward {toRecipients, comment}"],
    rules=[
        (
            "confirm must be true.",
            "Invalid confirm 'False': forward invitation requires confirm=True to proceed. Expected: Explicit user confirmation",
        )
    ],
    replaces=["calendar_forward_event"],
    examples=[
        {
            "title": "Forward to a friend",
            "input": {
                "event_id": "AAMkADAwATM3INV",
                "to": ["sam@example.com"],
                "confirm": True,
            },
            "output": {
                "event_id": "AAMkADAwATM3INV",
                "status": "forwarded",
                "recipient_count": 1,
                "summary": "Forwarded 'Book club' to 1 recipient.",
            },
        }
    ],
)

# ---- calendar_find_availability -------------------------------------------
tool(
    name="calendar_find_availability",
    title="Find Free Time",
    tier="core",
    category="calendar",
    safety="safe",
    confirm_mode="never",
    read_only=True,
    destructive=False,
    idempotent=True,
    description=(
        "Show when you are busy in your own calendar during a time range and, "
        "given slot_minutes, suggest free slots of that length within your "
        "working hours. Personal accounts cannot see other people's "
        "availability, so this covers your calendar only."
    ),
    input_schema=obj(
        {
            "start": DATETIME,
            "end": {
                **DATETIME,
                "description": "Range end; at most 62 days after start.",
            },
            "account_id": ACCOUNT_ID,
            "time_zone": TIME_ZONE,
            "slot_minutes": integer("Length of free slots to suggest.", 15, 480),
            "working_hours_only": boolean(
                "Only suggest slots inside your Outlook working hours.", True
            ),
            "min_gap_minutes": integer(
                "Buffer to keep before and after busy time.", 0, 120, 0
            ),
            "max_slots": integer("Most free slots to return.", 1, 50, 10),
        },
        ["start", "end"],
    ),
    output_schema=output(
        {
            "time_zone": OUT_STR,
            "busy": out_array(
                out_obj(
                    {
                        "start": OUT_DT,
                        "end": OUT_DT,
                        "show_as": {
                            "enum": ["tentative", "busy", "oof", "workingElsewhere"]
                        },
                        "subject": nullable(OUT_STR),
                    },
                    "Busy block.",
                )
            ),
            "free_slots": out_array(
                out_obj({"start": OUT_DT, "end": OUT_DT}, "Free slot.")
            ),
            "working_hours": nullable(
                out_obj(
                    {
                        "days": out_array(
                            {
                                "enum": [
                                    "monday",
                                    "tuesday",
                                    "wednesday",
                                    "thursday",
                                    "friday",
                                    "saturday",
                                    "sunday",
                                ]
                            }
                        ),
                        "start_time": OUT_STR,
                        "end_time": OUT_STR,
                        "time_zone": OUT_STR,
                    },
                    "Your Outlook working hours.",
                )
            ),
        },
        "Busy blocks and suggested free slots.",
    ),
    graph=[
        "GET /me/calendarView?startDateTime&endDateTime&$select=subject,start,end,showAs (paged)",
        "GET /me/mailboxSettings/workingHours",
        "Free slots computed server-side (getSchedule/findMeetingTimes are not used: undocumented or unsupported for personal accounts)",
    ],
    rules=[
        (
            "end after start, at most 62 days.",
            "Invalid end: must be after start and within 62 days",
        ),
        (
            "working_hours_only has no effect without slot_minutes.",
            "(no error; busy blocks are always returned)",
        ),
    ],
    replaces=["calendar_check_availability", "calendar_get_free_busy"],
    examples=[
        {
            "title": "An hour free on Thursday",
            "input": {
                "start": "2026-10-01T00:00:00+09:30",
                "end": "2026-10-02T00:00:00+09:30",
                "slot_minutes": 60,
                "max_slots": 1,
            },
            "output": {
                "time_zone": "Australia/Adelaide",
                "busy": [
                    {
                        "start": "2026-10-01T09:00:00+09:30",
                        "end": "2026-10-01T10:30:00+09:30",
                        "show_as": "busy",
                        "subject": "Physio",
                    }
                ],
                "free_slots": [
                    {
                        "start": "2026-10-01T10:30:00+09:30",
                        "end": "2026-10-01T11:30:00+09:30",
                    }
                ],
                "working_hours": {
                    "days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
                    "start_time": "08:00:00",
                    "end_time": "17:00:00",
                    "time_zone": "Australia/Adelaide",
                },
                "summary": "1 busy block; first free hour 10:30–11:30.",
            },
        }
    ],
)

# ---- drive_upload ----------------------------------------------------------
tool(
    name="drive_upload",
    title="Upload File",
    tier="extended",
    category="drive",
    safety="moderate",
    confirm_mode="never",
    read_only=False,
    destructive=False,
    idempotent=False,
    description=(
        "Upload a local file to OneDrive, as a new file (parent_id or "
        "parent_path) or by replacing an existing file's contents (item_id). "
        "Reads from the local disk, inside the allowed folders only. Returns "
        "the OneDrive item."
    ),
    input_schema=obj(
        {
            "local_path": LOCAL_PATH,
            "account_id": ACCOUNT_ID,
            "parent_id": item_id("New file: destination folder ID ('root' allowed)."),
            "parent_path": string(
                "New file: destination folder path, e.g. /Documents.",
                minLength=1,
                maxLength=2048,
            ),
            "name": string(
                "New file: name in OneDrive (default: local file name).",
                minLength=1,
                maxLength=255,
            ),
            "item_id": item_id("Replace the contents of this existing file."),
            "if_exists": enum(
                ["fail", "replace", "rename"],
                "New file: what to do if the name is taken.",
                default="fail",
            ),
        },
        ["local_path"],
    ),
    output_schema=output(
        {
            "item": ref("drive_item"),
            "status": {"enum": ["created", "replaced", "renamed"]},
        },
        "The uploaded file.",
    ),
    graph=[
        "≤ 4 MB: PUT /me/drive/items/{parent}:/{name}:/content or /me/drive/items/{item}/content",
        "> 4 MB: POST …/createUploadSession then 15 × 320 KiB chunks (no Authorization header)",
    ],
    rules=[
        (
            "Exactly one target: item_id, or parent_id/parent_path (not both).",
            "Invalid item_id: cannot be combined with parent_id or parent_path",
        ),
        (
            "local_path inside allowed roots, not deny-listed, and a regular file.",
            "Invalid local_path: '.env' is a protected file",
        ),
        (
            "if_exists='fail' and the name exists.",
            "A file named 'budget.xlsx' already exists there. Expected: if_exists='replace' or 'rename'",
        ),
    ],
    replaces=["file_create", "file_update"],
    examples=[
        {
            "title": "Upload a new file",
            "input": {
                "local_path": "C:/Users/me/Downloads/budget.xlsx",
                "parent_path": "/Documents",
            },
            "output": {
                "item": {
                    "id": "01ABCDEF6789",
                    "name": "budget.xlsx",
                    "item_type": "file",
                    "path": "/Documents",
                    "parent_id": "01ABCDEF0002",
                    "size": 20480,
                    "modified_at": "2026-09-26T10:10:00+09:30",
                    "created_at": "2026-09-26T10:10:00+09:30",
                    "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "child_count": None,
                    "web_url": "https://onedrive.live.com/?id=01ABCDEF6789",
                    "shared": False,
                    "children": None,
                },
                "status": "created",
                "summary": "Uploaded budget.xlsx to /Documents.",
            },
        }
    ],
)

# ---- drive_copy ------------------------------------------------------------
tool(
    name="drive_copy",
    title="Copy File",
    tier="extended",
    category="drive",
    safety="moderate",
    confirm_mode="never",
    read_only=False,
    destructive=False,
    idempotent=False,
    description=(
        "Copy a OneDrive file or folder to another folder. Copying runs in "
        "the background: this returns an operation_id to check with "
        "m365_get(resource='operation')."
    ),
    input_schema=obj(
        {
            "item_id": item_id("File or folder to copy."),
            "account_id": ACCOUNT_ID,
            "destination_id": item_id("Destination folder ID ('root' allowed)."),
            "destination_path": string(
                "Destination folder path instead of destination_id.",
                minLength=1,
                maxLength=2048,
            ),
            "new_name": string(
                "Name for the copy (default: same name).", minLength=1, maxLength=255
            ),
        },
        ["item_id"],
    ),
    output_schema=output(
        {"operation_id": OUT_STR, "status": {"const": "in_progress"}}, "Started copy."
    ),
    graph=[
        "POST /me/drive/items/{id}/copy {parentReference, name} → 202 + Location monitor URL (stored server-side for 24 hours)"
    ],
    rules=[
        (
            "Exactly one of destination_id or destination_path.",
            "Invalid destination_path: cannot be combined with destination_id",
        )
    ],
    replaces=["file_copy"],
    examples=[
        {
            "title": "Copy a file",
            "input": {"item_id": "01ABCDEF6789", "destination_path": "/Backups"},
            "output": {
                "operation_id": "op_7f3c2a",
                "status": "in_progress",
                "summary": "Copy started; check with m365_get(resource='operation', id='op_7f3c2a').",
            },
        }
    ],
)

# ---- drive_share -----------------------------------------------------------
tool(
    name="drive_share",
    title="Share File",
    tier="extended",
    category="drive",
    safety="dangerous",
    confirm_mode="always",
    confirm_rule="Always required.",
    read_only=False,
    destructive=False,
    idempotent=False,
    description=(
        "Share a OneDrive file or folder by link (mode='link') or by inviting "
        "named people (mode='invite'). A view or edit link works for anyone "
        "who has it. Always requires confirm=true after the user approves who "
        "gets access. Returns the link or the invitation results."
    ),
    input_schema=obj(
        {
            "item_id": item_id("File or folder to share (not the OneDrive root)."),
            "mode": enum(
                ["link", "invite"], "Share by link or invite specific people."
            ),
            "account_id": ACCOUNT_ID,
            "link_type": enum(
                ["view", "edit", "embed"],
                "link: view (read-only), edit, or embed (files only).",
            ),
            "recipients": recipients("invite: people to share with.", 1, 50),
            "role": enum(["read", "write"], "invite: access level."),
            "message": string("invite: note in the invitation email.", maxLength=2000),
            "send_invitation": boolean("invite: email the recipients.", True),
            "require_sign_in": boolean("invite: recipients must sign in.", True),
            "password": string(
                "Optional password for the link or invitation.",
                minLength=4,
                maxLength=256,
            ),
            "expires_at": {
                **DATETIME,
                "description": "Optional expiry (invite expiry needs a premium OneDrive).",
            },
            "confirm": confirm("grant this access"),
        },
        ["item_id", "mode", "confirm"],
    ),
    output_schema=output(
        {
            "mode": {"enum": ["link", "invite"]},
            "permission_ids": out_array(OUT_STR),
            "link_url": nullable(OUT_STR),
            "created": nullable(OUT_BOOL),
            "recipients": out_array(
                out_obj(
                    {
                        "email": OUT_STR,
                        "status": {"enum": ["granted", "failed"]},
                        "error": nullable(OUT_STR),
                    },
                    "Per-recipient result.",
                )
            ),
        },
        "Sharing result. created=false means an existing link of that type was returned.",
    ),
    graph=[
        "link: POST /me/drive/items/{id}/createLink {type, scope:'anonymous', password?, expirationDateTime?}",
        "invite: POST /me/drive/items/{id}/invite {recipients, roles, message, sendInvitation, requireSignIn, password?, expirationDateTime?} (207 partial success mapped per recipient)",
    ],
    rules=[
        (
            "link needs link_type; invite needs recipients and role; fields of the other mode are rejected.",
            "Invalid recipients: only valid with mode='invite'",
        ),
        (
            "embed links only for files.",
            "Invalid link_type 'embed': only files can be embedded",
        ),
        (
            "The OneDrive root cannot be shared.",
            "Invalid item_id: the OneDrive root cannot be shared",
        ),
        (
            "confirm must be true.",
            "Invalid confirm 'False': sharing requires confirm=True to proceed. Expected: Explicit user confirmation",
        ),
    ],
    replaces=["file_share"],
    examples=[
        {
            "title": "View-only link",
            "input": {
                "item_id": "01ABCDEF6789",
                "mode": "link",
                "link_type": "view",
                "confirm": True,
            },
            "output": {
                "mode": "link",
                "permission_ids": ["aTowIy5mfG1lbWJlcnNoaXA"],
                "link_url": "https://1drv.ms/x/s!AbCdEf",
                "created": True,
                "recipients": [],
                "summary": "Created a view-only link to budget.xlsx (anyone with the link can open it).",
            },
        }
    ],
)

# ---- account & admin -------------------------------------------------------
tool(
    name="account_list",
    title="List Accounts",
    tier="admin",
    category="account",
    safety="safe",
    confirm_mode="never",
    read_only=True,
    destructive=False,
    idempotent=True,
    description=(
        "List the Microsoft accounts signed in to this server. Needed only "
        "when more than one account is signed in, to choose account_id."
    ),
    input_schema=obj({}),
    output_schema=output(
        {
            "accounts": out_array(
                out_obj(
                    {
                        "account_id": OUT_STR,
                        "email": OUT_STR,
                        "display_name": nullable(OUT_STR),
                    },
                    "Signed-in account.",
                )
            )
        },
        "Signed-in accounts.",
    ),
    graph=["None (local MSAL token cache)."],
    rules=[],
    replaces=["account_list"],
    examples=[
        {
            "title": "One account",
            "input": {},
            "output": {
                "accounts": [
                    {
                        "account_id": "00000000-0000-0000-d16c-ebaa65a1624c.9188040d-6c67-4c5b-b112-36a304b66dad",
                        "email": "robin@example.com",
                        "display_name": "Robin",
                    }
                ],
                "summary": "1 account signed in.",
            },
        }
    ],
)
tool(
    name="account_auth_begin",
    title="Start Sign-in",
    tier="admin",
    category="account",
    safety="moderate",
    confirm_mode="never",
    read_only=False,
    destructive=False,
    idempotent=False,
    description=(
        "Start signing in a personal Microsoft account. Returns a web address "
        "and code for the user to enter, and an auth_session_id to pass to "
        "account_auth_complete. Prefer `uv run authenticate.py` when "
        "available."
    ),
    input_schema=obj({}),
    output_schema=output(
        {
            "auth_session_id": OUT_STR,
            "verification_url": OUT_STR,
            "user_code": OUT_STR,
            "expires_in": OUT_INT,
        },
        "Sign-in instructions. The device code itself never leaves the server.",
    ),
    graph=[
        "MSAL initiate_device_flow against https://login.microsoftonline.com/consumers"
    ],
    rules=[],
    replaces=["account_authenticate"],
    examples=[
        {
            "title": "Begin",
            "input": {},
            "output": {
                "auth_session_id": "as_91b2",
                "verification_url": "https://login.microsoft.com/device",
                "user_code": "PMQDYGWPS",
                "expires_in": 900,
                "summary": "Visit https://login.microsoft.com/device and enter PMQDYGWPS.",
            },
        }
    ],
)
tool(
    name="account_auth_complete",
    title="Finish Sign-in",
    tier="admin",
    category="account",
    safety="moderate",
    confirm_mode="never",
    read_only=False,
    destructive=False,
    idempotent=True,
    description=(
        "Finish a sign-in started with account_auth_begin, after the user has "
        "entered the code. Returns pending (try again shortly) or the "
        "signed-in account. Work or school accounts are rejected."
    ),
    input_schema=obj(
        {
            "auth_session_id": string(
                "From account_auth_begin.", minLength=1, maxLength=128
            )
        },
        ["auth_session_id"],
    ),
    output_schema=output(
        {
            "status": {"enum": ["pending", "success"]},
            "account": nullable(
                out_obj({"account_id": OUT_STR, "email": OUT_STR}, "Signed-in account.")
            ),
        },
        "Sign-in state.",
    ),
    graph=[
        "MSAL acquire_token_by_device_flow (single poll, exit_condition=lambda f: True)"
    ],
    rules=[
        (
            "Unknown or expired sessions are rejected.",
            "Invalid auth_session_id: unknown or expired. Expected: start again with account_auth_begin",
        ),
        (
            "Work/school accounts are rejected.",
            "Only personal Microsoft accounts are supported",
        ),
    ],
    replaces=["account_complete_auth"],
    examples=[
        {
            "title": "Still waiting",
            "input": {"auth_session_id": "as_91b2"},
            "output": {
                "status": "pending",
                "account": None,
                "summary": "Waiting for the user to enter the code.",
            },
        }
    ],
)
tool(
    name="admin_cache_get",
    title="Cache Status",
    tier="admin",
    category="admin",
    safety="safe",
    confirm_mode="never",
    read_only=True,
    destructive=False,
    idempotent=True,
    description=(
        "Inspect the local encrypted cache: overall statistics (view='stats'), "
        "background tasks (view='tasks'), one task (view='task') or cache "
        "warming progress (view='warming')."
    ),
    input_schema=obj(
        {
            "view": enum(["stats", "tasks", "task", "warming"], "What to show."),
            "task_id": string("view='task': task ID.", minLength=1, maxLength=128),
            "status": enum(
                ["queued", "running", "completed", "failed"],
                "view='tasks': filter by status.",
            ),
            "account_id": ACCOUNT_ID,
            "limit": integer("view='tasks': most tasks to return.", 1, 200, 50),
        },
        ["view"],
    ),
    output_schema=output(
        {
            "view": {"enum": ["stats", "tasks", "task", "warming"]},
            "stats": nullable(
                out_obj(
                    {
                        "entry_count": OUT_INT,
                        "total_bytes": OUT_INT,
                        "max_bytes": OUT_INT,
                        "usage_percent": {"type": "number", "minimum": 0},
                        "total_hits": OUT_INT,
                        "by_resource": {
                            "type": "object",
                            "additionalProperties": {"type": "object"},
                        },
                    },
                    "Cache statistics.",
                )
            ),
            "tasks": nullable(
                out_array(
                    out_obj(
                        {
                            "task_id": OUT_STR,
                            "operation": OUT_STR,
                            "status": {
                                "enum": ["queued", "running", "completed", "failed"]
                            },
                            "priority": {"type": "integer"},
                            "retry_count": OUT_INT,
                            "created_at": nullable(OUT_STR),
                            "started_at": nullable(OUT_STR),
                            "completed_at": nullable(OUT_STR),
                            "error": nullable(OUT_STR),
                        },
                        "Background task.",
                    )
                )
            ),
            "warming": nullable(
                out_obj(
                    {
                        "status": OUT_STR,
                        "is_warming": OUT_BOOL,
                        "operations_total": OUT_INT,
                        "operations_completed": OUT_INT,
                        "operations_skipped": OUT_INT,
                        "operations_failed": OUT_INT,
                        "progress_percent": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 100,
                        },
                    },
                    "Warming progress.",
                )
            ),
        },
        "Cache information; fields for other views are null. view='task' returns a one-element tasks list.",
    ),
    graph=["None (local cache database)."],
    rules=[
        ("view='task' requires task_id.", "Invalid task_id: required for view='task'")
    ],
    replaces=[
        "cache_get_stats",
        "cache_task_list",
        "cache_task_get_status",
        "cache_warming_status",
    ],
    examples=[
        {
            "title": "Warming status",
            "input": {"view": "warming"},
            "output": {
                "view": "warming",
                "stats": None,
                "tasks": None,
                "warming": {
                    "status": "disabled",
                    "is_warming": False,
                    "operations_total": 0,
                    "operations_completed": 0,
                    "operations_skipped": 0,
                    "operations_failed": 0,
                    "progress_percent": 0.0,
                },
                "summary": "Cache warming is disabled.",
            },
        }
    ],
)
tool(
    name="admin_cache_invalidate",
    title="Clear Cache",
    tier="admin",
    category="admin",
    safety="moderate",
    confirm_mode="never",
    read_only=False,
    destructive=False,
    idempotent=True,
    description=(
        "Remove cached results so the next call fetches fresh data: for one "
        "resource type or all, for one account or all."
    ),
    input_schema=obj(
        {
            "scope": enum(LIST_RESOURCES + ["all"], "Resource type to clear, or all."),
            "account_id": ACCOUNT_ID,
            "reason": string("Why (recorded in the audit log).", maxLength=500),
        },
        ["scope"],
    ),
    output_schema=output(
        {"scope": OUT_STR, "entries_removed": OUT_INT}, "Invalidation result."
    ),
    graph=["None (local cache database)."],
    rules=[],
    replaces=["cache_invalidate"],
    examples=[
        {
            "title": "Clear email cache",
            "input": {"scope": "email", "reason": "stale inbox"},
            "output": {
                "scope": "email",
                "entries_removed": 12,
                "summary": "Removed 12 cached email entries.",
            },
        }
    ],
)
tool(
    name="admin_server_info",
    title="Server Info",
    tier="admin",
    category="admin",
    safety="safe",
    confirm_mode="never",
    read_only=True,
    destructive=False,
    idempotent=True,
    description="Report the server version, supported MCP protocol versions and enabled toolsets.",
    input_schema=obj({}),
    output_schema=output(
        {
            "version": OUT_STR,
            "protocol_versions": out_array(OUT_STR),
            "toolsets_enabled": out_array({"enum": ["core", "extended", "admin"]}),
            "tool_count": OUT_INT,
            "cache_enabled": OUT_BOOL,
        },
        "Server information.",
    ),
    graph=["None."],
    rules=[],
    replaces=["server_get_version"],
    examples=[
        {
            "title": "Info",
            "input": {},
            "output": {
                "version": "1.0.0",
                "protocol_versions": ["2025-06-18"],
                "toolsets_enabled": ["core", "extended", "admin"],
                "tool_count": 29,
                "cache_enabled": True,
                "summary": "m365-mcp 1.0.0, 29 tools.",
            },
        }
    ],
)

TIER_ORDER = {"core": 0, "extended": 1, "admin": 2}
TOOL_ORDER = [
    "m365_list", "m365_get", "m365_search", "m365_get_content", "m365_create",
    "m365_update", "m365_move", "m365_delete", "email_create_draft", "email_send",
    "email_reply", "email_forward", "calendar_create_event", "calendar_update_event",
    "calendar_respond", "calendar_find_availability", "drive_upload", "drive_copy",
    "drive_share", "email_folder_mark_all_read", "email_folder_empty",
    "email_rule_manage", "calendar_forward", "account_list", "account_auth_begin",
    "account_auth_complete", "admin_cache_get", "admin_cache_invalidate",
    "admin_server_info",
]  # fmt: skip

# ---------------------------------------------------------------------------
# Legacy mapping (all 85 tools of v0.x)
# ---------------------------------------------------------------------------

LEGACY_MAPPING: list[tuple[str, str, str]] = [
    ("account_list", "account_list", "account_type removed"),
    (
        "account_authenticate",
        "account_auth_begin",
        "opaque auth_session_id; device code stays server-side",
    ),
    (
        "account_complete_auth",
        "account_auth_complete",
        "session handle instead of flow dump; non-blocking; personal accounts only",
    ),
    ("cache_task_get_status", "admin_cache_get(view='task')", ""),
    ("cache_task_list", "admin_cache_get(view='tasks')", ""),
    ("cache_get_stats", "admin_cache_get(view='stats')", ""),
    (
        "cache_invalidate",
        "admin_cache_invalidate",
        "typed scope instead of glob pattern",
    ),
    ("cache_warming_status", "admin_cache_get(view='warming')", ""),
    (
        "calendar_list_events",
        "m365_list(resource='event', start, end)",
        "time window instead of days_ahead; recurrences expanded",
    ),
    ("calendar_get_event", "m365_get(resource='event')", ""),
    (
        "calendar_create_event",
        "calendar_create_event",
        "confirm when attendees; calendar_id, is_all_day, reminder, show_as added",
    ),
    (
        "calendar_update_event",
        "calendar_update_event",
        "typed changes; confirm when attendees affected",
    ),
    (
        "calendar_delete_event",
        "m365_delete(resource='event')",
        "organiser cancellation automatic; cancellation_message",
    ),
    ("calendar_respond_event", "calendar_respond", "confirm when a response is sent"),
    (
        "calendar_check_availability",
        "calendar_find_availability",
        "own calendar only (Graph limitation for personal accounts)",
    ),
    ("calendar_forward_event", "calendar_forward", ""),
    ("calendar_list_calendars", "m365_list(resource='calendar')", ""),
    ("calendar_create_calendar", "m365_create(resource='calendar')", ""),
    (
        "calendar_delete_calendar",
        "m365_delete(resource='calendar')",
        "default calendar refused",
    ),
    (
        "calendar_propose_new_time",
        "calendar_respond(action='tentative'|'decline', proposed_start, proposed_end)",
        "confirm when sending",
    ),
    (
        "calendar_get_free_busy",
        "calendar_find_availability",
        "own calendar only; free slots added",
    ),
    ("contact_list", "m365_list(resource='contact')", "optional contact folder"),
    ("contact_get", "m365_get(resource='contact')", ""),
    (
        "contact_create",
        "m365_create(resource='contact')",
        "more fields; optional folder",
    ),
    ("contact_update", "m365_update(resource='contact')", "typed changes"),
    ("contact_delete", "m365_delete(resource='contact')", ""),
    (
        "contact_create_list",
        "m365_create(resource='contact_folder')",
        "named contact_folder",
    ),
    (
        "contact_add_to_list",
        "m365_move(resource='contact', destination_id)",
        "real move instead of duplicate; new ID",
    ),
    ("contact_export", "m365_get_content(resource='contact', mode='vcard')", ""),
    ("emailfolders_list", "m365_list(resource='email_folder')", ""),
    ("emailfolders_get", "m365_get(resource='email_folder')", ""),
    ("emailfolders_get_tree", "m365_list(resource='email_folder', recursive=true)", ""),
    ("emailfolders_create", "m365_create(resource='email_folder')", ""),
    ("emailfolders_rename", "m365_update(resource='email_folder')", ""),
    ("emailfolders_move", "m365_move(resource='email_folder')", ""),
    (
        "emailfolders_delete",
        "m365_delete(resource='email_folder')",
        "well-known folders refused",
    ),
    (
        "emailfolders_mark_all_as_read",
        "email_folder_mark_all_read",
        "batched; bounded per call",
    ),
    ("emailfolders_empty", "email_folder_empty", "batched; bounded per call"),
    ("emailrules_list", "m365_list(resource='email_rule')", ""),
    ("emailrules_get", "m365_get(resource='email_rule')", ""),
    (
        "emailrules_create",
        "email_rule_manage(action='create')",
        "typed Graph predicate/action set; confirm for forward/redirect/delete",
    ),
    ("emailrules_update", "email_rule_manage(action='update')", "as create"),
    ("emailrules_delete", "m365_delete(resource='email_rule')", ""),
    ("emailrules_move_top", "email_rule_manage(action='reorder', position='top')", ""),
    (
        "emailrules_move_bottom",
        "email_rule_manage(action='reorder', position='bottom')",
        "",
    ),
    ("emailrules_move_up", "email_rule_manage(action='reorder', position='up')", ""),
    (
        "emailrules_move_down",
        "email_rule_manage(action='reorder', position='down')",
        "",
    ),
    (
        "email_list",
        "m365_list(resource='email')",
        "preview instead of body; filters; cursor",
    ),
    (
        "email_get",
        "m365_get(resource='email')",
        "default body cap 20k characters (was 50k)",
    ),
    ("email_create_draft", "email_create_draft", "bcc, body_format, importance"),
    ("email_send", "email_send(mode='new')", "bcc; mode='draft' added"),
    ("email_update", "m365_update(resource='email')", "typed changes"),
    ("email_delete", "m365_delete(resource='email')", ""),
    ("email_move", "m365_move(resource='email')", "returns new ID"),
    ("email_reply", "email_reply(mode='sender')", "cc and attachments added"),
    ("email_reply_all", "email_reply(mode='all')", "cc and attachments added"),
    ("email_forward", "email_forward", "bcc and attachments added"),
    (
        "email_get_attachment",
        "m365_get_content(resource='email', mode='download')",
        "no silent overwrite",
    ),
    ("email_mark_read", "m365_update(resource='email', email_changes.is_read)", ""),
    ("email_flag", "m365_update(resource='email', email_changes.flag)", ""),
    (
        "email_add_category",
        "m365_update(resource='email', email_changes.categories_add)",
        "remove/set also available",
    ),
    ("email_archive", "m365_move(resource='email', destination_id='archive')", ""),
    ("file_list", "m365_list(resource='drive_item', item_type='file')", ""),
    (
        "file_get",
        "m365_get(resource='drive_item') + m365_get_content(mode='download')",
        "details and download split",
    ),
    (
        "file_create",
        "drive_upload(parent_id|parent_path, local_path)",
        "if_exists default fail",
    ),
    ("file_update", "drive_upload(item_id, local_path)", ""),
    ("file_delete", "m365_delete(resource='drive_item')", "described as recycle bin"),
    ("file_copy", "drive_copy", "operation handle + status"),
    ("file_move", "m365_move(resource='drive_item')", ""),
    ("file_rename", "m365_update(resource='drive_item', drive_item_changes.name)", ""),
    (
        "file_share",
        "drive_share(mode='link')",
        "confirm; no default scope; invite mode added",
    ),
    (
        "file_download_url",
        "m365_get_content(resource='drive_item', mode='download_url')",
        "",
    ),
    ("folder_list", "m365_list(resource='drive_item', item_type='folder')", ""),
    ("folder_get", "m365_get(resource='drive_item')", ""),
    (
        "folder_get_tree",
        "m365_list(resource='drive_item', item_type='folder', recursive=true)",
        "",
    ),
    ("folder_create", "m365_create(resource='drive_item', drive_folder)", ""),
    ("folder_delete", "m365_delete(resource='drive_item')", "recycle bin"),
    ("folder_rename", "m365_update(resource='drive_item')", ""),
    ("folder_move", "m365_move(resource='drive_item')", ""),
    ("search_files", "m365_search(resources=['drive_item'])", ""),
    (
        "search_emails",
        "m365_search(resources=['email'])",
        "whole mailbox via server-side $search",
    ),
    ("search_events", "m365_search(resources=['event'])", "explicit window"),
    ("search_contacts", "m365_search(resources=['contact'])", ""),
    ("search_unified", "m365_search(resources=[...])", "Search API path removed"),
    ("server_get_version", "admin_server_info", ""),
]

# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def ordered_tools() -> list[dict[str, Any]]:
    by_name = {t["name"]: t for t in TOOLS}
    missing = set(by_name) ^ set(TOOL_ORDER)
    if missing:
        raise SystemExit(f"TOOL_ORDER and TOOLS disagree: {sorted(missing)}")
    return [by_name[name] for name in TOOL_ORDER]


def dump(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def esc(text: str) -> str:
    """Escape text for a Markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ")


def fmt_type(schema: Schema) -> str:
    if "enum" in schema:
        return " \\| ".join(f"`{v}`" for v in schema["enum"])
    if "anyOf" in schema:
        return " or ".join(fmt_type(s) for s in schema["anyOf"])
    if "$ref" in schema:
        return f"[{schema['$ref'].rsplit('/', 1)[1]}](#type-{schema['$ref'].rsplit('/', 1)[1]})"
    kind = schema.get("type", "any")
    if kind == "array":
        return f"array of {fmt_type(schema.get('items', {}))}"
    if kind == "string" and "format" in schema:
        return f"string ({schema['format']})"
    return str(kind)


def fmt_constraints(schema: Schema) -> str:
    parts = []
    for key, label in (
        ("minimum", "min"),
        ("maximum", "max"),
        ("minLength", "min length"),
        ("maxLength", "max length"),
        ("minItems", "min items"),
        ("maxItems", "max items"),
        ("minProperties", "min fields"),
    ):
        if key in schema:
            parts.append(f"{label} {schema[key]}")
    if schema.get("uniqueItems"):
        parts.append("unique")
    return ", ".join(parts)


def param_rows(schema: Schema, root: Schema, prefix: str = "") -> list[str]:
    """Flatten an input schema into Markdown table rows (dotted names)."""
    rows = []
    required = set(schema.get("required", []))
    for name, prop in schema.get("properties", {}).items():
        full = f"{prefix}{name}"
        target = prop
        if "$ref" in prop:
            # Resolve local $defs so shared sub-schemas are documented inline.
            target = {**root["$defs"][prop["$ref"].rsplit("/", 1)[1]], **prop}
            target.pop("$ref")
        default = f"`{json.dumps(prop['default'])}`" if "default" in prop else "—"
        desc = esc(prop.get("description", ""))
        cons = fmt_constraints(target)
        rows.append(
            f"| `{full}` | {fmt_type(target)} | {'yes' if name in required else 'no'} "
            f"| {default} | {cons or '—'} | {desc} |"
        )
        if target.get("type") == "object" and "properties" in target:
            rows.extend(param_rows(target, root, f"{full}."))
    return rows


def render_reference(tools: list[dict[str, Any]]) -> str:
    md = [
        "# Unified Tools — Schema Reference",
        "",
        (
            f"Specification version **{SPEC_VERSION}**. Generated by "
            "`scripts/build_unified_tool_specs.py` from the same source as "
            "`docs/unified-tools/tools/*.json`. **Do not edit by hand.**"
        ),
        "",
        (
            "The JSON files are the implementation source of truth: the server's "
            "`tools/list` must reproduce each file's `name`, `title`, `description`, "
            "`annotations`, `inputSchema` and `outputSchema` exactly (see "
            "docs/unified-tools/README.md)."
        ),
        "",
        "## Tools",
        "",
        "| # | Tool | Tier | Safety | Confirm | Replaces |",
        "|---|---|---|---|---|---|",
    ]
    for i, t in enumerate(tools, 1):
        md.append(
            f"| {i} | [`{t['name']}`](#{t['name']}) | {t['meta']['tier']} | "
            f"{t['meta']['safety_level']} | {t['meta']['confirm']} | "
            + ", ".join(f"`{r}`" for r in t["replaces"])
            + " |"
        )
    md.append("")
    for t in tools:
        meta = t["meta"]
        ann = t["annotations"]
        md += [
            f'<a id="{t["name"]}"></a>',
            "",
            f"## `{t['name']}` — {t['title']}",
            "",
            t["description"],
            "",
            (
                f"- **Tier:** {meta['tier']} · **Category:** {meta['category']} · "
                f"**Safety:** {meta['safety_level']}"
            ),
            f"- **Confirm:** {meta['confirm']}"
            + (f" — {meta['confirm_rule']}" if meta["confirm_rule"] else ""),
            (
                f"- **Annotations:** readOnly={str(ann['readOnlyHint']).lower()}, "
                f"destructive={str(ann['destructiveHint']).lower()}, "
                f"idempotent={str(ann['idempotentHint']).lower()}, openWorld=true"
            ),
            "",
            "### Input",
            "",
        ]
        rows = param_rows(t["inputSchema"], t["inputSchema"])
        if rows:
            md += [
                "| Parameter | Type | Required | Default | Constraints | Description |",
                "|---|---|---|---|---|---|",
                *rows,
                "",
            ]
        else:
            md += ["_No parameters._", ""]
        md += ["### Output", "", t["outputSchema"].get("description", ""), ""]
        md += [
            "| Field | Type |",
            "|---|---|",
            *[
                f"| `{k}` | {fmt_type(v)} |"
                for k, v in t["outputSchema"]["properties"].items()
            ],
            "",
        ]
        md += ["### Microsoft Graph calls", ""]
        md += [f"- {g}" for g in t["graph_calls"]] + [""]
        if t["validation_rules"]:
            md += [
                "### Server-side validation",
                "",
                "| Rule | Error returned |",
                "|---|---|",
            ]
            md += [
                f"| {esc(r['rule'])} | {esc(r['error'])} |"
                for r in t["validation_rules"]
            ]
            md.append("")
        for ex in t["examples"]:
            md += [
                f"### Example — {ex['title']}",
                "",
                "```json",
                json.dumps(
                    {"arguments": ex["input"], "structuredContent": ex["output"]},
                    indent=2,
                    ensure_ascii=False,
                ),
                "```",
                "",
            ]
    md += ["## Result types", "", "Shared output projections (`$defs`).", ""]
    for name in sorted(DEFS):
        d = DEFS[name]
        md += [
            f'<a id="type-{name}"></a>',
            "",
            f"### `{name}`",
            "",
            d.get("description", ""),
            "",
        ]
        if "properties" in d:
            md += ["| Field | Type |", "|---|---|"]
            md += [f"| `{k}` | {fmt_type(v)} |" for k, v in d["properties"].items()]
            md.append("")
        elif "propertyNames" in d:
            md += [
                "Keys: " + ", ".join(f"`{k}`" for k in d["propertyNames"]["enum"]),
                "",
            ]
    return "\n".join(md)


def build() -> dict[Path, str]:
    tools = ordered_tools()
    files: dict[Path, str] = {}
    for t in tools:
        files[OUT_DIR / "tools" / f"{t['name']}.json"] = dump(
            {"spec_version": SPEC_VERSION, **copy.deepcopy(t)}
        )
    tiers = {
        tier: [t["name"] for t in tools if t["meta"]["tier"] == tier]
        for tier in TIER_ORDER
    }
    files[OUT_DIR / "index.json"] = dump(
        {
            "spec_version": SPEC_VERSION,
            "tool_count": len(tools),
            "tool_order": [t["name"] for t in tools],
            "tiers": tiers,
            "default_toolsets": ["core", "extended"],
            "resources": GET_RESOURCES,
        }
    )
    files[OUT_DIR / "legacy_mapping.json"] = dump(
        {
            "spec_version": SPEC_VERSION,
            "legacy_tool_count": len(LEGACY_MAPPING),
            "mapping": [
                {
                    "legacy_tool": legacy,
                    "replacement": new,
                    "behaviour_change": change or None,
                }
                for legacy, new, change in LEGACY_MAPPING
            ],
        }
    )
    files[OUT_DIR / "SCHEMA_REFERENCE.md"] = render_reference(tools) + "\n"
    # Package-data copy loaded by the server (m365_mcp.tool_specs).
    for path, content in list(files.items()):
        if path.parent.name == "tools" or path.name == "index.json":
            files[PKG_DIR / path.relative_to(OUT_DIR)] = content
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description="Build unified tool specs.")
    parser.add_argument(
        "--check", action="store_true", help="Fail if outputs are stale."
    )
    args = parser.parse_args()

    files = build()
    stale = [
        path
        for path, content in files.items()
        if not path.exists() or path.read_text(encoding="utf-8") != content
    ]
    expected = set(files)
    extra = [
        p
        for tools_dir in (OUT_DIR / "tools", PKG_DIR / "tools")
        for p in sorted(tools_dir.glob("*.json"))
        if p not in expected
    ]

    if args.check:
        if stale or extra:
            for path in stale + extra:
                print(f"stale: {path.relative_to(ROOT)}")
            return 1
        print(f"Unified tool specs up to date ({len(TOOLS)} tools).")
        return 0

    for path in extra:
        path.unlink()
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    print(
        f"Wrote {len(files)} files for {len(TOOLS)} tools to "
        f"{OUT_DIR.relative_to(ROOT)} and {PKG_DIR.relative_to(ROOT)}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
