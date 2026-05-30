# MCP Tools Reference

This document lists all tools made available by the installed Model Context Protocol (MCP) servers, including their descriptions and input parameters.

## chrome-devtools-mcp

### `click`

Clicks on the provided element

This tool does not take any parameters.

### `close_page`

Closes the page by its index. The last open page cannot be closed.

This tool does not take any parameters.

### `drag`

Drag an element onto another element

This tool does not take any parameters.

### `emulate`

Emulates various features on the selected page.

This tool does not take any parameters.

### `evaluate_script`

Evaluate a JavaScript function inside the currently selected page. Returns the response as JSON,
so returned values have to be JSON-serializable.

This tool does not take any parameters.

### `fill`

Type text into an input, text area or select an option from a <select> element.

This tool does not take any parameters.

### `fill_form`

Fill out multiple form elements (inputs, selects, checkboxes, radios) at once. ALWAYS prefer this tool over multiple individual 'fill' or 'click' calls when interacting with forms. It is significantly faster, more reliable, and reduces turn count. Example: Fill username, password, and check "Remember Me" in one call.

This tool does not take any parameters.

### `get_console_message`

Gets a console message by its ID. You can get all messages by calling list_console_messages.

This tool does not take any parameters.

### `get_network_request`

Gets a network request by an optional reqid, if omitted returns the currently selected request in the DevTools Network panel.

This tool does not take any parameters.

### `handle_dialog`

If a browser dialog was opened, use this command to handle it

This tool does not take any parameters.

### `hover`

Hover over the provided element

This tool does not take any parameters.

### `lighthouse_audit`

Get Lighthouse score and reports for accessibility, SEO, best practices, and agentic browsing. This excludes performance. For performance audits, run performance_start_trace

This tool does not take any parameters.

### `list_console_messages`

List all console messages for the currently selected page since the last navigation.

This tool does not take any parameters.

### `list_network_requests`

List all requests for the currently selected page since the last navigation.

This tool does not take any parameters.

### `list_pages`

Get a list of pages open in the browser.

This tool does not take any parameters.

### `navigate_page`

Go to a URL, or back, forward, or reload. Use project URL if not specified otherwise.

This tool does not take any parameters.

### `new_page`

Open a new tab and load a URL. Use project URL if not specified otherwise.

This tool does not take any parameters.

### `performance_analyze_insight`

Provides more detailed information on a specific Performance Insight of an insight set that was highlighted in the results of a trace recording.

This tool does not take any parameters.

### `performance_start_trace`

Start a performance trace on the selected webpage. Use to find frontend performance issues, Core Web Vitals (LCP, INP, CLS), and improve page load speed.

This tool does not take any parameters.

### `performance_stop_trace`

Stop the active performance trace recording on the selected webpage.

This tool does not take any parameters.

### `press_key`

Press a key or key combination. Use this when other input methods like fill() cannot be used (e.g., keyboard shortcuts, navigation keys, or special key combinations).

This tool does not take any parameters.

### `resize_page`

Resizes the selected page's window so that the page has specified dimension

This tool does not take any parameters.

### `select_page`

Select a page as a context for future tool calls.

This tool does not take any parameters.

### `take_heapsnapshot`

Capture a heap snapshot of the currently selected page. Use to analyze the memory distribution of JavaScript objects and debug memory leaks.

This tool does not take any parameters.

### `take_screenshot`

Take a screenshot of the page or element.

This tool does not take any parameters.

### `take_snapshot`

Take a text snapshot of the currently selected page based on the a11y tree. The snapshot lists page elements along with a unique
identifier (uid). Always use the latest snapshot. Prefer taking a snapshot over taking a screenshot. The snapshot indicates the element selected
in the DevTools Elements panel (if any).

This tool does not take any parameters.

### `type_text`

Type text using keyboard into a previously focused input

This tool does not take any parameters.

### `upload_file`

Upload a file through a provided element.

This tool does not take any parameters.

### `wait_for`

Wait for the specified text to appear on the selected page.

This tool does not take any parameters.

## m365-mcp

### `account_authenticate`

✏️ Authenticate a new Microsoft account using device flow (requires user confirmation recommended)

Initiates device flow authentication for adding a new Microsoft account.
Returns authentication instructions with a device code and verification URL.

The user must:
1. Visit the verification URL
2. Enter the device code
3. Sign in with their Microsoft account
4. Use account_complete_auth to finish the process

This tool does not take any parameters.

### `account_complete_auth`

✏️ Complete device flow authentication (requires user confirmation recommended)

Completes the authentication process after the user has entered the device code
at the verification URL.

Args:
    flow_cache: The flow data returned from account_authenticate (the _flow_cache field)

Returns:
    Account information if authentication was successful, or pending status if
    the user hasn't completed authentication yet.

This tool does not take any parameters.

### `account_list`

📖 List all signed-in Microsoft accounts (read-only, safe for unsupervised use)

Returns a list of authenticated Microsoft accounts with their usernames, account IDs,
and account types (personal or work/school).

Returns:
    List of account dictionaries with:
    - username: Account email/username
    - account_id: Unique account identifier
    - account_type: "personal", "work_school", or "unknown"

Example:
    [
        {
            "username": "user@outlook.com",
            "account_id": "abc123...",
            "account_type": "personal"
        },
        {
            "username": "user@contoso.com",
            "account_id": "def456...",
            "account_type": "work_school"
        }
    ]

This tool does not take any parameters.

### `cache_get_stats`

📖 Get cache statistics and performance metrics (read-only, safe for unsupervised use)

Retrieve comprehensive statistics about the cache system including size,
hit rates, entry counts, and performance metrics.

Returns:
    Dictionary containing cache statistics:
    - total_entries: Total number of cached entries
    - total_size_bytes: Total size of cache in bytes
    - total_size_mb: Total size in megabytes
    - size_percentage: Percentage of max cache size used
    - hit_count: Number of cache hits
    - miss_count: Number of cache misses
    - hit_rate: Cache hit rate (0.0-1.0)
    - entries_by_resource_type: Count of entries per resource type
    - average_entry_size_bytes: Average size per entry
    - compressed_entries: Number of compressed entries
    - compression_ratio: Average compression ratio
    - oldest_entry_age_hours: Age of oldest entry in hours
    - cleanup_triggered: Whether cleanup threshold has been reached
    - last_cleanup: Timestamp of last cleanup operation

