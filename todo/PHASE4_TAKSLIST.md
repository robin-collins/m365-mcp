# Phase 4 Tasklist — Safe Operations (Read)

Final validation phase to ensure read-only operations enforce safe parameter handling without regression risks.

## ⚠️ Important Context

**Phase 3 Status Required:** Phase 3 must be complete before starting Phase 4:

- ✅ Update dict validation complete (4 tools)
- ✅ Limit bounds checking complete (13 tools)
- ✅ DateTime validation complete (search_events)

**Phase 4 Scope:** Final validation for read-only operations (lowest priority)

1. **Folder choice validation** - Email folder names (inbox, sent, etc.)
2. **Query validation** - Search query non-empty, length limits
3. **Path validation** - OneDrive/email folder paths format checking

**Why Phase 4 is Last:**

- Read-only operations have **minimal risk** (no data modification)
- Graph API provides good error messages for invalid inputs
- Validation improves UX but not critical for security
- Most important validations already in Phases 1-3

## Prerequisites (MUST Complete Before Starting Phase 4)

- [ ] **Phase 3 Complete:** All moderate operation validations implemented
- [ ] **Validators Available (if needed):**
  - [ ] `validate_folder_choice(folder: str, allowed: dict[str, str]) -> str` - Folder name validation
  - [ ] `validate_onedrive_path(path: str) -> str` - Path format validation (from Critical Path Section 2)
  - [ ] Note: Most validation can be inline (simple checks) rather than requiring new validators

## Tools in Scope

**Folder Choice Tools (2):**

- `email_list` (email.py:32-86) - Has FOLDERS dict, casefold() logic
- `email_move` (email.py:526-560) - Has destination_folder validation
- `search_emails` (search.py:66-113) - Optional folder parameter

**Search Tools with Query (5):**

- `search_files` (search.py:22-51)
- `search_emails` (search.py:66-113)
- `search_events` (search.py:115-171)
- `search_contacts` (search.py:173-211)
- `search_unified` (search.py:214-252) - Also validates entity_types

**Path Parameter Tools (5):**

- OneDrive paths: `file_list`, `folder_list`, `folder_get`
- Email folder paths: `emailfolders_get_tree` (uses folder IDs, not paths)
- Note: Path validation partially covered in Critical Path Section 2 (ensure_safe_path)

## 1. Enhance Folder Choice Validation for Email Tools

**Current State Analysis:**

- ✅ `email_list` (email.py:32-86): **Has FOLDERS dict** with casefold() normalization
  - Current logic: `FOLDERS.get(folder.casefold(), folder)` - accepts any string, uses as-is if not in dict
  - Issue: Invalid folder names silently passed to Graph API (fails at runtime)
- ✅ `email_move` (email.py:526-560): **Uses FOLDERS dict** similar pattern
- ✅ `search_emails` (search.py:66-113): **Optional folder param**, similar pattern

**Current FOLDERS Dict (email.py:7-17):**

```python
FOLDERS = {
    "inbox": "inbox",
    "sent": "sentitems",
    "drafts": "drafts",
    "deleted": "deleteditems",
    "junk": "junkemail",
    "archive": "archive",
}
```

**Validation Strategy:**

- **Option 1 (Recommended):** Reject unknown folder names with helpful error
- **Option 2:** Keep current behavior (pass-through to Graph API)
- **Decision:** Option 1 - Better UX, fail fast with guidance

### 1a. Enhance `email_list` Folder Validation

**Current Implementation:** email.py:32-86

- Lines 54-62: folder_id takes precedence, folder with FOLDERS lookup, default to inbox
- **Issue:** Unknown folder names passed through (e.g., `folder="invalid"` → Graph 404)

**Implementation:**

- [ ] **Add validation after folder parameter:**

  ```python
  # Current code at lines 54-62
  if folder_id:
      folder_path = folder_id
  elif folder:
      # NEW: Validate folder name
      folder_lower = folder.casefold()
      if folder_lower not in FOLDERS:
          valid_folders = ", ".join(sorted(FOLDERS.keys()))
          raise ValueError(
              f"Invalid folder name '{folder}'. "
              f"Valid options: {valid_folders}, or use folder_id parameter"
          )
      folder_path = FOLDERS[folder_lower]
  else:
      folder_path = "inbox"
  ```

- [ ] **Testing:**
  - Valid: "inbox", "INBOX", "Sent" → Success
  - Invalid: "invalid", "trash" → ValueError with valid options
  - folder_id: Any string → Pass through (user knows ID)
- [ ] **Quality Gate:** `uv run pytest tests/ -k email_list -v`

### 1b. Enhance `email_move` Folder Validation

**Current Implementation:** email.py:526-560

- Similar pattern to email_list

