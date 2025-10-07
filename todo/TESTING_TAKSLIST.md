# Testing & Quality Tasklist

Comprehensive checklist to ensure validation implementation ships with full test coverage and quality assurance across all phases.

## ⚠️ Important Context

**Testing Runs Throughout All Phases:**

- This is NOT a separate phase - testing happens **during** Phases 1-4
- Each phase has phase-specific testing requirements
- This tasklist covers **cross-phase** testing infrastructure and final validation

**Current Test Infrastructure:**

- ✅ **Integration tests exist:** `tests/test_integration.py` (34 tests)
- ❌ **No conftest.py yet:** Need to create fixtures (Critical Path Section 4)
- ❌ **No unit tests yet:** Need module-specific test files
- ❌ **No validator tests yet:** Part of Critical Path Section 5

**Testing Strategy:**

1. **Critical Path Section 5:** Create validator unit tests (100% coverage target)
2. **Phase-specific testing:** Each phase adds tool-specific validation tests
3. **Cross-phase testing:** This tasklist - integration, regression, coverage goals
4. **Final quality gate:** All phases complete, full suite passing

## Prerequisites (MUST Complete Before Final Testing)

- [ ] **Critical Path Section 4 Complete:** `tests/conftest.py` exists with fixtures
  - [ ] `mock_graph_request` - Mock Graph API calls
  - [ ] `mock_account_id` - Test account fixture
  - [ ] Data factories (email, file, calendar, contact)
  - [ ] File system fixtures (`temp_safe_dir`)
- [ ] **Critical Path Section 5 Complete:** Validator tests at 100% coverage
- [ ] **Phases 1-4 Implementation:** Each phase includes tool-specific tests
  - [ ] Phase 1: Confirm validation tests (7 tools)
  - [ ] Phase 2: Recipient/body/response/attendee tests
  - [ ] Phase 3: Update dict, limit, datetime tests
  - [ ] Phase 4: Folder/query/path tests

## 1. Create Module-Specific Validation Tests (9 Test Files)

**Current State:**

- ✅ Integration tests exist: `tests/test_integration.py` (34 tests, end-to-end)
- ❌ No unit tests for tools yet
- ❌ No validation-specific tests yet

**Testing Architecture Decision:**

- **Option 1:** Separate validation test files (`test_<module>_validation.py`)
- **Option 2:** Combined tool test files (`test_<module>.py` covering all tool functionality)
- **Recommendation:** **Option 2** - Simpler structure, validation is part of tool behavior

**File Structure:**

```
tests/
├── conftest.py (fixtures - from Critical Path Section 4)
├── test_validators.py (100% validator coverage - from Critical Path Section 5)
├── test_integration.py (existing - end-to-end tests)
└── tools/ (NEW - unit tests per module)
    ├── test_account.py
    ├── test_calendar.py
    ├── test_contact.py
    ├── test_email.py
    ├── test_email_folders.py
    ├── test_email_rules.py
    ├── test_file.py
    ├── test_folder.py
    └── test_search.py
```

### 1a. Test File Creation Strategy

**For each module file, include:**

1. **Validation tests** - Parameter validation (what this program adds)
2. **Business logic tests** - Tool functionality
3. **Error handling tests** - Graph API errors, edge cases
4. **Integration points** - Validator usage, Graph client calls

**Test Organization Pattern:**

```python
# tests/tools/test_email.py

import pytest
from unittest.mock import Mock, patch
from microsoft_mcp.tools.email import email_send, email_delete, email_list

class TestEmailSend:
    """Tests for email_send tool"""

    def test_valid_recipients(self, mock_graph_request, mock_account_id):
        """Test email_send with valid recipients"""
        # Positive path

    def test_invalid_recipients_empty(self, mock_account_id):
        """Test email_send rejects empty recipient list"""
        with pytest.raises(ValueError, match="At least one recipient required"):
            email_send(mock_account_id, to=[], subject="Test", body="Test", confirm=True)

    def test_recipient_deduplication(self, mock_graph_request, mock_account_id):
        """Test email_send deduplicates recipients"""
        # Validation logic test

class TestEmailDelete:
    """Tests for email_delete tool"""

    def test_confirm_required(self, mock_account_id):
        """Test email_delete requires confirm=True"""
        with pytest.raises(ValueError, match="confirmation"):
            email_delete("email123", mock_account_id, confirm=False)
```