Example:
    stats = cache_get_stats()
    print(f"Cache hit rate: {stats['hit_rate']:.2%}")
    print(f"Cache size: {stats['total_size_mb']:.2f} MB")
    print(f"Size used: {stats['size_percentage']:.1f}%")

This tool does not take any parameters.

### `cache_invalidate`

✏️ Invalidate cache entries matching a pattern (requires user confirmation recommended)

Delete cache entries that match the specified pattern. This is useful for
forcing fresh data retrieval or clearing stale cache entries.

Args:
    pattern: Pattern to match cache keys (supports wildcards):
            - "*" matches any characters within a segment
            - Use "email_list:*" to invalidate all email lists
            - Use "email_list:account@example.com:*" for specific account
            - Use "folder_get_tree:*" to invalidate all folder trees
    account_id: Optional account ID to scope invalidation (None = all accounts).
    reason: Reason for invalidation (for audit logging).

Returns:
    Dictionary containing:
    - entries_deleted: Number of cache entries deleted
    - pattern: Pattern that was used
    - account_id: Account ID filter (if specified)
    - reason: Invalidation reason
    - timestamp: When invalidation occurred

Examples:
    # Invalidate all email lists
    cache_invalidate("email_list:*", reason="email_sent")

    # Invalidate specific account's folder tree
    cache_invalidate(
        "folder_get_tree:user@example.com:*",
        account_id="user@example.com",
        reason="folder_created"
    )

    # Invalidate all cache for an account
    cache_invalidate("*:user@example.com:*", reason="account_refresh")

This tool does not take any parameters.

### `cache_task_get_status`

📖 Get status of a background cache task (read-only, safe for unsupervised use)

Retrieve the current status, progress, and result/error information for a
specific background cache task.

Args:
    task_id: The unique identifier for the cache task.

Returns:
    Dictionary containing task status information:
    - task_id: Task identifier
    - status: Current status (queued, running, completed, failed)
    - operation: Operation type (e.g., folder_get_tree, email_list)
    - account_id: Associated account
    - progress: Progress percentage (0-100)
    - created_at: Task creation timestamp
    - updated_at: Last update timestamp
    - result: Operation result (if completed)
    - error: Error message (if failed)
    - retry_count: Number of retries attempted

Raises:
    ValueError: If task_id is not found.

This tool does not take any parameters.

### `cache_task_list`

📖 List background cache tasks (read-only, safe for unsupervised use)

Retrieve a list of background cache tasks, optionally filtered by account
and status.

Args:
    account_id: Optional account ID to filter tasks (None = all accounts).
    status: Optional status filter (queued, running, completed, failed).
    limit: Maximum number of tasks to return (default: 50).

Returns:
    List of task dictionaries, each containing:
    - task_id: Task identifier
    - status: Current status
    - operation: Operation type
    - account_id: Associated account
    - priority: Task priority (1=highest, 10=lowest)
    - created_at: Creation timestamp
    - updated_at: Last update timestamp
    - retry_count: Number of retries

Example:
    # List all tasks for a specific account
    tasks = cache_task_list(account_id="user@example.com")

    # List only failed tasks
    failed = cache_task_list(status="failed")

    # List recent queued tasks
    queued = cache_task_list(status="queued", limit=10)

This tool does not take any parameters.

### `cache_warming_status`

📖 Get cache warming status and progress (read-only, safe for unsupervised use)

Retrieve the current status of the cache warming process, including progress,
completion estimates, and statistics.

Returns:
    Dictionary containing warming status:
    - is_warming: Whether cache warming is currently active
    - started_at: When warming started (if active)
    - completed_at: When warming completed (if finished)
    - total_operations: Total number of warming operations
    - completed_operations: Number of completed operations
    - failed_operations: Number of failed operations
    - progress_percentage: Progress percentage (0-100)
    - estimated_completion: Estimated completion time
    - accounts_warmed: Number of accounts warmed
    - operations_by_type: Breakdown of operations by type
    - status: Current status message

Example:
    status = cache_warming_status()
    if status['is_warming']:
        print(f"Warming in progress: {status['progress_percentage']:.1f}%")
    else:
        print("Cache warming complete or not started")

This tool does not take any parameters.

### `calendar_check_availability`

📖 Check calendar availability for scheduling (read-only, safe for unsupervised use)

Returns free/busy information for the user and optional attendees.
Useful for finding meeting times.

Args:
    account_id: Microsoft account ID
    start: Start time in ISO format
    end: End time in ISO format
    attendees: Optional email address(es) to check availability

Returns:
    Schedule information with free/busy slots

Raises:
    ValidationError: If start/end datetimes or attendee addresses
        are invalid.
    ValueError: If the current account email address is unavailable.

This tool does not take any parameters.

### `calendar_create_calendar`

✏️ Create a new calendar (requires user confirmation recommended)

Creates a new calendar in the user's mailbox. Useful for organizing
events into separate calendars (work, personal, project-specific, etc.).

Args:
    account_id: Microsoft account ID
    name: Name for the new calendar

Returns:
    Created calendar object with ID and metadata

Raises:
    ValidationError: If calendar name is empty or invalid.

This tool does not take any parameters.

### `calendar_create_event`

✏️ Create a calendar event (requires user confirmation recommended)

Creates a new calendar event with optional attendees and location.
Attendees will receive meeting invitations. Addresses are validated,
deduplicated, and limited to 500 unique recipients.

Args:
    account_id: Microsoft account ID
    subject: Event title
    start: Start time in ISO format (e.g., "2024-01-15T10:00:00")
    end: End time in ISO format
    location: Location name (optional)
    body: Event description (optional)
    attendees: Email address(es) of attendees (optional)
    timezone: Timezone for the event (default: "UTC")

Returns:
    Created event object with ID

Raises:
    ValidationError: If datetime values, timezone, or attendee
        addresses are invalid.

This tool does not take any parameters.

### `calendar_delete_calendar`

🔴 Delete a calendar permanently (always require user confirmation)

WARNING: This action permanently deletes the calendar and ALL events
contained within it. This action cannot be undone.

Note: The default calendar cannot be deleted.

Args:
    account_id: Microsoft account ID
    calendar_id: The calendar ID to delete
    confirm: Must be True to confirm deletion (prevents accidents)

Returns:
    Status confirmation

Raises:
    ValidationError: If confirm is False.
    ValueError: If attempting to delete the default calendar.

This tool does not take any parameters.

### `calendar_delete_event`

🔴 Delete a calendar event (always require user confirmation)

