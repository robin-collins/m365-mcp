"""Handlers for the compose tools (U3.9-U3.12).

``email_create_draft``, ``email_send``, ``email_reply`` and
``email_forward``. Graph calls live in ``services/mail_compose.py``; an
ambiguous failure of the final send request becomes the spec's "Outcome
unknown" error and is never retried.
"""

from __future__ import annotations

import math
import mimetypes
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any, TypeVar

from fastmcp.exceptions import ToolError

from ...local_files import check_read_path
from ...services import mail_compose
from ...services.mail_compose import LocalAttachment, SendOutcomeUnknown
from ...untrusted import sanitize_text
from ..handlers import register_handler, register_validation_rule
from . import common
from .common import arg, invalid, require_confirm

MAX_RECIPIENTS = 500
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
OUTCOME_UNKNOWN = "Outcome unknown: check Sent Items before retrying"

# email_send: fields of a new message, forbidden with mode='draft'.
_NEW_ONLY = (
    "to",
    "cc",
    "bcc",
    "subject",
    "body",
    "body_format",
    "attachments",
    "importance",
    "save_to_sent",
)
_NEW_REQUIRED = ("to", "subject", "body")

_T = TypeVar("_T")


# ----------------------------------------------------------------------
# shared helpers
# ----------------------------------------------------------------------


def _unique_count(*groups: Iterable[str] | None) -> int:
    return len({a.lower() for group in groups for a in group or ()})


def _check_recipient_total(args: dict[str, Any]) -> None:
    if _unique_count(args.get("to"), args.get("cc"), args.get("bcc")) > MAX_RECIPIENTS:
        raise invalid("to", f"more than {MAX_RECIPIENTS} recipients in total")


def _check_attachments(args: dict[str, Any]) -> None:
    for path in args.get("attachments") or ():
        resolved = check_read_path(path, "attachments")
        size = resolved.stat().st_size
        if size > MAX_ATTACHMENT_BYTES:
            megabytes = math.ceil(size / (1024 * 1024))
            raise invalid(
                "attachments",
                f"'{resolved.name}' is {megabytes} MB",
                "at most 25 MB",
            )


def _load_attachments(args: dict[str, Any]) -> list[LocalAttachment]:
    attachments = []
    for path in args.get("attachments") or ():
        resolved = check_read_path(path, "attachments")
        content_type = mimetypes.guess_type(resolved.name)[0]
        attachments.append(
            LocalAttachment(
                name=resolved.name,
                content_type=content_type or "application/octet-stream",
                data=resolved.read_bytes(),
            )
        )
    return attachments


def _addresses(recipients: list[dict[str, Any]] | None) -> list[str]:
    return [
        (r.get("emailAddress") or {}).get("address") or "" for r in recipients or []
    ]


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _subject_of(message: dict[str, Any]) -> str:
    return sanitize_text(message.get("subject")) or ""


def _send_once(call: Callable[[], _T]) -> _T:
    """Run a send flow, mapping an ambiguous final failure to the spec text."""
    try:
        return call()
    except SendOutcomeUnknown as exc:
        raise ToolError(OUTCOME_UNKNOWN) from exc


def _message_from_args(args: dict[str, Any], tool: str) -> dict[str, Any]:
    return mail_compose.build_message(
        subject=args.get("subject"),
        body=args.get("body"),
        body_format=arg(args, tool, "body_format"),
        to=args.get("to") or (),
        cc=args.get("cc") or (),
        bcc=args.get("bcc") or (),
        importance=args.get("importance"),
    )


# ----------------------------------------------------------------------
# email_create_draft (U3.9)
# ----------------------------------------------------------------------


@register_validation_rule("email_create_draft")
def _draft_recipients(args: dict[str, Any]) -> None:
    _check_recipient_total(args)


@register_validation_rule("email_create_draft")
def _draft_attachments(args: dict[str, Any]) -> None:
    _check_attachments(args)


@register_handler("email_create_draft")
def email_create_draft(args: dict[str, Any]) -> dict[str, Any]:
    """Create an unsent draft, attaching local files.

    Args:
        args: Validated ``email_create_draft`` arguments.

    Returns:
        The created draft record with ``summary``.
    """
    account_id = common.account(args)
    common.check_rate(account_id, "normal")
    attachments = _load_attachments(args)
    draft = mail_compose.create_draft(
        account_id,
        message=_message_from_args(args, "email_create_draft"),
        attachments=attachments,
    )
    to = _addresses(draft.get("toRecipients")) or list(args["to"])
    subject = draft.get("subject") or args["subject"]
    shown = ", ".join(to) if len(to) <= 3 else _plural(len(to), "recipient")
    return {
        "draft_id": draft["id"],
        "subject": subject,
        "to": to,
        "cc": _addresses(draft.get("ccRecipients")),
        "bcc": _addresses(draft.get("bccRecipients")),
        "attachment_count": len(attachments),
        "web_link": draft.get("webLink"),
        "summary": f"Draft '{subject}' created for {shown} (not sent).",
    }


# ----------------------------------------------------------------------
# email_send (U3.10)
# ----------------------------------------------------------------------


