# m365-mcp Write Tool Test Plan

**Account:** Robin.F.Collins@outlook.com  
**Server:** m365-mcp v0.2.3  
**Scope:** All non-read-only tools (✏️ write, 📧 send, 🔴 destructive)  
**Prerequisite:** Read-only audit completed 2026-05-30 — all baseline data confirmed.

---

## Guiding Principles

- **Cradle-to-grave per resource type.** Every test group creates, reads back, mutates, then destroys its own data. Nothing is left behind.
- **Canary values.** All test data uses a `[MCP-TEST]` prefix in names/subjects so it's identifiable and safe to bulk-delete if something goes wrong mid-run.
- **ID chaining.** Each create step captures the returned ID and passes it explicitly into subsequent update, get, and delete calls. No assumptions about auto-selection.
- **Confirm flags.** Tools that require `confirm: true` must have it set explicitly — never rely on defaults.
- **Ordering matters.** Within each group, steps are sequential and depend on prior results. Across groups, the order below is recommended but groups are otherwise independent.
- **Nothing external.** No emails are sent to third parties. All send/reply/forward tests target `Robin.F.Collins@outlook.com` (self-send).
- **Cache invalidation awareness.** After destructive operations, note that cached list results may be stale for up to the relevant TTL. Use `force_refresh: true` on verification reads.

---

## Group 1 — Calendar Event Lifecycle

**Rationale:** Lowest risk starting point. Creates isolated events, no external notifications if attendees field is left empty. Tests the full CRUD loop plus two calendar-management tools (respond, propose).

**Tools covered:** `calendar_create_event`, `calendar_get_event`, `calendar_update_event`, `calendar_respond_event`, `calendar_propose_new_time`, `calendar_forward_event`, `calendar_delete_event`

### Step 1.1 — Create a test event

```
tool: calendar_create_event
inputs:
  subject: "[MCP-TEST] Write Tool Audit Event"
  start:   "2026-06-10T10:00:00+09:30"
  end:     "2026-06-10T11:00:00+09:30"
  timezone: "Cen. Australia Standard Time"
  location: "MCP Test Lab (Virtual)"
  body:    "Created by automated write-tool audit. Safe to delete."
  attendees: (none — omit to avoid sending invitations)
```

**Expected:** Event object returned with a valid `id`. Capture this as `EVENT_ID`.

**Verify:** Call `calendar_get_event(EVENT_ID)` — confirm subject, start/end, location all match.

---

### Step 1.2 — Update the event

```
tool: calendar_update_event
inputs:
  event_id: EVENT_ID
  updates:
    subject:  "[MCP-TEST] Write Tool Audit Event — UPDATED"
    location: "MCP Test Lab (Updated Location)"
    body:     "Updated by write-tool audit step 1.2."
```

**Expected:** Updated event object returned. Subject and location reflect changes.

**Verify:** Call `calendar_get_event(EVENT_ID)` again — confirm both changed fields.

---

### Step 1.3 — Forward the event

```
tool: calendar_forward_event
inputs:
  event_id: EVENT_ID
  to:       "Robin.F.Collins@outlook.com"
  message:  "MCP test forward — safe to ignore."
  confirm:  true
```

**Expected:** Status confirmation (HTTP 202 / success). A forwarded invitation email should appear in Inbox.

**Verify:** `email_list(folder=inbox, limit=5)` — look for a forwarded calendar item from self. Note: this does not add an attendee; it merely sends a copy.

---

### Step 1.4 — Respond to event (accept)

> Note: `calendar_respond_event` is only meaningful when you are an *attendee*, not the organiser. Since this event was self-created without attendees, this step tests the tool call mechanics and expected error/no-op behaviour.

```
tool: calendar_respond_event
inputs:
  event_id: EVENT_ID
  response: "accept"
  message:  "MCP test accept response."
```

**Expected:** Either a success status (organiser auto-accept), or a meaningful error indicating the user is the organiser. Either outcome is informative.

---

### Step 1.5 — Propose new time

> Same caveat as 1.4 — meaningful only as an attendee. Test for graceful handling.