### 1b. Module-Specific Test Requirements

**Phase-aligned approach:** Tests created **during** phase implementation, not after

#### Account Module (`test_account.py`) - Phase 1

- [ ] `list_accounts` - Returns account list
- [ ] `authenticate_account` - Device flow validation (if applicable)
- [ ] `complete_authentication` - Flow cache parsing

#### Calendar Module (`test_calendar.py`) - Phases 2 & 3

- [ ] **Phase 2:** `calendar_create_event` - Attendee validation, datetime validation, timezone validation
- [ ] **Phase 2:** `calendar_check_availability` - DateTime window validation
- [ ] **Phase 1:** `calendar_delete_event` - Confirm validation (refactoring)
- [ ] **Phase 3:** `calendar_update_event` - Update dict validation, datetime in updates
- [ ] **Phase 2:** `calendar_respond_event` - Response enum validation

#### Contact Module (`test_contact.py`) - Phases 1 & 3

- [ ] **Phase 1:** `contact_delete` - Confirm validation (refactoring)
- [ ] **Phase 3:** `contact_update` - Update dict validation, email format in updates
- [ ] `contact_create` - Email validation for emailAddresses parameter
- [ ] `contact_list` - **Phase 3:** Limit validation

#### Email Module (`test_email.py`) - Phases 1, 2, 3, 4

- [ ] **Phase 2:** `email_send` - Recipient validation, deduplication
- [ ] **Phase 2:** `email_reply` - Body validation (non-empty)
- [ ] **Phase 1:** `email_delete` - Confirm validation (refactoring)
- [ ] **Phase 3:** `email_update` - Update dict validation (isRead, categories, etc.)
- [ ] **Phase 3:** `email_list` - Limit validation (1-200)
- [ ] **Phase 3:** `email_get` - body_max_length validation
- [ ] **Phase 4:** `email_list` - Folder choice validation
- [ ] **Phase 4:** `email_move` - Folder choice validation

#### Email Folders Module (`test_email_folders.py`) - Phase 3

- [ ] **Phase 3:** `emailfolders_list` - Limit validation (1-250)
- [ ] **Phase 3:** `emailfolders_get_tree` - max_depth validation (1-25)

#### Email Rules Module (`test_email_rules.py`) - Phases 1 & 3

- [ ] **Phase 1:** `emailrules_delete` - Confirm validation (refactoring)
- [ ] **Phase 3:** `emailrules_update` - Update dict validation, sequence validation

#### File Module (`test_file.py`) - Phases 1, 3, 4

- [ ] **Phase 1:** `file_delete` - Confirm validation (refactoring)
- [ ] **Critical Path:** `file_get` - URL validation, path validation, file size limits
- [ ] **Phase 3:** `file_list` - Limit validation (1-500)
- [ ] **Phase 4:** `file_list` - Path validation (optional)

#### Folder Module (`test_folder.py`) - Phases 3 & 4

- [ ] **Phase 3:** `folder_list` - Limit validation (1-500)
- [ ] **Phase 3:** `folder_get_tree` - max_depth validation (1-25)
- [ ] **Phase 4:** `folder_list`, `folder_get` - Path validation (optional)

#### Search Module (`test_search.py`) - Phases 3 & 4

- [ ] **Phase 3:** All search tools - Limit validation (1-500)
- [ ] **Phase 3:** `search_events` - days_ahead/days_back validation (0-730)
- [ ] **Phase 4:** All search tools - Query validation (non-empty, length)
- [ ] **Phase 4:** `search_unified` - Entity type validation
- [ ] **Phase 4:** `search_emails` - Folder choice validation (optional)

### 1c. Test Implementation Guidelines

**Validation Test Pattern:**

```python
@pytest.mark.parametrize("invalid_input,expected_error", [
    ("", "cannot be empty"),
    ("   ", "whitespace-only"),
    ("x" * 1001, "too long"),
])
def test_query_validation(invalid_input, expected_error):
    """Test search query validation"""
    with pytest.raises(ValueError, match=expected_error):
        search_files(invalid_input, "account123", limit=50)
```

**Mock Pattern:**

```python
def test_email_send_success(mock_graph_request, mock_account_id):
    """Test successful email send"""
    mock_graph_request.return_value = {"id": "message123", "status": "sent"}

    result = email_send(
        mock_account_id,
        to="user@example.com",
        subject="Test",
        body="Test body",
        confirm=True
    )

    assert result["status"] == "sent"
    mock_graph_request.assert_called_once()
```

