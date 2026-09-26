# M365 MCP

MCP server for Microsoft Graph: 29 intent-based tools that give an AI
assistant safe access to Outlook mail, Calendar, Contacts and OneDrive on
**personal Microsoft accounts** (outlook.com, hotmail.com, live.com).

## Features

- **Small tool surface**: 29 tools in three tiers (16 core, 7 extended, 6 admin,
  hidden by default) instead of one tool per Graph endpoint. Eight generic
  `m365_*` tools browse, read, search, create, update, move and delete across
  eight resource types; dedicated tools cover sending mail, calendar
  invitations, sharing and file transfer.
- **Safe by design**: anything that sends mail, notifies attendees, shares a
  file or deletes data needs `confirm=true`, enforced by the server. Local file
  access is limited to allowed folders with a deny-list for secrets.
- **Compact, typed results**: every tool has an `outputSchema`. Lists return
  previews (not full bodies) with an opaque `next_cursor` and a short summary.
- **Multi-account**: several personal accounts at once; `account_id` is
  optional when only one is signed in.
- **Whole-mailbox search**: email search runs server-side over the entire
  mailbox, plus events, contacts and OneDrive files in one call.
- **Free-time finder**: `calendar_find_availability` suggests free slots inside
  your working hours.
- **Encrypted caching**: AES-256 SQLCipher cache keyed by account and
  resource; the only model-facing control is `refresh`.
- **Hardened transports**: stdio by default; Streamable HTTP with bearer
  token, constant-time comparison and Origin validation.
- **Audit log and rate limits**: one JSON log line per call (no argument
  values or secrets); per-account limits on sends, shares and deletes.

Only personal Microsoft accounts are supported. Work and school accounts are
rejected at sign-in.

## Quick Start

**See [QUICKSTART.md](QUICKSTART.md) for the complete installation and setup guide.**

### TL;DR

```bash
# 1. Install
git clone https://github.com/robin-collins/m365-mcp.git
cd m365-mcp && uv sync

# 2. Configure (use .env.example template)
cp .env.example .env
# Edit .env with your M365_MCP_CLIENT_ID

# 3. Sign in a personal Microsoft account
uv run authenticate.py

# 4. Run
uv run m365-mcp
```

### Claude Desktop

```bash
# Add M365 MCP server (replace with your Azure app ID)
claude mcp add m365-mcp -e M365_MCP_CLIENT_ID=your-app-id-here -- uvx --from git+https://github.com/robin-collins/m365-mcp.git m365-mcp

# Start Claude Desktop
claude
```

### Usage Examples

```text
# Email
> show my unread emails from last week
> find the email about the Telstra migration
> reply to Jane saying "Tuesday works" (asks you to confirm before sending)

# Calendar
> what is on my calendar next week?
> when am I free for an hour on Thursday?
> book a dentist appointment on Friday at 9am

# Files
> what is in my OneDrive Documents folder?
> upload budget.xlsx from Downloads to /Documents
> send me a view-only link to budget.xlsx (asks you to confirm)

# Contacts and accounts
> put Jane in my Family contacts folder
> use my second account for this
```

## Available Tools

