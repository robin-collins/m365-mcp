# Project Structure

## Overview

M365 MCP Server follows a modular architecture with clear separation of concerns. The project is organized into logical layers that support easy maintenance, testing, and extension.

## Core Architecture

```
m365-mcp/
├── src/m365_mcp/              # Main package
│   ├── auth.py                # MSAL auth, personal accounts only (authority consumers)
│   ├── auth_sessions.py       # Server-side device-flow sessions (opaque auth_session_id)
│   ├── graph.py               # Graph client: retries, 401 refresh, deadlines, $batch
│   ├── errors.py              # GraphAPIError and mapping to actionable ToolError text
│   ├── server.py              # Entry point, stdio and HTTP transports
│   ├── http_security.py       # Origin allowlist and constant-time bearer check
│   ├── tool_specs/            # Packaged spec JSON (generated; do not edit)
│   ├── tools/
│   │   ├── registry.py        # Builds the server from tool_specs; validation,
│   │   │                      # output contract, caching, error translation
│   │   ├── handlers.py        # Handler and validation-rule registries
│   │   └── unified/           # Handlers by domain (mail, calendar, drive, ...)
│   ├── services/              # Graph logic (URLs, params, paging); no FastMCP
│   ├── projections.py         # Graph JSON -> spec result records
│   ├── untrusted.py           # Sanitising of third-party text
│   ├── cursors.py             # Opaque, HMAC-protected pagination cursors
│   ├── resource_cache.py      # Cache keyed by account, resource and arguments
│   ├── local_files.py         # Allowed roots, deny-list, safe file names
│   ├── rate_limit.py          # Per-account token buckets
│   ├── operations.py          # Async copy operation store
│   ├── reauth_schedule.py     # Weekly re-auth job: Task Scheduler / cron install, checks
│   ├── reauth_job.py          # The scheduled job: refresh every signed-in account
│   ├── observability.py       # Per-call JSON audit log middleware
│   ├── cache.py               # Encrypted SQLite cache manager (AES-256)
│   ├── cache_config.py        # TTL policies, cache configuration
│   ├── cache_warming.py       # Optional startup warming
│   ├── background_worker.py   # Async task queue for cache operations
│   ├── encryption.py          # Cache key management (keyring integration)
│   └── validators.py          # Shared validation helpers and error format
├── docs/unified-tools/        # Tool specification (source of truth, generated)
├── scripts/                   # Spec builder and tool reference generator
├── evals/                     # Golden-prompt evaluation harness and fake Graph
├── tests/                     # Unit, conformance and (opt-in) live tests
├── .projects/steering/        # AI assistant guidance
└── docs/                      # Documentation
```

## Layer Responsibilities

### Authentication Layer (`auth.py`)
- **MSAL integration** - Microsoft Authentication Library setup
- **Token management** - Refresh token storage and renewal
- **Multi-account support** - Account discovery and isolation
- **Device flow authentication** - User-friendly auth process

### API Client Layer (`graph.py`)
- **HTTP client setup** - Configured httpx client with timeouts
- **Request/response handling** - Unified Graph API communication
- **Pagination support** - Efficient handling of large datasets
- **Rate limiting** - Intelligent backoff and retry logic
- **File upload** - Large file handling with chunked upload

### Tool Layer (`tools/` package)
- **Spec-driven registration** - `tools/registry.py` registers each enabled
  tool from its packaged spec JSON (exact name, description, annotations,
  input and output schemas) in `index.json` order, filtered by
  `M365_MCP_TOOLSETS`
- **Pipeline** - JSON Schema validation, semantic rules, handler, output
  contract, caching and error translation happen in the registry
- **Handlers** - `tools/unified/` modules register handlers; the eight
  `m365_*` tools dispatch on `resource` to per-resource functions
- **No Graph URLs** - handlers call services; they never build URLs

### Services Layer (`services/` package)
- **Graph logic** - endpoints, query parameters, paging, request bodies
- **No FastMCP** - enforced by `tests/test_services_boundaries.py`

### Server Layer (`server.py`)
- **Transport modes** - stdio (default) and HTTP support
- **Security configuration** - Authentication middleware for HTTP
- **Health checks** - Monitoring and diagnostics endpoints
- **Environment management** - Configuration loading and validation

### Cache Layer (`cache.py`, `cache_config.py`, `encryption.py`)
- **Encrypted storage** - AES-256 encryption via SQLCipher for data at rest
- **TTL management** - Three-state cache lifecycle (Fresh/Stale/Expired)
- **Compression** - Automatic gzip compression for entries ≥50KB
- **Invalidation** - Pattern-based cache invalidation on write operations
- **Connection pooling** - Pool of 5 connections for concurrent access
- **Key management** - Secure keyring integration with environment fallback
- **Size management** - Automatic cleanup at 80% of 2GB limit

