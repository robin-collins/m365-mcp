# Microsoft MCP

Powerful MCP server for Microsoft Graph API - a complete AI assistant toolkit for Outlook, Calendar, OneDrive, and Contacts.

## Features

- **Email Management**: Read, send, reply, manage attachments, organize folders
- **Calendar Intelligence**: Create, update, check availability, respond to invitations
- **OneDrive Files**: Upload, download, browse with pagination
- **Contacts**: Search and list contacts from your address book
- **Multi-Account**: Support for multiple Microsoft accounts (personal, work, school)
- **Unified Search**: Search across emails, files, events, and people

## Quick Start

**📚 See [QUICKSTART.md](QUICKSTART.md) for complete installation and setup guide.**

### TL;DR

```bash
# 1. Install
git clone https://github.com/elyxlz/microsoft-mcp.git
cd microsoft-mcp && uv sync

# 2. Configure (use .env.example template)
cp .env.example .env
# Edit .env with your MICROSOFT_MCP_CLIENT_ID

# 3. Authenticate
uv run authenticate.py

# 4. Run
uv run microsoft-mcp
```

### Claude Desktop

```bash
# Add Microsoft MCP server (replace with your Azure app ID)
claude mcp add microsoft-mcp -e MICROSOFT_MCP_CLIENT_ID=your-app-id-here -- uvx --from git+https://github.com/elyxlz/microsoft-mcp.git microsoft-mcp

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
- **`list_emails`** - List emails with optional body content
- **`get_email`** - Get specific email with attachments
- **`create_email_draft`** - Create email draft with attachments support
- **`send_email`** - Send email immediately with CC/BCC and attachments
- **`reply_to_email`** - Reply maintaining thread context
- **`reply_all_email`** - Reply to all recipients in thread
- **`update_email`** - Mark emails as read/unread
- **`move_email`** - Move emails between folders
- **`delete_email`** - Delete emails
- **`get_attachment`** - Get email attachment content
- **`search_emails`** - Search emails by query

### Calendar Tools
- **`list_events`** - List calendar events with details
- **`get_event`** - Get specific event details
- **`create_event`** - Create events with location and attendees
- **`update_event`** - Reschedule or modify events
- **`delete_event`** - Cancel events
- **`respond_event`** - Accept/decline/tentative response to invitations
- **`check_availability`** - Check free/busy times for scheduling
- **`search_events`** - Search calendar events

### Contact Tools
- **`list_contacts`** - List all contacts
- **`get_contact`** - Get specific contact details
- **`create_contact`** - Create new contact
- **`update_contact`** - Update contact information
- **`delete_contact`** - Delete contact
- **`search_contacts`** - Search contacts by query

### File Tools
- **`list_files`** - Browse OneDrive files and folders
- **`get_file`** - Download file content
- **`create_file`** - Upload files to OneDrive
- **`update_file`** - Update existing file content
- **`delete_file`** - Delete files or folders
- **`search_files`** - Search files in OneDrive

### Utility Tools
- **`unified_search`** - Search across emails, events, and files
- **`list_accounts`** - Show authenticated Microsoft accounts
- **`authenticate_account`** - Start authentication for a new Microsoft account
- **`complete_authentication`** - Complete the authentication process after entering device code

## Manual Setup

### 1. Azure App Registration

1. Go to [Azure Portal](https://portal.azure.com) → Microsoft Entra ID → App registrations
2. New registration → Name: `microsoft-mcp`
3. Supported account types: Personal + Work/School
4. Authentication → Allow public client flows: Yes
5. API permissions → Add these delegated permissions:
   - Mail.ReadWrite
   - Calendars.ReadWrite
   - Files.ReadWrite
   - Contacts.Read
   - People.Read
   - User.Read
6. Copy Application ID

### 2. Installation

```bash
git clone https://github.com/elyxlz/microsoft-mcp.git
cd microsoft-mcp
uv sync
```

### 3. Authentication

```bash
# Set your Azure app ID
export MICROSOFT_MCP_CLIENT_ID="your-app-id-here"

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
      "args": ["--from", "git+https://github.com/elyxlz/microsoft-mcp.git", "microsoft-mcp"],
      "env": {
        "MICROSOFT_MCP_CLIENT_ID": "your-app-id-here"
      }
    }
  }
}
```

Or for local development:

```json
{
  "mcpServers": {
    "microsoft": {
      "command": "uv",
      "args": ["--directory", "/path/to/microsoft-mcp", "run", "microsoft-mcp"],
      "env": {
        "MICROSOFT_MCP_CLIENT_ID": "your-app-id-here"
      }
    }
  }
}
```

## Transport Modes

Microsoft MCP supports two transport modes for different use cases:

### stdio (Default) - For Desktop Apps

**Use for:** Claude Desktop, local MCP clients

**Security:** Inherently secure through process isolation (no authentication required)

```bash
# Default mode - no configuration needed
export MICROSOFT_MCP_CLIENT_ID="your-app-id"
uv run microsoft-mcp
```

### Streamable HTTP - For Web/API Access

**Use for:** Web applications, remote access, multi-client scenarios

**Security:** ⚠️ **Requires authentication** (bearer token or OAuth)

**Protocol:** Uses MCP Streamable HTTP (spec 2025-03-26+)

```bash
# Generate secure token
export MCP_AUTH_TOKEN=$(openssl rand -hex 32)

# Configure Streamable HTTP with bearer authentication
export MICROSOFT_MCP_CLIENT_ID="your-app-id"
export MCP_TRANSPORT="http"
export MCP_AUTH_METHOD="bearer"
export MCP_HOST="127.0.0.1"
export MCP_PORT="8000"

# Start server
uv run microsoft-mcp
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

All tools require an `account_id` parameter as the first argument:

```python
# List accounts to get IDs
accounts = list_accounts()
account_id = accounts[0]["account_id"]

# Use account for operations
send_email(account_id, "user@example.com", "Subject", "Body")
list_emails(account_id, limit=10, include_body=True)
create_event(account_id, "Meeting", "2024-01-15T10:00:00Z", "2024-01-15T11:00:00Z")
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
accounts = list_accounts()
account_id = accounts[0]["account_id"]

# List latest emails with full content
emails = list_emails(account_id, limit=10, include_body=True)

# Reply maintaining thread
reply_to_email(account_id, email_id, "Thanks for your message. I'll review and get back to you.")

# Forward with attachments
email = get_email(email_id, account_id)
attachments = [get_attachment(email_id, att["id"], account_id) for att in email["attachments"]]
send_email(account_id, "boss@company.com", f"FW: {email['subject']}", email["body"]["content"], attachments=attachments)
```

### Intelligent Scheduling
```python
# Get account ID first
accounts = list_accounts()
account_id = accounts[0]["account_id"]

# Check availability before scheduling
availability = check_availability(account_id, "2024-01-15T10:00:00Z", "2024-01-15T18:00:00Z", ["colleague@company.com"])

# Create meeting with details
create_event(
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

- Tokens are cached locally in `~/.microsoft_mcp_token_cache.json`
- Use app-specific passwords if you have 2FA enabled
- Only request permissions your app actually needs
- Consider using a dedicated app registration for production

## Troubleshooting

- **Authentication fails**: Check your CLIENT_ID is correct
- **"Need admin approval"**: Use `MICROSOFT_MCP_TENANT_ID=consumers` for personal accounts
- **Missing permissions**: Ensure all required API permissions are granted in Azure
- **Token errors**: Delete `~/.microsoft_mcp_token_cache.json` and re-authenticate

## License

MIT