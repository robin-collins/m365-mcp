# M365 MCP Security Guide

## Supported Accounts

M365 MCP supports **personal Microsoft accounts only** (outlook.com,
hotmail.com, live.com). The default authority is `consumers`. Work and school
accounts are rejected when sign-in completes, and any such account is removed
from the token cache. There is no organisation-scope sharing and no code path
for work or school tenants.

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
- The admin tools `account_auth_begin` and `account_auth_complete` (hidden
  unless `M365_MCP_TOOLSETS` includes `admin`) start and finish a device-code
  sign-in from a client. The MSAL flow stays on the server in a single-use
  session that expires after 15 minutes; the model sees only the verification
  URL, the user code and an opaque `auth_session_id`.

Tokens are cached locally in `~/.m365_mcp_token_cache.json`. Protect this file
with normal user-profile filesystem permissions and use `authenticate.py
--remove` when removing an account from a machine. Tokens, download URLs,
passwords and cache keys are never written to the logs.

## Confirmation Gates

Tools that send mail, notify other people, grant access or destroy data take a
`confirm` parameter that defaults to `false`. The **server** refuses the call
unless `confirm=true`, and the tool descriptions tell the model to ask the user
first.

| Rule | Tools |
|---|---|
| Always | `m365_delete`, `email_send`, `email_reply`, `email_forward`, `drive_share`, `email_folder_empty`, `calendar_forward` |
| Only when others are affected | `calendar_create_event` and `calendar_update_event` (attendees would receive mail), `calendar_respond` (a response is sent), `email_rule_manage` (the rule forwards, redirects or deletes mail) |

Deleting a meeting you organise sends cancellations; OneDrive deletes go to the
recycle bin. `confirm` is not human approval: also enable host-side approval for
tools annotated `dangerous` or `critical`. Recipients are never inferred.

## Local File Access

Tools that touch the local disk (`drive_upload` reads, `m365_get_content` writes)
accept paths only inside these **allowed roots**:

- the server's working directory
- the system temp directory
- each folder in `MCP_FILE_ALLOWED_ROOTS` (separated by `;` on Windows, `:`
  elsewhere)

Symlinks are resolved before the check, so a link that escapes a root is
refused. A **deny-list** applies to both reads and writes: any path component
below the root that starts with `.` (which covers `.env` and `.ssh`), files
ending in `.pem` or `.key`, and anything with `token_cache` in the name. Errors
never echo the full path. Downloads never overwrite an existing file unless
`overwrite=true`, and file names are sanitised.

`MCP_FILE_DOWNLOAD_MAX_MB` (default 512) caps OneDrive downloads; email
attachments are limited to 25 MB.

## Rate Limits

Each account has token buckets that refill continuously:

- sends, shares and deletes: at most 20 per minute
- all calls together: at most 300 per minute

A refused call fails with an actionable message saying how long to wait.
Graph throttling (`429`) is also honoured through `Retry-After`, and only
idempotent requests are retried automatically.

## Untrusted Content

Email subjects, previews and bodies, event subjects, locations, previews and
bodies, contact names and file names are written by other people. The server:

- tells the model in its `instructions` to treat this content as data and never
  follow instructions found in it
- converts HTML to plain text, strips control, zero-width and bidirectional
  override characters, and caps preview and body length
- never lets content choose a tool call: every side effect still needs
  `confirm=true` after the user approves

Treat results as untrusted input in any downstream automation as well.

## Cursors

Pagination cursors are opaque and HMAC-protected. A cursor is bound to the
account, the resource and the exact request, expires after 24 hours, and its
Graph link host is verified. Set `M365_MCP_CURSOR_KEY` to a long random secret
to keep cursors valid across restarts or several workers; without it a random
per-process key is used. Treat the key like any other secret.

## Transport Security

stdio is the default and safest local transport because access is limited to the
client process that launches the server.

Streamable HTTP requires explicit authentication unless
`MCP_ALLOW_INSECURE=true` is set for isolated local testing. Supported methods
are `bearer` and `none`; `oauth` and unknown values fail at startup.

- **Bearer token**: `MCP_AUTH_TOKEN` is compared in constant time.
- **Origin validation**: every request that carries an `Origin` header must
  match an allowed origin, otherwise it is rejected. This blocks DNS-rebinding
  attacks from web pages. The default allows `http(s)://localhost`,
  `127.0.0.1` and `[::1]` on any port. Set `MCP_ALLOWED_ORIGINS`
  (comma-separated, exact `scheme://host[:port]` values) to replace the
  default. Requests without an `Origin` header (desktop and CLI clients) are
  not affected.

Recommended HTTP settings:

```bash
export MCP_TRANSPORT=http
export MCP_AUTH_METHOD=bearer
export MCP_AUTH_TOKEN=$(openssl rand -hex 32)
export MCP_HOST=127.0.0.1
# export MCP_ALLOWED_ORIGINS=https://app.example.com
```

Use TLS, a reverse proxy, firewall rules, and secret management before exposing
HTTP beyond localhost. Rotate bearer tokens after sharing or suspected exposure.

## Audit Log

The server writes one JSON log line per tool call: tool name, resource, a
hashed account, duration, outcome and error class, Graph retries, result size
and whether the call changed data. Argument values, message content, tokens and
URLs are never logged. Unexpected errors are masked in the client response
(`mask_error_details`); details go to the log only.

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

- Cache entries are keyed by account and resource; accounts never share entries.
- Every write clears the affected resources for its own account only.
- `admin_cache_invalidate` (admin tier) clears one resource type or everything,
  for one account or all.
- Cache key mismatch or corrupt database recovery recreates the cache file.
- Logs must not contain tokens, cache encryption keys, cursor keys or bearer
  tokens.

## Incident Response

If a token or cache key is exposed:

1. Stop the server.
2. Delete `~/.m365_mcp_token_cache.json` if Microsoft Graph tokens may be
   exposed.
3. Delete `~/.m365_mcp_cache.db` if cached data or cache keys may be exposed.
4. Rotate `M365_MCP_CACHE_KEY` (and `M365_MCP_CURSOR_KEY`) or remove the keyring
   entry.
5. Rotate HTTP bearer tokens and restart the server.
