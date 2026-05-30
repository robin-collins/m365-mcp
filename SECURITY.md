# M365 MCP Security Guide

## Authentication

M365 MCP uses Microsoft Authentication Library (MSAL) public-client device-code
authentication for Microsoft Graph.

- Run `uv run authenticate.py` to perform interactive device-code login.
- Run `uv run authenticate.py --re-auth <account-id-or-email>` to verify that a
  cached refresh token can mint a new access token.
- Run `uv run authenticate.py --remove <account-id-or-email>` to remove one
  account's MSAL tokens, account metadata, and account-scoped database cache.
- Normal MCP requests use cached tokens silently.
- If no cached token is available, normal requests fail immediately with an
  actionable message instead of starting an interactive prompt.
- `M365_MCP_INTERACTIVE_AUTH=true` is reserved for explicit interactive flows.

Tokens are cached locally in `~/.m365_mcp_token_cache.json`. Protect this file
with normal user-profile filesystem permissions and use `authenticate.py
--remove` when removing an account from a machine.

## Transport Security

stdio is the default and safest local transport because access is limited to the
client process that launches the server.

Streamable HTTP requires explicit authentication unless
`MCP_ALLOW_INSECURE=true` is set for isolated local testing.

Recommended HTTP settings:

```bash
export MCP_TRANSPORT=http
export MCP_AUTH_METHOD=bearer
export MCP_AUTH_TOKEN=$(openssl rand -hex 32)
export MCP_HOST=127.0.0.1
```

Use TLS, a reverse proxy, firewall rules, and secret management before exposing
HTTP beyond localhost. Rotate bearer tokens after sharing or suspected exposure.

## Cache Encryption

The cache is encrypted at rest by default with SQLCipher and stored at
`~/.m365_mcp_cache.db`.

Key lookup order:

1. System keyring
2. `M365_MCP_CACHE_KEY`
3. Generated key

If neither keyring nor `M365_MCP_CACHE_KEY` can persist a generated key, the
server logs an ephemeral-key warning. In that state, encrypted cache files may be
unreadable after restart. For headless services, set `M365_MCP_CACHE_KEY` to a
base64-encoded 32-byte value.

```bash
export M365_MCP_CACHE_KEY=$(openssl rand -base64 32)
```

If SQLCipher is unavailable while encryption is enabled, startup fails rather
than silently writing plaintext. Plaintext cache mode is only used when
encryption is explicitly disabled by code, primarily for tests or diagnostics.

## Cache Warming

Startup warming and stale-cache background refresh are disabled by default.
Enable them with:

```bash
export M365_MCP_CACHE_WARMING=true
```

When enabled, the server owns the background worker lifecycle and stops the
worker and cache handles on shutdown.

## Data Handling

- Cache entries are scoped by account.
- Manual invalidation can be scoped with `account_id`.
- Cache key mismatch or corrupt database recovery recreates the cache file.
- Logs must not contain tokens, cache encryption keys, or bearer tokens.

## Incident Response

If a token or cache key is exposed:

1. Stop the server.
2. Delete `~/.m365_mcp_token_cache.json` if Microsoft Graph tokens may be
   exposed.
3. Delete `~/.m365_mcp_cache.db` if cached data or cache keys may be exposed.
4. Rotate `M365_MCP_CACHE_KEY` or remove the keyring entry.
5. Rotate HTTP bearer tokens and restart the server.
