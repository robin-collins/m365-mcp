#!/usr/bin/env python3
"""Regenerate the tool index and reference in MCP_SERVER_TOOLS.md.

The tool sections are built from the unified server's live ``tools/list``
response (all tiers), captured through an in-memory FastMCP client, so they
always match what MCP clients receive. Everything before the
``## 4. Tool index`` heading is hand-written and preserved as-is.

Usage:
    uv run python scripts/generate_tools_doc.py [--check]

With ``--check`` the document is not written; the script exits with status 1
if it is out of date.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from fastmcp import Client

from m365_mcp.cache_config import RESOURCE_TTL_POLICIES
from m365_mcp.tools.registry import build_server

DOC_PATH = ROOT / "MCP_SERVER_TOOLS.md"
GENERATED_MARKER = "## 4. Tool index"
ALL_TOOLSETS = "core,extended,admin"

CATEGORIES: OrderedDict[str, tuple[str, str]] = OrderedDict(
    [
        (
            "m365",
            (
                "Generic resource tools",
                (
                    "List, search, read, create, update, move and delete any "
                    "mail, calendar, contact or OneDrive resource by `resource`."
                ),
            ),
        ),
        (
            "email",
            ("Email", "Compose, send, reply, forward and organise mail."),
        ),
        (
            "calendar",
            ("Calendar", "Events, invitations, responses and availability."),
        ),
        ("drive", ("OneDrive", "Upload, copy and share OneDrive files.")),
        (
            "account",
            ("Accounts", "Discover signed-in accounts and add new ones."),
        ),
        (
            "admin",
            ("Administration", "Inspect and control the cache and the server."),
        ),
    ]
)

# Tools whose results are cached (registry.CACHED_READS).
CACHED_TOOLS = ("m365_list", "m365_get")


async def fetch_tools() -> list[dict[str, Any]]:
    """Return the unified server's tools/list response as dictionaries."""
    async with Client(build_server(ALL_TOOLSETS)) as client:
        tools = await client.list_tools()
    return [tool.model_dump(mode="json", exclude_none=True) for tool in tools]


def schema_type(schema: dict[str, Any]) -> str:
    """Render a JSON Schema fragment as a compact type expression."""
    if not schema:
        return "any"
    if "anyOf" in schema:
        return " | ".join(schema_type(option) for option in schema["anyOf"])
    if "enum" in schema:
        return " | ".join(json.dumps(value) for value in schema["enum"])
    if "const" in schema:
        return json.dumps(schema["const"])
    kind = schema.get("type")
    if kind == "array":
        return f"array<{schema_type(schema.get('items', {}))}>"
    if kind == "object":
        extra = schema.get("additionalProperties")
        if isinstance(extra, dict):
            return f"object<string, {schema_type(extra)}>"
        return "object"
    return kind or "any"


def cell(text: str) -> str:
    """Escape text for a Markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ")


def bounds(schema: dict[str, Any]) -> str:
    """Summarise numeric and length limits of a parameter."""
    parts = []
    for key, label in (
        ("minimum", "min"),
        ("maximum", "max"),
        ("minLength", "min length"),
        ("maxLength", "max length"),
        ("minItems", "min items"),
        ("maxItems", "max items"),
    ):
        if key in schema:
            parts.append(f"{label} {schema[key]}")
    return ", ".join(parts)


def tool_meta(tool: dict[str, Any]) -> dict[str, Any]:
    """Return the tool's ``meta`` block."""
    return tool.get("_meta") or tool.get("meta") or {}


def category_of(tool: dict[str, Any]) -> str:
    """Return the documentation category of a tool."""
    return str(tool_meta(tool).get("category") or tool["name"].split("_")[0])


def yes_no(value: Any) -> str:
    """Render a boolean as yes or no."""
    return "yes" if value else "no"


def group_by_category(
    tools: list[dict[str, Any]],
) -> OrderedDict[str, list[dict[str, Any]]]:
    """Group tools by category in ``CATEGORIES`` order."""
    groups: OrderedDict[str, list[dict[str, Any]]] = OrderedDict(
        (prefix, []) for prefix in CATEGORIES
    )
    for tool in tools:
        groups.setdefault(category_of(tool), []).append(tool)
    return groups