WARNING: This action permanently deletes the event and cannot be undone.
If this is a meeting, attendees will receive cancellation notices.

Args:
    account_id: Microsoft account ID
    event_id: The event to delete
    send_cancellation: Whether to notify attendees (default: True)
    confirm: Must be True to confirm deletion (prevents accidents)

Returns:
    Status confirmation

This tool does not take any parameters.

### `calendar_forward_event`

📧 Forward a calendar event to recipients (always require user confirmation)

WARNING: Meeting invitation will be sent immediately to specified recipients.
This action cannot be undone.

Addresses are validated, deduplicated across To/CC, and limited to
500 unique recipients in total.

Args:
    account_id: Microsoft account ID
    event_id: The event ID to forward
    to: Recipient email address(es)
    cc: CC recipient email address(es) (optional)
    message: Optional comment/message to include with forward (plain text)
    confirm: Must be True to confirm sending (prevents accidents)

Returns:
    Status confirmation

Raises:
    ValidationError: If recipients are invalid, exceed limits,
        or confirm is False.

This tool does not take any parameters.

### `calendar_get_event`

📖 Get full event details (read-only, safe for unsupervised use)

Returns complete event information including recurrence patterns and online meeting details.

Args:
    event_id: The event ID
    account_id: Microsoft account ID
    use_cache: Whether to use cache (default: True)
    force_refresh: Bypass cache and fetch fresh data (default: False)

Returns:
    Complete event object with all metadata

This tool does not take any parameters.

### `calendar_get_free_busy`

📖 Get simplified free/busy times for attendees (read-only, safe for unsupervised use)

Returns a simplified view of free/busy information for specified attendees.
This is similar to calendar_check_availability but focuses on availability
view strings rather than detailed schedule information.

Args:
    account_id: Microsoft account ID
    attendees: Email address(es) to check availability for
    start: Start time in ISO format
    end: End time in ISO format
    time_interval: Interval in minutes for availability view (default: 30)

Returns:
    Free/busy information with availability view strings

Raises:
    ValidationError: If start/end datetimes or attendee addresses are invalid.

This tool does not take any parameters.

### `calendar_list_calendars`

📖 List all available calendars (read-only, safe for unsupervised use)

Returns all calendars accessible by the user, including primary calendar
and any additional calendars (shared, group, etc.).

Caching: Results are cached for 15 minutes (fresh) / 1 hour (stale).
Use force_refresh=True to bypass cache and fetch fresh data.

Args:
    account_id: Microsoft account ID
    use_cache: Whether to use cached data if available (default: True)
    force_refresh: Force refresh from API, bypassing cache (default: False)

Returns:
    List of calendar objects with metadata.
    Each calendar includes _cache_status and _cached_at fields.

This tool does not take any parameters.

### `calendar_list_events`

📖 List upcoming calendar events (read-only, safe for unsupervised use)

Returns calendar events from now until the specified number of days ahead.

Caching: Results are cached for 5 minutes (fresh) / 30 minutes (stale).
Use force_refresh=True to bypass cache and fetch fresh data.

Args:
    account_id: Microsoft account ID
    days_ahead: Number of days ahead to look for events (1-365, default: 7)
    include_details: Include full event details like attendees and body (default: False)
    limit: Maximum events to return (1-200, default: 50)
    use_cache: Whether to use cached data if available (default: True)
    force_refresh: Force refresh from API, bypassing cache (default: False)

Returns:
    List of calendar events with metadata.
    Each event includes _cache_status and _cached_at fields.

This tool does not take any parameters.

### `calendar_propose_new_time`

✏️ Propose a new time for a meeting (requires user confirmation recommended)

Proposes a new meeting time to the organizer. This is useful when you've
been invited to a meeting but the time doesn't work for you.

Note: This only works for meetings where you are an attendee, not the organizer.

Args:
    account_id: Microsoft account ID
    event_id: The event ID to propose new time for
    proposed_start: Proposed start time in ISO format (e.g., "2024-01-15T10:00:00")
    proposed_end: Proposed end time in ISO format
    message: Optional message explaining the proposed change

Returns:
    Status confirmation

Raises:
    ValidationError: If datetime values are invalid.

This tool does not take any parameters.

### `calendar_respond_event`

⚠️ Respond to a calendar event invitation (requires user confirmation recommended)

IMPORTANT: This sends a response to the event organizer.

Valid responses:
    - "accept" - Accept the invitation
    - "decline" - Decline the invitation
    - "tentativelyAccept" - Mark as tentative
  (Input is case-insensitive; "tentative" is accepted as an alias.)

Args:
    account_id: Microsoft account ID
    event_id: The event ID to respond to
    response: Response type (default: "accept")
    message: Optional message to the organizer

Returns:
    Status confirmation

Raises:
    ValidationError: If the response value or message payload is invalid.

This tool does not take any parameters.

### `calendar_update_event`

✏️ Update event properties (requires user confirmation recommended)

Modifies event details like time, location, or attendees.
Attendees will receive update notifications.

Allowed update keys: subject, start, end, timezone, location, body, attendees.

Args:
    event_id: The event ID to update
    updates: Dictionary with fields to update (subject, start, end, location, body)
    account_id: Microsoft account ID

Returns:
    Updated event object

This tool does not take any parameters.

### `contact_add_to_list`

✏️ Add a contact to a contact list (requires user confirmation recommended)

Adds an existing contact to a contact folder (list). The contact is copied
to the list, so it will exist in both the original location and the list.

Args:
    account_id: Microsoft account ID
    contact_id: The contact ID to add
    list_id: The contact list/folder ID

Returns:
    Copy of the contact in the new list

Raises:
    ValueError: If contact or list is not found.

This tool does not take any parameters.

### `contact_create`

✏️ Create a new contact (requires user confirmation recommended)

Creates a contact with name, email addresses, and phone numbers.

Args:
    account_id: Microsoft account ID
    given_name: First name (required)
    surname: Last name (optional)
    email_addresses: Email address(es) (optional)
    phone_numbers: Phone numbers dict with keys: business, home, mobile (optional)

Returns:
    Created contact object with ID

This tool does not take any parameters.

### `contact_create_list`

✏️ Create a new contact list (requires user confirmation recommended)

Creates a contact folder (list) for organizing contacts into groups.
Useful for creating distribution lists, project teams, or other groupings.

Args:
    account_id: Microsoft account ID
    list_name: Name for the contact list/folder

