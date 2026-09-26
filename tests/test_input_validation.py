"""Runtime input validation of the unified tools (task U2.3).

Every call is validated against the tool's ``inputSchema`` (Draft 2020-12
with a format checker) before its semantic rules and handler run.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from m365_mcp.tools import handlers, registry
from m365_mcp.validators import ValidationError
from tests.test_unified_tool_specs import INVALID_INPUT_CASES

ROOT = Path(__file__).resolve().parent.parent
SPEC_DIR = ROOT / "docs" / "unified-tools"
INDEX = json.loads((SPEC_DIR / "index.json").read_text(encoding="utf-8"))
SPECS = {
    name: json.loads((SPEC_DIR / "tools" / f"{name}.json").read_text(encoding="utf-8"))
    for name in INDEX["tool_order"]
}
ERROR_FORMAT = re.compile(r"^Invalid \S+ '.*': .+\. Expected: .+$", re.DOTALL)
EXAMPLES = [
    pytest.param(name, example["input"], id=f"{name}-{i}")
    for name, spec in SPECS.items()
    for i, example in enumerate(spec["examples"])
]


@pytest.fixture(autouse=True)
def isolated_registries(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Give each test empty handler and rule registries."""
    monkeypatch.setattr(handlers, "HANDLERS", {})
    monkeypatch.setattr(handlers, "VALIDATION_RULES", {})
    yield


@pytest.fixture(scope="module")
def server() -> FastMCP:
    return registry.build_server("core,extended,admin")


def call(server: FastMCP, name: str, arguments: dict[str, Any]) -> tuple[bool, str]:
    """Call a tool in memory and return (is_error, first text block)."""

    async def run() -> tuple[bool, str]:
        async with Client(server) as client:
            result = await client.call_tool(name, arguments, raise_on_error=False)
        return result.is_error, result.content[0].text  # type: ignore[union-attr]

    return asyncio.run(run())


def error_text(server: FastMCP, name: str, arguments: dict[str, Any]) -> str:
    is_error, text = call(server, name, arguments)
    assert is_error, f"{name} accepted {arguments}"
    return text


@pytest.mark.parametrize(("name", "arguments"), INVALID_INPUT_CASES)
def test_invalid_input_corpus_is_rejected_at_runtime(
    server: FastMCP, name: str, arguments: dict[str, Any]
) -> None:
    text = error_text(server, name, arguments)
    assert ERROR_FORMAT.match(text), text
    assert "not implemented" not in text


@pytest.mark.parametrize(("name", "arguments"), EXAMPLES)
def test_spec_examples_pass_validation(
    server: FastMCP, name: str, arguments: dict[str, Any]
) -> None:
    assert error_text(server, name, arguments) == f"{name} is not implemented yet"


def test_enum_error_lists_allowed_values(server: FastMCP) -> None:
    allowed = SPECS["m365_list"]["inputSchema"]["properties"]["resource"]["enum"]
    assert error_text(server, "m365_list", {"resource": "mail"}) == (
        "Invalid resource 'mail': is not an allowed value. "
        f"Expected: one of {', '.join(allowed)}"
    )


def test_bound_error(server: FastMCP) -> None:
    assert error_text(server, "m365_list", {"resource": "email", "limit": 500}) == (
        "Invalid limit '500': is above the maximum of 50. "
        "Expected: integer from 1 to 50"
    )


def test_unknown_parameter_error(server: FastMCP) -> None:
    text = error_text(server, "m365_list", {"resource": "email", "unknown": 1})
    assert text.startswith("Invalid unknown '1': is not a parameter of m365_list.")
    assert "Expected: one of resource, account_id, container_id" in text


def test_missing_required_parameter_error(server: FastMCP) -> None:
    assert error_text(server, "m365_delete", {"resource": "email", "id": "x"}) == (
        "Invalid confirm '': is required. Expected: true or false"
    )


def test_type_error(server: FastMCP) -> None:
    text = error_text(
        server,
        "email_send",
        {"mode": "new", "to": "jane@example.com", "confirm": True},
    )
    assert text == (
        "Invalid to 'j***e@example.com': must be an array. "
        "Expected: array of 1 to 500 items, each email address"
    )


def test_nested_item_path_and_format(server: FastMCP) -> None:
    text = error_text(
        server,
        "email_send",
        {"mode": "new", "to": ["jane@example.com", "nope"], "confirm": True},
    )
    assert text == "Invalid to[1] 'nope': is not a valid email. Expected: email address"


def test_empty_object_error(server: FastMCP) -> None:
    text = error_text(
        server, "m365_update", {"resource": "email", "id": "x", "email_changes": {}}
    )
    assert text.startswith("Invalid email_changes '{}': must set at least 1 field.")
    assert "Expected: object with fields is_read, flag" in text