**Implementation:**

- [ ] **Add same validation pattern** for destination_folder parameter
- [ ] **Testing:** Valid/invalid folder names
- [ ] **Quality Gate:** `uv run pytest tests/ -k email_move -v`

### 1c. Enhance `search_emails` Folder Validation

**Current Implementation:** search.py:66-113

- Optional folder parameter (can be None)

**Implementation:**

- [ ] **Add validation only if folder provided:**

  ```python
  if folder:
      folder_lower = folder.casefold()
      if folder_lower not in FOLDERS:  # Import FOLDERS from email module
          valid_folders = ", ".join(sorted(FOLDERS.keys()))
          raise ValueError(f"Invalid folder '{folder}'. Valid: {valid_folders}")
      folder_id = FOLDERS[folder_lower]
  ```

- [ ] **Testing:** None (search all), valid folder, invalid folder
- [ ] **Quality Gate:** `uv run pytest tests/ -k search_emails -v`

### 1d. Skip Other Folder Tools

**Reasoning:**

- `emailfolders_*` tools use folder **IDs** (not names) - no validation needed
- `file_list`, `folder_list` use OneDrive paths (validated in Section 3)
- File tools don't have folder name concept like email

## 2. Add Query Validation to Search Operations

**Current State Analysis:**

- ⚠️ **NO query validation** in any search tool - accepts any string including empty
- All 5 tools call `graph.search_query(query, entity_types, account_id, limit)`
- Graph API handles query, but empty queries may fail or return unexpected results

**Search Tools (5):**

1. `search_files` (search.py:22-51) - `query: str` (required)
2. `search_emails` (search.py:66-113) - `query: str` (required)
3. `search_events` (search.py:115-171) - `query: str` (required)
4. `search_contacts` (search.py:173-211) - `query: str` (required)
5. `search_unified` (search.py:214-252) - `query: str` (required), `entity_types: list[str] | None`

**Validation Strategy:**

- **Minimum length:** Query must have at least 1 non-whitespace character
- **Maximum length:** Graph API limits ~1000 chars (reasonable for search)
- **No special validation:** Graph handles search syntax (quotes, operators, etc.)
- **Entity types:** Validate for unified search only

### 2a. Add Query Validation to All Search Tools (except unified)

**Implementation Pattern:**

```python
# Add at start of each search function
query_stripped = query.strip()
if not query_stripped:
    raise ValueError("Search query cannot be empty or whitespace-only")
if len(query_stripped) > 1000:
    raise ValueError(f"Search query too long: {len(query_stripped)} chars (max: 1000)")

# Use query_stripped in Graph call
items = list(graph.search_query(query_stripped, entity_types, account_id, limit))
```

**Tools to Update:**

- [ ] **search_files:** Add query validation
- [ ] **search_emails:** Add query validation
- [ ] **search_events:** Add query validation
- [ ] **search_contacts:** Add query validation
- [ ] **Quality Gate:** `uv run pytest tests/ -k "search_files or search_emails or search_events or search_contacts" -v`

### 2b. Add Query + Entity Type Validation to `search_unified`

**Current Implementation:** search.py:214-252

- Lines 233-234: `if not entity_types: entity_types = ["message", "event", "driveItem"]`
- ⚠️ **No validation** of user-provided entity_types

**Implementation:**

- [ ] **Validate query (same as 2a)**
- [ ] **Validate entity_types:**

  ```python
  VALID_ENTITY_TYPES = {"message", "event", "driveItem"}

  if entity_types:
      # Normalize and validate
      entity_types_lower = [et.lower() for et in entity_types]
      invalid_types = set(entity_types_lower) - VALID_ENTITY_TYPES
      if invalid_types:
          raise ValueError(
              f"Invalid entity types: {invalid_types}. "
              f"Valid: {VALID_ENTITY_TYPES}"
          )
      # Use normalized types
      entity_types = list(set(entity_types_lower))
  else:
      entity_types = ["message", "event", "driveItem"]
  ```

- [ ] **Testing:**
  - Query: Empty, whitespace, valid, too long
  - Entity types: None (default), valid, invalid, mixed case
- [ ] **Quality Gate:** `uv run pytest tests/ -k search_unified -v`

### Testing Requirements for Section 2

- [ ] **Empty query:** `query=""` → ValueError
- [ ] **Whitespace query:** `query="   "` → ValueError
- [ ] **Valid query:** `query="test"` → Success
- [ ] **Long query:** `query="x" * 1001` → ValueError
- [ ] **Entity types (unified):** Invalid type → ValueError with valid options

## 3. Validate Path Parameters in Folder Operations

**Current State Analysis:**

