# File Tree

```text
microsoft-mcp/
├── .cache/                                 # **NEW** Cache directory (auto-created, not in repo)
│   └── token_cache.json                   # MSAL token cache for authenticated accounts
├── .env                                    # Environment variables (create from .env.example)
├── .env.example                            # **NEW** Environment configuration template with comments
├── .env.stdio.example                      # **NEW** stdio mode configuration example
├── .env.http.example                       # **NEW** HTTP mode configuration example
├── .git/                                   # Git repository
├── .gitignore                              # Git ignore rules (includes .env)
├── .python-version                         # Python version specification
├── .venv/                                  # Virtual environment
├── authenticate.py                         # **MODIFIED** Interactive authentication script (supports --env-file)
├── CHANGELOG.md                            # **MODIFIED** Project changelog with monitoring system updates
├── CLAUDE.md                               # Claude Code guidance file
├── EMAIL_FOLDER_IMPLEMENTATION_SUMMARY.md  # **NEW** Email folder tools implementation
├── EMAIL_OUTPUT_FORMAT.md                  # **NEW** Email reading output format guide
├── ENV_FILE_USAGE.md                       # **NEW** Guide for using --env-file argument
├── FOLDER_LISTING_TODO.md                  # **NEW** Implementation plan
├── FILETREE.md                             # **MODIFIED** This file - project structure with monitoring updates
├── MESSAGE_RULES_IMPLEMENTATION_SUMMARY.md # **NEW** Message rule tools implementation
├── MONITORING.md                           # **NEW** Monitoring and troubleshooting guide
├── ONEDRIVE_FOLDER_IMPLEMENTATION_SUMMARY.md # **NEW** OneDrive folder tools implementation
├── QUICKSTART.md                           # **NEW** Quick start guide for installation and setup
├── SECURITY.md                             # **NEW** Security guide for transport modes and authentication
├── HTTP_TRANSPORT_IMPLEMENTATION.md         # **NEW** Streamable HTTP transport implementation details
├── HTTP_APP_METHOD_FIX.md                   # **NEW** Fix for http_app() method issue (2025-10-06)
├── MIGRATION_SSE_TO_HTTP.md                 # **NEW** Migration notes from SSE to Streamable HTTP
├── monitor_mcp_server.sh                   # **NEW** Health monitoring script with auto-recovery
├── start_mcp_with_monitoring.sh            # **NEW** Server startup script with monitoring
├── pyproject.toml                          # **MODIFIED** Python project configuration (added fastapi, uvicorn)
├── README.md                               # Project documentation
├── uv.lock                                 # UV package lock file
├── logs/                                   # **NEW** Log directory (auto-created)
│   ├── mcp_server_all.jsonl                # JSON structured logs (all levels)
│   ├── mcp_server_errors.jsonl             # JSON error logs only
│   ├── mcp_server.log                      # Human-readable logs
│   ├── server_output.log                   # Server stdout/stderr
│   └── monitor.log                         # Monitor activity log
├── reports/                                # **NEW** Error report directory (auto-created)
│   └── error_report_YYYYMMDD_HHMMSS.txt   # Auto-generated error reports
├── src/
│   └── microsoft_mcp/
│       ├── __init__.py                     # Package initialization
│       ├── auth.py                         # **MODIFIED** MSAL authentication & token management (env loading removed)
│       ├── graph.py                        # Microsoft Graph API client wrapper
│       ├── health_check.py                 # **NEW** Health check utility module with async/sync functions
│       │                                   #   - check_health() - Single health check
│       │                                   #   - continuous_health_check() - Continuous monitoring
│       │                                   #   - CLI: python -m microsoft_mcp.health_check
│       ├── logging_config.py               # **NEW** Comprehensive logging configuration
│       │                                   #   - Structured JSON formatter
│       │                                   #   - Human-readable formatter with colors
│       │                                   #   - Multiple log outputs (JSON, errors, readable)
│       │                                   #   - Automatic log rotation (10 files × 10MB)
│       ├── mcp_instance.py                 # **NEW** FastMCP instance (single source of truth)
│       ├── server.py                       # **MODIFIED** FastMCP server with logging, monitoring, and graceful shutdown
│       │                                   #   - Command-line argument support (--env-file)
│       │                                   #   - Comprehensive structured logging
│       │                                   #   - Signal handlers for graceful shutdown
│       │                                   #   - Request/response timing and client IP tracking
│       ├── tools.py                        # **NEW** MCP tool registry (imports mcp and triggers tool registration)
│       ├── validators.py                   # Shared validation helpers and ValidationError class
│       │                                   #   - Validators for accounts, email, datetime, paths, Graph IDs, URLs
│       │                                   #   - Security helpers: ensure_safe_path, validate_graph_url, validate_onedrive_path
│       │                                   #   - Sanitised error messaging and logging utilities
│       └── tools/                          # **NEW** Modular tool implementations (50 tools across 9 files)
│           ├── __init__.py                  # **NEW** Tool package exports (imports all functions and mcp)
│           ├── account.py                   # **NEW** Account management tools (3 tools)
│           ├── calendar.py                  # **NEW** Calendar and event tools (6 tools)
│           ├── contact.py                   # **NEW** Contact management tools (5 tools)
│           ├── email.py                     # **NEW** Email operations tools (9 tools)
│           ├── email_folders.py             # **NEW** Email folder navigation tools (3 tools)
│           ├── email_rules.py               # **NEW** Email rule/filter management tools (9 tools)
│           ├── file.py                      # **NEW** OneDrive file operations tools (5 tools)
│           ├── folder.py                    # **NEW** OneDrive folder navigation tools (3 tools)
│           └── search.py                    # **NEW** Search operations tools (5 tools)
│           ├── account.py: 3 tools
│           │   ├── account_list                    # List signed-in accounts
│           │   ├── account_authenticate            # Start device flow auth
│           │   └── account_complete_auth           # Complete device flow
│           ├── calendar.py: 6 tools
│           │   ├── calendar_get_event              # Get event details
│           │   ├── calendar_create_event           # Create event
│           │   ├── calendar_update_event           # Update event
│           │   ├── calendar_delete_event           # Delete event (confirm=True)
│           │   ├── calendar_respond_event          # Respond to invite
│           │   └── calendar_check_availability     # Check availability
│           ├── contact.py: 5 tools
│           │   ├── contact_list                    # List contacts
│           │   ├── contact_get                     # Get contact details
│           │   ├── contact_create                  # Create contact
│           │   ├── contact_update                  # Update contact
│           │   └── contact_delete                  # Delete contact (confirm=True)
│           ├── email.py: 9 tools
│           │   ├── email_list                      # List emails (folder_id param)
│           │   ├── email_get                       # Get email details
│           │   ├── email_create_draft              # Create draft
│           │   ├── email_send                      # Send email (confirm=True)
│           │   ├── email_update                    # Update email properties
│           │   ├── email_delete                    # Delete email (confirm=True)
│           │   ├── email_move                      # Move to folder
│           │   ├── email_reply                     # Reply to sender (confirm=True)
│           │   └── email_get_attachment            # Download attachment
│           ├── email_folders.py: 3 tools
│           │   ├── emailfolders_list               # List root/child folders
│           │   ├── emailfolders_get                # Get folder details
│           │   └── emailfolders_get_tree           # Build recursive tree
│           ├── email_rules.py: 9 tools
│           │   ├── emailrules_list                 # List email filter rules
│           │   ├── emailrules_get                  # Get rule details
│           │   ├── emailrules_create               # Create filter rule
│           │   ├── emailrules_update               # Update rule
│           │   ├── emailrules_delete               # Delete rule (confirm=True)
│           │   ├── emailrules_move_top             # Move to sequence 1
│           │   ├── emailrules_move_bottom          # Move to last position
│           │   ├── emailrules_move_up              # Decrease sequence by 1
│           │   └── emailrules_move_down            # Increase sequence by 1
│           ├── file.py: 5 tools
│           │   ├── file_list                       # List files/folders (folder_id, type_filter)
│           │   ├── file_get                        # Download file
│           │   ├── file_create                     # Upload file
│           │   ├── file_update                     # Update file content
│           │   └── file_delete                     # Delete file/folder (confirm=True)
│           ├── folder.py: 3 tools
│           │   ├── folder_list                     # List OneDrive folders
│           │   ├── folder_get                      # Get folder metadata
│           │   └── folder_get_tree                 # Build recursive tree
│           └── search.py: 5 tools
│               ├── search_files                    # Search OneDrive files
│               ├── search_emails                   # Search emails
│               ├── search_events                   # Search calendar events
│               ├── search_contacts                 # Search contacts
│               └── search_unified                  # Unified search
├── tests/
│   ├── __init__.py                         # Test package initialization
│   ├── conftest.py                         # Shared pytest fixtures for Graph API mocking
│   ├── test_integration.py                 # **MODIFIED** Integration tests (supports TEST_ENV_FILE env var)
│   └── tools/                              # Planned module-specific validation suites (future work)
│       ├── test_email_validation.py        # Planned email tool validation tests
│       ├── test_file_validation.py         # Planned file tool validation tests
│       ├── test_calendar_validation.py     # Planned calendar tool validation tests
│       ├── test_contact_validation.py      # Planned contact tool validation tests
│       ├── test_email_rules_validation.py  # Planned email rules validation tests
│       ├── test_search_validation.py       # Planned search tool validation tests
│       ├── test_folder_validation.py       # Planned folder validation tests
│       ├── test_email_folders_validation.py # **PLANNED** Email folders validation tests
│       └── test_account_validation.py      # **PLANNED** Account tool validation tests
└── reports/
    └── todo/
        ├── PARAMETER_VALIDATION.md         # **NEW** Parameter validation analysis report
        └── PARAMETER_VALIDATION_PLAN.md    # **NEW** Comprehensive validation implementation plan
```