### Background Processing (`background_worker.py`, `cache_warming.py`)
- **Async task queue** - Priority-based task scheduling and execution
- **Cache warming** - Startup warming and stale-cache refresh are wired behind
  `M365_MCP_CACHE_WARMING=true` and are disabled by default
- **Retry logic** - Automatic retry with exponential backoff for failed tasks
- **Status tracking** - Real-time task status and completion monitoring

## Key Design Patterns

### MCP Tool Pattern
All Microsoft 365 operations are exposed as stateless MCP tools with:
- **Spec-defined surface** - 30 tools defined in `docs/unified-tools/`;
  optional `account_id` on every Microsoft 365 tool
- **Typed results** - `outputSchema`, `structuredContent` and a `summary`
- **Actionable errors** - Graph errors mapped to fix-it text; no URLs
- **Explicit handles** - cursors, auth sessions and copy operations

### Graph API Client Pattern
Centralized API communication with:
- **Unified error handling** - Consistent HTTP error management
- **Automatic retries** - Exponential backoff for transient failures
- **Response parsing** - JSON response processing
- **Authentication** - Automatic token injection

### Multi-Account Pattern
Account isolation and management:
- **Account context** - Per-operation account specification
- **Token isolation** - Separate tokens per account
- **Resource scoping** - Account-specific API calls

## Development Organization

### Testing Structure
```
tests/
├── conftest.py, unified_harness.py, parity_helpers.py   # Shared fixtures and mocked Graph harness
├── fixtures/graph/            # Recorded Graph response fixtures
├── test_unified_*.py          # Handler tests per domain (mail, calendar, drive, ...)
├── test_services_*.py         # Services layer tests
├── test_parity.py             # Legacy-to-unified mapping rows
├── test_tool_registry.py      # Live tools/list equals the specs
├── test_unified_tool_specs.py # Spec validation
├── test_sdk_client_conformance.py  # MCP client SDK against the server
├── test_evals_harness.py      # evals/ harness
├── test_graph_*.py, test_cursors.py, test_local_files.py, ...  # One file per module
├── test_cache*.py, test_encryption.py, ...  # Cache layer
└── test_integration_unified.py  # Live read-only tests (M365_MCP_LIVE_TESTS=1)
```

### Documentation Structure
```
*.md                           # Root documentation files
docs/                          # Detailed documentation (future)
reports/                       # Generated analysis and reports
```

### Build and Configuration
```
pyproject.toml                 # Project configuration
uv.lock                        # Dependency lock file
.env.example                   # Environment template
```

## File Organization Guidelines

### Adding New Tools
1. **Spec** - Add the tool to `scripts/build_unified_tool_specs.py`
   (description, schemas, validation rules, Graph calls, examples), run the
   builder, and pass `tests/test_unified_tool_specs.py`
2. **Services** - Add the Graph calls to the matching `services/` module
3. **Handler** - Register it in a `tools/unified/` module with
   `@register_handler` (or `@resource_op` for a generic tool resource)
4. **Tests** - One test per validation rule (exact text), the confirm gate,
   the Graph calls, and each spec example, using the `harness` fixture
5. **Breaking changes** - Only in a major version, listed in `CHANGELOG.md`

### Adding New Modules
1. **Location** - Create in `src/m365_mcp/`
2. **Integration** - Import in `__init__.py`
3. **Dependencies** - Minimize cross-module dependencies
4. **Testing** - Include corresponding test file

### Configuration Changes
1. **Environment variables** - Document in `.env.example`
2. **Server configuration** - Modify `server.py` transport logic
3. **Authentication** - Update `auth.py` scopes and flows

## Code Style Conventions

### Python Standards
- **Formatting** - Use `ruff format` for consistent formatting
- **Linting** - Use `ruff check` for code quality
- **Types** - Full type annotations required
- **Imports** - Group standard library, third-party, then local imports

### Documentation Standards
- **Docstrings** - Google style docstrings for all public functions
- **Comments** - Explain complex logic and business rules
- **Examples** - Include usage examples in tool docstrings

### Error Handling Standards
- **Specific exceptions** - Use appropriate exception types
- **Error messages** - Clear, actionable error messages
- **Logging** - Structured logging for debugging

## Extension Points

### Adding New Microsoft Services
1. **API Client** - Extend `graph.py` with new endpoints
2. **Tools** - Add tools in the appropriate `tools/` package module
3. **Authentication** - Update scopes in `auth.py` if needed
4. **Testing** - Add integration tests for new services

### Performance Enhancements
1. **Caching** - Add caching logic to `graph.py` or tool layer
2. **Batch Operations** - Implement batch API calls where beneficial
3. **Background Processing** - Use async patterns for long operations

### Transport Extensions
1. **New Transports** - Extend `server.py` transport modes
2. **Security** - Add authentication methods in `server.py`
3. **Monitoring** - Add metrics and health checks
