"""OneDrive handlers: the ``drive_item`` and ``operation`` resources of the
generic ``m365_*`` tools, plus ``drive_upload``, ``drive_copy`` and
``drive_share`` (tasks U3.1-U3.8, U3.17-U3.19).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
from fastmcp.exceptions import ToolError

from ...errors import GraphAPIError
from ...local_files import check_read_path, check_write_path
from ...operations import OperationStatusError, operation_store
from ...projections import project_drive_item
from ...services import drive
from ...untrusted import sanitize_text
from ...validators import ValidationError, validate_onedrive_path
from ..handlers import register_handler, register_validation_rule
from .common import (
    account,
    arg,
    check_rate,
    decode_cursor,
    encode_cursor,
    invalid,
    require_confirm,
    resource_op,
)

Record = dict[str, Any]

MIB = 1024 * 1024
OUTCOME_UNKNOWN_MOVE = "Outcome unknown: check the destination folder before retrying"
OUTCOME_UNKNOWN_DELETE = (
    "Outcome unknown: check whether the item still exists before retrying"
)
_FOLDER_REFUSED = "Invalid id: item is a folder. Expected: a file"
_INVITE_ONLY = ("recipients", "role", "message", "send_invitation", "require_sign_in")
# link_type -> (description, who can do what)
_LINK_TEXT = {
    "view": ("view-only link", "anyone with the link can open it"),
    "edit": ("edit link", "anyone with the link can open and edit it"),
    "embed": ("embed link", "anyone with the link can view it on a web page"),
}


def ambiguous_failure(exc: Exception) -> bool:
    """Return whether a failed write may still have taken effect.

    Timeouts and dropped connections after the request was sent, and 5xx
    responses other than 503 (which means "not processed"), leave the
    outcome unknown. Connection failures and 4xx responses do not.

    Args:
        exc: Exception raised by the Graph call.

    Returns:
        True when the caller must not assume the write failed.
    """
    if isinstance(exc, GraphAPIError):
        return exc.status >= 500 and exc.status != 503
    if isinstance(exc, httpx.TransportError):
        return not isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout))
    return False


def _path(args: dict[str, Any], key: str, param: str | None = None) -> str | None:
    """Return ``args[key]`` as a normalised OneDrive path, or ``None``."""
    value = args.get(key)
    return None if value is None else validate_onedrive_path(value, param or key)


def _is_folder(item: Record) -> bool:
    return "folder" in item


def _full_path(item: Record) -> str:
    """Return an item's own path, e.g. ``/Documents/Tax`` (root: ``/``)."""
    if "root" in item:
        return "/"
    record = project_drive_item(item)
    parent = record["path"] or ""
    return f"{parent.rstrip('/')}/{record['name']}"


def _where(container_id: str | None, path: str | None) -> str:
    if path is not None:
        return path
    if container_id is None or container_id == drive.ROOT_ALIAS:
        return "the OneDrive root"
    return f"folder {container_id}"


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


# ----------------------------------------------------------------------
# m365_list
# ----------------------------------------------------------------------


def _matches(item: Record, item_type: str) -> bool:
    if item_type == "all":
        return True
    return (item_type == "folder") == _is_folder(item)


