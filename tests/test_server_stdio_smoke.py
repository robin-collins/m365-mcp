"""Start the real server over stdio and list its tools (no Graph calls)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

DEFAULT_TOOL_COUNT = 23


def test_stdio_server_lists_default_tools(tmp_path: Path) -> None:
    """`python -m m365_mcp.server` serves the unified default tool set."""
    env = {
        **os.environ,
        "M365_MCP_CLIENT_ID": "test",
        "M365_MCP_CACHE_KEY": "test-key",
        "MCP_LOG_DIR": str(tmp_path / "logs"),
        "M365_MCP_CACHE_DB_PATH": str(tmp_path / "cache.db"),
    }
    env.pop("M365_MCP_TOOLSETS", None)
    env.pop("M365_MCP_LIVE_TESTS", None)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "m365_mcp.server", "--env-file", str(tmp_path / "none.env")],
        env=env,
        cwd=str(tmp_path),
    )

    async def run() -> list[str]:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return [tool.name for tool in (await session.list_tools()).tools]

    names = anyio.run(run)
    assert len(names) == DEFAULT_TOOL_COUNT
    assert "m365_list" in names