```
tool: calendar_propose_new_time
inputs:
  event_id:       EVENT_ID
  proposed_start: "2026-06-10T14:00:00+09:30"
  proposed_end:   "2026-06-10T15:00:00+09:30"
  message:        "MCP test time proposal."
```

**Expected:** Success or a clear error explaining organiser-cannot-propose-to-self. Document actual behaviour.

---

### Step 1.6 — Delete the event

```
tool: calendar_delete_event
inputs:
  event_id:          EVENT_ID
  send_cancellation: false    ← no attendees, suppress the notification
  confirm:           true
```

**Expected:** 204 No Content / status confirmation.

**Verify:** `calendar_get_event(EVENT_ID)` — expect a 404 / not-found error, confirming deletion.

---

## Group 2 — Calendar Management (Create & Delete Calendar)

**Rationale:** Tests the calendar container lifecycle, separate from event lifecycle. Kept short — a calendar with no events is trivially deletable.

**Tools covered:** `calendar_create_calendar`, `calendar_delete_calendar`

### Step 2.1 — Create a test calendar

```
tool: calendar_create_calendar
inputs:
  name: "[MCP-TEST] Audit Calendar"
```

**Expected:** Calendar object returned with `id`. Capture as `CAL_ID`.

**Verify:** `calendar_list_calendars()` — confirm `[MCP-TEST] Audit Calendar` appears in the list.

---

### Step 2.2 — Delete the test calendar

```
tool: calendar_delete_calendar
inputs:
  calendar_id: CAL_ID
  confirm:     true
```

**Expected:** Status confirmation.

**Verify:** `calendar_list_calendars()` — confirm calendar is gone.

---

## Group 3 — Email Lifecycle (Draft → Send → Read → Flag → Move → Delete)

**Rationale:** Tests the full email workflow without touching any real contacts. All sends go to self. Tests build on each other in a deliberate sequence that mirrors real usage.

**Tools covered:** `email_create_draft`, `email_send`, `email_update`, `email_mark_read`, `email_flag`, `email_add_category`, `email_archive`, `email_move`, `email_reply`, `email_reply_all`, `email_forward`, `email_delete`

### Step 3.1 — Create a draft

```
tool: email_create_draft
inputs:
  to:      "Robin.F.Collins@outlook.com"
  subject: "[MCP-TEST] Write Tool Audit Email"
  body:    "This is a draft created by the m365-mcp write-tool audit. Step 3.1."
```

**Expected:** Draft message object returned with `id`. Capture as `DRAFT_ID`.

**Verify:** `email_list(folder=drafts, limit=5)` — confirm draft appears.

---

### Step 3.2 — Send the draft (via email_send, not from draft)

> We send a fresh email (not the draft) because `email_send` creates and sends in one step. The draft from 3.1 is cleaned up separately in 3.3.

```
tool: email_send
inputs:
  to:      "Robin.F.Collins@outlook.com"
  subject: "[MCP-TEST] Write Tool Audit — Sent Email"
  body:    "Sent by m365-mcp write-tool audit. Step 3.2."
  confirm: true
```

**Expected:** Status confirmation. Email arrives in Inbox within seconds.

**Verify:** `email_list(folder=inbox, limit=5, force_refresh=true)` — confirm subject appears. Capture arrived email `id` as `EMAIL_ID`.

---

### Step 3.3 — Delete the unused draft

```
tool: email_delete
inputs:
  email_id: DRAFT_ID
  confirm:  true
```

**Expected:** Status confirmation.

**Verify:** `email_list(folder=drafts, limit=5)` — confirm draft is gone.

---

### Step 3.4 — Mark as unread

```
tool: email_mark_read
inputs:
  email_id: EMAIL_ID
  is_read:  false
```

**Expected:** Updated email object with `isRead: false`.

**Verify:** `email_get(EMAIL_ID)` — confirm `isRead` is false.

---

### Step 3.5 — Mark as read

```
tool: email_mark_read
inputs:
  email_id: EMAIL_ID
  is_read:  true
```