@resource_op("m365_list", "drive_item")
def list_drive_items(args: dict[str, Any]) -> dict[str, Any]:
    """List a OneDrive folder, one level or as a tree to ``max_depth``."""
    tool = "m365_list"
    account_id = account(args)
    container_id = args.get("container_id")
    path = _path(args, "path")
    item_type = arg(args, tool, "item_type")
    recursive = arg(args, tool, "recursive")
    max_depth = arg(args, tool, "max_depth")
    limit = arg(args, tool, "limit")
    check_rate(account_id, "normal")
    cursor = decode_cursor(args, account_id, "drive_item")

    next_cursor = None
    if not recursive and item_type == "all":
        items, next_link = drive.list_drive_children_page(
            account_id,
            item_id=container_id,
            path=path,
            limit=limit,
            next_link=cursor.next_link if cursor else None,
        )
        records = [project_drive_item(item) for item in items]
        if next_link:
            next_cursor = encode_cursor(
                args, account_id, "drive_item", next_link=next_link
            )
    else:

        def node(item: Record, depth: int) -> Record:
            record = project_drive_item(item)
            if _is_folder(item) and depth < max_depth:
                children = drive.list_all_drive_children(account_id, item_id=item["id"])
                record["children"] = [
                    node(child, depth + 1)
                    for child in children
                    if _matches(child, item_type)
                ]
            return record

        offset = (cursor.offset or 0) if cursor else 0
        matching = [
            item
            for item in drive.list_all_drive_children(
                account_id, item_id=container_id, path=path
            )
            if _matches(item, item_type)
        ]
        page = matching[offset : offset + limit]
        records = [
            node(item, 1) if recursive else project_drive_item(item) for item in page
        ]
        if offset + limit < len(matching):
            next_cursor = encode_cursor(
                args, account_id, "drive_item", offset=offset + limit
            )

    where = _where(container_id, path)
    summary = f"Returned {_plural(len(records), 'item')} from {where}"
    if recursive:
        summary = (
            f"Returned a tree of {_plural(len(records), 'top-level item')} "
            f"from {where} (depth {max_depth})"
        )
    summary += "; more available (pass next_cursor)." if next_cursor else "."
    return {
        "resource": "drive_item",
        "items": records,
        "next_cursor": next_cursor,
        "has_more": next_cursor is not None,
        "summary": summary,
    }


# ----------------------------------------------------------------------
# m365_get
# ----------------------------------------------------------------------


@resource_op("m365_get", "drive_item")
def get_drive_item(args: dict[str, Any]) -> dict[str, Any]:
    """Read a OneDrive item by ID, ``root`` alias or path."""
    account_id = account(args)
    path = _path(args, "path")
    check_rate(account_id, "normal")
    item = drive.get_drive_item(account_id, item_id=args.get("id"), path=path)
    record = project_drive_item(item)
    where = f" in {record['path']}" if record["path"] else ""
    return {
        "resource": "drive_item",
        "item": record,
        "summary": f"OneDrive {record['item_type']} {record['name']}{where}.",
    }


@resource_op("m365_get", "operation")
def get_operation(args: dict[str, Any]) -> dict[str, Any]:
    """Report the status of a copy started with drive_copy."""
    account_id = account(args)
    check_rate(account_id, "normal")
    try:
        item = operation_store.get_status(args["id"], account_id)
    except OperationStatusError as exc:
        raise ToolError(f"m365_get failed: {exc}") from None
    if item["status"] == "completed":
        summary = "Copy completed"
        if item["resource_id"]:
            summary += f"; new item id {item['resource_id']}"
        summary += "."
    elif item["status"] == "failed":
        summary = f"Copy failed: {item['error']}"
    else:
        percent = item["percent_complete"]
        progress = f" ({percent:g}% complete)" if percent is not None else ""
        summary = f"Copy in progress{progress}; check again shortly."
    return {"resource": "operation", "item": item, "summary": summary}


# ----------------------------------------------------------------------
# m365_get_content
# ----------------------------------------------------------------------


def _require_file(item: Record) -> None:
    if _is_folder(item):
        raise ValidationError(_FOLDER_REFUSED)


