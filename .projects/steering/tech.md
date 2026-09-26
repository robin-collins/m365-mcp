# Technology Stack

## Core Technologies

### Runtime Environment
- **Python 3.11+** - Primary programming language
- **FastMCP** - MCP server framework for tool registration and transport
- **httpx** - Async HTTP client for Microsoft Graph API communication

### Microsoft Integration
- **Microsoft Authentication Library (MSAL)** - OAuth2 authentication for Microsoft accounts
- **Microsoft Graph API v1.0** - REST API for Microsoft 365 services

### Development Tools
- **uv** - Fast Python package manager and virtual environment tool
- **ruff** - Python linter and formatter (replaces flake8, black, isort)

## Key Dependencies

### Production Dependencies
```python
fastmcp>=4.0.10     # MCP server framework (MCP SDK 2, protocol 2026-07-28)
msal>=1.20.0        # Microsoft authentication
httpx>=0.25.0       # Async HTTP client
python-dotenv>=1.0.0 # Environment variable management
sqlcipher3-wheels==0.5.6 # Encrypted SQLite for cache (AES-256)
keyring>=24.0.0     # Secure key storage (system keyring integration)
```

### Development Dependencies
```python
pytest>=7.0.0       # Testing framework
pytest-asyncio>=0.21.0 # Async testing support
ruff>=0.1.0         # Linting and formatting
pyright>=1.1.300    # Type checking
```

## Build System

### Package Management
- **uv** - Modern Python project manager
- **uv.lock** - Lockfile for reproducible builds
- **pyproject.toml** - Project configuration and dependencies

### Common Commands

#### Development Setup
```bash
# Install dependencies
uv sync

# Install in development mode
uv pip install -e .

# Run type checking
uv run pyright

# Check formatting
uvx ruff format --check .

# Lint code (CI runs this)
uvx ruff check .
```

#### Testing
```bash
# Run all tests (no network; live tests are skipped by default)
uv run pytest tests/ -q

# Run specific test file
uv run pytest tests/test_tool_registry.py -v

# Live read-only tests against a signed-in personal account (opt-in)
M365_MCP_LIVE_TESTS=1 uv run pytest tests/test_integration_unified.py -v

# Run with coverage
uv run pytest --cov=src tests/

# Verify the generated tool specs and tool reference are current
uv run python scripts/build_unified_tool_specs.py --check
uv run python scripts/generate_tools_doc.py --check
```

#### Running the Server

**stdio Mode (Default):**
```bash
# Set required environment variables
export M365_MCP_CLIENT_ID="your-azure-app-id"

# Run server
uv run m365-mcp
```

**Tool exposure:** `M365_MCP_TOOLSETS` (comma separated, default
`core,extended`) selects the tiers: `core` (16 tools), `extended` (7) and
`admin` (6, hidden by default). Unknown values fail at startup.

**HTTP Mode:**
```bash
# Set HTTP transport configuration
export MCP_TRANSPORT="http"
export MCP_HOST="127.0.0.1"
export MCP_PORT="8000"
export MCP_AUTH_METHOD="bearer"
export MCP_AUTH_TOKEN="your-secure-token"

# Run HTTP server
uv run m365-mcp
```

#### Authentication
```bash
# Run authentication script
uv run authenticate.py

# Sign-in is interactive through authenticate.py (device code flow);
# the admin tools account_auth_begin / account_auth_complete do the same
# from an MCP client when M365_MCP_TOOLSETS includes admin.
```

## API Integration

### Microsoft Graph Endpoints
- **Authentication:** `https://login.microsoftonline.com/`
- **Graph API:** `https://graph.microsoft.com/v1.0/`
- **Scopes:** the server requests `.default`; the app registration must grant
  Mail.ReadWrite, Mail.Send, Calendars.ReadWrite, Files.ReadWrite,
  Contacts.ReadWrite, MailboxSettings.Read and User.Read
- **Accounts:** personal Microsoft accounts only (outlook.com, hotmail.com,
  live.com). The default authority is `consumers` (`M365_MCP_TENANT_ID`);
  work and school accounts are rejected at sign-in completion

### Transport Modes
1. **stdio** - Standard input/output for desktop applications
2. **HTTP** - Streamable HTTP for web applications and remote access

## Code Organization

### Architecture Patterns
- **MCP Tool Pattern** - All Microsoft 365 operations exposed as MCP tools
- **Modular Tool Package** - Tool implementations live under `src/m365_mcp/tools/`
  and are registered by `tools/registry.py` (`build_server()`) from the
  packaged tool specs
- **Authentication Proxy** - Centralized token management and refresh
- **Graph API Client** - Unified HTTP client with retry logic and rate limiting
- **Multi-account Support** - Account isolation and context management

### Error Handling
- **HTTP Status Codes** - Proper handling of Microsoft Graph API responses
- **Rate Limiting** - Intelligent backoff for API quota management
- **Token Refresh** - Automatic token renewal on expiration
- **Partial Failures** - Graceful degradation for batch operations

## Performance Considerations

### Caching Strategy
- **Encrypted SQLite Cache** - AES-256 encryption via SQLCipher for data at rest
- **Three-State TTL** - Fresh, Stale and Expired lifecycle with per-resource
  lifetimes (`cache_config.RESOURCE_TTL_POLICIES`, for example `email` fresh
  2 min and expired after 10 min)
- **Automatic Compression** - Gzip compression for entries ≥50KB (70-80% size reduction)
- **Smart Invalidation** - Mutating tools invalidate the affected resources for that account
- **Connection Pooling** - Pool of 5 SQLite connections for concurrent access
- **Automatic Cleanup** - Triggers at 80% of 2GB limit, reduces to 60% target
- **Cache Warming** - Background pre-population and stale-cache refresh are
  wired behind `M365_MCP_CACHE_WARMING=true`; default startup leaves the worker
  inactive
- **Scope** - Only `m365_list` and `m365_get` results are cached; the only
  model-facing control is `refresh`
- **Encryption Key Management** - System keyring integration with environment
  fallback and explicit warnings for non-persistent generated keys

### Large Dataset Handling
- **Pagination** - Efficient handling of large result sets
- **Streaming** - Memory-efficient processing of large files
- **Batch operations** - Optimized bulk operations with rate limiting

## Security Model

### Authentication Flow
1. **Device Code Flow** - User-friendly authentication for installed applications through `authenticate.py` or `M365_MCP_INTERACTIVE_AUTH=true`
2. **Silent Token Use** - Normal MCP requests fail fast with an actionable error if no cached token is available
3. **Token Caching** - Secure local storage of refresh tokens
4. **Scope Management** - Minimal required permissions for security

### Transport Security
- **stdio Mode** - Inherently secure through process isolation
- **HTTP Mode** - Bearer token authentication with configurable security
- **Environment Variables** - Secure configuration management

### Data Security
- **Cache Encryption** - AES-256 encryption for cached data via SQLCipher by default; startup fails if SQLCipher is unavailable while encryption is enabled
- **Key Storage** - Secure keyring integration (macOS Keychain, Windows Credential Manager, Linux Secret Service)
- **Key Fallback** - Environment variable `M365_MCP_CACHE_KEY` for headless servers; generated ephemeral keys are warned and not durable
- **Compliance** - Encryption, TTL, and account isolation controls for GDPR/HIPAA-aligned deployments
