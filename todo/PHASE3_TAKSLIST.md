# Phase 3 Tasklist — Moderate Operations (Write/Update)

Comprehensive checklist for ensuring write/update operations enforce strict validation rules.

## ⚠️ Important Context

**Phase 2 Status Required:** Phase 2 must be complete before starting Phase 3:

- ✅ email_send recipient validation complete
- ✅ email_reply body validation complete
- ✅ calendar_respond_event enum validation complete
- ✅ Calendar attendee + datetime validation complete

**Phase 3 Scope:** Update dict validation, limit bounds checking, remaining datetime/timezone validation

1. **Update dict validation** - Whitelist allowed keys, validate nested structures
2. **Limit parameter bounds** - Enforce 1 <= limit <= max across all list operations
3. **ISO datetime validation** - Remaining date/time parameters not covered in Phase 2
4. **Timezone validation** - Calendar operations not covered in Phase 2

**Key Difference from Phase 2:**

- Phase 2: Specific tools with specific validations (recipients, body, response, attendees)
- Phase 3: **Systematic validation patterns** applied across ALL tools of each type

## Prerequisites (MUST Complete Before Starting Phase 3)

- [ ] **Phase 2 Complete:** All dangerous operation validations implemented
- [ ] **Validators Available:** The following validators must exist in `validators.py`:
  - [ ] `validate_json_payload(payload: dict, required_keys: set[str], allowed_keys: set[str])` - Update dict validation
  - [ ] `validate_limit(limit: int, minimum: int, maximum: int, param_name: str) -> int` - Bounds checking
  - [ ] `validate_iso_datetime(value: str, name: str, allow_date_only: bool) -> datetime` - DateTime validation
  - [ ] `validate_datetime_window(start: str, end: str) -> tuple[datetime, datetime]` - Start/end validation
  - [ ] `validate_timezone(tz: str) -> str` - Timezone validation (if not done in Phase 2)
- [ ] **Test Infrastructure:** Comprehensive fixtures for update dict testing

## Tools in Scope

**Update Tools (5):**

- `email_update` (email.py:443-468)
- `calendar_update_event` (calendar.py:112-150)
- `contact_update` (contact.py:142-160)
- `emailrules_update` (email_rules.py:149-202)
- `file_update` (file.py:191-210) - **NOTE: Not dict-based, updates content only**

**Tools with Limit Parameters (13):**

- `email_list`, `email_get` (body_max_length)
- `emailfolders_list`, `emailfolders_get_tree` (max_depth)
- `contact_list`
- `file_list`, `folder_list`, `folder_get_tree` (max_depth)
- `search_files`, `search_emails`, `search_events`, `search_contacts`, `search_unified`

**DateTime Parameters (Already covered in Phase 2 or read-only):**

- ✅ Phase 2: `calendar_create_event`, `calendar_check_availability`
- Phase 3: Search tools with date ranges

## 1. Validate Update Dicts Across All `*_update` Tools

**Current State Analysis:**

- ✅ `email_update` (email.py:443-468): **NO validation** - accepts any dict, passes directly to Graph
- ✅ `calendar_update_event` (calendar.py:112-150): **Partial validation** - checks specific keys, transforms to Graph format
- ✅ `contact_update` (contact.py:142-160): **NO validation** - accepts any dict
- ✅ `emailrules_update` (email_rules.py:149-202): **Empty check only** - validates at least one field
- ❌ `file_update` (file.py:191-210): **NOT applicable** - updates file content, not dict-based

**Validation Challenge:** Each tool has different allowed keys and nested structure requirements.

### 1a. Validate `email_update` Dict

**Current Implementation:** email.py:443-468

- Accepts `updates: dict[str, Any]` without validation
- Passes directly to Graph PATCH `/me/messages/{email_id}`

**Allowed Keys (Microsoft Graph Message properties):**

- `isRead: bool` - Mark as read/unread
- `categories: list[str]` - Category labels
- `importance: str` - "low" | "normal" | "high"
- `flag: dict` - Flag with status/dueDateTime
- **NOT allowed:** subject, body, toRecipients (immutable after creation)