@resource_op("m365_get_content", "drive_item")
def get_drive_content(args: dict[str, Any]) -> dict[str, Any]:
    """Download a OneDrive file to ``save_path`` or return a download URL."""
    tool = "m365_get_content"
    account_id = account(args)
    item_id = args["id"]
    result: dict[str, Any] = {
        "resource": "drive_item",
        "id": item_id,
        "mode": args["mode"],
        "saved_path": None,
        "size": None,
        "mime_type": None,
        "download_url": None,
        "vcard": None,
    }

    if args["mode"] == "download_url":
        check_rate(account_id, "normal")
        item = drive.get_drive_download_url(account_id, item_id)
        _require_file(item)
        record = project_drive_item(item)
        result.update(
            size=record["size"],
            mime_type=record["mime_type"],
            download_url=item.get("@microsoft.graph.downloadUrl"),
            summary=(
                f"Temporary download link for {record['name']}; it expires in "
                "about an hour and works without signing in, so treat it as a "
                "secret."
            ),
        )
        return result

    destination = check_write_path(
        args["save_path"], "save_path", overwrite=arg(args, tool, "overwrite")
    )
    check_rate(account_id, "normal")
    item = drive.get_drive_item(account_id, item_id=item_id)
    _require_file(item)
    limit_mib = drive.max_download_mib()
    if (item.get("size") or 0) > limit_mib * MIB:
        raise invalid(
            "id",
            f"the file is larger than the {limit_mib} MB download limit",
            "a smaller file, or raise MCP_FILE_DOWNLOAD_MAX_MB",
        )
    download_url = item.get("@microsoft.graph.downloadUrl")
    if not download_url:
        raise ToolError(
            f"{tool} failed: OneDrive returned no download link for this file. "
            "Try again in a minute."
        )
    size = drive.download_drive_file(download_url, destination)
    record = project_drive_item(item)
    result.update(
        saved_path=str(destination),
        size=size,
        mime_type=record["mime_type"],
        summary=f"Saved {record['name']} ({size} bytes) to {destination}.",
    )
    return result


# ----------------------------------------------------------------------
# m365_create (folders)
# ----------------------------------------------------------------------


@register_validation_rule("m365_create")
def _drive_folder_parent_rule(args: dict[str, Any]) -> None:
    folder = args.get("drive_folder") or {}
    if folder.get("parent_id") is not None and folder.get("parent_path") is not None:
        raise ValidationError("Invalid parent_path: cannot be combined with parent_id")


@resource_op("m365_create", "drive_item")
def create_drive_folder(args: dict[str, Any]) -> dict[str, Any]:
    """Create a OneDrive folder, failing or renaming on a name conflict."""
    folder = args["drive_folder"]
    account_id = account(args)
    parent_path = _path(folder, "parent_path")
    name = folder["name"]
    check_rate(account_id, "normal")
    try:
        item = drive.create_drive_folder(
            account_id,
            name,
            parent_id=folder.get("parent_id"),
            parent_path=parent_path,
            conflict=folder.get("if_exists", "fail"),
        )
    except GraphAPIError as exc:
        if exc.status == 409:
            raise ValidationError(
                f"A folder named '{name}' already exists there. "
                "Expected: another name or if_exists='rename'"
            ) from None
        raise
    record = project_drive_item(item)
    where = record["path"] or parent_path or "OneDrive"
    return {
        "resource": "drive_item",
        "item": record,
        "summary": f"Created folder {record['name']} in {where}.",
    }


# ----------------------------------------------------------------------
# m365_update (rename)
# ----------------------------------------------------------------------


@resource_op("m365_update", "drive_item")
def rename_drive_item(args: dict[str, Any]) -> dict[str, Any]:
    """Rename a OneDrive file or folder; the root is refused."""
    if args["id"] == drive.ROOT_ALIAS:
        raise ValidationError("Invalid id: the OneDrive root cannot be renamed")
    account_id = account(args)
    name = args["drive_item_changes"]["name"]
    check_rate(account_id, "normal")
    drive.patch_drive_item(account_id, args["id"], {"name": name})
    return {
        "resource": "drive_item",
        "id": args["id"],
        "status": "updated",
        "changed_fields": ["name"],
        "summary": f"Renamed OneDrive item to {name}.",
    }


# ----------------------------------------------------------------------
# m365_move
# ----------------------------------------------------------------------


