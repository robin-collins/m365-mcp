# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Phase 1 Confirmation Regression Tests**: Added `tests/test_tool_confirmation.py` to assert the shared `require_confirm` validator guards all destructive and dangerous Phase 1 tools (email_send, email_reply, email_delete, file_delete, contact_delete, calendar_delete_event, emailrules_delete).
- **Parameter Validation Phase 1 Tasklist Review**: Comprehensive review and update of Phase 1 implementation plan
  - **Review Summary**: Created `reports/todo/PHASE1_REVIEW_SUMMARY.md` documenting critical findings
  - **Key Finding**: All 7 tools (5 delete + 2 send/reply) **already have** confirm validation - Phase 1 is REFACTORING task
  - **Scope Clarification**: Phase 1 refactors 7 tools (not 5) to use shared validators:
    - 5 Critical (Delete): email_delete, file_delete, contact_delete, calendar_delete_event, emailrules_delete
    - 2 Dangerous (Send/Reply): email_send, email_reply
  - **Prerequisites Added**: Explicit dependencies on Critical Path Sections 3-5 completion
  - **Status**: ✅ Ready for implementation after validators.py is complete

- **Parameter Validation Critical Path Tasklist Review**: Comprehensive review and enhancement of validation implementation plan
  - **Review Summary**: Created `reports/todo/CRITICAL_PATH_REVIEW_SUMMARY.md` documenting findings and updates
  - **Status**: ✅ Ready for implementation with 40+ enhancements across all 5 critical path sections

- **Parameter Validation Critical Path Tasklist**: Granular implementation tasklist for must-complete-first validation tasks (ENHANCED)
  - Section 1: Replace subprocess in `file.py:get_file` with httpx/graph client (CRITICAL SECURITY FIX)
    - Added URL validation for SSRF prevention (verify graph.microsoft.com domain)
    - Added file size limit checks before download (memory exhaustion prevention)
    - Added retry logic with exponential backoff for transient network failures
    - Added download path validation using `ensure_safe_path` helper
  - Section 2: Path traversal protection for all file operations (CRITICAL SECURITY FIX)
    - Windows-specific restrictions: UNC paths, drive letters, reserved filenames (CON, PRN, AUX, NUL, COM1-9, LPT1-9)
    - Added `validate_onedrive_path` helper for OneDrive path format validation
    - Comprehensive testing for path traversal, symlinks, alternate data streams
  - Section 3: Create `src/microsoft_mcp/validators.py` with shared validation helpers
    - Added 20+ validators including email, datetime, path, Graph ID, URL validation
    - Standardized error message format: `"Invalid {param} '{value}': {reason}. Expected: {guidance}"`
    - Added `ValidationError` exception class for consistency
    - Added cross-cutting concerns: logging strategy, PII protection, performance benchmarks
    - Deferred `validate_bearer_token_scopes` to Phase 2 (requires OAuth library integration)
  - Section 4: Enhanced `tests/conftest.py` with comprehensive fixtures
    - Added data fixtures: `mock_account_id`, `mock_email_data`, `mock_file_metadata`, `mock_calendar_event`, `mock_contact_data`
    - Added file system fixtures: `temp_safe_dir`, `mock_download_file`
    - Added datetime fixtures: `freeze_time`, `sample_iso_datetimes`
  - Section 5: Comprehensive validator testing with 100% coverage target
    - Organized tests by validator type (core, email, datetime, path, complex)
    - Added error message validation tests to verify template compliance and PII protection
    - Added platform compatibility tests for Windows and POSIX path handling
    - Added performance benchmarks for expensive validators
    - Added integration tests to verify backward compatibility
  - See `reports/todo/CRITICAL_PATH_TASKLIST.md` for detailed implementation plan

