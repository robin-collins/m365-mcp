# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

M365 MCP is a Model Context Protocol (MCP) server that gives AI assistants
access to Microsoft Graph for **personal Microsoft accounts** (outlook.com,
hotmail.com, live.com): Outlook mail, Calendar, Contacts and OneDrive. Several
personal accounts can be signed in at once. Work and school accounts are not
supported and are rejected at sign-in.

Version 1.0.0 exposes 29 intent-based tools (16 `core`, 7 `extended`, 6
`admin`). The full contract for every tool lives in `docs/unified-tools/`.

## Architecture

### Specification first

`docs/unified-tools/` is the source of truth for the tool surface. One JSON
file per tool (`tools/<tool>.json`) holds the name, title, description,
annotations, `inputSchema`, `outputSchema`, `validation_rules`, `graph_calls`
and examples. `index.json` holds the tool order, tiers and default toolsets;
`legacy_mapping.json` maps the 85 removed v0.x names to their replacements.

These files are **generated** by `scripts/build_unified_tool_specs.py`; never
edit them by hand. To change a tool: edit the script, run
`uv run python scripts/build_unified_tool_specs.py`, then
`uv run pytest tests/test_unified_tool_specs.py`. The server ships a copy of
the same specs as package data in `src/m365_mcp/tool_specs/` (also generated;
`--check` verifies both copies).

### Core modules (`src/m365_mcp/`)

- **`server.py`**: entry point; transport selection (stdio or Streamable
  HTTP), cache lifecycle, bearer authentication for HTTP.
- **`tools/registry.py`**: `build_server(toolsets)` registers each tool
  **from its spec JSON** in fixed index order, so `tools/list` cannot drift
  from the spec. It validates arguments against `inputSchema`, runs the
  per-tool rules, enforces `confirm` gates and the rate limit, validates
  output against `outputSchema`, and returns `structuredContent` plus a
  one-line text `summary`. `M365_MCP_TOOLSETS` selects the tiers.
- **`tools/unified/`**: the tool handlers (thin layer: schema in,
  projection out): `mail.py`, `mail_compose.py`, `mail_bulk.py`,
  `mail_rules.py`, `calendar.py`, `calendar_availability.py`,
  `contacts.py`, `drive.py`, `search.py`, `admin.py`, plus shared helpers in
  `common.py`. `tools/handlers.py` holds the per-tool semantic rule hook.
- **`services/`**: all Graph logic (`mail`, `mail_compose`, `mail_folders`,
  `mail_rules`, `calendar`, `contacts`, `drive`, `search`, `accounts`).
  Tools never build Graph URLs; services never import FastMCP (checked by
  `tests/test_services_boundaries.py`).
- **`tool_specs/`**: packaged copy of the generated specs (`index.json`,
  `tools/*.json`).
- **`projections.py`**: Graph JSON to compact result records (no `@odata.*`,
  no cache fields, every field present).
- **`cursors.py`**: opaque, HMAC-protected pagination cursors bound to
  account, resource and request; 24 hour expiry; the nextLink host is
  verified. Key from `M365_MCP_CURSOR_KEY`, else random per process.
- **`errors.py`**: `GraphAPIError` and its mapping to actionable `ToolError`
  text (no URLs, codes or request IDs). The server runs with
  `mask_error_details=True`.
- **`resource_cache.py`**: cache keyed by account + resource + normalised
  parameters + cursor, over the encrypted cache manager; per-resource TTLs
  (`cache_config.RESOURCE_TTL_POLICIES`) and a mutation-to-resource
  invalidation table.
- **`observability.py`**: middleware writing one JSON audit line per call
  (tool, resource, hashed account, duration, outcome, retries, result bytes,
  mutation flag; never argument values, tokens or URLs).
- **`http_security.py`**: Origin validation (loopback default,
  `MCP_ALLOWED_ORIGINS`) and constant-time bearer token comparison.
- **`local_files.py`**: allowed local roots (working directory, temp
  directory, `MCP_FILE_ALLOWED_ROOTS`), deny-list for dotfiles and secrets,
  symlink resolution, file-name sanitising.
- **`rate_limit.py`**: per-account token buckets: 20 per minute for sends,
  shares and deletes; 300 per minute overall.
