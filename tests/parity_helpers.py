"""Shared helpers for the mapping-row parity tests (task U3.30).

``docs/unified-tools/legacy_mapping.json`` is the migration record of the
retired legacy tools. Each row is exercised in ``tests/test_parity.py``
against the unified surface only; these helpers open a fresh, seeded
surface and expose the pristine seed for baselines.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

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


def seeded_copy() -> FakeGraph:
    """A pristine seeded fake Graph (the baseline every scenario starts from)."""
    return FakeGraph.seeded(ANCHOR)
