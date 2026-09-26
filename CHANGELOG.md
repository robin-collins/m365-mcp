# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-09-26

Version 1.0.0 replaces the 85-tool surface with 30 intent-based tools and
supports **personal Microsoft accounts only**. It is a hard cut: the 85 old
tool names are removed with no aliases. The tool contract is defined in
[`docs/unified-tools/`](docs/unified-tools/README.md) and the design in
[`UNIFIED_TOOLS_CONCEPT.md`](UNIFIED_TOOLS_CONCEPT.md). Definition size drops
from about 22k tokens (85 tools, no parameter descriptions) to about 13.5k
for the default 23 tools (about 9.4k for the 16 core tools), with every
parameter documented.

### Breaking Changes

Every change below breaks existing clients, saved tool calls or
configurations. Move each old call using the [migration table](#migration-table-85-removed-tools)
below.

- **Personal accounts only.** Work and school accounts are rejected when
  sign-in completes and are removed from the token cache. The default
  authority is now `consumers` (it was `common`). The Microsoft Search API
  path, organisation-scope sharing and participant free/busy are removed
  because personal accounts do not support them.
- **All 85 legacy tool names are removed**, with no aliases. The
  replacements are 29 tools: eight generic `m365_*` tools, `email_*`,
  `calendar_*`, `drive_*`, `account_*` and `admin_*` tools.
- **Signatures are new.** `account_id` is now optional on every tool (it was
  required and its position varied per tool). Omitted means the only
  signed-in account; with several accounts the call fails and lists them.
  `account_id` accepts the ID or the email address. Recipients are always
  lists of strings.
- **Email search covers the whole mailbox.** It uses server-side `$search`.
  The old client-side filter only looked at the newest `max(limit x 5, 50)`
  messages, so older mail was never found.
- **Availability is own-calendar only, and `attendees` inputs are dropped.**
  `calendar_get_free_busy` and `calendar_check_availability` become
  `calendar_find_availability`, computed from `calendarView` and your working
  hours, because Graph cannot return other people's free/busy for personal
  accounts. It also suggests free slots.
- **`contact_add_to_list` is now a real move.** `m365_move(resource="contact")`
  creates the contact in the destination folder and deletes the original,
  so the contact gets a **new ID** (returned). The old tool created a
  duplicate. "Contact lists" are now the `contact_folder` resource.
- **Lists return previews, not bodies.** List and search results are compact
  projections (`preview` of at most 255 characters); use `m365_get` for the
  body. Results no longer contain raw Graph objects, `@odata.*` fields or
  cache metadata, and every field is always present (`null` when absent).
  `email_get` returns at most 20,000 body characters by default (it was
  50,000), controlled by `body_max_chars`.
- **`confirm` is now required** for: `calendar_create_event` and
  `calendar_update_event` when attendees would be emailed; `calendar_respond`
  when a response is sent (including proposing a new time); forwarding
  meeting invitations (`calendar_forward`); creating, updating or deleting
  Inbox rules that forward, redirect or delete mail (`email_rule_manage`);
  deleting a rule; and all sharing (`drive_share`). Sends, forwards, replies
  and deletes already required it.
- **`drive_share` has no default scope.** Choose `mode="link"` (view, edit or
  embed) or `mode="invite"`. The `organization` scope is removed and the old
  anonymous default is gone. It always requires `confirm=true`.
- **`drive_upload` defaults to `if_exists="fail"`.** It no longer silently
  overwrites; pass `if_exists="replace"` (or an `item_id`) to replace.
  Downloads via `m365_get_content` refuse to overwrite unless
  `overwrite=true`.
- **Cache controls reduced to `refresh`.** The `use_cache` and
  `force_refresh` parameters are removed from all tools; `refresh` exists on
  `m365_list` and `m365_get`. The five cache tools are now two admin tools,
  `admin_cache_get` and `admin_cache_invalidate` (typed `scope` instead of glob
  patterns), and cache keys are by account and resource, not tool name.
- **Result shapes changed.** Every tool returns `structuredContent` that
  validates against a published `outputSchema` plus a one-line text summary.
  Lists return `next_cursor` and `has_more`; the opaque cursor is only valid
  for the identical request, for 24 hours.
- **Folders and files unified.** `file_*` and `folder_*` become the
  `drive_item` resource; `emailfolders_*` becomes `email_folder`,
  `emailrules_*` becomes `email_rule`; move and rename are separate
  operations (`m365_move`, `m365_update`).
- **Moved emails and contacts get a new ID**, returned in the result.
- **Sign-in tools changed.** `account_authenticate` and
  `account_complete_auth` become `account_auth_begin` and
  `account_auth_complete` (admin tier). The device code and MSAL flow stay on
  the server behind an opaque `auth_session_id`; completion polls once and
  does not block. `account_list` no longer returns `account_type`.
- **Admin tools are hidden by default.** `account_list`, `account_auth_*`,
  `admin_cache_*` and `admin_server_info` register only when
  `M365_MCP_TOOLSETS` includes `admin`. The default is `core,extended`.
- **Local paths are restricted.** File tools accept only paths inside the
  working directory, the temp directory or `MCP_FILE_ALLOWED_ROOTS`, and refuse
  hidden and secret-like files for both reads and writes.
- **HTTP transport:** `MCP_AUTH_METHOD=oauth` and unknown values now fail at
  startup (an unknown value previously ran the server without
  authentication), and requests with a disallowed `Origin` header are
  rejected.

### Added

- `admin_reauth_schedule` (admin tier) and the `MCP_WEEKLY_RE_AUTH` setting: the
  server installs, repairs and health-checks a weekly job (Windows Task
  Scheduler, or cron on Linux and macOS) that refreshes every signed-in
  account's token so it never expires from disuse. New variables
  `MCP_RE_AUTH_DAY`, `MCP_RE_AUTH_TIME`, `MCP_RE_AUTH_CHECK_HOURS`; the job is
  `python -m m365_mcp.reauth_job`. Has no v0.x predecessor.
- MCP protocol 2026-07-28 support: the server runs on FastMCP 4.0 and the MCP
  Python SDK 2.2, and negotiates every revision from 2024-11-05 to 2026-07-28
  (`tests/test_protocol_versions.py` covers the handshake, auto and pinned
  2026-07-28 connect modes). `null` values in tool `_meta` (for example
  `confirm_rule`) are omitted on the wire by the SDK; clients should treat a
  missing key as `null`.
- 30 tools defined by generated JSON specs: 16 `core`, 7 `extended`, 7
  `admin` (see `docs/unified-tools/`). The server registers them from the spec
  in a fixed order, so `tools/list` is deterministic; `M365_MCP_TOOLSETS`
  selects tiers (default `core,extended`).
- Typed input and output schemas for every tool: descriptions on every
  parameter, enums, bounds and closed objects; `structuredContent` plus a
  text `summary`; input validated with JSON Schema 2020-12 (RFC 3339
  date-times) and per-tool rules with actionable errors.
- `m365_list`, `m365_get`, `m365_search`, `m365_get_content`, `m365_create`,
  `m365_update`, `m365_move` and `m365_delete` across email, mail folders,
  inbox rules, events, calendars, contacts, contact folders and OneDrive.
- Semantic email list filters (unread, sender, dates, attachments,
  importance, flagged, category); tree listing for mail and OneDrive folders;
  contact vCard export; OneDrive download URLs.
- `email_send(mode="draft")` to send an existing draft; BCC, CC and
  attachments on reply and forward; `body_format` and `importance` on drafts.
- `calendar_find_availability`: busy blocks and suggested free slots inside
  working hours.
- `drive_share(mode="invite")`, idempotent link creation, and `embed` links.
- `drive_copy` returns an `operation_id`; `m365_get(resource="operation")`
  reports progress.
- `email_folder_mark_all_read` and `email_folder_empty` use `$batch` and are
  bounded per call, reporting `remaining_unread` or partial failures.
- Opaque HMAC-protected pagination cursors (`M365_MCP_CURSOR_KEY`).
- Graph `$batch` support, a per-call deadline (45 s reads, 60 s writes) and
  server-side polling of asynchronous operations.
- Actionable error mapping for Graph failures (no URLs, codes or request IDs);
  `mask_error_details` hides unexpected errors from clients.
- Per-call JSON audit log (tool, resource, hashed account, duration, outcome,
  retries, result bytes, mutation flag; never argument values).
- Per-account rate limits: 20 per minute for sends, shares and deletes; 300
  per minute overall.
- Server `instructions` telling the model that `account_id` is optional, to ask
  the user before `confirm=true`, and to treat mail, event, contact and file
  content as untrusted data.
- Untrusted-content handling: control, zero-width and bidirectional
  characters stripped, HTML converted to text, previews and bodies capped.
- `services/` layer for all Graph logic, `projections.py`, `cursors.py`,
  `errors.py`, `resource_cache.py`, `observability.py`, `http_security.py`,
  `local_files.py`, `rate_limit.py`, `operations.py`, `auth_sessions.py`.
- New environment variables: `M365_MCP_TOOLSETS`, `M365_MCP_CURSOR_KEY`,
  `MCP_ALLOWED_ORIGINS`, `MCP_FILE_ALLOWED_ROOTS` and
  `MCP_FILE_DOWNLOAD_MAX_MB` (documented in `.env.example`).
- Golden-prompt evaluation harness in `evals/` (115 cases, 25% held out,
  mocked Graph), a CI workflow, and parity tests covering every row of the
  migration table.
- `jsonschema` is now a direct dependency (runtime input and output
  validation).

### Changed

- Cache warming and stale-entry refresh now work on the unified tools
  (`M365_MCP_CACHE_WARMING=true`): warming pre-loads the mail folder tree,
  inbox, upcoming events and contacts per account, and a stale `m365_list` or
  `m365_get` entry queues a background refresh of that request. Previously the
  refresh executor only knew the removed 0.x tool names.
- The documented Azure app permissions were corrected against Microsoft's
  permission tables: added `Mail.Send` (sending, replying and forwarding need
  it; `Mail.ReadWrite` does not cover them), `MailboxSettings.Read` (working
  hours and time zone for `calendar_find_availability`) and
  `Contacts.ReadWrite` (the contact tools create, update and delete); removed
  `People.Read`, which no tool uses. Grant them in the app registration.
- Default authority is `consumers`; the MSAL cache is cleaned of work and
  school accounts at sign-in.
- Cache keys are by account, resource, normalised parameters and cursor, with
  per-resource freshness rules; every write invalidates only the affected
  resources for its own account.
- The Graph client raises `GraphAPIError` (a subclass of `httpx.HTTPStatusError`)
  that carries the status, code and request ID for the audit log only.
- Steering documents, README, QUICKSTART, SECURITY, FILETREE, CLAUDE.md and the
  cache guides describe the unified surface. Breaking changes are now allowed
  only in a major version and must be listed here.
- Deleting a OneDrive item is described as a move to the recycle bin;
  deleting a meeting you organise states that cancellations are sent.

### Removed

- All 85 legacy tools (see the migration table) and their modules:
  `tools/account.py`, `cache_tools.py`, `calendar.py`, `contact.py`,
  `email.py`, `email_folders.py`, `email_rules.py`, `file.py`, `folder.py`,
  `search.py` and `server.py`, plus `search_router.py` and `account_type.py`.
- The Microsoft Search API path, organisation-scope sharing links and
  participant free/busy.
- The `use_cache` and `force_refresh` tool parameters and the emoji safety
  prefixes in tool descriptions (safety is expressed by annotations and
  `meta.safety_level`).
- `pyjwt` as a direct dependency (it was unused; MSAL still installs it
  transitively).

### Security

- HTTP transport: Origin validation on every request (loopback by default,
  `MCP_ALLOWED_ORIGINS` to change), constant-time bearer token comparison, and
  unsupported `MCP_AUTH_METHOD` values (including `oauth`) fail at startup.
- Personal accounts only; work and school sign-ins are rejected.
- Server-enforced `confirm` gates for sends, replies, forwards, sharing,
  deletes, rule changes that act silently, and calendar changes that notify
  attendees.
- Local file allowed roots and a deny-list (dotfiles, `*.pem`, `*.key`, token
  caches) for reads and writes, symlink resolution, no silent overwrite.
- Sign-in device codes and MSAL flow data no longer enter model context.
- Per-account rate limits, a per-call audit log without argument values or
  secrets, and HMAC-protected cursors.
- Untrusted third-party text is sanitised and labelled as data.

### Migration table (85 removed tools)

Generated from [`docs/unified-tools/legacy_mapping.json`](docs/unified-tools/legacy_mapping.json).
`account_id` is optional in every replacement. Calls that send, share, delete
or notify others need `confirm=true`.

| Removed tool (v0.x) | Replacement (v1.0.0) | Behaviour change |
|---|---|---|
| `account_list` | `account_list` | account_type removed |
| `account_authenticate` | `account_auth_begin` | opaque auth_session_id; device code stays server-side |
| `account_complete_auth` | `account_auth_complete` | session handle instead of flow dump; non-blocking; personal accounts only |
| `cache_task_get_status` | `admin_cache_get(view='task')` | None |
| `cache_task_list` | `admin_cache_get(view='tasks')` | None |
| `cache_get_stats` | `admin_cache_get(view='stats')` | None |
| `cache_invalidate` | `admin_cache_invalidate` | typed scope instead of glob pattern |
| `cache_warming_status` | `admin_cache_get(view='warming')` | None |
| `calendar_list_events` | `m365_list(resource='event', start, end)` | time window instead of days_ahead; recurrences expanded |
| `calendar_get_event` | `m365_get(resource='event')` | None |
| `calendar_create_event` | `calendar_create_event` | confirm when attendees; calendar_id, is_all_day, reminder, show_as added |
| `calendar_update_event` | `calendar_update_event` | typed changes; confirm when attendees affected |
| `calendar_delete_event` | `m365_delete(resource='event')` | organiser cancellation automatic; cancellation_message |
| `calendar_respond_event` | `calendar_respond` | confirm when a response is sent |
| `calendar_check_availability` | `calendar_find_availability` | own calendar only (Graph limitation for personal accounts) |
| `calendar_forward_event` | `calendar_forward` | None |
| `calendar_list_calendars` | `m365_list(resource='calendar')` | None |
| `calendar_create_calendar` | `m365_create(resource='calendar')` | None |
| `calendar_delete_calendar` | `m365_delete(resource='calendar')` | default calendar refused |
| `calendar_propose_new_time` | `calendar_respond(action='tentative'\|'decline', proposed_start, proposed_end)` | confirm when sending |
| `calendar_get_free_busy` | `calendar_find_availability` | own calendar only; free slots added |
| `contact_list` | `m365_list(resource='contact')` | optional contact folder |
| `contact_get` | `m365_get(resource='contact')` | None |
| `contact_create` | `m365_create(resource='contact')` | more fields; optional folder |
| `contact_update` | `m365_update(resource='contact')` | typed changes |
| `contact_delete` | `m365_delete(resource='contact')` | None |
| `contact_create_list` | `m365_create(resource='contact_folder')` | named contact_folder |
| `contact_add_to_list` | `m365_move(resource='contact', destination_id)` | real move instead of duplicate; new ID |
| `contact_export` | `m365_get_content(resource='contact', mode='vcard')` | None |
| `emailfolders_list` | `m365_list(resource='email_folder')` | None |
| `emailfolders_get` | `m365_get(resource='email_folder')` | None |
| `emailfolders_get_tree` | `m365_list(resource='email_folder', recursive=true)` | None |
| `emailfolders_create` | `m365_create(resource='email_folder')` | None |
| `emailfolders_rename` | `m365_update(resource='email_folder')` | None |
| `emailfolders_move` | `m365_move(resource='email_folder')` | None |
| `emailfolders_delete` | `m365_delete(resource='email_folder')` | well-known folders refused |
| `emailfolders_mark_all_as_read` | `email_folder_mark_all_read` | batched; bounded per call |
| `emailfolders_empty` | `email_folder_empty` | batched; bounded per call |
| `emailrules_list` | `m365_list(resource='email_rule')` | None |
| `emailrules_get` | `m365_get(resource='email_rule')` | None |
| `emailrules_create` | `email_rule_manage(action='create')` | typed Graph predicate/action set; confirm for forward/redirect/delete |
| `emailrules_update` | `email_rule_manage(action='update')` | as create |
| `emailrules_delete` | `m365_delete(resource='email_rule')` | None |
| `emailrules_move_top` | `email_rule_manage(action='reorder', position='top')` | None |
| `emailrules_move_bottom` | `email_rule_manage(action='reorder', position='bottom')` | None |
| `emailrules_move_up` | `email_rule_manage(action='reorder', position='up')` | None |
| `emailrules_move_down` | `email_rule_manage(action='reorder', position='down')` | None |
| `email_list` | `m365_list(resource='email')` | preview instead of body; filters; cursor |
| `email_get` | `m365_get(resource='email')` | default body cap 20k characters (was 50k) |
| `email_create_draft` | `email_create_draft` | bcc, body_format, importance |
| `email_send` | `email_send(mode='new')` | bcc; mode='draft' added |
| `email_update` | `m365_update(resource='email')` | typed changes |
| `email_delete` | `m365_delete(resource='email')` | None |
| `email_move` | `m365_move(resource='email')` | returns new ID |
| `email_reply` | `email_reply(mode='sender')` | cc and attachments added |
| `email_reply_all` | `email_reply(mode='all')` | cc and attachments added |
| `email_forward` | `email_forward` | bcc and attachments added |
| `email_get_attachment` | `m365_get_content(resource='email', mode='download')` | no silent overwrite |
| `email_mark_read` | `m365_update(resource='email', email_changes.is_read)` | None |
| `email_flag` | `m365_update(resource='email', email_changes.flag)` | None |
| `email_add_category` | `m365_update(resource='email', email_changes.categories_add)` | remove/set also available |
| `email_archive` | `m365_move(resource='email', destination_id='archive')` | None |
| `file_list` | `m365_list(resource='drive_item', item_type='file')` | None |
| `file_get` | `m365_get(resource='drive_item') + m365_get_content(mode='download')` | details and download split |
| `file_create` | `drive_upload(parent_id\|parent_path, local_path)` | if_exists default fail |
| `file_update` | `drive_upload(item_id, local_path)` | None |
| `file_delete` | `m365_delete(resource='drive_item')` | described as recycle bin |
| `file_copy` | `drive_copy` | operation handle + status |
| `file_move` | `m365_move(resource='drive_item')` | None |
| `file_rename` | `m365_update(resource='drive_item', drive_item_changes.name)` | None |
| `file_share` | `drive_share(mode='link')` | confirm; no default scope; invite mode added |
| `file_download_url` | `m365_get_content(resource='drive_item', mode='download_url')` | None |
| `folder_list` | `m365_list(resource='drive_item', item_type='folder')` | None |
| `folder_get` | `m365_get(resource='drive_item')` | None |
| `folder_get_tree` | `m365_list(resource='drive_item', item_type='folder', recursive=true)` | None |
| `folder_create` | `m365_create(resource='drive_item', drive_folder)` | None |
| `folder_delete` | `m365_delete(resource='drive_item')` | recycle bin |
| `folder_rename` | `m365_update(resource='drive_item')` | None |
| `folder_move` | `m365_move(resource='drive_item')` | None |
| `search_files` | `m365_search(resources=['drive_item'])` | None |
| `search_emails` | `m365_search(resources=['email'])` | whole mailbox via server-side $search |
| `search_events` | `m365_search(resources=['event'])` | explicit window |
| `search_contacts` | `m365_search(resources=['contact'])` | None |
| `search_unified` | `m365_search(resources=[...])` | Search API path removed |
| `server_get_version` | `admin_server_info` | None |

## [0.2.3] - 2026-09-26 (final 0.x release, tag `v0.2.3-final`)

This is the last release of the 85-tool surface. Everything below refers to
tools that 1.0.0 removes; see the migration table under
[1.0.0](#100---2026-09-26-unreleased) for the replacement of each one.

### Fixed (reliability and authentication review, September 2026)

- `authenticate.py` checks every account with a forced token refresh, offers
  re-sign-in for expired accounts, and exits 1 unless all accounts are usable.
- The token cache uses `msal-extensions` (cross-process lock, reload on
  change), and one MSAL app is reused per client ID and tenant.
- Sign-in errors carry the MSAL reason; an account that needs sign-in raises
  `SignInRequiredError` instead of a generic failure.
- `account_complete_auth` polls once instead of blocking for up to 15
  minutes.
- A 401 triggers one forced token refresh and a retry; network errors are
  retried (connect errors for every method, timeouts only for idempotent
  ones) with a fresh token per attempt.
- `Retry-After` accepts seconds or an HTTP date and is honoured on 503.
- POST requests are no longer retried after an ambiguous 5xx or a read
  timeout, so a send cannot be duplicated.
- Chunked uploads no longer send `Authorization` to the pre-authenticated
  upload URL, and an empty final 201 no longer crashes.
- Pagination resends the first page's query headers on every page (plain-text
  bodies and `ConsistencyLevel`), and `graph.request()` no longer mutates the
  caller's `params`.
- The device flow completes against the authority that issued the code.

### Added

- **📧 Email Archive Tool**: Added `email_archive` quick action tool for convenient email archiving
  - `email_archive(email_id, account_id)` - Move emails to Archive folder with single command (✏️ moderate)
  - Convenience wrapper around `email_move` that specifically targets the archive folder
  - Includes automatic cache invalidation for affected email lists
  - Added 2 validation tests in `tests/test_email_quick_actions_validation.py`

### Changed

- **MCP Tool Signature Compatibility Policy**: Documented that existing
  account-scoped tool parameter order is preserved for generated-client and
  saved-call compatibility. New tools should follow nearby family conventions
  and any future account-id-first migration must be explicit.
- **Tool Naming Consistency**: Renamed `reply_all_email` to `email_reply_all` for consistency with naming conventions
  - Updated function name in `src/m365_mcp/tools/email.py:1058`
  - Updated MCP tool registration name from "reply_all_email" to "email_reply_all"
  - Updated test function name in `tests/test_integration.py` from `test_reply_all_email` to `test_email_reply_all`
  - All references and documentation updated to reflect the new name

### Fixed

- **Type Safety Improvements**: Resolved all 48 pyright type errors for improved code quality
  - Added type stubs for sqlcipher3 module with `type: ignore` annotations
  - Fixed Path/str type handling in cache migration utilities
  - Added None checks for datetime operations in cache warming
  - Fixed missing return statement in health check main function
  - Corrected type annotation from `any` to `Any` in logging configuration
  - Added proper type annotations and assertions for logger initialization
  - Updated `_check_upn_domain` to accept `str | None` parameter
  - Added type ignore comments for sqlcipher3 in test files

### Testing

- **Complete Integration Test Suite**: Rewrote all integration tests using working async pattern
  - `tests/test_integration.py` - 34 integration tests, all passing (125.80s, ~3.7s per test)
  - Tests cover: emails (10), calendar (7), contacts (5), files (5), search (4), attachments (1), account (1), send (1)
  - Uses proven async pattern: `async for session in get_session()` for stability
  - Each test spawns independent MCP server session (no session-scoped fixtures due to asyncio task group limitations)
- **Email Folder Tools Integration Tests**: Added comprehensive integration tests for all 6 new email folder management tools
  - `tests/test_email_folders_integration.py` - 7 integration tests, all passing (16.49s, ~2.4s per test)
  - Tests verify: list, get, get_tree, create, delete, rename, and move operations
  - Tests include proper cleanup with try/finally blocks for created resources
  - `tests/test_email_folders_validation.py` - 17 unit tests, all passing

### Added

- **📁 Email Folder Management Tools**: Added 6 new MCP tools for comprehensive email folder management
  - `emailfolders_create(display_name, account_id, parent_folder_id?)` - Create new mail folders at root or as child folders (✏️ moderate)
  - `emailfolders_rename(folder_id, new_display_name, account_id)` - Rename existing mail folders (✏️ moderate)
  - `emailfolders_move(folder_id, destination_folder_id, account_id)` - Move folders to different parent folders (✏️ moderate)
  - `emailfolders_delete(folder_id, account_id, confirm)` - Permanently delete folders and all contents (🔴 critical, requires confirmation)
  - `emailfolders_mark_all_as_read(folder_id, account_id)` - Mark all messages in folder as read (✏️ moderate)
  - `emailfolders_empty(folder_id, account_id, confirm)` - Permanently delete all messages in folder (🔴 critical, requires confirmation)
  - All tools follow MCP naming conventions with proper safety annotations
  - Comprehensive input validation and error handling
  - Critical operations require explicit `confirm=True` parameter to prevent accidents

- **📂 OneDrive Folder Management Tools**: Added 4 new MCP tools for OneDrive folder management (mirrors email folders pattern)
  - `folder_create(name, account_id, parent_folder_id?)` - Create OneDrive folders at root or as child folders (✏️ moderate)
  - `folder_rename(folder_id, new_name, account_id)` - Rename existing OneDrive folders (✏️ moderate)
  - `folder_move(folder_id, destination_folder_id, account_id)` - Move folders to different parent folders (✏️ moderate)
  - `folder_delete(folder_id, account_id, confirm)` - Permanently delete folders and all contents (🔴 critical, requires confirmation)
  - Follows exact same pattern as emailfolders tools for consistency
  - Full input validation and error handling
  - Unit tested with 13 tests, all passing
  - Fills obvious gap identified after emailfolders implementation

- **🚀 High-Performance Encrypted Cache System**: Complete implementation of enterprise-grade caching system with dramatic performance improvements
  - **Core Implementation** (Phase 1-3, previously added):
    - Encryption key management (`src/m365_mcp/encryption.py` - 273 lines)
    - Cache database schema with migrations
    - Cache configuration system with TTL policies
    - Encrypted cache manager with compression
    - Background worker for async operations
    - Cache warming system for instant responses

  - **Cache Management Tools** (5 new MCP tools):
    - `cache_get_stats()` - View cache statistics (size, entries, hit rate, oldest/newest entries)
    - `cache_invalidate(pattern, account_id?, reason?)` - Manually invalidate cache entries by pattern
    - `cache_task_enqueue(task_type, params, priority?)` - Queue background cache tasks
    - `cache_task_status(task_id)` - Check status of queued cache tasks
    - `cache_task_list(account_id?, status?)` - List all cache tasks by account or status

  - **Tool Integration** (Phase 3):
    - Added caching to `folder_get_tree` - 30s → <100ms (**300x faster**)
    - Added caching to `email_list` - 2-5s → <50ms (**40-100x faster**)
    - Added caching to `file_list` - 1-3s → <30ms (**30-100x faster**)
    - Optional cache parameters on all cached tools:
      - `use_cache: bool = True` - Enable/disable caching for this request
      - `force_refresh: bool = False` - Bypass cache and fetch fresh data
    - Automatic cache invalidation on write operations (file_create, email_send, etc.)

  - **Performance Features**:
    - Three-state TTL lifecycle: Fresh (0-5 min) → Stale (5-30 min) → Expired (>30 min)
    - Automatic compression for entries ≥50KB (70-80% size reduction)
    - Connection pooling (5 connections) for concurrent access
    - Automatic cleanup at 80% of 2GB limit
    - Cache warming on server startup (non-blocking)
    - >80% cache hit rate on typical workloads
    - >70% API call reduction

  - **Security & Compliance**:
    - AES-256 encryption via SQLCipher for all cached data
    - Secure key storage via system keyring (macOS Keychain, Windows Credential Manager, Linux Secret Service)
    - Environment variable fallback (`M365_MCP_CACHE_KEY`) for headless servers
    - GDPR Article 32 compliant (encryption at rest, data minimization, audit logging)
    - HIPAA §164.312 compliant (encryption, access controls, audit controls, integrity)
    - Account-based isolation (multi-tenant safe)
    - Security audit rating: A- (Excellent)

  - **Testing & Quality** (Phase 4):
    - 79 cache tests passing (100% pass rate)
    - 46 security-focused tests
    - Comprehensive test coverage:
      - `tests/test_cache.py` (18 tests) - Cache operations, compression, TTL, invalidation
      - `tests/test_encryption.py` (26 tests) - Key generation, keyring, environment fallback
      - `tests/test_cache_schema.py` (8 tests) - Database structure, configuration
      - `tests/test_cache_warming.py` (11+ tests) - Cache warming, priority queue
      - `tests/test_background_worker.py` (9 tests) - Task queue, retries, priority
      - `tests/test_tool_caching.py` (7 tests) - Tool integration, key generation
      - `tests/test_cache_tools.py` (~15 tests) - Cache management tools

  - **Documentation** (Phase 5):
    - Updated `CLAUDE.md` with complete cache architecture section (65+ lines)
    - Updated `README.md` with cache features and benchmarks (70+ lines)
    - Updated `.projects/steering/tech.md` with cache dependencies and architecture
    - Updated `.projects/steering/structure.md` with cache modules and layers
    - Created `docs/cache_user_guide.md` (389 lines) - Complete user guide with troubleshooting
    - Created `docs/cache_security.md` (486 lines) - Security, compliance, backup/recovery
    - Created `docs/cache_examples.md` (642 lines) - Practical patterns and workflows
    - Created `cache_update_v2/SECURITY_AUDIT_REPORT.md` - Complete security audit
    - Created `cache_update_v2/FINAL_REPORT.md` - Implementation completion report

  - **Impact**:
    - **300x performance improvement** for folder operations
    - **40-100x performance improvement** for email/file operations
    - **Zero breaking changes** - fully backward compatible
    - **Automatic migration** - seamless upgrade from previous versions
    - **Production-ready** - comprehensive testing and security audit complete

- **Encryption Key Management**: Added comprehensive encryption key management system for secure cache implementation
  - Implemented `EncryptionKeyManager` class in `src/m365_mcp/encryption.py` (273 lines)
  - 256-bit AES encryption key generation using cryptographically secure random values
  - Multi-source key retrieval with priority order:
    1. System keyring (Linux Secret Service API/GNOME Keyring/KWallet, macOS Keychain, Windows Credential Manager)
    2. Environment variable (`M365_MCP_CACHE_KEY`)
    3. Automatic generation with keyring storage
  - Cross-platform support (Linux/macOS/Windows)
  - Graceful degradation for headless server deployments
  - Comprehensive unit test coverage (28 tests, 100% passing)
  - Test file: `tests/test_encryption.py` (309 lines)
  - Prepares foundation for encrypted SQLite cache system

- **Cache Database Schema**: Created comprehensive SQLite database schema for encrypted cache system
  - Migration script: `src/m365_mcp/migrations/001_init_cache.sql` (171 lines)
  - Four main tables:
    - `cache_entries`: Stores cached API responses with compression and TTL management
    - `cache_tasks`: Background task queue for cache warming and async operations
    - `cache_invalidation`: Audit trail for cache invalidation operations
    - `cache_stats`: System-wide cache performance metrics
  - 9 performance indexes for optimal query performance
  - Schema version tracking with migration history
  - Initial data seeding for statistics tracking
  - Full encryption at rest via SQLCipher integration

- **Cache Configuration System**: Implemented comprehensive cache configuration module
  - Configuration file: `src/m365_mcp/cache_config.py` (244 lines)
  - TTL Policies for 12 resource types:
    - Folder operations: 15-30min fresh, 1-2h stale
    - Email operations: 2-15min fresh, 10min-1h stale
    - File operations: 10-20min fresh, 1-2h stale
    - Contact operations: 20-30min fresh, 2-4h stale
    - Calendar operations: 5-10min fresh, 30min-1h stale
    - Search operations: 1min fresh, 5min stale
  - Three-state cache model (Fresh/Stale/Expired/Missing)
  - Cache limits configuration:
    - Max entry size: 10MB
    - Max total size: 2GB soft limit
    - Cleanup threshold: 80% (triggers at 1.6GB)
    - Cleanup target: 60% (cleans down to 1.2GB)
    - Max entries per account: 10,000
    - Compression threshold: 50KB
  - Cache warming operations configuration
  - Cache key generation and parsing utilities
  - Test file: `tests/test_cache_schema.py` (10 tests, all passing)

- **Encrypted Cache Manager**: Implemented comprehensive cache manager with encryption, compression, and TTL support
  - Cache manager: `src/m365_mcp/cache.py` (481 lines)
  - `CacheManager` class with full lifecycle management:
    - Encrypted database operations via SQLCipher (AES-256)
    - Connection pooling (max 5 connections) with proper cleanup
    - Automatic gzip compression for entries ≥50KB
    - Three-state TTL detection (Fresh/Stale/Expired)
    - Pattern-based cache invalidation with wildcard support
    - Automatic cleanup at 80% capacity threshold
    - LRU eviction when needed
    - Comprehensive cache statistics
  - Migration utilities: `src/m365_mcp/cache_migration.py` (121 lines)
    - Migrate from unencrypted to encrypted cache
    - Automatic detection and migration on startup
    - Backup creation for safety
  - Core methods implemented:
    - `get_cached()`: Retrieve with decompression and state detection
    - `set_cached()`: Store with compression and encryption
    - `invalidate_pattern()`: Wildcard pattern invalidation
    - `cleanup_expired()`: Manual cleanup of expired entries
    - `_check_cleanup()`: Automatic cleanup trigger at 80%
    - `_cleanup_to_target()`: Clean to 60% target size
    - `get_stats()`: Comprehensive statistics by account and resource type
  - Test file: `tests/test_cache.py` (361 lines, 19 tests, all passing)
  - Test coverage:
    - Encrypted read/write operations
    - Compression for large entries (≥50KB)
    - Fresh/Stale/Expired state detection
    - Pattern invalidation with wildcards
    - Automatic cleanup at 80% threshold
    - Connection pooling
    - Encryption at rest verification
    - Cache statistics tracking
    - Hit count tracking

### Fixed

- **OneDrive Folder Tree Hanging Issue**: Fixed `folder_get_tree` tool causing server hang and unresponsive behavior
  - Removed inefficient `childCount > 0` check that caused unnecessary API calls
  - The `childCount` includes both files AND folders, leading to API calls even for folders with only files
  - Fixed by always recursing and letting empty results naturally terminate recursion
  - Added try-catch error handling to prevent entire tree failure on single branch errors
  - Improved efficiency by only making API calls when subfolders exist
  - Server now properly handles Ctrl+C interrupts during folder tree operations
  - Location: `src/m365_mcp/tools/folder.py:185-226`

### Changed

- **Environment Variable Loading in Startup Script**: Enhanced `start_mcp_with_monitoring.sh` to automatically load environment variables from `.env` file in addition to shell environment. The `.env` file takes precedence over shell environment variables. This allows users to keep all configuration in the `.env` file without requiring shell environment variable exports.

### Changed - BREAKING

- **Project Renamed**: Renamed from `microsoft-mcp` to `m365-mcp` for cleaner branding and consistency
  - **Package name**: `microsoft-mcp` → `m365-mcp` (pyproject.toml:2)
  - **Module name**: `microsoft_mcp` → `m365_mcp` (src/ folder structure)
  - **CLI command**: `microsoft-mcp` → `m365-mcp` (pyproject.toml:21)
  - **Environment variables**: All renamed with new prefix
    - `MICROSOFT_MCP_CLIENT_ID` → `M365_MCP_CLIENT_ID`
    - `MICROSOFT_MCP_TENANT_ID` → `M365_MCP_TENANT_ID`
  - **Migration required**: Users must update their `.env` files and CLI commands
    - Update environment variable names in `.env` configuration files
    - Update Claude Desktop config from `uvx --from git+https://github.com/robin-collins/microsoft-mcp.git microsoft-mcp` to `uvx --from git+https://github.com/robin-collins/m365-mcp.git m365-mcp`
    - Update any scripts or automation using old package/module names
  - All documentation, shell scripts, and test files updated to reflect new naming

### Added

- **Server Version Tool**: Added new `server_get_version` tool that returns the current version of the m365-mcp server. Useful for diagnostics, troubleshooting, and ensuring compatibility. Returns package name and semantic version string.
- **Version in Startup Logs**: Server startup logs now display the version number (e.g., "M365 MCP Server Starting v0.1.4"). Version is dynamically retrieved from package metadata to match pyproject.toml.

### Fixed

- **Token Cache Location**: Reverted token cache location from `.cache/token_cache.json` (project directory) back to `~/.m365_mcp_token_cache.json` (user home directory). Project directory may not always be user-writable, and user credentials should be stored in standard user-specific locations for proper permissions and security.
- **stdio Mode JSON-RPC Corruption**: Fixed critical issue where print statements writing to stdout corrupted JSON-RPC protocol communication in stdio mode
  - Removed debug print statement from `src/m365_mcp/__init__.py:2` that wrote to stdout
  - Updated all authentication print statements in `src/m365_mcp/auth.py` to write to stderr instead of stdout (lines 78-80, 114-121)
  - stdio transport requires exclusive stdout usage for JSON-RPC messages per MCP protocol specification
  - All diagnostic and authentication messages now properly use stderr to maintain protocol integrity

### Added
- Command-line argument `--env-file` to specify custom environment file path
  - Supports both `m365-mcp` server and `authenticate.py` script
  - Default: `.env` (maintains backward compatibility)
  - Usage: `m365-mcp --env-file .env.stdio` or `python authenticate.py --env-file .env.http`
  - Facilitates testing different MCP server modes (stdio vs HTTP)
  - Tests now support custom env file via `TEST_ENV_FILE` environment variable
- Example environment files for different modes
  - `.env.stdio.example` - Pre-configured for stdio mode (default)
  - `.env.http.example` - Pre-configured for HTTP mode with bearer auth
  - Both include usage instructions and security notes
- `ENV_FILE_USAGE.md` - Comprehensive guide for using `--env-file` argument with examples and use cases

### Changed
- **Environment Loading**: Refactored environment loading to occur before module imports in `server.py` and `authenticate.py`
- **Auth Module**: Removed module-level `load_dotenv()` from `auth.py` (now loaded by caller before import)

### Added

- **Comprehensive Logging System**: Multi-tier structured logging for production debugging and monitoring
  - `src/microsoft_mcp/logging_config.py` - Centralized logging configuration with structured JSON and human-readable formats
  - Multiple log outputs: JSON structured logs (`mcp_server_all.jsonl`), error-only logs (`mcp_server_errors.jsonl`), human-readable logs (`mcp_server.log`)
  - Automatic log rotation (10 files × 10MB per log type)
  - Configurable log levels via `MCP_LOG_LEVEL` environment variable (DEBUG, INFO, WARNING, ERROR, CRITICAL)
  - Color-coded console output for improved readability
  - Detailed request/response logging with timing, client IP, and status codes

- **Health Check & Monitoring System**: Continuous diagnostics collection with automatic kill on failure
  - `monitor_mcp_server.sh` - Comprehensive monitoring and diagnostics script
  - Continuous metrics collection: Memory (RSS), CPU%, threads, open files, response times
  - Health check monitoring via HTTP endpoint with configurable check intervals
  - Automatic process kill on failure (graceful SIGTERM followed by SIGKILL if needed)
  - **NO AUTO-RESTART**: Server is killed and monitoring exits to allow investigation
  - Configurable failure thresholds (default: 3 consecutive failures)
  - Comprehensive error report generation including metrics history, logs, system info, and process details
  - Metrics log (`logs/metrics.log`) with CSV format for easy analysis

- **Health Check Utility Module**: Programmatic health checking
  - `src/microsoft_mcp/health_check.py` - Python module for health check operations
  - Async and sync health check functions
  - Continuous monitoring mode with configurable intervals
  - Command-line interface: `python -m microsoft_mcp.health_check`
  - Bearer token authentication support
  - Detailed result objects with response times and error information

- **Startup Scripts**: Easy server deployment with monitoring
  - `start_mcp_with_monitoring.sh` - Launches server with automatic monitoring
  - Automatic bearer token generation if not provided
  - Environment variable validation
  - Background process management with PID tracking
  - Graceful shutdown on SIGTERM/SIGINT
  - Health check verification before declaring server ready

- **Documentation**: Comprehensive monitoring and troubleshooting guide
  - `MONITORING.md` - Complete guide to logging, monitoring, and troubleshooting
  - Log file structure and formats
  - Searching and analyzing logs
  - Error report interpretation
  - Common troubleshooting scenarios
  - Production deployment best practices
  - Security considerations for log management

### Changed

- **Server Startup**: Enhanced with comprehensive logging and signal handling
  - Added structured logging initialization on startup
  - Added signal handlers for graceful shutdown (SIGTERM, SIGINT)
  - Added startup information logging (PID, Python version, environment variables)
  - Added error logging for all failure scenarios
  - Added request/response logging in HTTP middleware with timing metrics
  - Added authentication failure logging with client IP tracking

- **HTTP Middleware**: Enhanced with detailed request tracking
  - Added timing instrumentation for all requests
  - Added client IP logging for security auditing
  - Added debug logging for health checks and browser requests
  - Added warning logging for authentication failures with reason codes
  - Added info logging for successful authenticated requests with status and duration

### Fixed

- **HTTP Transport MCP Endpoint Routing**: Fixed critical routing issue where `/mcp` endpoint returned 307 redirect followed by 404 error. Root cause was double-path mounting - `mcp.http_app()` returns an app with routes already at `/mcp`, so mounting it again at `/mcp` created incorrect paths. Fixed by mounting the FastMCP app at root `/` instead of at the configured path. (`src/microsoft_mcp/server.py:160`)
- **Shell Script Variable Quoting**: Fixed shellcheck warnings in `start_mcp_with_monitoring.sh` by properly quoting variables in command substitutions to prevent globbing and word splitting issues (`${PID_FILE}`, `${MONITOR_PID_FILE}`)

### Added

- **Phase 3 Validation Tests**: Added targeted suites covering update dictionary guards, pagination limits, and search date windows (`tests/test_contact_validation.py`, `tests/test_email_rules_validation.py`, `tests/test_search_validation.py`, `tests/test_folder_validation.py`).
- **Phase 4 Validation Tests**: Added read-only coverage for folder choice, query bounds, and path validation (`tests/test_email_validation.py`, `tests/test_search_validation.py`, `tests/test_folder_validation.py`).
- **Phase 1 Confirmation Regression Tests**: Added `tests/test_tool_confirmation.py` to assert the shared `require_confirm` validator guards all destructive and dangerous Phase 1 tools (email_send, email_reply, email_delete, file_delete, contact_delete, calendar_delete_event, emailrules_delete).
- **Parameter Validation Phase 1 Tasklist Review**: Comprehensive review and update of Phase 1 implementation plan
  - **Review Summary**: Created `reports/todo/PHASE1_REVIEW_SUMMARY.md` documenting critical findings
  - **Key Finding**: All 7 tools (5 delete + 2 send/reply) **already have** confirm validation - Phase 1 is REFACTORING task
  - **Scope Clarification**: Phase 1 refactors 7 tools (not 5) to use shared validators:
    - 5 Critical (Delete): email_delete, file_delete, contact_delete, calendar_delete_event, emailrules_delete
    - 2 Dangerous (Send/Reply): email_send, email_reply
  - **Prerequisites Added**: Explicit dependencies on Critical Path Sections 3-5 completion
  - **Status**: ✅ Ready for implementation after validators.py is complete
- **Phase 2 Validation Tests**: Added dedicated suites
  (`tests/test_email_validation.py`, `tests/test_calendar_validation.py`)
  covering recipient normalization, reply body enforcement, calendar response
  enums, and datetime windows.

### Changed

- Hardened moderate operations as part of Phase 3: enforced strict whitelist validation for `email_update`, `calendar_update_event`, `contact_update`, and `emailrules_update`; applied explicit limit bounds across email, folder, contact, file, and search tools; added day-range validation to `search_events`; normalised error handling to emit `ValidationError` for rejected input.
- Completed Phase 4 read-only validation: enforced canonical folder names for email listing/move operations, added non-empty/length-checked search queries with entity-type validation, and required absolute OneDrive paths for list/get helpers.
- Hardened dangerous email and calendar tools with Phase 2 parameter
  validation: recipient normalization/deduplication with limits, reply body
  checks, calendar response enum enforcement, attendee validation, and ISO
  datetime/timezone verification.

- **Parameter Validation Critical Path Tasklist Review**: Comprehensive review and enhancement of validation implementation plan
  - **Review Summary**: Created `reports/todo/CRITICAL_PATH_REVIEW_SUMMARY.md` documenting findings and updates
  - **Status**: ✅ Ready for implementation with 40+ enhancements across all 5 critical path sections

- **Parameter Validation Critical Path Tasklist**: Granular implementation tasklist for must-complete-first validation tasks (ENHANCED)
  - Section 1: Replace subprocess in `file.py:get_file` with httpx/graph client (CRITICAL SECURITY FIX)
    - Added URL validation for SSRF prevention (verify graph.microsoft.com domain)
    - Added file size limit checks before download (memory exhaustion prevention)
    - Added retry logic with exponential backoff for transient network failures
    - Added download path validation using `ensure_safe_path` helper
  - Section 2: Path traversal protection for all file operations (CRITICAL SECURITY FIX)
    - Windows-specific restrictions: UNC paths, drive letters, reserved filenames (CON, PRN, AUX, NUL, COM1-9, LPT1-9)
    - Added `validate_onedrive_path` helper for OneDrive path format validation
    - Comprehensive testing for path traversal, symlinks, alternate data streams
  - Section 3: Create `src/microsoft_mcp/validators.py` with shared validation helpers
    - Added 20+ validators including email, datetime, path, Graph ID, URL validation
    - Standardized error message format: `"Invalid {param} '{value}': {reason}. Expected: {guidance}"`
    - Added `ValidationError` exception class for consistency
    - Added cross-cutting concerns: logging strategy, PII protection, performance benchmarks
    - Deferred `validate_bearer_token_scopes` to Phase 2 (requires OAuth library integration)
  - Section 4: Enhanced `tests/conftest.py` with comprehensive fixtures
    - Added data fixtures: `mock_account_id`, `mock_email_data`, `mock_file_metadata`, `mock_calendar_event`, `mock_contact_data`
    - Added file system fixtures: `temp_safe_dir`, `mock_download_file`
    - Added datetime fixtures: `freeze_time`, `sample_iso_datetimes`
  - Section 5: Comprehensive validator testing with 100% coverage target
    - Organized tests by validator type (core, email, datetime, path, complex)
    - Added error message validation tests to verify template compliance and PII protection
    - Added platform compatibility tests for Windows and POSIX path handling
    - Added performance benchmarks for expensive validators
    - Added integration tests to verify backward compatibility
  - See `reports/todo/CRITICAL_PATH_TASKLIST.md` for detailed implementation plan

- **Parameter Validation Plan**: Comprehensive implementation plan for strengthening validation across all 50 MCP tools
  - Security-focused approach with immediate fixes for critical vulnerabilities
  - Shared validation toolkit design (`validators.py`) for consistent error handling
  - Phased rollout prioritizing destructive operations (delete), dangerous operations (send), then moderate/safe operations
  - Enhanced testing infrastructure with Graph API mocking and 100% validator coverage target
  - Full compliance verification with project steering documents
  - Estimated timeline: 12-15 days for complete implementation
  - See `reports/todo/PARAMETER_VALIDATION_PLAN.md` for detailed implementation strategy

- **Security Fixes**
  - Replaced `file_get` subprocess usage with streaming `httpx` client, including Microsoft domain allow-listing, size pre-checks, retry logic, and configurable timeouts.
  - Hardened file and attachment operations with `ensure_safe_path`, Windows-specific restrictions, and overwrite prevention.
  - Added OneDrive path validation and Microsoft Graph ID validation utilities.

- **Shared Validators**
  - Introduced `src/microsoft_mcp/validators.py` containing reusable helpers and the `ValidationError` class.
  - Implemented sanitised error formatting that guards against PII exposure.
  - Added security-focused helpers for Graph URL validation, OneDrive path validation, and filesystem safety checks.

- **Testing Infrastructure**
  - Added `tests/conftest.py` with Graph API fixtures and reusable factories.
  - Created dedicated unit tests for file downloads (`tests/test_file_get.py`) and validator helpers (`tests/test_validators.py`).

- **Documentation**
  - Documented file download safeguards, configuration flags, and SSRF protection in `SECURITY.md`.
  - Updated `FILETREE.md` to reflect the implemented validators module and new test suites.

- **Modular Tool Architecture**: Refactored 50 MCP tools into organized package structure:
  - `src/microsoft_mcp/tools/account.py` - 3 account management tools
  - `src/microsoft_mcp/tools/calendar.py` - 6 calendar tools
  - `src/microsoft_mcp/tools/contact.py` - 5 contact management tools
  - `src/microsoft_mcp/tools/email.py` - 9 email tools
  - `src/microsoft_mcp/tools/email_folders.py` - 3 email folder tools
  - `src/microsoft_mcp/tools/email_rules.py` - 9 email rule tools
  - `src/microsoft_mcp/tools/file.py` - 5 OneDrive file tools
  - `src/microsoft_mcp/tools/folder.py` - 3 OneDrive folder tools
  - `src/microsoft_mcp/tools/search.py` - 5 search tools
- **Package Exports**: `src/microsoft_mcp/tools/__init__.py` provides clean imports for all tools
- **MCP Instance Management**: Created `src/microsoft_mcp/mcp_instance.py` containing single FastMCP instance
  - Avoids circular import issues between tools.py and tool modules
  - All tool modules import `mcp` from `mcp_instance.py`
  - Registry file `tools.py` imports tool modules to trigger registration
  - Original monolithic `tools.py` backed up to `reference/tools_monolithic_original.py`

### Changed - BREAKING

- **Phase 1 Confirmation Refactor**: Replaced inline `confirm` checks in `email_send`, `email_reply`, `email_delete`, `file_delete`, `contact_delete`, `calendar_delete_event`, and `emailrules_delete` with the shared `require_confirm` validator. The tools now emit standardized `ValidationError` messages (`Invalid confirm 'False': … Expected: Explicit user confirmation`) while preserving original signatures and metadata.
- **Tool Naming Convention Migration**: All 50 MCP tools have been renamed to follow `category_verb_entity` convention for better organization and clarity:
  - **Account tools** (3): `list_accounts` → `account_list`, `authenticate_account` → `account_authenticate`, `complete_authentication` → `account_complete_auth`
  - **Email tools** (10): `list_emails` → `email_list`, `get_email` → `email_get`, `create_email_draft` → `email_create_draft`, `send_email` → `email_send`, `update_email` → `email_update`, `delete_email` → `email_delete`, `move_email` → `email_move`, `reply_to_email` → `email_reply`, `reply_all_email` → `email_reply_all`, `get_attachment` → `email_get_attachment`
  - **Email Folders tools** (3): `list_mail_folders` → `emailfolders_list`, `get_mail_folder` → `emailfolders_get`, `get_mail_folder_tree` → `emailfolders_get_tree`
  - **Email Rules tools** (9): `list_message_rules` → `emailrules_list`, `get_message_rule` → `emailrules_get`, `create_message_rule` → `emailrules_create`, `update_message_rule` → `emailrules_update`, `delete_message_rule` → `emailrules_delete`, `move_rule_to_top` → `emailrules_move_top`, `move_rule_to_bottom` → `emailrules_move_bottom`, `move_rule_up` → `emailrules_move_up`, `move_rule_down` → `emailrules_move_down`
  - **Calendar tools** (7): `list_events` → `calendar_list_events`, `get_event` → `calendar_get_event`, `create_event` → `calendar_create_event`, `update_event` → `calendar_update_event`, `delete_event` → `calendar_delete_event`, `respond_event` → `calendar_respond_event`, `check_availability` → `calendar_check_availability`
  - **Contact tools** (5): `list_contacts` → `contact_list`, `get_contact` → `contact_get`, `create_contact` → `contact_create`, `update_contact` → `contact_update`, `delete_contact` → `contact_delete`
  - **File tools** (5): `list_files` → `file_list`, `get_file` → `file_get`, `create_file` → `file_create`, `update_file` → `file_update`, `delete_file` → `file_delete`
  - **Folder tools** (3): `list_folders` → `folder_list`, `get_folder` → `folder_get`, `get_folder_tree` → `folder_get_tree`
  - **Search tools** (5): `search_files`, `search_emails`, `search_events`, `search_contacts` (unchanged), `unified_search` → `search_unified`
- **Safety Annotations**: All tools now include FastMCP `annotations` parameter with safety hints:
  - `readOnlyHint`: Indicates read-only operations (23 safe tools)
  - `destructiveHint`: Marks destructive operations like delete (5 critical tools)
  - `idempotentHint`: Indicates if repeated calls have same effect
  - `openWorldHint`: Always true for all tools
- **Meta Information**: All tools include `meta` parameter with categorization:
  - `category`: Tool category (account, email, emailfolders, emailrules, calendar, contact, file, folder, search)
  - `safety_level`: Safety classification (safe, moderate, dangerous, critical)
  - `requires_confirmation`: Flagged for dangerous/critical operations
- **Enhanced Descriptions**: All tool descriptions now include:
  - Emoji visual indicators (📖 safe, ✏️ moderate, 📧 dangerous, 🔴 critical, ⚠️ special caution)
  - Safety hints in parentheses (e.g., "read-only, safe for unsupervised use")
  - WARNING messages for dangerous/critical operations
  - Comprehensive documentation with examples for complex tools
- **Confirmation Parameters**: Added required `confirm: bool = False` parameter to all dangerous and critical operations:
  - **Dangerous (Send)**: `email_send`, `email_reply`, `email_reply_all` - must set `confirm=True` to send emails
  - **Critical (Delete)**: `email_delete`, `emailrules_delete`, `calendar_delete_event`, `contact_delete`, `file_delete` - must set `confirm=True` to delete
  - All confirmation-required tools raise `ValueError` with clear message if `confirm` is not `True`

### Added 2025-10-04

- **Streamable HTTP Transport Support** - Modern MCP Streamable HTTP protocol (spec 2025-03-26+) for web/API access with configurable host/port/path
- **Bearer Token Authentication** - Secure token-based authentication for HTTP transport with automatic validation
- **OAuth Authentication Support** - Enterprise-grade OAuth 2.0 authentication for HTTP transport (FastMCP 2.0+)
- **Security Safeguards**:
  - HTTP transport refuses to start without authentication (requires explicit `MCP_ALLOW_INSECURE=true` override)
  - Token length validation (minimum 32 characters recommended)
  - Network binding warnings for `0.0.0.0` exposure
  - Health check endpoint at `/health` (no auth required)
  - MCP endpoint at configurable path (default `/mcp`)
- Email folder navigation tools:
  - `list_mail_folders` - List root or child mail folders with metadata (childFolderCount, unreadItemCount, etc.)
  - `get_mail_folder` - Get specific mail folder details by folder ID
  - `get_mail_folder_tree` - Build recursive email folder tree with configurable max depth
- OneDrive folder navigation tools:
  - `list_folders` - List only folders (not files) in OneDrive location
  - `get_folder` - Get specific OneDrive folder metadata
  - `get_folder_tree` - Build recursive OneDrive folder tree with configurable max depth
- Message rule (email filter) management tools:
  - `list_message_rules` - List all inbox message rules
  - `get_message_rule` - Get specific rule details
  - `create_message_rule` - Create new email filtering rule with conditions and actions
  - `update_message_rule` - Update existing rule
  - `delete_message_rule` - Delete a rule
  - `move_rule_to_top` - Move rule to execute first (sequence = 1)
  - `move_rule_to_bottom` - Move rule to execute last
  - `move_rule_up` - Move rule up one position in execution order
  - `move_rule_down` - Move rule down one position in execution order
- Enhanced `list_emails` to support direct folder ID lookup via new `folder_id` parameter
- Enhanced `list_files` to support `folder_id` parameter and `type_filter` for filtering files/folders
- Internal helper functions for code reuse:
  - `_list_mail_folders_impl()` - Email folder listing implementation
  - `_list_folders_impl()` - OneDrive folder listing implementation

### Changed

- `list_emails` now accepts optional `folder_id` parameter for direct folder access (takes precedence over `folder` name)
- `list_emails` `folder` parameter is now optional (defaults to "inbox" if neither `folder` nor `folder_id` provided)
- `list_files` now accepts `folder_id` parameter for direct folder access and `type_filter` to filter by files/folders/all
- `list_files` maintains backward compatibility with existing path-based calls

### Fixed

- Fixed "'FunctionTool' object is not callable" error in `get_mail_folder_tree` by extracting shared logic into internal helper function
- Fixed `AttributeError: 'FastMCP' object has no attribute 'get_asgi_app'` by using correct `http_app()` method for Streamable HTTP transport
- Fixed auth middleware to gracefully handle browser requests (favicon.ico, robots.txt) by returning 404 instead of 401
- Fixed auth middleware 500 errors by returning JSONResponse instead of raising HTTPException (proper handling of 401 unauthorized requests)

### Documentation

- Added `QUICKSTART.md` - Quick start guide for installation, configuration, and first-time setup
- Added `.env.example` - Template file with all configuration options and detailed comments
- Added `EMAIL_OUTPUT_FORMAT.md` - Comprehensive guide to email reading output format, metadata fields, and AI interaction examples
- Added `SECURITY.md` - Complete security guide covering transport modes, authentication methods, best practices, and incident response
- Added `HTTP_TRANSPORT_IMPLEMENTATION.md` - Complete implementation details for Streamable HTTP transport and security features
- Updated `README.md` with quick start section and transport mode configuration

### Dependencies

- Added `fastapi>=0.115.0` - Required for Streamable HTTP transport with bearer auth middleware
- Added `uvicorn>=0.32.0` - ASGI server for Streamable HTTP transport

### Notes

- Uses modern MCP Streamable HTTP protocol (spec 2025-03-26+) instead of deprecated SSE transport
- Streamable HTTP provides bidirectional communication over single endpoint at `/mcp`

## [0.1.0] - 2024-10-03

### Added 2024-10-03

- Initial release with Microsoft Graph API integration
- Email management tools (list, send, reply, delete, move, attachments)
- Calendar tools (events, availability, responses)
- OneDrive file tools (upload, download, browse, search)
- Contacts tools (list, search, create, update, delete)
- Multi-account support with device flow authentication
- Unified search across emails, events, and files
