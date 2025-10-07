# Documentation & Compliance Tasklist

Structured checklist to ensure validation updates are fully documented and aligned with steering directives.

## Context & Prerequisites

**Purpose:** This tasklist ensures all parameter validation changes are properly documented, comply with project standards, and maintain user-facing documentation accuracy.

**Prerequisites:**

- ✅ Critical Path Sections 1-5 complete (validators.py implemented and tested)
- ✅ Phase 1 complete (confirm validation refactored - 7 tools)
- ✅ Phase 2 complete (recipient, body, attendee, datetime validation - 6+ tools)
- ✅ Phase 3 complete (update dict, limit, datetime validation - 17+ tools)
- ✅ Phase 4 complete (folder, query, path validation - 8+ tools)
- ✅ Testing & Quality complete (unit tests, integration tests, coverage >90%)

**Scope:** This tasklist covers documentation and compliance verification AFTER all implementation phases are complete. It should be executed as the final step before merging validation work.

---

## 1. Update Tool Docstrings with Valid Parameter Ranges

### 1a. Inventory All Validation Changes

- [ ] **Critical Path Tools (Security Fixes)**
  - [ ] `file_get` - Document SSRF protection, file size limits, retry behavior
  - [ ] All tools using `validate_onedrive_path` - Document path traversal protection

- [ ] **Phase 1 Tools (Confirm Validation - 7 tools)**
  - [ ] `email_delete` - Document `confirm: bool = False` parameter
  - [ ] `contact_delete` - Document `confirm: bool = False` parameter
  - [ ] `calendar_delete_event` - Document `confirm: bool = False` parameter
  - [ ] `file_delete` - Document `confirm: bool = False` parameter
  - [ ] `emailrules_delete` - Document `confirm: bool = False` parameter
  - [ ] `email_send` - Document `confirm: bool = False` parameter
  - [ ] `email_reply` - Document `confirm: bool = False` parameter

- [ ] **Phase 2 Tools (Dangerous Operations - 6+ tools)**
  - [ ] `email_send` - Document recipient validation (to/cc/bcc normalization)
  - [ ] `email_reply` - Document body validation (non-empty requirement)
  - [ ] `calendar_respond_event` - Document response validation (accept/tentative/decline only)
  - [ ] `calendar_create_event` - Document attendee validation and datetime formats
  - [ ] `calendar_check_availability` - Document attendee validation

- [ ] **Phase 3 Tools (Moderate Operations - 17+ tools)**
  - [ ] `email_update` - Document allowed keys: isRead, categories, importance, flag
  - [ ] `calendar_update_event` - Document allowed keys: subject, start, end, timezone, location, body, attendees
  - [ ] `contact_update` - Document allowed keys: givenName, surname, displayName, emailAddresses, etc.
  - [ ] `emailrules_update` - Document allowed keys: display_name, conditions, actions, sequence
  - [ ] 13 limit-accepting tools - Document limit bounds (see Phase 3 table)

- [ ] **Phase 4 Tools (Safe Operations - 8+ tools)**
  - [ ] `email_list` - Document folder validation (valid folder names from FOLDERS dict)
  - [ ] `folder_list` - Document folder validation
  - [ ] Search tools - Document query validation (non-empty, non-whitespace)
  - [ ] `search_unified` - Document entity_types validation (optional list of allowed types)

- [ ] **Create validation tracking spreadsheet**
  - [ ] Tool name | Module | Parameters changed | Old behavior | New behavior | Docstring updated?

### 1b. Update Args Sections with Validation Constraints

- [ ] **Add range information** for limit parameters
  - [ ] Example: `limit: Maximum results to return. Must be between 1-200. Defaults to 10.`

- [ ] **Add choice information** for enum-like parameters
  - [ ] Example: `response: Response type. Valid values: "accept", "tentative", "decline".`

- [ ] **Add format information** for complex parameters
  - [ ] Example: `attendees: List of attendee email addresses. Can be single string or list. Empty strings will be filtered out.`

- [ ] **Add confirm parameter documentation**
  - [ ] Use consistent wording: `confirm: Must be True to confirm [operation]. Prevents accidental [operation]. Defaults to False.`

### 1c. Add/Update Raises Sections

- [ ] **Add ValidationError documentation** for all tools using validators
  - [ ] Example: `Raises:\n        ValueError: If confirm is False (deletion requires confirmation).`