- **`operations.py`**: server-side store for asynchronous Graph operations
  (`drive_copy` monitor URLs), polled by `m365_get(resource="operation")`.
- **`auth_sessions.py`**: server-side device-code sessions for
  `account_auth_begin` / `account_auth_complete` (opaque ID, single use,
  15 minute TTL; the device code and MSAL flow never reach the model).
- **`untrusted.py`**: strips control and bidirectional characters, converts
  HTML to text and caps previews and bodies.
- **`auth.py`**: MSAL public client, device flow, token cache at
  `~/.m365_mcp_token_cache.json`, multi-account management. Default
  authority is `consumers`; work/school accounts are removed at sign-in.
- **`graph.py`**: HTTP client for Microsoft Graph: retries with exponential
  backoff (idempotent requests only), `Retry-After`, 401 refresh,
  pagination, `$batch`, chunked uploads, and a per-call deadline (45 s reads,
  60 s writes).
- **`validators.py`**, **`logging_config.py`**, **`health_check.py`**:
  shared validation helpers, logging setup and health check.
- **`authenticate.py`** (repository root): standalone interactive sign-in.

### Cache system

- **`cache.py`**: encrypted SQLite cache manager (AES-256 via SQLCipher)
- **`cache_config.py`**: TTL policies, limits, cache-key generation
- **`cache_warming.py`**, **`background_worker.py`**: optional warming and
  background tasks, enabled with `M365_MCP_CACHE_WARMING=true`
- **`encryption.py`**: key management (keyring, `M365_MCP_CACHE_KEY`
  fallback, ephemeral-key warning)

### Key design patterns

- **Spec-first**: change the spec builder, regenerate, then implement. The
  live `tools/list` must equal the spec for every toolset combination
  (`tests/test_tool_registry.py`).
- **Optional `account_id`**: every Microsoft 365 tool accepts an optional
  `account_id` (ID or email address). Omitted means the only signed-in
  account; with several accounts the error lists them.
  `account_list` (admin tier) shows them.
- **Confirm gates**: tools that send mail, share, delete, or notify others
  carry a `confirm` parameter (default `false`) that the server enforces.
  `meta.confirm` is `always` (`m365_delete`, `email_send`, `email_reply`,
  `email_forward`, `drive_share`, `email_folder_empty`, `calendar_forward`),
  `conditional` (`calendar_create_event`, `calendar_update_event`,
  `calendar_respond`, `email_rule_manage`) or `never`. The model must ask
  the user first; hosts should also require approval for `dangerous` and
  `critical` tools.
- **Resource-tagged sub-objects**: generic tools take `resource` plus exactly
  one matching sub-object (for example `email_changes`), not `oneOf`.
- **Compact results**: projections with `next_cursor`, `has_more` and a
  `summary`; lists return previews, not bodies.
- **Untrusted content**: subject, preview, body, location and file names are
  written by other people; the server instructions tell the model to treat
  them as data.
- **Layering**: tools (MCP layer) to services (Graph logic) to `graph.py`.
- **Encrypted caching**: AES-256 SQLite cache with compression, three-state
  TTL and per-resource invalidation.

### Cache architecture

The cache reduces repeated Graph calls for reads.

1. **AES-256 encryption** via SQLCipher. Keys come from the system keyring
   (Windows Credential Manager, macOS Keychain, Linux Secret Service), then
   `M365_MCP_CACHE_KEY`. Startup fails if SQLCipher is unavailable while
   encryption is enabled; a generated key that cannot be stored is logged as
   ephemeral.
2. **Three-state TTL per resource** (`cache_config.RESOURCE_TTL_POLICIES`):
   Fresh entries are returned with no Graph call; stale entries are still
   served until they expire; expired entries are refetched. For example
   `email` is fresh for 2 minutes and expires after 10; `email_folder` 5 and
   30; `event` 5 and 30; `drive_item` 10 and 60.
3. **Keys by account + resource**: a key combines the resolved account ID,
   the resource, the hashed normalised parameters and the cursor. Accounts
   never share entries.
4. **Compression** for entries of 50 KB or more.
5. **Invalidation on write**: each mutating tool clears the affected
   resources for that account only (`resource_cache.MUTATION_INVALIDATES`).
