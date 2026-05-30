# M365 MCP Quick Start

This guide gets the server installed, authenticated, and running with the
current runtime behavior.

## Prerequisites

- Python 3.11 or newer
- `uv`
- A Microsoft Entra app registration client ID with public client flows enabled
- Delegated Microsoft Graph permissions listed in `README.md`

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

Use `M365_MCP_TENANT_ID=consumers` for personal Microsoft accounts if the
default `common` authority returns an admin-consent error.

## Authenticate

Run the standalone authentication script before normal MCP server use:

```bash
uv run authenticate.py
```

The script enables the interactive device-code flow, stores MSAL tokens in
`~/.m365_mcp_token_cache.json`, and can be rerun when adding accounts.

Normal MCP requests do not start an interactive device flow. If no cached token
is available, the server fails fast with an actionable error asking you to run
`authenticate.py`. This prevents a tool request from blocking on terminal input.

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

HTTP transport should use bearer or OAuth authentication. Binding to
`127.0.0.1` is recommended unless a reverse proxy, firewall, and TLS are in
place.

## Cache Defaults

The local cache is encrypted with SQLCipher by default at
`~/.m365_mcp_cache.db`. If SQLCipher is unavailable while encryption is enabled,
startup fails instead of falling back to plaintext.

Keys are loaded from the system keyring, then `M365_MCP_CACHE_KEY`, then a
generated key. If the generated key cannot be persisted, the server logs a
warning because the cache may be unreadable after restart.

Startup warming and stale-cache background refresh are disabled by default. To
enable the worker-owned lifecycle:

```bash
export M365_MCP_CACHE_WARMING=true
uv run m365-mcp
```

## Verify

```bash
uv run pytest tests/ -v
uv run pyright
uvx ruff format .
uvx ruff check --fix --unsafe-fixes .
```

Some integration tests require a configured client ID and authenticated account.
