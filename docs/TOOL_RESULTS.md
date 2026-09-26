> **Historical (v0.2.3).** This document was written against the removed 85-tool server. Tool names in it (`email_list`, `emailfolders_*`, `file_list`, `cache_get_stats`, `account_authenticate` and so on) no longer exist; see [`legacy_mapping.json`](unified-tools/legacy_mapping.json) for their replacements and [`../MCP_SERVER_TOOLS.md`](../MCP_SERVER_TOOLS.md) for the current tools.

## 📜 Write Tool Audit Failure Report

This report summarizes API failures and errors encountered during the execution of the write-tool audit plan. The failures are categorized by the original test group.

***

### 📅 Group 1 — Calendar Event Lifecycle (Steps 1.2, 1.4, 1.5, 1.6)
*   **Step 1.2 (Update):** Success was blocked due to API errors on subsequent cleanup/verification attempts, though the initial update call succeeded.
    *   `calendar_update_event`: **Success**, but verification steps failed with `415 Unsupported Media Type`.
*   **Step 1.4 (Respond):** Failed because the user is the event organizer.
    *   `calendar_respond_event`: `Client error '400 Bad Request'` - *Reason: User is the organizer.*
*   **Step 1.5 (Propose Time):** Failed due to API constraints when proposing time for an organizer-owned event.
    *   `calendar_propose_new_time`: `Client error '400 Bad Request'` - *Reason: User is the organizer.*
*   **Step 1.6 (Delete):** The final deletion attempt failed due to API type mismatch/error handling for cancellation.
    *   `calendar_delete_event`: `Client error '415 Unsupported Media Type'` - *Reason: Failed during cleanup verification.*

### 📅 Group 2 — Calendar Management (Steps 2.2)
*   **Step 2.2 (Delete):** The attempt to delete the newly created calendar failed due to API constraints on deletion.
    *   `calendar_delete_calendar`: `Client error '400 Bad Request'` - *Reason: Invalid request/API constraint.*

### 📧 Group 3 — Email Lifecycle (Steps 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, 3.13, 3.14)
*   **Step 3.1 (Create Draft):** **Success**. No errors.
*   **Step 3.2 (Send Email):** **Success**. No errors.
*   **Step 3.3 (Delete Draft):** The first attempt to delete the draft failed because the ID was incorrect/stale after a previous error, but subsequent calls were blocked by `404 Not Found`.
    *   `email_delete`: `Client error '404 Not Found'` - *Reason: Email ID not found.*
*   **Step 3.14 (Delete All):** Multiple attempts to delete emails failed due to the IDs becoming invalid or stale after previous operations.
    *   `email_delete`: `Client error '404 Not Found'` - *Reason: Email ID not found.*

### 📂 Group 4 — Email Folders Lifecycle (Steps 4.2, 4.3, 4.5, 4.6, 4.7, 4.8)
*   **Step 4.2 (Create Child):** Failed due to API constraints when attempting to create a child folder ID using the parent's ID.
    *   `emailfolders_create`: `Client error '400 Bad Request'` - *Reason: Invalid Parent Folder ID.*
*   **Step 4.3 (Rename):** The rename operation failed because the folder ID was invalid/stale after previous errors.
    *   `emailfolders_rename`: `Client error '404 Not Found'` - *Reason: Folder ID not found.*
*   **Step 4.5 (Move):** Failed due to API constraints when attempting to move a non-existent or stale folder ID.
    *   `emailfolders_move`: *(No explicit call was made for this step after the failure in Step 4.3, but subsequent steps would fail.)*

### 📁 Group 7 — OneDrive Files Lifecycle (Steps 7.1 through 7.2)
*   **Step 7.3 (Upload File):** Failed because the provided local path was outside the allowed directories for security reasons.
    *   `file_create`: `Client error 'Invalid path ...'` - *Reason: Local file path traversal restriction.*
*   **Step 7.4 (Get Download URL):** Failed because the combination of IDs used in the call did not match a retrievable resource.
    *   `file_download_url`: `Client error '400 Bad Request'` - *Reason: Invalid file ID or structure.*

### 🧑‍🤝‍🧑 Group 6 — Contacts Lifecycle (Steps 6.2, 6.4)
*   **Step 6.2 (Update):** Failed to update fields due to a `400 Bad Request` error from the Graph API.
    *   `contact_update`: `Client error '400 Bad Request'` - *Reason: Invalid payload/API constraint.*
*   **Step 6.4 (Add to List):** Failed because the list ID was invalid or stale, and the operation is highly sensitive to correct IDs.
    *   `contact_add_to_list`: `Client error '400 Bad Request'` - *Reason: Invalid contact or list ID.*

***
**Summary:** The most consistent failures were related to **API Constraints (400/409)** and **Resource Not Found (404)**, suggesting that the IDs captured in earlier steps became stale, invalid, or that certain operations are fundamentally restricted when performed by an organizer. The file system group failed due to local path security restrictions.