"""Live read-only checks of the unified tools on a real personal account (U3.31).

Runs only with ``M365_MCP_LIVE_TESTS=1`` and a signed-in account
(``uv run authenticate.py``). Every call is a read: list, get and search
for each resource. Nothing is created, changed or deleted.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastmcp import Client

pytestmark = pytest.mark.skipif(
    os.getenv("M365_MCP_LIVE_TESTS") != "1",
    reason="live account test; set M365_MCP_LIVE_TESTS=1 to run",
)

LIST_RESOURCES = [
    "email",
    "email_folder",
    "email_rule",
    "event",
    "calendar",
    "contact",
    "contact_folder",
    "drive_item",
]
SEARCH_RESOURCES = ["email", "event", "contact", "drive_item"]


@pytest.fixture(scope="module")
def server():
    from m365_mcp.tools.registry import build_server

    return build_server("core,extended,admin")


def _call(server, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    async def run() -> dict[str, Any]:
        async with Client(server) as client:
            result = await client.call_tool(tool, args, raise_on_error=False)
        text = "\n".join(getattr(b, "text", "") for b in result.content)
        assert not result.is_error, f"{tool}({args}) failed: {text}"
        assert result.structured_content is not None
        return result.structured_content

    return asyncio.run(run())


def test_account_is_signed_in(server) -> None:
    accounts = _call(server, "account_list", {})["accounts"]
    assert len(accounts) >= 1


@pytest.mark.parametrize("resource", LIST_RESOURCES)
def test_list_then_get_each_resource(server, resource: str) -> None:
    args: dict[str, Any] = {"resource": resource, "limit": 3}
    if resource == "event":
        now = datetime.now(UTC)
        args["start"] = (now - timedelta(days=30)).isoformat()
        args["end"] = (now + timedelta(days=30)).isoformat()
    listed = _call(server, "m365_list", args)
    assert listed["resource"] == resource
    assert "summary" in listed
    items = listed["items"]
    if not items:
        pytest.skip(f"no {resource} items on this account")
    got = _call(server, "m365_get", {"resource": resource, "id": items[0]["id"]})
    assert got["item"]["id"] == items[0]["id"]


def test_list_supports_cursors(server) -> None:
    first = _call(server, "m365_list", {"resource": "email", "limit": 2})
    if not first["has_more"]:
        pytest.skip("mailbox has too few messages to page")
    second = _call(
        server,
        "m365_list",
        {"resource": "email", "limit": 2, "cursor": first["next_cursor"]},
    )
    first_ids = {i["id"] for i in first["items"]}
    assert first_ids.isdisjoint(i["id"] for i in second["items"])


@pytest.mark.parametrize("resource", SEARCH_RESOURCES)
def test_search_each_resource(server, resource: str) -> None:
    result = _call(
        server, "m365_search", {"query": "the", "resources": [resource], "limit": 5}
    )
    assert "summary" in result
    for item in result["items"]:
        assert item["resource"] == resource


def test_drive_root_by_path_and_availability(server) -> None:
    root = _call(server, "m365_get", {"resource": "drive_item", "path": "/"})
    assert root["item"]["item_type"] == "folder"
    now = datetime.now(UTC)
    busy = _call(
        server,
        "calendar_find_availability",
        {
            "start": now.isoformat(),
            "end": (now + timedelta(days=2)).isoformat(),
            "slot_minutes": 30,
        },
    )
    assert "busy" in busy and "summary" in busy
