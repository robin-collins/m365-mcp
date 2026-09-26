"""Compose and send mail over Microsoft Graph (unified tools).

Owns the Graph endpoints for drafts, sends, replies and forwards used by
``email_create_draft``, ``email_send``, ``email_reply`` and
``email_forward``. Callers pass validated inputs and file contents that
were already read from allowed local paths.

Sending is not idempotent. The final send request of every flow is never
retried (``graph`` only retries requests Graph did not process), and an
ambiguous failure of that request (a timeout, a dropped connection or a
5xx other than 503) raises :class:`SendOutcomeUnknown` so the caller can
tell the user to check Sent Items instead of retrying.
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

import httpx

from .. import graph
from ..errors import GraphAPIError

# Attachments of this size or more go through an upload session; a send
# whose attachments total this much or more goes through a draft, so the
# JSON request stays under Graph's 4 MB limit after base64 encoding.
UPLOAD_SESSION_THRESHOLD = 3 * 1024 * 1024

_T = TypeVar("_T")


@dataclass(frozen=True)
class LocalAttachment:
    """A local file to attach, already read from an allowed path.

    Attributes:
        name: File name shown to recipients.
        content_type: MIME type.
        data: File contents.
    """

    name: str
    content_type: str
    data: bytes


class SendOutcomeUnknown(Exception):
    """The final send request failed in a way that may have sent the mail."""


def is_ambiguous_failure(exc: BaseException) -> bool:
    """Return whether a failed write may still have taken effect.

    Args:
        exc: Exception raised by a Graph request.

    Returns:
        True for 5xx responses other than 503, and for network errors
        other than connection failures (the request may have arrived).
    """
    if isinstance(exc, GraphAPIError):
        return exc.status >= 500 and exc.status != 503
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return False
    return isinstance(exc, httpx.TransportError)


def _final_send(call: Callable[[], _T]) -> _T:
    """Run the final, non-idempotent send request of a flow."""
    try:
        return call()
    except Exception as exc:
        if is_ambiguous_failure(exc):
            raise SendOutcomeUnknown(str(exc)) from exc
        raise


def _recipients(addresses: Sequence[str]) -> list[dict[str, Any]]:
    return [{"emailAddress": {"address": address}} for address in addresses]


def build_message(
    *,
    subject: str | None = None,
    body: str | None = None,
    body_format: str = "text",
    to: Sequence[str] = (),
    cc: Sequence[str] = (),
    bcc: Sequence[str] = (),
    importance: str | None = None,
) -> dict[str, Any]:
    """Build a Graph ``message`` body from the supplied fields only.

    Args:
        subject: Subject line.
        body: Body text.
        body_format: ``text`` or ``html``.
        to: To addresses.
        cc: Cc addresses.
        bcc: Bcc addresses.
        importance: ``low``, ``normal`` or ``high``.

    Returns:
        The Graph message object.
    """
    message: dict[str, Any] = {}
    if subject is not None:
        message["subject"] = subject
    if body is not None:
        content_type = "HTML" if body_format == "html" else "Text"
        message["body"] = {"contentType": content_type, "content": body}
    if to:
        message["toRecipients"] = _recipients(to)
    if cc:
        message["ccRecipients"] = _recipients(cc)
    if bcc:
        message["bccRecipients"] = _recipients(bcc)
    if importance is not None:
        message["importance"] = importance
    return message


def _file_attachment(attachment: LocalAttachment) -> dict[str, Any]:
    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": attachment.name,
        "contentType": attachment.content_type,
        "contentBytes": base64.b64encode(attachment.data).decode("ascii"),
    }


def add_attachments(
    account_id: str, message_id: str, attachments: Sequence[LocalAttachment]
) -> None:
    """Attach local files to a draft.

    Files under 3 MB are posted to ``/attachments``; larger ones use an
    attachment upload session with chunked PUTs.

    Args:
        account_id: Microsoft account ID.
        message_id: Draft message ID.
        attachments: Files to attach.
    """
    for attachment in attachments:
        if len(attachment.data) >= UPLOAD_SESSION_THRESHOLD:
            graph.upload_large_mail_attachment(
                message_id,
                attachment.name,
                attachment.data,
                account_id,
                attachment.content_type,
            )
        else:
            graph.request(
                "POST",
                f"/me/messages/{message_id}/attachments",
                account_id,
                json=_file_attachment(attachment),
            )


def get_message(account_id: str, message_id: str) -> dict[str, Any]:
    """Read the fields the compose tools report on.

    Args:
        account_id: Microsoft account ID.
        message_id: Message ID.

    Returns:
        The Graph message (subject, recipients, conversation ID).

    Raises:
        ValueError: If Graph returns no message.
    """
    result = graph.request(
        "GET",
        f"/me/messages/{message_id}",
        account_id,
        params={
            "$select": (
                "id,subject,from,toRecipients,ccRecipients,bccRecipients,"
                "conversationId,isDraft,webLink"
            )
        },
    )
    if not result:
        raise ValueError(f"Email {message_id} not found")
    return result


def create_draft(
    account_id: str,
    *,
    message: dict[str, Any],
    attachments: Sequence[LocalAttachment] = (),
) -> dict[str, Any]:
    """Create a draft (``POST /me/messages``) and attach files to it.

    Args:
        account_id: Microsoft account ID.
        message: Graph message from :func:`build_message`.
        attachments: Files to attach after the draft exists.

    Returns:
        The created draft from Graph.

    Raises:
        ValueError: If Graph returns no draft.
    """
    draft = graph.request("POST", "/me/messages", account_id, json=message)
    if not draft:
        raise ValueError("Failed to create email draft")
    add_attachments(account_id, draft["id"], attachments)
    return draft


def send_draft(account_id: str, draft_id: str) -> None:
    """Send an existing draft (``POST /me/messages/{id}/send``).

    Raises:
        SendOutcomeUnknown: If the send may have happened despite the error.
    """
    _final_send(
        lambda: graph.request("POST", f"/me/messages/{draft_id}/send", account_id)
    )


def send_new(
    account_id: str,
    *,
    message: dict[str, Any],
    attachments: Sequence[LocalAttachment] = (),
    save_to_sent: bool = True,
) -> str | None:
    """Send a new message.

    Small sends use ``POST /me/sendMail`` with inline attachments. When any
    attachment needs an upload session, or the attachments total 3 MB or
    more, the message is created as a draft, the files are attached, and
    the draft is sent (Graph then always keeps a copy in Sent Items).

    Args:
        account_id: Microsoft account ID.
        message: Graph message from :func:`build_message`.
        attachments: Files to attach.
        save_to_sent: ``saveToSentItems`` for ``sendMail``.

    Returns:
        The draft ID when the draft path was used, else ``None``.

    Raises:
        SendOutcomeUnknown: If the send may have happened despite the error.
    """
    total = sum(len(a.data) for a in attachments)
    if total >= UPLOAD_SESSION_THRESHOLD:
        draft = create_draft(account_id, message=message, attachments=attachments)
        send_draft(account_id, draft["id"])
        return str(draft["id"])

    payload_message = dict(message)
    if attachments:
        payload_message["attachments"] = [_file_attachment(a) for a in attachments]
    _final_send(
        lambda: graph.request(
            "POST",
            "/me/sendMail",
            account_id,
            json={"message": payload_message, "saveToSentItems": save_to_sent},
        )
    )
    return None


def _draft_then_send(
    account_id: str,
    create_path: str,
    comment: str | None,
    changes: dict[str, Any],
    attachments: Sequence[LocalAttachment],
) -> str:
    """Run createReply/createReplyAll/createForward → PATCH → attach → send."""
    draft = graph.request(
        "POST",
        create_path,
        account_id,
        json={"comment": comment or ""},
    )
    if not draft:
        raise ValueError("Failed to create the reply or forward draft")
    draft_id = str(draft["id"])
    if changes:
        graph.request("PATCH", f"/me/messages/{draft_id}", account_id, json=changes)
    add_attachments(account_id, draft_id, attachments)
    send_draft(account_id, draft_id)
    return draft_id


def reply(
    account_id: str,
    *,
    email_id: str,
    reply_all: bool,
    comment: str,
    cc: Sequence[str] = (),
    existing_cc: Sequence[str] = (),
    attachments: Sequence[LocalAttachment] = (),
) -> None:
    """Reply to the sender, or to everyone, on a message.

    Without extra Cc or attachments this is one ``/reply`` or ``/replyAll``
    call with ``comment``. Otherwise it creates the reply draft, PATCHes the
    Cc list (``existing_cc`` plus ``cc``), attaches the files and sends.

    Args:
        account_id: Microsoft account ID.
        email_id: Message to reply to.
        reply_all: Reply to all recipients.
        comment: Reply text.
        cc: Extra Cc addresses.
        existing_cc: Cc addresses the reply draft already has (reply all).
        attachments: Files to attach.

    Raises:
        SendOutcomeUnknown: If the send may have happened despite the error.
    """
    action = "replyAll" if reply_all else "reply"
    if not cc and not attachments:
        _final_send(
            lambda: graph.request(
                "POST",
                f"/me/messages/{email_id}/{action}",
                account_id,
                json={"comment": comment},
            )
        )
        return
    changes: dict[str, Any] = {}
    if cc:
        merged = list(dict.fromkeys([*existing_cc, *cc]))
        changes["ccRecipients"] = _recipients(merged)
    create = "createReplyAll" if reply_all else "createReply"
    _draft_then_send(
        account_id,
        f"/me/messages/{email_id}/{create}",
        comment,
        changes,
        attachments,
    )


def forward(
    account_id: str,
    *,
    email_id: str,
    to: Sequence[str],
    cc: Sequence[str] = (),
    bcc: Sequence[str] = (),
    comment: str | None = None,
    attachments: Sequence[LocalAttachment] = (),
) -> None:
    """Forward a message.

    Without Cc, Bcc or attachments this is one ``/forward`` call. Otherwise
    it creates the forward draft, PATCHes the recipients, attaches the
    files and sends.

    Args:
        account_id: Microsoft account ID.
        email_id: Message to forward.
        to: Recipients.
        cc: Cc recipients.
        bcc: Bcc recipients.
        comment: Optional note above the forwarded message.
        attachments: Extra files to attach.

    Raises:
        SendOutcomeUnknown: If the send may have happened despite the error.
    """
    if not cc and not bcc and not attachments:
        payload: dict[str, Any] = {"toRecipients": _recipients(to)}
        if comment:
            payload["comment"] = comment
        _final_send(
            lambda: graph.request(
                "POST",
                f"/me/messages/{email_id}/forward",
                account_id,
                json=payload,
            )
        )
        return
    changes = build_message(to=to, cc=cc, bcc=bcc)
    _draft_then_send(
        account_id,
        f"/me/messages/{email_id}/createForward",
        comment,
        changes,
        attachments,
    )