- [ ] **Document all validation error scenarios** per tool
  - [ ] Confirm validation errors (7 tools)
  - [ ] Recipient validation errors (email_send)
  - [ ] Body validation errors (email_reply)
  - [ ] Response validation errors (calendar_respond_event)
  - [ ] Attendee validation errors (calendar tools)
  - [ ] Update dict validation errors (4 update tools)
  - [ ] Limit validation errors (13 limit tools)
  - [ ] Folder validation errors (folder tools)
  - [ ] Query validation errors (search tools)
  - [ ] Path validation errors (file/folder tools)

### 1d. Verify Safety Indicators and Annotations

- [ ] **Verify FastMCP annotations** still accurate (from `.projects/steering/tool-names.md`)
  - [ ] readOnlyHint: True for safe operations
  - [ ] destructiveHint: True for delete operations
  - [ ] meta.safety_level: "safe", "moderate", "dangerous", "critical"

- [ ] **Verify emoji indicators** in descriptions match safety level
  - [ ] 📖 Safe (read-only)
  - [ ] ✏️ Moderate (write/modify)
  - [ ] 📧 Dangerous (send operations)
  - [ ] 🔴 Critical (delete operations)

### 1e. Google-Style Docstring Compliance

- [ ] **Line length compliance** - All docstring lines ≤72 characters (PEP 257)
- [ ] **Format compliance** - Args, Returns, Raises sections properly formatted
- [ ] **Summary line compliance** - Imperative mood, ends with period
- [ ] **Run validation checks**
  - [ ] `uvx ruff check --select D src/microsoft_mcp/tools/` (docstring linting)
  - [ ] `uv run pyright` (type hint validation)

### 1f. Consistency with README/QUICKSTART Examples

- [ ] **Review README.md** for example tool calls
  - [ ] Update examples to include new validation parameters
  - [ ] Add examples showing confirm=True usage

- [ ] **Review QUICKSTART.md** for example tool calls
  - [ ] Update examples to match new validation behavior

- [ ] **Review CLAUDE.md** "Common Patterns" section
  - [ ] Update patterns to show validation best practices

## 2. Document Breaking Changes in `CHANGELOG.md`

### 2a. Identify Breaking vs Non-Breaking Changes

- [ ] **CRITICAL: Confirm parameter is NOT breaking**
  - [ ] All 7 tools already have `confirm` validation implemented (Phase 1 is refactoring, not new feature)
  - [ ] Default value is `confirm=False` maintaining backward compatibility
  - [ ] Users who don't pass confirm will get validation error (which they already get today)
  - [ ] **Classification:** Enhancement, NOT breaking change

- [ ] **Breaking Change: Update dict key validation (Phase 3)**
  - [ ] `email_update`, `calendar_update_event`, `contact_update`, `emailrules_update` now reject unknown keys
  - [ ] **Impact:** Users passing invalid/unsupported keys will get ValueError instead of silent ignore
  - [ ] **Required action:** Review update dict parameters, remove invalid keys

- [ ] **Breaking Change: Limit bounds validation (Phase 3)**
  - [ ] 13 tools now enforce strict limit ranges (e.g., email_list: 1-200, contact_list: 1-500)
  - [ ] **Impact:** Users passing limit=0 or limit=9999 will get ValueError
  - [ ] **Required action:** Adjust limit parameters to fall within documented ranges

- [ ] **Breaking Change: Folder name validation (Phase 4)**
  - [ ] `email_list` and `folder_list` now validate folder names against FOLDERS dict
  - [ ] **Impact:** Users passing invalid folder names (typos, unknown folders) will get ValueError
  - [ ] **Required action:** Use valid folder names from FOLDERS dict (inbox, sent, drafts, deleted, junk, archive, outbox)

- [ ] **Security Fix: Path traversal protection (Critical Path)**
  - [ ] All file/folder tools now block path traversal attempts (../, .\, UNC paths, drive letters)
  - [ ] **Impact:** Users attempting to access paths outside OneDrive root will get ValueError
  - [ ] **Required action:** Use OneDrive-relative paths only

- [ ] **Enhancement: Recipient normalization (Phase 2)**
  - [ ] `email_send` now normalizes recipients (str → list, empty string filtering)
  - [ ] **Impact:** More lenient - accepts both string and list for to/cc/bcc
  - [ ] **Required action:** None (backward compatible)

