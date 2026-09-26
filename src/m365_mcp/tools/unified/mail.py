"""Mail resources of the generic ``m365_*`` tools (U3.1-U3.8, mail parts).

Registers the per-resource functions for ``email``, ``email_folder`` and
``email_rule``: list, get, get_content (attachments), create (folders),
update, move and delete. Graph access goes through ``services.mail``,
``services.mail_folders`` and ``services.mail_rules``; results use the
projections in ``projections.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

import httpx
from fastmcp.exceptions import ToolError

from ...errors import GraphAPIError
from ...local_files import check_write_path, sanitize_file_name
from ...projections import (
    project_email_detail,
    project_email_folder,
    project_email_rule,
    project_email_summary,
)
from ...services import mail, mail_folders, mail_rules
from ...untrusted import sanitize_text
from ...validators import ValidationError
from ..handlers import register_validation_rule
from .common import (
    account,
    arg,
    check_rate,
    decode_cursor,
    encode_cursor,
    invalid,
    is_well_known_mail_folder,
    resolve_mail_folder,
    resource_op,
)

_T = TypeVar("_T")

MOVE_UNKNOWN = "Outcome unknown: check the destination folder before retrying"
DELETE_UNKNOWN = "Outcome unknown: check whether the item still exists before retrying"

ROOT_FOLDER = "msgfolderroot"
# Earliest receivedDateTime, used when a $filter has no date clause: Graph
# requires the $orderby property to lead the $filter.
_ALL_TIME = "receivedDateTime ge 1900-01-01T00:00:00Z"
_MAX_ANCESTORS = 32

# Display names of the well-known folders, for summaries.
_FOLDER_NAMES = {
    "inbox": "Inbox",
    "sentitems": "Sent Items",
    "drafts": "Drafts",
    "deleteditems": "Deleted Items",
    "junkemail": "Junk Email",
    "archive": "Archive",
    ROOT_FOLDER: "the top level",
}
_FLAG_TO_GRAPH = {
    "not_flagged": "notFlagged",
    "flagged": "flagged",
    "complete": "complete",
}


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------


def plural(count: int, noun: str) -> str:
    """Return ``'<count> <noun>'`` with an ``s`` unless count is 1."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _utc(value: str) -> str:
    """Format an RFC 3339 date-time as a Graph UTC literal."""
    return _parse(value).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _graph_datetime(value: str) -> dict[str, str]:
    """Build a Graph dateTimeTimeZone in UTC."""
    moment = _parse(value).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    return {"dateTime": moment, "timeZone": "UTC"}


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _folder_name(folder: str) -> str:
    return _FOLDER_NAMES.get(folder, f"folder {folder}")


def _is_ambiguous(exc: Exception) -> bool:
    """Return whether a failed write may still have taken effect.

    Connection failures never reached Graph, and 503 means the request was
    not processed. Timeouts, dropped connections and other 5xx responses
    can arrive after Graph acted.
    """
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return False
    if isinstance(exc, httpx.TransportError):
        return True
    return isinstance(exc, GraphAPIError) and exc.status >= 500 and exc.status != 503


def _write(action: Callable[[], _T], unknown: str) -> _T:
    """Run a write once; report an ambiguous failure as outcome unknown."""
    try:
        return action()
    except Exception as exc:
        if _is_ambiguous(exc):
            raise ToolError(unknown) from exc
        raise


def _parent_folder(value: str | None, param: str) -> str | None:
    """Resolve a parent folder; the top level (``root``) becomes ``None``."""
    if value is None:
        return None
    folder = resolve_mail_folder(value, param)
    return None if folder == ROOT_FOLDER else folder


def _offset_page(
    args: dict[str, Any], account_id: str, resource: str, records: list[Any]
) -> tuple[list[Any], str | None]:
    """Slice ``records`` for this page and build the offset cursor."""
    cursor = decode_cursor(args, account_id, resource)
    offset = cursor.offset if cursor is not None and cursor.offset else 0
    limit = arg(args, "m365_list", "limit")
    end = offset + limit
    next_cursor = (
        encode_cursor(args, account_id, resource, offset=end)
        if end < len(records)
        else None
    )
    return records[offset:end], next_cursor


def _list_result(
    resource: str, items: list[Any], next_cursor: str | None, summary: str
) -> dict[str, Any]:
    if next_cursor:
        summary += "; more available (pass next_cursor)."
    else:
        summary += "."
    return {
        "resource": resource,
        "items": items,
        "next_cursor": next_cursor,
        "has_more": next_cursor is not None,
        "summary": summary,
    }


