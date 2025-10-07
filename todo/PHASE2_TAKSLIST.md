# Phase 2 Tasklist — Dangerous Operations (Send/Reply) + Additional Validation

Detailed checklist to implement comprehensive validation for high-impact send/reply scenarios and calendar operations.

## ⚠️ Important Context

**Phase 1 Status Required:** Phase 1 must be complete before starting Phase 2:

- ✅ All 7 tools refactored to use `require_confirm()` validator
- ✅ email_send and email_reply already have confirm validation (refactored in Phase 1)

**Phase 2 Scope:** Add ADDITIONAL parameter validation beyond confirm:

1. **Recipient/attendee validation** - email format, deduplication, required fields
2. **Response enum validation** - calendar response choices
3. **Body validation** - non-empty checks for replies
4. **DateTime validation** - ISO format for calendar operations

**NOT in Phase 2 Scope:**

- Confirm parameter validation (done in Phase 1)
- Update dict validation (Phase 3)
- Limit parameter validation (Phase 3)

## Prerequisites (MUST Complete Before Starting Phase 2)

- [ ] **Phase 1 Complete:** All 7 tools refactored to use shared confirm validator
- [ ] **Validators Available:** The following validators must exist in `validators.py`:
  - [ ] `validate_email_format(email: str) -> str` - Email format validation
  - [ ] `normalize_recipients(recipients: str | list[str]) -> list[str]` - Normalize and validate recipients
  - [ ] `validate_iso_datetime(value: str, name: str) -> datetime` - ISO datetime validation
  - [ ] `validate_datetime_window(start: str, end: str) -> tuple[datetime, datetime]` - Start/end validation
  - [ ] `validate_timezone(tz: str) -> str` - Timezone validation
  - [ ] `validate_choices(value: str, allowed: set[str], name: str) -> str` - Enum validation
- [ ] **Test Infrastructure:** conftest.py has fixtures for testing validation

## 1. Add Recipient Validation to `email_send`

**Current Implementation:** `src/microsoft_mcp/tools/email.py:277-330`

- ✅ Already has confirm validation (refactored in Phase 1)
- ⚠️ **NO recipient validation** - accepts any string/list without format checking
- ⚠️ **NO deduplication** - may send duplicate emails
- Parameters: `to: str | list[str]`, `cc: str | list[str] | None`

**Task:** Add recipient email format validation and deduplication

- [ ] **Current Behavior Analysis**
  - [ ] Review email.py:277-330 implementation
  - [ ] **Current code does:** Simple type coercion `to_list = [to] if isinstance(to, str) else to`
  - [ ] **Current code missing:** Email format validation, deduplication, empty checks
  - [ ] **Note:** BCC not currently supported (potential future enhancement)
- [ ] **Validation Requirements**
  - [ ] **Required recipients:** At least one valid email in `to` parameter (required field)
  - [ ] **Email format:** Use `validate_email_format()` for each address
  - [ ] **Deduplication:** Case-insensitive deduplication across to/cc
  - [ ] **Graph limits:** Document max recipients (typically 500 total per Graph API)
  - [ ] **Empty/whitespace:** Reject empty strings, whitespace-only addresses
- [ ] **Implementation**
  - [ ] **Import validators:** `from ..validators import normalize_recipients, validate_email_format`
  - [ ] **Validate `to` recipients:**

    ```python
    to_normalized = normalize_recipients(to)  # Returns validated list
    if not to_normalized:
        raise ValueError("At least one recipient required in 'to' field")
    ```

  - [ ] **Validate `cc` recipients (if provided):**

    ```python
    cc_normalized = normalize_recipients(cc) if cc else []
    ```

  - [ ] **Deduplication:** Combine to + cc, deduplicate, rebuild separate lists
  - [ ] **Validation order:** Recipients → Confirm → Graph API (validation errors fail early)
  - [ ] **Preserve existing:** Attachment handling, subject/body validation unchanged
