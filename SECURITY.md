# Security Guide

**Last Updated:** 2025-10-05

---

## Transport Security Overview

Microsoft MCP supports two transport modes with different security characteristics:

| Transport | Security Model | Authentication | Use Case |
|-----------|---------------|----------------|----------|
| **stdio** | Process isolation | Not required | Local desktop apps (Claude Desktop) |
| **SSE** | Network-based | **Required** | Web apps, remote access, multi-client |

---

## 🔒 stdio Transport (Default)

### Security Characteristics

✅ **Inherently Secure** - No additional authentication needed because:
- **Process Isolation** - Only the spawning process can communicate via stdin/stdout
- **Local-Only** - No network exposure
- **OS Permissions** - Protected by operating system access controls

### Configuration

```bash
# Default mode - no MCP_TRANSPORT variable needed
export MICROSOFT_MCP_CLIENT_ID="your-app-id"
uv run microsoft-mcp
```

### Usage with Claude Desktop

```json
{
  "mcpServers": {
    "microsoft-mcp": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/robin-collins/m365-mcp.git", "microsoft-mcp"],
      "env": {
        "MICROSOFT_MCP_CLIENT_ID": "your-app-id-here"
      }
    }
  }
}
```

---

## 🌐 Streamable HTTP Transport

### ⚠️ Critical Security Requirements

**Streamable HTTP mode exposes your Microsoft account over HTTP.** Without authentication:
- ❌ Anyone who can reach the server can read all your emails
- ❌ Anyone can send emails as you
- ❌ Anyone can access your OneDrive files
- ❌ Anyone can manage your calendar
- ❌ Full access to all 50 MCP tools

**The server REQUIRES authentication and will refuse to start in insecure mode unless explicitly overridden.**

---

## 🛡️ Authentication Methods

### Method 1: Bearer Token (Recommended for most use cases)

Simple and secure token-based authentication.

#### Setup

```bash
# 1. Generate a secure token
export MCP_AUTH_TOKEN=$(openssl rand -hex 32)

# 2. Configure SSE with bearer auth
export MICROSOFT_MCP_CLIENT_ID="your-app-id"
export MCP_TRANSPORT="http"
export MCP_AUTH_METHOD="bearer"
export MCP_HOST="127.0.0.1"  # localhost only
export MCP_PORT="8000"

# 3. Start server
uv run microsoft-mcp
```

#### Server Output

```
Starting MCP server with Streamable HTTP transport on 127.0.0.1:8000
✅ Bearer token authentication enabled
✅ Health check available at http://127.0.0.1:8000/health
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000
```

#### Client Usage

```python
from mcp.client.http import http_client

async with http_client(
    "http://localhost:8000/mcp",
    headers={"Authorization": f"Bearer {your_token}"}
) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        # Use the session...
```

#### Security Features

- ✅ Minimum token length validation (32 characters)
- ✅ Constant-time token comparison (prevents timing attacks)
- ✅ Health check endpoint (no auth required)
- ✅ Proper HTTP 401 responses with WWW-Authenticate headers
- ✅ Token never logged or exposed

#### Token Storage

```bash
# Store in .env file (add to .gitignore!)
echo "MCP_AUTH_TOKEN=$(openssl rand -hex 32)" >> .env

# Or use a secrets manager
export MCP_AUTH_TOKEN=$(aws secretsmanager get-secret-value --secret-id mcp-token --query SecretString --output text)
```

---

### Method 2: OAuth (FastMCP 2.0+)

Enterprise-grade OAuth 2.0 authentication with automatic browser flow.

#### Setup

```bash
export MICROSOFT_MCP_CLIENT_ID="your-app-id"
export MCP_TRANSPORT="http"
export MCP_AUTH_METHOD="oauth"
export MCP_HOST="127.0.0.1"
export MCP_PORT="8000"

uv run microsoft-mcp
```

#### Features

- ✅ Browser-based OAuth flow
- ✅ Token refresh handling
- ✅ Persistent storage
- ✅ Enterprise SSO support (WorkOS, Azure AD, Auth0)

---

### Method 3: Insecure Mode (NOT RECOMMENDED)

**⚠️ DANGER: Only use for local development on isolated networks**