# ----------------------------------------------------------------------
# validation rules
# ----------------------------------------------------------------------


@register_validation_rule("m365_list")
def _received_window(args: dict[str, Any]) -> None:
    """received_before must be after received_after."""
    if args.get("resource") != "email":
        return
    email_filter = args.get("email_filter") or {}
    after = email_filter.get("received_after")
    before = email_filter.get("received_before")
    if after and before and _parse(before) <= _parse(after):
        raise invalid("received_before", "must be after received_after")


@register_validation_rule("m365_update")
def _categories_exclusive(args: dict[str, Any]) -> None:
    """categories_set cannot be combined with categories_add/remove."""
    changes = args.get("email_changes") or {}
    if "categories_set" in changes and (
        "categories_add" in changes or "categories_remove" in changes
    ):
        raise invalid(
            "categories_set",
            "cannot be combined with categories_add or categories_remove",
        )


# ----------------------------------------------------------------------
# m365_list
# ----------------------------------------------------------------------


def email_filter_expression(email_filter: dict[str, Any] | None) -> str | None:
    """Build the Graph ``$filter`` for an ``email_filter`` object.

    Graph rejects a ``$filter`` combined with ``$orderby`` unless the
    ordered property (``receivedDateTime``) comes first, so a date clause
    always leads; without date filters an all-time clause is added.

    Args:
        email_filter: The schema-validated ``email_filter`` argument.

    Returns:
        The ``$filter`` expression, or ``None`` when there is no filter.
    """
    if not email_filter:
        return None
    dates: list[str] = []
    if "received_after" in email_filter:
        dates.append(f"receivedDateTime ge {_utc(email_filter['received_after'])}")
    if "received_before" in email_filter:
        dates.append(f"receivedDateTime lt {_utc(email_filter['received_before'])}")
    clauses = dates or [_ALL_TIME]
    if "unread" in email_filter:
        clauses.append(f"isRead eq {'false' if email_filter['unread'] else 'true'}")
    if "from" in email_filter:
        clauses.append(f"from/emailAddress/address eq {_quote(email_filter['from'])}")
    if "has_attachments" in email_filter:
        value = "true" if email_filter["has_attachments"] else "false"
        clauses.append(f"hasAttachments eq {value}")
    if "importance" in email_filter:
        clauses.append(f"importance eq {_quote(email_filter['importance'])}")
    if "flagged" in email_filter:
        op = "eq" if email_filter["flagged"] else "ne"
        clauses.append(f"flag/flagStatus {op} 'flagged'")
    if "category" in email_filter:
        clauses.append(f"categories/any(c:c eq {_quote(email_filter['category'])})")
    return " and ".join(clauses)


@resource_op("m365_list", "email")
def list_email(args: dict[str, Any]) -> dict[str, Any]:
    """List one page of emails in a folder, newest first."""
    account_id = account(args)
    folder = resolve_mail_folder(args.get("container_id"), "container_id")
    cursor = decode_cursor(args, account_id, "email")
    check_rate(account_id, "normal")
    messages, next_link = mail.list_messages_page(
        account_id,
        folder_id=folder,
        top=arg(args, "m365_list", "limit"),
        filter_expr=email_filter_expression(args.get("email_filter")),
        next_link=cursor.next_link if cursor is not None else None,
    )
    items = [project_email_summary(m) for m in messages]
    next_cursor = (
        encode_cursor(args, account_id, "email", next_link=next_link)
        if next_link
        else None
    )
    label = args.get("container_id") or "inbox"
    summary = f"Returned {plural(len(items), 'email')} from {label}"
    return _list_result("email", items, next_cursor, summary)


def _folder_tree(
    account_id: str,
    folder: dict[str, Any],
    depth: int,
    max_depth: int,
    include_hidden: bool,
) -> dict[str, Any]:
    """Project a folder with its subfolders down to ``max_depth``.

    ``children`` is ``[]`` for folders without subfolders and ``None``
    for folders at the depth limit whose subfolders were not read.
    """
    record = project_email_folder(folder)
    if not folder.get("childFolderCount"):
        record["children"] = []
    elif depth < max_depth:
        children = mail_folders.list_folders(
            account_id,
            parent_folder_id=folder["id"],
            include_hidden=include_hidden,
        )
        record["children"] = [
            _folder_tree(account_id, child, depth + 1, max_depth, include_hidden)
            for child in children
        ]
    return record