- [ ] **Enhancement: Body validation (Phase 2)**
  - [ ] `email_reply` now validates body is non-empty and non-whitespace
  - [ ] **Impact:** Users passing empty/whitespace-only body will get ValueError
  - [ ] **Classification:** Enhancement with validation (could be considered breaking if users relied on sending empty replies)

### 2b. Draft CHANGELOG.md Entries

- [ ] **Add version heading** (e.g., `## [Unreleased]` or `## [0.3.0] - 2025-10-XX`)

- [ ] **Security section** (highest priority)

  ```markdown
  ### Security
  - **CRITICAL:** Added path traversal protection to all file/folder operations
    - Blocks attempts to access paths outside OneDrive root (../, .\, UNC paths, drive letters)
    - Prevents access to Windows reserved filenames (CON, PRN, AUX, NUL, etc.)
    - All file/folder tools now use `validate_onedrive_path()` validator
  - Added SSRF protection to `file_get` - validates download URLs are from graph.microsoft.com
  - Added file size limit checks to `file_get` before downloading (prevents memory exhaustion)
  ```

- [ ] **Breaking Changes section**

  ```markdown
  ### Breaking Changes
  - **Update dict validation (Phase 3):** Four update tools now reject unknown dictionary keys
    - Affected tools: `email_update`, `calendar_update_event`, `contact_update`, `emailrules_update`
    - See tool docstrings for complete list of allowed keys
    - **Migration:** Remove any invalid/unsupported keys from update_values dict

  - **Limit bounds validation (Phase 3):** 13 tools now enforce strict limit ranges
    - See Phase 3 tasklist for complete limit bounds table
    - **Migration:** Adjust limit parameters to fall within documented ranges (typically 1-200 or 1-500)

  - **Folder name validation (Phase 4):** Email and folder tools now validate folder names
    - Valid folders: inbox, sent, drafts, deleted, junk, archive, outbox
    - **Migration:** Use valid folder names from FOLDERS dict, fix any typos

  - **Body validation (Phase 2):** `email_reply` now requires non-empty body
    - Empty or whitespace-only body will raise ValueError
    - **Migration:** Ensure reply body contains actual content
  ```

- [ ] **Added section** (enhancements and new features)

  ```markdown
  ### Added
  - Created `validators.py` module with 20+ shared validation functions
  - Added `ValidationError` exception class with standardized error messages
  - Added recipient normalization to `email_send` (accepts both str and list for to/cc/bcc)
  - Added attendee validation to calendar operations (normalize, filter empty strings)
  - Added datetime format validation to calendar operations
  - Added response type validation to `calendar_respond_event` (accept/tentative/decline only)
  - Added query validation to search operations (non-empty, non-whitespace)
  - Added entity_types validation to `search_unified`
  ```

- [ ] **Changed section** (refactoring, non-breaking improvements)

  ```markdown
  ### Changed
  - Refactored confirm validation across 7 tools to use shared `require_confirm()` validator
    - Affected tools: email_delete, contact_delete, calendar_delete_event, file_delete, emailrules_delete, email_send, email_reply
    - No behavioral change - all tools already had confirm validation
  - Improved error messages across all validation failures (clearer, more actionable)
  - Added retry logic with exponential backoff to `file_get`
  ```

### 2c. Add Migration Guide (if needed)

- [ ] **Create `MIGRATION.md`** if breaking changes are substantial
  - [ ] Include before/after code examples for each breaking change
  - [ ] Provide migration scripts or recipes where applicable
  - [ ] Document timeline for deprecation warnings (if using phased approach)

### 2d. Verify CHANGELOG Style Compliance

- [ ] **Check against existing CHANGELOG.md format**
  - [ ] Consistent heading levels
  - [ ] Consistent bullet point style
  - [ ] Consistent date format
  - [ ] Consistent version format (semantic versioning)

- [ ] **Ensure clarity and actionability**
  - [ ] Each entry explains WHAT changed
  - [ ] Each breaking change entry explains WHY it's breaking
  - [ ] Each breaking change entry includes migration path

### 2e. Cross-Reference with Issues/PRs

- [ ] **Link to related issues** (if available)
  - [ ] Format: `- Fixed #123: Description`

- [ ] **Link to related PRs** (if using PR-based workflow)
  - [ ] Format: `- [#456](link): Description`

## 3. Update `FILETREE.md` with New `validators.py` Module

