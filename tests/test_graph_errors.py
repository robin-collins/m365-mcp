"""Tests for GraphAPIError parsing and ToolError mapping (task U2.7)."""

from __future__ import annotations

import re
from typing import Any

import httpx
import pytest
from fastmcp.exceptions import ToolError

from src.m365_mcp import graph
from src.m365_mcp.errors import DeadlineExceeded, GraphAPIError, to_tool_error
from src.m365_mcp.validators import ValidationError

URL_PATTERN = re.compile(r"https?://", re.IGNORECASE)
REQUEST_ID = "7c9f2d1e-aaaa-bbbb-cccc-0123456789ab"


class FakeClient:
    """Return queued responses and record each request."""

    def __init__(self, outcomes: list[httpx.Response]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append({"method": method, "url": url, **kwargs})
        outcome = self.outcomes.pop(0)
        outcome.request = httpx.Request(method, url)
        return outcome


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph.time, "sleep", lambda _s: None)
    monkeypatch.setattr(graph, "get_token", lambda _a, force_refresh=False: "token")


def _install(monkeypatch: pytest.MonkeyPatch, *outcomes: Any) -> FakeClient:
    client = FakeClient(list(outcomes))
    monkeypatch.setattr(graph, "_client", client)
    return client


def _graph_body(code: str, message: str) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "innerError": {"request-id": REQUEST_ID, "date": "2026-09-26"},
        }
    }


# --- Parsing in graph._send -------------------------------------------------


def test_send_raises_graph_api_error_parsed_from_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(
        monkeypatch,
        httpx.Response(
            404, json=_graph_body("ErrorItemNotFound", "The item was not found.")
        ),
    )

    with pytest.raises(GraphAPIError) as info:
        graph.request("GET", "/me/messages/abc", "acc-1")

    err = info.value
    assert err.status == 404
    assert err.code == "ErrorItemNotFound"
    assert err.message == "The item was not found."
    assert err.request_id == REQUEST_ID