def _destination_folder(
    account_id: str, args: dict[str, Any], id_key: str, path_key: str
) -> Record:
    """Read the destination folder given by ID/``root`` or path."""
    destination = drive.get_drive_item(
        account_id, item_id=args.get(id_key), path=_path(args, path_key)
    )
    if not _is_folder(destination):
        raise invalid(id_key, "not a folder", "a folder ID or 'root'")
    return destination


@resource_op("m365_move", "drive_item")
def move_drive_item(args: dict[str, Any]) -> dict[str, Any]:
    """Move (and optionally rename) a OneDrive item via ``parentReference``."""
    account_id = account(args)
    item_id = args["id"]
    check_rate(account_id, "normal")
    source = drive.get_drive_item(account_id, item_id=item_id)
    destination = _destination_folder(
        account_id, args, "destination_id", "destination_path"
    )
    if _is_folder(source):
        source_path = _full_path(source).lower()
        target_path = _full_path(destination).lower()
        if destination["id"] == source["id"] or target_path.startswith(
            source_path.rstrip("/") + "/"
        ):
            raise ValidationError(
                "Invalid destination_id: is inside the folder being moved"
            )

    body: dict[str, Any] = {"parentReference": {"id": destination["id"]}}
    if args.get("new_name") is not None:
        body["name"] = args["new_name"]
    try:
        moved = drive.patch_drive_item(account_id, item_id, body)
    except (GraphAPIError, httpx.TransportError) as exc:
        if ambiguous_failure(exc):
            raise ToolError(OUTCOME_UNKNOWN_MOVE) from None
        raise
    name = project_drive_item(moved)["name"] if moved.get("id") else item_id
    return {
        "resource": "drive_item",
        "previous_id": item_id,
        "id": moved.get("id") or item_id,
        "status": "moved",
        "destination_id": destination["id"],
        "summary": f"Moved {name} to {_full_path(destination)}.",
    }


# ----------------------------------------------------------------------
# m365_delete
# ----------------------------------------------------------------------

_ROOT_DELETE = "Invalid id: the OneDrive root cannot be deleted"


@resource_op("m365_delete", "drive_item")
def delete_drive_item(args: dict[str, Any]) -> dict[str, Any]:
    """Delete a OneDrive item into the recycle bin; the root is refused."""
    item_id = args["id"]
    if item_id == drive.ROOT_ALIAS:
        raise ValidationError(_ROOT_DELETE)
    account_id = account(args)
    check_rate(account_id, "sensitive")
    item = drive.get_drive_item(account_id, item_id=item_id)
    if "root" in item:
        raise ValidationError(_ROOT_DELETE)
    try:
        drive.delete_drive_item(account_id, item_id)
    except (GraphAPIError, httpx.TransportError) as exc:
        if ambiguous_failure(exc):
            raise ToolError(OUTCOME_UNKNOWN_DELETE) from None
        raise
    name = project_drive_item(item)["name"]
    return {
        "resource": "drive_item",
        "id": item_id,
        "status": "deleted",
        "recoverable": True,
        "summary": f"Moved '{name}' to the OneDrive recycle bin.",
    }


# ----------------------------------------------------------------------
# drive_upload
# ----------------------------------------------------------------------


@register_validation_rule("drive_upload")
def _upload_rules(args: dict[str, Any]) -> None:
    has_item = args.get("item_id") is not None
    has_parent_id = args.get("parent_id") is not None
    has_parent_path = args.get("parent_path") is not None
    if has_item and (has_parent_id or has_parent_path):
        raise ValidationError(
            "Invalid item_id: cannot be combined with parent_id or parent_path"
        )
    if has_parent_id and has_parent_path:
        raise ValidationError("Invalid parent_path: cannot be combined with parent_id")
    if not (has_item or has_parent_id or has_parent_path):
        raise invalid("parent_id", "required", "parent_id, parent_path or item_id")
    if has_item and args.get("name") is not None:
        raise invalid(
            "name",
            "only valid for a new file",
            "remove name, or use parent_id or parent_path",
        )
    check_read_path(args["local_path"], "local_path")