### 3a. Current FILETREE.md State Assessment

- [ ] **Line 36: validators.py is already documented as "PLANNED"**
  - [ ] Current entry shows detailed implementation notes (20+ validators, security validators, ValidationError class)
  - [ ] Status needs to change from "PLANNED" to "NEW" or "MODIFIED"
  - [ ] Verify all listed validators are actually implemented

### 3b. Update validators.py Entry

- [ ] **Change status marker** from `**PLANNED**` to `**NEW**`

- [ ] **Update description** to reflect actual implementation

  ```markdown
  ├── validators.py                   # **NEW** Shared validation helpers
  │                                   #   Core validators: require_confirm, normalize_recipients, normalize_attendees
  │                                   #   Validation: validate_response_type, validate_limit, validate_nonempty_string
  │                                   #   Update dict validators: validate_email_update_keys, validate_calendar_update_keys, validate_contact_update_keys, validate_emailrules_update_keys
  │                                   #   Security: validate_onedrive_path, validate_graph_url, validate_microsoft_graph_id
  │                                   #   Datetime: validate_datetime_format, validate_timezone
  │                                   #   Folder: validate_folder_name (uses FOLDERS constant)
  │                                   #   ValidationError exception class with standardized error messages
  │                                   #   Comprehensive unit tests with >95% coverage
  ```

- [ ] **Verify validator count** matches implementation
  - [ ] Count actual validator functions in validators.py
  - [ ] Update description if count differs from "20+ validators"

### 3c. Update Test Directory Entries (if applicable)

- [ ] **Add new test files** if test structure changed
  - [ ] `tests/test_validators.py` - Unit tests for validators module
  - [ ] `tests/unit/` directory - If unit tests were organized into subdirectory
  - [ ] `tests/conftest.py` - If pytest fixtures were added (Critical Path Section 4)

- [ ] **Update test count** in `tests/test_integration.py` description
  - [ ] Current: "34 integration tests exist"
  - [ ] Update if integration tests were added during validation work

### 3d. Verify Tool Module Descriptions Remain Accurate

- [ ] **Check tool counts haven't changed**
  - [ ] account.py: 3 tools ✓
  - [ ] calendar.py: 6 tools ✓
  - [ ] contact.py: 5 tools ✓
  - [ ] email.py: 9 tools ✓
  - [ ] email_folders.py: 3 tools ✓
  - [ ] email_rules.py: 9 tools ✓
  - [ ] file.py: 5 tools ✓
  - [ ] folder.py: 3 tools ✓
  - [ ] search.py: 5 tools ✓
  - [ ] **Total: 50 tools** (unchanged)

- [ ] **Update tool parameter descriptions** if significant
  - [ ] email.py: Note confirm parameter on email_delete, email_send, email_reply
  - [ ] calendar.py: Note confirm parameter on calendar_delete_event
  - [ ] contact.py: Note confirm parameter on contact_delete
  - [ ] file.py: Note confirm parameter on file_delete, security enhancements on file_get
  - [ ] email_rules.py: Note confirm parameter on emailrules_delete

### 3e. Formatting and Consistency Checks

- [ ] **Verify indentation** matches existing FILETREE.md style
  - [ ] Use `│` for continuation lines
  - [ ] Use `├──` for file entries
  - [ ] Use `└──` for last entries in sections

- [ ] **Verify comment alignment** (typically column 37 or after)
  - [ ] All `#` comment markers should align vertically

- [ ] **Verify marker formatting** (e.g., `**NEW**`, `**MODIFIED**`)
  - [ ] Consistent use of bold markers
  - [ ] Consistent capitalization

## 4. Refresh `reports/todo/PARAMETER_VALIDATION.md` with Completion Status

### 4a. Current PARAMETER_VALIDATION.md State

- [ ] **Verify document structure and purpose**
  - [ ] Current document shows "before" state analysis (56% good validation, 44% no validation)
  - [ ] Contains examples of tools with excellent validation and missing validation
  - [ ] This is a point-in-time snapshot, needs "after" state added

### 4b. Add Completion Summary Section

