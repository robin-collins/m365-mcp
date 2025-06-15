# Microsoft MCP

Minimal, powerful MCP server for Microsoft Graph API (Outlook, Calendar, OneDrive).

## Quick Start

```bash
# Install
uv add microsoft-mcp

# Set up (get client ID from Azure Portal)
export MICROSOFT_MCP_CLIENT_ID="your-app-id"

# Run
uv run microsoft-mcp
```

## Azure Setup

1. Go to [Azure Portal](https://portal.azure.com) → Microsoft Entra ID → App registrations
2. New registration → Name: `microsoft-mcp`
3. Supported accounts: Personal + Work/School
4. Authentication → Allow public client flows: Yes
5. API permissions → Add: Mail.ReadWrite, Calendars.ReadWrite, Files.ReadWrite
6. Copy Application ID

## Tools

- `list_accounts()` - Show signed-in accounts
- `read_emails(count, folder, account_id)` - Read from any mail folder  
- `send_email(to, subject, body, account_id)` - Send email
- `get_calendar_events(days, account_id)` - List calendar events
- `create_event(subject, start, end, attendees, account_id)` - Create event
- `list_files(path, account_id)` - Browse OneDrive
- `download_file(file_id, account_id)` - Download as base64
- `upload_file(path, content_base64, account_id)` - Upload file
- `delete_file(file_id, account_id)` - Delete file/folder
- `search(query, types, account_id)` - Search across services

## Multi-Account

All tools support `account_id` parameter. Use `list_accounts()` to get IDs.

```python
# Default account
send_email("user@example.com", "Hi", "Hello!")

# Specific account  
send_email("user@example.com", "Hi", "Hello!", account_id="abc123")
```

## License

MIT