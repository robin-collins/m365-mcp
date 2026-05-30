# M365 MCP

Powerful MCP server for Microsoft Graph API - a complete AI assistant toolkit for Outlook, Calendar, OneDrive, and Contacts.

## Features

- **Email Management**: Read, send, reply, manage attachments, organize folders
- **Calendar Intelligence**: Create, update, check availability, respond to invitations
- **OneDrive Files**: Upload, download, browse with pagination
- **Contacts**: Search and list contacts from your address book
- **Multi-Account**: Support for multiple Microsoft accounts (personal, work, school)
- **Unified Search**: Search across emails, files, events, and people
- **⚡ High-Performance Caching**: AES-256 encrypted cache with 300x performance improvement
- **🔒 Security & Compliance**: Encrypted-at-rest cache designed for
  GDPR/HIPAA-aligned deployments

## Quick Start

**📚 See [QUICKSTART.md](QUICKSTART.md) for complete installation and setup guide.**

### TL;DR

```bash
# 1. Install
git clone https://github.com/robin-collins/m365-mcp.git
cd m365-mcp && uv sync

# 2. Configure (use .env.example template)
cp .env.example .env
# Edit .env with your M365_MCP_CLIENT_ID

# 3. Authenticate
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

```bash
# Email examples
> read my latest emails with full content
> reply to the email from John saying "I'll review this today"
> send an email with attachment to alice@example.com

# Calendar examples  
> show my calendar for next week
> check if I'm free tomorrow at 2pm
> create a meeting with Bob next Monday at 10am

# File examples
> list files in my OneDrive
> upload this report to OneDrive
> search for "project proposal" across all my files