**Implementation:**

- [ ] **Define allowed keys:**

  ```python
  ALLOWED_EMAIL_UPDATE_KEYS = {
      "isRead", "categories", "importance", "flag", "inferenceClassification"
  }
  ```

- [ ] **Validate dict:**

  ```python
  if not updates:
      raise ValueError("At least one field must be provided to update")

  unknown_keys = set(updates.keys()) - ALLOWED_EMAIL_UPDATE_KEYS
  if unknown_keys:
      raise ValueError(
          f"Invalid update keys: {unknown_keys}. "
          f"Allowed: {ALLOWED_EMAIL_UPDATE_KEYS}"
      )

  # Type-specific validation
  if "isRead" in updates and not isinstance(updates["isRead"], bool):
      raise ValueError("isRead must be boolean")
  if "categories" in updates and not isinstance(updates["categories"], list):
      raise ValueError("categories must be list of strings")
  ```

- [ ] **Testing:** Valid updates, unknown keys, type errors
- [ ] **Quality Gate:** `uv run pytest tests/ -k email_update -v`

### 1b. Refactor `calendar_update_event` Dict Validation

**Current Implementation:** calendar.py:112-150

- ✅ **Already has key checking** - processes specific keys only
- ⚠️ **Missing:** Validation of unknown keys, datetime validation, attendee validation

**Current Allowed Keys:** subject, start, end, timezone, location, body
**Missing:** attendees (deferred from Phase 2)

**Implementation:**

- [ ] **Define allowed keys:**

  ```python
  ALLOWED_CALENDAR_UPDATE_KEYS = {
      "subject", "start", "end", "timezone", "location", "body", "attendees"
  }
  ```

- [ ] **Add validation before processing:**

  ```python
  if not updates:
      raise ValueError("At least one field must be provided to update")

  unknown_keys = set(updates.keys()) - ALLOWED_CALENDAR_UPDATE_KEYS
  if unknown_keys:
      raise ValueError(f"Invalid keys: {unknown_keys}")

  # Validate datetime fields if present
  if "start" in updates:
      validate_iso_datetime(updates["start"], "start")
  if "end" in updates:
      validate_iso_datetime(updates["end"], "end")
  if "start" in updates and "end" in updates:
      validate_datetime_window(updates["start"], updates["end"])
  if "timezone" in updates:
      validate_timezone(updates["timezone"])
  if "attendees" in updates:
      updates["attendees"] = normalize_recipients(updates["attendees"])
  ```

- [ ] **Testing:** Unknown keys, datetime validation, attendee validation
- [ ] **Quality Gate:** `uv run pytest tests/ -k calendar_update -v`

### 1c. Validate `contact_update` Dict

**Current Implementation:** contact.py:142-160

- Accepts `updates: dict[str, Any]` without validation

**Allowed Keys (Microsoft Graph Contact properties):**

- `givenName`, `surname`, `displayName`
- `emailAddresses: list[dict]` - Email addresses array
- `businessPhones: list[str]`, `homePhones: list[str]`, `mobilePhone: str`
- `jobTitle`, `companyName`, `department`

**Implementation:**

- [ ] **Define allowed keys:**

  ```python
  ALLOWED_CONTACT_UPDATE_KEYS = {
      "givenName", "surname", "displayName", "emailAddresses",
      "businessPhones", "homePhones", "mobilePhone",
      "jobTitle", "companyName", "department"
  }
  ```

- [ ] **Validate + type checking**
- [ ] **Email validation:** If emailAddresses in updates, validate format
- [ ] **Testing:** Valid/invalid keys, email format validation
- [ ] **Quality Gate:** `uv run pytest tests/ -k contact_update -v`

### 1d. Enhance `emailrules_update` Dict Validation

**Current Implementation:** email_rules.py:149-202

- ✅ **Already checks empty dict**
- ⚠️ **Missing:** Allowed keys validation, nested structure validation

**Allowed Keys:** display_name, conditions, actions, sequence, is_enabled, exceptions

**Implementation:**

