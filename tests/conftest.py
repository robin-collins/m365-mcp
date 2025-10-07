from __future__ import annotations

from collections import deque
from typing import Any, Callable

import pytest

from src.microsoft_mcp import graph


@pytest.fixture
def mock_graph_request(monkeypatch: pytest.MonkeyPatch) -> Callable[[str, str, Any], None]:
    """Patch graph.request and allow registering responses."""

    responses: dict[tuple[str, str], Any] = {}

    def register(method: str, path: str, response: Any) -> None:
        responses[(method, path)] = response

    def fake_request(
        method: str,
        path: str,
        account_id: str | None = None,
        **kwargs: Any,
    ) -> Any:
        key = (method, path)
        if key not in responses:
            raise AssertionError(f"Unexpected Graph request: {method} {path}")
        value = responses[key]
        return value() if callable(value) else value

    monkeypatch.setattr(graph, "request", fake_request)
    return register


@pytest.fixture
def mock_graph_paginated(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[str, list[dict[str, Any]]], None]:
    """Patch graph.request_paginated with configurable payloads."""

    payloads: dict[str, deque[list[dict[str, Any]]]] = {}

    def register(path: str, pages: list[dict[str, Any]]) -> None:
        payloads.setdefault(path, deque()).append(pages)

    def fake_paginated(
        path: str,
        account_id: str | None = None,
        params: dict[str, Any] | None = None,
        limit: int | None = None,
    ):
        queue = payloads.get(path)
        if not queue:
            return iter(())
        page = queue.popleft()
        return iter(page)

    monkeypatch.setattr(graph, "request_paginated", fake_paginated)
    return register


@pytest.fixture
def mock_account_id() -> str:
    """Provide a reusable fake account identifier."""

    return "test-account"


@pytest.fixture
def mock_email_data() -> Callable[..., dict[str, Any]]:
    """Factory for building fake email payloads."""

    def _builder(**overrides: Any) -> dict[str, Any]:
        payload = {
            "id": "mock-email-id",
            "subject": "Test Subject",
            "body": {"contentType": "Text", "content": "Hello"},
            "hasAttachments": False,
        }
        payload.update(overrides)
        return payload

    return _builder


@pytest.fixture
def mock_file_metadata() -> Callable[..., dict[str, Any]]:
    """Factory for building fake OneDrive file metadata payloads."""

    def _builder(**overrides: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": "01ABCDEFZLMNO!123",
            "name": "example.txt",
            "size": 2048,
            "file": {"mimeType": "text/plain"},
            "@microsoft.graph.downloadUrl": (
                "https://graph.microsoft.com/v1.0/me/drive/items/01ABCDEFZLMNO!123/content"
            ),
        }
        payload.update(overrides)
        return payload

    return _builder