The server exposes 29 tools. `M365_MCP_TOOLSETS` (default `core,extended`)
chooses the tiers; see [Client Configuration](#client-configuration). Every
Microsoft 365 tool takes an optional `account_id`. The complete input and
output schema of each tool is in
[`docs/unified-tools/SCHEMA_REFERENCE.md`](docs/unified-tools/SCHEMA_REFERENCE.md)
and [`MCP_SERVER_TOOLS.md`](MCP_SERVER_TOOLS.md).

Safety: **safe** = read-only; **moderate** = changes data; **dangerous** =
communicates with other people or grants access; **critical** = destroys data.
"Confirm" means `confirm=true` is required (`conditional` = only in some
cases, as described).

### Core tier (16, on by default)

| Tool | Safety | What it does |
|---|---|---|
| `m365_list` | safe | Browse emails in a folder, events in a time window, calendars, contacts, contact folders, mail folders, inbox rules or OneDrive files (optionally as a tree) |
| `m365_get` | safe | Read one item by ID: email with body, event with attendees, contact, folder, rule, calendar, OneDrive item, or the status of a copy (`resource="operation"`) |
| `m365_search` | safe | Find emails, events, contacts or OneDrive files by free text, one type or several at once |
| `m365_get_content` | moderate | Save a OneDrive file or email attachment to a local file, get a temporary download link, or export a contact as a vCard |
| `m365_create` | moderate | Create a mail folder, calendar, contact, contact folder or OneDrive folder |
| `m365_update` | moderate | Mark read, flag, categorise, set importance, rename folders and files, edit contact details |
| `m365_move` | moderate | Move an email, mail folder, contact or OneDrive item (emails and contacts get a new ID) |
| `m365_delete` | critical, confirm | Delete an email, folder, rule, event, calendar, contact or OneDrive item (OneDrive items go to the recycle bin; deleting a meeting you organise sends cancellations) |
| `email_create_draft` | moderate | Create an unsent draft (sends nothing) |
| `email_send` | dangerous, confirm | Send a new email or a draft |
| `email_reply` | dangerous, confirm | Reply to the sender or to everyone |
| `email_forward` | dangerous, confirm | Forward an email with an optional note |
| `calendar_create_event` | dangerous, conditional | Add an event; confirm required only when attendees would be emailed |
| `calendar_update_event` | dangerous, conditional | Change an event; confirm required when attendees are notified |
| `calendar_respond` | dangerous, conditional | Accept, tentatively accept or decline an invitation; confirm required when a response is emailed |
| `calendar_find_availability` | safe | Show your busy times and suggest free slots inside your working hours (own calendar only) |

### Extended tier (7, on by default)

| Tool | Safety | What it does |
|---|---|---|
| `drive_upload` | moderate | Upload a local file to OneDrive as a new file or replace an existing one |
| `drive_copy` | moderate | Copy a OneDrive file or folder (asynchronous; returns an `operation_id`) |
| `drive_share` | dangerous, confirm | Share a file or folder by link or by inviting named people |
| `email_folder_mark_all_read` | moderate | Mark every unread message in a mail folder as read (bounded per call) |
| `email_folder_empty` | critical, confirm | Delete all messages in a mail folder such as Junk Email (bounded per call) |
| `email_rule_manage` | dangerous, conditional | Create, change, enable/disable or reorder an inbox rule; confirm required for rules that forward, redirect or delete |
| `calendar_forward` | dangerous, confirm | Forward a meeting invitation to named people |

### Admin tier (6, hidden by default; add `admin` to `M365_MCP_TOOLSETS`)

| Tool | Safety | What it does |
|---|---|---|
| `account_list` | safe | List the signed-in accounts (needed only with more than one account) |
| `account_auth_begin` | moderate | Start a device-code sign-in; returns a URL, a code and an `auth_session_id` |
| `account_auth_complete` | moderate | Finish the sign-in (single non-blocking poll); work or school accounts are rejected |
| `admin_cache_get` | safe | Cache statistics, background tasks, one task, or warming progress (`view`) |
| `admin_cache_invalidate` | moderate | Clear cached results for one resource type or all, for one account or all |
| `admin_server_info` | safe | Server version, protocol versions, enabled toolsets |

## High-Performance Caching

Reads through `m365_list` and `m365_get` use an encrypted local cache, which
cuts repeated Microsoft Graph calls and makes repeated browsing fast.

### Key Features

- **AES-256 encryption**: cached data is encrypted at rest using SQLCipher by default
- **Three-state TTL per resource**: fresh (returned immediately), stale (still
  served until it expires) and expired (refetched); for example `email` is
  fresh for 2 minutes and expires after 10, `drive_item` 10 and 60 minutes
- **Automatic compression**: entries of 50 KB or more are gzip-compressed
- **Keys by account and resource**: accounts never share entries; entries
  are keyed by the resolved account, the resource, the normalised request
  and the cursor
- **Smart invalidation**: every mutating tool clears the affected resources
  for its own account only
- **Optional cache warming**: set `M365_MCP_CACHE_WARMING=true` to pre-load
  the folder tree, inbox, upcoming events and contacts at startup and refresh
  stale entries in the background
- **Automatic cleanup**: kept under 2 GB

### The `refresh` parameter

The model never manages the cache. The only control is `refresh` on
`m365_list` and `m365_get`:

```python
# Served from the cache when fresh (default)
m365_list(resource="drive_item", path="/Documents")

# Bypass the cache and fetch fresh data
m365_list(resource="drive_item", path="/Documents", refresh=True)
m365_get(resource="email", id=email_id, refresh=True)
```

### Cache Security

- **Encryption**: AES-256 encryption via SQLCipher. If SQLCipher is missing
  while encryption is enabled, startup fails instead of silently using plaintext.
- **Key storage**: system keyring (macOS Keychain, Windows Credential Manager, Linux Secret Service)
- **Fallback**: environment variable `M365_MCP_CACHE_KEY` for headless servers;
  if neither keyring nor the env var is available, a generated ephemeral key is
  used with a warning
- **Plaintext mode**: only used when cache encryption is explicitly disabled
  by code, primarily for tests and diagnostics

### Cache Management (admin tier)

Add `admin` to `M365_MCP_TOOLSETS` to enable the cache tools:

```python
# Statistics: entries, size, hits, per-resource breakdown
admin_cache_get(view="stats")

# Background tasks and cache warming progress
admin_cache_get(view="tasks", status="running")
admin_cache_get(view="warming")

# Clear cached emails for one account, or everything
admin_cache_invalidate(scope="email", account_id="me@outlook.com", reason="stale inbox")
admin_cache_invalidate(scope="all")
```

**For the cache guides, see [docs/cache_user_guide.md](docs/cache_user_guide.md),
[docs/cache_examples.md](docs/cache_examples.md) and
[docs/cache_security.md](docs/cache_security.md); for the architecture, see
[CLAUDE.md](CLAUDE.md#cache-architecture).**

## Manual Setup

### 1. Azure App Registration

1. Go to [Azure Portal](https://portal.azure.com) → Microsoft Entra ID → App registrations
2. New registration → Name: `m365-mcp`
3. Supported account types: **Personal Microsoft accounts only**
4. Authentication → Allow public client flows: Yes
5. API permissions → Add these delegated permissions:
  - offline_access (required for refresh tokens; the CLI retries against the consumers authority if a personal account flags it as reserved)
  - Mail.ReadWrite (read, draft, move, delete mail and rules)
  - Mail.Send (send, reply, forward; `Mail.ReadWrite` does not cover sending)
  - Calendars.ReadWrite
  - Files.ReadWrite
  - Contacts.ReadWrite
  - MailboxSettings.Read (working hours and time zone for `calendar_find_availability`)
  - User.Read
6. Copy Application ID

The server requests the `.default` scope, so it gets exactly the permissions
granted to the app registration. A missing permission shows up as a
`403` error for that tool only. `People.Read` is not needed.

The default authority is `consumers`. Set `M365_MCP_TENANT_ID` only if you
know you need a different value; work and school accounts are still rejected.

### 2. Installation

```bash
git clone https://github.com/robin-collins/m365-mcp.git
cd m365-mcp
uv sync
```

### 3. Authentication

```bash
# Set your Azure app ID
export M365_MCP_CLIENT_ID="your-app-id-here"

# Run authentication script
uv run authenticate.py

# Force-refresh a cached token to verify silent renewal
uv run authenticate.py --re-auth <account-id-or-email>

# Remove an account, its tokens, and its local data cache
uv run authenticate.py --remove <account-id-or-email>

# Follow the prompts to sign in your personal Microsoft accounts
```

Alternatively add the `admin` tier and let the assistant call
`account_auth_begin` / `account_auth_complete`. You enter the displayed code
at the shown URL; the underlying MSAL flow stays on the server and the model
only sees an opaque `auth_session_id`.

### 4. Claude Desktop Configuration

Add to your Claude Desktop configuration:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`  
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "microsoft": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/robin-collins/m365-mcp.git", "m365-mcp"],
      "env": {
        "M365_MCP_CLIENT_ID": "your-app-id-here"
      }
    }
  }
}
```

Or for local development:

```json
{
  "mcpServers": {
    "m365-mcp": {
      "command": "uv",
      "args": ["--directory", "c:\\projects\\m365-mcp", "run", "m365-mcp"],
      "env": {
        "M365_MCP_CLIENT_ID": "your-app-id-here"
      }
    }
  }
}
```

## Client Configuration

The server exposes 29 tools in three tiers: `core` (16), `extended` (7) and
`admin` (6, hidden by default). `M365_MCP_TOOLSETS` (comma separated, default
`core,extended`) chooses which tiers the server registers. Cutting the tool
list saves model context: the core tier costs about 9.4k tokens of tool
definitions and the default `core,extended` about 13.5k. Unknown values fail
at startup.

| Client situation | Set `M365_MCP_TOOLSETS` to | Also |
|---|---|---|
| Client without tool search or deferred loading | `core` | Users lose `drive_*`, bulk mail and rule tools |
| Client with tool search or deferred loading | `core,extended` (default) | Load `core` eagerly, defer `extended` |
| Signing in from the client (no terminal) | add `admin` | `uv run authenticate.py` remains the primary sign-in path |

Tier contents:

- **core:** "m365_list", "m365_get", "m365_search", "m365_get_content", "m365_create", "m365_update", "m365_move", "m365_delete", "email_create_draft", "email_send", "email_reply", "email_forward", "calendar_create_event", "calendar_update_event", "calendar_respond", "calendar_find_availability"
- **extended:** "drive_upload", "drive_copy", "drive_share", "email_folder_mark_all_read", "email_folder_empty", "email_rule_manage", "calendar_forward"
- **admin:** "account_list", "account_auth_begin", "account_auth_complete", "admin_cache_get", "admin_cache_invalidate", "admin_server_info"

### Claude Desktop and Claude Code (stdio)

Claude Desktop uses the `mcpServers` block shown under *Claude Desktop
Configuration* above; add `"M365_MCP_TOOLSETS": "core,extended"` to `env`.
Claude Code:

```bash
claude mcp add m365 --env M365_MCP_CLIENT_ID=your-app-id \
  --env M365_MCP_TOOLSETS=core,extended \
  -- uv --directory /path/to/m365-mcp run m365-mcp
```

Claude API MCP connector and Claude Code both support tool search: keep the
`core` tools loaded and let `extended` load on demand. Have the host ask for
approval on tools annotated `dangerous` or `critical` (send, share and delete
tools). The server's `confirm=true` gate is a second check, not a substitute.

### OpenAI (Responses API, remote MCP)

Run the server with HTTP transport (see *Transport Modes*), then:

```json
{
  "type": "mcp",
  "server_label": "m365",
  "server_url": "https://your-host.example/mcp",
  "authorization": "<bearer token>",
  "allowed_tools": ["m365_list", "m365_get", "m365_search", "m365_get_content"],
  "require_approval": "always",
  "defer_loading": true
}
```

`allowed_tools` imports only the listed tools; use it to expose the read
tools alone, or the `core` list above. `defer_loading: true` keeps the
function definitions out of the prompt until the model searches for them,
which suits the `extended` tier. Keep `require_approval` on for tools that
send, share or delete.

### Gemini CLI (Streamable HTTP)

```json
{
  "mcpServers": {
    "m365": {
      "httpUrl": "http://127.0.0.1:8000/mcp",
      "headers": { "Authorization": "Bearer <token>" },
      "timeout": 30000,
      "trust": false,
      "includeTools": ["m365_list", "m365_get", "m365_search", "m365_get_content"],
      "excludeTools": ["m365_delete", "email_folder_empty", "drive_share"]
    }
  }
}
```

`includeTools` is an allowlist and `excludeTools` a blocklist; exclusion wins.
Leave `trust` false so Gemini CLI asks before running tools.

### Choosing what to expose

Prefer restricting on the server (`M365_MCP_TOOLSETS`) so every client sees
the same surface, and add client-side `allowed_tools` / `includeTools` for
per-agent least privilege (for example a read-only agent with only the
`m365_list`, `m365_get`, `m365_search` and `m365_get_content` tools).

## Transport Modes

M365 MCP supports two transport modes for different use cases:

### stdio (Default) - For Desktop Apps

**Use for:** Claude Desktop, local MCP clients

**Security:** Inherently secure through process isolation (no authentication required)

```bash
# Default mode - no configuration needed
export M365_MCP_CLIENT_ID="your-app-id"
uv run m365-mcp
```

### Streamable HTTP - For Web/API Access

**Use for:** Web applications, remote access, multi-client scenarios

**Security:** ⚠️ **Requires authentication** (bearer token; `MCP_AUTH_METHOD=oauth` is not supported). Browser requests must come from an allowed `Origin` (loopback by default; set `MCP_ALLOWED_ORIGINS` to change)

**Protocol:** Uses MCP Streamable HTTP (spec 2025-03-26+)

```bash
# Generate secure token
export MCP_AUTH_TOKEN=$(openssl rand -hex 32)

# Configure Streamable HTTP with bearer authentication
export M365_MCP_CLIENT_ID="your-app-id"
export MCP_TRANSPORT="http"
export MCP_AUTH_METHOD="bearer"
export MCP_HOST="127.0.0.1"
export MCP_PORT="8000"

# Start server
uv run m365-mcp
```

**Client connection:**
```python
from mcp.client.http import http_client

async with http_client(
    "http://localhost:8000/mcp",
    headers={"Authorization": f"Bearer {your_token}"}
) as (read, write):
    # Use the session...
```

**📚 See [SECURITY.md](SECURITY.md) for complete security guide and authentication options**

## Multi-Account Support

Every Microsoft 365 tool accepts an optional `account_id` (the account ID or
its email address).

- With **one** signed-in account, omit it.
- With **several** accounts, omitting it fails with an error that lists each
  account's ID and email, so the assistant can ask you which one to use.
- `account_list` (admin tier) shows the signed-in accounts.

```python
# One account signed in
m365_list(resource="email", limit=10)

# Several accounts
m365_list(resource="email", account_id="me@outlook.com", limit=10)
m365_list(resource="event", account_id="family@hotmail.com")
```

All accounts must be personal Microsoft accounts. Cache entries, rate limits
and cursors are separate per account.

## Development

```bash
# Run the test suite (no network; live tests are skipped by default)
uv run pytest tests/ -q

# Live read-only tests against a signed-in personal account
M365_MCP_LIVE_TESTS=1 uv run pytest tests/test_integration_unified.py -v

# Type checking
uv run pyright

# Format and lint
uvx ruff format --check .
uvx ruff check .

# Regenerate and verify the tool specs and reference
uv run python scripts/build_unified_tool_specs.py
uv run python scripts/build_unified_tool_specs.py --check
uv run python scripts/generate_tools_doc.py --check
```

The tool surface is defined by the generated specs in
[`docs/unified-tools/`](docs/unified-tools/README.md); see
[CLAUDE.md](CLAUDE.md) for the architecture and [CHANGELOG.md](CHANGELOG.md)
for the 1.0.0 migration table from the old tool names.

## Example: AI Assistant Scenarios

### Smart Email Management

```python
# Newest unread mail (previews only)
page = m365_list(resource="email", email_filter={"unread": True}, limit=10)

# Read one message in full
email = m365_get(resource="email", id=page["items"][0]["id"])

# Draft a reply for review, or reply after the user approves
email_reply(email_id=email["item"]["id"], mode="sender",
            body="Thanks, I'll review and get back to you.", confirm=True)

# Save an attachment locally (inside an allowed folder)
m365_get_content(resource="email", id=email["item"]["id"], mode="download",
                 attachment_id=email["item"]["attachments"][0]["id"],
                 save_path="C:/Users/you/Downloads/attachment.pdf")

# Archive the message
m365_move(resource="email", id=email["item"]["id"], destination_id="archive")
```

### Intelligent Scheduling

```python
# When am I free for an hour on Thursday?
calendar_find_availability(start="2026-10-01T00:00:00+09:30",
                           end="2026-10-02T00:00:00+09:30",
                           slot_minutes=60, max_slots=3)

# Private appointment (no attendees, no confirm needed)
calendar_create_event(subject="Dentist", start="2026-10-02T09:00:00+09:30",
                      end="2026-10-02T10:00:00+09:30", location="City Dental")

# Meeting with attendees emails invitations, so confirm is required
calendar_create_event(subject="Project Review",
                      start="2026-10-02T14:00:00+09:30",
                      end="2026-10-02T15:00:00+09:30",
                      attendees=[{"address": "colleague@example.com"}], confirm=True)
```

Date-times use RFC 3339 with an offset. Availability covers your own calendar
only, because Microsoft Graph does not expose other people's free/busy for
personal accounts.

### OneDrive

```python
# Upload, then share by view-only link (asks the user first)
drive_upload(local_path="C:/Users/you/Downloads/budget.xlsx",
             parent_path="/Documents")
drive_share(item_id=item_id, mode="link", link_type="view", confirm=True)

# Copy is asynchronous: check the returned operation_id
drive_copy(item_id=item_id, destination_path="/Backups")
m365_get(resource="operation", id=operation_id)
```

## Security Notes

- Personal Microsoft accounts only; work and school sign-ins are rejected
- Tokens are cached locally in `~/.m365_mcp_token_cache.json`
- Cache data is encrypted at rest using AES-256 SQLCipher in `~/.m365_mcp_cache.db`
- Encryption keys are loaded from system keyring or `M365_MCP_CACHE_KEY`; generated non-persistent keys produce a warning
- SQLCipher is required when cache encryption is enabled; plaintext cache mode is only used when explicitly requested by code
- Sending, sharing, deleting and notifying other people require `confirm=true`
- Local file access is limited to the working directory, the temp directory and `MCP_FILE_ALLOWED_ROOTS`; hidden and secret-like files are refused
- Email, event, contact and file content is written by other people and is treated as data, never as instructions
- Only request permissions your app actually needs
- Consider using a dedicated app registration for production

See [SECURITY.md](SECURITY.md) for the full security guide.

## Troubleshooting

- **Authentication fails**: Check your CLIENT_ID is correct
- **"Need admin approval"** or a work/school account is rejected: only personal
  accounts are supported; leave `M365_MCP_TENANT_ID` unset (default `consumers`)
- **Missing permissions**: Ensure all required API permissions are granted in Azure
- **Token errors**: Delete `~/.m365_mcp_token_cache.json` and re-authenticate
- **"several accounts are signed in"**: pass `account_id` (the error lists the choices)
- **"Invalid cursor: it does not match this request"**: repeat the call without `cursor`;
  cursors are valid only for the identical request, for 24 hours, and expire
  on restart unless `M365_MCP_CURSOR_KEY` is set
- **Local path refused**: the path must be inside the working directory, the
  temp directory or a folder in `MCP_FILE_ALLOWED_ROOTS`, and not hidden or
  secret-like
- **Cache issues**: Delete `~/.m365_mcp_cache.db` to reset cache. If the stored key cannot open the database, the cache is recreated automatically.
- **Stale results**: call `m365_list` or `m365_get` with `refresh=true`
- **Slow first requests**: Normal on a cold cache. Set `M365_MCP_CACHE_WARMING=true` to enable startup warming and stale-cache background refresh.

## License

MIT
