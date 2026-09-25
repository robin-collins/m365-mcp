#!/usr/bin/env python3
"""Regenerate the tool index and reference in MCP_SERVER_TOOLS.md.

The tool sections are built from the server's live ``tools/list`` response,
captured through an in-memory FastMCP client, so they always match what MCP
clients receive. Everything before the ``## 4. Tool index`` heading is
hand-written and preserved as-is. Hand-verified corrections to individual
tools live in ``ARG_OVERRIDES`` and ``IMPLEMENTATION_NOTES`` below.

Usage:
    uv run python scripts/generate_tools_doc.py [--check]

With ``--check`` the document is not written; the script exits with status 1
if it is out of date.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from fastmcp import Client

from m365_mcp.cache_config import get_ttl_policy
from m365_mcp.tools import mcp

DOC_PATH = ROOT / "MCP_SERVER_TOOLS.md"
GENERATED_MARKER = "## 4. Tool index"

CATEGORIES: OrderedDict[str, tuple[str, str]] = OrderedDict(
    [
        (
            "account",
            ("Accounts", "Discover signed-in Microsoft accounts and add new ones."),
        ),
        ("email", ("Email", "Read, compose, send, organise and delete mail messages.")),
        (
            "emailfolders",
            ("Mail folders", "Manage Outlook mail folders (not OneDrive folders)."),
        ),
        (
            "emailrules",
            ("Mail rules", "Manage Outlook inbox rules and their execution order."),
        ),
        ("calendar", ("Calendar", "Events, calendars, invitations and availability.")),
        ("contact", ("Contacts", "Personal contacts and contact lists.")),
        (
            "file",
            ("OneDrive files", "OneDrive file operations, sharing and transfers."),
        ),
        (
            "folder",
            ("OneDrive folders", "OneDrive folder operations (not mail folders)."),
        ),
        (
            "search",
            ("Search", "Free-text search across mail, events, contacts and files."),
        ),
        (
            "cache",
            ("Cache administration", "Inspect and control the local encrypted cache."),
        ),
        ("server", ("Server", "Server metadata.")),
    ]
)

# Parameter descriptions for tools whose docstrings lack an Args section,
# verified against the implementation.
ARG_OVERRIDES: dict[str, dict[str, str]] = {
    "file_delete": {
        "file_id": "OneDrive item ID of the file or folder *(from implementation; "
        "the docstring has no Args section)*",
        "account_id": "Microsoft account ID *(from implementation)*",
        "confirm": "Must be `true`, or the call is refused *(from implementation)*",
    },
}

# Behaviour notes verified against the code and Microsoft Graph docs, shown
# after a tool's Output line.
IMPLEMENTATION_NOTES: dict[str, str] = {
    "file_delete": (
        'Returns `{"status": "deleted"}`. The tool calls '
        "`DELETE /me/drive/items/{file_id}`. In Microsoft Graph this moves the "
        "item to the OneDrive recycle bin, from which it can be restored; it "
        "is not a permanent delete, despite the tool's description. Deleting "
        "a folder deletes its contents. Invalidates the account's "
        "`file_list` and `folder_get_tree` cache entries."
    ),
    "folder_delete": (
        "Calls `DELETE /me/drive/items/{folder_id}`, which moves the folder "
        "and its contents to the OneDrive recycle bin (see section 2.8)."
    ),
    "calendar_delete_event": (
        "Calls `DELETE /me/events/{event_id}`. For a meeting you organise, "
        "Microsoft Graph sends a cancellation to every attendee (see "
        "section 2.8)."
    ),
}

SECTION_RE = re.compile(
    r"^(Args|Arguments|Parameters|Returns|Return|Raises|Examples?|Notes?|"
    r"Warning|Yields)\s*:\s*$"
)
EXTRA_SECTIONS = ("Raises", "Example", "Examples", "Note", "Notes", "Warning")


async def fetch_tools() -> list[dict[str, Any]]:
    """Return the server's tools/list response as plain dictionaries."""
    async with Client(mcp) as client:
        tools = await client.list_tools()
    return [tool.model_dump(mode="json", exclude_none=True) for tool in tools]


