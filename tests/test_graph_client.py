"""Unit tests for Graph client retry, token refresh and upload handling."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from src.m365_mcp import graph


class FakeClient:
    """Return queued responses/exceptions and record each request."""

    def __init__(self, outcomes: list[httpx.Response | Exception]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append({"method": method, "url": url, **kwargs})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        outcome.request = httpx.Request(method, url)
        return outcome


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []
    monkeypatch.setattr(graph.time, "sleep", recorded.append)
    return recorded


@pytest.fixture
def token_calls(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    calls: list[bool] = []

    def fake_get_token(account_id: str | None, force_refresh: bool = False) -> str:
        calls.append(force_refresh)
        return f"token-{len(calls)}"

    monkeypatch.setattr(graph, "get_token", fake_get_token)
    return calls


def _install(monkeypatch: pytest.MonkeyPatch, *outcomes: Any) -> FakeClient:
    client = FakeClient(list(outcomes))
    monkeypatch.setattr(graph, "_client", client)
    return client


def test_401_forces_one_token_refresh_and_retries(
    monkeypatch: pytest.MonkeyPatch, token_calls: list[bool], sleeps: list[float]
) -> None:
    client = _install(
        monkeypatch, httpx.Response(401), httpx.Response(200, json={"ok": True})
    )

    assert graph.request("GET", "/me", "acc-1") == {"ok": True}
    assert token_calls == [False, True]
    assert client.calls[1]["headers"]["Authorization"] == "Bearer token-2"
    assert sleeps == []


def test_repeated_401_is_raised_after_one_refresh(
    monkeypatch: pytest.MonkeyPatch, token_calls: list[bool], sleeps: list[float]
) -> None:
    _install(monkeypatch, httpx.Response(401), httpx.Response(401))

    with pytest.raises(httpx.HTTPStatusError):
        graph.request("GET", "/me", "acc-1")
    assert token_calls == [False, True]


def test_429_honours_http_date_retry_after(
    monkeypatch: pytest.MonkeyPatch, token_calls: list[bool], sleeps: list[float]
) -> None:
    _install(
        monkeypatch,
        httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}),
        httpx.Response(200, json={}),
    )

    graph.request("GET", "/me", "acc-1")
    # A date in the past means "retry now", not a ValueError.
    assert sleeps == [0.0]


def test_503_retry_after_seconds_is_used_and_capped(
    monkeypatch: pytest.MonkeyPatch, token_calls: list[bool], sleeps: list[float]
) -> None:
    _install(
        monkeypatch,
        httpx.Response(503, headers={"Retry-After": "7"}),
        httpx.Response(503, headers={"Retry-After": "600"}),
        httpx.Response(204),
    )

    assert graph.request("DELETE", "/me/messages/1", "acc-1") is None
    assert sleeps == [7.0, graph.MAX_RETRY_WAIT_SECONDS]


def test_post_is_not_retried_on_ambiguous_5xx(
    monkeypatch: pytest.MonkeyPatch, token_calls: list[bool], sleeps: list[float]
) -> None:
    """A 504 on sendMail may mean the mail went out; never resend it."""
    client = _install(monkeypatch, httpx.Response(504))

    with pytest.raises(httpx.HTTPStatusError):
        graph.request("POST", "/me/sendMail", "acc-1", json={"message": {}})
    assert len(client.calls) == 1


def test_get_is_retried_on_5xx(
    monkeypatch: pytest.MonkeyPatch, token_calls: list[bool], sleeps: list[float]
) -> None:
    _install(monkeypatch, httpx.Response(500), httpx.Response(200, json={"v": 1}))

    assert graph.request("GET", "/me", "acc-1") == {"v": 1}
    assert sleeps == [1]


def test_connect_error_is_retried_for_any_method(
    monkeypatch: pytest.MonkeyPatch, token_calls: list[bool], sleeps: list[float]
) -> None:
    _install(
        monkeypatch,
        httpx.ConnectError("dns failure"),
        httpx.Response(202),
    )

    assert graph.request("POST", "/me/sendMail", "acc-1", json={"m": 1}) is None
    assert sleeps == [1]


def test_read_timeout_is_not_retried_for_post(
    monkeypatch: pytest.MonkeyPatch, token_calls: list[bool], sleeps: list[float]
) -> None:
    client = _install(monkeypatch, httpx.ReadTimeout("slow"))

    with pytest.raises(httpx.ReadTimeout):
        graph.request("POST", "/me/sendMail", "acc-1", json={"m": 1})
    assert len(client.calls) == 1


def test_read_timeout_is_retried_for_get(
    monkeypatch: pytest.MonkeyPatch, token_calls: list[bool], sleeps: list[float]
) -> None:
    _install(monkeypatch, httpx.ReadTimeout("slow"), httpx.Response(200, content=b"x"))

    assert graph.download_raw("/me/drive/items/1/content", "acc-1") == b"x"


def test_chunked_upload_sends_no_authorization_and_accepts_empty_201(
    monkeypatch: pytest.MonkeyPatch, token_calls: list[bool], sleeps: list[float]
) -> None:
    monkeypatch.setattr(graph, "UPLOAD_CHUNK_SIZE", 4)
    client = _install(monkeypatch, httpx.Response(202), httpx.Response(201))

    assert graph._do_chunked_upload("https://upload.example/session", b"abcdef") == {}
    assert token_calls == []
    assert all("Authorization" not in call["headers"] for call in client.calls)
    assert client.calls[1]["headers"]["Content-Range"] == "bytes 4-5/6"


def test_request_does_not_mutate_caller_params(
    monkeypatch: pytest.MonkeyPatch, token_calls: list[bool], sleeps: list[float]
) -> None:
    client = _install(monkeypatch, httpx.Response(200, json={"value": []}))
    params = {"$search": '"invoice"'}

    graph.request("GET", "/me/messages", "acc-1", params=params)

    assert params == {"$search": '"invoice"'}
    assert client.calls[0]["params"]["$count"] == "true"


def test_paginated_next_pages_keep_query_headers(
    monkeypatch: pytest.MonkeyPatch, token_calls: list[bool], sleeps: list[float]
) -> None:
    """Page 2+ must keep plain-text bodies and eventual consistency."""
    next_link = f"{graph.BASE_URL}/me/messages?$search=x&$skiptoken=abc"
    client = _install(
        monkeypatch,
        httpx.Response(200, json={"value": [{"id": 1}], "@odata.nextLink": next_link}),
        httpx.Response(200, json={"value": [{"id": 2}]}),
    )

    items = list(
        graph.request_paginated(
            "/me/messages", "acc-1", params={"$search": "x", "$select": "body"}
        )
    )

    assert [item["id"] for item in items] == [1, 2]
    second = client.calls[1]
    assert second["url"] == next_link
    assert second["params"] is None
    assert second["headers"]["ConsistencyLevel"] == "eventual"
    assert second["headers"]["Prefer"] == 'outlook.body-content-type="text"'
