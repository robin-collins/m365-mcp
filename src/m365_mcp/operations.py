"""Server-side store for background ``drive_copy`` operations (§8.14).

``drive_copy`` receives a monitor URL from Graph (``202 Accepted`` plus
``Location``). The URL is pre-authenticated, so it is kept here, keyed by an
opaque ``operation_id`` that is bound to the account, and is never returned
to the model. Entries expire 24 hours after they are recorded.

``get_status`` polls the monitor URL without an ``Authorization`` header and
maps Graph's ``asyncJobStatus`` to the spec's ``operation`` projection.
Completed and failed results are kept, so they are not polled again.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from . import graph
from .validators import ValidationError, validate_graph_url

OPERATION_TTL_SECONDS = 24 * 60 * 60

_UNKNOWN = (
    "Invalid id: unknown operation. Expected: an operation_id returned by "
    "drive_copy in the last 24 hours"
)
_FAILED_STATUSES = frozenset({"failed", "deletefailed"})
_REDIRECT_STATUSES = frozenset({302, 303})

Fetch = Callable[[str], httpx.Response]


class OperationStatusError(Exception):
    """Raised when the monitor URL cannot be read.

    The message never contains the monitor URL, which carries credentials.
    """


@dataclass
class _Operation:
    monitor_url: str
    account_id: str
    created: float
    final: dict[str, Any] | None = None


def _fetch_monitor(url: str) -> httpx.Response:
    """GET the monitor URL without credentials or following redirects.

    On completion the monitor may answer ``303 See Other`` pointing at the
    new item; that response is returned rather than followed.
    """
    try:
        return graph._send("GET", url, None, authenticate=False, follow_redirects=False)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in _REDIRECT_STATUSES:
            return exc.response
        raise


class OperationStore:
    """Keep monitor URLs server-side and report operation status."""

    def __init__(
        self,
        fetch: Fetch | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Create a store.

        Args:
            fetch: Performs the unauthenticated monitor GET. Defaults to
                ``graph._send`` with ``authenticate=False``.
            clock: Returns the current time in seconds.
        """
        self._fetch = fetch or _fetch_monitor
        self._clock = clock
        self._operations: dict[str, _Operation] = {}
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        expired = [
            op_id
            for op_id, op in self._operations.items()
            if now - op.created > OPERATION_TTL_SECONDS
        ]
        for op_id in expired:
            del self._operations[op_id]

    def record(self, monitor_url: str, account_id: str) -> str:
        """Store a monitor URL and return its new operation ID.

        Args:
            monitor_url: ``Location`` header from Graph's copy response.
            account_id: Resolved account that started the copy.

        Returns:
            An opaque ID such as ``op_1f2e3d4c5b6a7980``.

        Raises:
            ValidationError: If the monitor URL is not an approved Microsoft
                HTTPS URL.
        """
        monitor_url = validate_graph_url(monitor_url, "monitor_url")
        op_id = f"op_{secrets.token_hex(8)}"
        with self._lock:
            now = self._clock()
            self._prune(now)
            self._operations[op_id] = _Operation(monitor_url, account_id, now)
        return op_id

    def get_status(self, operation_id: str, account_id: str) -> dict[str, Any]:
        """Poll an operation and return the ``operation`` projection.

        Args:
            operation_id: ID returned by ``record``.
            account_id: Resolved account of the current call.

        Returns:
            ``{operation_id, status, percent_complete, resource_id, error}``
            with ``status`` one of ``in_progress``, ``completed`` or
            ``failed``.

        Raises:
            ValidationError: If the ID is unknown, expired or belongs to
                another account.
            OperationStatusError: If the monitor request fails.
        """
        with self._lock:
            self._prune(self._clock())
            op = self._operations.get(operation_id)
        if op is None or op.account_id != account_id:
            raise ValidationError(_UNKNOWN)
        if op.final is not None:
            return dict(op.final)

        try:
            response = self._fetch(op.monitor_url)
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            raise OperationStatusError(
                f"Could not read the copy status (HTTP {code}); try again later"
            ) from None
        except httpx.TransportError:
            raise OperationStatusError(
                "Could not reach the copy status service; try again later"
            ) from None
        result = _project(operation_id, response)
        if result["status"] != "in_progress":
            op.final = dict(result)
        return result


def _project(operation_id: str, response: httpx.Response) -> dict[str, Any]:
    """Map a monitor response to the ``operation`` projection."""
    if response.status_code in _REDIRECT_STATUSES:
        location = urlparse(response.headers.get("Location", "")).path
        resource_id = location.rstrip("/").rsplit("/", 1)[-1] or None
        return _operation(operation_id, "completed", 100, resource_id, None)

    body = response.json() if response.content else {}
    graph_status = str(body.get("status", "")).lower()
    percent = body.get("percentageComplete")
    percent = float(percent) if isinstance(percent, (int, float)) else None
    resource_id = body.get("resourceId") or None

    if graph_status == "completed":
        return _operation(operation_id, "completed", percent, resource_id, None)
    if graph_status in _FAILED_STATUSES:
        error = body.get("error")
        message = None
        if isinstance(error, dict):
            message = error.get("message") or error.get("code")
        return _operation(
            operation_id,
            "failed",
            percent,
            None,
            str(message) if message else "The copy failed.",
        )
    return _operation(operation_id, "in_progress", percent, None, None)


def _operation(
    operation_id: str,
    status: str,
    percent: float | None,
    resource_id: str | None,
    error: str | None,
) -> dict[str, Any]:
    """Build the closed ``operation`` projection."""
    return {
        "operation_id": operation_id,
        "status": status,
        "percent_complete": percent,
        "resource_id": resource_id,
        "error": error,
    }


operation_store = OperationStore()