### 1d. Test Coverage Targets

**Per-module coverage goals:**

- **Validators module:** 100% (Critical Path Section 5)
- **Tool modules:** ≥90% (validation + business logic)
- **Integration tests:** Maintain existing coverage (34 tests)

**Total target:** >90% across entire `src/microsoft_mcp/` codebase

## 2. Run Full Quality Gate: pyright, ruff format, ruff check, pytest

**Quality Gate Runs:**

- **During development:** After each tool/validator implementation
- **Before PR:** Full suite before submitting pull request
- **In CI:** Automated checks on push/PR (if configured)

### 2a. Quality Gate Command Sequence

**Standard workflow (run in project root):**

```bash
# 1. Type checking
uv run pyright

# 2. Format code (auto-fix)
uvx ruff format .

# 3. Lint and auto-fix issues
uvx ruff check --fix --unsafe-fixes .

# 4. Run tests with coverage
uv run pytest tests/ -v --cov=src/microsoft_mcp --cov-report=term-missing

# 5. Run integration tests (requires auth)
uv run pytest tests/test_integration.py -v
```

**Quick validation check (before commit):**

```bash
# Fast check without fixes
uvx ruff format --check . && \
uvx ruff check . && \
uv run pyright && \
uv run pytest tests/ -v
```

### 2b. Command-Specific Guidelines

#### **pyright (Type Checking)**

- [ ] **Zero errors required** - All type errors must be resolved
- [ ] **Address warnings** - Type hints should be complete
- [ ] **Common issues:**
  - Missing return type annotations
  - `Any` type overuse (prefer specific types)
  - Incorrect Union/Optional usage
- [ ] **Fix pattern:**

  ```python
  # Before
  def email_send(account_id, to, subject, body):
      return result

  # After
  def email_send(
      account_id: str,
      to: str | list[str],
      subject: str,
      body: str
  ) -> dict[str, Any]:
      return result
  ```

#### **ruff format (Code Formatting)**

- [ ] **Auto-applies PEP 8 formatting** - No manual action needed
- [ ] **Consistent across codebase** - All files use same style
- [ ] **Run before commit** - Avoid formatting-only commits

#### **ruff check (Linting)**

- [ ] **Fix all errors** - Red violations must be resolved
- [ ] **Address warnings** - Yellow warnings should be fixed
- [ ] **Common issues:**
  - Unused imports (`F401`)
  - Undefined names (`F821`)
  - Line too long (`E501`) - ruff format handles this
  - Unused variables (`F841`)
- [ ] **Use `--fix`** - Auto-fixes safe issues
- [ ] **Use `--unsafe-fixes`** - Auto-fixes potentially unsafe issues (review diffs)

#### **pytest (Testing)**

- [ ] **All tests must pass** - Green status required
- [ ] **Coverage threshold:** >90% for validation code
- [ ] **Run specific tests during development:**

  ```bash
  # Test single module
  uv run pytest tests/tools/test_email.py -v

  # Test specific function
  uv run pytest tests/tools/test_email.py::TestEmailSend::test_valid_recipients -v

  # Test by keyword
  uv run pytest tests/ -k "email_send" -v
  ```

### 2c. Quality Gate Failure Handling

**Issue Triage Process:**

1. **Categorize failure:** Type error, lint error, test failure
2. **Locate root cause:** Review error message and stack trace
3. **Fix immediately:** Don't accumulate errors
4. **Re-run gate:** Verify fix resolved issue
5. **Document if complex:** Add comment explaining non-obvious fixes

**Common Failure Patterns:**

| Failure | Cause | Fix |
|---------|-------|-----|
| `pyright: Type[X] is not assignable to Type[Y]` | Type mismatch | Add proper type hints or cast |
| `ruff: F401 'foo' imported but unused` | Unused import | Remove import or use `# noqa: F401` if needed |
| `pytest: ValueError: Invalid folder` | Validation test expectation wrong | Update test to match actual error message |
| `pytest: AssertionError: assert mock called` | Mock not called as expected | Check function implementation, adjust mock setup |

### 2d. Automation Script (Optional)

**Create `scripts/quality_gate.sh`:**