**Expected:** Updated email object with `isRead: true`.

---

### Step 3.6 — Flag the email

```
tool: email_flag
inputs:
  email_id:    EMAIL_ID
  flag_status: "flagged"
```

**Expected:** Updated email object with `flag.flagStatus: "flagged"`.

**Verify:** `email_get(EMAIL_ID)` — confirm flag status.

---

### Step 3.7 — Add a category

```
tool: email_add_category
inputs:
  email_id:   EMAIL_ID
  categories: ["MCP-Test"]
```

**Expected:** Updated email object with `categories: ["MCP-Test"]`.

> Note: Outlook categories must exist in the account's master category list to display with colour, but the API accepts arbitrary strings.

---

### Step 3.8 — Update via email_update (importance)

```
tool: email_update
inputs:
  email_id: EMAIL_ID
  updates:
    importance: "high"
```

**Expected:** Updated email with `importance: "high"`. Tests the generic update path for properties not covered by the convenience wrappers.

---

### Step 3.9 — Reply to the email

```
tool: email_reply
inputs:
  email_id: EMAIL_ID
  body:     "MCP test reply — step 3.9."
  confirm:  true
```

**Expected:** Status confirmation. A reply appears in Inbox.

**Verify:** `email_list(folder=inbox, limit=5, force_refresh=true)` — confirm reply thread. Capture reply `id` as `REPLY_ID`.

---

### Step 3.10 — Reply-all to the email

```
tool: email_reply_all
inputs:
  email_id: EMAIL_ID
  body:     "MCP test reply-all — step 3.10."
  confirm:  true
```

**Expected:** Status confirmation. Another reply arrives (to all recipients — only self in this case, so identical behaviour to reply).

---

### Step 3.11 — Forward the email

```
tool: email_forward
inputs:
  email_id: EMAIL_ID
  to:       "Robin.F.Collins@outlook.com"
  body:     "MCP test forward — step 3.11."
  confirm:  true
```

**Expected:** Status confirmation. A forwarded copy arrives in Inbox. Capture `id` as `FWD_ID`.

---

### Step 3.12 — Move the email to a test folder

> Uses the Drafts folder as a temporary holding location (convenient and reversible).

```
tool: email_move
inputs:
  email_id:           EMAIL_ID
  destination_folder: "drafts"
```

**Expected:** Status confirmation with new email ID (may change on move). Capture new ID as `EMAIL_ID_MOVED`.

**Verify:** `email_list(folder=drafts, limit=5)` — confirm email present.

---

### Step 3.13 — Archive the moved email

```
tool: email_archive
inputs:
  email_id: EMAIL_ID_MOVED
```

**Expected:** Status confirmation. Email moves to Archive folder.

**Verify:** `email_list(folder=archive, limit=5)` — confirm email present.

---

### Step 3.14 — Delete all test emails

Delete the original sent email, reply, reply-all result, forward, and the archived moved copy. Repeat for each captured ID:

```
tool: email_delete
inputs:
  email_id: <each test email ID in turn>
  confirm:  true
```

**Expected:** Status confirmation for each.

**Verify:** `search_emails(query="MCP-TEST Write Tool Audit")` — expect zero results.

---

## Group 4 — Email Folders Lifecycle

**Rationale:** Tests folder create/rename/move/empty/delete. Uses a dedicated parent folder structure created and destroyed within this group.

**Tools covered:** `emailfolders_create`, `emailfolders_rename`, `emailfolders_move`, `emailfolders_mark_all_as_read`, `emailfolders_empty`, `emailfolders_delete`

### Step 4.1 — Create a parent test folder

```
tool: emailfolders_create
inputs:
  display_name:    "[MCP-TEST] Audit Parent"
  parent_folder_id: (none — root level)
```

**Expected:** Folder object with `id`. Capture as `FOLDER_PARENT_ID`.

---

### Step 4.2 — Create a child test folder

```
tool: emailfolders_create
inputs:
  display_name:    "[MCP-TEST] Audit Child"
  parent_folder_id: FOLDER_PARENT_ID
```

