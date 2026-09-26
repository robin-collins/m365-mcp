"""Outputs validate for a standards-based MCP client (the official SDK).

The SDK client validates ``structuredContent`` against each tool's
``outputSchema`` with a JSON Schema validator, as real MCP hosts do. This
guards against schemas that our server accepts but other clients reject.
"""

from __future__ import annotations

import asyncio

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

CALLS = [
    ("m365_list", {"resource": resource, "limit": 3})
    for resource in (
        "email",
        "email_folder",
        "email_rule",
        "event",
        "calendar",
        "contact",
        "contact_folder",
        "drive_item",
    )
] + [
    ("m365_list", {"resource": "email_folder", "recursive": True}),
    ("m365_list", {"resource": "drive_item", "recursive": True, "item_type": "folder"}),
    ("m365_search", {"query": "budget"}),
    ("m365_get", {"resource": "email", "id": "msg-006"}),
    ("m365_get", {"resource": "event", "id": "evt-sync"}),
    ("m365_get", {"resource": "contact", "id": "contact-jane"}),
    ("m365_get", {"resource": "drive_item", "path": "/Documents"}),
    (
        "calendar_find_availability",
        {
            "start": "2026-09-29T00:00:00+00:00",
            "end": "2026-09-30T00:00:00+00:00",
            "slot_minutes": 30,
        },
    ),
    ("admin_server_info", {}),
    ("account_list", {}),
]


@pytest.mark.parametrize(
    ("tool", "args"), CALLS, ids=[f"{t}-{a.get('resource', '')}" for t, a in CALLS]
)
def test_sdk_client_accepts_output(harness, tool, args) -> None:
    async def run():
        async with create_connected_server_and_client_session(
            harness.surface.server._mcp_server
        ) as client:
            await client.list_tools()  # the SDK reads output schemas here
            return await client.call_tool(tool, args)

    result = asyncio.run(run())
    assert not result.isError, result.content
    assert result.structuredContent is not None