@resource_op("m365_list", "email_folder")
def list_email_folders(args: dict[str, Any]) -> dict[str, Any]:
    """List mail folders one level deep or as a tree."""
    account_id = account(args)
    parent = _parent_folder(args.get("container_id"), "container_id")
    include_hidden = bool(arg(args, "m365_list", "include_hidden"))
    check_rate(account_id, "normal")
    where = f" in {args['container_id']}" if parent else " at the top level"

    if not arg(args, "m365_list", "recursive"):
        cursor = decode_cursor(args, account_id, "email_folder")
        folders, next_link = mail_folders.list_folders_page(
            account_id,
            parent_folder_id=parent,
            include_hidden=include_hidden,
            top=arg(args, "m365_list", "limit"),
            next_link=cursor.next_link if cursor is not None else None,
        )
        items = [project_email_folder(f) for f in folders]
        next_cursor = (
            encode_cursor(args, account_id, "email_folder", next_link=next_link)
            if next_link
            else None
        )
        summary = f"Returned {plural(len(items), 'mail folder')}{where}"
        return _list_result("email_folder", items, next_cursor, summary)

    max_depth = arg(args, "m365_list", "max_depth")
    top_level = mail_folders.list_folders(
        account_id, parent_folder_id=parent, include_hidden=include_hidden
    )
    page, next_cursor = _offset_page(args, account_id, "email_folder", top_level)
    items = [
        _folder_tree(account_id, folder, 1, max_depth, include_hidden)
        for folder in page
    ]
    summary = (
        f"Returned {plural(len(items), 'mail folder')}{where} "
        f"with subfolders to depth {max_depth}"
    )
    return _list_result("email_folder", items, next_cursor, summary)


@resource_op("m365_list", "email_rule")
def list_email_rules(args: dict[str, Any]) -> dict[str, Any]:
    """List the Inbox rules in run order."""
    account_id = account(args)
    check_rate(account_id, "normal")
    rules = [project_email_rule(r) for r in mail_rules.list_rules(account_id)]
    items, next_cursor = _offset_page(args, account_id, "email_rule", rules)
    summary = f"Returned {plural(len(items), 'inbox rule')}"
    return _list_result("email_rule", items, next_cursor, summary)


# ----------------------------------------------------------------------
# m365_get
# ----------------------------------------------------------------------


@resource_op("m365_get", "email")
def get_email(args: dict[str, Any]) -> dict[str, Any]:
    """Get one email with its body and attachment metadata."""
    account_id = account(args)
    check_rate(account_id, "normal")
    message = mail.get_message_detail(account_id, message_id=args["id"])
    item = project_email_detail(
        message,
        include_body=bool(arg(args, "m365_get", "include_body")),
        body_max_chars=arg(args, "m365_get", "body_max_chars"),
    )
    sender = (item["from"] or {}).get("address") or "an unknown sender"
    summary = (
        f"Returned email from {sender} with "
        f"{plural(len(item['attachments']), 'attachment')}"
    )
    if item["body_truncated"]:
        summary += "; body truncated"
    return {"resource": "email", "item": item, "summary": summary + "."}


@resource_op("m365_get", "email_folder")
def get_email_folder(args: dict[str, Any]) -> dict[str, Any]:
    """Get one mail folder by ID or alias."""
    account_id = account(args)
    folder_id = resolve_mail_folder(args["id"], "id")
    check_rate(account_id, "normal")
    item = project_email_folder(
        mail_folders.get_folder(account_id, folder_id=folder_id)
    )
    summary = (
        f"Mail folder '{item['display_name']}': {item['unread_count']} unread "
        f"of {item['total_count']}."
    )
    return {"resource": "email_folder", "item": item, "summary": summary}


@resource_op("m365_get", "email_rule")
def get_email_rule(args: dict[str, Any]) -> dict[str, Any]:
    """Get one Inbox rule."""
    account_id = account(args)
    check_rate(account_id, "normal")
    item = project_email_rule(mail_rules.get_rule(account_id, rule_id=args["id"]))
    state = "enabled" if item["is_enabled"] else "disabled"
    summary = f"Inbox rule '{item['display_name']}' ({state})."
    return {"resource": "email_rule", "item": item, "summary": summary}


# ----------------------------------------------------------------------
# m365_get_content
# ----------------------------------------------------------------------