**Expected:** Folder object with `id`. Capture as `FOLDER_CHILD_ID`.

**Verify:** `emailfolders_list(parent_folder_id=FOLDER_PARENT_ID)` — confirm child appears.

---

### Step 4.3 — Rename the child folder

```
tool: emailfolders_rename
inputs:
  folder_id:       FOLDER_CHILD_ID
  new_display_name: "[MCP-TEST] Audit Child — RENAMED"
```

**Expected:** Updated folder object with new `displayName`.

---

### Step 4.4 — Move a test email into the child folder, then mark all as read

First send a self-email and move it into `FOLDER_CHILD_ID` (use `email_move` with `folder_id` parameter), then:

```
tool: emailfolders_mark_all_as_read
inputs:
  folder_id: FOLDER_CHILD_ID
```

**Expected:** Status confirmation with count of messages updated.

**Verify:** `emailfolders_get(FOLDER_CHILD_ID)` — `unreadItemCount` should be 0.

---

### Step 4.5 — Move the child folder under a different parent

```
tool: emailfolders_move
inputs:
  folder_id:           FOLDER_CHILD_ID
  destination_folder_id: (Inbox folder ID — temporarily re-parent it)
```

**Expected:** Updated folder object with new `parentFolderId`.

**Verify:** `emailfolders_list(parent_folder_id=<Inbox ID>)` — confirm child appears there.

Move it back to `FOLDER_PARENT_ID` immediately after verification.

---

### Step 4.6 — Empty the child folder

```
tool: emailfolders_empty
inputs:
  folder_id: FOLDER_CHILD_ID
  confirm:   true
```

**Expected:** Status confirmation with message count deleted.

**Verify:** `emailfolders_get(FOLDER_CHILD_ID)` — `totalItemCount` should be 0.

---

### Step 4.7 — Delete the child folder

```
tool: emailfolders_delete
inputs:
  folder_id: FOLDER_CHILD_ID
  confirm:   true
```

**Expected:** Status confirmation.

---

### Step 4.8 — Delete the parent folder

```
tool: emailfolders_delete
inputs:
  folder_id: FOLDER_PARENT_ID
  confirm:   true
```

**Expected:** Status confirmation.

**Verify:** `emailfolders_list()` — neither folder should appear.

---

## Group 5 — Email Rules Lifecycle

**Rationale:** Rules are purely server-side configuration — no emails sent, no external effects. Safe to create and delete. Tests ordering tools as a bonus.

**Tools covered:** `emailrules_create`, `emailrules_get`, `emailrules_update`, `emailrules_move_top`, `emailrules_move_up`, `emailrules_move_down`, `emailrules_move_bottom`, `emailrules_delete`

### Step 5.1 — Create a test rule

```
tool: emailrules_create
inputs:
  display_name: "[MCP-TEST] Audit Rule"
  conditions:
    subjectContains: ["[MCP-TEST-RULE-TRIGGER]"]
  actions:
    markAsRead: true
  is_enabled:  true
  sequence:    999    ← high number to avoid interfering with real rules
```

**Expected:** Rule object returned with `id`. Capture as `RULE_ID`.

**Verify:** `emailrules_list()` — confirm rule appears at sequence 999 (or wherever the server places it).

---

### Step 5.2 — Get the rule

```
tool: emailrules_get
inputs:
  rule_id: RULE_ID
```

**Expected:** Full rule object. This is the primary opportunity to test `emailrules_get` directly (was skipped in the read-only audit).

---

### Step 5.3 — Update the rule

```
tool: emailrules_update
inputs:
  rule_id: RULE_ID
  (update body — exact parameters TBC from tool schema)
  is_enabled: false    ← disable it as a safe mutation
```

**Expected:** Updated rule object with `isEnabled: false`.

**Verify:** `emailrules_get(RULE_ID)` — confirm disabled.

---

### Step 5.4 — Test ordering tools

Run all four ordering calls in sequence, verifying sequence number changes after each:

```
tool: emailrules_move_top    → rule_id: RULE_ID
tool: emailrules_move_down   → rule_id: RULE_ID
tool: emailrules_move_up     → rule_id: RULE_ID
tool: emailrules_move_bottom → rule_id: RULE_ID
```

After each call, run `emailrules_list()` and check that the rule's `sequence` value changes as expected.

> ⚠️ Moving to top (sequence 1) temporarily promotes the test rule above all real rules. Immediately follow with `move_bottom` or `move_down` to restore safe ordering.

---

### Step 5.5 — Delete the rule

```
tool: emailrules_delete
inputs:
  rule_id: RULE_ID
  confirm: true
```

**Expected:** Status confirmation.

**Verify:** `emailrules_list()` — rule absent.

---

## Group 6 — Contacts Lifecycle

**Rationale:** Contact operations are entirely local (no emails sent). Safe CRUD loop with an export verification and list cleanup.

**Tools covered:** `contact_create`, `contact_update`, `contact_delete`, `contact_create_list`, `contact_add_to_list`

### Step 6.1 — Create a test contact

```
tool: contact_create
inputs:
  given_name: "MCPTest"
  surname:    "AuditContact"
  email_addresses: ["mcp-test-audit@example.com"]
  phone_numbers:
    mobile: "+61400000000"
```

**Expected:** Contact object with `id`. Capture as `CONTACT_ID`.

**Verify:** `contact_get(CONTACT_ID)` — confirm all fields present.

---

### Step 6.2 — Update the contact

```
tool: contact_update
inputs:
  contact_id: CONTACT_ID
  updates:
    jobTitle:    "Test Automation Bot"
    companyName: "m365-mcp Audit"
    department:  "Write Tool Testing"
```

**Expected:** Updated contact object with new fields.

**Verify:** `contact_get(CONTACT_ID)` — confirm updated fields.

---

### Step 6.3 — Create a test contact list

```
tool: contact_create_list
inputs:
  list_name: "[MCP-TEST] Audit List"
```

**Expected:** Contact folder object with `id`. Capture as `LIST_ID`.

---

### Step 6.4 — Add contact to list

```
tool: contact_add_to_list
inputs:
  contact_id: CONTACT_ID
  list_id:    LIST_ID
```

**Expected:** Copy of contact in the list returned.

**Verify:** `contact_list(folder_id=LIST_ID)` (if supported) or `search_contacts(query="MCPTest")` — confirm contact appears in list context.

---

### Step 6.5 — Delete the test contact

```
tool: contact_delete
inputs:
  contact_id: CONTACT_ID
  confirm:    true
```

**Expected:** Status confirmation.

**Verify:** `contact_get(CONTACT_ID)` — expect not-found error.

> Note: The copy added to the list in step 6.4 may need separate deletion. Investigate whether deleting the source contact cascades to list copies.

---

## Group 7 — OneDrive Files Lifecycle

**Rationale:** OneDrive operations are isolated to your own storage. Tests cover file upload, update, copy, move, rename, share, and delete. Uses a small text file to keep size trivial.

**Tools covered:** `file_create`, `file_update`, `file_copy`, `file_move`, `file_rename`, `file_share`, `file_download_url` (retry), `file_delete`, `folder_create`, `folder_rename`, `folder_move`, `folder_delete`

### Step 7.1 — Create a test folder

```
tool: folder_create
inputs:
  name:             "[MCP-TEST] Audit Folder"
  parent_folder_id: (none — root)
```

**Expected:** Folder object with `id`. Capture as `TEST_FOLDER_ID`.

---

### Step 7.2 — Create a second folder (for move testing)

```
tool: folder_create
inputs:
  name: "[MCP-TEST] Audit Folder B"
```

Capture as `TEST_FOLDER_B_ID`.

---

### Step 7.3 — Upload a test file

```
tool: file_create
inputs:
  local_file_path: (a small local text file, e.g. a temp .txt created via bash_tool)
  onedrive_path:   "/[MCP-TEST] Audit Folder/mcp_test_file.txt"
  account_id:      ...
```