- **Parameter Validation Plan**: Comprehensive implementation plan for strengthening validation across all 50 MCP tools
  - Security-focused approach with immediate fixes for critical vulnerabilities
  - Shared validation toolkit design (`validators.py`) for consistent error handling
  - Phased rollout prioritizing destructive operations (delete), dangerous operations (send), then moderate/safe operations
  - Enhanced testing infrastructure with Graph API mocking and 100% validator coverage target
  - Full compliance verification with project steering documents
  - Estimated timeline: 12-15 days for complete implementation
  - See `reports/todo/PARAMETER_VALIDATION_PLAN.md` for detailed implementation strategy

- **Security Fixes**
  - Replaced `file_get` subprocess usage with streaming `httpx` client, including Microsoft domain allow-listing, size pre-checks, retry logic, and configurable timeouts.
  - Hardened file and attachment operations with `ensure_safe_path`, Windows-specific restrictions, and overwrite prevention.
  - Added OneDrive path validation and Microsoft Graph ID validation utilities.

- **Shared Validators**
  - Introduced `src/microsoft_mcp/validators.py` containing reusable helpers and the `ValidationError` class.
  - Implemented sanitised error formatting that guards against PII exposure.
  - Added security-focused helpers for Graph URL validation, OneDrive path validation, and filesystem safety checks.

- **Testing Infrastructure**
  - Added `tests/conftest.py` with Graph API fixtures and reusable factories.
  - Created dedicated unit tests for file downloads (`tests/test_file_get.py`) and validator helpers (`tests/test_validators.py`).

- **Documentation**
  - Documented file download safeguards, configuration flags, and SSRF protection in `SECURITY.md`.
  - Updated `FILETREE.md` to reflect the implemented validators module and new test suites.

- **Modular Tool Architecture**: Refactored 50 MCP tools into organized package structure:
  - `src/microsoft_mcp/tools/account.py` - 3 account management tools
  - `src/microsoft_mcp/tools/calendar.py` - 6 calendar tools
  - `src/microsoft_mcp/tools/contact.py` - 5 contact management tools
  - `src/microsoft_mcp/tools/email.py` - 9 email tools
  - `src/microsoft_mcp/tools/email_folders.py` - 3 email folder tools
  - `src/microsoft_mcp/tools/email_rules.py` - 9 email rule tools
  - `src/microsoft_mcp/tools/file.py` - 5 OneDrive file tools
  - `src/microsoft_mcp/tools/folder.py` - 3 OneDrive folder tools
  - `src/microsoft_mcp/tools/search.py` - 5 search tools
- **Package Exports**: `src/microsoft_mcp/tools/__init__.py` provides clean imports for all tools
- **MCP Instance Management**: Created `src/microsoft_mcp/mcp_instance.py` containing single FastMCP instance
  - Avoids circular import issues between tools.py and tool modules
  - All tool modules import `mcp` from `mcp_instance.py`
  - Registry file `tools.py` imports tool modules to trigger registration
  - Original monolithic `tools.py` backed up to `reference/tools_monolithic_original.py`

### Changed - BREAKING