```bash
export MICROSOFT_MCP_CLIENT_ID="your-app-id"
export MCP_TRANSPORT="http"
export MCP_ALLOW_INSECURE="true"  # Required to bypass security check
export MCP_HOST="127.0.0.1"
export MCP_PORT="8000"

uv run microsoft-mcp
```

#### Server Output

```
⚠️  WARNING: Running Streamable HTTP server without authentication!
⚠️  Anyone who can reach this server will have full access to your Microsoft account!
⚠️  Set MCP_AUTH_METHOD=bearer and MCP_AUTH_TOKEN=<token> to enable auth
Starting MCP server with Streamable HTTP transport on 127.0.0.1:8000
```

**Use cases:**
- ✅ Local development on isolated machine
- ✅ Testing in Docker container without network exposure
- ❌ **NEVER use in production**
- ❌ **NEVER use on shared networks**
- ❌ **NEVER expose to internet**

---

## 🔐 Environment Variables Reference

### Required (All Modes)

| Variable | Description | Example |
|----------|-------------|---------|
| `MICROSOFT_MCP_CLIENT_ID` | Azure app registration ID | `abc123-def456-...` |

### Transport Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_TRANSPORT` | `stdio` | Transport mode: `stdio` or `sse` |
| `MCP_HOST` | `127.0.0.1` | Streamable HTTP server bind address |
| `MCP_PORT` | `8000` | Streamable HTTP server port |

### Authentication (Streamable HTTP Mode)

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_AUTH_METHOD` | `none` | Auth method: `bearer`, `oauth`, or `none` |
| `MCP_AUTH_TOKEN` | - | Bearer token (required if `MCP_AUTH_METHOD=bearer`) |
| `MCP_ALLOW_INSECURE` | `false` | Allow SSE without auth (DANGEROUS) |

---

## 🌍 Network Security

### Binding Addresses

```bash
# Localhost only (most secure)
export MCP_HOST="127.0.0.1"

# All interfaces (requires auth + firewall)
export MCP_HOST="0.0.0.0"
⚠️  WARNING: Binding to all network interfaces. Ensure firewall is configured!
```

### Firewall Rules

If binding to `0.0.0.0`, configure your firewall:

```bash
# Ubuntu/Debian - Allow only specific IP
sudo ufw allow from 192.168.1.100 to any port 8000

# RedHat/CentOS
sudo firewall-cmd --add-rich-rule='rule family="ipv4" source address="192.168.1.100" port protocol="tcp" port="8000" accept'

# Docker - don't expose port to host
docker run --network none ...  # No network access
```

### SSH Tunneling (Recommended for Remote Access)

Instead of exposing Streamable HTTP server to network, use SSH tunnel:

```bash
# On remote server
export MCP_HOST="127.0.0.1"
export MCP_AUTH_METHOD="bearer"
uv run microsoft-mcp

# On local machine
ssh -L 8000:localhost:8000 user@remote-server

# Connect to http://localhost:8000 (tunnels to remote)
```

---

## 🔍 Health Check Endpoint

The Streamable HTTP server provides a health check endpoint (no authentication required):

```bash
# Check server status
curl http://localhost:8000/health

