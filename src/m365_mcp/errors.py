"""Graph error types and their mapping to actionable tool errors.

``graph._send`` raises :class:`GraphAPIError` (parsed from the Graph error
body) and :class:`DeadlineExceeded` (per-call budget spent). Tools convert
any exception with :func:`to_tool_error`, whose text says what failed, how
to fix it and whether retrying helps. Messages never contain URLs,
request IDs, raw Graph codes, status numbers or stack traces; those stay in
the exception attributes and the server log.
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any

import httpx
from fastmcp.exceptions import ToolError

from .validators import ValidationError

logger = logging.getLogger(__name__)

_URL_PATTERN = re.compile(r"\bhttps?://\S+", re.IGNORECASE)
_MAX_DETAIL_CHARS = 200
_DEFAULT_THROTTLE_SECONDS = 60

# Human noun for each resource type, used in 404 hints.
_RESOURCE_NOUNS = {
    "email": "email",
    "email_folder": "mail folder",
    "email_rule": "inbox rule",
    "event": "event",
    "calendar": "calendar",
    "contact": "contact",
    "contact_folder": "contact folder",
    "drive_item": "OneDrive item",
}


class GraphAPIError(httpx.HTTPStatusError):
    """A Microsoft Graph request failed after retries.

    Subclasses ``httpx.HTTPStatusError`` so legacy callers that catch that
    type, or read ``exc.response.status_code``, keep working.

    Attributes:
        status: HTTP status code.
        code: Graph error code (for example ``ErrorItemNotFound``), or an
            empty string when the body had none.
        message: Graph error message, or the HTTP reason phrase.
        request_id: Graph ``request-id`` for support, if known.
        retry_after: Server-requested wait in seconds, if any.
    """

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        request_id: str | None,
        *,
        retry_after: float | None = None,
        request: httpx.Request | None = None,
        response: httpx.Response | None = None,
    ) -> None:
        """Create the error; request/response default to placeholders."""
        if request is None:
            request = httpx.Request("GET", "https://graph.microsoft.com")
        if response is None:
            response = httpx.Response(status, request=request)
        label = f"{code}: {message}" if code else message
        super().__init__(
            f"Graph API error {status} ({label})",
            request=request,
            response=response,
        )
        self.status = status
        self.code = code
        self.message = message
        self.request_id = request_id
        self.retry_after = retry_after

    @classmethod
    def from_response(
        cls, response: httpx.Response, *, retry_after: float | None = None
    ) -> GraphAPIError:
        """Parse a Graph error response.

        Graph returns ``{"error": {"code", "message", "innerError":
        {"request-id"}}}``. Non-JSON bodies fall back to the reason phrase
        and the ``request-id`` response header.

        Args:
            response: The failed response (its request must be set).
            retry_after: Server-requested wait in seconds, if any.

        Returns:
            The parsed error.
        """
        error: dict[str, Any] = {}
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict) and isinstance(body.get("error"), dict):
            error = body["error"]
        inner = error.get("innerError")
        inner = inner if isinstance(inner, dict) else {}

        code = str(error.get("code") or "")
        message = str(error.get("message") or response.reason_phrase or "")
        request_id = inner.get("request-id") or response.headers.get("request-id")
        return cls(
            response.status_code,
            code,
            message,
            request_id,
            retry_after=retry_after,
            request=response.request,
            response=response,
        )


class DeadlineExceeded(Exception):
    """The per-call time budget would be exceeded by another retry.

    Attributes:
        retry_after_seconds: Whole seconds the caller should wait before
            trying again (at least 1).
    """

    def __init__(self, retry_after: float) -> None:
        """Create the error from the wait that no longer fits."""
        self.retry_after_seconds = max(1, math.ceil(retry_after))
        super().__init__(
            f"Deadline exceeded; try again in {self.retry_after_seconds} s"
        )


def _detail(message: str) -> str:
    """Return Graph's message without URLs, trimmed for display."""
    text = _URL_PATTERN.sub("", message)
    text = " ".join(text.split()).strip(" .")
    return text[:_MAX_DETAIL_CHARS]