Returns:
    Created contact folder object with ID

Raises:
    ValidationError: If list name is empty or invalid.

This tool does not take any parameters.

### `contact_delete`

🔴 Delete a contact permanently (always require user confirmation)

WARNING: This action permanently deletes the contact and cannot be undone.

Args:
    contact_id: The contact to delete
    account_id: Microsoft account ID
    confirm: Must be True to confirm deletion (prevents accidents)

Returns:
    Status confirmation

This tool does not take any parameters.

### `contact_export`

📖 Export a contact in vCard format (read-only, safe for unsupervised use)

Exports contact information in vCard format for portability and sharing.
vCard is a standard format supported by most contact management applications.

Args:
    account_id: Microsoft account ID
    contact_id: The contact ID to export
    format: Export format (currently only "vcard" is supported)

Returns:
    Dictionary containing the vCard data and metadata

Raises:
    ValidationError: If format is not supported.
    ValueError: If contact is not found.

This tool does not take any parameters.

### `contact_get`

📖 Get contact details (read-only, safe for unsupervised use)

Returns complete contact information including all fields.

Caching: Results are cached for 30 minutes (fresh) / 4 hours (stale).
Use force_refresh=True to bypass cache and fetch fresh data.

Args:
    contact_id: The contact ID
    account_id: Microsoft account ID
    use_cache: Whether to use cached data if available (default: True)
    force_refresh: Force refresh from API, bypassing cache (default: False)

Returns:
    Contact details with:
    - _cache_status: Cache state (fresh/stale/miss)
    - _cached_at: When data was cached (ISO format)

This tool does not take any parameters.

### `contact_list`

📖 List contacts (read-only, safe for unsupervised use)

Returns contacts with names, email addresses, and phone numbers.

Caching: Results are cached for 20 minutes (fresh) / 2 hours (stale).
Use force_refresh=True to bypass cache and fetch fresh data.

Args:
    account_id: Microsoft account ID
    limit: Maximum contacts to return (1-500, default: 50)
    use_cache: Whether to use cached data if available (default: True)
    force_refresh: Force refresh from API, bypassing cache (default: False)

Returns:
    List of contact objects with metadata.
    Each contact includes _cache_status and _cached_at fields.

This tool does not take any parameters.

### `contact_update`

✏️ Update contact information (requires user confirmation recommended)

Modifies contact fields like name, email, or phone numbers.

Allowed update keys: givenName, surname, displayName, emailAddresses,
businessPhones, homePhones, mobilePhone, jobTitle, companyName, department.

Args:
    contact_id: The contact ID to update
    updates: Dictionary with fields to update
    account_id: Microsoft account ID

Returns:
    Updated contact object

This tool does not take any parameters.

### `email_add_category`

✏️ Add categories to an email (requires user confirmation recommended)

Simpler alternative to email_update for managing email categories.
This replaces all existing categories with the specified ones.

Args:
    email_id: The email ID to update
    account_id: Microsoft account ID
    categories: Category name(s) to apply (single string or list)

Returns:
    Updated email object

Raises:
    ValueError: If email_id is invalid
    ValidationError: If categories is empty or contains invalid values

This tool does not take any parameters.

### `email_archive`

✏️ Archive an email (requires user confirmation recommended)

Quick action to move an email to the Archive folder. This is a convenience
wrapper around email_move that specifically targets the archive folder.

Args:
    email_id: The email ID to archive
    account_id: Microsoft account ID

Returns:
    Status confirmation with new email ID

Raises:
    ValueError: If email_id is invalid or archive folder not found

This tool does not take any parameters.

### `email_create_draft`

✏️ Create an email draft (requires user confirmation recommended)

Creates a draft email message that can be edited later before sending.
Supports attachments from local file paths.

Args:
    account_id: Microsoft account ID
    to: Recipient email address(es)
    subject: Email subject
    body: Email body (plain text)
    cc: CC recipient email address(es) (optional)
    attachments: Local file path(s) for attachments (optional)

Returns:
    Created draft message with ID

This tool does not take any parameters.

### `email_delete`

🔴 Delete an email permanently (always require user confirmation)

WARNING: This action permanently deletes the email and cannot be undone.

For safety, consider moving items to the deleted items folder first using email_move.

Args:
    email_id: The email to delete
    account_id: The account ID
    confirm: Must be True to confirm deletion (prevents accidents)

Returns:
    Status confirmation

This tool does not take any parameters.

### `email_flag`

✏️ Flag or unflag an email (requires user confirmation recommended)

Simpler alternative to email_update for flagging emails.

Args:
    email_id: The email ID to update
    account_id: Microsoft account ID
    flag_status: Flag status - "notFlagged", "flagged", or "complete" (default: "flagged")

Returns:
    Updated email object

Raises:
    ValueError: If email_id is invalid or flag_status is unsupported

This tool does not take any parameters.

### `email_forward`

📧 Forward an email to recipients (always require user confirmation)

WARNING: Email will be forwarded immediately to specified recipients.
This action cannot be undone.

Addresses are validated, deduplicated across To/CC, and limited to
500 unique recipients in total.

Args:
    account_id: Microsoft account ID
    email_id: The email ID to forward
    to: Recipient email address(es)
    cc: CC recipient email address(es) (optional)
    body: Optional comment/message to include with forward (plain text)
    confirm: Must be True to confirm sending (prevents accidents)

Returns:
    Status confirmation

Raises:
    ValidationError: If recipients are invalid, exceed limits,
        or confirm is False.

This tool does not take any parameters.

### `email_get`

📖 Get detailed information about a specific email (read-only, safe for unsupervised use)

Includes full headers, body content, and attachment metadata.
Body content is truncated at 50,000 characters by default.

Caching: Results are cached for 15 minutes (fresh) / 1 hour (stale).
Use force_refresh=True to bypass cache and fetch fresh data.

Args:
    email_id: The email ID
    account_id: The account ID
    include_body: Whether to include the email body (default: True)
    body_max_length: Maximum characters for body content (1-500000, default: 50000)
    include_attachments: Whether to include attachment metadata (default: True)
    use_cache: Whether to use cached data if available (default: True)
    force_refresh: Force refresh from API, bypassing cache (default: False)

Returns:
    Email details with:
    - _cache_status: Cache state (fresh/stale/miss)
    - _cached_at: When data was cached (ISO format)

This tool does not take any parameters.

### `email_get_attachment`

Download an email attachment to a validated local path.