@register_handler("drive_upload")
def drive_upload(args: dict[str, Any]) -> dict[str, Any]:
    """Upload a local file as a new OneDrive file or over an existing one."""
    account_id = account(args)
    local = check_read_path(args["local_path"], "local_path")
    check_rate(account_id, "normal")

    if args.get("item_id") is not None:
        _code, item = drive.upload_drive_file(
            account_id, local, item_id=args["item_id"]
        )
        record = project_drive_item(item)
        return {
            "item": record,
            "status": "replaced",
            "summary": f"Replaced the contents of {record['name']}.",
        }

    parent_id = args.get("parent_id")
    parent_path = _path(args, "parent_path")
    if parent_path is not None:
        parent = drive.get_drive_item(account_id, path=parent_path)
        if not _is_folder(parent):
            raise invalid("parent_path", "not a folder", "a OneDrive folder path")
        parent_id = parent["id"]
    name = args.get("name") or Path(local).name
    try:
        code, item = drive.upload_drive_file(
            account_id,
            local,
            parent_id=parent_id,
            name=name,
            conflict=arg(args, "drive_upload", "if_exists"),
        )
    except GraphAPIError as exc:
        if exc.status == 409:
            raise ValidationError(
                f"A file named '{name}' already exists there. "
                "Expected: if_exists='replace' or 'rename'"
            ) from None
        raise
    record = project_drive_item(item)
    where = record["path"] or parent_path or "OneDrive"
    if record["name"] != name:
        status = "renamed"
        summary = (
            f"Uploaded {name} to {where} as {record['name']} (the name was taken)."
        )
    elif code == 200:
        status = "replaced"
        summary = f"Uploaded {name} to {where}, replacing the existing file."
    else:
        status = "created"
        summary = f"Uploaded {name} to {where}."
    return {"item": record, "status": status, "summary": summary}


# ----------------------------------------------------------------------
# drive_copy
# ----------------------------------------------------------------------


@register_validation_rule("drive_copy")
def _copy_rules(args: dict[str, Any]) -> None:
    has_id = args.get("destination_id") is not None
    has_path = args.get("destination_path") is not None
    if has_id and has_path:
        raise invalid("destination_path", "cannot be combined with destination_id")
    if not has_id and not has_path:
        raise invalid("destination_id", "required")


@register_handler("drive_copy")
def drive_copy(args: dict[str, Any]) -> dict[str, Any]:
    """Start a background copy and return its operation handle."""
    account_id = account(args)
    check_rate(account_id, "normal")
    destination = _destination_folder(
        account_id, args, "destination_id", "destination_path"
    )
    parent_reference: dict[str, Any] = {"id": destination["id"]}
    drive_id = (destination.get("parentReference") or {}).get("driveId")
    if drive_id:
        parent_reference["driveId"] = drive_id
    monitor_url = drive.start_drive_copy(
        account_id, args["item_id"], parent_reference, args.get("new_name")
    )
    operation_id = operation_store.record(monitor_url, account_id)
    return {
        "operation_id": operation_id,
        "status": "in_progress",
        "summary": (
            "Copy started; check with "
            f"m365_get(resource='operation', id='{operation_id}')."
        ),
    }


# ----------------------------------------------------------------------
# drive_share
# ----------------------------------------------------------------------

_ROOT_SHARE = "Invalid item_id: the OneDrive root cannot be shared"
_NOT_GRANTED = "Microsoft 365 did not grant access"


@register_validation_rule("drive_share")
def _share_rules(args: dict[str, Any]) -> None:
    if args["mode"] == "link":
        for field in _INVITE_ONLY:
            if args.get(field) is not None:
                raise invalid(field, "only valid with mode='invite'")
        if args.get("link_type") is None:
            raise invalid("link_type", "required when mode='link'")
    else:
        if args.get("link_type") is not None:
            raise invalid("link_type", "only valid with mode='link'")
        for field in ("recipients", "role"):
            if args.get(field) is None:
                raise invalid(field, "required when mode='invite'")
    if args["item_id"] == drive.ROOT_ALIAS:
        raise ValidationError(_ROOT_SHARE)