# Multi-account
> list all my Microsoft accounts
> send email from my work account
```

## Available Tools

### Email Tools
- **`email_list`** - List emails with optional body content
- **`email_get`** - Get a specific email with attachments
- **`email_create_draft`** - Create an email draft with attachment support
- **`email_send`** - Send email immediately with CC/BCC and attachments
- **`email_reply`** - Reply while maintaining thread context
- **`email_reply_all`** - Reply to all recipients in a thread
- **`email_forward`** - Forward an email
- **`email_update`** - Update message metadata
- **`email_move`** - Move email between folders
- **`email_delete`** - Delete email
- **`email_get_attachment`** - Download an attachment to a validated local path
- **`email_mark_read`** - Mark email read or unread
- **`email_flag`** - Add or clear follow-up flags
- **`email_add_category`** - Add an Outlook category
- **`email_archive`** - Archive an email
- **`search_emails`** - Search emails by query

### Calendar Tools
- **`calendar_list_calendars`** - List calendars
- **`calendar_create_calendar`** - Create a calendar
- **`calendar_delete_calendar`** - Delete a calendar
- **`calendar_list_events`** - List calendar events with details
- **`calendar_get_event`** - Get specific event details
- **`calendar_create_event`** - Create events with location and attendees
- **`calendar_update_event`** - Reschedule or modify events
- **`calendar_delete_event`** - Cancel events
- **`calendar_respond_event`** - Accept, decline, or tentatively accept invitations
- **`calendar_forward_event`** - Forward an event invitation
- **`calendar_propose_new_time`** - Propose a new meeting time
- **`calendar_get_free_busy`** - Get free/busy schedules
- **`calendar_check_availability`** - Check free/busy times for scheduling
- **`search_events`** - Search calendar events

### Contact Tools
- **`contact_list`** - List all contacts
- **`contact_get`** - Get specific contact details
- **`contact_create`** - Create a new contact
- **`contact_update`** - Update contact information
- **`contact_delete`** - Delete a contact
- **`contact_create_list`** - Create a contact list
- **`contact_add_to_list`** - Add contacts to a contact list
- **`contact_export`** - Export contacts
- **`search_contacts`** - Search contacts by query

### File Tools
- **`file_list`** - Browse OneDrive files and folders
- **`file_get`** - Download file content
- **`file_create`** - Upload files to OneDrive
- **`file_update`** - Update existing file content
- **`file_delete`** - Delete files
- **`file_copy`** - Copy files
- **`file_move`** - Move files
- **`file_rename`** - Rename files
- **`file_share`** - Create sharing links
- **`file_download_url`** - Get a temporary download URL
- **`folder_list`** - List OneDrive folders
- **`folder_get`** - Get folder metadata
- **`folder_get_tree`** - Build a recursive folder tree
- **`folder_create`** - Create folders
- **`folder_move`** - Move folders
- **`folder_rename`** - Rename folders
- **`folder_delete`** - Delete folders
- **`search_files`** - Search files in OneDrive

### Email Folder And Rule Tools
- **`emailfolders_list`** - List mail folders
- **`emailfolders_get`** - Get mail folder metadata
- **`emailfolders_get_tree`** - Build a recursive mail folder tree
- **`emailfolders_create`** - Create mail folders
- **`emailfolders_rename`** - Rename mail folders
- **`emailfolders_move`** - Move mail folders
- **`emailfolders_delete`** - Delete mail folders
- **`emailfolders_mark_all_as_read`** - Mark a folder as read
- **`emailfolders_empty`** - Empty a mail folder
- **`emailrules_list`** - List inbox rules
- **`emailrules_get`** - Get a rule
- **`emailrules_create`** - Create a rule
- **`emailrules_update`** - Update a rule
- **`emailrules_delete`** - Delete a rule
- **`emailrules_move_top`**, **`emailrules_move_bottom`**, **`emailrules_move_up`**, **`emailrules_move_down`** - Reorder rules

### Utility Tools
- **`search_unified`** - Search across emails, events, files, and contacts
- **`account_list`** - Show authenticated Microsoft accounts
- **`account_authenticate`** - Start authentication for a new Microsoft account
- **`account_complete_auth`** - Complete authentication after entering the device code
- **`server_get_version`** - Return server version metadata

### Cache Management Tools
- **`cache_get_stats`** - View cache statistics (size, entries, hit rate)
- **`cache_invalidate`** - Manually invalidate cache entries by pattern
- **`cache_task_get_status`** - Check status of queued cache tasks
- **`cache_task_list`** - List all cache tasks by account or status
- **`cache_warming_status`** - View cache warming/background refresh status

## ⚡ High-Performance Caching

M365 MCP includes an intelligent caching system that dramatically improves performance by reducing redundant API calls to Microsoft Graph.

### Key Features

- **🔒 AES-256 Encryption**: Cached data is encrypted at rest using SQLCipher by default
- **⚡ 300x Performance Boost**: Common operations like `folder_get_tree` go from 30s → <100ms
- **🧠 Intelligent TTL**: Three-state cache (Fresh/Stale/Expired) with automatic refresh
- **📦 Automatic Compression**: Large entries (≥50KB) automatically compressed (70-80% size reduction)
- **🔄 Optional Cache Warming**: Set `M365_MCP_CACHE_WARMING=true` to start
  the background worker, startup warming, and stale-cache refresh queue
- **🎯 Smart Invalidation**: Write operations automatically invalidate related caches
- **🌐 Multi-Account**: Complete isolation between different accounts
- **✅ Compliance Ready**: Encryption and retention controls for regulated deployments

### Performance Benchmarks

| Operation | Without Cache | With Cache | Speedup |
|-----------|---------------|------------|---------|
| `folder_get_tree` | 30s | <100ms | **300x** |
| `email_list` | 2-5s | <50ms | **40-100x** |
| `file_list` | 1-3s | <30ms | **30-100x** |
| Cache Hit Rate | N/A | >80% | **70%+ API call reduction** |

### Cache Configuration

The cache works automatically, but you can control its behavior:

```python
# Use cache (default - recommended)
folder_get_tree(account_id, path="/Documents")

# Force refresh (bypass cache, update with fresh data)
folder_get_tree(account_id, path="/Documents", force_refresh=True)

# Disable cache for this request only
email_list(account_id, folder="inbox", use_cache=False)
```

### Cache Security

- **Encryption**: AES-256 encryption via SQLCipher. If SQLCipher is missing
  while encryption is enabled, startup fails instead of silently using plaintext.
- **Key Storage**: System keyring (macOS Keychain, Windows Credential Manager, Linux Secret Service)
- **Fallback**: Environment variable `M365_MCP_CACHE_KEY` for headless servers;
  if neither keyring nor the env var is available, a generated ephemeral key is
  used with a warning
- **Plaintext Mode**: Only used when cache encryption is explicitly disabled
  by code, primarily for tests and diagnostics

### Cache Management

View cache statistics:
```python
stats = cache_get_stats()
# Returns: total_entries, size_bytes, hit_rate, oldest_entry, etc.
```

Manually invalidate cache:
```python
# Invalidate all email caches
cache_invalidate("email_*")