Args:
    email_id: Microsoft Graph message identifier containing the attachment.
    attachment_id: Target attachment identifier within the message.
    save_path: Destination path for the attachment. Validated via
        `ensure_safe_path`; existing files are never overwritten.
    account_id: Microsoft account identifier.

Returns:
    Attachment metadata, including saved path and content size.

This tool does not take any parameters.

### `email_list`

📖 List emails from a mailbox folder (read-only, safe for unsupervised use)

Returns recent emails with subject, sender, date, size, and attachment info.

Caching: Results are cached for 2 minutes (fresh) / 10 minutes (stale).
Use force_refresh=True to bypass cache and fetch fresh data.

Args:
    account_id: Microsoft account ID
    folder: Folder name (inbox, sent, drafts, deleted, junk, archive)
    folder_id: Direct folder ID - takes precedence over folder name
    limit: Maximum emails to return (1-200, default: 10)
    include_body: Whether to include email body content (default: True)
    use_cache: Whether to use cached data if available (default: True)
    force_refresh: Force refresh from API, bypassing cache (default: False)

Returns:
    List of email messages with metadata and optionally body content.
    Each message includes _cache_status and _cached_at fields.

This tool does not take any parameters.

### `email_mark_read`

✏️ Mark an email as read or unread (requires user confirmation recommended)

Simpler alternative to email_update for marking emails as read/unread.

Args:
    email_id: The email ID to update
    account_id: Microsoft account ID
    is_read: Whether to mark as read (True) or unread (False) (default: True)

Returns:
    Updated email object

Raises:
    ValueError: If email_id is invalid
    ValidationError: If is_read is not a boolean

This tool does not take any parameters.

### `email_move`

✏️ Move an email to a different folder (requires user confirmation recommended)

Moves the email to the specified folder without deleting it from the source.

Valid folder names: inbox, sent, drafts, deleted, junk, archive.

Args:
    email_id: The email ID to move
    destination_folder: Folder name to move to
    account_id: Microsoft account ID

Returns:
    Status confirmation with new email ID

This tool does not take any parameters.

### `email_reply`

📧 Reply to an email (always require user confirmation)

WARNING: Reply will be sent immediately to the original sender.
This action cannot be undone.

Body content is stripped of surrounding whitespace and must not be
empty before sending.

Args:
    account_id: Microsoft account ID
    email_id: The email ID to reply to
    body: Reply message body (plain text)
    confirm: Must be True to confirm sending (prevents accidents)

Returns:
    Status confirmation

Raises:
    ValidationError: If the reply body is empty/whitespace or confirm
        is False.

This tool does not take any parameters.

### `email_reply_all`

📧 Reply to all recipients of an email (always require user confirmation)

WARNING: Reply will be sent immediately to ALL recipients (original sender,
To, and Cc recipients). This action cannot be undone.

Body content is stripped of surrounding whitespace and must not be
empty before sending.

Args:
    account_id: Microsoft account ID
    email_id: The email ID to reply to
    body: Reply message body (plain text)
    confirm: Must be True to confirm sending (prevents accidents)

Returns:
    Status confirmation

Raises:
    ValidationError: If the reply body is empty/whitespace or confirm
        is False.

This tool does not take any parameters.

### `email_send`

📧 Send an email to recipients (always require user confirmation)

WARNING: Email will be sent immediately upon execution.
This action cannot be undone.

Supports multiple recipients, CC, attachments, and HTML formatting.
Addresses are validated, deduplicated across To/CC, and limited to
500 unique recipients in total.

Args:
    account_id: Microsoft account ID
    to: Recipient email address(es)
    subject: Email subject
    body: Email body (plain text)
    cc: CC recipient email address(es) (optional)
    attachments: Local file path(s) for attachments (optional)
    confirm: Must be True to confirm sending (prevents accidents)

Returns:
    Status confirmation

Raises:
    ValidationError: If recipients are invalid, exceed limits,
        or confirm is False.

This tool does not take any parameters.

### `email_update`

✏️ Update email properties (requires user confirmation recommended)

Modifies properties like isRead status, categories, and flags without
changing email content.

Examples:
    email_update(email_id, {"isRead": True}, account_id)
    email_update(email_id, {"categories": ["Important"]}, account_id)

Allowed update keys: isRead, categories, importance, flag, inferenceClassification.

Args:
    email_id: The email ID to update
    updates: Dictionary of properties to update
    account_id: Microsoft account ID

Returns:
    Updated email object

This tool does not take any parameters.

### `emailfolders_create`

✏️ Create a new mail folder (requires user confirmation recommended)

Creates a new mail folder in the mailbox, either at the root level or
as a child of an existing folder.

Args:
    display_name: Name for the new folder
    account_id: Microsoft account ID
    parent_folder_id: Parent folder ID (None = root level)

Returns:
    Created folder object with id, displayName, and other metadata

Raises:
    ValueError: If display_name is empty or parent_folder_id is invalid

This tool does not take any parameters.

### `emailfolders_delete`

🔴 Delete a mail folder permanently (always require user confirmation)

WARNING: This action permanently deletes the folder and all its contents
(emails and subfolders) and cannot be undone.

Args:
    folder_id: The folder ID to delete
    account_id: Microsoft account ID
    confirm: Must be True to confirm deletion (prevents accidents)

Returns:
    Status confirmation

Raises:
    ValueError: If folder_id is invalid or confirm is False

This tool does not take any parameters.

### `emailfolders_empty`

🔴 Delete all messages in a folder (always require user confirmation)

WARNING: This action permanently deletes all messages in the folder
and cannot be undone. The folder itself remains but all messages
are permanently deleted.

Args:
    folder_id: The folder ID to empty
    account_id: Microsoft account ID
    confirm: Must be True to confirm deletion (prevents accidents)

Returns:
    Status confirmation with count of messages deleted

Raises:
    ValueError: If folder_id is invalid or confirm is False

This tool does not take any parameters.

### `emailfolders_get`

📖 Get detailed information about a specific mail folder (read-only, safe for unsupervised use)

Returns complete folder metadata including counts and hierarchy information.

Args:
    folder_id: The folder ID to retrieve
    account_id: Microsoft account ID

Returns:
    Folder object with full metadata including id, displayName,
    childFolderCount, unreadItemCount, totalItemCount

This tool does not take any parameters.

### `emailfolders_get_tree`

📖 Recursively build a tree of mail folders (read-only, safe for unsupervised use)