- OneDrive path tools use `path: str` parameter
- Paths are used in Graph endpoints: `/me/drive/root:/{path}:/...`
- ⚠️ **Minimal validation** - some tools check for `/` but not comprehensive

**Path Parameter Tools (3 OneDrive tools):**

1. `file_list` (file.py:19-84) - `path: str = "/"`
2. `folder_list` (folder.py:7-47) - `path: str = "/"`
3. `folder_get` (folder.py:50-82) - `path: str | None`

**Note:** `folder_get_tree` and `emailfolders_*` use folder **IDs**, not paths

**Validation Strategy:**

- **Reuse validator:** `validate_onedrive_path()` from Critical Path Section 2
- **Requirements:** Must start with `/`, no `..`, no reserved chars
- **Decision:** Use existing validator if available, otherwise inline validation

### 3a. Add Path Validation to OneDrive Tools

**Implementation Decision:**

- **If `validate_onedrive_path` exists** (from Critical Path): Use it
- **If not implemented yet:** Add inline validation

**Inline Validation Pattern:**

```python
# Normalize path
path = path.strip()

# Validate format
if not path.startswith('/'):
    raise ValueError("OneDrive path must start with '/' (e.g., '/Documents/file.txt')")
if '..' in path:
    raise ValueError("OneDrive path cannot contain '..' (no directory traversal)")
if path != '/' and path.endswith('/'):
    path = path.rstrip('/')  # Normalize trailing slash

# Use validated path
```

**Tools to Update:**

- [ ] **file_list:** Add path validation (currently just checks for `/` at line 47-50)
- [ ] **folder_list:** Add path validation
- [ ] **folder_get:** Add path validation (optional param, validate if provided)
- [ ] **Testing:**
  - Valid: "/", "/Documents", "/folder/subfolder"
  - Invalid: "relative", "../parent", "~user"
  - Normalization: "/folder/" → "/folder"
- [ ] **Quality Gate:** `uv run pytest tests/ -k "file_list or folder" -v`

### 3b. Decision: Skip or Defer?

**Recommendation:** **OPTIONAL - Can defer or skip Phase 4 Section 3**

**Reasoning:**

1. Path validation **already covered** in Critical Path Section 2 for security
2. OneDrive paths have **low risk** (read-only operations)
3. Graph API provides good errors for invalid paths
4. Effort vs benefit: Minimal UX improvement

**If skipping:** Document in completion notes that path validation covered in Critical Path

## Phase 4 Completion Checklist

- [ ] **Section 1 Complete (Folder Choice Validation):**
  - [ ] 1a: email_list ✓
  - [ ] 1b: email_move ✓
  - [ ] 1c: search_emails ✓
  - [ ] 1d: Other folder tools (skipped - not applicable) ✓

- [ ] **Section 2 Complete (Query Validation):**
  - [ ] 2a: search_files, search_emails, search_events, search_contacts ✓
  - [ ] 2b: search_unified (query + entity_types) ✓

- [ ] **Section 3 Complete (Path Validation):**
  - [ ] 3a: OneDrive tools (file_list, folder_list, folder_get) ✓
  - [ ] OR: **Deferred** - Already covered in Critical Path Section 2 ✓

- [ ] **Quality Gate Passed:**
  - [ ] All ruff format/check/pyright passes
  - [ ] All tool-specific tests passing
  - [ ] Full test suite: `uv run pytest tests/ -v` passes
  - [ ] No regressions in integration tests

- [ ] **Documentation Updates:**
  - [ ] Update CHANGELOG.md with Phase 4 completion
  - [ ] Update tool docstrings with validation rules
  - [ ] Document any breaking changes (stricter validation)

- [ ] **Final Validation Program Completion:**
  - [ ] Update `reports/todo/PARAMETER_VALIDATION.md` marking ALL phases complete
  - [ ] Create final validation summary documenting:
    - Complete coverage across all 50 tools
    - All validators implemented and tested
    - Breaking changes summary
    - Validation coverage metrics
  - [ ] Celebrate! 🎉 All 4 phases complete

## Validation Program Summary

**Phase 1:** Critical Operations (7 tools) - Confirm validation refactoring
**Phase 2:** Dangerous Operations (6+ tools) - Recipient, body, response, attendee, datetime validation
**Phase 3:** Moderate Operations (17+ tools) - Update dict, limit bounds, datetime validation
**Phase 4:** Safe Operations (8+ tools) - Folder choice, query, path validation

**Total Coverage:** All 50 tools with appropriate validation for their risk level

**Priority Hierarchy:**

1. **Critical (destructive)** - Strictest validation, confirm required
2. **Dangerous (send/reply)** - Strong validation, prevent errors before sending
3. **Moderate (write)** - Systematic validation, consistent patterns
4. **Safe (read)** - UX improvements, fail fast with helpful errors
