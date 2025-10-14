# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

M365 MCP is a Model Context Protocol (MCP) server that provides AI assistants with access to Microsoft Graph API. It enables management of Outlook emails, Calendar events, OneDrive files, and Contacts with support for multiple Microsoft accounts (personal, work, school).

## Architecture

### Core Modules

- **`src/m365_mcp/server.py`**: Entry point that initializes the FastMCP server
- **`src/m365_mcp/auth.py`**: Handles MSAL authentication using device flow, token caching to `~/.m365_mcp_token_cache.json`, and multi-account management
- **`src/m365_mcp/graph.py`**: HTTP client wrapper for Microsoft Graph API with retry logic, pagination, chunked uploads (15×320 KiB chunks), and rate limiting handling
- **`src/m365_mcp/tools.py`**: Defines 51 MCP tools using FastMCP decorators (`@mcp.tool`)
- **`authenticate.py`**: Standalone script for interactive account authentication

### Key Design Patterns

- **Multi-Account Architecture**: All tool functions require `account_id` as first parameter. Use `list_accounts()` to get available account IDs.
- **Token Management**: Uses MSAL `PublicClientApplication` with device flow authentication. Tokens are automatically refreshed and cached.
- **Pagination**: `graph.request_paginated()` follows `@odata.nextLink` for large result sets
- **Large File Handling**: Files >4.8MB use resumable upload sessions via `graph.upload_large_file()` and `graph.upload_large_mail_attachment()`
- **Error Handling**: Graph requests implement exponential backoff for 5xx errors and respect 429 rate limit headers

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

# Run authentication (interactive)
uv run authenticate.py

# Run MCP server (requires M365_MCP_CLIENT_ID env var)
uv run m365-mcp

# Run tests (requires authenticated account)
uv run pytest tests/ -v

# Type checking
uv run pyright

# Format code
uvx ruff format .

# Lint and auto-fix
uvx ruff check --fix --unsafe-fixes .
```

## Environment Variables

- **`M365_MCP_CLIENT_ID`** (required): Azure app registration client ID
- **`M365_MCP_TENANT_ID`** (optional): Defaults to "common". Use "consumers" for personal accounts only

## Azure App Requirements

Required delegated permissions:
- Mail.ReadWrite
- Calendars.ReadWrite
- Files.ReadWrite
- Contacts.Read
- People.Read
- User.Read

App must allow public client flows (device code authentication).

## Testing

Tests in `tests/test_integration.py` run against live Microsoft Graph API and require:
1. Valid `M365_MCP_CLIENT_ID` in environment
2. At least one authenticated account (run `authenticate.py` first)
3. Test account with email, calendar, and OneDrive access

## Common Patterns

### Working with Account IDs
```python
# All tools require account_id as first parameter
accounts = list_accounts()
account_id = accounts[0]["account_id"]

# Use in tool calls
send_email(account_id, to="user@example.com", subject="Test", body="Hello")
```

### Email with Attachments
```python
# Attachments are base64-encoded strings
attachments = [{
    "name": "file.pdf",
    "content_bytes": base64_string,
    "content_type": "application/pdf"
}]
send_email(account_id, to="...", subject="...", body="...", attachments=attachments)
```

### File Uploads
```python
# Files auto-switch to chunked upload for files >4.8MB
create_file(
    account_id=account_id,
    local_file_path="/path/to/file.pdf",
    parent_folder_id="root"  # Use "root" for OneDrive root
)
```

## Important Notes

- FastMCP handles tool registration via decorators; tools are auto-discovered from `tools.py`
- Graph API requests automatically add `ConsistencyLevel: eventual` header for search queries
- Email body content returns as plain text (via `outlook.body-content-type="text"` preference header)
- Folder names in `FOLDERS` dict map user-friendly names to Graph API folder IDs (e.g., "deleted" → "deleteditems")