Returns a hierarchical tree structure showing all folders and their nested children.
Useful for understanding mailbox folder organization.

Args:
    account_id: Microsoft account ID
    parent_folder_id: Root folder to start from (None = root)
    max_depth: Maximum recursion depth to prevent infinite loops (1-25, default: 10)
    include_hidden: Whether to include hidden folders (default: False)

Returns:
    Nested tree structure with folders and their children

This tool does not take any parameters.

### `emailfolders_list`

📖 List mail folders from mailbox (read-only, safe for unsupervised use)

Returns root folders or child folders of a specific parent with metadata
including unread counts and child folder information.

Args:
    account_id: Microsoft account ID
    parent_folder_id: If None, lists root folders. If provided, lists child folders.
    include_hidden: Whether to include hidden folders (default: False)
    limit: Maximum number of folders to return (1-250, default: 100)

Returns:
    List of folder objects with: id, displayName, childFolderCount,
    unreadItemCount, totalItemCount, parentFolderId, isHidden

This tool does not take any parameters.

### `emailfolders_mark_all_as_read`

✏️ Mark all messages in a folder as read (requires user confirmation recommended)

Updates all messages in the specified folder to mark them as read.
This operation may take time for folders with many messages.

Args:
    folder_id: The folder ID containing messages to mark as read
    account_id: Microsoft account ID

Returns:
    Status confirmation with count of messages updated

Raises:
    ValueError: If folder_id is invalid

This tool does not take any parameters.

### `emailfolders_move`

✏️ Move a mail folder to a different parent (requires user confirmation recommended)

Moves a mail folder to become a child of a different parent folder.

Args:
    folder_id: The folder ID to move
    destination_folder_id: The destination parent folder ID
    account_id: Microsoft account ID

Returns:
    Updated folder object with new parentFolderId

Raises:
    ValueError: If folder_id or destination_folder_id is invalid

This tool does not take any parameters.

### `emailfolders_rename`

✏️ Rename a mail folder (requires user confirmation recommended)

Updates the display name of an existing mail folder.

Args:
    folder_id: The folder ID to rename
    new_display_name: New name for the folder
    account_id: Microsoft account ID

Returns:
    Updated folder object with new displayName

Raises:
    ValueError: If folder_id is invalid or new_display_name is empty

This tool does not take any parameters.

### `emailrules_create`

✏️ Create a new inbox message rule to automatically process emails (requires user confirmation recommended)

Rules are executed in priority order (sequence number).

Conditions examples:
    {"fromAddresses": [{"address": "john@example.com"}]}
    {"subjectContains": ["urgent", "important"]}
    {"senderContains": ["@company.com"]}
    {"hasAttachments": true}

Actions examples:
    {"moveToFolder": "folder_id"}
    {"markAsRead": true}
    {"forwardTo": [{"emailAddress": {"address": "manager@example.com"}}]}
    {"assignCategories": ["Red category"]}
    {"delete": true}

Args:
    account_id: Microsoft account ID
    display_name: Name for the rule (e.g., "Move work emails to Projects")
    conditions: Conditions that trigger the rule
    actions: Actions to perform when conditions match
    sequence: Rule execution order (lower numbers execute first, default: 1)
    is_enabled: Whether the rule is active (default: True)
    exceptions: Optional conditions that prevent rule execution

Returns:
    Created rule with its ID and full configuration

This tool does not take any parameters.

### `emailrules_delete`

🔴 Delete a message rule permanently (always require user confirmation)

WARNING: This action permanently deletes the rule and cannot be undone.
Emails will no longer be automatically processed by this rule.

Args:
    rule_id: The message rule ID to delete
    account_id: Microsoft account ID
    confirm: Must be True to confirm deletion (prevents accidents)

Returns:
    Status confirmation

This tool does not take any parameters.

### `emailrules_get`

📖 Get details of a specific message rule (read-only, safe for unsupervised use)

Returns complete rule configuration including conditions, actions, and execution order.

Args:
    rule_id: The message rule ID
    account_id: Microsoft account ID

Returns:
    Rule details including conditions, actions, sequence, and enabled status

This tool does not take any parameters.

### `emailrules_list`

📖 List all inbox message rules (read-only, safe for unsupervised use)

Message rules automatically process incoming emails based on conditions.
Rules are executed in sequence order (1, 2, 3...).

Args:
    account_id: Microsoft account ID

Returns:
    List of rules with: id, displayName, sequence, isEnabled, conditions, actions

This tool does not take any parameters.

### `emailrules_move_bottom`

✏️ Move a message rule to the bottom of execution order (requires user confirmation recommended)

Rules execute in sequence order. Moving to bottom means it runs after all other rules.

Args:
    rule_id: The message rule ID to move
    account_id: Microsoft account ID

Returns:
    Updated rule with new sequence number

This tool does not take any parameters.

### `emailrules_move_down`

✏️ Move a message rule down one position in execution order (requires user confirmation recommended)

Decreases the rule's priority by moving it one position lower in the
execution order. Rules at the bottom cannot be moved down further.

Args:
    rule_id: The message rule ID to move
    account_id: Microsoft account ID

Returns:
    Updated rule with new sequence number

This tool does not take any parameters.

### `emailrules_move_top`

✏️ Move a message rule to the top of execution order (requires user confirmation recommended)

Rules execute in sequence order. Moving to top means it runs before all other rules.
Sets the rule's sequence number to 1.

Args:
    rule_id: The message rule ID to move
    account_id: Microsoft account ID

Returns:
    Updated rule with new sequence number

This tool does not take any parameters.

### `emailrules_move_up`

✏️ Move a message rule up one position in execution order (requires user confirmation recommended)

Increases the rule's priority by moving it one position higher in the
execution order. Rules at the top (sequence = 1) cannot be moved up.

Args:
    rule_id: The message rule ID to move
    account_id: Microsoft account ID

Returns:
    Updated rule with new sequence number

This tool does not take any parameters.

### `emailrules_update`

✏️ Update an existing message rule (requires user confirmation recommended)

Modifies rule properties, conditions, actions, or execution order.
At least one field must be provided to update.

Allowed parameters: display_name, conditions, actions, sequence,
is_enabled, exceptions.

Args:
    rule_id: The message rule ID to update
    account_id: Microsoft account ID
    display_name: New name for the rule (optional)
    conditions: New conditions (optional)
    actions: New actions (optional)
    sequence: New execution order (optional)
    is_enabled: Enable or disable the rule (optional)
    exceptions: New exception conditions (optional)