# Response
{
  "status": "ok",
  "transport": "sse",
  "auth": "bearer"
}
```

**Use cases:**
- Load balancer health checks
- Monitoring systems
- Startup verification

---

## 🚨 Security Best Practices

### Token Management

1. **Generate Strong Tokens**
   ```bash
   # Minimum 32 characters (64 hex digits)
   openssl rand -hex 32

   # Or use UUID
   python3 -c "import uuid; print(uuid.uuid4())"
   ```

2. **Never Commit Tokens**
   ```bash
   # Add to .gitignore
   echo ".env" >> .gitignore
   echo "*.token" >> .gitignore
   ```

3. **Rotate Tokens Regularly**
   ```bash
   # Generate new token
   NEW_TOKEN=$(openssl rand -hex 32)

   # Update environment
   export MCP_AUTH_TOKEN="$NEW_TOKEN"

   # Restart server
   ```

4. **Use Secrets Managers**
   ```bash
   # AWS Secrets Manager
   export MCP_AUTH_TOKEN=$(aws secretsmanager get-secret-value \
     --secret-id microsoft-mcp-token \
     --query SecretString --output text)

   # HashiCorp Vault
   export MCP_AUTH_TOKEN=$(vault kv get -field=token secret/mcp)
   ```

### Network Security

1. **Prefer Localhost**
   - Bind to `127.0.0.1` unless remote access is required
   - Use SSH tunneling for remote access instead of `0.0.0.0`

2. **Use TLS/HTTPS**
   - Streamable HTTP server currently uses HTTP
   - Put behind reverse proxy (nginx, Caddy) with TLS:
   ```nginx
   server {
       listen 443 ssl;
       server_name mcp.example.com;

       ssl_certificate /path/to/cert.pem;
       ssl_certificate_key /path/to/key.pem;

       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Authorization $http_authorization;
       }
   }
   ```

3. **Rate Limiting**
   - Implement rate limiting to prevent brute force attacks
   - Use nginx/Caddy rate limits or application-level throttling

### Microsoft Account Security

1. **Use Dedicated Azure App**
   - Don't reuse app registrations
   - Create separate app for MCP server

2. **Minimal Permissions**
   - Only grant required Graph API permissions
   - Review permissions regularly

3. **Monitor Access**
   - Check Azure AD sign-in logs
   - Review token cache regularly
   - Revoke tokens if compromised

---

## 🔧 Troubleshooting

### Server Won't Start (Streamable HTTP Mode)

**Error:** `Error: Refusing to start insecure Streamable HTTP server`

**Cause:** No authentication configured

**Solution:**
```bash
export MCP_AUTH_METHOD="bearer"
export MCP_AUTH_TOKEN=$(openssl rand -hex 32)
```

---

**Error:** `Error: MCP_AUTH_TOKEN required when MCP_AUTH_METHOD=bearer`

**Cause:** Bearer auth selected but no token provided

**Solution:**
```bash
export MCP_AUTH_TOKEN=$(openssl rand -hex 32)
```

---

**Error:** `⚠️  WARNING: MCP_AUTH_TOKEN is too short`

**Cause:** Token less than 32 characters

**Solution:**
```bash
export MCP_AUTH_TOKEN=$(openssl rand -hex 32)  # 64 chars
```

---

### Client Connection Fails

**Error:** `401 Unauthorized`

**Cause:** Missing or invalid bearer token

**Solution:**
```python
# Ensure Authorization header is present
headers = {"Authorization": f"Bearer {your_token}"}
async with http_client(url, headers=headers) as (read, write):
    ...
```

---

**Error:** `Invalid Authorization header format`

**Cause:** Missing "Bearer " prefix

**Solution:**
```python
# Correct
headers = {"Authorization": "Bearer abc123..."}

# Incorrect
headers = {"Authorization": "abc123..."}
```

---

## 📊 Security Comparison Matrix

| Feature | stdio | SSE + bearer | SSE + OAuth | SSE insecure |
|---------|-------|--------------|-------------|--------------|
| **Network exposure** | None | HTTP | HTTP | HTTP |
| **Authentication** | Process isolation | Token-based | OAuth 2.0 | None ❌ |
| **Multi-client** | No | Yes | Yes | Yes |
| **Setup complexity** | Low | Medium | High | Low |
| **Security level** | High | High | Very High | **CRITICAL RISK** |
| **Use case** | Desktop apps | Internal tools | Enterprise | **Never use** |

---

## 🆘 Security Incident Response

### If Token is Compromised

1. **Immediately generate new token:**
   ```bash
   export MCP_AUTH_TOKEN=$(openssl rand -hex 32)
   ```

2. **Restart server**

3. **Update all clients with new token**

4. **Review access logs for unauthorized access**

### If Server is Exposed Without Auth

1. **Immediately stop server:**
   ```bash
   pkill -f microsoft-mcp
   ```

2. **Revoke Microsoft tokens:**
   ```bash
   rm ~/.microsoft_mcp_token_cache.json
   ```

3. **Review Microsoft account activity:**
   - Check Azure AD sign-in logs
   - Review recent emails sent
   - Check OneDrive access logs

4. **Change Microsoft account password** (if suspicious activity detected)

5. **Restart with proper authentication**

---

## 📚 Additional Resources

- [FastMCP Authentication Docs](https://github.com/jlowin/fastmcp)
- [Microsoft Graph Security Best Practices](https://docs.microsoft.com/graph/security-authorization)
- [MCP Protocol Specification](https://modelcontextprotocol.io/)

---

**Document Version:** 1.0
**Last Updated:** 2025-10-05
**Maintainer:** microsoft-mcp contributors