```bash
#!/bin/bash
set -e  # Exit on first error

echo "🔍 Running type checking..."
uv run pyright

echo "🎨 Formatting code..."
uvx ruff format .

echo "🔧 Linting code..."
uvx ruff check --fix --unsafe-fixes .

echo "🧪 Running tests with coverage..."
uv run pytest tests/ -v --cov=src/microsoft_mcp --cov-report=term-missing

echo "✅ Quality gate passed!"
```

Make executable: `chmod +x scripts/quality_gate.sh`

Usage: `./scripts/quality_gate.sh`

## 3. Verify No Regressions in Existing Integration Tests

**Current Integration Tests:** `tests/test_integration.py` (34 tests)

- End-to-end tests using actual MCP server via stdio
- Requires `MICROSOFT_MCP_CLIENT_ID` environment variable
- Requires at least one authenticated account

**Integration Test Strategy:**

- **Run after each phase** - Verify no breaking changes
- **Maintain existing coverage** - Don't break what works
- **Add validation scenarios** - Extend integration tests for validation edge cases

### 3a. Integration Test Execution

**Standard execution:**

```bash
# Ensure environment variables set
export MICROSOFT_MCP_CLIENT_ID="your-client-id"

# Run integration tests
uv run pytest tests/test_integration.py -v

# Run with detailed output
uv run pytest tests/test_integration.py -vv -s
```

**Expected result:** All 34 tests pass (or more if new tests added)

### 3b. Regression Analysis Checklist

**After each phase implementation:**

- [ ] **Phase 1 (Confirm refactoring):**
  - [ ] Integration tests for delete operations still pass (just use confirm=True)
  - [ ] No changes to external behavior (only internal refactoring)
- [ ] **Phase 2 (Recipient/body/datetime validation):**
  - [ ] Integration tests provide valid inputs → should still pass
  - [ ] Tests with invalid inputs should fail with helpful errors
- [ ] **Phase 3 (Update dict/limit validation):**
  - [ ] Integration tests use valid update dicts → should pass
  - [ ] Limit parameters within range → should pass
- [ ] **Phase 4 (Folder/query/path validation):**
  - [ ] Integration tests use valid folders/queries → should pass

### 3c. Handling Integration Test Failures

**Failure Investigation Process:**

1. **Identify which test failed** - Read test name and error message
2. **Determine if breaking change** - Is failure due to stricter validation?
3. **Evaluate fix approach:**
   - **Option A:** Update test to provide valid inputs (if validation is correct)
   - **Option B:** Adjust validation (if too strict/incorrect)
   - **Option C:** Add backward compatibility (if breaking users)

**Example scenarios:**

| Failure | Cause | Fix |
|---------|-------|-----|
| `test_email_send` fails | Now requires valid email format | Update test to use valid email addresses |
| `test_calendar_create` fails | Timezone validation too strict | Relax validation or update test with valid timezone |
| `test_contact_update` fails | Update dict rejects unknown key | Remove unknown key from test or add to allowed keys |

### 3d. Adding New Integration Scenarios

**When to add integration tests:**

- New validation catches important edge case
- End-to-end scenario not covered by unit tests
- Cross-tool interaction needs verification

**Example: Add confirm validation integration test:**

```python
async def test_delete_requires_confirm(session):
    """Verify delete operations require confirm=True"""
    accounts = parse_result(await session.call_tool("account_list"))
    account_id = accounts[0]["account_id"]

    # Should fail without confirm
    with pytest.raises(Exception, match="confirmation"):
        await session.call_tool("email_delete", {
            "email_id": "test123",
            "account_id": account_id,
            "confirm": False
        })

    # Should succeed with confirm=True (if email exists)
    # Note: May still fail if email doesn't exist, but different error
```

## 4. Achieve >90% Validation Coverage Across All Tools

**Coverage Goal:** >90% across entire `src/microsoft_mcp/` codebase

- **Critical:** 100% for `validators.py` (Critical Path Section 5)
- **High:** >90% for tool modules (validation + business logic)
- **Maintain:** Existing coverage for `auth.py`, `graph.py`, `server.py`

### 4a. Coverage Configuration

**pytest.ini or pyproject.toml:**

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = [
    "-v",
    "--cov=src/microsoft_mcp",
    "--cov-report=term-missing",
    "--cov-report=html:htmlcov",
    "--cov-fail-under=90"
]
```

**Command-line usage:**

```bash
# Generate coverage report
uv run pytest tests/ --cov=src/microsoft_mcp --cov-report=term-missing