Returns:
    Updated rule configuration

This tool does not take any parameters.

### `file_copy`

✏️ Copy a file within OneDrive (requires user confirmation recommended)

Creates a copy of a file in a specified destination folder. The copy
operation is asynchronous and may take time for large files.

Args:
    file_id: The file ID to copy
    destination_folder_id: The destination folder ID
    account_id: Microsoft account ID
    new_name: Optional new name for the copied file

Returns:
    Copy operation status with location URL to monitor progress

Raises:
    ValueError: If file_id or destination_folder_id is invalid

This tool does not take any parameters.

### `file_create`

✏️ Upload a local file to OneDrive (requires user confirmation recommended)

Args:
    onedrive_path: Destination path within OneDrive (must start with '/').
    local_file_path: Absolute path to the local file to upload. Paths are
        validated via `ensure_safe_path` to prevent traversal and
        restrict uploads to trusted directories.
    account_id: Microsoft account identifier.

Returns:
    Metadata for the created OneDrive file.

This tool does not take any parameters.

### `file_delete`

🔴 Delete a OneDrive file or folder permanently (always require user confirmation)

WARNING: This action permanently deletes the file or folder and cannot be undone.

This tool does not take any parameters.

### `file_download_url`

📖 Get direct download URL for a OneDrive file (read-only, safe for unsupervised use)

Returns a temporary download URL that can be used to download the file directly
without authentication. The URL expires after a short period.

Args:
    file_id: The file ID to get download URL for
    account_id: Microsoft account ID

Returns:
    Dictionary containing the download URL and file metadata

Raises:
    ValueError: If file_id is invalid or file not found

This tool does not take any parameters.

### `file_get`

✏️ Download a OneDrive file to a local path (requires user confirmation recommended)

The download URL is supplied by Microsoft Graph (never user input) and is
validated against an allow-list of Microsoft domains before use. The file
is streamed to disk in configurable chunks with retry behaviour to protect
against transient failures. Download size and timeouts respect the
environment variables `MCP_FILE_DOWNLOAD_MAX_MB` and
`MCP_FILE_DOWNLOAD_TIMEOUT`.

Args:
    file_id: The Microsoft Graph file identifier to download.
    account_id: Microsoft account identifier associated with the file.
    download_path: Absolute path where the file will be stored locally.
        Must reside within an allowed root directory.

Returns:
    Dictionary containing download metadata (name, size_mb, mime_type).

Raises:
    ValidationError: If input parameters are invalid.
    RuntimeError: If all download attempts fail.

This tool does not take any parameters.

### `file_list`

📖 List files and/or folders in OneDrive (read-only, safe for unsupervised use)

Returns items from OneDrive with names, sizes, and modification dates.

Caching: Results are cached for 10 minutes (fresh) / 1 hour (stale).
Use force_refresh=True to bypass cache and fetch fresh data.

Args:
    account_id: Microsoft account ID
    path: Path to list from (default: "/")
    folder_id: Direct folder ID (takes precedence over path)
    limit: Maximum items to return (1-500, default: 50)
    type_filter: Filter by type - "all", "files", or "folders" (default: "all")
    use_cache: Whether to use cached data if available (default: True)
    force_refresh: Force refresh from API, bypassing cache (default: False)

Returns:
    List of items matching the filter criteria.
    Each item includes _cache_status and _cached_at fields.

This tool does not take any parameters.

### `file_move`

✏️ Move a file to a different folder (requires user confirmation recommended)

Moves a file to a different parent folder within OneDrive.

Args:
    file_id: The file ID to move
    destination_folder_id: The destination folder ID
    account_id: Microsoft account ID

Returns:
    Updated file object with new parentReference

Raises:
    ValueError: If file_id or destination_folder_id is invalid

This tool does not take any parameters.

### `file_rename`

✏️ Rename a file (requires user confirmation recommended)

Updates the name of an existing OneDrive file.

Args:
    file_id: The file ID to rename
    new_name: New name for the file
    account_id: Microsoft account ID

Returns:
    Updated file object with new name

Raises:
    ValueError: If file_id is invalid or new_name is empty

This tool does not take any parameters.

### `file_share`

✏️ Create a sharing link for a OneDrive file (requires user confirmation recommended)

Creates a sharing link that allows others to access the file. Permission types
control what recipients can do with the file.

Args:
    file_id: The file ID to share
    account_id: Microsoft account ID
    permission_type: Type of permission - "view" or "edit" (default: "view")
    scope: Link scope - "anonymous" or "organization" (default: "anonymous")

Returns:
    Sharing link details including the web URL

Raises:
    ValueError: If file_id is invalid or permission_type/scope is unsupported

This tool does not take any parameters.

### `file_update`

✏️ Replace OneDrive file content with local file (requires user confirmation recommended)

Args:
    file_id: Target OneDrive file identifier to replace.
    local_file_path: Absolute path to the replacement file. Validated via
        `ensure_safe_path` to block traversal and enforce workspace roots.
    account_id: Microsoft account identifier.

Returns:
    Updated file metadata returned by Microsoft Graph.

This tool does not take any parameters.

### `folder_create`

✏️ Create a new OneDrive folder (requires user confirmation recommended)

Creates a new folder in OneDrive, either at the root level or
as a child of an existing folder.

Args:
    name: Name for the new folder
    account_id: Microsoft account ID
    parent_folder_id: Parent folder ID (None = root level)

Returns:
    Created folder object with id, name, and other metadata

Raises:
    ValueError: If name is empty or parent_folder_id is invalid

This tool does not take any parameters.

### `folder_delete`

🔴 Delete an OneDrive folder permanently (always require user confirmation)

WARNING: This action permanently deletes the folder and all its contents
(files and subfolders) and cannot be undone.

Args:
    folder_id: The folder ID to delete
    account_id: Microsoft account ID
    confirm: Must be True to confirm deletion (prevents accidents)

Returns:
    Status confirmation

Raises:
    ValueError: If folder_id is invalid or confirm is False

This tool does not take any parameters.

### `folder_get`

📖 Get metadata for a specific OneDrive folder (read-only, safe for unsupervised use)

Returns folder details including child count and web URL.

Args:
    account_id: Microsoft account ID
    folder_id: Folder ID (takes precedence if provided)
    path: Folder path (e.g., "/Documents/Projects")

Returns:
    Folder metadata including childCount, webUrl, and parent info