def parse_docstring(
    text: str,
) -> tuple[str, str, OrderedDict[str, list[str]]]:
    """Split a tool description into summary, narrative and sections.

    Section headers (``Args:``, ``Returns:`` ...) are recognised only at
    column 0, as FastMCP publishes the dedented docstring.
    """
    lines = text.strip("\n").splitlines()
    summary = lines[0].strip() if lines else ""
    narrative: list[str] = []
    sections: OrderedDict[str, list[str]] = OrderedDict()
    current: str | None = None
    for line in lines[1:]:
        match = SECTION_RE.match(line) if not line.startswith(" ") else None
        if match:
            current = str(match.group(1))
            sections[current] = []
        elif current is None:
            narrative.append(line)
        else:
            sections[current].append(line)
    return summary, "\n".join(narrative).strip(), sections


def parse_args(lines: list[str]) -> OrderedDict[str, str]:
    """Map parameter names to descriptions from a Google-style Args block."""
    args: OrderedDict[str, str] = OrderedDict()
    name: str | None = None
    base: int | None = None
    for raw in lines:
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip())
        if base is None:
            base = indent
        match = re.match(r"^(\w+)\s*(\([^)]*\))?\s*:\s*(.*)$", raw.strip())
        if indent == base and match:
            name = str(match.group(1))
            args[name] = str(match.group(3)).strip()
        elif name:
            args[name] = f"{args[name]} {raw.strip()}".strip()
    return args


def dedent_block(lines: list[str]) -> str:
    """Trim blank edges and common indentation from a block of lines."""
    block = list(lines)
    while block and not block[-1].strip():
        block.pop()
    while block and not block[0].strip():
        block.pop(0)
    indents = [len(line) - len(line.lstrip()) for line in block if line.strip()]
    cut = min(indents) if indents else 0
    return "\n".join(line[cut:] for line in block)


def fence_indented(text: str) -> str:
    """Render runs of indented docstring lines as fenced code blocks."""
    out: list[str] = []
    block: list[str] = []

    def flush() -> None:
        if block:
            out.extend(["", "```text", dedent_block(block), "```", ""])
            block.clear()

    for line in text.splitlines():
        if line.startswith("    ") or (block and not line.strip()):
            block.append(line)
        else:
            flush()
            out.append(line)
    flush()
    return "\n".join(out).strip()


def schema_type(schema: dict[str, Any]) -> str:
    """Render a JSON Schema fragment as a compact type expression."""
    if not schema:
        return "any"
    if "anyOf" in schema:
        return " | ".join(schema_type(option) for option in schema["anyOf"])
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


def output_shape(tool: dict[str, Any]) -> str:
    """Describe where and how a tool's structured result is returned."""
    schema = tool.get("outputSchema")
    if not schema:
        return "Unstructured (text content only)."
    if schema.get("x-fastmcp-wrap-result"):
        inner = schema.get("properties", {}).get("result", {})
        return (
            f"`structuredContent.result`: `{schema_type(inner) if inner else 'any'}` "
            "(the tool's return value, wrapped under `result`)."
        )
    return f"`structuredContent`: `{schema_type(schema)}` (no declared fields)."


def tool_meta(tool: dict[str, Any]) -> dict[str, Any]:
    return tool.get("_meta") or tool.get("meta") or {}


def yes_no(value: Any) -> str:
    return "yes" if value else "no"


def group_by_category(
    tools: list[dict[str, Any]],
) -> OrderedDict[str, list[dict[str, Any]]]:
    groups: OrderedDict[str, list[dict[str, Any]]] = OrderedDict(
        (prefix, []) for prefix in CATEGORIES
    )
    for tool in tools:
        groups.setdefault(tool["name"].split("_")[0], []).append(tool)
    return groups


