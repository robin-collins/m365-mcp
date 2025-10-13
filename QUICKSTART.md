# Quick Start Guide

Get M365 MCP server up and running in 5 minutes.

---

## Prerequisites

- **Python 3.12+** installed
- **uv** package manager ([install instructions](https://docs.astral.sh/uv/))
- **Microsoft Azure App Registration** with client ID (see [Azure Setup](#azure-setup-optional))

---

## Installation

### 1. Clone Repository

```bash
git clone https://github.com/robin-collins/m365-mcp.git
cd m365-mcp
```

### 2. Install Dependencies

```bash
uv sync
```

This installs:
- `fastmcp` - MCP server framework
- `msal` - Microsoft authentication
- `httpx` - HTTP client
- `fastapi` - Streamable HTTP transport (if needed)
- `uvicorn` - Streamable HTTP server (if needed)

---

## Configuration

### Required Environment Variables

```bash
# Your Azure app registration client ID
export M365_MCP_CLIENT_ID="abc123-def456-ghi789"
```

### Optional Environment Variables (Streamable HTTP Mode)

```bash
# Transport mode (default: stdio)
export MCP_TRANSPORT="http"              # or "stdio"

# Streamable HTTP server configuration
export MCP_HOST="127.0.0.1"             # Default: localhost
export MCP_PORT="8000"                  # Default: 8000

# Authentication (required for SSE)
export MCP_AUTH_METHOD="bearer"         # or "oauth" or "none"
export MCP_AUTH_TOKEN="your-token"      # Required if bearer auth
```

**💡 Tip:** Use the provided `.env.example` template:

```bash
# Copy example file and edit with your values
cp .env.example .env

# Edit .env with your client ID
# The file contains detailed comments for all configuration options
```

The server automatically loads `.env` files.

---

## Authentication

### First-Time Setup

Before using the server, authenticate your Microsoft account:

```bash
# Run authentication script
uv run authenticate.py
```

**Follow the prompts:**
1. Visit the URL shown (e.g., https://microsoft.com/devicelogin)
2. Enter the device code displayed
3. Sign in with your Microsoft account
4. Grant permissions

**Authentication is saved** to `~/.m365_mcp_token_cache.json` and persists across sessions.

### Multi-Account Support

To add additional accounts:

```bash
# Run authentication again
uv run authenticate.py

# Choose "Add new account" when prompted
```

---

## Running the Server

### stdio Mode (Default - For Desktop Apps)

**Use for:** Claude Desktop, local MCP clients

```bash
export M365_MCP_CLIENT_ID="your-app-id"
uv run m365-mcp
```

**No additional setup required** - stdio is secure by default through process isolation.

### Streamable HTTP Mode (For Web/API Access)

**Use for:** Web applications, remote access, multi-client scenarios

#### Step 1: Generate Secure Token

```bash
export MCP_AUTH_TOKEN=$(openssl rand -hex 32)
echo "Save this token: $MCP_AUTH_TOKEN"
```

#### Step 2: Configure Streamable HTTP Transport

```bash
export M365_MCP_CLIENT_ID="your-app-id"
export MCP_TRANSPORT="http"
export MCP_AUTH_METHOD="bearer"
export MCP_HOST="127.0.0.1"
export MCP_PORT="8000"
```

#### Step 3: Start Server

```bash
uv run m365-mcp
```

**Expected output:**
```
Starting MCP server with Streamable HTTP transport on 127.0.0.1:8000
✅ Bearer token authentication enabled
✅ Health check available at http://127.0.0.1:8000/health
INFO:     Uvicorn running on http://127.0.0.1:8000
```

#### Step 4: Verify Server

```bash
# Test health check (no auth required)
curl http://localhost:8000/health

# Response:
# {"status": "ok", "transport": "sse", "auth": "bearer"}
```

---

## Claude Desktop Integration

### Configuration File Location

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
**Linux:** `~/.config/Claude/claude_desktop_config.json`

### Option 1: Install from GitHub

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

### Option 2: Local Development

```json
{
  "mcpServers": {
    "microsoft": {
      "command": "uv",
      "args": ["--directory", "/path/to/m365-mcp", "run", "m365-mcp"],
      "env": {
        "M365_MCP_CLIENT_ID": "your-app-id-here"
      }
    }
  }
}
```

**Replace `/path/to/m365-mcp`** with your actual project path.

### Restart Claude Desktop

After updating the config:
1. Quit Claude Desktop completely
2. Restart Claude Desktop
3. Server will start automatically when Claude loads

---

## Quick Testing

### Test 1: List Accounts

```python
# In Claude Desktop, ask:
"List my Microsoft accounts"

# Or use MCP client:
result = await session.call_tool("list_accounts", {})
```

### Test 2: List Emails

```python
# In Claude Desktop:
"Show me my latest 5 emails"

# Or use MCP client:
accounts = await session.call_tool("list_accounts", {})
account_id = accounts[0]["account_id"]

emails = await session.call_tool("list_emails", {
    "account_id": account_id,
    "limit": 5,
    "include_body": False
})
```

### Test 3: List OneDrive Files

```python
# In Claude Desktop:
"List files in my OneDrive root folder"

# Or use MCP client:
files = await session.call_tool("list_files", {
    "account_id": account_id,
    "path": "/",
    "limit": 10
})
```

---

## Common Issues & Solutions

### Issue 1: "M365_MCP_CLIENT_ID environment variable is required"

**Cause:** Environment variable not set

**Solution:**
```bash
export M365_MCP_CLIENT_ID="your-app-id"
```

Or add to `.env` file in project root.

---

### Issue 2: "No accounts found - please authenticate first"

**Cause:** No authenticated Microsoft accounts

**Solution:**
```bash
uv run authenticate.py
```

Follow authentication prompts to sign in.

---

### Issue 3: "Refusing to start insecure Streamable HTTP server"

**Cause:** Streamable HTTP mode requires authentication

**Solution:**
```bash
# Option 1: Add bearer token (recommended)
export MCP_AUTH_METHOD="bearer"
export MCP_AUTH_TOKEN=$(openssl rand -hex 32)

# Option 2: Allow insecure mode (NOT RECOMMENDED)
export MCP_ALLOW_INSECURE="true"
```

---

### Issue 4: Token expired or authentication failed

**Cause:** Token cache corrupted or expired

**Solution:**
```bash
# Remove token cache
rm ~/.m365_mcp_token_cache.json

# Re-authenticate
uv run authenticate.py
```

---

### Issue 5: Claude Desktop doesn't see the server

**Cause:** Configuration file syntax error or wrong path

**Solution:**
1. Validate JSON syntax (use https://jsonlint.com/)
2. Check file path in config matches your installation
3. Check Claude Desktop logs:
   - macOS: `~/Library/Logs/Claude/mcp*.log`
   - Windows: `%APPDATA%\Claude\logs\mcp*.log`
4. Restart Claude Desktop completely (quit, then reopen)

---

## Environment Variables Reference

### Required

| Variable | Description | Example |
|----------|-------------|---------|
| `M365_MCP_CLIENT_ID` | Azure app client ID | `abc123-def456-...` |

### Optional (Transport)

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_TRANSPORT` | `stdio` | `stdio` or `sse` |
| `MCP_HOST` | `127.0.0.1` | Streamable HTTP server bind address |
| `MCP_PORT` | `8000` | Streamable HTTP server port |

### Optional (SSE Authentication)

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_AUTH_METHOD` | `none` | `bearer`, `oauth`, or `none` |
| `MCP_AUTH_TOKEN` | - | Bearer token (required if bearer auth) |
| `MCP_ALLOW_INSECURE` | `false` | Allow SSE without auth (DANGEROUS) |

### Optional (Microsoft)

| Variable | Default | Description |
|----------|---------|-------------|
| `M365_MCP_TENANT_ID` | `common` | Azure tenant ID |

---

## File Locations

### Token Cache

**Location:** `~/.m365_mcp_token_cache.json`

Contains MSAL token cache for authenticated accounts. Delete to force re-authentication.

### Environment File

**Location:** `.env` in project root

**Setup:**
```bash
# Copy the example file
cp .env.example .env

# Edit with your values
nano .env  # or use your preferred editor
```

The `.env.example` file contains:
- All available configuration options
- Detailed comments for each variable
- Example configurations for different use cases
- Security best practices

### Claude Desktop Config

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
**Linux:** `~/.config/Claude/claude_desktop_config.json`

---

## Next Steps

### Explore Tools

The server provides 50 MCP tools across 5 categories:

- **Email** (20 tools) - Read, send, manage folders, rules
- **Calendar** (7 tools) - Events, availability
- **OneDrive** (9 tools) - Files, folders
- **Contacts** (6 tools) - Search, manage contacts
- **Search** (4 tools) - Unified search across email/files
- **Account** (3 tools) - Multi-account management

**See `README.md`** for complete tool list and usage examples.

### Security Considerations

**stdio mode:** Secure by default (process isolation)

**Streamable HTTP mode:** Requires authentication
- **Bearer token** (recommended) - Simple, secure
- **OAuth** (enterprise) - Browser-based flow
- **Insecure** (testing only) - Requires explicit opt-in

**📚 See `SECURITY.md`** for complete security guide.

### Advanced Configuration

- **SSH Tunneling** - Remote access without exposing Streamable HTTP server
- **Reverse Proxy** - Add TLS/HTTPS with nginx or Caddy
- **Multiple Accounts** - Work and personal accounts simultaneously
- **Message Rules** - Automated email filtering and organization

**📖 See `README.md` and `SECURITY.md`** for advanced topics.

---

## Quick Reference: Complete Setup

### Minimal Setup (stdio mode)

```bash
# 1. Clone and install
git clone https://github.com/robin-collins/m365-mcp.git
cd m365-mcp
uv sync

# 2. Set environment
export M365_MCP_CLIENT_ID="your-app-id"

# 3. Authenticate
uv run authenticate.py

# 4. Run server
uv run m365-mcp
```

### Complete Setup (Streamable HTTP mode)

```bash
# 1. Clone and install
git clone https://github.com/robin-collins/m365-mcp.git
cd m365-mcp
uv sync

# 2. Create .env file
cat > .env << EOF
M365_MCP_CLIENT_ID=your-app-id-here
MCP_TRANSPORT=http
MCP_AUTH_METHOD=bearer
MCP_AUTH_TOKEN=$(openssl rand -hex 32)
MCP_HOST=127.0.0.1
MCP_PORT=8000
EOF

# 3. Authenticate
uv run authenticate.py

# 4. Run server
uv run m365-mcp

# 5. Test health check
curl http://localhost:8000/health
```

### Claude Desktop Setup

```bash
# 1. Find config file location
# macOS:
CONFIG_FILE="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
# Windows:
# CONFIG_FILE="%APPDATA%\Claude\claude_desktop_config.json"
# Linux:
# CONFIG_FILE="~/.config/Claude/claude_desktop_config.json"

# 2. Edit config (or create if missing)
cat > "$CONFIG_FILE" << 'EOF'
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
EOF

# 3. Restart Claude Desktop
```

---

## Development & Testing

### Run Tests

```bash
# Run integration tests (requires authenticated account)
uv run pytest tests/ -v
```

### Code Quality

```bash
# Type checking
uv run pyright

# Format code
uvx ruff format .

# Lint and auto-fix
uvx ruff check --fix .
```

### Debug Mode

```bash
# Increase logging verbosity
export LOG_LEVEL=DEBUG
uv run m365-mcp
```

---

## Getting Help

### Documentation

- **README.md** - Complete project overview and tool reference
- **SECURITY.md** - Security guide for transport modes and auth
- **CHANGELOG.md** - Version history and changes
- **EMAIL_OUTPUT_FORMAT.md** - Email reading output format guide

### Troubleshooting

1. Check environment variables: `env | grep MCP`
2. Check token cache: `ls -lh ~/.m365_mcp_token_cache.json`
3. Check Claude Desktop logs (see Issue 5 above)
4. Verify Azure app permissions (see Azure Setup below)

### Support

- **GitHub Issues:** https://github.com/robin-collins/m365-mcp/issues
- **MCP Documentation:** https://modelcontextprotocol.io/

---

## Azure Setup (Optional)

If you don't have an Azure app registration yet:

### 1. Create App Registration

1. Go to [Azure Portal](https://portal.azure.com)
2. Navigate to **Microsoft Entra ID** → **App registrations**
3. Click **New registration**
4. Name: `m365-mcp`
5. Supported account types: **Personal + Work/School**
6. Click **Register**

### 2. Enable Device Flow

1. Go to **Authentication**
2. Scroll to **Advanced settings**
3. Enable **Allow public client flows**: **Yes**
4. Click **Save**

### 3. Add API Permissions

1. Go to **API permissions**
2. Click **Add a permission**
3. Select **Microsoft Graph** → **Delegated permissions**
4. Add these permissions:
   - `Mail.ReadWrite`
   - `Calendars.ReadWrite`
   - `Files.ReadWrite`
   - `Contacts.Read`
   - `People.Read`
   - `User.Read`
   - `MailboxSettings.ReadWrite` (for message rules)
5. Click **Add permissions**
6. Click **Grant admin consent** (if required)

### 4. Copy Client ID

1. Go to **Overview**
2. Copy **Application (client) ID**
3. Use this as `M365_MCP_CLIENT_ID`

**Example:**
```bash
export M365_MCP_CLIENT_ID="12345678-1234-1234-1234-123456789abc"
```

---

## Summary

**Quickest path to running:**

```bash
# 1. Install
git clone https://github.com/robin-collins/m365-mcp.git
cd m365-mcp && uv sync

# 2. Configure
export M365_MCP_CLIENT_ID="your-app-id"

# 3. Authenticate
uv run authenticate.py

# 4. Run (stdio mode)
uv run m365-mcp

# Or for Streamable HTTP mode with auth:
export MCP_AUTH_TOKEN=$(openssl rand -hex 32)
export MCP_TRANSPORT=http
export MCP_AUTH_METHOD=bearer
uv run m365-mcp
```

**That's it!** 🎉

For Claude Desktop, add the server to your config file and restart Claude.

---

**Document Version:** 1.0
**Last Updated:** 2025-10-05
**Maintainer:** m365-mcp contributors
