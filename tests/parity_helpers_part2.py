"""Helpers for the legacy-vs-unified parity tests (mapping rows 43-84).

``run_legacy`` runs a legacy tool on the legacy surface against its own
freshly seeded fake Graph and returns that graph, so a test can compare the
legacy end state with the state the unified call left in the harness graph.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
from fastmcp import Client

from evals.fake_graph import ACCOUNT_ID, FakeGraph
from evals.surface import open_surface
from tests.unified_harness import ANCHOR, UnifiedHarness


@dataclass
class LegacyRun:
    """Result of one legacy tool call and the fake Graph it left behind."""

    is_error: bool
    text: str
    data: Any
    graph: FakeGraph
    sandbox_files: dict[str, bytes]


def run_legacy(
    tool: str,
    args: dict[str, Any],
    prepare: Callable[[FakeGraph], None] | None = None,
) -> LegacyRun:
    """Call legacy ``tool`` (account_id added) on a fresh seeded fake Graph."""
    # The harness fixture already routed httpx.Client to ITS fake Graph; a
    # nested open_surface would wrap that router. Use the real class so the
    # legacy surface talks to its own fake.
    outer_client = httpx.Client
    httpx.Client = httpx._client.Client  # type: ignore[misc]
    try:
        return _run_legacy(tool, args, prepare)
    finally:
        httpx.Client = outer_client  # type: ignore[misc]


def _run_legacy(
    tool: str,
    args: dict[str, Any],
    prepare: Callable[[FakeGraph], None] | None,
) -> LegacyRun:
    with open_surface("legacy", ANCHOR) as surface:
        if prepare is not None:
            prepare(surface.graph)
        call_args = dict(args)
        if tool != "server_get_version":
            call_args.setdefault("account_id", ACCOUNT_ID)

        async def go() -> Any:
            async with Client(surface.server) as client:
                return await client.call_tool(tool, call_args, raise_on_error=False)

        result = asyncio.run(go())
        text = "\n".join(getattr(b, "text", "") for b in result.content)
        data = result.structured_content
        if data is None:
            data = getattr(result, "data", None)
        files = {
            p.name: p.read_bytes() for p in surface.sandbox.iterdir() if p.is_file()
        }
        return LegacyRun(bool(result.is_error), text, data, surface.graph, files)


def seeded_copy() -> FakeGraph:
    """A pristine seeded fake Graph (for baseline comparisons)."""
    return FakeGraph.seeded(ANCHOR)


def compare(
    harness: UnifiedHarness,
    legacy: LegacyRun,
    view: Callable[[FakeGraph], Any],
) -> Any:
    """Assert legacy and unified end states match on ``view`` and moved.

    The shared ``view`` must differ from the pristine seed, so a no-op on
    either side fails. Returns the (equal) view for further assertions.
    """
    assert not legacy.is_error, legacy.text
    assert view(legacy.graph) == view(harness.fake)
    assert view(harness.fake) != view(seeded_copy()), "state did not change"
    return view(harness.fake)
