# M365 MCP Server — Tool Reference

Authoritative reference for every tool the M365 MCP server exposes, as
implemented today.

| | |
|---|---|
| Server name (MCP) | `microsoft-mcp` |
| Package version | `m365-mcp` 0.2.3 |
| MCP runtime | FastMCP 2.13.3 on the `mcp` Python SDK 1.22.0 |
| Protocol versions negotiated | `2024-11-05`, `2025-03-26`, `2025-06-18` (newest offered: `2025-06-18`) |
| Tools exposed | **85** |
| Snapshot date | 2026-09-26 |

**Source of truth.** Sections 4–5 were generated from the server's live
`tools/list` response (names, titles, annotations, metadata, input schemas,
output schemas, descriptions), captured through an in-memory MCP client.
Cache lifetimes come from `cache_config.TTL_POLICIES`. The tool list is
deterministic: two separate processes produced byte-identical output, so
the order below is the order clients receive.

**Regenerating.** Run `uv run python scripts/generate_tools_doc.py` after
changing any tool. It rewrites sections 4–5 and leaves sections 1–3
untouched. Use `--check` in CI to fail when this file is out of date.
Hand-verified corrections live in the script's `ARG_OVERRIDES` and
`IMPLEMENTATION_NOTES`.

Parameter descriptions in section 5 come from each tool's docstring
*Args:* block. Paragraphs marked **Implementation note** were added by
hand, after checking the code and Microsoft's Graph documentation. They
correct or supplement a tool's own description where it differs from
actual behaviour (see section 2.8). The JSON input schema itself carries **no per-parameter
descriptions, enums, or numeric bounds**: constraints such as "1–200" are
enforced by server-side validation and appear only in the description text.

---

## 1. Connecting to the server

### 1.1 Transports

| `MCP_TRANSPORT` | Behaviour |
|---|---|
| `stdio` (default) | The host launches `uv run m365-mcp`; JSON-RPC runs over stdin/stdout. Logs go to stderr and `MCP_LOG_DIR`. |
| `http` | Streamable HTTP at `http://MCP_HOST:MCP_PORT` + `MCP_PATH` (default `http://127.0.0.1:8000/mcp`). SSE-only transport is not offered. |

HTTP authentication (`MCP_AUTH_METHOD`):

| Value | Behaviour |
|---|---|
| `bearer` | Every request needs `Authorization: Bearer <MCP_AUTH_TOKEN>`. A token shorter than 32 characters is accepted with a warning. `GET /health` is unauthenticated and returns `{"status":"ok","transport":"http","auth":"bearer"}`; `/favicon.ico` and `/robots.txt` return 404 without an auth check. |
| `none` (default) | Refused unless `MCP_ALLOW_INSECURE=true` is also set. |
| `oauth` | Present in configuration, but currently fails at startup: FastMCP's HTTP runner does not accept the `auth` argument the server passes. |

### 1.2 Microsoft sign-in

- Accounts are added interactively with `uv run authenticate.py` (device
  code flow), or with the `account_authenticate` / `account_complete_auth`
  tools.
- Tokens are stored in `~/.m365_mcp_token_cache.json`, a cross-process
  locked MSAL cache (`msal-extensions`). Account types are stored in
  `~/.m365_mcp_account_metadata.json`.
- During tool calls, access tokens refresh silently from the cached refresh
  token. The server never starts an interactive sign-in during a tool call
  unless `M365_MCP_INTERACTIVE_AUTH=true`.
- If an account's refresh token has expired or been revoked (for personal
  accounts, after 90 days unused), every tool call for that account fails
  with: *"Microsoft sign-in has expired or is missing for '<user>'.
  Microsoft reported: <reason>. Run `uv run authenticate.py` and sign in
  again …"*.
- `uv run authenticate.py` checks and refreshes every account, offers to
  sign in again for expired ones, and exits with code 1 if any account is
  still unusable. `--re-auth <account>` refreshes one account;
  `--remove <account>` deletes an account and its cached data.
- Graph permissions are requested as `https://graph.microsoft.com/.default`,
  meaning whatever delegated permissions the Azure app registration grants.

### 1.3 Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `M365_MCP_CLIENT_ID` | *(required)* | Azure app registration (public client) ID |
| `M365_MCP_TENANT_ID` | `common` | Authority tenant (`common`, `consumers`, `organizations` or a tenant ID) |
| `M365_MCP_INTERACTIVE_AUTH` | `false` | Allow `get_token` to start a device-code sign-in (set automatically by `authenticate.py`) |
| `M365_MCP_CACHE_KEY` | *(keyring)* | Cache encryption key, used when no system keyring is available |
| `M365_MCP_CACHE_WARMING` | `false` | Pre-populate the cache at startup and refresh stale entries in the background |
| `MCP_TRANSPORT` | `stdio` | `stdio` or `http` |
| `MCP_HOST` / `MCP_PORT` / `MCP_PATH` | `127.0.0.1` / `8000` / `/mcp` | HTTP bind address and endpoint path |
| `MCP_AUTH_METHOD` | `none` | `bearer`, `none` or `oauth` (see 1.1) |
| `MCP_AUTH_TOKEN` | — | Bearer token for `MCP_AUTH_METHOD=bearer` |
| `MCP_ALLOW_INSECURE` | — | Must be `true` to run HTTP without authentication |
| `MCP_FILE_ALLOWED_ROOTS` | — | Extra local directories (separated by `os.pathsep`: `;` on Windows, `:` elsewhere) that file tools may read from or write to |
| `MCP_FILE_DOWNLOAD_MAX_MB` | `512` | Maximum size of a OneDrive download |
| `MCP_FILE_DOWNLOAD_TIMEOUT` | `60.0` | Download timeout in seconds |
| `MCP_FILE_DOWNLOAD_CHUNK_SIZE` | `1048576` | Download streaming chunk size in bytes |
| `MCP_LOG_LEVEL` / `MCP_LOG_DIR` | `INFO` / `logs` | Logging level and directory |

---

## 2. Conventions that apply to every tool

### 2.1 `account_id`

- Every Microsoft 365 tool takes a required `account_id`. Get valid values
  from `account_list` (the `account_id` field, an MSAL home account ID such
  as `00000000-0000-0000-xxxx-xxxxxxxxxxxx.9188040d-6c67-4c5b-b112-36a304b66dad`).
- Token lookup also accepts the account's username (email address),
  case-insensitively. Cache entries are keyed by the literal `account_id`
  string, so mixing the ID and the email for one account keeps separate
  cache entries.
- The position of `account_id` in the parameter list varies by tool, because
  historical signatures are preserved. Always pass arguments by name.
- Server-side validation checks only that `account_id` is a non-empty
  string. An unknown account fails at token lookup with the sign-in message
  in 1.2.

### 2.2 Safety levels, annotations and confirmation

Each tool carries MCP annotations (`title`, `readOnlyHint`,
`destructiveHint`, `idempotentHint`, `openWorldHint`) and metadata
`{category, safety_level}`. Descriptions begin with an emoji that matches
the level.

| Level | Emoji | Count | Meaning in this server |
|---|---|---|---|
| `safe` | 📖 | 31 | Read-only (`readOnlyHint=true`) |
| `moderate` | ✏️ | 40 | Creates or modifies data, or writes local files; no `confirm` parameter |
| `dangerous` | 📧 | 5 | Sends mail or invitations on the user's behalf: `email_send`, `email_reply`, `email_reply_all`, `email_forward`, `calendar_forward_event` |
| `critical` | 🔴 | 9 | Deletes data (`destructiveHint=true`): `email_delete`, `emailfolders_delete`, `emailfolders_empty`, `emailrules_delete`, `calendar_delete_event`, `calendar_delete_calendar`, `contact_delete`, `file_delete`, `folder_delete` |

- The 14 `dangerous` and `critical` tools have a `confirm` parameter
  (default `false`) and **refuse to act** unless `confirm=true`. The refusal
  is a tool error such as: *"Invalid confirm 'False': delete email on
  resource requires confirm=True to proceed. Expected: Explicit user
  confirmation"*.
- `confirm` is supplied by the calling model. It guards against accidental
  calls, but it does not prove a human approved the action; that depends
  on the host's tool-approval settings.
- Some `moderate` tools also have external effects without a `confirm`
  gate:
  - `calendar_create_event` / `calendar_update_event` with attendees send
    invitations or updates;
  - `calendar_respond_event` and `calendar_propose_new_time` send responses;
  - `file_share` creates sharing links (default scope `anonymous`);
  - `emailrules_create` / `emailrules_update` can add forwarding or
    redirect actions.

### 2.3 Caching parameters

15 read tools accept `use_cache` (default `true`) and `force_refresh`
(default `false`). Results are stored in the encrypted local SQLite cache
(SQLCipher, AES-256), scoped to the account:

| State | Behaviour |
|---|---|
| Fresh | Returned from cache with no Graph call |
| Stale | Returned from cache (with background refresh when warming is enabled) |
| Expired | Fetched from Graph and re-cached |

| Tool | Fresh | Stale until |
|---|---|---|
| `email_list` | 2 min | 10 min |
| `email_get` | 15 min | 60 min |
| `calendar_list_events` | 5 min | 30 min |
| `calendar_get_event` | 10 min | 60 min |
| `contact_list` | 20 min | 120 min |
| `contact_get` | 30 min | 240 min |
| `file_list` | 10 min | 60 min |
| `folder_list` | 15 min | 60 min |
| `folder_get_tree` | 30 min | 120 min |
| `search_emails`, `search_files` | 1 min | 5 min |
| `calendar_list_calendars`, `search_events`, `search_contacts`, `search_unified` | 5 min (default policy) | 15 min |

- Write tools invalidate the related cache entries for that account only.
- Cached results carry `_cache_status` (`"fresh"`, `"stale"` or `"miss"`)
  and `_cached_at` (ISO timestamp); list tools add them to each item.
- The cache is capped at 2 GB, with cleanup starting at 80%, and entries of
  50 KB or more are gzip-compressed.
- The `cache_*` tools (section 5.10) inspect and control the cache.

### 2.4 Results

- Tools return the Microsoft Graph data they fetched, largely unprojected.
  Items include Graph fields such as `id` and `@odata.etag`, and nested
  objects such as `from.emailAddress`.
- Every tool declares an `outputSchema`.
  - Tools returning a list wrap it as `structuredContent.result`.
  - Tools returning an object use it directly as `structuredContent`.
  - The schemas do not declare individual fields.
- The same result is also returned as JSON in a text content block.
- Mail bodies are requested as plain text (`Prefer:
  outlook.body-content-type="text"`) on every page of a paginated request.
  `email_get` truncates bodies at 50,000 characters by default. `email_list`
  includes full bodies unless `include_body=false`.
- List tools take a `limit` and return up to that many items. They follow
  Graph `@odata.nextLink` internally, and do not return a continuation
  cursor.

### 2.5 Errors

Failures are returned as MCP tool errors (`isError: true`) with the text
`Error calling tool '<name>': <message>`. Message forms:

| Source | Example message |
|---|---|
| Input validation | `Invalid limit '500': must be between 1 and 200. Expected: 1-200` |
| Missing confirmation | `Invalid confirm 'False': … requires confirm=True to proceed. Expected: Explicit user confirmation` |
| Sign-in required | `Microsoft sign-in has expired or is missing for '<user>'. …` |
| Token service outage | `Microsoft token refresh failed: <error> - <description>. This is usually temporary; retry shortly.` |
| Graph HTTP error | `Client error '404 Not Found' for url 'https://graph.microsoft.com/v1.0/…'` (Graph's own error code and message are not included) |

### 2.6 Graph request behaviour

- A fresh token is obtained for each attempt. A `401` triggers one forced
  token refresh and a retry.
- `429` and `503` are retried up to 3 times for any method, honouring
  `Retry-After` (seconds or HTTP date), capped at 60 s per wait.
- Other `5xx` responses, timeouts and dropped connections are retried only
  for idempotent methods (`GET`, `PUT`, `DELETE`, `HEAD`, `OPTIONS`).
  Sends and other `POST`s are never replayed after an ambiguous failure.
  Connection failures are retried for any method.
- Other backoff waits are exponential (1 s, 2 s, 4 s). Per-request timeout
  is 30 s.
- Uploads larger than 4.8 MB (15 × 320 KiB) use Graph upload sessions.
  Chunks go to the pre-authenticated upload URL without an `Authorization`
  header.

### 2.7 Local files, folders and formats

- **Local paths.** Tools that read or write local files only accept paths
  inside the allowed roots listed below. Those tools are:
  - `file_create` and `file_update` (upload a local file);
  - `file_get` (`download_path`);
  - `email_send` and `email_create_draft` (`attachments`: at most 10 files,
    25 MB each);
  - `email_get_attachment` (save path).

  The allowed roots are:
  - the server's working directory;
  - the system temp directory;
  - any directory in `MCP_FILE_ALLOWED_ROOTS`.
- **Mail folder names.** `folder` parameters accept these case-insensitive
  aliases, or a Graph folder ID via `folder_id`:

  | Alias | Graph folder |
  |---|---|
  | `inbox` | `inbox` |
  | `sent` | `sentitems` |
  | `drafts` | `drafts` |
  | `deleted` | `deleteditems` |
  | `junk` | `junkemail` |
  | `archive` | `archive` |

- **Mail attachments.** Up to 25 MB each, for sending and for downloading.
  Outbound attachments of 3 MB or more are uploaded through an upload
  session after the draft is created.
- **Datetimes.** Calendar datetimes are ISO 8601. Validated windows require
  timezone-aware values and a start before the end; see each tool's
  parameters.
- **Two kinds of folder tool.** `folder_*` tools operate on **OneDrive**
  folders; `emailfolders_*` tools operate on **Outlook mail** folders.

### 2.8 What the delete tools actually do

Several tool descriptions say "permanently deletes". Every delete tool
issues a plain Graph `DELETE`; none uses Graph's separate `permanentDelete`
action. Documented Graph behaviour:

| Tool | Graph call | Documented effect |
|---|---|---|
| `file_delete`, `folder_delete` | `DELETE /me/drive/items/{id}` | Moved to the OneDrive **recycle bin**, not permanently deleted ([driveitem-delete](https://learn.microsoft.com/en-us/graph/api/driveitem-delete?view=graph-rest-1.0)) |
| `calendar_delete_event` | `DELETE /me/events/{id}` | Removed from the calendar. If you are the organizer of a meeting, **a cancellation is sent to all attendees** ([event-delete](https://learn.microsoft.com/en-us/graph/api/event-delete?view=graph-rest-1.0)) |
| `email_delete`, `emailfolders_empty` (per message) | `DELETE /me/messages/{id}` | Deleted from the mailbox; the Graph page does not describe it as permanent ([message-delete](https://learn.microsoft.com/en-us/graph/api/message-delete?view=graph-rest-1.0)) |
| `emailfolders_delete`, `emailrules_delete`, `calendar_delete_calendar`, `contact_delete` | `DELETE` on the resource | Deleted as described by Graph for each resource |

---

## 3. Tools by category

| Category | Prefix | Tools |
|---|---|---|
| Accounts | `account_` | 3 |
| Email | `email_` | 15 |
| Mail folders | `emailfolders_` | 9 |
| Mail rules | `emailrules_` | 9 |
| Calendar | `calendar_` | 13 |
| Contacts | `contact_` | 8 |
| OneDrive files | `file_` | 10 |
| OneDrive folders | `folder_` | 7 |
| Search | `search_` | 5 |
| Cache administration | `cache_` | 5 |
| Server | `server_` | 1 |
| **Total** | | **85** |

---

## 4. Tool index

Legend: **RO** = `readOnlyHint`, **Destr.** = `destructiveHint`, **Idem.** = `idempotentHint`, **Confirm** = tool refuses to run unless `confirm=true`, **Cache** = supports `use_cache`/`force_refresh`.

| # | Tool | Title | Safety | RO | Destr. | Idem. | Confirm | Cache |
|---|---|---|---|---|---|---|---|---|
| 1 | [`account_list`](#account_list) | List Accounts | safe | yes | no | yes | no | no |
| 2 | [`account_authenticate`](#account_authenticate) | Authenticate Account | moderate | no | no | no | no | no |
| 3 | [`account_complete_auth`](#account_complete_auth) | Complete Authentication | moderate | no | no | no | no | no |
| 4 | [`email_list`](#email_list) | List Emails | safe | yes | no | yes | no | yes |
| 5 | [`email_get`](#email_get) | Get Email | safe | yes | no | yes | no | yes |
| 6 | [`email_create_draft`](#email_create_draft) | Create Email Draft | moderate | no | no | no | no | no |
| 7 | [`email_send`](#email_send) | Send Email | dangerous | no | no | no | yes | no |
| 8 | [`email_update`](#email_update) | Update Email Properties | moderate | no | no | yes | no | no |
| 9 | [`email_delete`](#email_delete) | Delete Email | critical | no | yes | yes | yes | no |
| 10 | [`email_move`](#email_move) | Move Email | moderate | no | no | yes | no | no |
| 11 | [`email_reply`](#email_reply) | Reply to Email | dangerous | no | no | no | yes | no |
| 12 | [`email_reply_all`](#email_reply_all) | Reply All to Email | dangerous | no | no | no | yes | no |
| 13 | [`email_forward`](#email_forward) | Forward Email | dangerous | no | no | no | yes | no |
| 14 | [`email_get_attachment`](#email_get_attachment) | Get Email Attachment | moderate | no | no | yes | no | no |
| 15 | [`email_mark_read`](#email_mark_read) | Mark Email Read/Unread | moderate | no | no | yes | no | no |
| 16 | [`email_flag`](#email_flag) | Flag Email | moderate | no | no | yes | no | no |
| 17 | [`email_add_category`](#email_add_category) | Add Email Category | moderate | no | no | no | no | no |
| 18 | [`email_archive`](#email_archive) | Archive Email | moderate | no | no | yes | no | no |
| 19 | [`emailfolders_list`](#emailfolders_list) | List Email Folders | safe | yes | no | yes | no | no |
| 20 | [`emailfolders_get`](#emailfolders_get) | Get Email Folder | safe | yes | no | yes | no | no |
| 21 | [`emailfolders_get_tree`](#emailfolders_get_tree) | Get Email Folder Tree | safe | yes | no | yes | no | no |
| 22 | [`emailfolders_create`](#emailfolders_create) | Create Email Folder | moderate | no | no | no | no | no |
| 23 | [`emailfolders_rename`](#emailfolders_rename) | Rename Email Folder | moderate | no | no | yes | no | no |
| 24 | [`emailfolders_move`](#emailfolders_move) | Move Email Folder | moderate | no | no | yes | no | no |
| 25 | [`emailfolders_delete`](#emailfolders_delete) | Delete Email Folder | critical | no | yes | no | yes | no |
| 26 | [`emailfolders_mark_all_as_read`](#emailfolders_mark_all_as_read) | Mark All Emails in Folder as Read | moderate | no | no | yes | no | no |
| 27 | [`emailfolders_empty`](#emailfolders_empty) | Empty Email Folder | critical | no | yes | no | yes | no |
| 28 | [`emailrules_list`](#emailrules_list) | List Email Rules | safe | yes | no | yes | no | no |
| 29 | [`emailrules_get`](#emailrules_get) | Get Email Rule | safe | yes | no | yes | no | no |
| 30 | [`emailrules_create`](#emailrules_create) | Create Email Rule | moderate | no | no | no | no | no |
| 31 | [`emailrules_update`](#emailrules_update) | Update Email Rule | moderate | no | no | yes | no | no |
| 32 | [`emailrules_delete`](#emailrules_delete) | Delete Email Rule | critical | no | yes | yes | yes | no |
| 33 | [`emailrules_move_top`](#emailrules_move_top) | Move Email Rule to Top | moderate | no | no | no | no | no |
| 34 | [`emailrules_move_bottom`](#emailrules_move_bottom) | Move Email Rule to Bottom | moderate | no | no | no | no | no |
| 35 | [`emailrules_move_up`](#emailrules_move_up) | Move Email Rule Up | moderate | no | no | no | no | no |
| 36 | [`emailrules_move_down`](#emailrules_move_down) | Move Email Rule Down | moderate | no | no | no | no | no |
| 37 | [`calendar_list_events`](#calendar_list_events) | List Calendar Events | safe | yes | no | yes | no | yes |
| 38 | [`calendar_get_event`](#calendar_get_event) | Get Calendar Event | safe | yes | no | yes | no | yes |
| 39 | [`calendar_create_event`](#calendar_create_event) | Create Calendar Event | moderate | no | no | no | no | no |
| 40 | [`calendar_update_event`](#calendar_update_event) | Update Calendar Event | moderate | no | no | yes | no | no |
| 41 | [`calendar_delete_event`](#calendar_delete_event) | Delete Calendar Event | critical | no | yes | yes | yes | no |
| 42 | [`calendar_respond_event`](#calendar_respond_event) | Respond to Calendar Event | moderate | no | no | yes | no | no |
| 43 | [`calendar_check_availability`](#calendar_check_availability) | Check Calendar Availability | safe | yes | no | yes | no | no |
| 44 | [`calendar_forward_event`](#calendar_forward_event) | Forward Calendar Event | dangerous | no | no | no | yes | no |
| 45 | [`calendar_list_calendars`](#calendar_list_calendars) | List Calendars | safe | yes | no | yes | no | yes |
| 46 | [`calendar_create_calendar`](#calendar_create_calendar) | Create Calendar | moderate | no | no | no | no | no |
| 47 | [`calendar_delete_calendar`](#calendar_delete_calendar) | Delete Calendar | critical | no | yes | yes | yes | no |
| 48 | [`calendar_propose_new_time`](#calendar_propose_new_time) | Propose New Meeting Time | moderate | no | no | no | no | no |
| 49 | [`calendar_get_free_busy`](#calendar_get_free_busy) | Get Free/Busy Times | safe | yes | no | yes | no | no |
| 50 | [`contact_list`](#contact_list) | List Contacts | safe | yes | no | yes | no | yes |
| 51 | [`contact_get`](#contact_get) | Get Contact | safe | yes | no | yes | no | yes |
| 52 | [`contact_create`](#contact_create) | Create Contact | moderate | no | no | no | no | no |
| 53 | [`contact_update`](#contact_update) | Update Contact | moderate | no | no | yes | no | no |
| 54 | [`contact_delete`](#contact_delete) | Delete Contact | critical | no | yes | yes | yes | no |
| 55 | [`contact_create_list`](#contact_create_list) | Create Contact List | moderate | no | no | no | no | no |
| 56 | [`contact_add_to_list`](#contact_add_to_list) | Add Contact to List | moderate | no | no | no | no | no |
| 57 | [`contact_export`](#contact_export) | Export Contact | safe | yes | no | yes | no | no |
| 58 | [`file_list`](#file_list) | List Files | safe | yes | no | yes | no | yes |
| 59 | [`file_get`](#file_get) | Get File | moderate | no | no | yes | no | no |
| 60 | [`file_create`](#file_create) | Create File | moderate | no | no | no | no | no |
| 61 | [`file_update`](#file_update) | Update File | moderate | no | no | yes | no | no |
| 62 | [`file_delete`](#file_delete) | Delete File | critical | no | yes | yes | yes | no |
| 63 | [`file_copy`](#file_copy) | Copy File | moderate | no | no | no | no | no |
| 64 | [`file_move`](#file_move) | Move File | moderate | no | no | no | no | no |
| 65 | [`file_rename`](#file_rename) | Rename File | moderate | no | no | no | no | no |
| 66 | [`file_share`](#file_share) | Share File | moderate | no | no | no | no | no |
| 67 | [`file_download_url`](#file_download_url) | Get File Download URL | safe | yes | no | yes | no | no |
| 68 | [`folder_list`](#folder_list) | List Folders | safe | yes | no | yes | no | yes |
| 69 | [`folder_get`](#folder_get) | Get Folder | safe | yes | no | yes | no | no |
| 70 | [`folder_get_tree`](#folder_get_tree) | Get Folder Tree | safe | yes | no | yes | no | yes |
| 71 | [`folder_create`](#folder_create) | Create OneDrive Folder | moderate | no | no | no | no | no |
| 72 | [`folder_delete`](#folder_delete) | Delete OneDrive Folder | critical | no | yes | no | yes | no |
| 73 | [`folder_rename`](#folder_rename) | Rename OneDrive Folder | moderate | no | no | no | no | no |
| 74 | [`folder_move`](#folder_move) | Move OneDrive Folder | moderate | no | no | no | no | no |
| 75 | [`search_files`](#search_files) | Search Files | safe | yes | no | yes | no | yes |
| 76 | [`search_emails`](#search_emails) | Search Emails | safe | yes | no | yes | no | yes |
| 77 | [`search_events`](#search_events) | Search Events | safe | yes | no | yes | no | yes |
| 78 | [`search_contacts`](#search_contacts) | Search Contacts | safe | yes | no | yes | no | yes |
| 79 | [`search_unified`](#search_unified) | Unified Search | safe | yes | no | yes | no | yes |
| 80 | [`cache_task_get_status`](#cache_task_get_status) | Get Cache Task Status | safe | yes | no | yes | no | no |
| 81 | [`cache_task_list`](#cache_task_list) | List Cache Tasks | safe | yes | no | yes | no | no |
| 82 | [`cache_get_stats`](#cache_get_stats) | Get Cache Statistics | safe | yes | no | yes | no | no |
| 83 | [`cache_invalidate`](#cache_invalidate) | Invalidate Cache Entries | moderate | no | no | yes | no | no |
| 84 | [`cache_warming_status`](#cache_warming_status) | Get Cache Warming Status | safe | yes | no | yes | no | no |
| 85 | [`server_get_version`](#server_get_version) | Get Server Version | safe | yes | no | yes | no | no |

## 5. Tool reference

### 5.1 Accounts (3 tools)

Discover signed-in Microsoft accounts and add new ones.

<a id="account_list"></a>

#### `account_list`

📖 List all signed-in Microsoft accounts (read-only, safe for unsupervised use)

**Title:** List Accounts  
**Safety level:** `safe`  
**Category:** `account`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Returns a list of authenticated Microsoft accounts with their usernames, account IDs,
and account types (personal or work/school).

_No parameters._

**Output:** `structuredContent.result`: `array<object<string, string>>` (the tool's return value, wrapped under `result`).

**Returns (as documented):**

```text
List of account dictionaries with:
- username: Account email/username
- account_id: Unique account identifier
- account_type: "personal", "work_school", or "unknown"
```

**Example:**

```text
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
```

---

<a id="account_authenticate"></a>

#### `account_authenticate`

✏️ Authenticate a new Microsoft account using device flow (requires user confirmation recommended)

**Title:** Authenticate Account  
**Safety level:** `moderate`  
**Category:** `account`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Initiates device flow authentication for adding a new Microsoft account.
Returns authentication instructions with a device code and verification URL.

The user must:
1. Visit the verification URL
2. Enter the device code
3. Sign in with their Microsoft account
4. Use account_complete_auth to finish the process

_No parameters._

**Output:** `structuredContent`: `object<string, string>` (no declared fields).

---

<a id="account_complete_auth"></a>

#### `account_complete_auth`

✏️ Complete device flow authentication (requires user confirmation recommended)

**Title:** Complete Authentication  
**Safety level:** `moderate`  
**Category:** `account`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Completes the authentication process after the user has entered the device code
at the verification URL.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `flow_cache` | `string` | yes | — | The flow data returned from account_authenticate (the _flow_cache field) |

**Output:** `structuredContent`: `object<string, string>` (no declared fields).

**Returns (as documented):**

```text
Account information if authentication was successful, or pending status if
the user hasn't completed authentication yet.
```

---

### 5.2 Email (15 tools)

Read, compose, send, organise and delete mail messages.

<a id="email_list"></a>

#### `email_list`

📖 List emails from a mailbox folder (read-only, safe for unsupervised use)

**Title:** List Emails  
**Safety level:** `safe`  
**Category:** `email`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no  
**Cache:** fresh 2 min, stale-while-refresh until 10 min

Returns recent emails with subject, sender, date, size, and attachment info.

Caching: Results are cached for 2 minutes (fresh) / 10 minutes (stale).
Use force_refresh=True to bypass cache and fetch fresh data.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `account_id` | `string` | yes | — | Microsoft account ID |
| `folder` | `string \| null` | no | `null` | Folder name (inbox, sent, drafts, deleted, junk, archive) |
| `folder_id` | `string \| null` | no | `null` | Direct folder ID - takes precedence over folder name |
| `limit` | `integer` | no | `10` | Maximum emails to return (1-200, default: 10) |
| `include_body` | `boolean` | no | `true` | Whether to include email body content (default: True) |
| `use_cache` | `boolean` | no | `true` | Whether to use cached data if available (default: True) |
| `force_refresh` | `boolean` | no | `false` | Force refresh from API, bypassing cache (default: False) |

**Output:** `structuredContent.result`: `array<object>` (the tool's return value, wrapped under `result`).

**Returns (as documented):**

```text
List of email messages with metadata and optionally body content.
Each message includes _cache_status and _cached_at fields.
```

---

<a id="email_get"></a>

#### `email_get`

📖 Get detailed information about a specific email (read-only, safe for unsupervised use)

**Title:** Get Email  
**Safety level:** `safe`  
**Category:** `email`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no  
**Cache:** fresh 15 min, stale-while-refresh until 60 min

Includes full headers, body content, and attachment metadata.
Body content is truncated at 50,000 characters by default.

Caching: Results are cached for 15 minutes (fresh) / 1 hour (stale).
Use force_refresh=True to bypass cache and fetch fresh data.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `email_id` | `string` | yes | — | The email ID |
| `account_id` | `string` | yes | — | The account ID |
| `include_body` | `boolean` | no | `true` | Whether to include the email body (default: True) |
| `body_max_length` | `integer` | no | `50000` | Maximum characters for body content (1-500000, default: 50000) |
| `include_attachments` | `boolean` | no | `true` | Whether to include attachment metadata (default: True) |
| `use_cache` | `boolean` | no | `true` | Whether to use cached data if available (default: True) |
| `force_refresh` | `boolean` | no | `false` | Force refresh from API, bypassing cache (default: False) |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Email details with:
- _cache_status: Cache state (fresh/stale/miss)
- _cached_at: When data was cached (ISO format)
```

---

<a id="email_create_draft"></a>

#### `email_create_draft`

✏️ Create an email draft (requires user confirmation recommended)

**Title:** Create Email Draft  
**Safety level:** `moderate`  
**Category:** `email`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Creates a draft email message that can be edited later before sending.
Supports attachments from local file paths.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `account_id` | `string` | yes | — | Microsoft account ID |
| `to` | `string \| array<string>` | yes | — | Recipient email address(es) |
| `subject` | `string` | yes | — | Email subject |
| `body` | `string` | yes | — | Email body (plain text) |
| `cc` | `string \| array<string> \| null` | no | `null` | CC recipient email address(es) (optional) |
| `attachments` | `string \| array<string> \| null` | no | `null` | Local file path(s) for attachments (optional) |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Created draft message with ID
```

---

<a id="email_send"></a>

#### `email_send`

📧 Send an email to recipients (always require user confirmation)

**Title:** Send Email  
**Safety level:** `dangerous`  
**Category:** `email`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Requires `confirm=true`:** yes

WARNING: Email will be sent immediately upon execution.
This action cannot be undone.

Supports multiple recipients, CC, attachments, and HTML formatting.
Addresses are validated, deduplicated across To/CC, and limited to
500 unique recipients in total.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `account_id` | `string` | yes | — | Microsoft account ID |
| `to` | `string \| array<string>` | yes | — | Recipient email address(es) |
| `subject` | `string` | yes | — | Email subject |
| `body` | `string` | yes | — | Email body (plain text) |
| `cc` | `string \| array<string> \| null` | no | `null` | CC recipient email address(es) (optional) |
| `attachments` | `string \| array<string> \| null` | no | `null` | Local file path(s) for attachments (optional) |
| `confirm` | `boolean` | no | `false` | Must be True to confirm sending (prevents accidents) |

**Output:** `structuredContent`: `object<string, string>` (no declared fields).

**Returns (as documented):**

```text
Status confirmation
```

**Raises:**

```text
ValidationError: If recipients are invalid, exceed limits,
    or confirm is False.
```

---

<a id="email_update"></a>

#### `email_update`

✏️ Update email properties (requires user confirmation recommended)

**Title:** Update Email Properties  
**Safety level:** `moderate`  
**Category:** `email`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Modifies properties like isRead status, categories, and flags without
changing email content.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `email_id` | `string` | yes | — | The email ID to update |
| `updates` | `object` | yes | — | Dictionary of properties to update |
| `account_id` | `string` | yes | — | Microsoft account ID |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Updated email object
```

**Examples:**

```text
    email_update(email_id, {"isRead": True}, account_id)
    email_update(email_id, {"categories": ["Important"]}, account_id)

Allowed update keys: isRead, categories, importance, flag, inferenceClassification.
```

---

<a id="email_delete"></a>

#### `email_delete`

🔴 Delete an email permanently (always require user confirmation)

**Title:** Delete Email  
**Safety level:** `critical`  
**Category:** `email`  
**Hints:** readOnlyHint=`false`, destructiveHint=`true`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** yes

WARNING: This action permanently deletes the email and cannot be undone.

For safety, consider moving items to the deleted items folder first using email_move.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `email_id` | `string` | yes | — | The email to delete |
| `account_id` | `string` | yes | — | The account ID |
| `confirm` | `boolean` | no | `false` | Must be True to confirm deletion (prevents accidents) |

**Output:** `structuredContent`: `object<string, string>` (no declared fields).

**Returns (as documented):**

```text
Status confirmation
```

---

<a id="email_move"></a>

#### `email_move`

✏️ Move an email to a different folder (requires user confirmation recommended)

**Title:** Move Email  
**Safety level:** `moderate`  
**Category:** `email`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Moves the email to the specified folder without deleting it from the source.

Valid folder names: inbox, sent, drafts, deleted, junk, archive.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `email_id` | `string` | yes | — | The email ID to move |
| `destination_folder` | `string` | yes | — | Folder name to move to |
| `account_id` | `string` | yes | — | Microsoft account ID |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Status confirmation with new email ID
```

---

<a id="email_reply"></a>

#### `email_reply`

📧 Reply to an email (always require user confirmation)

**Title:** Reply to Email  
**Safety level:** `dangerous`  
**Category:** `email`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Requires `confirm=true`:** yes

WARNING: Reply will be sent immediately to the original sender.
This action cannot be undone.

Body content is stripped of surrounding whitespace and must not be
empty before sending.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `account_id` | `string` | yes | — | Microsoft account ID |
| `email_id` | `string` | yes | — | The email ID to reply to |
| `body` | `string` | yes | — | Reply message body (plain text) |
| `confirm` | `boolean` | no | `false` | Must be True to confirm sending (prevents accidents) |

**Output:** `structuredContent`: `object<string, string>` (no declared fields).

**Returns (as documented):**

```text
Status confirmation
```

**Raises:**

```text
ValidationError: If the reply body is empty/whitespace or confirm
    is False.
```

---

<a id="email_reply_all"></a>

#### `email_reply_all`

📧 Reply to all recipients of an email (always require user confirmation)

**Title:** Reply All to Email  
**Safety level:** `dangerous`  
**Category:** `email`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Requires `confirm=true`:** yes

WARNING: Reply will be sent immediately to ALL recipients (original sender,
To, and Cc recipients). This action cannot be undone.

Body content is stripped of surrounding whitespace and must not be
empty before sending.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `account_id` | `string` | yes | — | Microsoft account ID |
| `email_id` | `string` | yes | — | The email ID to reply to |
| `body` | `string` | yes | — | Reply message body (plain text) |
| `confirm` | `boolean` | no | `false` | Must be True to confirm sending (prevents accidents) |

**Output:** `structuredContent`: `object<string, string>` (no declared fields).

**Returns (as documented):**

```text
Status confirmation
```

**Raises:**

```text
ValidationError: If the reply body is empty/whitespace or confirm
    is False.
```

---

<a id="email_forward"></a>

#### `email_forward`

📧 Forward an email to recipients (always require user confirmation)

**Title:** Forward Email  
**Safety level:** `dangerous`  
**Category:** `email`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Requires `confirm=true`:** yes

WARNING: Email will be forwarded immediately to specified recipients.
This action cannot be undone.

Addresses are validated, deduplicated across To/CC, and limited to
500 unique recipients in total.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `account_id` | `string` | yes | — | Microsoft account ID |
| `email_id` | `string` | yes | — | The email ID to forward |
| `to` | `string \| array<string>` | yes | — | Recipient email address(es) |
| `cc` | `string \| array<string> \| null` | no | `null` | CC recipient email address(es) (optional) |
| `body` | `string \| null` | no | `null` | Optional comment/message to include with forward (plain text) |
| `confirm` | `boolean` | no | `false` | Must be True to confirm sending (prevents accidents) |

**Output:** `structuredContent`: `object<string, string>` (no declared fields).

**Returns (as documented):**

```text
Status confirmation
```

**Raises:**

```text
ValidationError: If recipients are invalid, exceed limits,
    or confirm is False.
```

---

<a id="email_get_attachment"></a>

#### `email_get_attachment`

Download an email attachment to a validated local path.

**Title:** Get Email Attachment  
**Safety level:** `moderate`  
**Category:** `email`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `email_id` | `string` | yes | — | Microsoft Graph message identifier containing the attachment. |
| `attachment_id` | `string` | yes | — | Target attachment identifier within the message. |
| `save_path` | `string` | yes | — | Destination path for the attachment. Validated via `ensure_safe_path`; existing files are never overwritten. |
| `account_id` | `string` | yes | — | Microsoft account identifier. |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Attachment metadata, including saved path and content size.
```

---

<a id="email_mark_read"></a>

#### `email_mark_read`

✏️ Mark an email as read or unread (requires user confirmation recommended)

**Title:** Mark Email Read/Unread  
**Safety level:** `moderate`  
**Category:** `email`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Simpler alternative to email_update for marking emails as read/unread.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `email_id` | `string` | yes | — | The email ID to update |
| `account_id` | `string` | yes | — | Microsoft account ID |
| `is_read` | `boolean` | no | `true` | Whether to mark as read (True) or unread (False) (default: True) |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Updated email object
```

**Raises:**

```text
ValueError: If email_id is invalid
ValidationError: If is_read is not a boolean
```

---

<a id="email_flag"></a>

#### `email_flag`

✏️ Flag or unflag an email (requires user confirmation recommended)

**Title:** Flag Email  
**Safety level:** `moderate`  
**Category:** `email`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Simpler alternative to email_update for flagging emails.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `email_id` | `string` | yes | — | The email ID to update |
| `account_id` | `string` | yes | — | Microsoft account ID |
| `flag_status` | `string` | no | `"flagged"` | Flag status - "notFlagged", "flagged", or "complete" (default: "flagged") |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Updated email object
```

**Raises:**

```text
ValueError: If email_id is invalid or flag_status is unsupported
```

---

<a id="email_add_category"></a>

#### `email_add_category`

✏️ Add categories to an email (requires user confirmation recommended)

**Title:** Add Email Category  
**Safety level:** `moderate`  
**Category:** `email`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Simpler alternative to email_update for managing email categories.
This replaces all existing categories with the specified ones.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `email_id` | `string` | yes | — | The email ID to update |
| `account_id` | `string` | yes | — | Microsoft account ID |
| `categories` | `string \| array<string>` | yes | — | Category name(s) to apply (single string or list) |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Updated email object
```

**Raises:**

```text
ValueError: If email_id is invalid
ValidationError: If categories is empty or contains invalid values
```

---

<a id="email_archive"></a>

#### `email_archive`

✏️ Archive an email (requires user confirmation recommended)

**Title:** Archive Email  
**Safety level:** `moderate`  
**Category:** `email`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Quick action to move an email to the Archive folder. This is a convenience
wrapper around email_move that specifically targets the archive folder.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `email_id` | `string` | yes | — | The email ID to archive |
| `account_id` | `string` | yes | — | Microsoft account ID |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Status confirmation with new email ID
```

**Raises:**

```text
ValueError: If email_id is invalid or archive folder not found
```

---

### 5.3 Mail folders (9 tools)

Manage Outlook mail folders (not OneDrive folders).

<a id="emailfolders_list"></a>

#### `emailfolders_list`

📖 List mail folders from mailbox (read-only, safe for unsupervised use)

**Title:** List Email Folders  
**Safety level:** `safe`  
**Category:** `emailfolders`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Returns root folders or child folders of a specific parent with metadata
including unread counts and child folder information.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `account_id` | `string` | yes | — | Microsoft account ID |
| `parent_folder_id` | `string \| null` | no | `null` | If None, lists root folders. If provided, lists child folders. |
| `include_hidden` | `boolean` | no | `false` | Whether to include hidden folders (default: False) |
| `limit` | `integer` | no | `100` | Maximum number of folders to return (1-250, default: 100) |

**Output:** `structuredContent.result`: `array<object>` (the tool's return value, wrapped under `result`).

**Returns (as documented):**

```text
List of folder objects with: id, displayName, childFolderCount,
unreadItemCount, totalItemCount, parentFolderId, isHidden
```

---

<a id="emailfolders_get"></a>

#### `emailfolders_get`

📖 Get detailed information about a specific mail folder (read-only, safe for unsupervised use)

**Title:** Get Email Folder  
**Safety level:** `safe`  
**Category:** `emailfolders`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Returns complete folder metadata including counts and hierarchy information.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `folder_id` | `string` | yes | — | The folder ID to retrieve |
| `account_id` | `string` | yes | — | Microsoft account ID |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Folder object with full metadata including id, displayName,
childFolderCount, unreadItemCount, totalItemCount
```

---

<a id="emailfolders_get_tree"></a>

#### `emailfolders_get_tree`

📖 Recursively build a tree of mail folders (read-only, safe for unsupervised use)

**Title:** Get Email Folder Tree  
**Safety level:** `safe`  
**Category:** `emailfolders`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Returns a hierarchical tree structure showing all folders and their nested children.
Useful for understanding mailbox folder organization.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `account_id` | `string` | yes | — | Microsoft account ID |
| `parent_folder_id` | `string \| null` | no | `null` | Root folder to start from (None = root) |
| `max_depth` | `integer` | no | `10` | Maximum recursion depth to prevent infinite loops (1-25, default: 10) |
| `include_hidden` | `boolean` | no | `false` | Whether to include hidden folders (default: False) |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Nested tree structure with folders and their children
```

---

<a id="emailfolders_create"></a>

#### `emailfolders_create`

✏️ Create a new mail folder (requires user confirmation recommended)

**Title:** Create Email Folder  
**Safety level:** `moderate`  
**Category:** `emailfolders`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Creates a new mail folder in the mailbox, either at the root level or
as a child of an existing folder.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `display_name` | `string` | yes | — | Name for the new folder |
| `account_id` | `string` | yes | — | Microsoft account ID |
| `parent_folder_id` | `string \| null` | no | `null` | Parent folder ID (None = root level) |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Created folder object with id, displayName, and other metadata
```

**Raises:**

```text
ValueError: If display_name is empty or parent_folder_id is invalid
```

---

<a id="emailfolders_rename"></a>

#### `emailfolders_rename`

✏️ Rename a mail folder (requires user confirmation recommended)

**Title:** Rename Email Folder  
**Safety level:** `moderate`  
**Category:** `emailfolders`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Updates the display name of an existing mail folder.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `folder_id` | `string` | yes | — | The folder ID to rename |
| `new_display_name` | `string` | yes | — | New name for the folder |
| `account_id` | `string` | yes | — | Microsoft account ID |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Updated folder object with new displayName
```

**Raises:**

```text
ValueError: If folder_id is invalid or new_display_name is empty
```

---

<a id="emailfolders_move"></a>

#### `emailfolders_move`

✏️ Move a mail folder to a different parent (requires user confirmation recommended)

**Title:** Move Email Folder  
**Safety level:** `moderate`  
**Category:** `emailfolders`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Moves a mail folder to become a child of a different parent folder.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `folder_id` | `string` | yes | — | The folder ID to move |
| `destination_folder_id` | `string` | yes | — | The destination parent folder ID |
| `account_id` | `string` | yes | — | Microsoft account ID |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Updated folder object with new parentFolderId
```

**Raises:**

```text
ValueError: If folder_id or destination_folder_id is invalid
```

---

<a id="emailfolders_delete"></a>

#### `emailfolders_delete`

🔴 Delete a mail folder permanently (always require user confirmation)

**Title:** Delete Email Folder  
**Safety level:** `critical`  
**Category:** `emailfolders`  
**Hints:** readOnlyHint=`false`, destructiveHint=`true`, idempotentHint=`false`, openWorldHint=`true`  
**Requires `confirm=true`:** yes

WARNING: This action permanently deletes the folder and all its contents
(emails and subfolders) and cannot be undone.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `folder_id` | `string` | yes | — | The folder ID to delete |
| `account_id` | `string` | yes | — | Microsoft account ID |
| `confirm` | `boolean` | no | `false` | Must be True to confirm deletion (prevents accidents) |

**Output:** `structuredContent`: `object<string, string>` (no declared fields).

**Returns (as documented):**

```text
Status confirmation
```

**Raises:**

```text
ValueError: If folder_id is invalid or confirm is False
```

---

<a id="emailfolders_mark_all_as_read"></a>

#### `emailfolders_mark_all_as_read`

✏️ Mark all messages in a folder as read (requires user confirmation recommended)

**Title:** Mark All Emails in Folder as Read  
**Safety level:** `moderate`  
**Category:** `emailfolders`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Updates all messages in the specified folder to mark them as read.
This operation may take time for folders with many messages.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `folder_id` | `string` | yes | — | The folder ID containing messages to mark as read |
| `account_id` | `string` | yes | — | Microsoft account ID |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Status confirmation with count of messages updated
```

**Raises:**

```text
ValueError: If folder_id is invalid
```

---

<a id="emailfolders_empty"></a>

#### `emailfolders_empty`

🔴 Delete all messages in a folder (always require user confirmation)

**Title:** Empty Email Folder  
**Safety level:** `critical`  
**Category:** `emailfolders`  
**Hints:** readOnlyHint=`false`, destructiveHint=`true`, idempotentHint=`false`, openWorldHint=`true`  
**Requires `confirm=true`:** yes

WARNING: This action permanently deletes all messages in the folder
and cannot be undone. The folder itself remains but all messages
are permanently deleted.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `folder_id` | `string` | yes | — | The folder ID to empty |
| `account_id` | `string` | yes | — | Microsoft account ID |
| `confirm` | `boolean` | no | `false` | Must be True to confirm deletion (prevents accidents) |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Status confirmation with count of messages deleted
```

**Raises:**

```text
ValueError: If folder_id is invalid or confirm is False
```

---

### 5.4 Mail rules (9 tools)

Manage Outlook inbox rules and their execution order.

<a id="emailrules_list"></a>

#### `emailrules_list`

📖 List all inbox message rules (read-only, safe for unsupervised use)

**Title:** List Email Rules  
**Safety level:** `safe`  
**Category:** `emailrules`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Message rules automatically process incoming emails based on conditions.
Rules are executed in sequence order (1, 2, 3...).

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `account_id` | `string` | yes | — | Microsoft account ID |

**Output:** `structuredContent.result`: `array<object>` (the tool's return value, wrapped under `result`).

**Returns (as documented):**

```text
List of rules with: id, displayName, sequence, isEnabled, conditions, actions
```

---

<a id="emailrules_get"></a>

#### `emailrules_get`

📖 Get details of a specific message rule (read-only, safe for unsupervised use)

**Title:** Get Email Rule  
**Safety level:** `safe`  
**Category:** `emailrules`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Returns complete rule configuration including conditions, actions, and execution order.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `rule_id` | `string` | yes | — | The message rule ID |
| `account_id` | `string` | yes | — | Microsoft account ID |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Rule details including conditions, actions, sequence, and enabled status
```

---

<a id="emailrules_create"></a>

#### `emailrules_create`

✏️ Create a new inbox message rule to automatically process emails (requires user confirmation recommended)

**Title:** Create Email Rule  
**Safety level:** `moderate`  
**Category:** `emailrules`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Rules are executed in priority order (sequence number).

Conditions examples:

```text
{"fromAddresses": [{"address": "john@example.com"}]}
{"subjectContains": ["urgent", "important"]}
{"senderContains": ["@company.com"]}
{"hasAttachments": true}
```

Actions examples:

```text
{"moveToFolder": "folder_id"}
{"markAsRead": true}
{"forwardTo": [{"emailAddress": {"address": "manager@example.com"}}]}
{"assignCategories": ["Red category"]}
{"delete": true}
```

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `account_id` | `string` | yes | — | Microsoft account ID |
| `display_name` | `string` | yes | — | Name for the rule (e.g., "Move work emails to Projects") |
| `conditions` | `object` | yes | — | Conditions that trigger the rule |
| `actions` | `object` | yes | — | Actions to perform when conditions match |
| `sequence` | `integer` | no | `1` | Rule execution order (lower numbers execute first, default: 1) |
| `is_enabled` | `boolean` | no | `true` | Whether the rule is active (default: True) |
| `exceptions` | `object \| null` | no | `null` | Optional conditions that prevent rule execution |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Created rule with its ID and full configuration
```

---

<a id="emailrules_update"></a>

#### `emailrules_update`

✏️ Update an existing message rule (requires user confirmation recommended)

**Title:** Update Email Rule  
**Safety level:** `moderate`  
**Category:** `emailrules`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Modifies rule properties, conditions, actions, or execution order.
At least one field must be provided to update.

Allowed parameters: display_name, conditions, actions, sequence,
is_enabled, exceptions.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `rule_id` | `string` | yes | — | The message rule ID to update |
| `account_id` | `string` | yes | — | Microsoft account ID |
| `display_name` | `string \| null` | no | `null` | New name for the rule (optional) |
| `conditions` | `object \| null` | no | `null` | New conditions (optional) |
| `actions` | `object \| null` | no | `null` | New actions (optional) |
| `sequence` | `integer \| null` | no | `null` | New execution order (optional) |
| `is_enabled` | `boolean \| null` | no | `null` | Enable or disable the rule (optional) |
| `exceptions` | `object \| null` | no | `null` | New exception conditions (optional) |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Updated rule configuration
```

---

<a id="emailrules_delete"></a>

#### `emailrules_delete`

🔴 Delete a message rule permanently (always require user confirmation)

**Title:** Delete Email Rule  
**Safety level:** `critical`  
**Category:** `emailrules`  
**Hints:** readOnlyHint=`false`, destructiveHint=`true`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** yes

WARNING: This action permanently deletes the rule and cannot be undone.
Emails will no longer be automatically processed by this rule.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `rule_id` | `string` | yes | — | The message rule ID to delete |
| `account_id` | `string` | yes | — | Microsoft account ID |
| `confirm` | `boolean` | no | `false` | Must be True to confirm deletion (prevents accidents) |

**Output:** `structuredContent`: `object<string, string>` (no declared fields).

**Returns (as documented):**

```text
Status confirmation
```

---

<a id="emailrules_move_top"></a>

#### `emailrules_move_top`

✏️ Move a message rule to the top of execution order (requires user confirmation recommended)

**Title:** Move Email Rule to Top  
**Safety level:** `moderate`  
**Category:** `emailrules`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Rules execute in sequence order. Moving to top means it runs before all other rules.
Sets the rule's sequence number to 1.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `rule_id` | `string` | yes | — | The message rule ID to move |
| `account_id` | `string` | yes | — | Microsoft account ID |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Updated rule with new sequence number
```

---

<a id="emailrules_move_bottom"></a>

#### `emailrules_move_bottom`

✏️ Move a message rule to the bottom of execution order (requires user confirmation recommended)

**Title:** Move Email Rule to Bottom  
**Safety level:** `moderate`  
**Category:** `emailrules`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Rules execute in sequence order. Moving to bottom means it runs after all other rules.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `rule_id` | `string` | yes | — | The message rule ID to move |
| `account_id` | `string` | yes | — | Microsoft account ID |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Updated rule with new sequence number
```

---

<a id="emailrules_move_up"></a>

#### `emailrules_move_up`

✏️ Move a message rule up one position in execution order (requires user confirmation recommended)

**Title:** Move Email Rule Up  
**Safety level:** `moderate`  
**Category:** `emailrules`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Increases the rule's priority by moving it one position higher in the
execution order. Rules at the top (sequence = 1) cannot be moved up.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `rule_id` | `string` | yes | — | The message rule ID to move |
| `account_id` | `string` | yes | — | Microsoft account ID |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Updated rule with new sequence number
```

---

<a id="emailrules_move_down"></a>

#### `emailrules_move_down`

✏️ Move a message rule down one position in execution order (requires user confirmation recommended)

**Title:** Move Email Rule Down  
**Safety level:** `moderate`  
**Category:** `emailrules`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Decreases the rule's priority by moving it one position lower in the
execution order. Rules at the bottom cannot be moved down further.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `rule_id` | `string` | yes | — | The message rule ID to move |
| `account_id` | `string` | yes | — | Microsoft account ID |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Updated rule with new sequence number
```

---

### 5.5 Calendar (13 tools)

Events, calendars, invitations and availability.

<a id="calendar_list_events"></a>

#### `calendar_list_events`

📖 List upcoming calendar events (read-only, safe for unsupervised use)

**Title:** List Calendar Events  
**Safety level:** `safe`  
**Category:** `calendar`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no  
**Cache:** fresh 5 min, stale-while-refresh until 30 min

Returns calendar events from now until the specified number of days ahead.

Caching: Results are cached for 5 minutes (fresh) / 30 minutes (stale).
Use force_refresh=True to bypass cache and fetch fresh data.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `account_id` | `string` | yes | — | Microsoft account ID |
| `days_ahead` | `integer` | no | `7` | Number of days ahead to look for events (1-365, default: 7) |
| `include_details` | `boolean` | no | `false` | Include full event details like attendees and body (default: False) |
| `limit` | `integer` | no | `50` | Maximum events to return (1-200, default: 50) |
| `use_cache` | `boolean` | no | `true` | Whether to use cached data if available (default: True) |
| `force_refresh` | `boolean` | no | `false` | Force refresh from API, bypassing cache (default: False) |

**Output:** `structuredContent.result`: `array<object>` (the tool's return value, wrapped under `result`).

**Returns (as documented):**

```text
List of calendar events with metadata.
Each event includes _cache_status and _cached_at fields.
```

---

<a id="calendar_get_event"></a>

#### `calendar_get_event`

📖 Get full event details (read-only, safe for unsupervised use)

**Title:** Get Calendar Event  
**Safety level:** `safe`  
**Category:** `calendar`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no  
**Cache:** fresh 10 min, stale-while-refresh until 60 min

Returns complete event information including recurrence patterns and online meeting details.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `event_id` | `string` | yes | — | The event ID |
| `account_id` | `string` | yes | — | Microsoft account ID |
| `use_cache` | `boolean` | no | `true` | Whether to use cache (default: True) |
| `force_refresh` | `boolean` | no | `false` | Bypass cache and fetch fresh data (default: False) |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Complete event object with all metadata
```

---

<a id="calendar_create_event"></a>

#### `calendar_create_event`

✏️ Create a calendar event (requires user confirmation recommended)

**Title:** Create Calendar Event  
**Safety level:** `moderate`  
**Category:** `calendar`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Creates a new calendar event with optional attendees and location.
Attendees will receive meeting invitations. Addresses are validated,
deduplicated, and limited to 500 unique recipients.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `account_id` | `string` | yes | — | Microsoft account ID |
| `subject` | `string` | yes | — | Event title |
| `start` | `string` | yes | — | Start time in ISO format (e.g., "2024-01-15T10:00:00") |
| `end` | `string` | yes | — | End time in ISO format |
| `location` | `string \| null` | no | `null` | Location name (optional) |
| `body` | `string \| null` | no | `null` | Event description (optional) |
| `attendees` | `string \| array<string> \| null` | no | `null` | Email address(es) of attendees (optional) |
| `timezone` | `string` | no | `"UTC"` | Timezone for the event (default: "UTC") |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Created event object with ID
```

**Raises:**

```text
ValidationError: If datetime values, timezone, or attendee
    addresses are invalid.
```

---

<a id="calendar_update_event"></a>

#### `calendar_update_event`

✏️ Update event properties (requires user confirmation recommended)

**Title:** Update Calendar Event  
**Safety level:** `moderate`  
**Category:** `calendar`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Modifies event details like time, location, or attendees.
Attendees will receive update notifications.

Allowed update keys: subject, start, end, timezone, location, body, attendees.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `event_id` | `string` | yes | — | The event ID to update |
| `updates` | `object` | yes | — | Dictionary with fields to update (subject, start, end, location, body) |
| `account_id` | `string` | yes | — | Microsoft account ID |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Updated event object
```

---

<a id="calendar_delete_event"></a>

#### `calendar_delete_event`

🔴 Delete a calendar event (always require user confirmation)

**Title:** Delete Calendar Event  
**Safety level:** `critical`  
**Category:** `calendar`  
**Hints:** readOnlyHint=`false`, destructiveHint=`true`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** yes

WARNING: This action permanently deletes the event and cannot be undone.
If this is a meeting, attendees will receive cancellation notices.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `account_id` | `string` | yes | — | Microsoft account ID |
| `event_id` | `string` | yes | — | The event to delete |
| `send_cancellation` | `boolean` | no | `true` | Whether to notify attendees (default: True) |
| `confirm` | `boolean` | no | `false` | Must be True to confirm deletion (prevents accidents) |

**Output:** `structuredContent`: `object<string, string>` (no declared fields).

**Implementation note:** Calls `DELETE /me/events/{event_id}`. For a meeting you organise, Microsoft Graph sends a cancellation to every attendee (see section 2.8).

**Returns (as documented):**

```text
Status confirmation
```

---

<a id="calendar_respond_event"></a>

#### `calendar_respond_event`

⚠️ Respond to a calendar event invitation (requires user confirmation recommended)

**Title:** Respond to Calendar Event  
**Safety level:** `moderate`  
**Category:** `calendar`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no

IMPORTANT: This sends a response to the event organizer.

Valid responses:

```text
- "accept" - Accept the invitation
- "decline" - Decline the invitation
- "tentativelyAccept" - Mark as tentative
```

  (Input is case-insensitive; "tentative" is accepted as an alias.)

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `account_id` | `string` | yes | — | Microsoft account ID |
| `event_id` | `string` | yes | — | The event ID to respond to |
| `response` | `string` | no | `"accept"` | Response type (default: "accept") |
| `message` | `string \| null` | no | `null` | Optional message to the organizer |

**Output:** `structuredContent`: `object<string, string>` (no declared fields).

**Returns (as documented):**

```text
Status confirmation
```

**Raises:**

```text
ValidationError: If the response value or message payload is invalid.
```

---

<a id="calendar_check_availability"></a>

#### `calendar_check_availability`

📖 Check calendar availability for scheduling (read-only, safe for unsupervised use)

**Title:** Check Calendar Availability  
**Safety level:** `safe`  
**Category:** `calendar`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Returns free/busy information for the user and optional attendees.
Useful for finding meeting times.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `account_id` | `string` | yes | — | Microsoft account ID |
| `start` | `string` | yes | — | Start time in ISO format |
| `end` | `string` | yes | — | End time in ISO format |
| `attendees` | `string \| array<string> \| null` | no | `null` | Optional email address(es) to check availability |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Schedule information with free/busy slots
```

**Raises:**

```text
ValidationError: If start/end datetimes or attendee addresses
    are invalid.
ValueError: If the current account email address is unavailable.
```

---

<a id="calendar_forward_event"></a>

#### `calendar_forward_event`

📧 Forward a calendar event to recipients (always require user confirmation)

**Title:** Forward Calendar Event  
**Safety level:** `dangerous`  
**Category:** `calendar`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Requires `confirm=true`:** yes

WARNING: Meeting invitation will be sent immediately to specified recipients.
This action cannot be undone.

Addresses are validated, deduplicated across To/CC, and limited to
500 unique recipients in total.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `account_id` | `string` | yes | — | Microsoft account ID |
| `event_id` | `string` | yes | — | The event ID to forward |
| `to` | `string \| array<string>` | yes | — | Recipient email address(es) |
| `cc` | `string \| array<string> \| null` | no | `null` | CC recipient email address(es) (optional) |
| `message` | `string \| null` | no | `null` | Optional comment/message to include with forward (plain text) |
| `confirm` | `boolean` | no | `false` | Must be True to confirm sending (prevents accidents) |

**Output:** `structuredContent`: `object<string, string>` (no declared fields).

**Returns (as documented):**

```text
Status confirmation
```

**Raises:**

```text
ValidationError: If recipients are invalid, exceed limits,
    or confirm is False.
```

---

<a id="calendar_list_calendars"></a>

#### `calendar_list_calendars`

📖 List all available calendars (read-only, safe for unsupervised use)

**Title:** List Calendars  
**Safety level:** `safe`  
**Category:** `calendar`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no  
**Cache:** fresh 5 min, stale-while-refresh until 15 min

Returns all calendars accessible by the user, including primary calendar
and any additional calendars (shared, group, etc.).

Caching: Results are cached for 15 minutes (fresh) / 1 hour (stale).
Use force_refresh=True to bypass cache and fetch fresh data.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `account_id` | `string` | yes | — | Microsoft account ID |
| `use_cache` | `boolean` | no | `true` | Whether to use cached data if available (default: True) |
| `force_refresh` | `boolean` | no | `false` | Force refresh from API, bypassing cache (default: False) |

**Output:** `structuredContent.result`: `array<object>` (the tool's return value, wrapped under `result`).

**Returns (as documented):**

```text
List of calendar objects with metadata.
Each calendar includes _cache_status and _cached_at fields.
```

---

<a id="calendar_create_calendar"></a>

#### `calendar_create_calendar`

✏️ Create a new calendar (requires user confirmation recommended)

**Title:** Create Calendar  
**Safety level:** `moderate`  
**Category:** `calendar`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Creates a new calendar in the user's mailbox. Useful for organizing
events into separate calendars (work, personal, project-specific, etc.).

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `account_id` | `string` | yes | — | Microsoft account ID |
| `name` | `string` | yes | — | Name for the new calendar |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Created calendar object with ID and metadata
```

**Raises:**

```text
ValidationError: If calendar name is empty or invalid.
```

---

<a id="calendar_delete_calendar"></a>

#### `calendar_delete_calendar`

🔴 Delete a calendar permanently (always require user confirmation)

**Title:** Delete Calendar  
**Safety level:** `critical`  
**Category:** `calendar`  
**Hints:** readOnlyHint=`false`, destructiveHint=`true`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** yes

WARNING: This action permanently deletes the calendar and ALL events
contained within it. This action cannot be undone.

Note: The default calendar cannot be deleted.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `account_id` | `string` | yes | — | Microsoft account ID |
| `calendar_id` | `string` | yes | — | The calendar ID to delete |
| `confirm` | `boolean` | no | `false` | Must be True to confirm deletion (prevents accidents) |

**Output:** `structuredContent`: `object<string, string>` (no declared fields).

**Returns (as documented):**

```text
Status confirmation
```

**Raises:**

```text
ValidationError: If confirm is False.
ValueError: If attempting to delete the default calendar.
```

---

<a id="calendar_propose_new_time"></a>

#### `calendar_propose_new_time`

✏️ Propose a new time for a meeting (requires user confirmation recommended)

**Title:** Propose New Meeting Time  
**Safety level:** `moderate`  
**Category:** `calendar`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Proposes a new meeting time to the organizer. This is useful when you've
been invited to a meeting but the time doesn't work for you.

Note: This only works for meetings where you are an attendee, not the organizer.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `account_id` | `string` | yes | — | Microsoft account ID |
| `event_id` | `string` | yes | — | The event ID to propose new time for |
| `proposed_start` | `string` | yes | — | Proposed start time in ISO format (e.g., "2024-01-15T10:00:00") |
| `proposed_end` | `string` | yes | — | Proposed end time in ISO format |
| `message` | `string \| null` | no | `null` | Optional message explaining the proposed change |

**Output:** `structuredContent`: `object<string, string>` (no declared fields).

**Returns (as documented):**

```text
Status confirmation
```

**Raises:**

```text
ValidationError: If datetime values are invalid.
```

---

<a id="calendar_get_free_busy"></a>

#### `calendar_get_free_busy`

📖 Get simplified free/busy times for attendees (read-only, safe for unsupervised use)

**Title:** Get Free/Busy Times  
**Safety level:** `safe`  
**Category:** `calendar`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Returns a simplified view of free/busy information for specified attendees.
This is similar to calendar_check_availability but focuses on availability
view strings rather than detailed schedule information.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `account_id` | `string` | yes | — | Microsoft account ID |
| `attendees` | `string \| array<string>` | yes | — | Email address(es) to check availability for |
| `start` | `string` | yes | — | Start time in ISO format |
| `end` | `string` | yes | — | End time in ISO format |
| `time_interval` | `integer` | no | `30` | Interval in minutes for availability view (default: 30) |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Free/busy information with availability view strings
```

**Raises:**

```text
ValidationError: If start/end datetimes or attendee addresses are invalid.
```

---

### 5.6 Contacts (8 tools)

Personal contacts and contact lists.

<a id="contact_list"></a>

#### `contact_list`

📖 List contacts (read-only, safe for unsupervised use)

**Title:** List Contacts  
**Safety level:** `safe`  
**Category:** `contact`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no  
**Cache:** fresh 20 min, stale-while-refresh until 120 min

Returns contacts with names, email addresses, and phone numbers.

Caching: Results are cached for 20 minutes (fresh) / 2 hours (stale).
Use force_refresh=True to bypass cache and fetch fresh data.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `account_id` | `string` | yes | — | Microsoft account ID |
| `limit` | `integer` | no | `50` | Maximum contacts to return (1-500, default: 50) |
| `use_cache` | `boolean` | no | `true` | Whether to use cached data if available (default: True) |
| `force_refresh` | `boolean` | no | `false` | Force refresh from API, bypassing cache (default: False) |

**Output:** `structuredContent.result`: `array<object>` (the tool's return value, wrapped under `result`).

**Returns (as documented):**

```text
List of contact objects with metadata.
Each contact includes _cache_status and _cached_at fields.
```

---

<a id="contact_get"></a>

#### `contact_get`

📖 Get contact details (read-only, safe for unsupervised use)

**Title:** Get Contact  
**Safety level:** `safe`  
**Category:** `contact`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no  
**Cache:** fresh 30 min, stale-while-refresh until 240 min

Returns complete contact information including all fields.

Caching: Results are cached for 30 minutes (fresh) / 4 hours (stale).
Use force_refresh=True to bypass cache and fetch fresh data.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `contact_id` | `string` | yes | — | The contact ID |
| `account_id` | `string` | yes | — | Microsoft account ID |
| `use_cache` | `boolean` | no | `true` | Whether to use cached data if available (default: True) |
| `force_refresh` | `boolean` | no | `false` | Force refresh from API, bypassing cache (default: False) |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Contact details with:
- _cache_status: Cache state (fresh/stale/miss)
- _cached_at: When data was cached (ISO format)
```

---

<a id="contact_create"></a>

#### `contact_create`

✏️ Create a new contact (requires user confirmation recommended)

**Title:** Create Contact  
**Safety level:** `moderate`  
**Category:** `contact`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Creates a contact with name, email addresses, and phone numbers.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `account_id` | `string` | yes | — | Microsoft account ID |
| `given_name` | `string` | yes | — | First name (required) |
| `surname` | `string \| null` | no | `null` | Last name (optional) |
| `email_addresses` | `string \| array<string> \| null` | no | `null` | Email address(es) (optional) |
| `phone_numbers` | `object<string, string> \| null` | no | `null` | Phone numbers dict with keys: business, home, mobile (optional) |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Created contact object with ID
```

---

<a id="contact_update"></a>

#### `contact_update`

✏️ Update contact information (requires user confirmation recommended)

**Title:** Update Contact  
**Safety level:** `moderate`  
**Category:** `contact`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Modifies contact fields like name, email, or phone numbers.

Allowed update keys: givenName, surname, displayName, emailAddresses,
businessPhones, homePhones, mobilePhone, jobTitle, companyName, department.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `contact_id` | `string` | yes | — | The contact ID to update |
| `updates` | `object` | yes | — | Dictionary with fields to update |
| `account_id` | `string` | yes | — | Microsoft account ID |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Updated contact object
```

---

<a id="contact_delete"></a>

#### `contact_delete`

🔴 Delete a contact permanently (always require user confirmation)

**Title:** Delete Contact  
**Safety level:** `critical`  
**Category:** `contact`  
**Hints:** readOnlyHint=`false`, destructiveHint=`true`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** yes

WARNING: This action permanently deletes the contact and cannot be undone.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `contact_id` | `string` | yes | — | The contact to delete |
| `account_id` | `string` | yes | — | Microsoft account ID |
| `confirm` | `boolean` | no | `false` | Must be True to confirm deletion (prevents accidents) |

**Output:** `structuredContent`: `object<string, string>` (no declared fields).

**Returns (as documented):**

```text
Status confirmation
```

---

<a id="contact_create_list"></a>

#### `contact_create_list`

✏️ Create a new contact list (requires user confirmation recommended)

**Title:** Create Contact List  
**Safety level:** `moderate`  
**Category:** `contact`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Creates a contact folder (list) for organizing contacts into groups.
Useful for creating distribution lists, project teams, or other groupings.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `account_id` | `string` | yes | — | Microsoft account ID |
| `list_name` | `string` | yes | — | Name for the contact list/folder |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Created contact folder object with ID
```

**Raises:**

```text
ValidationError: If list name is empty or invalid.
```

---

<a id="contact_add_to_list"></a>

#### `contact_add_to_list`

✏️ Add a contact to a contact list (requires user confirmation recommended)

**Title:** Add Contact to List  
**Safety level:** `moderate`  
**Category:** `contact`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Adds an existing contact to a contact folder (list). The contact is copied
to the list, so it will exist in both the original location and the list.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `account_id` | `string` | yes | — | Microsoft account ID |
| `contact_id` | `string` | yes | — | The contact ID to add |
| `list_id` | `string` | yes | — | The contact list/folder ID |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Copy of the contact in the new list
```

**Raises:**

```text
ValueError: If contact or list is not found.
```

---

<a id="contact_export"></a>

#### `contact_export`

📖 Export a contact in vCard format (read-only, safe for unsupervised use)

**Title:** Export Contact  
**Safety level:** `safe`  
**Category:** `contact`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Exports contact information in vCard format for portability and sharing.
vCard is a standard format supported by most contact management applications.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `account_id` | `string` | yes | — | Microsoft account ID |
| `contact_id` | `string` | yes | — | The contact ID to export |
| `format` | `string` | no | `"vcard"` | Export format (currently only "vcard" is supported) |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Dictionary containing the vCard data and metadata
```

**Raises:**

```text
ValidationError: If format is not supported.
ValueError: If contact is not found.
```

---

### 5.7 OneDrive files (10 tools)

OneDrive file operations, sharing and transfers.

<a id="file_list"></a>

#### `file_list`

📖 List files and/or folders in OneDrive (read-only, safe for unsupervised use)

**Title:** List Files  
**Safety level:** `safe`  
**Category:** `file`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no  
**Cache:** fresh 10 min, stale-while-refresh until 60 min

Returns items from OneDrive with names, sizes, and modification dates.

Caching: Results are cached for 10 minutes (fresh) / 1 hour (stale).
Use force_refresh=True to bypass cache and fetch fresh data.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `account_id` | `string` | yes | — | Microsoft account ID |
| `path` | `string` | no | `"/"` | Path to list from (default: "/") |
| `folder_id` | `string \| null` | no | `null` | Direct folder ID (takes precedence over path) |
| `limit` | `integer` | no | `50` | Maximum items to return (1-500, default: 50) |
| `type_filter` | `string` | no | `"all"` | Filter by type - "all", "files", or "folders" (default: "all") |
| `use_cache` | `boolean` | no | `true` | Whether to use cached data if available (default: True) |
| `force_refresh` | `boolean` | no | `false` | Force refresh from API, bypassing cache (default: False) |

**Output:** `structuredContent.result`: `array<object>` (the tool's return value, wrapped under `result`).

**Returns (as documented):**

```text
List of items matching the filter criteria.
Each item includes _cache_status and _cached_at fields.
```

---

<a id="file_get"></a>

#### `file_get`

✏️ Download a OneDrive file to a local path (requires user confirmation recommended)

**Title:** Get File  
**Safety level:** `moderate`  
**Category:** `file`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no

The download URL is supplied by Microsoft Graph (never user input) and is
validated against an allow-list of Microsoft domains before use. The file
is streamed to disk in configurable chunks with retry behaviour to protect
against transient failures. Download size and timeouts respect the
environment variables `MCP_FILE_DOWNLOAD_MAX_MB` and
`MCP_FILE_DOWNLOAD_TIMEOUT`.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `file_id` | `string` | yes | — | The Microsoft Graph file identifier to download. |
| `account_id` | `string` | yes | — | Microsoft account identifier associated with the file. |
| `download_path` | `string` | yes | — | Absolute path where the file will be stored locally. Must reside within an allowed root directory. |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Dictionary containing download metadata (name, size_mb, mime_type).
```

**Raises:**

```text
ValidationError: If input parameters are invalid.
RuntimeError: If all download attempts fail.
```

---

<a id="file_create"></a>

#### `file_create`

✏️ Upload a local file to OneDrive (requires user confirmation recommended)

**Title:** Create File  
**Safety level:** `moderate`  
**Category:** `file`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Requires `confirm=true`:** no

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `onedrive_path` | `string` | yes | — | Destination path within OneDrive (must start with '/'). |
| `local_file_path` | `string` | yes | — | Absolute path to the local file to upload. Paths are validated via `ensure_safe_path` to prevent traversal and restrict uploads to trusted directories. |
| `account_id` | `string` | yes | — | Microsoft account identifier. |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Metadata for the created OneDrive file.
```

---

<a id="file_update"></a>

#### `file_update`

✏️ Replace OneDrive file content with local file (requires user confirmation recommended)

**Title:** Update File  
**Safety level:** `moderate`  
**Category:** `file`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `file_id` | `string` | yes | — | Target OneDrive file identifier to replace. |
| `local_file_path` | `string` | yes | — | Absolute path to the replacement file. Validated via `ensure_safe_path` to block traversal and enforce workspace roots. |
| `account_id` | `string` | yes | — | Microsoft account identifier. |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Updated file metadata returned by Microsoft Graph.
```

---

<a id="file_delete"></a>

#### `file_delete`

🔴 Delete a OneDrive file or folder permanently (always require user confirmation)

**Title:** Delete File  
**Safety level:** `critical`  
**Category:** `file`  
**Hints:** readOnlyHint=`false`, destructiveHint=`true`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** yes

WARNING: This action permanently deletes the file or folder and cannot be undone.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `file_id` | `string` | yes | — | OneDrive item ID of the file or folder *(from implementation; the docstring has no Args section)* |
| `account_id` | `string` | yes | — | Microsoft account ID *(from implementation)* |
| `confirm` | `boolean` | no | `false` | Must be `true`, or the call is refused *(from implementation)* |

**Output:** `structuredContent`: `object<string, string>` (no declared fields).

**Implementation note:** Returns `{"status": "deleted"}`. The tool calls `DELETE /me/drive/items/{file_id}`. In Microsoft Graph this moves the item to the OneDrive recycle bin, from which it can be restored; it is not a permanent delete, despite the tool's description. Deleting a folder deletes its contents. Invalidates the account's `file_list` and `folder_get_tree` cache entries.

---

<a id="file_copy"></a>

#### `file_copy`

✏️ Copy a file within OneDrive (requires user confirmation recommended)

**Title:** Copy File  
**Safety level:** `moderate`  
**Category:** `file`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Creates a copy of a file in a specified destination folder. The copy
operation is asynchronous and may take time for large files.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `file_id` | `string` | yes | — | The file ID to copy |
| `destination_folder_id` | `string` | yes | — | The destination folder ID |
| `account_id` | `string` | yes | — | Microsoft account ID |
| `new_name` | `string \| null` | no | `null` | Optional new name for the copied file |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Copy operation status with location URL to monitor progress
```

**Raises:**

```text
ValueError: If file_id or destination_folder_id is invalid
```

---

<a id="file_move"></a>

#### `file_move`

✏️ Move a file to a different folder (requires user confirmation recommended)

**Title:** Move File  
**Safety level:** `moderate`  
**Category:** `file`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Moves a file to a different parent folder within OneDrive.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `file_id` | `string` | yes | — | The file ID to move |
| `destination_folder_id` | `string` | yes | — | The destination folder ID |
| `account_id` | `string` | yes | — | Microsoft account ID |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Updated file object with new parentReference
```

**Raises:**

```text
ValueError: If file_id or destination_folder_id is invalid
```

---

<a id="file_rename"></a>

#### `file_rename`

✏️ Rename a file (requires user confirmation recommended)

**Title:** Rename File  
**Safety level:** `moderate`  
**Category:** `file`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Updates the name of an existing OneDrive file.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `file_id` | `string` | yes | — | The file ID to rename |
| `new_name` | `string` | yes | — | New name for the file |
| `account_id` | `string` | yes | — | Microsoft account ID |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Updated file object with new name
```

**Raises:**

```text
ValueError: If file_id is invalid or new_name is empty
```

---

<a id="file_share"></a>

#### `file_share`

✏️ Create a sharing link for a OneDrive file (requires user confirmation recommended)

**Title:** Share File  
**Safety level:** `moderate`  
**Category:** `file`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Creates a sharing link that allows others to access the file. Permission types
control what recipients can do with the file.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `file_id` | `string` | yes | — | The file ID to share |
| `account_id` | `string` | yes | — | Microsoft account ID |
| `permission_type` | `string` | no | `"view"` | Type of permission - "view" or "edit" (default: "view") |
| `scope` | `string` | no | `"anonymous"` | Link scope - "anonymous" or "organization" (default: "anonymous") |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Sharing link details including the web URL
```

**Raises:**

```text
ValueError: If file_id is invalid or permission_type/scope is unsupported
```

---

<a id="file_download_url"></a>

#### `file_download_url`

📖 Get direct download URL for a OneDrive file (read-only, safe for unsupervised use)

**Title:** Get File Download URL  
**Safety level:** `safe`  
**Category:** `file`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Returns a temporary download URL that can be used to download the file directly
without authentication. The URL expires after a short period.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `file_id` | `string` | yes | — | The file ID to get download URL for |
| `account_id` | `string` | yes | — | Microsoft account ID |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Dictionary containing the download URL and file metadata
```

**Raises:**

```text
ValueError: If file_id is invalid or file not found
```

---

### 5.8 OneDrive folders (7 tools)

OneDrive folder operations (not mail folders).

<a id="folder_list"></a>

#### `folder_list`

📖 List only folders (not files) in OneDrive (read-only, safe for unsupervised use)

**Title:** List Folders  
**Safety level:** `safe`  
**Category:** `folder`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no  
**Cache:** fresh 15 min, stale-while-refresh until 60 min

Returns folders with child counts and hierarchy information.

Caching: Results are cached for 15 minutes (fresh) / 1 hour (stale).
Use force_refresh=True to bypass cache and fetch fresh data.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `account_id` | `string` | yes | — | Microsoft account ID |
| `path` | `string` | no | `"/"` | Path to list folders from (e.g., "/Documents", default: "/") |
| `folder_id` | `string \| null` | no | `null` | Direct folder ID (takes precedence over path) |
| `limit` | `integer` | no | `50` | Maximum folders to return (1-500, default: 50) |
| `use_cache` | `boolean` | no | `true` | Whether to use cached data if available (default: True) |
| `force_refresh` | `boolean` | no | `false` | Force refresh from API, bypassing cache (default: False) |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Dictionary with:
- folders: List of folder objects with id, name, childCount, path, parentId
- _cache_status: Cache state (fresh/stale/miss)
- _cached_at: When data was cached (ISO format)
```

---

<a id="folder_get"></a>

#### `folder_get`

📖 Get metadata for a specific OneDrive folder (read-only, safe for unsupervised use)

**Title:** Get Folder  
**Safety level:** `safe`  
**Category:** `folder`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Returns folder details including child count and web URL.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `account_id` | `string` | yes | — | Microsoft account ID |
| `folder_id` | `string \| null` | no | `null` | Folder ID (takes precedence if provided) |
| `path` | `string \| null` | no | `null` | Folder path (e.g., "/Documents/Projects") |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Folder metadata including childCount, webUrl, and parent info
```

---

<a id="folder_get_tree"></a>

#### `folder_get_tree`

📖 Recursively build a tree of OneDrive folders (read-only, safe for unsupervised use)

**Title:** Get Folder Tree  
**Safety level:** `safe`  
**Category:** `folder`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no  
**Cache:** fresh 30 min, stale-while-refresh until 120 min

Returns a hierarchical tree structure showing all folders and nested subfolders.
Useful for understanding OneDrive folder organization.

Caching: Results are cached for 30 minutes (fresh) / 2 hours (stale).
Use force_refresh=True to bypass cache and fetch fresh data.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `account_id` | `string` | yes | — | Microsoft account ID |
| `path` | `string` | no | `"/"` | Starting path (default: "/") |
| `folder_id` | `string \| null` | no | `null` | Starting folder ID (takes precedence over path) |
| `max_depth` | `integer` | no | `10` | Maximum recursion depth (1-25, default: 10) |
| `use_cache` | `boolean` | no | `true` | Whether to use cached data if available (default: True) |
| `force_refresh` | `boolean` | no | `false` | Force refresh from API, bypassing cache (default: False) |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Nested tree structure with folders and their children, including:
- _cache_status: Cache state (fresh/stale/miss)
- _cached_at: When data was cached (ISO format)
```

---

<a id="folder_create"></a>

#### `folder_create`

✏️ Create a new OneDrive folder (requires user confirmation recommended)

**Title:** Create OneDrive Folder  
**Safety level:** `moderate`  
**Category:** `folder`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Creates a new folder in OneDrive, either at the root level or
as a child of an existing folder.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | `string` | yes | — | Name for the new folder |
| `account_id` | `string` | yes | — | Microsoft account ID |
| `parent_folder_id` | `string \| null` | no | `null` | Parent folder ID (None = root level) |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Created folder object with id, name, and other metadata
```

**Raises:**

```text
ValueError: If name is empty or parent_folder_id is invalid
```

---

<a id="folder_delete"></a>

#### `folder_delete`

🔴 Delete an OneDrive folder permanently (always require user confirmation)

**Title:** Delete OneDrive Folder  
**Safety level:** `critical`  
**Category:** `folder`  
**Hints:** readOnlyHint=`false`, destructiveHint=`true`, idempotentHint=`false`, openWorldHint=`true`  
**Requires `confirm=true`:** yes

WARNING: This action permanently deletes the folder and all its contents
(files and subfolders) and cannot be undone.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `folder_id` | `string` | yes | — | The folder ID to delete |
| `account_id` | `string` | yes | — | Microsoft account ID |
| `confirm` | `boolean` | no | `false` | Must be True to confirm deletion (prevents accidents) |

**Output:** `structuredContent`: `object<string, string>` (no declared fields).

**Implementation note:** Calls `DELETE /me/drive/items/{folder_id}`, which moves the folder and its contents to the OneDrive recycle bin (see section 2.8).

**Returns (as documented):**

```text
Status confirmation
```

**Raises:**

```text
ValueError: If folder_id is invalid or confirm is False
```

---

<a id="folder_rename"></a>

#### `folder_rename`

✏️ Rename an OneDrive folder (requires user confirmation recommended)

**Title:** Rename OneDrive Folder  
**Safety level:** `moderate`  
**Category:** `folder`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Updates the name of an existing OneDrive folder.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `folder_id` | `string` | yes | — | The folder ID to rename |
| `new_name` | `string` | yes | — | New name for the folder |
| `account_id` | `string` | yes | — | Microsoft account ID |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Updated folder object with new name
```

**Raises:**

```text
ValueError: If folder_id is invalid or new_name is empty
```

---

<a id="folder_move"></a>

#### `folder_move`

✏️ Move an OneDrive folder to a different parent (requires user confirmation recommended)

**Title:** Move OneDrive Folder  
**Safety level:** `moderate`  
**Category:** `folder`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Moves a folder to become a child of a different parent folder.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `folder_id` | `string` | yes | — | The folder ID to move |
| `destination_folder_id` | `string` | yes | — | The destination parent folder ID |
| `account_id` | `string` | yes | — | Microsoft account ID |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Updated folder object with new parentReference
```

**Raises:**

```text
ValueError: If folder_id or destination_folder_id is invalid
```

---

### 5.9 Search (5 tools)

Free-text search across mail, events, contacts and files.

<a id="search_files"></a>

#### `search_files`

📖 Search for files in OneDrive (read-only, safe for unsupervised use)

**Title:** Search Files  
**Safety level:** `safe`  
**Category:** `search`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no  
**Cache:** fresh 1 min, stale-while-refresh until 5 min

Searches file names and content across all accessible OneDrive folders.
Automatically routes to the appropriate API based on account type:
- Personal accounts: Uses OneDrive-specific search
- Work/school accounts: Uses unified search API

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | `string` | yes | — | Search query string (1-512 characters) |
| `account_id` | `string` | yes | — | Microsoft account ID |
| `limit` | `integer` | no | `50` | Maximum results to return (1-500, default: 50) |
| `use_cache` | `boolean` | no | `true` | Whether to use cache (default: True) |
| `force_refresh` | `boolean` | no | `false` | Bypass cache and fetch fresh data (default: False) |

**Output:** `structuredContent.result`: `array<object>` (the tool's return value, wrapped under `result`).

**Returns (as documented):**

```text
List of matching files with metadata
```

---

<a id="search_emails"></a>

#### `search_emails`

📖 Search emails across mailbox (read-only, safe for unsupervised use)

**Title:** Search Emails  
**Safety level:** `safe`  
**Category:** `search`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no  
**Cache:** fresh 1 min, stale-while-refresh until 5 min

Searches email subject, body, and sender across all or specific folders.
Automatically routes to the appropriate API based on account type:
- Personal accounts: Uses OData $search parameter
- Work/school accounts: Uses unified search API

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | `string` | yes | — | Search query string (1-512 characters) |
| `account_id` | `string` | yes | — | Microsoft account ID |
| `limit` | `integer` | no | `50` | Maximum results to return (1-500, default: 50) |
| `folder` | `string \| null` | no | `null` | Optional folder to search within (e.g., "inbox", "sent") |
| `use_cache` | `boolean` | no | `true` | Whether to use cache (default: True) |
| `force_refresh` | `boolean` | no | `false` | Bypass cache and fetch fresh data (default: False) |

**Output:** `structuredContent.result`: `array<object>` (the tool's return value, wrapped under `result`).

**Returns (as documented):**

```text
List of matching emails with metadata
```

---

<a id="search_events"></a>

#### `search_events`

📖 Search calendar events (read-only, safe for unsupervised use)

**Title:** Search Events  
**Safety level:** `safe`  
**Category:** `search`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no  
**Cache:** fresh 5 min, stale-while-refresh until 15 min

Searches event titles, locations, and descriptions within date range.
Automatically routes to the appropriate API based on account type:
- Personal accounts: Uses OData $search parameter
- Work/school accounts: Uses unified search API

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | `string` | yes | — | Search query string (1-512 characters) |
| `account_id` | `string` | yes | — | Microsoft account ID |
| `days_ahead` | `integer` | no | `365` | Days to look forward (0-730, default: 365) |
| `days_back` | `integer` | no | `365` | Days to look back (0-730, default: 365) |
| `limit` | `integer` | no | `50` | Maximum results to return (1-500, default: 50) |
| `use_cache` | `boolean` | no | `true` | Whether to use cache (default: True) |
| `force_refresh` | `boolean` | no | `false` | Bypass cache and fetch fresh data (default: False) |

**Output:** `structuredContent.result`: `array<object>` (the tool's return value, wrapped under `result`).

**Returns (as documented):**

```text
List of matching events
```

---

<a id="search_contacts"></a>

#### `search_contacts`

📖 Search contacts (read-only, safe for unsupervised use)

**Title:** Search Contacts  
**Safety level:** `safe`  
**Category:** `search`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no  
**Cache:** fresh 5 min, stale-while-refresh until 15 min

Searches contact names, email addresses, and phone numbers.
Uses $filter with prefix matching (startswith) for all account types
due to Graph API limitations.

Note: Contact search is limited to prefix matching and may not find
matches in the middle of names.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | `string` | yes | — | Search query string (1-512 characters, used as prefix) |
| `account_id` | `string` | yes | — | Microsoft account ID |
| `limit` | `integer` | no | `50` | Maximum results to return (1-500, default: 50) |
| `use_cache` | `boolean` | no | `true` | Whether to use cache (default: True) |
| `force_refresh` | `boolean` | no | `false` | Bypass cache and fetch fresh data (default: False) |

**Output:** `structuredContent.result`: `array<object>` (the tool's return value, wrapped under `result`).

**Returns (as documented):**

```text
List of matching contacts
```

---

<a id="search_unified"></a>

#### `search_unified`

📖 Search across multiple Microsoft 365 resources (read-only, safe for unsupervised use)

**Title:** Unified Search  
**Safety level:** `safe`  
**Category:** `search`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no  
**Cache:** fresh 5 min, stale-while-refresh until 15 min

Searches emails, events, and files simultaneously.
Automatically routes to the appropriate API based on account type:
- Personal accounts: Performs sequential searches for each entity type
- Work/school accounts: Uses unified search API for parallel search

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | `string` | yes | — | Search query string (1-512 characters) |
| `account_id` | `string` | yes | — | Microsoft account ID |
| `entity_types` | `array<string> \| null` | no | `null` | Types to search: 'message', 'event', 'driveItem' (default: all) |
| `limit` | `integer` | no | `50` | Maximum results per type (1-500, default: 50) |
| `use_cache` | `boolean` | no | `true` | Whether to use cache (default: True) |
| `force_refresh` | `boolean` | no | `false` | Bypass cache and fetch fresh data (default: False) |

**Output:** `structuredContent`: `object<string, array<object>>` (no declared fields).

**Returns (as documented):**

```text
Dictionary with results grouped by entity type
```

---

### 5.10 Cache administration (5 tools)

Inspect and control the local encrypted cache.

<a id="cache_task_get_status"></a>

#### `cache_task_get_status`

📖 Get status of a background cache task (read-only, safe for unsupervised use)

**Title:** Get Cache Task Status  
**Safety level:** `safe`  
**Category:** `cache`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Retrieve the current status, progress, and result/error information for a
specific background cache task.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `task_id` | `string` | yes | — | The unique identifier for the cache task. |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
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
```

**Raises:**

```text
ValueError: If task_id is not found.
```

---

<a id="cache_task_list"></a>

#### `cache_task_list`

📖 List background cache tasks (read-only, safe for unsupervised use)

**Title:** List Cache Tasks  
**Safety level:** `safe`  
**Category:** `cache`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Retrieve a list of background cache tasks, optionally filtered by account
and status.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `account_id` | `string \| null` | no | `null` | Optional account ID to filter tasks (None = all accounts). |
| `status` | `string \| null` | no | `null` | Optional status filter (queued, running, completed, failed). |
| `limit` | `integer` | no | `50` | Maximum number of tasks to return (default: 50). |

**Output:** `structuredContent.result`: `array<object>` (the tool's return value, wrapped under `result`).

**Returns (as documented):**

```text
List of task dictionaries, each containing:
- task_id: Task identifier
- status: Current status
- operation: Operation type
- account_id: Associated account
- priority: Task priority (1=highest, 10=lowest)
- created_at: Creation timestamp
- updated_at: Last update timestamp
- retry_count: Number of retries
```

**Example:**

```text
# List all tasks for a specific account
tasks = cache_task_list(account_id="user@example.com")

# List only failed tasks
failed = cache_task_list(status="failed")

# List recent queued tasks
queued = cache_task_list(status="queued", limit=10)
```

---

<a id="cache_get_stats"></a>

#### `cache_get_stats`

📖 Get cache statistics and performance metrics (read-only, safe for unsupervised use)

**Title:** Get Cache Statistics  
**Safety level:** `safe`  
**Category:** `cache`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Retrieve comprehensive statistics about the cache system including size,
hit rates, entry counts, and performance metrics.

_No parameters._

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Dictionary containing cache statistics:
- total_entries: Total number of cached entries
- total_bytes: Total size of cache in bytes
- total_size_mb: Total size in megabytes
- size_percentage: Percentage of max cache size used
- total_hits: Number of cache hits
- hit_rate: None until cache misses are tracked
- entries_by_resource_type: Count of entries per resource type
- average_entry_size_bytes: Average size per entry
- compressed_entries: Number of compressed entries
- compression_ratio: Average compression ratio
- oldest_entry_age_hours: Age of oldest entry in hours
- cleanup_triggered: Whether cleanup threshold has been reached
- last_cleanup: Timestamp of last cleanup operation
```

**Example:**

```text
stats = cache_get_stats()
print(f"Cache size: {stats['total_size_mb']:.2f} MB")
print(f"Size used: {stats['size_percentage']:.1f}%")
```

---

<a id="cache_invalidate"></a>

#### `cache_invalidate`

✏️ Invalidate cache entries matching a pattern (requires user confirmation recommended)

**Title:** Invalidate Cache Entries  
**Safety level:** `moderate`  
**Category:** `cache`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Delete cache entries that match the specified pattern. This is useful for
forcing fresh data retrieval or clearing stale cache entries.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `pattern` | `string` | yes | — | Pattern to match cache keys (supports wildcards): - "*" matches any characters within a segment - Use "email_list:*" to invalidate all email lists - Use "email_list:account@example.com:*" for specific account - Use "folder_get_tree:*" to invalidate all folder trees |
| `account_id` | `string \| null` | no | `null` | Optional account ID to scope invalidation (None = all accounts). |
| `reason` | `string` | no | `"manual_invalidation"` | Reason for invalidation (for audit logging). |

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Dictionary containing:
- entries_deleted: Number of cache entries deleted
- pattern: Pattern that was used
- account_id: Account ID filter (if specified)
- reason: Invalidation reason
- timestamp: When invalidation occurred
```

**Examples:**

```text
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
```

---

<a id="cache_warming_status"></a>

#### `cache_warming_status`

📖 Get cache warming status and progress (read-only, safe for unsupervised use)

**Title:** Get Cache Warming Status  
**Safety level:** `safe`  
**Category:** `cache`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Retrieve the current status of the cache warming process, including progress,
completion estimates, and statistics.

_No parameters._

**Output:** `structuredContent`: `object` (no declared fields).

**Returns (as documented):**

```text
Dictionary containing warming status:
- is_warming: Whether cache warming is currently active
- started_at: When warming started (if active)
- completed_at: When warming completed (if finished)
- operations_total: Total number of warming operations
- operations_completed: Number of completed operations
- operations_failed: Number of failed operations
- progress_percent: Progress percentage (0-100)
- estimated_completion: Estimated completion time
- accounts_warmed: Number of accounts warmed
- operations_by_type: Breakdown of operations by type
- status: Current status message
```

**Example:**

```text
status = cache_warming_status()
if status['is_warming']:
    print(f"Warming in progress: {status['progress_percent']:.1f}%")
else:
    print("Cache warming complete or not started")
```

---

### 5.11 Server (1 tools)

Server metadata.

<a id="server_get_version"></a>

#### `server_get_version`

📖 Get the version of the m365-mcp server (read-only, safe for unsupervised use)

**Title:** Get Server Version  
**Safety level:** `safe`  
**Category:** `server`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Requires `confirm=true`:** no

Returns the current version of the m365-mcp server that is running.
Useful for diagnostics, troubleshooting, and ensuring compatibility.

_No parameters._

**Output:** `structuredContent`: `object<string, string>` (no declared fields).

**Returns (as documented):**

```text
Dictionary containing:
- version: The semantic version string (e.g., "0.1.3")
- package: The package name ("m365-mcp")
```

**Example:**

```text
>>> server_get_version()
{"version": "0.1.3", "package": "m365-mcp"}
```

---