- [ ] **Testing**
  - [ ] **Valid cases:** Single string, list of strings, mixed to/cc
  - [ ] **Invalid cases:** Empty to, invalid email format, whitespace-only
  - [ ] **Deduplication:** Same email in to and cc, case variations
  - [ ] **Error ordering:** Invalid recipients fail before confirm=False
  - [ ] **Integration:** Verify Graph payload structure unchanged (except normalized addresses)
- [ ] **Documentation**
  - [ ] Update docstring with recipient validation rules
  - [ ] Add Raises section for ValidationError on invalid recipients
- [ ] **Quality Gate**
  - [ ] Run: `uvx ruff format src/microsoft_mcp/tools/email.py`
  - [ ] Run: `uv run pytest tests/ -k email_send -v`

## 2. Add Body Validation to `email_reply`

**Current Implementation:** `src/microsoft_mcp/tools/email.py:555-580`

- ✅ Already has confirm validation (refactored in Phase 1)
- ⚠️ **NO body validation** - accepts empty/whitespace-only body
- ⚠️ **Recipients automatic** - Graph API replies to original sender automatically (no recipient param)
- Parameters: `body: str` (required), `message: str | None` (optional in payload)

**Task:** Add body content validation (non-empty, no whitespace-only)

**Key Finding:** Recipients are **NOT user-specified** - Graph handles reply addressing automatically. Only body needs validation.

- [ ] **Current Behavior Analysis**
  - [ ] Review email.py:555-580 implementation
  - [ ] **Current code does:** Sends body directly to Graph API without validation
  - [ ] **Current code missing:** Empty check, whitespace-only check
  - [ ] **Note:** Graph API determines recipients automatically (reply-to-sender)
- [ ] **Validation Requirements**
  - [ ] **Non-empty:** Reject empty string `""`
  - [ ] **Non-whitespace:** Reject whitespace-only strings (spaces, tabs, newlines)
  - [ ] **Minimum length:** Consider minimum meaningful message length (e.g., 1 non-whitespace char)
- [ ] **Implementation**
  - [ ] **Validate body parameter:**

    ```python
    body_stripped = body.strip()
    if not body_stripped:
        raise ValueError("Reply body cannot be empty or whitespace-only")
    ```

  - [ ] **Validation order:** Body → Confirm → Graph API
  - [ ] **Use stripped version:** Consider using `body_stripped` in Graph payload for consistency
- [ ] **Testing**
  - [ ] **Valid cases:** Non-empty body with content
  - [ ] **Invalid cases:** Empty string, whitespace-only (`"   "`, `"\n\t"`)
  - [ ] **Error ordering:** Invalid body fails before confirm=False
  - [ ] **Integration:** Verify Graph request structure unchanged
- [ ] **Documentation**
  - [ ] Update docstring to note body cannot be empty/whitespace-only
  - [ ] Add Raises section for ValidationError on invalid body
  - [ ] Clarify that recipients are automatic (reply-to-sender)
- [ ] **Quality Gate**
  - [ ] Run: `uv run pytest tests/ -k email_reply -v`

**Note:** No recipient validation needed - Graph API handles reply addressing. Phase 2 Section 2 is body-only validation.

## 3. Add Response Enum Validation to `calendar_respond_event`

**Current Implementation:** `src/microsoft_mcp/tools/calendar.py:214-243`

- ⚠️ **NO response validation** - accepts any string, passes directly to Graph API endpoint
- ⚠️ **Runtime failure** - Invalid responses cause Graph API 400 error (not caught early)
- Parameters: `response: str = "accept"` (default), `message: str | None` (optional)
- **Docstring lists valid responses:** accept, decline, tentativelyAccept (but not enforced)

**Current Code:** `graph.request("POST", f"/me/events/{event_id}/{response}", ...)`

- Uses response directly in URL path → invalid values cause Graph API errors

**Task:** Add enum validation for response parameter

- [ ] **Current Behavior Analysis**
  - [ ] Review calendar.py:214-243 implementation
  - [ ] **Current code does:** Constructs endpoint with raw response string
  - [ ] **Current code missing:** Response validation, case normalization
  - [ ] **Graph API requirement:** Exact strings "accept", "decline", "tentativelyAccept"
