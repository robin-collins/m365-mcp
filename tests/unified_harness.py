"""Test harness for unified tool handlers.

Runs the real unified server (``registry.build_server``) against the
deterministic fake Graph from ``evals/fake_graph.py`` (seeded by
``evals/fixtures.py``), with one signed-in personal account.

The ``harness`` fixture is registered in ``tests/conftest.py``::

    def test_something(harness: UnifiedHarness) -> None:
        result = harness.call("m365_list", {"resource": "email"})
        assert not result.is_error
        assert harness.graph_calls("GET", "/me/mailFolders/inbox/messages")
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from typing import Any

import pytest
from fastmcp import Client

from evals.fake_graph import ACCOUNT_EMAIL, ACCOUNT_ID, FakeGraph, RecordedCall
from evals.surface import Surface, open_surface

ANCHOR = date(2026, 9, 28)  # a Monday


@dataclass
class CallResult:
    """Outcome of one tool call."""

    is_error: bool
    text: str
    data: dict[str, Any] | None


class UnifiedHarness:
    """Call unified tools in memory and inspect the fake Graph."""

    account_id = ACCOUNT_ID
    account_email = ACCOUNT_EMAIL

    def __init__(self, surface: Surface) -> None:
        self.surface = surface
        self.fake: FakeGraph = surface.graph
        self.sandbox = surface.sandbox

    def call(self, tool: str, arguments: dict[str, Any]) -> CallResult:
        """Call ``tool`` and return its text and structured content."""

        async def run() -> CallResult:
            async with Client(self.surface.server) as client:
                result = await client.call_tool(tool, arguments, raise_on_error=False)
            text = "\n".join(getattr(b, "text", "") for b in result.content)
            return CallResult(bool(result.is_error), text, result.structured_content)

        return asyncio.run(run())

    def ok(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call ``tool``, assert success and return the structured content."""
        result = self.call(tool, arguments)
        assert not result.is_error, result.text
        assert result.data is not None
        return result.data

    def error(self, tool: str, arguments: dict[str, Any]) -> str:
        """Call ``tool``, assert it failed and return the error text."""
        result = self.call(tool, arguments)
        assert result.is_error, f"expected an error, got {result.data}"
        return result.text

    def graph_calls(
        self, method: str | None = None, path: str | None = None
    ) -> list[RecordedCall]:
        """Return recorded Graph requests, optionally filtered."""
        return [
            c
            for c in self.fake.calls
            if (method is None or c.method == method.upper())
            and (path is None or c.path == path)
        ]

    def clear_calls(self) -> None:
        """Forget recorded Graph requests."""
        self.fake.calls.clear()


@pytest.fixture
def harness() -> Iterator[UnifiedHarness]:
    """A fresh unified server and fake Graph for one test (all toolsets).

    The process-wide rate limiter is replaced per test, so sends and deletes
    from earlier tests cannot exhaust the 20-per-minute bucket.
    """
    from m365_mcp.rate_limit import RateLimiter
    from m365_mcp.tools.unified import common

    real = common.rate_limiter
    common.rate_limiter = RateLimiter()
    try:
        with open_surface("unified", ANCHOR, "core,extended,admin") as surface:
            yield UnifiedHarness(surface)
    finally:
        common.rate_limiter = real