def render_index(groups: OrderedDict[str, list[dict[str, Any]]]) -> list[str]:
    """Render the section 4 index table."""
    md = [
        f"{GENERATED_MARKER}\n",
        (
            "Legend: **Tier** = toolset that exposes the tool "
            "(`M365_MCP_TOOLSETS`), **RO** = `readOnlyHint`, **Destr.** = "
            "`destructiveHint`, **Idem.** = `idempotentHint`, **Confirm** = "
            "`meta.confirm` (`always`, `conditional` or `never`).\n"
        ),
        "| # | Tool | Title | Tier | Safety | RO | Destr. | Idem. | Confirm |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    number = 0
    for prefix in CATEGORIES:
        for tool in groups.get(prefix, []):
            number += 1
            ann = tool.get("annotations") or {}
            meta = tool_meta(tool)
            md.append(
                f"| {number} | [`{tool['name']}`](#{tool['name']}) | "
                f"{ann.get('title', '')} | {meta.get('tier', '—')} | "
                f"{meta.get('safety_level', '—')} | "
                f"{yes_no(ann.get('readOnlyHint'))} | "
                f"{yes_no(ann.get('destructiveHint'))} | "
                f"{yes_no(ann.get('idempotentHint'))} | "
                f"{meta.get('confirm', '—')} |"
            )
    md.append("")
    return md


def render_parameters(schema: dict[str, Any]) -> list[str]:
    """Render a tool's input parameters as a Markdown table."""
    props: dict[str, Any] = schema.get("properties", {})
    if not props:
        return ["_No parameters._\n"]
    required = set(schema.get("required", []))
    md = [
        "| Parameter | Type | Required | Default | Limits | Description |",
        "|---|---|---|---|---|---|",
    ]
    for name, prop in props.items():
        default = f"`{json.dumps(prop['default'])}`" if "default" in prop else "—"
        md.append(
            f"| `{name}` | `{cell(schema_type(prop))}` | "
            f"{yes_no(name in required)} | {default} | "
            f"{cell(bounds(prop)) or '—'} | {cell(prop.get('description', '—'))} |"
        )
    md.append("")
    return md


def render_output(tool: dict[str, Any]) -> list[str]:
    """Render a tool's structured output fields."""
    schema = tool.get("outputSchema") or {}
    props: dict[str, Any] = schema.get("properties", {})
    if not props:
        return ["**Output:** text content only.\n"]
    fields = ", ".join(f"`{name}`" for name in props)
    return [f"**Output** (`structuredContent`): {fields}.\n"]


def render_tool(tool: dict[str, Any], prefix: str) -> list[str]:
    """Render one tool's reference entry."""
    name = tool["name"]
    ann = tool.get("annotations") or {}
    meta = tool_meta(tool)
    hints = ", ".join(
        f"{key}=`{str(ann.get(key)).lower()}`"
        for key in (
            "readOnlyHint",
            "destructiveHint",
            "idempotentHint",
            "openWorldHint",
        )
        if key in ann
    )
    facts = [
        f"**Title:** {ann.get('title', '—')}",
        f"**Tier:** `{meta.get('tier', '—')}`",
        f"**Safety level:** `{meta.get('safety_level', '—')}`",
        f"**Category:** `{meta.get('category', prefix)}`",
        f"**Hints:** {hints}",
        f"**Confirm:** `{meta.get('confirm', '—')}`"
        + (f" ({meta['confirm_rule']})" if meta.get("confirm_rule") else ""),
    ]
    if name in CACHED_TOOLS:
        facts.append("**Cache:** per-resource TTLs; `refresh=true` bypasses the cache")

    md = [
        f'<a id="{name}"></a>\n',
        f"#### `{name}`\n",
        f"{tool.get('description', '')}\n",
        "  \n".join(facts) + "\n",
    ]
    md.extend(render_parameters(tool["inputSchema"]))
    md.extend(render_output(tool))
    md.append("---\n")
    return md


def render_cache_policies() -> list[str]:
    """Render the per-resource cache lifetimes used by m365_list/m365_get."""
    md = [
        "### 5.0 Cache lifetimes\n",
        (
            "Reads through `m365_list` and `m365_get` are cached per account and "
            "resource. Fresh entries are served with no Graph call; stale entries "
            "are served until they expire.\n"
        ),
        "| Resource | Fresh (min) | Expires (min) |",
        "|---|---|---|",
    ]
    for resource, policy in RESOURCE_TTL_POLICIES.items():
        md.append(
            f"| `{resource}` | {policy.fresh_seconds // 60} | "
            f"{policy.stale_seconds // 60} |"
        )
    md.append("")
    return md


def render_reference(groups: OrderedDict[str, list[dict[str, Any]]]) -> list[str]:
    """Render the section 5 tool reference."""
    md = ["## 5. Tool reference\n"]
    md.extend(render_cache_policies())
    number = 0
    for prefix, (label, blurb) in CATEGORIES.items():
        group = groups.get(prefix, [])
        if not group:
            continue
        number += 1
        md.append(f"### 5.{number} {label} ({len(group)} tools)\n")
        md.append(f"{blurb}\n")
        for tool in group:
            md.extend(render_tool(tool, prefix))
    return md


def render(tools: list[dict[str, Any]]) -> str:
    """Render sections 4 and 5 for the given tools."""
    unknown = [tool["name"] for tool in tools if category_of(tool) not in CATEGORIES]
    if unknown:
        raise SystemExit(f"Add a CATEGORIES entry for: {', '.join(unknown)}")
    groups = group_by_category(tools)
    return "\n".join(render_index(groups) + render_reference(groups))


def main() -> int:
    """Write or check MCP_SERVER_TOOLS.md."""
    parser = argparse.ArgumentParser(
        description="Regenerate the tool sections of MCP_SERVER_TOOLS.md."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if MCP_SERVER_TOOLS.md is out of date instead of writing it.",
    )
    args = parser.parse_args()

    current = DOC_PATH.read_text(encoding="utf-8")
    if GENERATED_MARKER not in current:
        raise SystemExit(f"'{GENERATED_MARKER}' heading not found in {DOC_PATH}")
    header = current[: current.index(GENERATED_MARKER)]

    tools = asyncio.run(fetch_tools())
    updated = header + render(tools)

    if args.check:
        if updated != current:
            print(f"{DOC_PATH.name} is out of date; run this script to update it.")
            return 1
        print(f"{DOC_PATH.name} is up to date ({len(tools)} tools).")
        return 0

    DOC_PATH.write_text(updated, encoding="utf-8")
    print(f"Wrote {DOC_PATH.name} ({len(tools)} tools).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