This tool does not take any parameters.

### `folder_get_tree`

📖 Recursively build a tree of OneDrive folders (read-only, safe for unsupervised use)

Returns a hierarchical tree structure showing all folders and nested subfolders.
Useful for understanding OneDrive folder organization.

Caching: Results are cached for 30 minutes (fresh) / 2 hours (stale).
Use force_refresh=True to bypass cache and fetch fresh data.

Args:
    account_id: Microsoft account ID
    path: Starting path (default: "/")
    folder_id: Starting folder ID (takes precedence over path)
    max_depth: Maximum recursion depth (1-25, default: 10)
    use_cache: Whether to use cached data if available (default: True)
    force_refresh: Force refresh from API, bypassing cache (default: False)

Returns:
    Nested tree structure with folders and their children, including:
    - _cache_status: Cache state (fresh/stale/miss)
    - _cached_at: When data was cached (ISO format)

This tool does not take any parameters.

### `folder_list`

📖 List only folders (not files) in OneDrive (read-only, safe for unsupervised use)

Returns folders with child counts and hierarchy information.

Caching: Results are cached for 15 minutes (fresh) / 1 hour (stale).
Use force_refresh=True to bypass cache and fetch fresh data.

Args:
    account_id: Microsoft account ID
    path: Path to list folders from (e.g., "/Documents", default: "/")
    folder_id: Direct folder ID (takes precedence over path)
    limit: Maximum folders to return (1-500, default: 50)
    use_cache: Whether to use cached data if available (default: True)
    force_refresh: Force refresh from API, bypassing cache (default: False)

Returns:
    Dictionary with:
    - folders: List of folder objects with id, name, childCount, path, parentId
    - _cache_status: Cache state (fresh/stale/miss)
    - _cached_at: When data was cached (ISO format)

This tool does not take any parameters.

### `folder_move`

✏️ Move an OneDrive folder to a different parent (requires user confirmation recommended)

Moves a folder to become a child of a different parent folder.

Args:
    folder_id: The folder ID to move
    destination_folder_id: The destination parent folder ID
    account_id: Microsoft account ID

Returns:
    Updated folder object with new parentReference

Raises:
    ValueError: If folder_id or destination_folder_id is invalid

This tool does not take any parameters.

### `folder_rename`

✏️ Rename an OneDrive folder (requires user confirmation recommended)

Updates the name of an existing OneDrive folder.

Args:
    folder_id: The folder ID to rename
    new_name: New name for the folder
    account_id: Microsoft account ID

Returns:
    Updated folder object with new name

Raises:
    ValueError: If folder_id is invalid or new_name is empty

This tool does not take any parameters.

### `search_contacts`

📖 Search contacts (read-only, safe for unsupervised use)

Searches contact names, email addresses, and phone numbers.
Uses $filter with prefix matching (startswith) for all account types
due to Graph API limitations.

Note: Contact search is limited to prefix matching and may not find
matches in the middle of names.

Args:
    query: Search query string (1-512 characters, used as prefix)
    account_id: Microsoft account ID
    limit: Maximum results to return (1-500, default: 50)
    use_cache: Whether to use cache (default: True)
    force_refresh: Bypass cache and fetch fresh data (default: False)

Returns:
    List of matching contacts

This tool does not take any parameters.

### `search_emails`

📖 Search emails across mailbox (read-only, safe for unsupervised use)

Searches email subject, body, and sender across all or specific folders.
Automatically routes to the appropriate API based on account type:
- Personal accounts: Uses OData $search parameter
- Work/school accounts: Uses unified search API

Args:
    query: Search query string (1-512 characters)
    account_id: Microsoft account ID
    limit: Maximum results to return (1-500, default: 50)
    folder: Optional folder to search within (e.g., "inbox", "sent")
    use_cache: Whether to use cache (default: True)
    force_refresh: Bypass cache and fetch fresh data (default: False)

Returns:
    List of matching emails with metadata

This tool does not take any parameters.

### `search_events`

📖 Search calendar events (read-only, safe for unsupervised use)

Searches event titles, locations, and descriptions within date range.
Automatically routes to the appropriate API based on account type:
- Personal accounts: Uses OData $search parameter
- Work/school accounts: Uses unified search API

Args:
    query: Search query string (1-512 characters)
    account_id: Microsoft account ID
    days_ahead: Days to look forward (0-730, default: 365)
    days_back: Days to look back (0-730, default: 365)
    limit: Maximum results to return (1-500, default: 50)
    use_cache: Whether to use cache (default: True)
    force_refresh: Bypass cache and fetch fresh data (default: False)

Returns:
    List of matching events

This tool does not take any parameters.

### `search_files`

📖 Search for files in OneDrive (read-only, safe for unsupervised use)

Searches file names and content across all accessible OneDrive folders.
Automatically routes to the appropriate API based on account type:
- Personal accounts: Uses OneDrive-specific search
- Work/school accounts: Uses unified search API

Args:
    query: Search query string (1-512 characters)
    account_id: Microsoft account ID
    limit: Maximum results to return (1-500, default: 50)
    use_cache: Whether to use cache (default: True)
    force_refresh: Bypass cache and fetch fresh data (default: False)

Returns:
    List of matching files with metadata

This tool does not take any parameters.

### `search_unified`

📖 Search across multiple Microsoft 365 resources (read-only, safe for unsupervised use)

Searches emails, events, and files simultaneously.
Automatically routes to the appropriate API based on account type:
- Personal accounts: Performs sequential searches for each entity type
- Work/school accounts: Uses unified search API for parallel search

Args:
    query: Search query string (1-512 characters)
    account_id: Microsoft account ID
    entity_types: Types to search: 'message', 'event', 'driveItem' (default: all)
    limit: Maximum results per type (1-500, default: 50)
    use_cache: Whether to use cache (default: True)
    force_refresh: Bypass cache and fetch fresh data (default: False)

Returns:
    Dictionary with results grouped by entity type

This tool does not take any parameters.

### `server_get_version`

📖 Get the version of the m365-mcp server (read-only, safe for unsupervised use)

Returns the current version of the m365-mcp server that is running.
Useful for diagnostics, troubleshooting, and ensuring compatibility.

Returns:
    Dictionary containing:
    - version: The semantic version string (e.g., "0.1.3")
    - package: The package name ("m365-mcp")

Example:
    >>> server_get_version()
    {"version": "0.1.3", "package": "m365-mcp"}

This tool does not take any parameters.