# Invalidate specific account's caches
cache_invalidate("email_*", account_id="account-123")
```

**📚 For complete cache documentation, see [CLAUDE.md](CLAUDE.md#cache-architecture)**

## Manual Setup

### 1. Azure App Registration

1. Go to [Azure Portal](https://portal.azure.com) → Microsoft Entra ID → App registrations
2. New registration → Name: `m365-mcp`
3. Supported account types: Personal + Work/School
4. Authentication → Allow public client flows: Yes
5. API permissions → Add these delegated permissions:
  - offline_access (required for refresh tokens; the CLI retries against the consumers authority if a personal account flags it as reserved)
  - Mail.ReadWrite
  - Calendars.ReadWrite
  - Files.ReadWrite
  - Contacts.Read
  - People.Read
  - User.Read
6. Copy Application ID

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

# Follow the prompts to authenticate your Microsoft accounts
```

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

**Security:** ⚠️ **Requires authentication** (bearer token or OAuth)

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

Account-scoped tools require an `account_id` argument. Established public tool
signatures keep their historical parameter order for compatibility, so use the
tool schema or examples for exact ordering instead of assuming `account_id` is
always first.

```python
# List accounts to get IDs
accounts = account_list()
account_id = accounts[0]["account_id"]

# Use account for operations
email_send(account_id, "user@example.com", "Subject", "Body", confirm=True)
email_list(account_id, limit=10, include_body=True)
calendar_create_event(account_id, "Meeting", "2024-01-15T10:00:00Z", "2024-01-15T11:00:00Z")
```

## Development

```bash
# Run tests
uv run pytest tests/ -v

# Type checking
uv run pyright

# Format code
uvx ruff format .

# Lint
uvx ruff check --fix --unsafe-fixes .
```

## Example: AI Assistant Scenarios

### Smart Email Management
```python
# Get account ID first
accounts = account_list()
account_id = accounts[0]["account_id"]

# List latest emails with full content
emails = email_list(account_id, limit=10, include_body=True)

# Reply maintaining thread
email_reply(account_id, email_id, "Thanks for your message. I'll review and get back to you.", confirm=True)

# Download attachments locally
email = email_get(email_id, account_id)
for attachment in email["attachments"]:
    email_get_attachment(
        email_id,
        attachment["id"],
        f"C:/Users/you/Downloads/{attachment['name']}",
        account_id,
    )
```

### Intelligent Scheduling
```python
# Get account ID first
accounts = account_list()
account_id = accounts[0]["account_id"]

# Check availability before scheduling
availability = calendar_check_availability(account_id, "2024-01-15T10:00:00Z", "2024-01-15T18:00:00Z", ["colleague@company.com"])

# Create meeting with details
calendar_create_event(
    account_id,
    "Project Review",
    "2024-01-15T14:00:00Z", 
    "2024-01-15T15:00:00Z",
    location="Conference Room A",
    body="Quarterly review of project progress",
    attendees=["colleague@company.com", "manager@company.com"]
)
```

## Security Notes

- Tokens are cached locally in `~/.m365_mcp_token_cache.json`
- Cache data is encrypted at rest using AES-256 SQLCipher in `~/.m365_mcp_cache.db`
- Encryption keys are loaded from system keyring or `M365_MCP_CACHE_KEY`; generated non-persistent keys produce a warning
- SQLCipher is required when cache encryption is enabled; plaintext cache mode is only used when explicitly requested by code
- Use app-specific passwords if you have 2FA enabled
- Only request permissions your app actually needs
- Consider using a dedicated app registration for production

## Troubleshooting

- **Authentication fails**: Check your CLIENT_ID is correct
- **"Need admin approval"**: Use `M365_MCP_TENANT_ID=consumers` for personal accounts
- **Missing permissions**: Ensure all required API permissions are granted in Azure
- **Token errors**: Delete `~/.m365_mcp_token_cache.json` and re-authenticate
- **Cache issues**: Delete `~/.m365_mcp_cache.db` to reset cache. If the stored key cannot open the database, the cache is recreated automatically.
- **Slow first requests**: Normal on a cold cache. Set `M365_MCP_CACHE_WARMING=true` to enable startup warming and stale-cache background refresh.

## License

MIT