@pytest.mark.parametrize(
    "value",
    ["2026-10-01T09:00:00", "2026-10-01", "tomorrow", "2026-13-01T09:00:00Z"],
)
def test_date_time_format_needs_rfc3339_with_offset(
    server: FastMCP, value: str
) -> None:
    text = error_text(
        server,
        "calendar_create_event",
        {"subject": "x", "start": value, "end": "2026-10-01T10:00:00+09:30"},
    )
    assert text.startswith(f"Invalid start '{value}': is not a valid date-time.")
    assert "Expected: RFC 3339 date-time with offset" in text


@pytest.mark.parametrize(
    "value", ["2026-10-01T09:00:00+09:30", "2026-10-01T09:00:00.5Z"]
)
def test_date_time_format_accepts_rfc3339(server: FastMCP, value: str) -> None:
    text = error_text(
        server,
        "calendar_create_event",
        {"subject": "x", "start": value, "end": "2026-10-01T10:00:00+09:30"},
    )
    assert text == "calendar_create_event is not implemented yet"


def test_long_values_are_masked(server: FastMCP) -> None:
    text = error_text(server, "m365_list", {"resource": "x" * 300})
    assert "x" * 64 not in text
    assert ERROR_FORMAT.match(text)


def test_semantic_rules_run_after_schema_and_before_handler(
    server: FastMCP,
) -> None:
    seen: list[str] = []

    @handlers.register_validation_rule("m365_list")
    def first(args: dict[str, Any]) -> None:
        seen.append("first")

    @handlers.register_validation_rule("m365_list")
    def reject_path(args: dict[str, Any]) -> None:
        seen.append("second")
        if "path" in args:
            raise ValidationError(
                "Invalid path '/x': only applies to drive_item. "
                "Expected: resource='drive_item'"
            )

    @handlers.register_handler("m365_list")
    def handler(args: dict[str, Any]) -> dict[str, Any]:
        seen.append("handler")
        raise AssertionError("handler must not run")

    assert error_text(server, "m365_list", {"resource": "mail"}).startswith(
        "Invalid resource 'mail'"
    )
    assert seen == []

    assert error_text(server, "m365_list", {"resource": "email", "path": "/x"}) == (
        "Invalid path '/x': only applies to drive_item. Expected: resource='drive_item'"
    )
    assert seen == ["first", "second"]


def test_missing_handler_fails_after_validation(server: FastMCP) -> None:
    ran: list[bool] = []
    handlers.register_validation_rule("m365_get")(lambda args: ran.append(True))
    text = error_text(server, "m365_get", {"resource": "email", "id": "x"})
    assert text == "m365_get is not implemented yet"
    assert ran == [True]


def test_handler_receives_validated_arguments(server: FastMCP) -> None:
    received: list[dict[str, Any]] = []

    @handlers.register_handler("admin_server_info")
    def handler(args: dict[str, Any]) -> dict[str, Any]:
        received.append(args)
        raise ValueError("Invalid thing 'x': broken. Expected: fixed")

    assert error_text(server, "admin_server_info", {}) == (
        "Invalid thing 'x': broken. Expected: fixed"
    )
    assert received == [{}]


def test_unexpected_handler_errors_are_masked(server: FastMCP) -> None:
    @handlers.register_handler("admin_server_info")
    def handler(args: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("secret https://graph.microsoft.com/v1.0/me?token=abc")

    text = error_text(server, "admin_server_info", {})
    assert "secret" not in text and "https://" not in text


def test_unexpected_errors_go_through_translate_exception(
    server: FastMCP, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[BaseException] = []

    def translate(exc: Exception, **kwargs: Any) -> Exception:
        seen.append(exc)
        return ToolError("Microsoft 365 is unavailable. Try again later.")

    monkeypatch.setattr(registry, "_translate_exception", translate)

    @handlers.register_handler("admin_server_info")
    def handler(args: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("boom")

    assert error_text(server, "admin_server_info", {}) == (
        "Microsoft 365 is unavailable. Try again later."
    )
    assert [type(exc) for exc in seen] == [RuntimeError]


def test_translate_exception_uses_the_graph_error_mapping() -> None:
    from m365_mcp.errors import GraphAPIError

    exc = GraphAPIError(404, "ErrorItemNotFound", "gone", "req-1")
    translated = registry._translate_exception(exc, tool="m365_get", resource="email")
    assert isinstance(translated, ToolError)
    assert "No email with that id" in str(translated)
    generic = registry._translate_exception(RuntimeError("secret detail"))
    assert isinstance(generic, ToolError) and "secret" not in str(generic)


def test_register_rejects_unknown_tool() -> None:
    with pytest.raises(KeyError, match="nope"):
        handlers.register_handler("nope")
    with pytest.raises(KeyError, match="nope"):
        handlers.register_validation_rule("nope")