def render_index(groups: OrderedDict[str, list[dict[str, Any]]]) -> list[str]:
    md = [
        f"{GENERATED_MARKER}\n",
        (
            "Legend: **RO** = `readOnlyHint`, **Destr.** = `destructiveHint`, "
            "**Idem.** = `idempotentHint`, **Confirm** = tool refuses to run "
            "unless `confirm=true`, **Cache** = supports "
            "`use_cache`/`force_refresh`.\n"
        ),
        "| # | Tool | Title | Safety | RO | Destr. | Idem. | Confirm | Cache |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    number = 0
    for prefix in CATEGORIES:
        for tool in groups.get(prefix, []):
            number += 1
            ann = tool.get("annotations") or {}
            props = tool["inputSchema"].get("properties", {})
            md.append(
                f"| {number} | [`{tool['name']}`](#{tool['name']}) | "
                f"{ann.get('title', '')} | "
                f"{tool_meta(tool).get('safety_level', '—')} | "
                f"{yes_no(ann.get('readOnlyHint'))} | "
                f"{yes_no(ann.get('destructiveHint'))} | "
                f"{yes_no(ann.get('idempotentHint'))} | "
                f"{yes_no('confirm' in props)} | {yes_no('use_cache' in props)} |"
            )
    md.append("")
    return md


def render_tool(tool: dict[str, Any], prefix: str) -> list[str]:
    name = tool["name"]
    ann = tool.get("annotations") or {}
    meta = tool_meta(tool)
    schema = tool["inputSchema"]
    props: dict[str, Any] = schema.get("properties", {})
    required = set(schema.get("required", []))
    summary, narrative, sections = parse_docstring(tool.get("description", ""))
    arg_docs = parse_args(sections.get("Args", []) or sections.get("Arguments", []))
    arg_docs.update(ARG_OVERRIDES.get(name, {}))

    md = [f'<a id="{name}"></a>\n', f"#### `{name}`\n", f"{summary}\n"]
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
        f"**Safety level:** `{meta.get('safety_level', '—')}`",
        f"**Category:** `{meta.get('category', prefix)}`",
        f"**Hints:** {hints}",
        f"**Requires `confirm=true`:** {yes_no('confirm' in props)}",
    ]
    if meta.get("requires_confirmation") and "confirm" not in props:
        facts.append(
            "**Meta `requires_confirmation`:** true (advisory; no confirm parameter)"
        )
    if "use_cache" in props:
        policy = get_ttl_policy(name)
        facts.append(
            f"**Cache:** fresh {policy.fresh_seconds // 60} min, "
            f"stale-while-refresh until {policy.stale_seconds // 60} min"
        )
    md.append("  \n".join(facts) + "\n")

    if narrative:
        md.append(fence_indented(narrative) + "\n")

    if props:
        md.append("| Parameter | Type | Required | Default | Description |")
        md.append("|---|---|---|---|---|")
        for pname, pschema in props.items():
            default = (
                f"`{json.dumps(pschema['default'])}`" if "default" in pschema else "—"
            )
            md.append(
                f"| `{pname}` | `{cell(schema_type(pschema))}` | "
                f"{yes_no(pname in required)} | {default} | "
                f"{cell(arg_docs.get(pname, '—'))} |"
            )
        md.append("")
        extra = [param for param in arg_docs if param not in props]
        if extra:
            md.append(
                "_Docstring mentions parameters not in the schema: "
                + ", ".join(f"`{param}`" for param in extra)
                + "._\n"
            )
    else:
        md.append("_No parameters._\n")

    md.append(f"**Output:** {output_shape(tool)}\n")
    if name in IMPLEMENTATION_NOTES:
        md.append(f"**Implementation note:** {IMPLEMENTATION_NOTES[name]}\n")

    returns = sections.get("Returns") or sections.get("Return")
    if returns:
        md.append("**Returns (as documented):**\n")
        md.append("```text\n" + dedent_block(returns) + "\n```\n")
    for section in EXTRA_SECTIONS:
        if section in sections and dedent_block(sections[section]).strip():
            md.append(f"**{section}:**\n")
            md.append("```text\n" + dedent_block(sections[section]) + "\n```\n")
    md.append("---\n")
    return md


def render_reference(groups: OrderedDict[str, list[dict[str, Any]]]) -> list[str]:
    md = ["## 5. Tool reference\n"]
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
    unknown = [
        tool["name"] for tool in tools if tool["name"].split("_")[0] not in CATEGORIES
    ]
    if unknown:
        raise SystemExit(f"Add a CATEGORIES entry for: {', '.join(unknown)}")
    groups = group_by_category(tools)
    return "\n".join(render_index(groups) + render_reference(groups))


def main() -> int:
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