def _invite_results(
    recipients: list[str], entries: list[Record]
) -> list[dict[str, Any]]:
    """Map Graph invite entries (permissions or errors) to recipients."""
    if len(entries) != len(recipients):
        by_email: dict[str, Record] = {}
        for entry in entries:
            email = (entry.get("invitation") or {}).get("email") or (
                (entry.get("grantedTo") or {}).get("user") or {}
            ).get("email")
            if email:
                by_email[email.lower()] = entry
        entries = [by_email.get(r.lower(), {"error": {}}) for r in recipients]
    results = []
    for email, entry in zip(recipients, entries, strict=True):
        error = entry.get("error")
        if error is None and entry.get("id"):
            results.append({"email": email, "status": "granted", "error": None})
            continue
        message = (error or {}).get("message") or _NOT_GRANTED
        results.append(
            {"email": email, "status": "failed", "error": sanitize_text(message)}
        )
    return results


@register_handler("drive_share")
def drive_share(args: dict[str, Any]) -> dict[str, Any]:
    """Share a OneDrive item by anonymous link or by inviting people."""
    tool = "drive_share"
    account_id = account(args)
    item_id = args["item_id"]
    check_rate(account_id, "normal")
    item = drive.get_drive_item(account_id, item_id=item_id)
    if "root" in item:
        raise ValidationError(_ROOT_SHARE)
    if args.get("link_type") == "embed" and _is_folder(item):
        raise ValidationError("Invalid link_type 'embed': only files can be embedded")
    require_confirm(args, "sharing")
    check_rate(account_id, "sensitive")
    name = project_drive_item(item)["name"]

    options: dict[str, Any] = {}
    if args.get("password") is not None:
        options["password"] = args["password"]
    if args.get("expires_at") is not None:
        options["expirationDateTime"] = args["expires_at"]

    if args["mode"] == "link":
        link_type = args["link_type"]
        body = {"type": link_type, "scope": "anonymous", **options}
        created, permission = drive.create_drive_link(account_id, item_id, body)
        label, reach = _LINK_TEXT[link_type]
        if created:
            article = "an" if label[0] in "aeiou" else "a"
            summary = f"Created {article} {label} to {name} ({reach})."
        else:
            summary = f"Returned the existing {label} to {name} ({reach})."
        return {
            "mode": "link",
            "permission_ids": [permission["id"]] if permission.get("id") else [],
            "link_url": (permission.get("link") or {}).get("webUrl"),
            "created": created,
            "recipients": [],
            "summary": summary,
        }

    recipients = list(args["recipients"])
    body = {
        "recipients": [{"email": email} for email in recipients],
        "roles": [args["role"]],
    }
    if args.get("message") is not None:
        body["message"] = args["message"]
    body["sendInvitation"] = arg(args, tool, "send_invitation")
    body["requireSignIn"] = arg(args, tool, "require_sign_in")
    body.update(options)
    entries = drive.invite_drive_recipients(account_id, item_id, body)
    results = _invite_results(recipients, entries)
    granted = [r for r in results if r["status"] == "granted"]
    permission_ids = [
        entry["id"]
        for entry in entries
        if entry.get("id") and entry.get("error") is None
    ]
    people = "person" if len(results) == 1 else "people"
    summary = (
        f"Shared {name} with {len(granted)} of {len(results)} {people} "
        f"({args['role']} access)"
    )
    failed = len(results) - len(granted)
    summary += f"; {failed} failed." if failed else "."
    return {
        "mode": "invite",
        "permission_ids": permission_ids,
        "link_url": None,
        "created": None,
        "recipients": results,
        "summary": summary,
    }