@register_validation_rule("email_send")
def _send_mode_fields(args: dict[str, Any]) -> None:
    if args["mode"] == "draft":
        if args.get("draft_id") is None:
            raise invalid("draft_id", "required when mode='draft'")
        for name in _NEW_ONLY:
            if name in args:
                raise invalid(name, "not allowed when mode='draft'")
        return
    if args.get("draft_id") is not None:
        raise invalid("draft_id", "not allowed when mode='new'")
    for name in _NEW_REQUIRED:
        if args.get(name) is None:
            raise invalid(name, "required when mode='new'")


@register_validation_rule("email_send")
def _send_confirm(args: dict[str, Any]) -> None:
    require_confirm(args, "send email")


@register_validation_rule("email_send")
def _send_recipients(args: dict[str, Any]) -> None:
    _check_recipient_total(args)


@register_validation_rule("email_send")
def _send_attachments(args: dict[str, Any]) -> None:
    _check_attachments(args)


@register_handler("email_send")
def email_send(args: dict[str, Any]) -> dict[str, Any]:
    """Send a new message or an existing draft.

    Args:
        args: Validated ``email_send`` arguments.

    Returns:
        The send confirmation with ``summary``.

    Raises:
        ToolError: "Outcome unknown" when the send may have happened.
    """
    account_id = common.account(args)
    common.check_rate(account_id, "sensitive")
    mode = args["mode"]
    if mode == "draft":
        draft_id = args["draft_id"]
        draft = mail_compose.get_message(account_id, draft_id)
        _send_once(lambda: mail_compose.send_draft(account_id, draft_id))
        subject = _subject_of(draft)
        count = _unique_count(
            _addresses(draft.get("toRecipients")),
            _addresses(draft.get("ccRecipients")),
            _addresses(draft.get("bccRecipients")),
        )
        sent_id: str | None = draft_id
    else:
        attachments = _load_attachments(args)
        message = _message_from_args(args, "email_send")
        save_to_sent = arg(args, "email_send", "save_to_sent")
        sent_id = _send_once(
            lambda: mail_compose.send_new(
                account_id,
                message=message,
                attachments=attachments,
                save_to_sent=save_to_sent,
            )
        )
        subject = args["subject"]
        count = _unique_count(args.get("to"), args.get("cc"), args.get("bcc"))
    return {
        "status": "sent",
        "mode": mode,
        "draft_id": sent_id,
        "recipient_count": count,
        "sent_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "summary": f"Sent '{subject}' to {_plural(count, 'recipient')}.",
    }


# ----------------------------------------------------------------------
# email_reply (U3.11)
# ----------------------------------------------------------------------


@register_validation_rule("email_reply")
def _reply_confirm(args: dict[str, Any]) -> None:
    require_confirm(args, "reply")


@register_validation_rule("email_reply")
def _reply_attachments(args: dict[str, Any]) -> None:
    _check_attachments(args)


@register_handler("email_reply")
def email_reply(args: dict[str, Any]) -> dict[str, Any]:
    """Reply to the sender or to everyone on a message.

    Args:
        args: Validated ``email_reply`` arguments.

    Returns:
        The reply confirmation with ``summary``.

    Raises:
        ToolError: "Outcome unknown" when the reply may have been sent.
    """
    account_id = common.account(args)
    common.check_rate(account_id, "sensitive")
    email_id, mode = args["email_id"], args["mode"]
    original = mail_compose.get_message(account_id, email_id)
    attachments = _load_attachments(args)
    reply_all = mode == "all"
    _send_once(
        lambda: mail_compose.reply(
            account_id,
            email_id=email_id,
            reply_all=reply_all,
            comment=args["body"],
            cc=args.get("cc") or (),
            existing_cc=_addresses(original.get("ccRecipients")) if reply_all else (),
            attachments=attachments,
        )
    )
    who = "all" if reply_all else "the sender"
    return {
        "status": "sent",
        "mode": mode,
        "in_reply_to": email_id,
        "conversation_id": original.get("conversationId"),
        "summary": f"Replied to {who} on '{_subject_of(original)}'.",
    }


# ----------------------------------------------------------------------
# email_forward (U3.12)
# ----------------------------------------------------------------------


@register_validation_rule("email_forward")
def _forward_confirm(args: dict[str, Any]) -> None:
    require_confirm(args, "forward")


@register_validation_rule("email_forward")
def _forward_attachments(args: dict[str, Any]) -> None:
    _check_attachments(args)


@register_handler("email_forward")
def email_forward(args: dict[str, Any]) -> dict[str, Any]:
    """Forward a message to the named recipients.

    Args:
        args: Validated ``email_forward`` arguments.

    Returns:
        The forward confirmation with ``summary``.

    Raises:
        ToolError: "Outcome unknown" when the forward may have been sent.
    """
    account_id = common.account(args)
    common.check_rate(account_id, "sensitive")
    email_id = args["email_id"]
    original = mail_compose.get_message(account_id, email_id)
    attachments = _load_attachments(args)
    _send_once(
        lambda: mail_compose.forward(
            account_id,
            email_id=email_id,
            to=args["to"],
            cc=args.get("cc") or (),
            bcc=args.get("bcc") or (),
            comment=args.get("comment"),
            attachments=attachments,
        )
    )
    count = _unique_count(args.get("to"), args.get("cc"), args.get("bcc"))
    return {
        "status": "sent",
        "forwarded_id": email_id,
        "recipient_count": count,
        "summary": (
            f"Forwarded '{_subject_of(original)}' to {_plural(count, 'recipient')}."
        ),
    }