## Key Files

### Source Code

- **`src/microsoft_mcp/tools.py`** (tool registry, imports from tools/ directory)
- **`src/microsoft_mcp/tools/`** (modular tool implementations)
  - `account.py` - Account management (3 tools)
  - `calendar.py` - Calendar operations (6 tools)
  - `contact.py` - Contact management (5 tools)
  - `email.py` - Email operations (9 tools)
  - `email_folders.py` - Email folder navigation (3 tools)
  - `email_rules.py` - Email rule management (9 tools)
  - `file.py` - OneDrive file operations (5 tools)
  - `folder.py` - OneDrive folder navigation (3 tools)
  - `search.py` - Search operations (5 tools)

### Documentation

- **`README.md`** - User-facing documentation with feature overview
- **`QUICKSTART.md`** - Quick start guide for installation and setup
- **`MONITORING.md`** - **NEW** Comprehensive monitoring and troubleshooting guide
  - Log file structure and formats
  - Health check monitoring
  - Error report interpretation
  - Common troubleshooting scenarios
  - Production deployment best practices
- **`SECURITY.md`** - Security guide for transport modes and authentication
- **`CLAUDE.md`** - AI assistant guidance
- **`CHANGELOG.md`** - Version history with monitoring system updates
- **`FOLDER_LISTING_TODO.md`** - Implementation plan
- **`EMAIL_FOLDER_IMPLEMENTATION_SUMMARY.md`** - Email folder tools implementation
- **`EMAIL_OUTPUT_FORMAT.md`** - Email reading output format guide
- **`ONEDRIVE_FOLDER_IMPLEMENTATION_SUMMARY.md`** - OneDrive folder tools implementation
- **`MESSAGE_RULES_IMPLEMENTATION_SUMMARY.md`** - Message rule tools implementation
- **`HTTP_TRANSPORT_IMPLEMENTATION.md`** - Streamable HTTP transport implementation details
- **`reports/todo/PARAMETER_VALIDATION.md`** - Parameter validation analysis report
- **`reports/todo/PARAMETER_VALIDATION_PLAN.md`** - Comprehensive validation implementation plan