# Generate HTML report (opens in browser)
uv run pytest tests/ --cov=src/microsoft_mcp --cov-report=html
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux

# Fail if coverage below threshold
uv run pytest tests/ --cov=src/microsoft_mcp --cov-fail-under=90
```

### 4b. Coverage Gap Analysis

**Read coverage report:**

```
Name                                    Stmts   Miss  Cover   Missing
---------------------------------------------------------------------
src/microsoft_mcp/validators.py          150      0   100%
src/microsoft_mcp/tools/email.py          320     35    89%   45-48, 102-105
src/microsoft_mcp/tools/calendar.py       180     20    89%   67-70, 134-140
---------------------------------------------------------------------
TOTAL                                    2000    180    91%
```

**Identify gaps:**

- **Missing lines** - Which code paths not covered?
- **Uncovered branches** - Which if/else not tested?
- **Edge cases** - Boundary values, error paths?

**Common coverage gaps:**

```python
# Gap: Error handling not tested
try:
    result = graph.request(...)
except GraphAPIError as e:  # <-- Not covered
    logger.error(f"Failed: {e}")  # <-- Not covered
    raise  # <-- Not covered

# Fix: Add error test
def test_email_send_graph_error(mock_graph_request, mock_account_id):
    """Test email_send handles Graph API errors"""
    mock_graph_request.side_effect = GraphAPIError("Rate limit")

    with pytest.raises(GraphAPIError):
        email_send(mock_account_id, to="test@example.com", ...)
```

### 4c. Coverage Monitoring

**Per-phase coverage targets:**

- **After Critical Path:** 100% validators.py, conftest.py setup
- **After Phase 1:** ≥85% (7 tools refactored)
- **After Phase 2:** ≥88% (additional validation on 6+ tools)
- **After Phase 3:** ≥90% (systematic validation across 17+ tools)
- **After Phase 4:** ≥90% maintained (final validation polish)

**Coverage tracking:**

```bash
# Before phase
uv run pytest tests/ --cov=src/microsoft_mcp --cov-report=term | grep TOTAL

# After phase
uv run pytest tests/ --cov=src/microsoft_mcp --cov-report=term | grep TOTAL

# Compare: Did coverage increase?
```

## Testing Completion Checklist

- [ ] **Critical Path Testing:**
  - [ ] conftest.py created with all fixtures ✓
  - [ ] test_validators.py at 100% coverage ✓

- [ ] **Phase-Specific Testing:**
  - [ ] Phase 1: 7 tools tested (confirm validation refactoring) ✓
  - [ ] Phase 2: 6+ tools tested (recipient, body, response, attendee) ✓
  - [ ] Phase 3: 17+ tools tested (update dict, limit, datetime) ✓
  - [ ] Phase 4: 8+ tools tested (folder, query, path) ✓

- [ ] **Module Test Files Created:**
  - [ ] tests/tools/test_account.py ✓
  - [ ] tests/tools/test_calendar.py ✓
  - [ ] tests/tools/test_contact.py ✓
  - [ ] tests/tools/test_email.py ✓
  - [ ] tests/tools/test_email_folders.py ✓
  - [ ] tests/tools/test_email_rules.py ✓
  - [ ] tests/tools/test_file.py ✓
  - [ ] tests/tools/test_folder.py ✓
  - [ ] tests/tools/test_search.py ✓

- [ ] **Quality Gate:**
  - [ ] All pyright checks pass ✓
  - [ ] All ruff formatting applied ✓
  - [ ] All ruff linting checks pass ✓
  - [ ] All pytest unit tests pass ✓
  - [ ] All integration tests pass ✓

- [ ] **Coverage:**
  - [ ] validators.py at 100% coverage ✓
  - [ ] Tool modules at ≥90% coverage ✓
  - [ ] Overall codebase at >90% coverage ✓

- [ ] **Documentation:**
  - [ ] Coverage metrics documented ✓
  - [ ] Test patterns documented ✓
  - [ ] Regression test results noted ✓

## Validation Program Testing Summary

**Testing integrated throughout implementation:**

- **Not a separate phase** - Testing happens during Phases 1-4
- **100% validator coverage** - Critical Path ensures validation quality
- **≥90% tool coverage** - Comprehensive testing across all 50 tools
- **No regressions** - All 34 integration tests maintained
- **Quality gates** - pyright, ruff, pytest enforced throughout

**Final validation:** All phases complete with full test coverage! 🎉