**Pre-step:** Use `bash_tool` to create a small file: `echo "MCP write tool audit test file." > /tmp/mcp_test.txt`

**Expected:** File metadata object with `id`. Capture as `FILE_ID`.

**Verify:** `file_list(path="/[MCP-TEST] Audit Folder")` — confirm file present.

---

### Step 7.4 — Get download URL (retry from read-only audit failure)

```
tool: file_download_url
inputs:
  file_id: FILE_ID
```

**Expected:** This time the file was created directly (not via search), so the download URL should be populated. If it still fails, the issue is account-type-wide, not search-specific.

---

### Step 7.5 — Update (replace) the file content

```
tool: file_update
inputs:
  file_id:        FILE_ID
  local_file_path: (updated temp file — e.g. "MCP write tool audit — UPDATED content.")
```

**Expected:** Updated file metadata. Modified timestamp should advance.

**Verify:** `file_download_url(FILE_ID)` — download and confirm updated content.

---

### Step 7.6 — Rename the file

```
tool: file_rename
inputs:
  file_id:  FILE_ID
  new_name: "mcp_test_file_renamed.txt"
```

**Expected:** Updated file object with new `name`.

---

### Step 7.7 — Copy the file to Folder B

```
tool: file_copy
inputs:
  file_id:              FILE_ID
  destination_folder_id: TEST_FOLDER_B_ID
  new_name:             "mcp_test_file_copy.txt"
```

**Expected:** Copy operation status (may be async — monitor with `cache_task_get_status` if a task ID is returned).

**Verify:** `file_list(folder_id=TEST_FOLDER_B_ID)` — confirm copy present. Capture copy ID as `FILE_COPY_ID`.

---

### Step 7.8 — Move the original file to Folder B

```
tool: file_move
inputs:
  file_id:              FILE_ID
  destination_folder_id: TEST_FOLDER_B_ID
```

**Expected:** Updated file object with new `parentReference`.

**Verify:** `file_list(folder_id=TEST_FOLDER_B_ID)` — both original and copy now present.

---

### Step 7.9 — Create a sharing link

```
tool: file_share
inputs:
  file_id:         FILE_ID
  permission_type: "view"
  scope:           "anonymous"
```

**Expected:** Sharing link object with `webUrl`. Note the link but do not distribute it.

> ⚠️ Anonymous links are publicly accessible. Revoke or delete the file promptly after this step.

---

### Step 7.10 — Rename Folder A

```
tool: folder_rename
inputs:
  folder_id: TEST_FOLDER_ID
  new_name:  "[MCP-TEST] Audit Folder — RENAMED"
```

**Expected:** Updated folder object with new name.

---

### Step 7.11 — Move Folder A under Folder B

```
tool: folder_move
inputs:
  folder_id:             TEST_FOLDER_ID
  destination_folder_id: TEST_FOLDER_B_ID
```

**Expected:** Updated folder object with new `parentReference`.

Move it back to root immediately after verification.

---

### Step 7.12 — Delete all test files and folders

```
# Delete copy file
tool: file_delete → file_id: FILE_COPY_ID, confirm: true

# Delete original file (now in Folder B)
tool: file_delete → file_id: FILE_ID, confirm: true

# Delete Folder A (now empty after file deletion)
tool: folder_delete → folder_id: TEST_FOLDER_ID, confirm: true

# Delete Folder B (now empty)
tool: folder_delete → folder_id: TEST_FOLDER_B_ID, confirm: true
```

**Verify:** `folder_list()` — neither test folder present.

---

## Group 8 — Account Authentication Flow

**Rationale:** `account_authenticate` and `account_complete_auth` are the only tools that haven't been covered. These initiate and complete a device-flow OAuth login for adding a *new* Microsoft account.

**Tools covered:** `account_authenticate`, `account_complete_auth`

> ⚠️ **This group is advisory only — do not run unless you intend to add a second Microsoft account.** The device flow generates a real verification URL and code. There is no dry-run or cancel mechanism once initiated; the code simply expires after 15 minutes if unused.

### Step 8.1 — Initiate device flow

