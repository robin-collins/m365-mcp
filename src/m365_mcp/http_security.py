"""Security helpers for the Streamable HTTP transport (audit BP6).

- :class:`OriginValidationMiddleware` rejects browser requests whose
  ``Origin`` is not allowed, as the MCP specification requires to prevent
  DNS-rebinding attacks. Requests without an ``Origin`` header (desktop and
  CLI clients) pass.
- :func:`token_matches` compares bearer tokens in constant time.

Allowed origins default to local loopback (``localhost``, ``127.0.0.1``,
``[::1]``, any port, http or https). ``MCP_ALLOWED_ORIGINS`` (comma
separated, exact ``scheme://host[:port]`` values) replaces the default.
"""

from __future__ import annotations

import hmac
import json
import os
import re
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

ALLOWED_ORIGINS_ENV = "MCP_ALLOWED_ORIGINS"
DEFAULT_ALLOWED_ORIGINS = [
    r"https?://localhost(:\d{1,5})?",
    r"https?://127\.0\.0\.1(:\d{1,5})?",
    r"https?://\[::1\](:\d{1,5})?",
]

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


def allowed_origins_from_env() -> list[str]:
    """Return allowed-origin patterns from ``MCP_ALLOWED_ORIGINS``.

    Returns:
        Regular expressions matching whole origins: the escaped configured
        values, or the loopback defaults when the variable is unset.
    """
    raw = os.environ.get(ALLOWED_ORIGINS_ENV, "")
    values = [v.strip().rstrip("/") for v in raw.split(",") if v.strip()]
    if not values:
        return list(DEFAULT_ALLOWED_ORIGINS)
    return [re.escape(v) for v in values]


def origin_allowed(origin: str, allowed: list[str]) -> bool:
    """Return whether ``origin`` fully matches one allowed pattern."""
    origin = origin.strip().rstrip("/").lower()
    return any(re.fullmatch(pattern, origin, re.IGNORECASE) for pattern in allowed)


def token_matches(provided: str, expected: str) -> bool:
    """Compare a bearer token with the configured one in constant time."""
    return hmac.compare_digest(provided.encode(), expected.encode())


class OriginValidationMiddleware:
    """ASGI middleware that rejects requests from disallowed origins."""

    def __init__(self, app: ASGIApp, allowed_origins: list[str] | None = None) -> None:
        """Wrap ``app``.

        Args:
            app: The ASGI application to protect.
            allowed_origins: Origin patterns; defaults to the environment.
        """
        self.app = app
        self.allowed = (
            allowed_origins
            if allowed_origins is not None
            else allowed_origins_from_env()
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Reject a disallowed ``Origin`` with 403, otherwise pass through."""
        if scope["type"] in ("http", "websocket"):
            origin = None
            for name, value in scope.get("headers", []):
                if name == b"origin":
                    origin = value.decode("latin-1")
                    break
            if origin is not None and not origin_allowed(origin, self.allowed):
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                    return
                body = json.dumps({"detail": "Origin not allowed"}).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 403,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)