- [ ] **Add new section at top of document**

  ```markdown
  ## Validation Implementation Completion Summary

  **Status:** ✅ Complete (as of [DATE])

  **Phases Completed:**
  - ✅ Critical Path: Security fixes, validators module, test infrastructure
  - ✅ Phase 1: Confirm validation refactored (7 tools)
  - ✅ Phase 2: Dangerous operations validation (6+ tools)
  - ✅ Phase 3: Moderate operations validation (17+ tools)
  - ✅ Phase 4: Safe operations validation (8+ tools)
  - ✅ Testing & Quality: Unit tests, integration tests, >90% coverage
  - ✅ Documentation & Compliance: This phase

  **Coverage Improvement:**
  - Before: 28 tools with good validation (56%)
  - After: 50 tools with excellent validation (100%)
  - Improvement: +22 tools, +44 percentage points

  **Security Enhancements:**
  - Path traversal protection (all file/folder tools)
  - SSRF protection (file_get)
  - File size limits (file_get)
  - Comprehensive input validation (all tools)

  **Breaking Changes:**
  - Update dict key validation (4 tools - Phase 3)
  - Limit bounds validation (13 tools - Phase 3)
  - Folder name validation (2 tools - Phase 4)
  - Body validation (email_reply - Phase 2)

  See CHANGELOG.md for complete migration guide.
  ```

### 4c. Update Validation Coverage Table

- [ ] **Replace "before" table** with "before/after" comparison

  ```markdown
  ### Validation Coverage: Before vs After

  | Metric | Before | After | Improvement |
  |--------|--------|-------|-------------|
  | Tools with good validation | 28 (56%) | 50 (100%) | +22 tools (+44%) |
  | Tools with no validation | 22 (44%) | 0 (0%) | -22 tools (-44%) |
  | Security-critical tools validated | N/A | 50 (100%) | N/A |
  | Shared validators created | 0 | 20+ | +20+ |
  | Test coverage | ~60% | >90% | +30% |
  ```

### 4d. Update "Tools with Missing Validation" Section

- [ ] **Replace ❌ Critical sections with ✅ Completed sections**

- [ ] **Example transformation for delete_email:**

  ```markdown
  ### ✅ Completed: `delete_email` (email.py)

  **Before (Line 573):**
  - No confirm parameter
  - No validation

  **After:**
  - Added confirm parameter with default=False
  - Uses shared require_confirm() validator
  - Clear error message explaining confirm requirement
  - Maintains backward compatibility (Phase 1)

  **Migration Impact:** None - existing behavior preserved, confirm=False triggers same error
  ```

- [ ] **Repeat for all 22 tools** that previously had missing validation
  - [ ] delete_email → ✅ Phase 1 complete
  - [ ] respond_event → ✅ Phase 2 complete
  - [ ] send_email → ✅ Phase 1 & 2 complete (confirm + recipient validation)
  - [ ] reply_to_email → ✅ Phase 1 & 2 complete (confirm + body validation)
  - [ ] update_email → ✅ Phase 3 complete (update dict validation)
  - [ ] list_emails → ✅ Phase 3 & 4 complete (limit + folder validation)
  - [ ] etc.

### 4e. Add "Lessons Learned" Section

- [ ] **Document key insights from implementation**

  ```markdown
  ## Lessons Learned

  ### What Went Well
  - Phased approach allowed incremental progress and testing
  - Shared validators module reduced code duplication significantly
  - Test-driven approach caught edge cases early
  - Tool inventory and categorization was crucial for planning

  ### Challenges Encountered
  - Some tools had overlapping validation concerns across phases
  - Datetime/timezone validation proved more complex than anticipated
  - Windows-specific path validation required extensive research
  - Balancing strict validation with backward compatibility

  ### Future Recommendations
  - Consider adding deprecation warnings for breaking changes
  - Explore schema validation libraries (Pydantic) for complex parameters
  - Add integration tests for validation error scenarios
  - Document validation patterns in contributor guide
  ```

### 4f. Add "Future Enhancements" Section

- [ ] **Document deferred work and future considerations**

  ```markdown
  ## Future Enhancements

  ### Deferred from Phase 4
  - Path validation for file operations (already covered in Critical Path)
  - Advanced query syntax validation for search tools

  ### Potential Future Work
  - Add batch operation validation (validate multiple items at once)
  - Add cross-parameter validation (e.g., start_time < end_time for calendar events)
  - Add async validation for operations requiring API calls (e.g., check email exists before deletion)
  - Add validation rate limiting to prevent abuse
  - Add validation logging/metrics for monitoring validation failures

  ### Performance Optimizations
  - Cache folder name validation results (FOLDERS dict is static)
  - Optimize recipient normalization for large recipient lists
  - Add validation short-circuiting (fail fast on first error)
  ```

