# M365 MCP Quick Start

This guide gets the server installed, authenticated, and running with the
current runtime behavior (v1.0.0, 29 tools, personal Microsoft accounts only).

## Prerequisites

- Python 3.11 or newer
- `uv`
- A Microsoft Entra app registration client ID with public client flows
  enabled, supporting **personal Microsoft accounts**
- Delegated Microsoft Graph permissions listed in `README.md`
- A personal Microsoft account (outlook.com, hotmail.com or live.com).
  Work and school accounts are not supported and are rejected at sign-in.

## Install

```bash
git clone https://github.com/robin-collins/m365-mcp.git
cd m365-mcp
uv sync
```

Copy the environment template and set your client ID:

```bash
cp .env.example .env
```

Set at least:

```bash
M365_MCP_CLIENT_ID=your-app-client-id-here
```

`M365_MCP_TENANT_ID` defaults to `consumers` (personal accounts only); leave it
unset.

Optional settings you may want early (all documented in `.env.example`):

- `M365_MCP_TOOLSETS`: tiers to expose. Default `core,extended` (23 tools);
  use `core` (16) for clients without tool search, or add `admin` (6 more) to
  sign in and inspect the cache from the client.
- `MCP_FILE_ALLOWED_ROOTS`: extra local folders the file tools may read or
  write (the working directory and temp directory are always allowed).

## Authenticate

Run the standalone authentication script before normal MCP server use:

```bash
uv run authenticate.py
```

The script enables the interactive device-code flow, stores MSAL tokens in
`~/.m365_mcp_token_cache.json`, and can be rerun when adding accounts. Sign in
with a personal Microsoft account; a work or school account is rejected and
removed from the token cache.

Use `uv run authenticate.py --re-auth <account-id-or-email>` to force-refresh a
cached token with the stored refresh token. Use
`uv run authenticate.py --remove <account-id-or-email>` to remove an account,
its token cache entries, and its account-scoped database cache rows.

Normal MCP requests do not start an interactive device flow. If no cached token
is available, the server fails fast with an actionable error asking you to run
`authenticate.py`. This prevents a tool request from blocking on terminal input.

You can also sign in from the assistant: add `admin` to `M365_MCP_TOOLSETS`
and it can call `account_auth_begin` (returns a URL and code) and then
`account_auth_complete`. `authenticate.py` remains the recommended path.

## Run With stdio

```bash
uv run m365-mcp
```

stdio is the default transport and is intended for local desktop MCP clients.

## Run With Streamable HTTP

```bash
export MCP_TRANSPORT=http
export MCP_AUTH_METHOD=bearer
export MCP_AUTH_TOKEN=$(openssl rand -hex 32)
export MCP_HOST=127.0.0.1
export MCP_PORT=8000
uv run m365-mcp
```

HTTP transport requires bearer authentication (`MCP_AUTH_METHOD=oauth` is not
supported). Binding to `127.0.0.1` is recommended unless a reverse proxy,
firewall, and TLS are in place. Browser requests must come from an allowed
`Origin`: loopback by default, or the values in `MCP_ALLOWED_ORIGINS`.

## First Calls

With one account signed in, `account_id` can be omitted everywhere:

```python
m365_list(resource="email", limit=5)              # newest mail in the inbox
m365_search(query="invoice", resources=["email", "drive_item"])
m365_list(resource="event")                       # next 7 days
calendar_find_availability(start="2026-10-01T00:00:00+09:30",
                           end="2026-10-02T00:00:00+09:30", slot_minutes=60)
```

With several accounts, pass `account_id` (the ID or the email address); the
error message lists the choices. Actions that send mail, notify attendees,
share files or delete data need `confirm=true` after the user approves.

See the README for the full tool list.

## Cache Defaults

The local cache is encrypted with SQLCipher by default at
`~/.m365_mcp_cache.db`. If SQLCipher is unavailable while encryption is enabled,
startup fails instead of falling back to plaintext.

Only `m365_list` and `m365_get` read through the cache. Pass `refresh=true`
to bypass it. With the `admin` tier enabled, `admin_cache_get` shows statistics
and `admin_cache_invalidate` clears entries.

Keys are loaded from the system keyring, then `M365_MCP_CACHE_KEY`, then a
generated key. If the generated key cannot be persisted, the server logs a
warning because the cache may be unreadable after restart.

Startup warming and stale-cache background refresh are disabled by default. To
enable them (folder tree, inbox, events and contacts are pre-loaded, and stale
entries refresh in the background):

```bash
export M365_MCP_CACHE_WARMING=true
uv run m365-mcp
```

## Verify

```bash
uv run pytest tests/ -q --ignore=tests/test_integration.py
uv run pyright
uvx ruff format .
uvx ruff check --fix --unsafe-fixes .
```

`tests/test_integration.py` is a live legacy test and is skipped above. To run
the live read-only checks against a signed-in personal account (they never
write):

```bash
M365_MCP_LIVE_TESTS=1 uv run pytest tests/test_integration_unified.py -v
```
