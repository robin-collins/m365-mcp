# Phase 1 Tasklist — Critical Operations (Destructive)

Granular checklist to **refactor existing confirmation validation** to use shared validators across all critical and dangerous tools before proceeding to later phases.

## ⚠️ Important Context

**Current State:** All tools in this phase **ALREADY HAVE** confirm parameter validation implemented:

- ✅ `confirm: bool = False` parameter exists
- ✅ Manual inline validation (`if not confirm: raise ValueError(...)`)
- ✅ Consistent error messages
- ✅ Proper metadata (`requires_confirmation: True`, `destructiveHint: True`)

**Phase 1 Goal:** **REFACTOR** existing inline validation to use shared validators from `validators.py` for consistency and maintainability.

**NOT in Scope for Phase 1:**

- Additional parameter validation (limits, emails, dates) → Phase 2-4
- New confirm parameters on tools that don't have them → Future enhancement

## Prerequisites (MUST Complete Before Starting Phase 1)

- [ ] **Critical Path Section 3 Complete:** `src/microsoft_mcp/validators.py` exists and is tested
  - [ ] `require_confirm(confirm: bool, action: str) -> None` validator implemented
  - [ ] `validate_confirmation_flag(confirm: bool, operation: str, resource_type: str) -> None` validator implemented
  - [ ] 100% test coverage for confirmation validators achieved
  - [ ] Validators follow standard error message format
- [ ] **Critical Path Section 4 Complete:** `tests/conftest.py` has necessary fixtures
  - [ ] `mock_graph_request` fixture available
  - [ ] `mock_account_id` fixture available
- [ ] **Critical Path Section 5 Complete:** Validator tests passing
  - [ ] All confirmation validator tests passing
  - [ ] No regressions in existing tests

## Phase Scope

**Phase 1 includes:**

1. **Critical Operations (Delete):** 5 tools
   - email_delete, file_delete, contact_delete, calendar_delete_event, emailrules_delete
2. **Dangerous Operations (Send/Reply):** 2 tools
   - email_send, email_reply (both already have confirm validation)

**Total:** 7 tools to refactor in Phase 1

## 1. Refactor `email_delete` to Use Shared Validator

**Current Implementation:** `src/microsoft_mcp/tools/email.py:487-511`

- ✅ Has `confirm: bool = False` parameter
- ✅ Has inline validation: `if not confirm: raise ValueError(...)`
- ✅ Has proper metadata and docstring

**Task:** Replace inline validation with shared `require_confirm()` helper

- [ ] **Context Review**
  - [ ] **Review current implementation** at email.py:487-511
  - [ ] **Document current error message** for comparison: `"Deletion requires explicit confirmation. Set confirm=True to proceed. This action cannot be undone."`
  - [ ] **Identify existing tests** in test suite that cover email_delete
  - [ ] **Search for callers** of email_delete in codebase (should find integration tests only)
- [ ] **Refactoring Implementation**
  - [ ] **Import validator:** Add `from ..validators import require_confirm` at top of email.py
  - [ ] **Replace inline check:** Change `if not confirm: raise ValueError(...)` to `require_confirm(confirm, "delete email")`
  - [ ] **Verify error message consistency:** Ensure new validator error message matches or improves upon original
  - [ ] **Preserve all existing behavior:** Same signature, same return type, same Graph API call
- [ ] **Testing Updates**
  - [ ] **Update existing tests** to verify validator integration (not "add" new tests)
  - [ ] **Regression test:** Verify error message format unchanged or documented as improved
  - [ ] **Mock verification:** Ensure Graph DELETE only called when confirm=True
  - [ ] **Negative test:** Verify confirm=False raises expected ValidationError
- [ ] **Documentation**
  - [ ] **Docstring:** Verify docstring still accurate (should not need changes)
  - [ ] **Raises section:** Verify ValidationError documented (or ValueError if validator uses that)
- [ ] **Quality Gate**
  - [ ] **Run:** `uvx ruff format src/microsoft_mcp/tools/email.py`
  - [ ] **Run:** `uvx ruff check src/microsoft_mcp/tools/email.py`
  - [ ] **Run:** `uv run pyright src/microsoft_mcp/tools/email.py`
  - [ ] **Run:** `uv run pytest tests/ -k email_delete -v`

## 2. Refactor `file_delete` to Use Shared Validator

**Current Implementation:** `src/microsoft_mcp/tools/file.py:229-253`

- ✅ Has `confirm: bool = False` parameter
- ✅ Has inline validation: `if not confirm: raise ValueError(...)`
- ✅ Has proper metadata and docstring
- ⚠️ Note: Will integrate with path validation from Critical Path Section 2

**Task:** Replace inline validation with shared `require_confirm()` helper

- [ ] **Context Review**
  - [ ] **Review current implementation** at file.py:229-253
  - [ ] **Document current error message:** `"Deletion requires explicit confirmation. Set confirm=True to proceed. This action cannot be undone."`
  - [ ] **Identify existing tests** for file_delete
  - [ ] **Note path traversal protection** integration point (Critical Path Section 2)
