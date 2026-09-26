"""Output contract of the unified tools (task U2.4).

Handlers return a result dict; the server returns it as
``structuredContent`` plus one text block holding the same data as JSON.
Per the MCP spec, ``structuredContent`` is not guaranteed to reach the
model (many clients, including a plain Anthropic-API tool loop, only see
``content``), so the text block must be "functionally equivalent" to the
structured content, not a bare one-line count: a live evaluation run
found that a summary-only text block collapsed task success from 91% to
50%, because the model could never see item ids or subjects to act on.
Under pytest (test mode) every result is validated against the tool's
``outputSchema``, so all handler tests check the output contract.
"""

from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from mcp.types import CallToolResult, TextContent

from m365_mcp.tools import handlers, registry

ROOT = Path(__file__).resolve().parent.parent
SPEC_DIR = ROOT / "docs" / "unified-tools"
INDEX = json.loads((SPEC_DIR / "index.json").read_text(encoding="utf-8"))
SPECS = {
    name: json.loads((SPEC_DIR / "tools" / f"{name}.json").read_text(encoding="utf-8"))
    for name in INDEX["tool_order"]
}
EXAMPLES = [
    pytest.param(name, example, id=f"{name}-{i}")
    for name, spec in SPECS.items()
    for i, example in enumerate(spec["examples"])
]
DELETE_OK = {
    "resource": "email",
    "id": "x",
    "status": "deleted",
    "recoverable": False,
    "summary": "Deleted the email.",
}
DELETE_ARGS = {"resource": "email", "id": "x", "confirm": True}


@pytest.fixture(autouse=True)
def isolated_registries(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(handlers, "HANDLERS", {})
    monkeypatch.setattr(handlers, "VALIDATION_RULES", {})
    monkeypatch.delenv(registry.VALIDATE_OUTPUT_ENV, raising=False)
    yield


@pytest.fixture(scope="module")
def server() -> FastMCP:
    return registry.build_server("core,extended,admin")


def call(server: FastMCP, name: str, arguments: dict[str, Any]) -> CallToolResult:
    async def run() -> CallToolResult:
        async with Client(server) as client:
            result = await client.call_tool_mcp(name, arguments)
        return result

    return asyncio.run(run())


def text_of(result: CallToolResult) -> str:
    (block,) = result.content
    assert isinstance(block, TextContent)
    return block.text


def test_output_validation_is_on_under_pytest() -> None:
    assert registry.output_validation_enabled()


@pytest.mark.parametrize(
    ("value", "enabled"),
    [("1", True), ("true", True), ("yes", True), ("0", False), ("false", False)],
)
def test_output_validation_env_override(
    monkeypatch: pytest.MonkeyPatch, value: str, enabled: bool
) -> None:
    monkeypatch.setenv(registry.VALIDATE_OUTPUT_ENV, value)
    assert registry.output_validation_enabled() is enabled


@pytest.mark.parametrize(("name", "example"), EXAMPLES)
def test_example_outputs_round_trip(
    server: FastMCP, name: str, example: dict[str, Any]
) -> None:
    output = copy.deepcopy(example["output"])
    handlers.register_handler(name)(lambda args: output)
    result = call(server, name, example["input"])
    assert not result.isError, text_of(result)
    assert result.structuredContent == example["output"]
    # The text block is the same data as JSON, so a text-only consumer
    # (no structuredContent) still sees everything, per the MCP spec's
    # "SHOULD also return the serialized JSON in a TextContent block".
    assert json.loads(text_of(result)) == example["output"]


def _email_summary(item_id: str, subject: str) -> dict[str, Any]:
    """A schema-valid ``email_summary`` record for the test below."""
    return {
        "id": item_id,
        "conversation_id": None,
        "subject": subject,
        "from": {"name": "Sender", "address": "sender@example.com"},
        "to": [],
        "cc": [],
        "received_at": "2026-09-20T08:15:00+09:30",
        "is_read": False,
        "has_attachments": False,
        "importance": "normal",
        "flag_status": "not_flagged",
        "categories": [],
        "preview": None,
        "folder_id": "junk",
    }


def test_text_block_carries_item_details_not_just_a_count(server: FastMCP) -> None:
    """A list result's text must let the model act without structuredContent.

    Regression test: a live evaluation run showed the model unable to name
    or act on any listed item when the text block held only
    ``"Returned 2 emails from junk."``.
    """
    output = {
        "resource": "email",
        "items": [
            _email_summary("msg-008", "You won a prize!!!"),
            _email_summary("msg-009", "Double your crypto today"),
        ],
        "next_cursor": None,
        "has_more": False,
        "summary": "Returned 2 emails from junk.",
    }
    handlers.register_handler("m365_list")(lambda args: output)
    result = call(server, "m365_list", {"resource": "email", "container_id": "junk"})
    assert not result.isError, text_of(result)
    text = text_of(result)
    assert "msg-008" in text and "You won a prize!!!" in text
    assert "msg-009" in text and "Double your crypto today" in text


def test_async_handler_is_awaited(server: FastMCP) -> None:
    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        return dict(DELETE_OK)

    handlers.register_handler("m365_delete")(handler)
    result = call(server, "m365_delete", DELETE_ARGS)
    assert not result.isError
    assert result.structuredContent == DELETE_OK
    assert json.loads(text_of(result)) == DELETE_OK


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        ({"status": "gone"}, "status"),
        ({"recoverable": None}, "recoverable"),
        ({"summary": 5}, "summary"),
    ],
)
def test_schema_mismatch_fails_loudly(
    server: FastMCP, change: dict[str, Any], fragment: str
) -> None:
    handlers.register_handler("m365_delete")(lambda args: {**DELETE_OK, **change})
    result = call(server, "m365_delete", DELETE_ARGS)
    assert result.isError
    text = text_of(result)
    assert text.startswith("Output contract violation in m365_delete")
    assert fragment in text


def test_format_mismatch_fails_in_test_mode_only(
    server: FastMCP, monkeypatch: pytest.MonkeyPatch
) -> None:
    example = SPECS["calendar_create_event"]["examples"][0]
    output = copy.deepcopy(example["output"])
    output["event"]["start"] = "next tuesday"
    handlers.register_handler("calendar_create_event")(lambda args: output)

    result = call(server, "calendar_create_event", example["input"])
    assert result.isError
    assert "Output contract violation in calendar_create_event" in text_of(result)
    assert "event.start" in text_of(result)

    monkeypatch.setenv(registry.VALIDATE_OUTPUT_ENV, "0")
    result = call(server, "calendar_create_event", example["input"])
    assert not result.isError
    assert result.structuredContent == output


@pytest.mark.parametrize("output", [None, ["x"], {"resource": "email"}])
def test_result_must_be_dict_with_summary_even_outside_test_mode(
    server: FastMCP, monkeypatch: pytest.MonkeyPatch, output: Any
) -> None:
    monkeypatch.setenv(registry.VALIDATE_OUTPUT_ENV, "0")
    handlers.register_handler("m365_delete")(lambda args: output)
    result = call(server, "m365_delete", DELETE_ARGS)
    assert result.isError
    assert text_of(result).startswith("Output contract violation in m365_delete")
