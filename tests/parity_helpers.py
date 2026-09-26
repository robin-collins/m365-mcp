"""Shared helpers for the legacy-to-unified parity tests (task U3.30).

A parity scenario performs one practical task twice: once through the
legacy tool surface and once through the unified surface, each against a
fresh, identically seeded fake Graph, so the two end states can be
compared. The legacy surface is opened and closed before the unified one
(``open_surface`` patches process-wide transport state, so the two must not
overlap).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastmcp import Client

from evals.fake_graph import FakeGraph
from evals.surface import open_surface
from tests.unified_harness import ANCHOR, UnifiedHarness

MAPPING_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "unified-tools"
    / "legacy_mapping.json"
)


def mapping_row(index: int) -> dict[str, Any]:
    """Return row ``index`` of ``legacy_mapping.json``."""
    return json.loads(MAPPING_PATH.read_text(encoding="utf-8"))["mapping"][index]


class LegacyRunner:
    """Call legacy tools in memory and expose the fake Graph behind them."""

    def __init__(self, surface: Any) -> None:
        self.surface = surface
        self.fake: FakeGraph = surface.graph

    def call(self, tool: str, arguments: dict[str, Any] | None = None) -> Any:
        """Call a legacy tool; raise ``AssertionError`` if it reports an error.

        Returns the structured content (unwrapping FastMCP's ``result`` key
        for list results) or the parsed JSON text.
        """

        async def run() -> Any:
            async with Client(self.surface.server) as client:
                return await client.call_tool(
                    tool, arguments or {}, raise_on_error=False
                )

        result = asyncio.run(run())
        text = "\n".join(getattr(b, "text", "") for b in result.content)
        assert not result.is_error, f"legacy {tool} failed: {text}"
        data = result.structured_content
        if isinstance(data, dict) and set(data) == {"result"}:
            return data["result"]
        if data is not None:
            return data
        try:
            return json.loads(text)
        except ValueError:
            return text


@contextmanager
def legacy_session() -> Iterator[LegacyRunner]:
    """A fresh legacy tool surface over a freshly seeded fake Graph."""
    with open_surface("legacy", ANCHOR) as surface:
        yield LegacyRunner(surface)


@contextmanager
def unified_session() -> Iterator[UnifiedHarness]:
    """A fresh unified surface (all toolsets); same setup as ``harness``."""
    from m365_mcp.rate_limit import RateLimiter
    from m365_mcp.tools.unified import common

    real = common.rate_limiter
    common.rate_limiter = RateLimiter()
    try:
        with open_surface("unified", ANCHOR, "core,extended,admin") as surface:
            yield UnifiedHarness(surface)
    finally:
        common.rate_limiter = real