- [ ] **Validation Requirements**
  - [ ] **Allowed values:** `{"accept", "decline", "tentativelyAccept"}` (exact Graph API format)
  - [ ] **Case handling:** Consider accepting "Accept", "ACCEPT", "tentativelyaccept" → normalize
  - [ ] **Whitespace:** Strip whitespace from input
  - [ ] **Error message:** Must list valid options when invalid value provided
  - [ ] **Message parameter:** Validate non-empty if provided (optional validation)
- [ ] **Implementation**
  - [ ] **Import validator:** `from ..validators import validate_choices`
  - [ ] **Validate response parameter:**

    ```python
    ALLOWED_RESPONSES = {"accept", "decline", "tentativelyAccept"}
    response_normalized = validate_choices(
        response.strip().lower(),
        ALLOWED_RESPONSES,
        "response"
    )
    # Or create case-insensitive mapping:
    RESPONSE_MAP = {
        "accept": "accept",
        "decline": "decline",
        "tentativelyaccept": "tentativelyAccept",
        "tentative": "tentativelyAccept"  # Allow short form?
    }
    ```

  - [ ] **Validate message (optional):**

    ```python
    if message is not None and not message.strip():
        raise ValueError("Message cannot be empty or whitespace-only if provided")
    ```

  - [ ] **Use normalized response** in Graph API endpoint
- [ ] **Testing**
  - [ ] **Valid cases:** Each exact response string, case variations (Accept, ACCEPT)
  - [ ] **Invalid cases:** Typos ("accep", "accepted"), invalid strings
  - [ ] **Message validation:** Empty message if provided, None message (should work)
  - [ ] **Endpoint verification:** Ensure Graph endpoint uses normalized response
- [ ] **Documentation**
  - [ ] Docstring already lists valid responses ✅ - verify still accurate
  - [ ] Add Raises section for ValidationError on invalid response
  - [ ] Consider adding note about case-insensitivity if implemented
- [ ] **Quality Gate**
  - [ ] Run: `uvx ruff format src/microsoft_mcp/tools/calendar.py`
  - [ ] Run: `uv run pytest tests/ -k calendar_respond -v`

## 4. Add Attendee Validation to Calendar Operations

**Scope:** 3 calendar tools accept `attendees` parameter:

1. `calendar_create_event` (calendar.py:48-97) - `attendees: str | list[str] | None`
2. `calendar_update_event` (calendar.py:101-150) - updates dict may contain attendees
3. `calendar_check_availability` (calendar.py:258-290) - `attendees: str | list[str] | None`

**Current Implementations:**

- ✅ Type coercion: `attendees_list = [attendees] if isinstance(attendees, str) else attendees`
- ⚠️ **NO email format validation** - accepts any string
- ⚠️ **NO deduplication** - may create duplicate attendee entries
- ⚠️ **NO count limits** - Graph API has limits (typically 500 attendees)

**Task:** Add attendee email format validation and deduplication

### 4a. Validate `calendar_create_event` Attendees

- [ ] **Current Behavior Analysis**
  - [ ] Review calendar.py:48-97 implementation
  - [ ] **Current code (lines 88-92):**

    ```python
    if attendees:
        attendees_list = [attendees] if isinstance(attendees, str) else attendees
        event["attendees"] = [
            {"emailAddress": {"address": a}, "type": "required"} for a in attendees_list
        ]
    ```

  - [ ] **Missing:** Email validation, deduplication, count limits
- [ ] **Implementation**
  - [ ] **Import validator:** `from ..validators import normalize_recipients`
  - [ ] **Validate attendees:**

    ```python
    if attendees:
        attendees_normalized = normalize_recipients(attendees)
        if len(attendees_normalized) > 500:  # Graph API limit
            raise ValueError(f"Maximum 500 attendees allowed, got {len(attendees_normalized)}")
        event["attendees"] = [
            {"emailAddress": {"address": a}, "type": "required"}
            for a in attendees_normalized
        ]
    ```