### 4g. Verify Line Number Accuracy

- [ ] **Check all line number references** in document
  - [ ] Line numbers may have changed during implementation
  - [ ] Use `grep -n` or editor line numbers to verify accuracy
  - [ ] Update any stale line number references

### 4h. Run Spell Check and Formatting

- [ ] **Spell check entire document**
  - [ ] Use editor spell check or `aspell` command
  - [ ] Pay special attention to technical terms and function names

- [ ] **Verify markdown formatting**
  - [ ] All code blocks have language specifiers
  - [ ] All tables have proper alignment
  - [ ] All links are valid (if any)
  - [ ] All headings follow consistent hierarchy

## 5. Verify Compliance with All Steering Documents

### 5a. Review `.projects/steering/mcp-server.md` Compliance

- [ ] **Single Responsibility Principle (SRP) for Tools**
  - [ ] Verify each tool has exactly one responsibility
  - [ ] Confirm validation logic is delegated to validators module (not inline)

- [ ] **Tool Signature Standards**
  - [ ] All tools have `account_id: str` as first parameter ✓
  - [ ] All tools have complete type annotations ✓
  - [ ] All tools have Google-style docstrings ✓

- [ ] **Security Mandates**
  - [ ] OAuth 2.1 compliance: Token validation (N/A - handled by auth.py)
  - [ ] Least privilege tool design: Tools use minimal required permissions ✓
  - [ ] Input validation: All tools validate all parameters ✅ (this project's goal)

- [ ] **Error Handling and Resilience**
  - [ ] MCP-specific error responses: ValidationError/MCPError used consistently
  - [ ] Graceful degradation: Partial failures handled in batch operations

- [ ] **Performance and Scalability**
  - [ ] Caching strategy: Validators don't cache (stateless by design) ✓
  - [ ] Rate limiting: N/A for validators (handled by graph.py) ✓

- [ ] **Monitoring and Observability**
  - [ ] Structured logging: Validation failures logged with context (check implementation)
  - [ ] Performance monitoring: Validation execution time tracked (check implementation)

### 5b. Review `.projects/steering/python.md` Compliance

- [ ] **PEP 8 Compliance**
  - [ ] Indentation: 4 spaces (no tabs) ✓
  - [ ] Line length: Maximum 79 characters for code, 72 for docstrings
  - [ ] Blank lines: 2 between top-level functions/classes ✓
  - [ ] **Run compliance check:** `uvx ruff check src/microsoft_mcp/validators.py`

- [ ] **Naming Conventions**
  - [ ] Functions: snake_case (validate_onedrive_path, require_confirm, etc.) ✓
  - [ ] Classes: CapWords (ValidationError) ✓
  - [ ] Constants: MACRO_CASE (if any constants defined)

- [ ] **Documentation Standards (PEP 257)**
  - [ ] All validators have Google-style docstrings ✓
  - [ ] All validators have Args, Returns, Raises sections ✓
  - [ ] Summary line uses imperative mood and ends with period ✓

- [ ] **Type Hinting Requirements**
  - [ ] All validator parameters have type annotations ✓
  - [ ] All validator return types annotated ✓
  - [ ] Complex types use proper syntax (str | list[str], dict[str, Any]) ✓
  - [ ] **Run type check:** `uv run pyright src/microsoft_mcp/validators.py`

- [ ] **Error Handling Standards**
  - [ ] Specific exceptions: ValueError, TypeError used appropriately ✓
  - [ ] ValidationError custom exception defined ✓
  - [ ] Error messages: Clear and actionable ✓
  - [ ] Logging: Using Python logging module (verify, not print())

- [ ] **Async and Concurrency**
  - [ ] Validators are synchronous (correct - validation should be fast) ✓
  - [ ] No blocking I/O in validators ✓

### 5c. Review `.projects/steering/structure.md` Compliance

- [ ] **File Organization**
  - [ ] validators.py in correct location: `src/microsoft_mcp/validators.py` ✓
  - [ ] Test files in correct location: `tests/test_validators.py` (verify exists)
  - [ ] No circular dependencies between modules ✓

- [ ] **Module Responsibilities**
  - [ ] validators.py contains ONLY validation logic (no business logic) ✓
  - [ ] Tools import from validators.py (not vice versa) ✓
  - [ ] graph.py and auth.py unchanged (validators don't depend on them) ✓

- [ ] **Testing Structure**
  - [ ] Unit tests: `tests/test_validators.py` (verify exists)
  - [ ] Integration tests: Validation tested through tool integration tests ✓
  - [ ] Fixtures: conftest.py for shared test fixtures (Critical Path Section 4)

### 5d. Review `.projects/steering/tech.md` Compliance

- [ ] **Development Tools**
  - [ ] ruff: Code formatted and linted ✓
  - [ ] **Run:** `uvx ruff format src/microsoft_mcp/validators.py`
  - [ ] **Run:** `uvx ruff check --fix --unsafe-fixes src/microsoft_mcp/validators.py`

- [ ] **Testing Tools**
  - [ ] pytest: Unit tests written for all validators ✓
  - [ ] pytest-asyncio: N/A (validators are synchronous) ✓
  - [ ] **Run:** `uv run pytest tests/test_validators.py -v`

- [ ] **Type Checking**
  - [ ] pyright: All validators type-checked ✓
  - [ ] **Run:** `uv run pyright src/microsoft_mcp/validators.py`

- [ ] **Code Quality Targets**
  - [ ] Test coverage: >95% for validators.py (Critical Path requirement) ✓
  - [ ] **Run:** `uv run pytest tests/test_validators.py --cov=src/microsoft_mcp/validators --cov-report=term-missing`

### 5e. Review `.projects/steering/tool-names.md` Compliance

- [ ] **Safety Annotations**
  - [ ] All tools have correct FastMCP annotations (readOnlyHint, destructiveHint) ✓
  - [ ] All tools have correct meta.safety_level ✓
  - [ ] Critical operations have confirm=True parameter requirement ✓

- [ ] **Description Guidelines**
  - [ ] All tools have emoji indicators matching safety level ✓
  - [ ] 📖 Safe (read-only)
  - [ ] ✏️ Moderate (write/modify)
  - [ ] 📧 Dangerous (send operations)
  - [ ] 🔴 Critical (delete operations)

- [ ] **Validation Requirement**
  - [ ] Critical operations MUST include confirm=True parameter ✅
  - [ ] confirm parameter uses shared require_confirm() validator ✅

### 5f. Review `.projects/steering/product.md` Compliance

- [ ] **Enterprise-grade Performance**
  - [ ] Validation optimized for large mailboxes (no O(n²) algorithms) ✓
  - [ ] Validation doesn't block on I/O operations ✓

- [ ] **Intelligent Automation**
  - [ ] Validation errors are actionable (tell user what to fix) ✓
  - [ ] Validation normalizes inputs where sensible (recipients, attendees) ✓

- [ ] **Comprehensive API Coverage**
  - [ ] All 50 tools have parameter validation ✅
  - [ ] No tool left without validation ✅

### 5g. Run All Compliance Checks

- [ ] **Quality Gate Commands** (from Testing & Quality tasklist)

  ```bash
  # Type checking
  uv run pyright

  # Code formatting (auto-fix)
  uvx ruff format .

  # Linting (auto-fix)
  uvx ruff check --fix --unsafe-fixes .

  # Test execution
  uv run pytest tests/ -v --cov=src/microsoft_mcp --cov-report=term-missing

  # Coverage threshold check (must be >90%)
  uv run pytest tests/ --cov=src/microsoft_mcp --cov-fail-under=90
  ```

- [ ] **Document results of compliance checks**
  - [ ] pyright: 0 errors, 0 warnings
  - [ ] ruff format: 0 files changed
  - [ ] ruff check: 0 violations
  - [ ] pytest: 100% pass rate
  - [ ] coverage: >90% overall, >95% validators.py

### 5h. Document Compliance Findings

- [ ] **Create compliance report** for PR summary

  ```markdown
  ## Compliance Verification Results

  ### Steering Document Compliance
  - ✅ mcp-server.md: All requirements met
  - ✅ python.md: PEP 8, PEP 257, type hints compliant
  - ✅ structure.md: File organization correct
  - ✅ tech.md: All quality tools passing
  - ✅ tool-names.md: Safety annotations correct
  - ✅ product.md: Enterprise-grade performance maintained

  ### Quality Gate Results
  - ✅ pyright: 0 errors
  - ✅ ruff format: No changes needed
  - ✅ ruff check: 0 violations
  - ✅ pytest: [X]/[X] tests passing (100%)
  - ✅ coverage: [X]% overall, [X]% validators.py

  ### Security Verification
  - ✅ Path traversal protection implemented
  - ✅ SSRF protection implemented
  - ✅ Input validation comprehensive
  - ✅ No security regressions introduced

  ### Backward Compatibility
  - ✅ confirm parameter maintains backward compatibility (default=False)
  - ⚠️ Breaking changes documented in CHANGELOG.md
  - ✅ Migration guide provided for breaking changes
  ```

- [ ] **Address any compliance gaps**
  - [ ] If pyright errors found: Fix type annotations
  - [ ] If ruff violations found: Fix code style issues
  - [ ] If tests failing: Fix test failures or implementation bugs
  - [ ] If coverage below threshold: Add more tests

## Cross-Cutting Documentation Tasks

### Timing and Coordination

- [ ] **Coordinate documentation with code merges**
  - [ ] Update documentation in same PR as code changes (not separate PRs)
  - [ ] Review documentation for staleness before merge
  - [ ] Ensure all code references (line numbers, function names) are accurate

### Review Process

- [ ] **Documentation review checklist**
  - [ ] Technical accuracy: All code examples tested and working
  - [ ] Consistency: Terminology consistent across all docs
  - [ ] Completeness: All changes documented, no gaps
  - [ ] Clarity: Documentation understandable by target audience

### User-Facing Documentation Updates

- [ ] **Review and update README.md** (if validation changes user workflows)
  - [ ] Update "Features" section if new validation capabilities added
  - [ ] Update "Usage" examples to show confirm parameter usage
  - [ ] Add "Breaking Changes" section if needed
  - [ ] Update "Testing" section if test structure changed

- [ ] **Review and update QUICKSTART.md** (if validation changes setup/usage)
  - [ ] Update "First Steps" if validation affects initial use
  - [ ] Update examples to match new validation behavior
  - [ ] Add troubleshooting section for common validation errors

- [ ] **Review and update SECURITY.md** (if validation adds security features)
  - [ ] Document path traversal protection
  - [ ] Document SSRF protection
  - [ ] Document input validation security benefits
  - [ ] Update threat model if applicable

- [ ] **Review and update CLAUDE.md** (if validation affects AI assistant guidance)
  - [ ] Update "Common Patterns" with validation examples
  - [ ] Update "Important Notes" if validation changes behavior
  - [ ] Add validation best practices section

### Stakeholder Communication

- [ ] **Prepare release notes** summarizing validation improvements
  - [ ] Executive summary (2-3 sentences)
  - [ ] Security improvements highlight
  - [ ] Breaking changes summary with migration guide link
  - [ ] Full changeset reference (link to CHANGELOG.md)

- [ ] **Notify stakeholders** of documentation updates
  - [ ] Team members: Share updated docs location
  - [ ] Users: Release notes via appropriate channel
  - [ ] Contributors: Update contributor guide if validation patterns established

### Final Verification

- [ ] **End-to-end documentation test**
  - [ ] Follow README instructions from scratch (fresh clone)
  - [ ] Verify all links work (internal and external)
  - [ ] Verify all code examples execute correctly
  - [ ] Verify all screenshots/diagrams are up-to-date (if any)

- [ ] **Accessibility check**
  - [ ] All markdown is valid and renders correctly
  - [ ] All code blocks have language specifiers
  - [ ] All tables are properly formatted
  - [ ] All images have alt text (if any)

---

## Documentation & Compliance Completion Checklist

Before marking Documentation & Compliance phase as complete, verify:

- [ ] ✅ Section 1 Complete: All tool docstrings updated with validation details
- [ ] ✅ Section 2 Complete: CHANGELOG.md updated with breaking changes and migration guide
- [ ] ✅ Section 3 Complete: FILETREE.md updated with validators.py status change
- [ ] ✅ Section 4 Complete: PARAMETER_VALIDATION.md refreshed with completion status
- [ ] ✅ Section 5 Complete: All steering document compliance verified
- [ ] ✅ Cross-Cutting Tasks Complete: All user-facing docs updated
- [ ] ✅ Quality Gates Passing: pyright, ruff, pytest all green
- [ ] ✅ Compliance Report: Created and reviewed
- [ ] ✅ PR Summary: Drafted with all documentation changes listed

**Final Sign-Off:** All documentation is accurate, complete, and ready for merge.