@resource_op("m365_get_content", "email")
def download_email_attachment(args: dict[str, Any]) -> dict[str, Any]:
    """Save one email attachment to a local file.

    A ``save_path`` that is an existing folder receives the attachment
    under its sanitised name; otherwise the final path component is
    sanitised. The path must pass the ``local_files`` checks.
    """
    account_id = account(args)
    overwrite = bool(arg(args, "m365_get_content", "overwrite"))
    requested = Path(args["save_path"]).expanduser()
    if not requested.is_absolute():
        requested = Path.cwd() / requested
    into_folder = requested.is_dir()
    if not into_folder:
        safe_name = requested.with_name(sanitize_file_name(requested.name))
        requested = check_write_path(safe_name, "save_path", overwrite)

    check_rate(account_id, "normal")
    meta, content = mail.get_file_attachment(
        account_id, message_id=args["id"], attachment_id=args["attachment_id"]
    )
    name = sanitize_file_name(meta.get("name") or "")
    target = (
        check_write_path(requested / name, "save_path", overwrite)
        if into_folder
        else requested
    )
    with target.open("wb" if overwrite else "xb") as handle:
        handle.write(content)
    return {
        "resource": "email",
        "id": args["id"],
        "mode": "download",
        "saved_path": str(target),
        "size": len(content),
        "mime_type": meta.get("contentType"),
        "download_url": None,
        "vcard": None,
        "summary": (
            f"Saved attachment '{sanitize_text(name)}' "
            f"({plural(len(content), 'byte')}) to {target}."
        ),
    }


# ----------------------------------------------------------------------
# m365_create
# ----------------------------------------------------------------------


@resource_op("m365_create", "email_folder")
def create_email_folder(args: dict[str, Any]) -> dict[str, Any]:
    """Create a mail folder at the top level or under a parent."""
    account_id = account(args)
    spec = args["email_folder"]
    parent = _parent_folder(spec.get("parent_id"), "parent_id")
    check_rate(account_id, "normal")
    folder = mail_folders.create_folder(
        account_id, display_name=spec["display_name"], parent_folder_id=parent
    )
    item = project_email_folder(folder)
    return {
        "resource": "email_folder",
        "item": item,
        "summary": f"Created mail folder '{item['display_name']}'.",
    }


# ----------------------------------------------------------------------
# m365_update
# ----------------------------------------------------------------------


def _updated(resource: str, item_id: str, fields: list[str], noun: str) -> dict:
    return {
        "resource": resource,
        "id": item_id,
        "status": "updated",
        "changed_fields": fields,
        "summary": f"Updated {noun}: {', '.join(fields)}.",
    }


def _new_categories(
    account_id: str, message_id: str, changes: dict[str, Any]
) -> list[str]:
    """Compute the category list after set, or add/remove on the current."""
    if "categories_set" in changes:
        return list(changes["categories_set"])
    current = mail.get_message_categories(account_id, message_id=message_id)
    removed = {name.casefold() for name in changes.get("categories_remove", [])}
    result = [name for name in current if name.casefold() not in removed]
    for name in changes.get("categories_add", []):
        if name.casefold() not in {c.casefold() for c in result}:
            result.append(name)
    return result


@resource_op("m365_update", "email")
def update_email(args: dict[str, Any]) -> dict[str, Any]:
    """Apply typed changes to one email in a single PATCH."""
    account_id = account(args)
    message_id = args["id"]
    changes = args["email_changes"]
    check_rate(account_id, "normal")
    body: dict[str, Any] = {}
    fields: list[str] = []
    if "is_read" in changes:
        body["isRead"] = changes["is_read"]
        fields.append("is_read")
    if "flag" in changes:
        flag = changes["flag"]
        graph_flag: dict[str, Any] = {"flagStatus": _FLAG_TO_GRAPH[flag["status"]]}
        if "start_at" in flag:
            graph_flag["startDateTime"] = _graph_datetime(flag["start_at"])
        if "due_at" in flag:
            graph_flag["dueDateTime"] = _graph_datetime(flag["due_at"])
        body["flag"] = graph_flag
        fields.append("flag")
    if "importance" in changes:
        body["importance"] = changes["importance"]
        fields.append("importance")
    if {"categories_set", "categories_add", "categories_remove"} & changes.keys():
        body["categories"] = _new_categories(account_id, message_id, changes)
        fields.append("categories")
    if "inference_classification" in changes:
        body["inferenceClassification"] = changes["inference_classification"]
        fields.append("inference_classification")
    mail.patch_message(account_id, message_id=message_id, changes=body)
    return _updated("email", message_id, fields, "email")


@resource_op("m365_update", "email_folder")
def rename_email_folder(args: dict[str, Any]) -> dict[str, Any]:
    """Rename a mail folder; well-known folders are refused."""
    folder_id = args["id"]
    if is_well_known_mail_folder(folder_id):
        raise ValidationError(f"Invalid id: {folder_id} cannot be renamed")
    account_id = account(args)
    check_rate(account_id, "normal")
    mail_folders.rename_folder(
        account_id,
        folder_id=folder_id,
        new_display_name=args["email_folder_changes"]["display_name"],
    )
    return _updated("email_folder", folder_id, ["display_name"], "mail folder")