```
tool: account_authenticate
inputs: (none)
```

**Expected:** Returns a `user_code`, `verification_url`, `expires_in`, and `_flow_cache` string. Do not navigate to the URL unless adding a real account.

### Step 8.2 — Complete authentication

```
tool: account_complete_auth
inputs:
  flow_cache: <value from step 8.1>
```

**Expected (if code used):** New account object returned and visible in `account_list`.  
**Expected (if code not used / expired):** Pending or expired status returned gracefully.

**Recommendation:** Test step 8.1 only (observe the returned structure), then let the code expire naturally. This confirms the tool calls and returns data without actually adding an account.

---

## Group 9 — Cache Management (Write Operations)

**Rationale:** `cache_invalidate` is the only cache write tool. Safe to run — it clears cached data, forcing the next read to re-fetch from the API. No data is modified or deleted; it just resets TTLs.

**Tools covered:** `cache_invalidate`

### Step 9.1 — Invalidate email list cache for the account

```
tool: cache_invalidate
inputs:
  pattern:    "email_list:*"
  account_id: "Robin.F.Collins@outlook.com"
  reason:     "mcp-write-tool-audit-test"
```

**Expected:** Returns `entries_deleted` count, pattern, account_id, reason, and timestamp.

**Verify:** `cache_get_stats()` — email_list entry count should drop to 0. Next `email_list()` call will show `cache_status: miss`.

### Step 9.2 — Invalidate all cache

```
tool: cache_invalidate
inputs:
  pattern: "*"
  reason:  "mcp-write-tool-audit-full-clear"
```

**Expected:** Higher `entries_deleted` count covering all cached resources.

---

## Execution Order (Recommended)

| Order | Group | Risk | Est. Steps |
|------:|-------|------|:----------:|
| 1 | Group 9 — Cache Invalidate | Minimal | 2 |
| 2 | Group 5 — Email Rules | Low | 8 |
| 3 | Group 6 — Contacts | Low | 5 |
| 4 | Group 2 — Calendar (calendar CRUD) | Low | 2 |
| 5 | Group 1 — Calendar Events | Medium | 6 |
| 6 | Group 4 — Email Folders | Medium | 8 |
| 7 | Group 7 — OneDrive Files | Medium | 12 |
| 8 | Group 3 — Email Lifecycle | Medium | 14 |
| 9 | Group 8 — Auth Flow | Advisory | 1–2 |

---

## Cleanup Checklist

After all groups complete, verify the following are absent:

- [ ] No calendar events with `[MCP-TEST]` in subject
- [ ] No calendars named `[MCP-TEST] Audit Calendar`
- [ ] No emails with `[MCP-TEST]` in subject (inbox, sent, drafts, archive)
- [ ] No email folders named `[MCP-TEST]`
- [ ] No email rules named `[MCP-TEST]`
- [ ] No contacts with given_name `MCPTest`
- [ ] No OneDrive folders named `[MCP-TEST]`
- [ ] No OneDrive files named `mcp_test_file*`
- [ ] Anonymous sharing links revoked (or files deleted)

---

## Known Unknowns / Things to Watch

- **`emailrules_update` parameter schema** — the exact update payload structure was not fully confirmed during the read-only audit. Inspect the tool schema carefully before step 5.3.
- **`contact_add_to_list` cascade behaviour** — it is unclear whether deleting the source contact removes the copy from the list, or whether the list copy must be deleted independently.
- **`file_copy` async behaviour** — the Graph API copy operation may return a `202 Accepted` with a monitor URL rather than immediate metadata. The server may wrap this; behaviour TBC.
- **`file_download_url` on personally-created files** — the read-only audit showed this fails on search-sourced IDs. Step 7.4 tests whether directly-created file IDs behave differently.
- **`calendar_respond_event` and `calendar_propose_new_time` on organiser-owned events** — expected to fail gracefully. Document actual error messages for completeness.
- **Sharing link revocation** — `file_share` creates anonymous links but there is no `file_unshare` tool in the m365-mcp schema. Deleting the file is the safest cleanup path.