### Scripts

- **`monitor_mcp_server.sh`** - **NEW** Health monitoring script with auto-recovery
  - Periodic health checks via HTTP endpoint
  - Automatic process cleanup on failure
  - Comprehensive error report generation
  - Configurable failure thresholds
- **`start_mcp_with_monitoring.sh`** - **NEW** Server startup script with monitoring
  - Launches server with automatic monitoring
  - Environment validation
  - Token generation if not provided
  - Graceful shutdown handling

### Configuration

- **`pyproject.toml`** - Project metadata, dependencies, build config
- **`.env`** - Environment variables (create from .env.example, not committed to git)
- **`.env.example`** - Template with all configuration options and detailed comments
- **`uv.lock`** - Locked dependency versions

### Authentication

- **`authenticate.py`** - CLI tool for user authentication
- **`.cache/token_cache.json`** - Token cache stored in project directory (not in repo)

## Tool Naming Convention

All 50 MCP tools follow the `category_verb_entity` naming pattern for better organization:

**Categories:**

- `account_` - Account authentication and management (3 tools)
- `email_` - Email operations (10 tools)
- `emailfolders_` - Email folder navigation (3 tools)
- `emailrules_` - Email rule/filter management (9 tools)
- `calendar_` - Calendar and event operations (7 tools)
- `contact_` - Contact management (5 tools)
- `file_` - OneDrive file operations (5 tools)
- `folder_` - OneDrive folder navigation (3 tools)
- `search_` - Search operations (5 tools)

