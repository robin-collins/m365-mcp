"""Tests for Graph JSON batching (task U2.8)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from src.m365_mcp import graph

BatchHandler = Callable[[list[dict[str, Any]]], list[dict[str, Any]]]


class FakeBatchClient:
    """Answer POST /$batch calls with per-item responses from a handler."""

    def __init__(self, handler: BatchHandler) -> None:
        self.handler = handler
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append({"method": method, "url": url, **kwargs})
        items = kwargs["json"]["requests"]
        # Graph may answer out of order; the client must reorder by id.
        responses = list(reversed(self.handler(items)))
        response = httpx.Response(200, json={"responses": responses})
        response.request = httpx.Request(method, url)
        return response

    def sent_ids(self) -> list[list[str]]:
        return [[r["id"] for r in c["json"]["requests"]] for c in self.calls]


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []
    monkeypatch.setattr(graph.time, "sleep", recorded.append)
    monkeypatch.setattr(graph, "get_token", lambda _a, force_refresh=False: "token")
    return recorded


def _install(monkeypatch: pytest.MonkeyPatch, handler: BatchHandler) -> FakeBatchClient:
    client = FakeBatchClient(handler)
    monkeypatch.setattr(graph, "_client", client)
    return client


def _ok(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"id": i["id"], "status": 200, "headers": {}, "body": {"url": i["url"]}}
        for i in items
    ]


def test_empty_batch_makes_no_call(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    client = _install(monkeypatch, _ok)
    assert graph.batch([], "acc-1") == []
    assert client.calls == []


def test_batch_posts_to_batch_endpoint_with_relative_urls(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    client = _install(monkeypatch, _ok)

    graph.batch(
        [
            {"method": "GET", "url": "/me/messages/1"},
            {"method": "PATCH", "url": "/me/messages/2", "body": {"isRead": True}},
        ],
        "acc-1",
    )

    call = client.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == f"{graph.BASE_URL}/$batch"
    sent = call["json"]["requests"]
    assert sent[0] == {"id": "0", "method": "GET", "url": "/me/messages/1"}
    assert sent[1]["body"] == {"isRead": True}
    assert sent[1]["headers"] == {"Content-Type": "application/json"}


def test_batch_chunks_at_20_and_keeps_input_order(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    client = _install(monkeypatch, _ok)
    requests = [{"method": "GET", "url": f"/me/messages/{n}"} for n in range(45)]

    results = graph.batch(requests, "acc-1")

    assert [len(ids) for ids in client.sent_ids()] == [20, 20, 5]
    assert [r["id"] for r in results] == [str(n) for n in range(45)]
    assert [r["body"]["url"] for r in results] == [
        f"/me/messages/{n}" for n in range(45)
    ]
    assert all(r["status"] == 200 for r in results)


def test_batch_returns_caller_ids(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    _install(monkeypatch, _ok)

    results = graph.batch(
        [
            {"id": "first", "method": "GET", "url": "/me"},
            {"id": "second", "method": "GET", "url": "/me/drive"},
        ],
        "acc-1",
    )

    assert [r["id"] for r in results] == ["first", "second"]


def test_partial_failure_returns_per_item_results_without_raising(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    def handler(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = _ok(items)
        out[1] = {
            "id": items[1]["id"],
            "status": 404,
            "headers": {},
            "body": {"error": {"code": "ErrorItemNotFound", "message": "gone"}},
        }
        out[2]["status"] = 500
        out[2]["body"] = {"error": {"code": "generalException", "message": "x"}}
        return out

    client = _install(monkeypatch, handler)

    results = graph.batch(
        [
            {"method": "GET", "url": "/me/messages/1"},
            {"method": "GET", "url": "/me/messages/2"},
            {"method": "POST", "url": "/me/messages/3/move", "body": {"d": "x"}},
        ],
        "acc-1",
    )

    assert [r["status"] for r in results] == [200, 404, 500]
    assert results[1]["body"]["error"]["code"] == "ErrorItemNotFound"
    # 404 is final and the POST is never resent.
    assert len(client.calls) == 1
    assert sleeps == []


def test_throttled_idempotent_items_are_retried_with_retry_after(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    rounds: list[list[str]] = []

    def handler(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rounds.append([i["id"] for i in items])
        out = _ok(items)
        if len(rounds) == 1:
            out[1] = {
                "id": items[1]["id"],
                "status": 429,
                "headers": {"Retry-After": "7"},
                "body": {"error": {"code": "TooManyRequests", "message": "slow"}},
            }
            out[2] = {
                "id": items[2]["id"],
                "status": 429,
                "headers": {"Retry-After": "3"},
                "body": {},
            }
        return out

    _install(monkeypatch, handler)

    results = graph.batch(
        [
            {"method": "GET", "url": "/me/messages/1"},
            {"method": "GET", "url": "/me/messages/2"},
            {"method": "DELETE", "url": "/me/messages/3"},
        ],
        "acc-1",
    )

    assert rounds == [["0", "1", "2"], ["1", "2"]]
    # One wait covering the longest Retry-After among throttled items.
    assert sleeps == [7.0]
    assert [r["status"] for r in results] == [200, 200, 200]
    assert results[1]["body"] == {"url": "/me/messages/2"}


@pytest.mark.parametrize("method", ["POST", "PATCH"])
def test_non_idempotent_items_are_never_retried(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float], method: str
) -> None:
    def handler(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {"id": i["id"], "status": 429, "headers": {"Retry-After": "1"}}
            for i in items
        ]

    client = _install(monkeypatch, handler)

    results = graph.batch(
        [{"method": method, "url": "/me/messages/1", "body": {"a": 1}}], "acc-1"
    )

    assert len(client.calls) == 1
    assert sleeps == []
    assert results[0]["status"] == 429


def test_throttled_items_are_returned_after_max_retries(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    def handler(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {"id": i["id"], "status": 429, "headers": {"Retry-After": "1"}}
            for i in items
        ]

    client = _install(monkeypatch, handler)

    results = graph.batch([{"method": "GET", "url": "/me"}], "acc-1", max_retries=2)

    assert len(client.calls) == 3
    assert sleeps == [1.0, 1.0]
    assert results[0]["status"] == 429


def test_batch_stops_retrying_at_the_deadline(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    """Retries stop once the read deadline would be exceeded."""
    now = [0.0]
    monkeypatch.setattr(graph, "_clock", lambda: now[0])
    monkeypatch.setattr(graph.time, "sleep", lambda s: now.__setitem__(0, now[0] + s))

    def handler(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {"id": i["id"], "status": 429, "headers": {"Retry-After": "30"}}
            for i in items
        ]

    client = _install(monkeypatch, handler)

    results = graph.batch([{"method": "GET", "url": "/me"}], "acc-1")

    # 30 s fits in the 45 s read budget; a second 30 s wait would not.
    assert len(client.calls) == 2
    assert now[0] == 30.0
    assert results[0]["status"] == 429