6. **Cleanup** keeps the cache under 2 GB (starts at 80%, reduces to 60%).
7. **Warming** is off by default. `M365_MCP_CACHE_WARMING=true` starts the
   background worker: it pre-loads the mail folder tree, inbox, upcoming events
   and contacts for each account (`cache_config.CACHE_WARMING_OPERATIONS`), and
   a stale `m365_list` / `m365_get` hit queues a `unified:<tool>` refresh task
   that re-runs the request with `refresh=true`.

Cache metadata is never returned to the model. The only model-facing control
is `refresh` on `m365_list` and `m365_get`:

```python
m365_list(resource="drive_item", path="/Documents")                # cached
m365_list(resource="drive_item", path="/Documents", refresh=True)  # bypass
```

#### Cache tools (admin tier, hidden by default)

1. **`admin_cache_get(view, task_id?, status?, account_id?, limit?)`**:
   `view` is `stats`, `tasks`, `task` or `warming`.
2. **`admin_cache_invalidate(scope, account_id?, reason?)`**: `scope` is a
   resource type (`email`, `email_folder`, `email_rule`, `event`,
   `calendar`, `contact`, `contact_folder`, `drive_item`) or `all`.

### Steering and Guidance Documents

Read and reference the below documentation and ensure compliance for all code edits.

- @.projects/steering/product.md
- @.projects/steering/tech.md
- @.projects/steering/structure.md
- @.projects/steering/python.md
- @.projects/steering/mcp-server.md
- @.projects/steering/tool-names.md

## Development Commands

```bash
# Install dependencies
uv sync

# Sign in a personal account (interactive device flow)
uv run authenticate.py

# Run the MCP server (requires M365_MCP_CLIENT_ID)
uv run m365-mcp

# Test suite (no network; live tests are skipped by default)
uv run pytest tests/ -q

# Live read-only tests on a signed-in personal account
M365_MCP_LIVE_TESTS=1 uv run pytest tests/test_integration_unified.py -v

# Type checking
uv run pyright

# Lint and format check (CI runs `ruff check`)
uvx ruff check .
uvx ruff format --check .

# Regenerate and verify the tool specs and the tool reference
uv run python scripts/build_unified_tool_specs.py
uv run python scripts/build_unified_tool_specs.py --check
uv run python scripts/generate_tools_doc.py --check

<<<<<<< HEAD
# Golden-prompt evaluation harness (needs ANTHROPIC_API_KEY and credits)
=======
# Golden-prompt evaluation harness (anthropic is a dev dependency; needs
# ANTHROPIC_API_KEY and credits, or --base-url for a local model)
>>>>>>> 15a702a (Docs sweep for v1.0.0: rewrite MCP_SERVER_TOOLS.md header and sections 1-3, fix test layout and commands in CLAUDE.md, steering, README, QUICKSTART, FILETREE)
uv run python -m evals.runner --help
```

Live tests are skipped unless `M365_MCP_LIVE_TESTS=1`. Never set it for
write-capable checks against a real mailbox unless you use a disposable
folder, draft, event and contact.

## Environment Variables

Authentication and tools:

- **`M365_MCP_CLIENT_ID`** (required): Azure app registration client ID
- **`M365_MCP_TENANT_ID`** (optional): defaults to `consumers`. Only personal
  accounts are supported.
- **`M365_MCP_TOOLSETS`** (optional): comma-separated tiers to register,
  from `core`, `extended`, `admin`. Default `core,extended` (23 tools).
  Unknown values fail at startup.
- **`M365_MCP_INTERACTIVE_AUTH`**: set by `authenticate.py`; normal MCP
  requests never start an interactive flow.
- **`M365_MCP_CURSOR_KEY`**: HMAC key for pagination cursors. Set it to keep
  cursors valid across restarts or workers; otherwise a random per-process
  key is used.
- **`MCP_FILE_ALLOWED_ROOTS`**: extra local folders (separated by
  `os.pathsep`) that file tools may read or write.
- **`MCP_FILE_DOWNLOAD_MAX_MB`**: largest OneDrive download (default 512).

Cache: `M365_MCP_CACHE_KEY`, `M365_MCP_CACHE_DB_PATH`,
`M365_MCP_CACHE_WARMING`.