**Safety Levels:**

- 📖 **Safe (23 tools)** - Read-only operations, safe for unsupervised use
- ✏️ **Moderate (19 tools)** - Write/modify operations, requires user confirmation recommended
- 📧 **Dangerous (3 tools)** - Send operations (email), always require user confirmation
- 🔴 **Critical (5 tools)** - Delete operations, always require user confirmation with `confirm=True` parameter

**Confirmation Required:**
Tools with `confirm=True` parameter (8 tools):

- Send: `email_send`, `email_reply`, `email_reply_all`
- Delete: `email_delete`, `emailrules_delete`, `calendar_delete_event`, `contact_delete`, `file_delete`

## Recent Changes

### 2024-10-03 - Email Folder Tools

**Modified:**

- `src/microsoft_mcp/tools.py` - Added 3 new tools, enhanced 1 tool, added 1 helper function

**Added:**

- `CHANGELOG.md` - Project changelog
- `FILETREE.md` - This file
- `EMAIL_FOLDER_IMPLEMENTATION_SUMMARY.md` - Implementation details
- `FOLDER_LISTING_TODO.md` - Full implementation plan
- `VERIFICATION_REPORT.md` - Comprehensive verification results
- `BUGFIX_SUMMARY.md` - Bug fix documentation
- `verify_email_tools.py` - Tool signature verification script
- `verify_implementation.py` - Implementation verification script
- `test_fix.py` - FunctionTool bug fix verification

**Bug Fixes:**

- Fixed "'FunctionTool' object is not callable" error in `get_mail_folder_tree`
- Created internal helper `_list_mail_folders_impl()` for code reuse

**Tool Count:** 35 → 38 (email folder tools added)

### 2024-10-03 - OneDrive Folder Tools

**Modified:**

- `src/microsoft_mcp/tools.py` - Added 3 new OneDrive tools, enhanced 1 tool, added 1 helper

**Added:**

- `ONEDRIVE_FOLDER_IMPLEMENTATION_SUMMARY.md` - OneDrive implementation details
- `verify_onedrive_tools.py` - OneDrive tool verification script

**New Tools:**

- `list_folders` - List only folders in OneDrive
- `get_folder` - Get OneDrive folder metadata
- `get_folder_tree` - Build recursive OneDrive folder tree
- `list_files` enhanced - Added folder_id and type_filter parameters

