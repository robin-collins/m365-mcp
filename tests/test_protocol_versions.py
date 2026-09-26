"""Protocol-version interop matrix (H2).

The server runs on FastMCP 4 / MCP SDK 2, which speak both the
``initialize``-handshake era (up to 2025-11-25) and the stateless
2026-07-28 revision. Each connect mode below must list the tools and run a
read call end to end, and the negotiated version must be the expected one.
"""

from __future__ import annotations

import asyncio

import pytest
from mcp import Client
from mcp_types.version import (
    HANDSHAKE_PROTOCOL_VERSIONS,
    LATEST_PROTOCOL_VERSION,
    MODERN_PROTOCOL_VERSIONS,
)

MODES = [
    ("legacy", HANDSHAKE_PROTOCOL_VERSIONS),
    ("auto", (LATEST_PROTOCOL_VERSION,)),
    (MODERN_PROTOCOL_VERSIONS[-1], (MODERN_PROTOCOL_VERSIONS[-1],)),
]


@pytest.mark.parametrize(("mode", "expected"), MODES, ids=[m for m, _ in MODES])
def test_negotiation_and_call(harness, mode: str, expected: tuple[str, ...]) -> None:
    async def run():
        async with Client(harness.surface.server._mcp_server, mode=mode) as client:
            tools = await client.list_tools()
            result = await client.call_tool(
                "m365_list", {"resource": "email", "limit": 3}
            )
            return client.protocol_version, tools, result

    version, tools, result = asyncio.run(run())
    assert version in expected
    assert len(tools.tools) == 29  # the harness registers every tier
    assert not result.is_error, result.content
    assert result.structured_content is not None


def test_server_info_lists_every_supported_version(harness) -> None:
    from mcp_types.version import SUPPORTED_PROTOCOL_VERSIONS

    info = harness.ok("admin_server_info", {})
    assert info["protocol_versions"] == list(SUPPORTED_PROTOCOL_VERSIONS)
    assert "2026-07-28" in info["protocol_versions"]