def test_graph_api_error_is_an_httpx_status_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy callers that catch httpx.HTTPStatusError keep working."""
    _install(monkeypatch, httpx.Response(400, json=_graph_body("BadRequest", "x")))

    with pytest.raises(httpx.HTTPStatusError) as info:
        graph.request("GET", "/me", "acc-1")

    assert isinstance(info.value, GraphAPIError)
    assert info.value.response.status_code == 400
    assert info.value.request.method == "GET"


def test_non_json_error_body_falls_back_to_reason_and_header_request_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(
        monkeypatch,
        httpx.Response(
            502, content=b"<html>Bad gateway</html>", headers={"request-id": "hdr-1"}
        ),
    )

    with pytest.raises(GraphAPIError) as info:
        graph.request("POST", "/me/sendMail", "acc-1", json={"m": 1})

    err = info.value
    assert err.status == 502
    assert err.code == ""
    assert err.message == "Bad Gateway"
    assert err.request_id == "hdr-1"


def test_graph_api_error_str_contains_no_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, httpx.Response(403, json=_graph_body("AccessDenied", "no")))

    with pytest.raises(GraphAPIError) as info:
        graph.request("GET", "/me/messages?$search=secret", "acc-1")

    assert not URL_PATTERN.search(str(info.value))
    assert "secret" not in str(info.value)


def test_429_carries_retry_after_after_retries_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    throttled = [httpx.Response(429, headers={"Retry-After": "2"}) for _ in range(4)]
    _install(monkeypatch, *throttled)

    with pytest.raises(GraphAPIError) as info:
        graph.request("GET", "/me", "acc-1")

    assert info.value.status == 429
    assert info.value.retry_after == 2.0


# --- Mapping to ToolError ---------------------------------------------------


def _err(
    status: int,
    code: str = "SomeGraphCode",
    message: str = "Graph said no.",
    retry_after: float | None = None,
) -> GraphAPIError:
    return GraphAPIError(status, code, message, REQUEST_ID, retry_after=retry_after)


def _text(exc: Exception, **kwargs: Any) -> str:
    tool_error = to_tool_error(exc, **kwargs)
    assert isinstance(tool_error, ToolError)
    return str(tool_error)


def test_400_explains_invalid_request_and_that_retry_will_not_help() -> None:
    text = _text(_err(400, message="Invalid filter clause"), tool="m365_list")
    assert "m365_list" in text
    assert "Invalid filter clause" in text
    assert "retrying unchanged will fail again" in text.lower()


def test_401_says_sign_in_again() -> None:
    text = _text(_err(401))
    assert "account_auth_begin" in text
    assert "sign" in text.lower()


def test_403_says_permission_missing() -> None:
    text = _text(_err(403))
    assert "permission" in text.lower()
    assert "will not help" in text.lower()


def test_404_is_resource_aware() -> None:
    text = _text(_err(404), tool="m365_get", resource="email")
    assert "No email with that id; ids come from m365_list or m365_search" in text


def test_404_without_resource_is_generic() -> None:
    text = _text(_err(404))
    assert "not found" in text.lower()
    assert "m365_list or m365_search" in text


def test_409_on_drive_item_suggests_if_exists() -> None:
    text = _text(_err(409), tool="drive_upload", resource="drive_item")
    assert "already exists" in text
    assert "if_exists='replace' or 'rename'" in text


def test_409_generic_is_a_conflict() -> None:
    text = _text(_err(409), resource="contact")
    assert "conflict" in text.lower()


def test_412_says_item_changed_and_to_reread() -> None:
    text = _text(_err(412))
    assert "changed" in text.lower()
    assert "m365_get" in text


def test_413_says_content_too_large() -> None:
    text = _text(_err(413))
    assert "too large" in text.lower()


def test_423_says_item_locked() -> None:
    text = _text(_err(423))
    assert "locked" in text.lower()


def test_429_after_retries_says_wait_n_seconds() -> None:
    text = _text(_err(429, retry_after=17.2))
    assert "throttling" in text.lower()
    assert "try again in 18 s" in text


def test_429_without_retry_after_still_says_when() -> None:
    text = _text(_err(429))
    assert "try again in 60 s" in text


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_5xx_says_temporary_and_to_verify_writes(status: int) -> None:
    text = _text(_err(status))
    assert "temporary" in text.lower()
    assert "try again" in text.lower()


def test_unlisted_4xx_has_generic_text() -> None:
    text = _text(_err(405))
    assert "rejected" in text.lower()


def test_deadline_exceeded_says_try_again_in_n_seconds() -> None:
    text = _text(DeadlineExceeded(12.1), tool="m365_list")
    assert "try again in 13 s" in text
    assert "m365_list" in text


def test_validation_error_text_is_kept() -> None:
    message = "Invalid limit '0': below minimum. Expected: 1-100"
    assert _text(ValidationError(message)) == message


def test_unexpected_exception_is_generic() -> None:
    text = _text(RuntimeError("boom at https://graph.microsoft.com/secret"))
    assert "unexpected" in text.lower()
    assert "boom" not in text


ALL_STATUSES = [400, 401, 403, 404, 405, 409, 412, 413, 423, 429, 500, 503, 504]
RESOURCES = [
    None,
    "email",
    "email_folder",
    "email_rule",
    "event",
    "calendar",
    "contact",
    "contact_folder",
    "drive_item",
    "operation",
]


@pytest.mark.parametrize("status", ALL_STATUSES)
@pytest.mark.parametrize("resource", RESOURCES)
def test_no_url_request_id_or_raw_code_in_any_message(
    status: int, resource: str | None
) -> None:
    err = _err(
        status,
        code="ErrorAccessDeniedSecretCode",
        message=(
            "See https://graph.microsoft.com/v1.0/me/messages?x=1 "
            "and http://example.com/help for details"
        ),
        retry_after=5,
    )
    text = _text(err, tool="m365_get", resource=resource)

    assert not URL_PATTERN.search(text), text
    assert "graph.microsoft.com" not in text
    assert REQUEST_ID not in text
    assert "ErrorAccessDeniedSecretCode" not in text
    assert "Traceback" not in text
    assert str(status) not in text
