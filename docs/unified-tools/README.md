# Unified Tools Specification (v1.0.0)

This directory is the **implementation source of truth** for the 29 tools
designed in [`UNIFIED_TOOLS_CONCEPT.md`](../../UNIFIED_TOOLS_CONCEPT.md). The
concept explains *why*; these files define *exactly what* the server exposes
and how each tool must behave.

## Files

| File | Content |
|---|---|
| `tools/<tool>.json` | One complete tool: `name`, `title`, `description`, `annotations`, `meta`, `inputSchema`, `outputSchema` (JSON Schema 2020-12), `graph_calls`, `validation_rules`, `replaces`, `examples` |
| `index.json` | Tool order, tiers (`core` / `extended` / `admin`), default toolsets, resource enum |
| `legacy_mapping.json` | All 85 v0.x tools → replacement call → behaviour change |
| `SCHEMA_REFERENCE.md` | Human-readable reference generated from the same source |

All four are **generated** by
[`scripts/build_unified_tool_specs.py`](../../scripts/build_unified_tool_specs.py).
Never edit them by hand.

## Changing the specification

1. Edit `scripts/build_unified_tool_specs.py`.
2. Run `uv run python scripts/build_unified_tool_specs.py`.
3. Run `uv run pytest tests/test_unified_tool_specs.py`.
4. Update `UNIFIED_TOOLS_CONCEPT.md` if the change affects the design.

`tests/test_unified_tool_specs.py` enforces the following:
- every schema is valid JSON Schema 2020-12;
- every example input and output validates against its schema;
- every input parameter has a description, strings have `maxLength`,
  numbers have bounds and arrays have `maxItems`;
- every object is closed (`additionalProperties: false`);
- safety metadata is consistent. Destructive tools are `critical` with
  `confirm: always`. `dangerous`/`critical` tools have a `confirm`
  parameter that defaults to `false`. Read-only tools are `safe`;
- tier counts are 16/7/6 in fixed order;
- the legacy mapping covers exactly the 85 v0.x tools;
- definition token budgets are met: core ≤ 10k, default (core + extended)
  ≤ 14k tokens;
- the generated files are current (`--check`).

## Implementation contract

1. **`tools/list` must match the spec.** For each enabled tool, the
   server's `name`, `title`, `description`, `annotations`, `inputSchema`
   and `outputSchema` must equal the JSON file (the `$schema` keys may be
   dropped). `meta.category`, `meta.safety_level` and `meta.tier` go in the
   FastMCP `meta`. The recommended mechanism is to register each tool from
   its JSON file (loaded as package data) rather than regenerating schemas
   from Python signatures, so they cannot drift. A conformance test must
   compare the live `tools/list` with these files.
2. **Validate twice.**
   - First, validate arguments against `inputSchema` (jsonschema).
   - Then enforce every entry in `validation_rules`, returning the listed
     `error` text (same wording, with the concrete values substituted).
     Each rule needs a unit test.
3. **Return `structuredContent` that validates against `outputSchema`**,
   plus a single text block holding the same result serialized as JSON
   (`summary` is one field within it). Per the MCP spec, `structuredContent`
   is not guaranteed to reach the model — many clients, including a plain
   Anthropic-API tool loop, only forward `content` — so the text must stay
   "functionally equivalent" to the structured data, not a bare summary
   sentence. Tests validate real handler output against the schema.
4. **Call Graph as listed in `graph_calls`** through the services layer
   (`src/m365_mcp/services/`); tools never build Graph URLs.
5. **Confirm gates.**
   - `meta.confirm = always`: refuse unless `confirm=true`.
   - `conditional`: apply `meta.confirm_rule` exactly.
   - `never`: there is no confirm parameter.
6. **Examples are test fixtures.** Each example must be reproducible
   against a mocked Graph layer.

## Shared conventions

| Convention | Rule |
|---|---|
| `account_id` | Optional on every Microsoft 365 tool. Omitted means the only signed-in account. With several accounts the error lists them. Accepts the ID or email address. |
| Date-times | RFC 3339 with offset (`format: date-time`). Time-zone names are IANA. |
| IDs | Opaque strings of at most 1024 characters. Aliases only where the parameter description says so. |
| Cursors | `next_cursor` is opaque (base64url of account hash, request hash, Graph nextLink or offset, and timestamp). It is only valid for the identical request, for 24 hours, and the nextLink host is verified. |
| Results | Closed objects. Every field is present (`null` when absent). No `@odata.*` or cache fields. `summary` is always present. |
| Untrusted text | Email subject, preview and body; event subject, location, preview and body; file names. The server `instructions` tell the model to treat these as data. |
| Errors | Validation errors use `Invalid <param> '<value>': <reason>. Expected: <expected>`. Graph errors are mapped to actionable text. There are no URLs, codes or stack traces. |
| Confirm | `confirm` defaults to `false`. Descriptions tell the model to ask the user first. |
| Local paths | Only inside the working directory, the temp directory or `MCP_FILE_ALLOWED_ROOTS`. Hidden and secret-like files are refused for both read and write. |

## Tiers and default exposure

`M365_MCP_TOOLSETS` (default `core,extended`) selects the registered tiers.
Order is always core → extended → admin, as in `index.json`.

## Known Graph facts encoded here (verified 2026-09-26)

- **Search API:** `POST /search/query` is unsupported for personal
  accounts. Search uses `$search`, `$filter` and drive search instead.
- **Free/busy:** only your own calendar is visible to a personal account.
  Availability is computed from `calendarView` plus `mailboxSettings`
  working hours.
- **Inbox rules:** the schemas use Graph's exact `messageRulePredicates` (30
  properties) and `messageRuleActions` (11). The legacy validator accepted
  six predicates Graph does not have (`headers`, `searchTerms`,
  `senderAddressContains`, `recipientAddressContains`,
  `meetingMessageType`, and `stopProcessingRules`, which is an action) and
  rejected 16 valid ones. The rule action
  `delete` moves mail to Deleted Items; only `permanent_delete` is
  permanent.
- **Sharing:** `createLink` returns an existing link of the same type
  (`created: false`). Invite `expirationDateTime` needs premium OneDrive.
  The drive root cannot be shared.
- **Deletes and copies:**
  - Drive deletes go to the recycle bin.
  - Deleting a meeting as its organiser sends cancellations.
  - Drive copy is asynchronous (202 plus a monitor URL).