- [ ] **Refactoring Implementation**
  - [ ] **Import validator:** Add `from ..validators import require_confirm` at top of file.py
  - [ ] **Replace inline check:** Change validation to `require_confirm(confirm, "delete file/folder")`
  - [ ] **Verify error message consistency**
  - [ ] **Preserve behavior:** Same signature, return type, Graph API call
  - [ ] **Coordinate with path validation:** Ensure confirm check happens BEFORE Graph API call
- [ ] **Testing Updates**
  - [ ] **Update existing tests** to verify validator integration
  - [ ] **Regression test:** Error message consistency
  - [ ] **Mock verification:** Graph DELETE only called when confirm=True
  - [ ] **Integration test:** Works with path traversal protection from Critical Path
- [ ] **Documentation**
  - [ ] **Docstring:** Verify still accurate (already has good folder deletion warning)
  - [ ] **Raises section:** Update if validator uses different exception type
- [ ] **Quality Gate**
  - [ ] **Run:** `uvx ruff format src/microsoft_mcp/tools/file.py`
  - [ ] **Run:** `uvx ruff check src/microsoft_mcp/tools/file.py`
  - [ ] **Run:** `uv run pyright src/microsoft_mcp/tools/file.py`
  - [ ] **Run:** `uv run pytest tests/ -k file_delete -v`

## 3. Refactor `contact_delete` to Use Shared Validator

**Current Implementation:** `src/microsoft_mcp/tools/contact.py:179-201`

- ✅ Has `confirm: bool = False` parameter
- ✅ Has inline validation: `if not confirm: raise ValueError(...)`
- ✅ Has proper metadata and docstring

**Task:** Replace inline validation with shared `require_confirm()` helper

- [ ] **Context Review & Implementation**
  - [ ] Review contact.py:179-201, document error message
  - [ ] Import validator: `from ..validators import require_confirm`
  - [ ] Replace inline check: `require_confirm(confirm, "delete contact")`
- [ ] **Testing & Quality**
  - [ ] Update existing tests, verify error message consistency
  - [ ] Run: `uvx ruff format src/microsoft_mcp/tools/contact.py`
  - [ ] Run: `uvx ruff check src/microsoft_mcp/tools/contact.py`
  - [ ] Run: `uv run pyright src/microsoft_mcp/tools/contact.py`
  - [ ] Run: `uv run pytest tests/ -k contact_delete -v`

## 4. Refactor `calendar_delete_event` to Use Shared Validator

**Current Implementation:** `src/microsoft_mcp/tools/calendar.py:169-199`

- ✅ Has `confirm: bool = False` parameter
- ✅ Has inline validation: `if not confirm: raise ValueError(...)`
- ✅ Has proper metadata and docstring
- ⚠️ Special logic: Has both cancel (POST) and delete (DELETE) branches based on `send_cancellation`

**Task:** Replace inline validation with shared `require_confirm()` helper

- [ ] **Context Review & Implementation**
  - [ ] Review calendar.py:169-199, understand cancel vs delete logic
  - [ ] Import validator: `from ..validators import require_confirm`
  - [ ] Replace inline check: `require_confirm(confirm, "delete calendar event")`
  - [ ] **Verify confirm check happens BEFORE** both cancellation and delete branches
- [ ] **Testing & Quality**
  - [ ] Update tests, verify both cancellation and delete branches work
  - [ ] Run: `uvx ruff format src/microsoft_mcp/tools/calendar.py`
  - [ ] Run: `uvx ruff check src/microsoft_mcp/tools/calendar.py`
  - [ ] Run: `uv run pyright src/microsoft_mcp/tools/calendar.py`
  - [ ] Run: `uv run pytest tests/ -k calendar_delete -v`

## 5. Refactor `emailrules_delete` to Use Shared Validator

**Current Implementation:** `src/microsoft_mcp/tools/email_rules.py:221-246`

- ✅ Has `confirm: bool = False` parameter
- ✅ Has inline validation: `if not confirm: raise ValueError(...)`
- ✅ Has proper metadata and docstring

**Task:** Replace inline validation with shared `require_confirm()` helper

- [ ] **Context Review & Implementation**
  - [ ] Review email_rules.py:221-246, document error message
  - [ ] Import validator: `from ..validators import require_confirm`
  - [ ] Replace inline check: `require_confirm(confirm, "delete email rule")`
- [ ] **Testing & Quality**
  - [ ] Update existing tests, verify rule deletion behavior unchanged
  - [ ] Run: `uvx ruff format src/microsoft_mcp/tools/email_rules.py`
  - [ ] Run: `uvx ruff check src/microsoft_mcp/tools/email_rules.py`
  - [ ] Run: `uv run pyright src/microsoft_mcp/tools/email_rules.py`
  - [ ] Run: `uv run pytest tests/ -k emailrules_delete -v`

## 6. Refactor `email_send` to Use Shared Validator (Dangerous Operation)

**Current Implementation:** `src/microsoft_mcp/tools/email.py:277-330`