- [ ] **Define allowed keys + nested validation**
- [ ] **Validate sequence >= 1**
- [ ] **Validate conditions/actions structure** (complex nested dicts)
- [ ] **Testing:** Unknown keys, invalid sequence, malformed conditions
- [ ] **Quality Gate:** `uv run pytest tests/ -k emailrules_update -v`

### 1e. Skip `file_update` (Not Dict-Based)

**Reasoning:** file_update(file_id, local_file_path, account_id) updates file **content**, not properties via dict. No dict validation needed.

## 2. Add Bounds Checking to All Limit Parameters

**Tools with Limit Parameters (13 tools):**

| Tool | Current Default | Current Validation | Graph Max | Proposed Validation |
|------|----------------|-------------------|-----------|-------------------|
| `email_list` | 10 | `min(limit, 200)` | 999 | `1 <= limit <= 200` |
| `email_get` | body_max_length=50000 | None | No limit | `1 <= limit <= 500000` |
| `emailfolders_list` | 100 | None | 250 | `1 <= limit <= 250` |
| `emailfolders_get_tree` | max_depth=10 | None | ~25 | `1 <= depth <= 25` |
| `contact_list` | 50 | `min(limit, 100)` | 999 | `1 <= limit <= 500` |
| `file_list` | 50 | `min(limit, 100)` | 999 | `1 <= limit <= 500` |
| `folder_list` | 50 | `min(limit, 100)` | 999 | `1 <= limit <= 500` |
| `folder_get_tree` | max_depth=10 | None | ~25 | `1 <= depth <= 25` |
| `search_files` | 50 | None | 999 | `1 <= limit <= 500` |
| `search_emails` | 50 | None | 999 | `1 <= limit <= 500` |
| `search_events` | 50 | None | 999 | `1 <= limit <= 500` |
| `search_contacts` | 50 | None | 999 | `1 <= limit <= 500` |
| `search_unified` | 50 | None | 999 | `1 <= limit <= 500` |

**Validation Strategy:**

- **Reject, don't clamp** - Raise error for out-of-bounds values (explicit > implicit)
- **Remove existing min() clamping** - Replace with explicit validation
- **Consistent maximums** - 500 for most lists, 200 for email (performance), 25 for tree depth

### Implementation Approach

**For each tool:**

1. **Import validator:** `from ..validators import validate_limit`
2. **Add validation at function entry:**

   ```python
   # For list operations
   limit = validate_limit(limit, minimum=1, maximum=500, param_name="limit")

   # For tree depth
   max_depth = validate_limit(max_depth, minimum=1, maximum=25, param_name="max_depth")

   # For body length
   body_max_length = validate_limit(body_max_length, minimum=1, maximum=500000, param_name="body_max_length")
   ```

3. **Remove existing min() calls** - e.g., `min(limit, 100)` → use validated limit directly
4. **Update docstring** - Document valid range

### 2a. Email Tools

- [ ] **email_list:** Validate `limit` (1-200)
- [ ] **email_get:** Validate `body_max_length` (1-500000)
- [ ] **Quality Gate:** `uv run pytest tests/ -k "email_list or email_get" -v`

### 2b. Folder Tools

- [ ] **emailfolders_list:** Validate `limit` (1-250)
- [ ] **emailfolders_get_tree:** Validate `max_depth` (1-25)
- [ ] **Quality Gate:** `uv run pytest tests/ -k emailfolders -v`

### 2c. Contact Tools

- [ ] **contact_list:** Validate `limit` (1-500), remove `min(limit, 100)`
- [ ] **Quality Gate:** `uv run pytest tests/ -k contact_list -v`

### 2d. File/Folder Tools

- [ ] **file_list:** Validate `limit` (1-500), remove `min(limit, 100)`
- [ ] **folder_list:** Validate `limit` (1-500), remove `min(limit, 100)`
- [ ] **folder_get_tree:** Validate `max_depth` (1-25)
- [ ] **Quality Gate:** `uv run pytest tests/ -k "file_list or folder" -v`

### 2e. Search Tools (5 tools)

- [ ] **All search tools:** Validate `limit` (1-500)
- [ ] **Quality Gate:** `uv run pytest tests/ -k search -v`

