# Microsoft MCP

Microsoft Graph MCP server for Outlook, Calendar, and OneDrive with multi-account support.

## Features

- Multi-account support: Manage multiple Microsoft accounts (personal, work, university)
- Email: Read inbox messages, send emails
- Calendar: View upcoming events, create new events
- OneDrive: List files, upload/download files
- Device-code authentication: No redirect server needed
- Token caching: Sign in once per account

## Quick Start

### 1. Install

```bash
git clone https://github.com/your-org/microsoft-mcp
cd microsoft-mcp
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
```

### 2. Azure App Registration

Register an app in Azure AD (free):

1. Go to Azure Portal > Microsoft Entra ID > App registrations
2. Click "New registration"
3. Name: microsoft-mcp
4. Supported account types: Accounts in any organizational directory and personal Microsoft accounts
5. Authentication > Allow public client flows: Yes
6. API permissions > Add delegated permissions: Mail.ReadWrite, Mail.Send, Calendars.ReadWrite, Files.ReadWrite, offline_access, User.Read
7. Copy the Application (client) ID

### 3. Environment Setup

```bash
export MICROSOFT_MCP_CLIENT_ID="your-app-id-here"
export MICROSOFT_MCP_TENANT_ID="common"  # or "consumers" for personal accounts only
```

**Note**: If you get "Need admin approval" error, either:
- Use `MICROSOFT_MCP_TENANT_ID="consumers"` for personal Microsoft accounts only
- Ask your organization's admin to grant consent for the app
- Use a personal Microsoft account instead of a work/school account

### 4. Run the Server

```bash
uv run microsoft-mcp
```

On first run, visit the displayed URL and enter the device code to authenticate.

## Available Tools

### Email
- read_latest_email(count, account_id) - Get recent inbox messages
- send_email(to, subject, body, account_id) - Send plain text email
- send_html_email(to, subject, body_html, cc, bcc, account_id) - Send HTML email with CC/BCC support

### Calendar
- upcoming_events(days, account_id) - List events for next N days
- create_calendar_event(subject, start_iso, end_iso, attendees, account_id) - Create new event

### OneDrive
- drive_info(account_id) - Get drive metadata
- list_files_in_root(max_items, account_id) - List root folder contents
- download_drive_item(item_id, account_id) - Download file as base64
- upload_drive_file(path, content_base64, account_id) - Upload file
- create_drive_folder(parent_path, folder_name, account_id) - Create new folder
- delete_drive_item(item_id, account_id) - Delete file or folder
- move_drive_item(item_id, new_parent_id, new_name, account_id) - Move/rename items

### Accounts
- list_signed_in_accounts() - Show all cached accounts
- health_check(account_id) - Check server health and connectivity

## Multi-Account Usage

All tools accept an optional account_id parameter. Use list_signed_in_accounts() to get account IDs.

```python
# Use default account
client.tools.read_latest_email()

# Use specific account
client.tools.read_latest_email(account_id="account-id-here")
```

## Advanced Features

### Automatic Retry Logic
All API calls include automatic retry with exponential backoff for rate limits and transient errors.

### Request Logging
Enable detailed request/response logging:
```bash
export MICROSOFT_MCP_LOG_LEVEL=DEBUG
export MICROSOFT_MCP_LOG_REQUESTS=true
```

### Token Management
Tokens are automatically refreshed in the background before expiration.

### Health Monitoring
Use the health_check tool to verify authentication and API connectivity.