**Helper Function:**

- `_list_folders_impl()` - OneDrive folder listing implementation

**Tool Count:** 38 → 41 (OneDrive folder tools added)

### 2025-10-07 - Modular Tool Architecture

**Modified:**

- `src/microsoft_mcp/tools.py` - Refactored to import from modular tools/ directory
- `src/microsoft_mcp/tools/__init__.py` - **NEW** Package exports for all 50 tools

**Added:**

- `src/microsoft_mcp/tools/` - **NEW** Modular tool implementations (9 files)
  - `account.py` - 3 account management tools
  - `calendar.py` - 6 calendar tools
  - `contact.py` - 5 contact management tools
  - `email.py` - 9 email tools
  - `email_folders.py` - 3 email folder tools
  - `email_rules.py` - 9 email rule tools
  - `file.py` - 5 OneDrive file tools
  - `folder.py` - 3 OneDrive folder tools
  - `search.py` - 5 search tools

**Benefits:**

- Better code organization and maintainability
- Easier to locate and modify specific tool categories
- Cleaner imports and exports
- Preserved all existing functionality

**Tool Count:** 50 (unchanged - same functionality, improved structure)

**Added:**

- `MESSAGE_RULES_IMPLEMENTATION_SUMMARY.md` - Rule management implementation details
- `EMAIL_OUTPUT_FORMAT.md` - Email reading output format guide
- `verify_rule_tools.py` - Rule tool verification script

**New Tools:**

- `list_message_rules` - List all inbox rules
- `get_message_rule` - Get specific rule details
- `create_message_rule` - Create email filter with conditions/actions
- `update_message_rule` - Update existing rule
- `delete_message_rule` - Delete a rule
- `move_rule_to_top` - Move to sequence 1 (execute first)
- `move_rule_to_bottom` - Move to last position
- `move_rule_up` - Decrease sequence by 1
- `move_rule_down` - Increase sequence by 1

**Azure Permission Required:**

- `MailboxSettings.ReadWrite` - Not yet added to Azure app

**Tool Count:** 41 → 50 (message rule tools added)

**Total Statistics:**

- Starting tools: 35
- Email folder tools: +3 (38 total)
- OneDrive folder tools: +3 (41 total)
- Message rule tools: +9 (50 total)
- Enhanced tools: 2 (`list_emails`, `list_files`)
- Helper functions: 2 (`_list_mail_folders_impl`, `_list_folders_impl`)

### 2025-10-05 - Transport Modes and Security

**Modified:**

- `src/microsoft_mcp/server.py` - Added stdio/Streamable HTTP transport selection with bearer token authentication
- `pyproject.toml` - Added fastapi and uvicorn dependencies

**Added:**

- `SECURITY.md` - Comprehensive security guide for transport modes, authentication, and best practices
- Streamable HTTP transport support with configurable host/port
- Bearer token authentication middleware for Streamable HTTP mode
- OAuth authentication support (FastMCP 2.0+)
- Security safeguards: refuses to start SSE without auth, token validation, network warnings

**Features:**

- **stdio transport** (default) - Process-isolated, secure for desktop apps (Claude Desktop)
- **Streamable HTTP transport** - HTTP-based for web/API access with required authentication:
  - Bearer token authentication (recommended)
  - OAuth 2.0 authentication
  - Health check endpoint at `/health`
  - Network binding warnings for `0.0.0.0`
  - Minimum token length validation (32 chars)

**Environment Variables:**

- `MCP_TRANSPORT` - "stdio" (default) or "sse"
- `MCP_HOST` - Streamable HTTP server bind address (default: "127.0.0.1")
- `MCP_PORT` - Streamable HTTP server port (default: "8000")
- `MCP_AUTH_METHOD` - "bearer", "oauth", or "none"
- `MCP_AUTH_TOKEN` - Bearer token (required for bearer auth)
- `MCP_ALLOW_INSECURE` - Allow SSE without auth (DANGEROUS, requires explicit opt-in)
