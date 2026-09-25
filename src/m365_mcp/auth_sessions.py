"""Server-side store for device-code sign-in sessions (task U2.11).

The MSAL device flow, including its device code, stays in this process.
Callers only ever see an opaque ``auth_session_id`` plus the user code and
verification URL the user needs to sign in.
"""

import secrets
import threading
import time
from collections.abc import Callable
from typing import Any, NamedTuple

from . import auth
from .validators import ValidationError

SESSION_TTL_SECONDS = 15 * 60
UNKNOWN_SESSION_ERROR = (
    "Invalid auth_session_id: unknown or expired. "
    "Expected: start again with account_auth_begin"
)


class _Session(NamedTuple):
    flow: dict[str, Any]
    expires_at: float


class AuthSessionStore:
    """Keep device flows server-side behind opaque, expiring session IDs."""

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        ttl_seconds: int = SESSION_TTL_SECONDS,
    ) -> None:
        """Create an empty store.

        Args:
            clock: Monotonic time source in seconds (injectable for tests).
            ttl_seconds: Session lifetime in seconds.
        """
        self._clock = clock
        self._ttl = ttl_seconds
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.Lock()

    def __len__(self) -> int:
        """Return the number of stored sessions."""
        return len(self._sessions)

    def _purge_expired(self, now: float) -> None:
        for session_id, session in list(self._sessions.items()):
            if session.expires_at <= now:
                del self._sessions[session_id]

    def begin(self) -> dict[str, Any]:
        """Start a device-code sign-in.

        Returns:
            ``auth_session_id``, ``verification_url``, ``user_code`` and
            ``expires_in`` (seconds). The device code is never returned.

        Raises:
            Exception: If MSAL cannot start the device flow.
        """
        app, tenant_id = auth.get_app()
        _app, flow = auth._initiate_device_flow(app, tenant_id)

        expires_in = min(int(flow.get("expires_in", self._ttl)), self._ttl)
        session_id = f"as_{secrets.token_urlsafe(24)}"
        with self._lock:
            now = self._clock()
            self._purge_expired(now)
            self._sessions[session_id] = _Session(flow, now + expires_in)

        return {
            "auth_session_id": session_id,
            "verification_url": flow.get(
                "verification_uri",
                flow.get("verification_url", "https://microsoft.com/devicelogin"),
            ),
            "user_code": flow["user_code"],
            "expires_in": expires_in,
        }

    def complete(self, auth_session_id: str) -> dict[str, Any]:
        """Poll a sign-in once, without blocking.

        Sessions end on success or on any error; a pending poll keeps them.

        Args:
            auth_session_id: ID returned by :meth:`begin`.

        Returns:
            ``{"status": "pending", "account": None}`` while the user has not
            finished, otherwise ``{"status": "success", "account":
            {"account_id", "email"}}``.

        Raises:
            ValidationError: If the session is unknown, used or expired.
            auth.PersonalAccountRequiredError: If a work or school account
                signed in.
            RuntimeError: If Microsoft rejected the sign-in.
        """
        with self._lock:
            self._purge_expired(self._clock())
            session = self._sessions.get(auth_session_id)
        if session is None:
            raise ValidationError(UNKNOWN_SESSION_ERROR)

        app, result = auth.poll_device_flow_once(session.flow)
        if result.get("error") == "authorization_pending":
            return {"status": "pending", "account": None}

        with self._lock:
            self._sessions.pop(auth_session_id, None)

        if "error" in result:
            reason = str(result.get("error_description") or result["error"])
            raise RuntimeError(
                f"Sign-in failed: {reason.splitlines()[0]}. "
                "Start again with account_auth_begin."
            )

        account = auth.finish_device_flow_sign_in(app, result)
        return {
            "status": "success",
            "account": {"account_id": account.account_id, "email": account.username},
        }


store = AuthSessionStore()