- [ ] **Testing**
  - [ ] Valid: Single string, list of emails, empty/None (optional)
  - [ ] Invalid: Malformed emails, duplicate emails, >500 attendees
- [ ] **Quality Gate:** `uv run pytest tests/ -k calendar_create -v`

### 4b. Validate `calendar_update_event` Attendees

- [ ] **Current Behavior Analysis**
  - [ ] Review calendar.py:101-150 - uses updates dict
  - [ ] **Note:** Attendees validation happens in Phase 3 (update dict validation)
  - [ ] **Decision:** Skip attendee-specific validation here OR validate if `attendees` key in updates
- [ ] **Implementation Decision**
  - [ ] **Option A:** Defer to Phase 3 (update dict validation handles all fields)
  - [ ] **Option B:** Add attendee-specific validation now:

    ```python
    if "attendees" in updates:
        # Validate and normalize attendees in updates dict
        attendees_normalized = normalize_recipients(updates["attendees"])
        updates["attendees"] = [{"emailAddress": {"address": a}, "type": "required"} for a in attendees_normalized]
    ```

  - [ ] **Recommendation:** **Defer to Phase 3** - update dict validation is more comprehensive

### 4c. Validate `calendar_check_availability` Attendees

- [ ] **Current Behavior Analysis**
  - [ ] Review calendar.py:258-290 implementation
  - [ ] **Current code:** Builds list of email addresses for availability query
  - [ ] **Missing:** Email validation for attendees parameter
- [ ] **Implementation**
  - [ ] **Validate attendees (optional parameter):**

    ```python
    if attendees:
        attendees_normalized = normalize_recipients(attendees)
        # Use normalized list in availability query
    ```

- [ ] **Testing**
  - [ ] Valid: None (check only user), single attendee, multiple attendees
  - [ ] Invalid: Malformed email addresses
- [ ] **Quality Gate:** `uv run pytest tests/ -k calendar_check -v`

### 4d. DateTime Validation for Calendar Operations

**Additional validation needed:** All 3 operations accept `start` and `end` datetime parameters

- [ ] **Add to calendar_create_event:**
  - [ ] **Import:** `from ..validators import validate_iso_datetime, validate_datetime_window, validate_timezone`
  - [ ] **Validate:** `start_dt, end_dt = validate_datetime_window(start, end)`
  - [ ] **Validate timezone:** `timezone_normalized = validate_timezone(timezone)`
- [ ] **Add to calendar_check_availability:**
  - [ ] **Validate:** `start_dt, end_dt = validate_datetime_window(start, end)`
- [ ] **Testing:** Invalid ISO format, end before start, invalid timezone

## Phase 2 Completion Checklist

- [ ] **All 4 Sections Complete:**
  - [ ] Section 1: email_send recipient validation ✓
  - [ ] Section 2: email_reply body validation ✓
  - [ ] Section 3: calendar_respond_event response validation ✓
  - [ ] Section 4: Calendar attendee + datetime validation ✓
- [ ] **Quality Gate Passed:**
  - [ ] All ruff format/check/pyright passes
  - [ ] All tool-specific tests passing
  - [ ] Full test suite: `uv run pytest tests/ -v` passes
- [ ] **Documentation Updates:**
  - [ ] Update CHANGELOG.md with Phase 2 completion
  - [ ] Update tool docstrings with validation rules
- [ ] **Handoff to Phase 3:**
  - [ ] Update `reports/todo/PARAMETER_VALIDATION.md` marking Phase 2 complete
  - [ ] Notify stakeholders Phase 2 complete, ready for Phase 3 (update dict validation)

## Phase 3 Preview

**Phase 3 Scope:** Moderate Operations - Update Dict and Limit Validation

- Update dict validation across all `*_update` tools (email, contact, calendar, etc.)
- Bounds checking for all `limit` parameters (1 <= limit <= max)
- Additional ISO datetime validation for remaining calendar/event operations
- Folder choice validation for email and file tools