# ----------------------------------------------------------------------
# m365_move
# ----------------------------------------------------------------------


@resource_op("m365_move", "email")
def move_email(args: dict[str, Any]) -> dict[str, Any]:
    """Move an email; the moved email has a new ID."""
    account_id = account(args)
    destination = resolve_mail_folder(args["destination_id"], "destination_id")
    check_rate(account_id, "normal")
    moved = _write(
        lambda: mail.move_message_to(
            account_id, message_id=args["id"], destination_id=destination
        ),
        MOVE_UNKNOWN,
    )
    new_id = moved["id"]
    return {
        "resource": "email",
        "previous_id": args["id"],
        "id": new_id,
        "status": "moved",
        "destination_id": moved.get("parentFolderId") or destination,
        "summary": f"Moved email to {_folder_name(destination)} (new id {new_id}).",
    }


def _refuse_move_into_itself(account_id: str, source_id: str, destination: str) -> None:
    """Refuse a destination that is the folder or one of its subfolders."""
    inside = invalid("destination_id", "is inside the folder being moved")
    root_id = mail_folders.get_folder(account_id, folder_id=ROOT_FOLDER)["id"]
    current = mail_folders.get_folder(account_id, folder_id=destination)
    for _ in range(_MAX_ANCESTORS):
        if current["id"] == source_id:
            raise inside
        parent = current.get("parentFolderId")
        if not parent or parent in (root_id, ROOT_FOLDER):
            return
        current = mail_folders.get_folder(account_id, folder_id=parent)


@resource_op("m365_move", "email_folder")
def move_email_folder(args: dict[str, Any]) -> dict[str, Any]:
    """Move a mail folder under another folder or to the top level."""
    folder_id = args["id"]
    raw_destination = args["destination_id"]
    destination = resolve_mail_folder(raw_destination, "destination_id")
    if raw_destination == folder_id:
        raise invalid("destination_id", "is inside the folder being moved")
    account_id = account(args)
    check_rate(account_id, "normal")
    source = mail_folders.get_folder(account_id, folder_id=folder_id)
    if destination != ROOT_FOLDER:
        _refuse_move_into_itself(account_id, source["id"], destination)
    moved = _write(
        lambda: mail_folders.move_folder_to(
            account_id, folder_id=folder_id, destination_id=destination
        ),
        MOVE_UNKNOWN,
    )
    name = moved.get("displayName") or source.get("displayName") or folder_id
    return {
        "resource": "email_folder",
        "previous_id": folder_id,
        "id": moved["id"],
        "status": "moved",
        "destination_id": moved.get("parentFolderId") or destination,
        "summary": f"Moved mail folder '{name}' to {_folder_name(destination)}.",
    }


# ----------------------------------------------------------------------
# m365_delete
# ----------------------------------------------------------------------


def _deleted(resource: str, item_id: str, summary: str) -> dict[str, Any]:
    return {
        "resource": resource,
        "id": item_id,
        "status": "deleted",
        "recoverable": False,
        "summary": summary,
    }


@resource_op("m365_delete", "email")
def delete_email(args: dict[str, Any]) -> dict[str, Any]:
    """Delete one email."""
    account_id = account(args)
    check_rate(account_id, "sensitive")
    _write(
        lambda: mail.remove_message(account_id, message_id=args["id"]),
        DELETE_UNKNOWN,
    )
    return _deleted("email", args["id"], "Deleted the email.")


@resource_op("m365_delete", "email_folder")
def delete_email_folder(args: dict[str, Any]) -> dict[str, Any]:
    """Delete a mail folder and its contents; well-known folders refused."""
    folder_id = args["id"]
    if is_well_known_mail_folder(folder_id):
        raise ValidationError(f"Invalid id: {folder_id} cannot be deleted")
    account_id = account(args)
    check_rate(account_id, "sensitive")
    _write(
        lambda: mail_folders.delete_folder(account_id, folder_id=folder_id),
        DELETE_UNKNOWN,
    )
    return _deleted(
        "email_folder", folder_id, "Deleted the mail folder and its contents."
    )


@resource_op("m365_delete", "email_rule")
def delete_email_rule(args: dict[str, Any]) -> dict[str, Any]:
    """Delete one Inbox rule."""
    account_id = account(args)
    check_rate(account_id, "sensitive")
    _write(
        lambda: mail_rules.delete_rule(account_id, rule_id=args["id"]),
        DELETE_UNKNOWN,
    )
    return _deleted("email_rule", args["id"], "Deleted the inbox rule.")
