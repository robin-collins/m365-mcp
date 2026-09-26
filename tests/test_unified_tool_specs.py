"""Conformance tests for the unified-tool specification (docs/unified-tools).

These tests keep the v1.0.0 source of truth trustworthy: every schema is
valid JSON Schema 2020-12, every example validates, every parameter is
documented, safety metadata is consistent, and the generated files match
scripts/build_unified_tool_specs.py.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent.parent
SPEC_DIR = ROOT / "docs" / "unified-tools"
BUILDER = ROOT / "scripts" / "build_unified_tool_specs.py"

# Token budgets for tool definitions (name, title, description, annotations,
# inputSchema), estimated at 4 characters per token. See
# UNIFIED_TOOLS_CONCEPT.md §16.2.
CORE_TOKEN_BUDGET = 10_000
DEFAULT_TOKEN_BUDGET = 14_000


def _load_builder() -> Any:
    spec = importlib.util.spec_from_file_location("build_unified_tool_specs", BUILDER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INDEX = json.loads((SPEC_DIR / "index.json").read_text(encoding="utf-8"))
TOOLS = {
    name: json.loads((SPEC_DIR / "tools" / f"{name}.json").read_text(encoding="utf-8"))
    for name in INDEX["tool_order"]
}
MAPPING = json.loads((SPEC_DIR / "legacy_mapping.json").read_text(encoding="utf-8"))


def _walk_properties(schema: dict[str, Any], path: str = ""):
    """Yield (path, property_schema, parent_schema) for every property."""
    for name, prop in schema.get("properties", {}).items():
        yield f"{path}{name}", prop, schema
        if isinstance(prop, dict):
            yield from _walk_properties(prop, f"{path}{name}.")
            if isinstance(prop.get("items"), dict):
                yield from _walk_properties(prop["items"], f"{path}{name}[].")
    for def_name, definition in schema.get("$defs", {}).items():
        yield from _walk_properties(definition, f"{path}$defs.{def_name}.")


def _objects(schema: Any):
    """Yield every object schema that declares properties."""
    if isinstance(schema, dict):
        if schema.get("type") == "object" and "properties" in schema:
            yield schema
        for value in schema.values():
            yield from _objects(value)
    elif isinstance(schema, list):
        for value in schema:
            yield from _objects(value)


def test_generated_files_are_current() -> None:
    builder = _load_builder()
    for path, content in builder.build().items():
        assert path.read_text(encoding="utf-8") == content, (
            f"{path.name} is stale; run scripts/build_unified_tool_specs.py"
        )


def test_catalog_shape() -> None:
    assert INDEX["tool_count"] == 30
    assert len(INDEX["tiers"]["core"]) == 16
    assert len(INDEX["tiers"]["extended"]) == 7
    assert len(INDEX["tiers"]["admin"]) == 7
    assert INDEX["default_toolsets"] == ["core", "extended"]
    ordered = (
        INDEX["tiers"]["core"] + INDEX["tiers"]["extended"] + INDEX["tiers"]["admin"]
    )
    assert ordered == INDEX["tool_order"], "tools must be ordered by tier"
    assert len(set(INDEX["tool_order"])) == 30


@pytest.mark.parametrize("name", INDEX["tool_order"])
def test_tool_definition(name: str) -> None:
    tool = TOOLS[name]
    assert tool["name"] == name
    assert re.fullmatch(r"[a-z][a-z0-9]*(_[a-z0-9]+)+", name)
    assert len(name) <= 64

    description = tool["description"]
    assert 40 <= len(description) <= 600
    assert "Args:" not in description
    assert all(ord(ch) < 0x2190 for ch in description), "no emoji in descriptions"

    Draft202012Validator.check_schema(tool["inputSchema"])
    Draft202012Validator.check_schema(tool["outputSchema"])
    assert tool["inputSchema"]["type"] == "object"
    assert tool["outputSchema"]["type"] == "object"
    assert "summary" in tool["outputSchema"]["required"]

    for obj in _objects(tool["inputSchema"]):
        assert obj.get("additionalProperties") is False
    for obj in _objects(tool["outputSchema"]):
        assert obj.get("additionalProperties") is False

    for path, prop, _parent in _walk_properties(tool["inputSchema"]):
        assert prop.get("description"), f"{name}: input '{path}' is undocumented"
        if prop.get("type") in ("integer", "number"):
            assert "minimum" in prop and "maximum" in prop, (
                f"{name}: '{path}' unbounded"
            )
        if prop.get("type") == "string" and "enum" not in prop and "format" not in prop:
            assert "maxLength" in prop, f"{name}: '{path}' has no maxLength"
        if prop.get("type") == "array":
            assert "maxItems" in prop, f"{name}: '{path}' has no maxItems"


@pytest.mark.parametrize("name", INDEX["tool_order"])
def test_safety_metadata_is_consistent(name: str) -> None:
    tool = TOOLS[name]
    meta, ann = tool["meta"], tool["annotations"]
    props = tool["inputSchema"]["properties"]
    required = tool["inputSchema"].get("required", [])

    assert meta["tier"] in {"core", "extended", "admin"}
    assert name in INDEX["tiers"][meta["tier"]]
    assert meta["safety_level"] in {"safe", "moderate", "dangerous", "critical"}
    assert ann["title"] == tool["title"]

    if meta["confirm"] == "never":
        assert "confirm" not in props and meta["confirm_rule"] is None
    else:
        assert "confirm" in props and props["confirm"]["default"] is False
        assert meta["confirm_rule"]
    if meta["confirm"] == "always":
        assert "confirm" in required
    if meta["safety_level"] in {"dangerous", "critical"}:
        assert meta["confirm"] in {"always", "conditional"}
    if ann["destructiveHint"]:
        assert meta["safety_level"] == "critical" and meta["confirm"] == "always"
    if ann["readOnlyHint"]:
        assert meta["safety_level"] == "safe" and not ann["destructiveHint"]


@pytest.mark.parametrize("name", INDEX["tool_order"])
def test_examples_validate(name: str) -> None:
    tool = TOOLS[name]
    assert tool["examples"], f"{name} needs at least one example"
    input_validator = Draft202012Validator(
        tool["inputSchema"], format_checker=FormatChecker()
    )
    output_validator = Draft202012Validator(
        tool["outputSchema"], format_checker=FormatChecker()
    )
    for example in tool["examples"]:
        input_validator.validate(example["input"])
        output_validator.validate(example["output"])


# Tools with no v0.x predecessor: nothing in the 85-row legacy mapping.
NEW_IN_1_0 = {"admin_reauth_schedule"}


@pytest.mark.parametrize("name", INDEX["tool_order"])
def test_tool_is_fully_specified(name: str) -> None:
    tool = TOOLS[name]
    assert tool["graph_calls"], f"{name} must list its Microsoft Graph calls"
    if name not in NEW_IN_1_0:
        assert tool["replaces"], f"{name} must list the legacy tools it replaces"
    for rule in tool["validation_rules"]:
        assert rule["rule"] and rule["error"]


# Common model mistakes every schema must reject. Shared with
# tests/test_input_validation.py, which checks the runtime rejection.
INVALID_INPUT_CASES: list[tuple[str, dict[str, Any]]] = [
    ("m365_list", {"resource": "mail"}),
    ("m365_list", {"resource": "email", "limit": 500}),
    ("m365_list", {"resource": "email", "unknown": 1}),
    ("m365_delete", {"resource": "email", "id": "x"}),
    ("email_send", {"mode": "new", "to": "jane@example.com", "confirm": True}),
    (
        "email_reply",
        {"email_id": "x", "mode": "everyone", "body": "hi", "confirm": True},
    ),
    (
        "drive_share",
        {"item_id": "x", "mode": "link", "link_type": "public", "confirm": True},
    ),
    ("calendar_respond", {"event_id": "x", "action": "maybe"}),
    ("m365_update", {"resource": "email", "id": "x", "email_changes": {}}),
]


def test_invalid_inputs_are_rejected() -> None:
    """Spot-check that schemas reject common model mistakes."""
    for name, arguments in INVALID_INPUT_CASES:
        validator = Draft202012Validator(TOOLS[name]["inputSchema"])
        assert list(validator.iter_errors(arguments)), f"{name} accepted {arguments}"


def test_legacy_mapping_covers_all_85_tools() -> None:
    legacy = [row["legacy_tool"] for row in MAPPING["mapping"]]
    assert MAPPING["legacy_tool_count"] == 85
    assert len(legacy) == 85 and len(set(legacy)) == 85

    replaced = {
        entry.split(" ")[0] for tool in TOOLS.values() for entry in tool["replaces"]
    }
    assert replaced == set(legacy), (
        f"missing: {sorted(set(legacy) - replaced)}, "
        f"unknown: {sorted(replaced - set(legacy))}"
    )


def _definition_tokens(names: list[str]) -> int:
    chars = 0
    for name in names:
        tool = TOOLS[name]
        definition = {
            key: tool[key]
            for key in ("name", "title", "description", "annotations", "inputSchema")
        }
        chars += len(json.dumps(definition, separators=(",", ":")))
    return chars // 4


def test_definition_token_budget() -> None:
    core = INDEX["tiers"]["core"]
    default = core + INDEX["tiers"]["extended"]
    assert _definition_tokens(core) <= CORE_TOKEN_BUDGET
    assert _definition_tokens(default) <= DEFAULT_TOKEN_BUDGET