HTTP transport: `MCP_TRANSPORT`, `MCP_HOST`, `MCP_PORT`, `MCP_PATH`,
`MCP_AUTH_METHOD` (`bearer` or `none`), `MCP_AUTH_TOKEN`, `MCP_ALLOW_INSECURE`,
`MCP_ALLOWED_ORIGINS`. See `.env.example` and `SECURITY.md`.

## Azure App Requirements

Supported account types: personal Microsoft accounts. Public client flows
must be allowed (device code). Required delegated permissions:

- offline_access
- Mail.ReadWrite
- Mail.Send (send, reply and forward; not covered by `Mail.ReadWrite`)
- Calendars.ReadWrite
- Files.ReadWrite
- Contacts.ReadWrite
- MailboxSettings.Read (working hours and time zone for `calendar_find_availability`)
- User.Read

The server requests `.default`, so it receives what the app registration
grants; a missing permission fails only the tools that need it.

## Testing

- `tests/` holds unit tests against a mocked Graph layer
  (`tests/unified_harness.py`, `tests/fixtures/graph/`), plus conformance
  tests: `test_tool_registry.py` compares the live `tools/list` with the
  specs; `test_unified_tool_specs.py` validates the specs;
  `test_parity.py` covers every legacy-to-unified mapping row;
  `test_sdk_client_conformance.py` drives the server through the MCP client
  SDK; `test_evals_harness.py` covers the `evals/` harness. Per-domain
  suites are `test_unified_*.py`, `test_services_*.py`, and one file per
  cross-cutting module (`test_graph_*.py`, `test_cursors.py`,
  `test_http_security.py`, `test_local_files.py`, `test_rate_limit.py`,
  `test_cache*.py`, and so on).
- Every `validation_rules` entry needs a test with its exact error text;
  spec examples are fixtures.
- Follow TDD (steering `python.md`): failing test first.
- The live test `tests/test_integration_unified.py` (reads only) is opt-in:
  it needs `M365_MCP_LIVE_TESTS=1`, a valid `M365_MCP_CLIENT_ID` and an
  authenticated personal account.
- Before finishing a change, all of these must pass: `uv run pytest tests/
  -q`, `uv run pyright`, `uvx ruff check .`, `uvx ruff format --check .`,
  `uv run python scripts/build_unified_tool_specs.py --check` and
  `uv run python scripts/generate_tools_doc.py --check`.

## Common Patterns

### Working with accounts

```python
# With one account signed in, omit account_id everywhere.
m365_list(resource="email", limit=10)

# With several accounts, pass the ID or the email address.
m365_list(resource="email", account_id="me@outlook.com", limit=10)
```

### Browse, find, read

```python
m365_list(resource="email", email_filter={"unread": True}, limit=20)
m365_search(query="tax return", resources=["email", "drive_item"])
m365_get(resource="email", id=email_id)
```

### Sending mail (confirm gate)

```python
# Ask the user to approve recipients and content, then:
email_send(mode="new", to=["alice@example.com"], subject="Hi",
           body="Hello", confirm=True)
```

### File transfer

```python
# Local file to OneDrive (local path must be inside the allowed folders)
drive_upload(local_path="C:/Users/me/report.pdf", parent_path="/Documents")

# OneDrive file or attachment to a local file
m365_get_content(resource="drive_item", id=item_id, mode="download",
                 save_path="C:/Users/me/Downloads/report.pdf")
```

Files above 4.8 MB use resumable upload sessions automatically
(`graph.upload_large_file()`).

## Important Notes

- Removing or renaming a tool, parameter or result field is a breaking
  change: only in a major version, recorded in `CHANGELOG.md`.
- Graph search queries add `ConsistencyLevel: eventual` automatically.
- Email and event bodies are returned as plain text
  (`outlook.body-content-type="text"`), capped by `body_max_chars`.
- Well-known mail folder aliases: `inbox`, `sent`, `drafts`, `deleted`,
  `junk`, `archive`, `root`.
- Moved emails and contacts get a new ID, returned in the result.
- The generated tool reference is `MCP_SERVER_TOOLS.md`; regenerate it with
  `scripts/generate_tools_doc.py`, never by hand.
