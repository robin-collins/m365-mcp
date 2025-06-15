# Microsoft MCP

Powerful MCP server for Microsoft Graph API - a complete AI assistant toolkit for Outlook, Calendar, OneDrive, and Contacts.

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
5. API permissions → Add these delegated permissions:
   - Mail.ReadWrite
   - Calendars.ReadWrite
   - Files.ReadWrite
   - Contacts.Read
   - People.Read
   - User.Read
6. Copy Application ID

## Features for AI Assistants

### 📧 Email Management
- **Read emails** with full body content and conversation threading
- **Reply to emails** maintaining thread context
- **Send emails** with CC/BCC and file attachments
- **Manage email state**: mark as read/unread, move between folders
- **Download attachments** from any email
- **Get specific email** details including all attachments

### 📅 Calendar Intelligence
- **List events** with complete details (location, attendees, body)
- **Check availability** for smart scheduling
- **Create events** with location, description, and attendees
- **Update events** - reschedule, change details
- **Delete/cancel events** with automatic notifications
- **Respond to invitations** (accept/decline/tentative)

### 👥 Contacts & People
- **Search contacts** by name or email
- **List all contacts** with full details
- **People API** integration for richer data

### 📁 OneDrive Files
- **Browse files** with pagination support
- **Upload/download** any file type
- **Delete files** and folders
- **File metadata** including size and modification time

### 🔍 Unified Search
- **Search everything**: emails, events, files, and people
- **Configurable result limits**
- **Multi-type search** in one query

## All Tools

### Email Tools
- `read_emails(count, folder, include_body, account_id)` - Read with full content
- `get_email(email_id, account_id)` - Get specific email with attachments
- `reply_to_email(email_id, body, reply_all, account_id)` - Thread-aware replies
- `send_email(to, subject, body, cc, attachments, account_id)` - Full-featured sending
- `mark_email_read(email_id, is_read, account_id)` - Manage read status
- `move_email(email_id, destination_folder, account_id)` - Organize emails
- `download_attachment(email_id, attachment_id, account_id)` - Get attachments

### Calendar Tools  
- `get_calendar_events(days, include_details, account_id)` - Rich event data
- `check_availability(start, end, attendees, account_id)` - Free/busy check
- `create_event(subject, start, end, location, body, attendees, timezone, account_id)`
- `update_event(event_id, subject, start, end, location, body, account_id)`
- `delete_event(event_id, send_cancellation, account_id)`
- `respond_to_event(event_id, response, message, account_id)`

### Contact Tools
- `get_contacts(search, limit, account_id)` - Search or list contacts

### File Tools
- `list_files(path, next_link, account_id)` - Browse with pagination
- `download_file(file_id, account_id)` - Get file content
- `upload_file(path, content_base64, account_id)` - Upload files
- `delete_file(file_id, account_id)` - Remove files

### Search & Discovery
- `search(query, types, limit, account_id)` - Universal search
- `list_accounts()` - Show all signed-in accounts

## Multi-Account Support

All tools support `account_id` parameter for multi-account scenarios:

```python
# Default account
send_email("user@example.com", "Subject", "Body")

# Specific account  
send_email("user@example.com", "Subject", "Body", account_id="home-account-id")
```

## Example: AI Assistant Scenarios

### Smart Email Management
```python
# Read latest emails with full content
emails = read_emails(count=10, include_body=True)

# Reply maintaining thread
reply_to_email(email_id, "Thanks for your message. I'll review and get back to you.")

# Forward with attachments
email = get_email(email_id)
attachments = [download_attachment(email_id, att["id"]) for att in email["attachments"]]
send_email("boss@company.com", f"FW: {email['subject']}", email["body"]["content"], attachments=attachments)
```

### Intelligent Scheduling
```python
# Check availability before scheduling
availability = check_availability("2024-01-15T10:00:00Z", "2024-01-15T18:00:00Z", ["colleague@company.com"])

# Create meeting with details
create_event(
    "Project Review",
    "2024-01-15T14:00:00Z", 
    "2024-01-15T15:00:00Z",
    location="Conference Room A",
    body="Quarterly review of project progress",
    attendees=["colleague@company.com", "manager@company.com"]
)
```

## License

MIT