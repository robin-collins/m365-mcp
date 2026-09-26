"""Bounded bulk mail folder tools (U3.20, U3.21).

``email_folder_mark_all_read`` and ``email_folder_empty`` page the IDs of
the folder's messages (at most ``max_messages``), then PATCH or DELETE
them through Graph JSON batching, 20 requests per ``$batch`` call. The
result says how many messages are left so the caller can call again.
"""

from __future__ import annotations

from typing import Any

from ...services import mail, mail_folders
from ...validators import ValidationError
from ..handlers import register_handler, register_validation_rule
from .common import account, arg, check_rate, require_confirm, resolve_mail_folder
from .mail import plural

MARK_ALL_READ = "email_folder_mark_all_read"
EMPTY = "email_folder_empty"


def _mark_all_read_folder(args: dict[str, Any]) -> str:
    """Resolve ``folder_id`` with the spec's alias error text."""
    try:
        return resolve_mail_folder(args["folder_id"], "folder_id")
    except ValidationError:
        raise ValidationError(
            f"Invalid folder_id '{args['folder_id']}': unknown folder alias"
        ) from None


@register_validation_rule(MARK_ALL_READ)
def _known_alias(args: dict[str, Any]) -> None:
    """Unknown aliases are rejected."""
    _mark_all_read_folder(args)


@register_validation_rule(EMPTY)
def _confirm_empty(args: dict[str, Any]) -> None:
    """confirm must be true."""
    require_confirm(args, "empty folder")


@register_handler(MARK_ALL_READ)
def mark_all_read(args: dict[str, Any]) -> dict[str, Any]:
    """Mark up to ``max_messages`` unread messages in a folder as read."""
    account_id = account(args)
    folder_id = _mark_all_read_folder(args)
    check_rate(account_id, "normal")
    folder = mail_folders.get_folder(account_id, folder_id=folder_id)
    ids, total = mail.list_message_ids(
        account_id,
        folder_id=folder_id,
        max_items=arg(args, MARK_ALL_READ, "max_messages"),
        unread_only=True,
    )
    marked = mail.mark_messages_read(account_id, message_ids=ids)
    if total is None:
        total = max(folder.get("unreadItemCount") or 0, len(ids))
    remaining = max(total - marked, 0)

    name = folder.get("displayName") or folder["id"]
    if not ids:
        summary = f"No unread messages in {name}."
    elif remaining:
        summary = (
            f"Marked {plural(marked, 'message')} read in {name}; "
            f"{remaining} still unread (call again)."
        )
    else:
        summary = f"Marked {plural(marked, 'message')} read in {name}."
    return {
        "folder_id": folder["id"],
        "marked": marked,
        "remaining_unread": remaining,
        "summary": summary,
    }


@register_handler(EMPTY)
def empty_folder(args: dict[str, Any]) -> dict[str, Any]:
    """Delete up to ``max_messages`` messages from a folder; keep subfolders."""
    account_id = account(args)
    folder_id = resolve_mail_folder(args["folder_id"], "folder_id")
    check_rate(account_id, "sensitive")
    folder = mail_folders.get_folder(account_id, folder_id=folder_id)
    ids, total = mail.list_message_ids(
        account_id,
        folder_id=folder_id,
        max_items=arg(args, EMPTY, "max_messages"),
        unread_only=False,
    )
    deleted = mail.delete_messages(account_id, message_ids=ids)
    if total is None:
        total = max(folder.get("totalItemCount") or 0, len(ids))
    remaining = max(total - deleted, 0)
    failed = len(ids) - deleted

    name = folder.get("displayName") or folder["id"]
    if not ids:
        summary = f"{name} is already empty."
    elif failed:
        summary = (
            f"Deleted {deleted} of {len(ids)}; {failed} failed (see remaining). "
            "Call again to retry the rest"
        )
    elif remaining:
        summary = (
            f"Deleted {plural(deleted, 'message')} from {name}; "
            f"{remaining} remain (call again)."
        )
    else:
        summary = f"Deleted {plural(deleted, 'message')} from {name}."
    return {
        "folder_id": folder["id"],
        "deleted": deleted,
        "remaining": remaining,
        "summary": summary,
    }
