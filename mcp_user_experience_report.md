# M365 MCP Server - User Experience & Diagnostic Report

This report documents the current health, tool validation results, and diagnostic state of the `m365-mcp` server. It summarizes findings from comprehensive regression and category-specific testing, issues identified and resolved, and the current operational status of the server.

---

## Executive Summary

The **M365 MCP Server (v0.2.3)** is currently in a highly stable, fully validated state. Following a series of platform-specific debugging sessions on the Windows environment, all critical system subsystems have been thoroughly verified. 

A total of **341 test cases** were executed and passed successfully across the codebase, confirming the reliability of database encryption, cache warming, background workers, validation rules, and direct Microsoft Graph API integrations.

---

## Test Execution Results by Category

All tests were categorized and executed sequentially to isolate concerns and ensure flawless compatibility:

| Test Category | Total Tests | Status | Key Subsystems Verified |
| :--- | :---: | :---: | :--- |
| **Cache Management & Tuning** | 72 | **PASSED** | Connection pooling, compression thresholds (≥50KB), TTL policy enforcement (Fresh/Stale/Expired), and SQLCipher decryption/encryption integrity |
| **Calendar Validation** | 31 | **PASSED** | ISO datetime parsing, timezone verification, attendee deduplication, attendee limit limits, and event proposal/free-busy status |
| **Email Tools & Formatting** | 73 | **PASSED** | Draft creation, folder tree building, email moves/archives, rule updates, CC recipient parsing, and response confirmations |
| **Contacts Management** | 11 | **PASSED** | Contact lists, field validation, and VCard exports (case-insensitivity support) |
| **File and Folder Operations** | 34 | **PASSED** | OneDrive paths, file copy/move operations, renaming restrictions, safe folder deletion, and attachment size limits |
| **Accounts, Workers & Validators** | 86 | **PASSED** | NamedTuple account serialization, background task enqueuing/priority ordering, backoff retries, DPAPI Windows keyrings, and UNC path blocks |
| **Full Subprocess Integration** | 34 | **PASSED** | Client-Server handshake, tool schemas, and end-to-end integration mapping over the stdio transport layer |

**Overall Result: 341 / 341 Tests Passed (100% Success)**

---

## Identified Issues & Platform Fixes

During the diagnostic phase, several critical platform-specific and functional bugs were identified and successfully resolved:

### 1. Windows alternate data streams (ADS) false-positives
* **Problem**: In `src/m365_mcp/validators.py`, the path validator checks for the presence of a colon (`:`) to block unsafe alternate data streams on Windows. However, `resolved.parts[0]` returns `C:\` which is not equal to `resolved.drive` (`C:`). As a result, the drive letter colon triggered a false-positive `ValidationError` for any absolute path.
* **Fix**: Updated `ensure_safe_path` to skip parts matching or starting with `resolved.drive` (e.g., `C:\`), resolving path validation errors for workspace/temporary files.

### 2. SQLite Database File Lockings (`WinError 32`)
* **Problem**: The `CacheManager` pooling mechanism keeps connections open in the connection pool. During unit test teardowns on Windows, attempting to delete temporary database files threw a `PermissionError` because active database handles remained in memory.
* **Fix**: Added explicit `close()` and `__del__()` methods to `CacheManager` to release pooled SQLite connection file locks. Yielded managers in all conftest fixtures and explicitly invoked `close()` during test teardown.

### 3. Missing Timezone Data Database on Windows
* **Problem**: Standard Python `zoneinfo` lookup failed on Windows with `ZoneInfoNotFoundError` (e.g. for `UTC`) due to the absence of a native IANA timezone database on Windows systems.
* **Fix**: Added the `tzdata` package as a project dependency and installed it using `uv pip` to guarantee timezone parsing consistency across all operating systems.

### 4. get_app() Tuple Unpacking Bug
* **Problem**: In `src/m365_mcp/tools/account.py`, the tool handlers treated the returned value of `auth.get_app()` as a single client instance instead of a tuple `(app, tenant_id)`, which would cause a crash when authenticating new accounts.
* **Fix**: Updated the tool handlers to correctly unpack the tuple (`app, _ = auth.get_app()`), and aligned all related test mocks in `tests/test_account_validation.py`.

### 5. Integration Test Entrypoint EXE Locking
* **Problem**: Integration tests launched the server using `uv run m365-mcp`, causing `uv` to perform packaging checks and attempt to modify the locked `m365-mcp.exe` entrypoint, resulting in a sharing violation (os error 32).
* **Fix**: Replaced command invocation in integration tests to use Python directly via `sys.executable` and `["-m", "m365_mcp.server"]`, preventing packaging build lockings during tests.

---

## Log & Console Monitoring Status

The server console and logs have been cleared and monitored:
* **Log Directory**: `c:\projects\m365-mcp\logs`
* **Startup Check**: Logging is initialized at `DEBUG` level and successfully records database schema updates and standard `ListToolsRequest` / `CallToolRequest` handshakes.
* **Cache DB Creation**: Successfully recreated the database file (`C:\Users\tech\.m365_mcp_cache.db`) with active encryption and pool sizes of 5. All operations are working optimally.
