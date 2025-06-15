import base64
from typing import NamedTuple, Any


class Attachment(NamedTuple):
    name: str
    content_bytes: bytes
    content_type: str = "application/octet-stream"


class EmailBody(NamedTuple):
    content: str
    content_type: str = "Text"


def _build_attachment_data(attachment: Attachment) -> dict[str, str]:
    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": attachment.name,
        "contentType": attachment.content_type,
        "contentBytes": base64.b64encode(attachment.content_bytes).decode(),
    }


def build_email_payload(
    subject: str,
    body: EmailBody,
    to_recipients: list[str],
    cc_recipients: list[str] | None = None,
    bcc_recipients: list[str] | None = None,
    attachments: list[Attachment] | None = None,
) -> dict[str, Any]:
    message = {
        "subject": subject,
        "body": {
            "contentType": body.content_type,
            "content": body.content,
        },
        "toRecipients": [{"emailAddress": {"address": addr}} for addr in to_recipients],
    }

    if cc_recipients:
        message["ccRecipients"] = [
            {"emailAddress": {"address": addr}} for addr in cc_recipients
        ]

    if bcc_recipients:
        message["bccRecipients"] = [
            {"emailAddress": {"address": addr}} for addr in bcc_recipients
        ]

    if attachments:
        message["attachments"] = [_build_attachment_data(att) for att in attachments]

    return {"message": message, "saveToSentItems": True}