def _not_found(resource: str | None) -> str:
    if resource == "operation":
        return (
            "No copy operation with that id; ids come from drive_copy. "
            "Retrying with the same id will not help."
        )
    noun = _RESOURCE_NOUNS.get(resource or "")
    if noun is None:
        return (
            "The item was not found. Check the id or path; ids come from "
            "m365_list or m365_search. Retrying with the same value will "
            "not help."
        )
    if resource == "drive_item":
        return (
            "No OneDrive item with that id or path; ids come from m365_list "
            "or m365_search. Retrying with the same value will not help."
        )
    return (
        f"No {noun} with that id; ids come from m365_list or m365_search. "
        "Retrying with the same id will not help."
    )


def _conflict(tool: str | None, resource: str | None) -> str:
    if resource == "drive_item":
        options = (
            "if_exists='rename'"
            if tool == "m365_create"
            else "if_exists='replace' or 'rename'"
        )
        return (
            "An item with that name already exists there. Pass "
            f"{options}, or choose another name."
        )
    return (
        "The change conflicts with the item's current state, for example a "
        "name already in use. Choose a different value; retrying unchanged "
        "will fail again."
    )


def _graph_hint(err: GraphAPIError, tool: str | None, resource: str | None) -> str:
    status = err.status
    if status == 400:
        detail = _detail(err.message)
        reason = f" ({detail})" if detail else ""
        return (
            f"Microsoft 365 rejected the request as invalid{reason}. Correct "
            "the arguments using the tool description; retrying unchanged "
            "will fail again."
        )
    if status == 401:
        return (
            "The account's sign-in is no longer valid. Sign in again with "
            "account_auth_begin; retrying before that will fail again."
        )
    if status == 403:
        return (
            "The account does not have permission for this item or "
            "operation. Use an item the account owns; retrying will not help."
        )
    if status == 404:
        return _not_found(resource)
    if status == 409:
        return _conflict(tool, resource)
    if status == 412:
        return (
            "The item changed since it was read. Fetch it again with "
            "m365_get, then retry the change."
        )
    if status == 413:
        return (
            "The content is too large for this operation. Send smaller "
            "content, or use drive_upload for large files; retrying "
            "unchanged will fail again."
        )
    if status == 423:
        return (
            "The item is locked, for example a file open for editing. Try "
            "again in a few minutes, once it is closed."
        )
    if status == 429:
        seconds = (
            math.ceil(err.retry_after) if err.retry_after else _DEFAULT_THROTTLE_SECONDS
        )
        return (
            "Microsoft 365 is throttling requests for this account. Wait, "
            f"then try again in {max(1, seconds)} s."
        )
    if status >= 500:
        return (
            "Microsoft 365 had a temporary service problem. Try again in a "
            "minute; for sends and creates, first check whether the change "
            "already happened."
        )
    return (
        "Microsoft 365 rejected the request. Check the arguments; retrying "
        "unchanged is unlikely to help."
    )


def to_tool_error(
    exc: Exception, *, tool: str | None = None, resource: str | None = None
) -> ToolError:
    """Convert an exception into an actionable FastMCP ``ToolError``.

    Args:
        exc: The exception raised while running the tool.
        tool: Tool name, used to say what failed.
        resource: Resource type (``email``, ``drive_item`` ...), used for
            resource-aware hints such as which tool supplies ids.

    Returns:
        A ``ToolError`` whose text states what failed, how to fix it and
        whether retrying helps, without URLs, request IDs, raw codes or
        stack traces.
    """
    if isinstance(exc, ValidationError):
        return ToolError(str(exc))

    prefix = f"{tool} failed: " if tool else ""
    if isinstance(exc, GraphAPIError):
        return ToolError(prefix + _graph_hint(exc, tool, resource))
    if isinstance(exc, DeadlineExceeded):
        return ToolError(
            f"{prefix}Microsoft 365 did not finish within the time limit; "
            f"try again in {exc.retry_after_seconds} s."
        )

    logger.error(
        "Unexpected tool error",
        exc_info=exc,
        extra={"mcp_tool": tool, "resource": resource},
    )
    return ToolError(
        f"{prefix}An unexpected internal error occurred. Retrying is "
        "unlikely to help; details are in the server log."
    )
