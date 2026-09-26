"""Opaque, integrity-protected pagination cursors (concept §7).

A cursor is base64url (no padding) of ``MAC || payload``:

- ``payload`` is compact JSON with the version ``v``, a keyed account hash
  ``a`` (never the raw account ID), the resource ``r``, the request hash
  ``q``, the issued-at time ``t`` (Unix seconds) and exactly one position:
  a Graph nextLink ``n``, an integer offset ``o``, or per-resource
  sub-cursors ``s`` for multi-resource search.
- ``MAC`` is the first 16 bytes of HMAC-SHA256 over the payload.

The HMAC key comes from ``M365_MCP_CURSOR_KEY`` when set, so cursors stay
valid across restarts and between workers. Otherwise a random key is
generated per process and cursors expire when the server restarts.

On decode the MAC, version, account, resource and request hash must match,
the cursor must be at most 24 hours old, and every nextLink must be an
HTTPS URL on a host in ``validators.GRAPH_ALLOWED_HOSTS``.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .validators import GRAPH_ALLOWED_HOSTS, ValidationError

CURSOR_VERSION = 1
CURSOR_TTL_SECONDS = 24 * 60 * 60
CURSOR_KEY_ENV = "M365_MCP_CURSOR_KEY"
_MAC_BYTES = 16
# Arguments that never change which result set a cursor belongs to. The
# account is checked separately against the resolved account ID.
_EXCLUDED_REQUEST_KEYS = frozenset({"cursor", "account_id"})

_RETRY = "Expected: repeat the call without cursor"
_MISMATCH = f"Invalid cursor: it does not match this request. {_RETRY}"
_EXPIRED = f"Invalid cursor: it is more than 24 hours old. {_RETRY}"
_BAD_HOST = f"Invalid cursor: its next page is not on Microsoft Graph. {_RETRY}"


@dataclass(frozen=True)
class PagePosition:
    """Where the next page starts: a Graph nextLink or an offset."""

    next_link: str | None = None
    offset: int | None = None


@dataclass(frozen=True)
class DecodedCursor:
    """A verified cursor.

    Exactly one of ``next_link``, ``offset`` or ``sub_cursors`` is set.
    ``sub_cursors`` maps each resource that has more results to its own
    position; exhausted resources are absent.
    """

    next_link: str | None = None
    offset: int | None = None
    sub_cursors: dict[str, PagePosition] | None = None


def request_hash(request: Mapping[str, Any]) -> str:
    """Hash the normalised request arguments.

    ``cursor`` and ``account_id`` are ignored, as are arguments whose value
    is ``None`` (the same as omitting them). Every other argument, including
    ``limit``, must be identical for a cursor to be accepted.

    Args:
        request: Tool arguments of the call that produced the cursor.

    Returns:
        A 32-character hex digest.
    """
    normalised = {
        key: value
        for key, value in request.items()
        if key not in _EXCLUDED_REQUEST_KEYS and value is not None
    }
    encoded = json.dumps(normalised, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]


def _position_payload(position: PagePosition) -> dict[str, Any]:
    """Encode one position as ``{"n": link}`` or ``{"o": offset}``."""
    has_link = position.next_link is not None
    has_offset = position.offset is not None
    if has_link == has_offset:
        raise ValueError("A position needs exactly one of next_link, offset")
    if has_link:
        return {"n": position.next_link}
    if not isinstance(position.offset, int) or position.offset < 0:
        raise ValueError("offset must be a non-negative integer")
    return {"o": position.offset}


def _position_from_payload(data: Any) -> PagePosition:
    """Decode ``{"n": link}`` or ``{"o": offset}``."""
    if not isinstance(data, dict):
        raise ValidationError(_MISMATCH)
    link, offset = data.get("n"), data.get("o")
    if isinstance(link, str) and offset is None:
        _check_link_host(link)
        return PagePosition(next_link=link)
    if isinstance(offset, int) and offset >= 0 and link is None:
        return PagePosition(offset=offset)
    raise ValidationError(_MISMATCH)


def _check_link_host(link: str) -> None:
    """Refuse nextLinks that are not HTTPS URLs on a Graph host."""
    parsed = urlparse(link)
    host = (parsed.hostname or "").lower()
    if parsed.scheme.lower() != "https" or host not in GRAPH_ALLOWED_HOSTS:
        raise ValidationError(_BAD_HOST)


class CursorCodec:
    """Encode and verify cursors with one HMAC key and clock."""

    def __init__(
        self,
        key: bytes | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Create a codec.

        Args:
            key: HMAC key. Defaults to ``M365_MCP_CURSOR_KEY`` (UTF-8) when
                set, otherwise 32 random bytes for this process.
            clock: Returns the current Unix time in seconds.
        """
        if key is None:
            env_key = os.getenv(CURSOR_KEY_ENV)
            key = env_key.encode("utf-8") if env_key else os.urandom(32)
        self._key = key
        self._clock = clock

    def _account_hash(self, account_id: str) -> str:
        """Return a keyed hash of the account ID."""
        digest = hmac.new(self._key, b"account:" + account_id.encode("utf-8"), "sha256")
        return digest.hexdigest()[:16]

    def _mac(self, payload: bytes) -> bytes:
        return hmac.new(self._key, payload, "sha256").digest()[:_MAC_BYTES]

    def encode(
        self,
        account_id: str,
        resource: str,
        request: Mapping[str, Any],
        *,
        next_link: str | None = None,
        offset: int | None = None,
        sub_cursors: Mapping[str, PagePosition] | None = None,
    ) -> str:
        """Create a cursor for the next page of a request.

        Args:
            account_id: Resolved account ID the request ran against.
            resource: Resource (or tool family, e.g. ``search``) listed.
            request: Tool arguments; see ``request_hash``.
            next_link: Graph ``@odata.nextLink`` for the next page.
            offset: Offset of the next item for client-side paging.
            sub_cursors: Per-resource positions for multi-resource search.

        Returns:
            The opaque cursor string.

        Raises:
            ValueError: If not exactly one of ``next_link``, ``offset`` or
                ``sub_cursors`` is given, or a position is invalid.
        """
        given = [
            value for value in (next_link, offset, sub_cursors) if value is not None
        ]
        if len(given) != 1:
            raise ValueError("Give exactly one of next_link, offset or sub_cursors")

        payload: dict[str, Any] = {
            "v": CURSOR_VERSION,
            "a": self._account_hash(account_id),
            "r": resource,
            "q": request_hash(request),
            "t": int(self._clock()),
        }
        if sub_cursors is not None:
            if not sub_cursors:
                raise ValueError("sub_cursors cannot be empty")
            payload["s"] = {
                name: _position_payload(position)
                for name, position in sub_cursors.items()
            }
        else:
            payload.update(
                _position_payload(PagePosition(next_link=next_link, offset=offset))
            )

        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        token = base64.urlsafe_b64encode(self._mac(body) + body)
        return token.decode("ascii").rstrip("=")

    def decode(
        self,
        cursor: str,
        account_id: str,
        resource: str,
        request: Mapping[str, Any],
    ) -> DecodedCursor:
        """Verify a cursor against the current request and unpack it.

        Args:
            cursor: The ``cursor`` argument supplied by the model.
            account_id: Resolved account ID of the current call.
            resource: Resource of the current call.
            request: Arguments of the current call.

        Returns:
            The verified position(s).

        Raises:
            ValidationError: If the cursor is malformed, tampered with, from
                another request or account, older than 24 hours, or points
                outside Microsoft Graph.
        """
        try:
            raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        except (binascii.Error, ValueError) as exc:
            raise ValidationError(_MISMATCH) from exc
        mac, body = raw[:_MAC_BYTES], raw[_MAC_BYTES:]
        if not body or not hmac.compare_digest(mac, self._mac(body)):
            raise ValidationError(_MISMATCH)
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValidationError(_MISMATCH) from exc

        if (
            not isinstance(payload, dict)
            or payload.get("v") != CURSOR_VERSION
            or payload.get("a") != self._account_hash(account_id)
            or payload.get("r") != resource
            or payload.get("q") != request_hash(request)
            or not isinstance(payload.get("t"), int)
        ):
            raise ValidationError(_MISMATCH)
        if self._clock() - payload["t"] > CURSOR_TTL_SECONDS:
            raise ValidationError(_EXPIRED)

        if "s" in payload:
            subs = payload["s"]
            if not isinstance(subs, dict) or not subs:
                raise ValidationError(_MISMATCH)
            return DecodedCursor(
                sub_cursors={
                    name: _position_from_payload(data) for name, data in subs.items()
                }
            )
        position = _position_from_payload(
            {key: payload[key] for key in ("n", "o") if key in payload}
        )
        return DecodedCursor(next_link=position.next_link, offset=position.offset)


cursor_codec = CursorCodec()