- **Phase 1 Confirmation Refactor**: Replaced inline `confirm` checks in `email_send`, `email_reply`, `email_delete`, `file_delete`, `contact_delete`, `calendar_delete_event`, and `emailrules_delete` with the shared `require_confirm` validator. The tools now emit standardized `ValidationError` messages (`Invalid confirm 'False': … Expected: Explicit user confirmation`) while preserving original signatures and metadata.
- **Tool Naming Convention Migration**: All 50 MCP tools have been renamed to follow `category_verb_entity` convention for better organization and clarity:
  - **Account tools** (3): `list_accounts` → `account_list`, `authenticate_account` → `account_authenticate`, `complete_authentication` → `account_complete_auth`
  - **Email tools** (10): `list_emails` → `email_list`, `get_email` → `email_get`, `create_email_draft` → `email_create_draft`, `send_email` → `email_send`, `update_email` → `email_update`, `delete_email` → `email_delete`, `move_email` → `email_move`, `reply_to_email` → `email_reply`, `reply_all_email` → `email_reply_all`, `get_attachment` → `email_get_attachment`
  - **Email Folders tools** (3): `list_mail_folders` → `emailfolders_list`, `get_mail_folder` → `emailfolders_get`, `get_mail_folder_tree` → `emailfolders_get_tree`
  - **Email Rules tools** (9): `list_message_rules` → `emailrules_list`, `get_message_rule` → `emailrules_get`, `create_message_rule` → `emailrules_create`, `update_message_rule` → `emailrules_update`, `delete_message_rule` → `emailrules_delete`, `move_rule_to_top` → `emailrules_move_top`, `move_rule_to_bottom` → `emailrules_move_bottom`, `move_rule_up` → `emailrules_move_up`, `move_rule_down` → `emailrules_move_down`
  - **Calendar tools** (7): `list_events` → `calendar_list_events`, `get_event` → `calendar_get_event`, `create_event` → `calendar_create_event`, `update_event` → `calendar_update_event`, `delete_event` → `calendar_delete_event`, `respond_event` → `calendar_respond_event`, `check_availability` → `calendar_check_availability`
  - **Contact tools** (5): `list_contacts` → `contact_list`, `get_contact` → `contact_get`, `create_contact` → `contact_create`, `update_contact` → `contact_update`, `delete_contact` → `contact_delete`
  - **File tools** (5): `list_files` → `file_list`, `get_file` → `file_get`, `create_file` → `file_create`, `update_file` → `file_update`, `delete_file` → `file_delete`
  - **Folder tools** (3): `list_folders` → `folder_list`, `get_folder` → `folder_get`, `get_folder_tree` → `folder_get_tree`
  - **Search tools** (5): `search_files`, `search_emails`, `search_events`, `search_contacts` (unchanged), `unified_search` → `search_unified`
- **Safety Annotations**: All tools now include FastMCP `annotations` parameter with safety hints:
  - `readOnlyHint`: Indicates read-only operations (23 safe tools)
  - `destructiveHint`: Marks destructive operations like delete (5 critical tools)
  - `idempotentHint`: Indicates if repeated calls have same effect
  - `openWorldHint`: Always true for all tools
- **Meta Information**: All tools include `meta` parameter with categorization:
  - `category`: Tool category (account, email, emailfolders, emailrules, calendar, contact, file, folder, search)
  - `safety_level`: Safety classification (safe, moderate, dangerous, critical)
  - `requires_confirmation`: Flagged for dangerous/critical operations
- **Enhanced Descriptions**: All tool descriptions now include:
  - Emoji visual indicators (📖 safe, ✏️ moderate, 📧 dangerous, 🔴 critical, ⚠️ special caution)
  - Safety hints in parentheses (e.g., "read-only, safe for unsupervised use")
  - WARNING messages for dangerous/critical operations
  - Comprehensive documentation with examples for complex tools
- **Confirmation Parameters**: Added required `confirm: bool = False` parameter to all dangerous and critical operations:
  - **Dangerous (Send)**: `email_send`, `email_reply`, `email_reply_all` - must set `confirm=True` to send emails
  - **Critical (Delete)**: `email_delete`, `emailrules_delete`, `calendar_delete_event`, `contact_delete`, `file_delete` - must set `confirm=True` to delete
  - All confirmation-required tools raise `ValueError` with clear message if `confirm` is not `True`

### Added 2025-10-04

- **Streamable HTTP Transport Support** - Modern MCP Streamable HTTP protocol (spec 2025-03-26+) for web/API access with configurable host/port/path
- **Bearer Token Authentication** - Secure token-based authentication for HTTP transport with automatic validation
- **OAuth Authentication Support** - Enterprise-grade OAuth 2.0 authentication for HTTP transport (FastMCP 2.0+)
- **Security Safeguards**:
  - HTTP transport refuses to start without authentication (requires explicit `MCP_ALLOW_INSECURE=true` override)
  - Token length validation (minimum 32 characters recommended)
  - Network binding warnings for `0.0.0.0` exposure
  - Health check endpoint at `/health` (no auth required)
  - MCP endpoint at configurable path (default `/mcp`)