- ✅ Has `confirm: bool = False` parameter
- ✅ Has inline validation: `if not confirm: raise ValueError(...)`
- ✅ Has proper metadata: `safety_level: "dangerous"`, `requires_confirmation: True`

**Task:** Replace inline validation with shared `require_confirm()` helper

- [ ] **Context Review & Implementation**
  - [ ] Review email.py:277-330, note this is send not delete
  - [ ] Import validator if not already imported: `from ..validators import require_confirm`
  - [ ] Replace inline check: `require_confirm(confirm, "send email")`
  - [ ] **Note:** Phase 2 will add recipient validation; Phase 1 only refactors confirm
- [ ] **Testing & Quality**
  - [ ] Update existing tests, verify send behavior unchanged
  - [ ] Run tests: `uv run pytest tests/ -k email_send -v`

## 7. Refactor `email_reply` to Use Shared Validator (Dangerous Operation)

**Current Implementation:** `src/microsoft_mcp/tools/email.py:555-580`

- ✅ Has `confirm: bool = False` parameter
- ✅ Has inline validation: `if not confirm: raise ValueError(...)`
- ✅ Has proper metadata: `safety_level: "dangerous"`, `requires_confirmation: True`

**Task:** Replace inline validation with shared `require_confirm()` helper

- [ ] **Context Review & Implementation**
  - [ ] Review email.py:555-580
  - [ ] Replace inline check: `require_confirm(confirm, "reply to email")`
  - [ ] **Note:** Phase 2 will add body validation; Phase 1 only refactors confirm
- [ ] **Testing & Quality**
  - [ ] Update existing tests, verify reply behavior unchanged
  - [ ] Run tests: `uv run pytest tests/ -k email_reply -v`

## 8. Verify Metadata Consistency for All Phase 1 Tools

**Current State:** All 7 tools **already have** proper metadata:

- ✅ `meta={"requires_confirmation": True}` present on all
- ✅ `annotations["destructiveHint"]` set to True on delete operations
- ✅ `safety_level` set correctly ("critical" for deletes, "dangerous" for send/reply)

**Task:** Verification only - ensure refactoring didn't break metadata

- [ ] **Metadata Verification**
  - [ ] **email_delete:** Verify `meta={"category": "email", "safety_level": "critical", "requires_confirmation": True}`
  - [ ] **file_delete:** Verify `meta={"category": "file", "safety_level": "critical", "requires_confirmation": True}`
  - [ ] **contact_delete:** Verify `meta={"category": "contact", "safety_level": "critical", "requires_confirmation": True}`
  - [ ] **calendar_delete_event:** Verify `meta={"category": "calendar", "safety_level": "critical", "requires_confirmation": True}`
  - [ ] **emailrules_delete:** Verify `meta={"category": "emailrules", "safety_level": "critical", "requires_confirmation": True}`
  - [ ] **email_send:** Verify `meta={"category": "email", "safety_level": "dangerous", "requires_confirmation": True}`
  - [ ] **email_reply:** Verify `meta={"category": "email", "safety_level": "dangerous", "requires_confirmation": True}`
- [ ] **Annotations Verification**
  - [ ] **All delete operations:** Verify `annotations["destructiveHint"] = True`
  - [ ] **Send/reply operations:** Verify `annotations["destructiveHint"] = False` (dangerous, not destructive)
- [ ] **Tool Discovery Test**
  - [ ] Run MCP server and list tools to verify metadata visible to clients
  - [ ] Verify metadata structure matches FastMCP expectations

## Phase 1 Completion Checklist

- [x] **All 7 Tools Refactored**
  - [x] email_delete ✓
  - [x] file_delete ✓
  - [x] contact_delete ✓
  - [x] calendar_delete_event ✓
  - [x] emailrules_delete ✓
  - [x] email_send ✓
  - [x] email_reply ✓
- [ ] **Quality Gate Passed**
  - [ ] All ruff format/check/pyright passes
  - [x] All tool-specific tests passing
  - [ ] Full test suite: `uv run pytest tests/ -v` passes
  - [ ] No regressions in integration tests
- [ ] **Documentation Updates**
  - [x] Update CHANGELOG.md with Phase 1 completion
  - [x] Note validator integration in documentation
  - [x] Document any error message format changes
- [ ] **Handoff Preparation**
  - [x] Update `reports/todo/PARAMETER_VALIDATION.md` marking Phase 1 complete
  - [x] Create Phase 1 completion summary documenting:
    - Error message format changes (if any)
    - Breaking changes (none expected - refactoring only)
    - Test coverage improvements
  - [ ] Notify stakeholders Phase 1 complete, ready for Phase 2

## Phase 2 Preview

**Phase 2 Scope:** Dangerous Operations - Additional Validation

- `email_send`: Add recipient validation (email format, required recipients)
- `email_reply`: Add body validation (non-empty, whitespace check)
- `calendar_respond_event`: Add response enum validation
- Calendar operations: Add attendee email validation

**Note:** Phase 1 focused ONLY on refactoring confirm validation. Phase 2 will add the additional parameter validation for these tools.