### Testing Requirements

- [ ] **Below minimum:** `limit=0`, `limit=-1` → ValueError with guidance
- [ ] **Above maximum:** `limit=1000` → ValueError listing valid range
- [ ] **Boundary values:** `limit=1`, `limit=500` → Success
- [ ] **Default values:** Ensure defaults still work (no breaking changes)

## 3. Add ISO Datetime Validation to Remaining Date/Time Parameters

**Scope Analysis:**

- ✅ **Phase 2 covered:** `calendar_create_event`, `calendar_check_availability` (start/end/timezone)
- ✅ **Section 1b covered:** `calendar_update_event` (if start/end in updates dict)
- **Phase 3 remaining:** Search tools with date parameters

**Tools Needing DateTime Validation:**

| Tool | Parameters | Current Validation | Phase 3 Action |
|------|-----------|-------------------|----------------|
| `search_events` | days_ahead, days_back | None | Validate range (0-730) |
| Other searches | N/A | N/A | No datetime params |

**Decision: Minimal scope** - Most datetime validation covered in Phase 2. Phase 3 only adds:

### 3a. Validate `search_events` Date Range

**Current Implementation:** search.py:120+

- Parameters: `days_ahead: int = 30`, `days_back: int = 7`
- No validation of range

**Implementation:**

- [ ] **Validate day ranges:**

  ```python
  if days_ahead < 0 or days_ahead > 730:
      raise ValueError("days_ahead must be between 0 and 730 (2 years)")
  if days_back < 0 or days_back > 730:
      raise ValueError("days_back must be between 0 and 730 (2 years)")
  ```

- [ ] **Quality Gate:** `uv run pytest tests/ -k search_events -v`

**Note:** Other datetime validation (ISO format, start/end windows, timezones) already covered in Phase 2.

## 4. Phase 3 Completion Checklist

- [ ] **All Section 1 Subsections Complete (Update Dict Validation):**
  - [ ] 1a: email_update ✓
  - [ ] 1b: calendar_update_event ✓
  - [ ] 1c: contact_update ✓
  - [ ] 1d: emailrules_update ✓
  - [ ] 1e: file_update (skipped - not applicable) ✓

- [ ] **All Section 2 Subsections Complete (Limit Validation):**
  - [ ] 2a: Email tools (2 tools) ✓
  - [ ] 2b: Folder tools (2 tools) ✓
  - [ ] 2c: Contact tools (1 tool) ✓
  - [ ] 2d: File/Folder tools (3 tools) ✓
  - [ ] 2e: Search tools (5 tools) ✓

- [ ] **Section 3 Complete (DateTime Validation):**
  - [ ] 3a: search_events day range validation ✓

- [ ] **Quality Gate Passed:**
  - [ ] All ruff format/check/pyright passes
  - [ ] All tool-specific tests passing
  - [ ] Full test suite: `uv run pytest tests/ -v` passes
  - [ ] No regressions in integration tests

- [ ] **Documentation Updates:**
  - [ ] Update CHANGELOG.md with Phase 3 completion
  - [ ] Update tool docstrings with validation rules and valid ranges
  - [ ] Document breaking changes (stricter validation may reject previously accepted values)

- [ ] **Handoff to Phase 4:**
  - [ ] Update `reports/todo/PARAMETER_VALIDATION.md` marking Phase 3 complete
  - [ ] Create Phase 3 completion summary documenting:
    - Update dict allowed keys for each tool
    - Limit ranges for all 13 tools
    - Any breaking changes
  - [ ] Notify stakeholders Phase 3 complete, ready for Phase 4 (safe operations)

## Phase 4 Preview

**Phase 4 Scope:** Safe Operations (Read-Only)

- Folder choice validation for email and file tools (inbox, sent, drafts, etc.)
- Query parameter validation for search operations (non-empty, length limits)
- Path parameter validation for folder operations (no traversal, format checking)
- Final validation coverage review across all 50 tools

**Note:** Phase 4 is lowest priority - read-only operations have minimal risk, but validation improves error messages and prevents API failures.