- Email folder navigation tools:
  - `list_mail_folders` - List root or child mail folders with metadata (childFolderCount, unreadItemCount, etc.)
  - `get_mail_folder` - Get specific mail folder details by folder ID
  - `get_mail_folder_tree` - Build recursive email folder tree with configurable max depth
- OneDrive folder navigation tools:
  - `list_folders` - List only folders (not files) in OneDrive location
  - `get_folder` - Get specific OneDrive folder metadata
  - `get_folder_tree` - Build recursive OneDrive folder tree with configurable max depth
- Message rule (email filter) management tools:
  - `list_message_rules` - List all inbox message rules
  - `get_message_rule` - Get specific rule details
  - `create_message_rule` - Create new email filtering rule with conditions and actions
  - `update_message_rule` - Update existing rule
  - `delete_message_rule` - Delete a rule
  - `move_rule_to_top` - Move rule to execute first (sequence = 1)
  - `move_rule_to_bottom` - Move rule to execute last
  - `move_rule_up` - Move rule up one position in execution order
  - `move_rule_down` - Move rule down one position in execution order
- Enhanced `list_emails` to support direct folder ID lookup via new `folder_id` parameter
- Enhanced `list_files` to support `folder_id` parameter and `type_filter` for filtering files/folders
- Internal helper functions for code reuse:
  - `_list_mail_folders_impl()` - Email folder listing implementation
  - `_list_folders_impl()` - OneDrive folder listing implementation

### Changed

- `list_emails` now accepts optional `folder_id` parameter for direct folder access (takes precedence over `folder` name)
- `list_emails` `folder` parameter is now optional (defaults to "inbox" if neither `folder` nor `folder_id` provided)
- `list_files` now accepts `folder_id` parameter for direct folder access and `type_filter` to filter by files/folders/all
- `list_files` maintains backward compatibility with existing path-based calls

### Fixed

- Fixed "'FunctionTool' object is not callable" error in `get_mail_folder_tree` by extracting shared logic into internal helper function
- Fixed `AttributeError: 'FastMCP' object has no attribute 'get_asgi_app'` by using correct `http_app()` method for Streamable HTTP transport
- Fixed auth middleware to gracefully handle browser requests (favicon.ico, robots.txt) by returning 404 instead of 401
- Fixed auth middleware 500 errors by returning JSONResponse instead of raising HTTPException (proper handling of 401 unauthorized requests)

### Documentation

- Added `QUICKSTART.md` - Quick start guide for installation, configuration, and first-time setup
- Added `.env.example` - Template file with all configuration options and detailed comments
- Added `EMAIL_OUTPUT_FORMAT.md` - Comprehensive guide to email reading output format, metadata fields, and AI interaction examples
- Added `SECURITY.md` - Complete security guide covering transport modes, authentication methods, best practices, and incident response
- Added `HTTP_TRANSPORT_IMPLEMENTATION.md` - Complete implementation details for Streamable HTTP transport and security features
- Updated `README.md` with quick start section and transport mode configuration

### Dependencies

- Added `fastapi>=0.115.0` - Required for Streamable HTTP transport with bearer auth middleware
- Added `uvicorn>=0.32.0` - ASGI server for Streamable HTTP transport

### Notes

- Uses modern MCP Streamable HTTP protocol (spec 2025-03-26+) instead of deprecated SSE transport
- Streamable HTTP provides bidirectional communication over single endpoint at `/mcp`

## [0.1.0] - 2024-10-03

### Added 2024-10-03

- Initial release with Microsoft Graph API integration
- Email management tools (list, send, reply, delete, move, attachments)
- Calendar tools (events, availability, responses)
- OneDrive file tools (upload, download, browse, search)
- Contacts tools (list, search, create, update, delete)
- Multi-account support with device flow authentication
- Unified search across emails, events, and files
