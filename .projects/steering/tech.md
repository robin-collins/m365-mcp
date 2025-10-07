# Technology Stack

## Core Technologies

### Runtime Environment
- **Python 3.8+** - Primary programming language
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
fastmcp>=0.2.0      # MCP server framework
msal>=1.20.0        # Microsoft authentication
httpx>=0.25.0       # Async HTTP client
python-dotenv>=1.0.0 # Environment variable management
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

# Format code
uvx ruff format .

# Lint code
uvx ruff check --fix --unsafe-fixes .
```

#### Testing
```bash
# Run all tests
uv run pytest tests/ -v

# Run specific test file
uv run pytest tests/test_integration.py -v

# Run with coverage
uv run pytest --cov=src tests/
```

#### Running the Server

**stdio Mode (Default):**
```bash
# Set required environment variables
export MICROSOFT_MCP_CLIENT_ID="your-azure-app-id"

# Run server
uv run microsoft-mcp
```

**HTTP Mode:**
```bash
# Set HTTP transport configuration
export MCP_TRANSPORT="http"
export MCP_HOST="127.0.0.1"
export MCP_PORT="8000"
export MCP_AUTH_METHOD="bearer"
export MCP_AUTH_TOKEN="your-secure-token"

# Run HTTP server
uv run microsoft-mcp
```

#### Authentication
```bash
# Run authentication script
uv run authenticate.py

# Complete authentication flow
uv run python -c "
import asyncio
from src.microsoft_mcp.tools import complete_authentication
result = asyncio.run(complete_authentication('your-flow-cache'))
print(result)
"
```

## API Integration

### Microsoft Graph Endpoints
- **Authentication:** `https://login.microsoftonline.com/`
- **Graph API:** `https://graph.microsoft.com/v1.0/`
- **Scopes:** Mail.ReadWrite, Calendars.ReadWrite, Files.ReadWrite, Contacts.Read

### Transport Modes
1. **stdio** - Standard input/output for desktop applications
2. **HTTP** - Streamable HTTP for web applications and remote access

## Code Organization

### Architecture Patterns
- **MCP Tool Pattern** - All Microsoft 365 operations exposed as MCP tools
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
- **Multi-level caching** - Hot/warm/cold cache layers for different data types
- **TTL-based expiration** - Time-based cache invalidation
- **LRU eviction** - Least recently used cache management

### Large Dataset Handling
- **Pagination** - Efficient handling of large result sets
- **Streaming** - Memory-efficient processing of large files
- **Batch operations** - Optimized bulk operations with rate limiting

## Security Model

### Authentication Flow
1. **Device Code Flow** - User-friendly authentication for installed applications
2. **Token Caching** - Secure local storage of refresh tokens
3. **Scope Management** - Minimal required permissions for security

### Transport Security
- **stdio Mode** - Inherently secure through process isolation
- **HTTP Mode** - Bearer token authentication with configurable security
- **Environment Variables** - Secure configuration management