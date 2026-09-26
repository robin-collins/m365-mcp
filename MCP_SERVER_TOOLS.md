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

Legend: **Tier** = toolset that exposes the tool (`M365_MCP_TOOLSETS`), **RO** = `readOnlyHint`, **Destr.** = `destructiveHint`, **Idem.** = `idempotentHint`, **Confirm** = `meta.confirm` (`always`, `conditional` or `never`).

| # | Tool | Title | Tier | Safety | RO | Destr. | Idem. | Confirm |
|---|---|---|---|---|---|---|---|---|
| 1 | [`m365_list`](#m365_list) | List Items | core | safe | yes | no | yes | never |
| 2 | [`m365_get`](#m365_get) | Get Item | core | safe | yes | no | yes | never |
| 3 | [`m365_search`](#m365_search) | Search | core | safe | yes | no | yes | never |
| 4 | [`m365_get_content`](#m365_get_content) | Get Content | core | moderate | no | no | yes | never |
| 5 | [`m365_create`](#m365_create) | Create Item | core | moderate | no | no | no | never |
| 6 | [`m365_update`](#m365_update) | Update Item | core | moderate | no | no | yes | never |
| 7 | [`m365_move`](#m365_move) | Move Item | core | moderate | no | no | no | never |
| 8 | [`m365_delete`](#m365_delete) | Delete Item | core | critical | no | yes | no | always |
| 9 | [`email_create_draft`](#email_create_draft) | Create Email Draft | core | moderate | no | no | no | never |
| 10 | [`email_send`](#email_send) | Send Email | core | dangerous | no | no | no | always |
| 11 | [`email_reply`](#email_reply) | Reply to Email | core | dangerous | no | no | no | always |
| 12 | [`email_forward`](#email_forward) | Forward Email | core | dangerous | no | no | no | always |
| 13 | [`email_folder_mark_all_read`](#email_folder_mark_all_read) | Mark Folder Read | extended | moderate | no | no | yes | never |
| 14 | [`email_folder_empty`](#email_folder_empty) | Empty Mail Folder | extended | critical | no | yes | yes | always |
| 15 | [`email_rule_manage`](#email_rule_manage) | Manage Inbox Rule | extended | dangerous | no | no | no | conditional |
| 16 | [`calendar_create_event`](#calendar_create_event) | Create Event | core | dangerous | no | no | no | conditional |
| 17 | [`calendar_update_event`](#calendar_update_event) | Update Event | core | dangerous | no | no | yes | conditional |
| 18 | [`calendar_respond`](#calendar_respond) | Respond to Invitation | core | dangerous | no | no | no | conditional |
| 19 | [`calendar_find_availability`](#calendar_find_availability) | Find Free Time | core | safe | yes | no | yes | never |
| 20 | [`calendar_forward`](#calendar_forward) | Forward Invitation | extended | dangerous | no | no | no | always |
| 21 | [`drive_upload`](#drive_upload) | Upload File | extended | moderate | no | no | no | never |
| 22 | [`drive_copy`](#drive_copy) | Copy File | extended | moderate | no | no | no | never |
| 23 | [`drive_share`](#drive_share) | Share File | extended | dangerous | no | no | no | always |
| 24 | [`account_list`](#account_list) | List Accounts | admin | safe | yes | no | yes | never |
| 25 | [`account_auth_begin`](#account_auth_begin) | Start Sign-in | admin | moderate | no | no | no | never |
| 26 | [`account_auth_complete`](#account_auth_complete) | Finish Sign-in | admin | moderate | no | no | yes | never |
| 27 | [`admin_cache_get`](#admin_cache_get) | Cache Status | admin | safe | yes | no | yes | never |
| 28 | [`admin_cache_invalidate`](#admin_cache_invalidate) | Clear Cache | admin | moderate | no | no | yes | never |
| 29 | [`admin_server_info`](#admin_server_info) | Server Info | admin | safe | yes | no | yes | never |

## 5. Tool reference

### 5.0 Cache lifetimes

Reads through `m365_list` and `m365_get` are cached per account and resource. Fresh entries are served with no Graph call; stale entries are served until they expire.

| Resource | Fresh (min) | Expires (min) |
|---|---|---|
| `email` | 2 | 10 |
| `email_folder` | 5 | 30 |
| `email_rule` | 15 | 60 |
| `event` | 5 | 30 |
| `calendar` | 30 | 120 |
| `contact` | 20 | 120 |
| `contact_folder` | 30 | 240 |
| `drive_item` | 10 | 60 |

### 5.1 Generic resource tools (8 tools)

List, search, read, create, update, move and delete any mail, calendar, contact or OneDrive resource by `resource`.

<a id="m365_list"></a>

#### `m365_list`

Browse items of one type in a known place: emails in a mail folder, events in a time window, calendars, contacts, contact folders, mail folders, inbox rules, or files in a OneDrive folder (optionally as a tree). Use this when you know where to look. Use m365_search to find items by text, and m365_get when you already have an ID. Returns compact items plus next_cursor for more.

**Title:** List Items  
**Tier:** `core`  
**Safety level:** `safe`  
**Category:** `m365`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Confirm:** `never`  
**Cache:** per-resource TTLs; `refresh=true` bypasses the cache

| Parameter | Type | Required | Default | Limits | Description |
|---|---|---|---|---|---|
| `resource` | `"email" \| "email_folder" \| "email_rule" \| "event" \| "calendar" \| "contact" \| "contact_folder" \| "drive_item"` | yes | — | — | Type of item to list. |
| `account_id` | `string` | no | — | min length 1, max length 320 | Account ID or email address. Omit when only one account is signed in. |
| `container_id` | `string` | no | — | min length 1, max length 1024 | Where to list. email: mail folder ID or alias (default inbox). email_folder: parent folder (default: top level). event: calendar ID (default: your default calendar). contact: contact folder ID (default: all contacts). drive_item: parent folder ID (default: OneDrive root). Not used for calendar, contact_folder and email_rule. |
| `path` | `string` | no | — | min length 1, max length 2048 | drive_item only: OneDrive folder path instead of container_id, e.g. /Documents/Tax. |
| `email_filter` | `object` | no | — | — | email only: filters applied by Microsoft 365 (all must match). |
| `start` | `string` | no | — | — | event only: window start (default now). RFC 3339 with offset. |
| `end` | `string` | no | — | — | event only: window end (default start + 7 days; at most 366 days after start). |
| `item_type` | `"file" \| "folder" \| "all"` | no | `"all"` | — | drive_item only: which kinds of item to return. |
| `recursive` | `boolean` | no | `false` | — | email_folder and drive_item only: return a nested tree of folders instead of one level. |
| `max_depth` | `integer` | no | `3` | min 1, max 10 | Tree depth when recursive=true. |
| `include_hidden` | `boolean` | no | `false` | — | email_folder only: include hidden folders. |
| `limit` | `integer` | no | `20` | min 1, max 50 | Maximum number of items to return. |
| `cursor` | `string` | no | — | min length 1, max length 8192 | next_cursor from the previous page; keep all other arguments the same. |
| `refresh` | `boolean` | no | `false` | — | Bypass the cache and fetch fresh data. |

**Output** (`structuredContent`): `resource`, `items`, `next_cursor`, `has_more`, `summary`.

---

<a id="m365_get"></a>

#### `m365_get`

Read one item whose ID you already have: an email with its body, an event with attendees, a contact, a mail or contact folder, an inbox rule, a calendar, a OneDrive item's details, or the status of a copy started with drive_copy (resource='operation'). Use m365_list or m365_search to find IDs. Use m365_get_content to download files or attachments. Returns the item.

**Title:** Get Item  
**Tier:** `core`  
**Safety level:** `safe`  
**Category:** `m365`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Confirm:** `never`  
**Cache:** per-resource TTLs; `refresh=true` bypasses the cache

| Parameter | Type | Required | Default | Limits | Description |
|---|---|---|---|---|---|
| `resource` | `"email" \| "email_folder" \| "email_rule" \| "event" \| "calendar" \| "contact" \| "contact_folder" \| "drive_item" \| "operation"` | yes | — | — | Type of item. |
| `account_id` | `string` | no | — | min length 1, max length 320 | Account ID or email address. Omit when only one account is signed in. |
| `id` | `string` | no | — | min length 1, max length 1024 | Item ID from a previous result (for operation: the operation_id). Aliases are accepted for email_folder, calendar (default) and drive_item (root). |
| `path` | `string` | no | — | min length 1, max length 2048 | drive_item only: OneDrive path instead of id. |
| `include_body` | `boolean` | no | `true` | — | email and event: include the body text. |
| `body_max_chars` | `integer` | no | `20000` | min 500, max 100000 | email and event: truncate the body after this many characters. |
| `refresh` | `boolean` | no | `false` | — | Bypass the cache and fetch fresh data. |

**Output** (`structuredContent`): `resource`, `item`, `summary`.

---

<a id="m365_search"></a>

#### `m365_search`

Find emails, events, contacts or OneDrive files by free text when you do not know where they are. Search one type or several at once. Do not use it to browse a folder (m365_list) or open a known ID (m365_get). Returns matching items labelled by resource, newest first, plus next_cursor.

**Title:** Search  
**Tier:** `core`  
**Safety level:** `safe`  
**Category:** `m365`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Confirm:** `never`

| Parameter | Type | Required | Default | Limits | Description |
|---|---|---|---|---|---|
| `query` | `string` | yes | — | min length 1, max length 256 | Words to search for. Plain text; the server handles quoting. |
| `resources` | `array<"email" \| "event" \| "contact" \| "drive_item">` | no | — | min items 1, max items 4 | Which item types to search. Default: all four. |
| `account_id` | `string` | no | — | min length 1, max length 320 | Account ID or email address. Omit when only one account is signed in. |
| `email_folder_id` | `string` | no | — | min length 1, max length 1024 | Mail folder ID, or one of the aliases inbox, sent, drafts, deleted, junk, archive. |
| `event_start` | `string` | no | — | — | Event search window start (default: 90 days ago). |
| `event_end` | `string` | no | — | — | Event search window end (default: 365 days ahead). |
| `limit` | `integer` | no | `20` | min 1, max 50 | Maximum number of items to return. |
| `cursor` | `string` | no | — | min length 1, max length 8192 | next_cursor from the previous page; keep all other arguments the same. |

**Output** (`structuredContent`): `query`, `items`, `next_cursor`, `has_more`, `summary`.

---

<a id="m365_get_content"></a>

#### `m365_get_content`

Get the content of an item rather than its details: save a OneDrive file or an email attachment to a local file (mode='download'), get a temporary download link for a OneDrive file (mode='download_url'), or export a contact as a vCard (mode='vcard'). Writes to the local disk only inside the allowed folders. Use m365_get for item details.

**Title:** Get Content  
**Tier:** `core`  
**Safety level:** `moderate`  
**Category:** `m365`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Confirm:** `never`

| Parameter | Type | Required | Default | Limits | Description |
|---|---|---|---|---|---|
| `resource` | `"drive_item" \| "email" \| "contact"` | yes | — | — | Type of item. |
| `account_id` | `string` | no | — | min length 1, max length 320 | Account ID or email address. Omit when only one account is signed in. |
| `id` | `string` | yes | — | min length 1, max length 1024 | OneDrive item ID, email ID or contact ID. |
| `mode` | `"download" \| "download_url" \| "vcard"` | yes | — | — | download: drive_item file or email attachment to save_path. download_url: drive_item file only. vcard: contact only. |
| `attachment_id` | `string` | no | — | min length 1, max length 1024 | email + download only: attachment ID from m365_get(resource='email'). |
| `save_path` | `string` | no | — | min length 1, max length 4096 | Local file path inside the server's allowed folders. Hidden and secret files are refused. |
| `overwrite` | `boolean` | no | `false` | — | Replace save_path if it already exists. |

**Output** (`structuredContent`): `resource`, `id`, `mode`, `saved_path`, `size`, `mime_type`, `download_url`, `vcard`, `summary`.

---

<a id="m365_create"></a>

#### `m365_create`

Create a mail folder, calendar, contact, contact folder or OneDrive folder. Supply the sub-object that matches resource. Not for emails (email_create_draft), events (calendar_create_event), inbox rules (email_rule_manage) or uploading files (drive_upload). Returns the created item.

**Title:** Create Item  
**Tier:** `core`  
**Safety level:** `moderate`  
**Category:** `m365`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Confirm:** `never`

| Parameter | Type | Required | Default | Limits | Description |
|---|---|---|---|---|---|
| `resource` | `"email_folder" \| "calendar" \| "contact" \| "contact_folder" \| "drive_item"` | yes | — | — | Type of item to create. |
| `account_id` | `string` | no | — | min length 1, max length 320 | Account ID or email address. Omit when only one account is signed in. |
| `email_folder` | `object` | no | — | — | Required when resource='email_folder'. |
| `calendar` | `object` | no | — | — | Required when resource='calendar'. |
| `contact` | `object` | no | — | — | Required when resource='contact'. |
| `contact_folder` | `object` | no | — | — | Required when resource='contact_folder'. |
| `drive_folder` | `object` | no | — | — | Required when resource='drive_item' (creates a folder). |

**Output** (`structuredContent`): `resource`, `item`, `summary`.

---

<a id="m365_update"></a>

#### `m365_update`

Change properties of an existing email, mail folder, contact or OneDrive item: mark read or unread, flag, set importance or categories, Focused/Other, rename folders and files, or edit contact details. Supply the *_changes object that matches resource. Not for events (calendar_update_event), inbox rules (email_rule_manage) or file contents (drive_upload). Returns the changed field names.

**Title:** Update Item  
**Tier:** `core`  
**Safety level:** `moderate`  
**Category:** `m365`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Confirm:** `never`

| Parameter | Type | Required | Default | Limits | Description |
|---|---|---|---|---|---|
| `resource` | `"email" \| "email_folder" \| "contact" \| "drive_item"` | yes | — | — | Type of item. |
| `account_id` | `string` | no | — | min length 1, max length 320 | Account ID or email address. Omit when only one account is signed in. |
| `id` | `string` | yes | — | min length 1, max length 1024 | Item ID. |
| `email_changes` | `object` | no | — | — | Required when resource='email'. |
| `email_folder_changes` | `object` | no | — | — | Required when resource='email_folder'. |
| `contact_changes` | `object` | no | — | — | Required when resource='contact'. Only supplied fields change; lists replace the existing list. |
| `drive_item_changes` | `object` | no | — | — | Required when resource='drive_item'. |

**Output** (`structuredContent`): `resource`, `id`, `status`, `changed_fields`, `summary`.

---

<a id="m365_move"></a>

#### `m365_move`

Move an email, mail folder, contact or OneDrive item to another folder. Moving an email to 'archive' archives it; moving a contact places it in a contact folder. Moved emails and contacts get a new ID, which is returned: use it for later calls.

**Title:** Move Item  
**Tier:** `core`  
**Safety level:** `moderate`  
**Category:** `m365`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Confirm:** `never`

| Parameter | Type | Required | Default | Limits | Description |
|---|---|---|---|---|---|
| `resource` | `"email" \| "email_folder" \| "contact" \| "drive_item"` | yes | — | — | Type of item. |
| `account_id` | `string` | no | — | min length 1, max length 320 | Account ID or email address. Omit when only one account is signed in. |
| `id` | `string` | yes | — | min length 1, max length 1024 | Item to move. |
| `destination_id` | `string` | no | — | min length 1, max length 1024 | Destination folder. email: mail folder ID or alias (archive, inbox, junk, deleted, drafts, sent). email_folder: mail folder ID or 'root'. contact: contact folder ID or 'default'. drive_item: folder ID or 'root'. |
| `destination_path` | `string` | no | — | min length 1, max length 2048 | drive_item only: destination folder path instead of destination_id. |
| `new_name` | `string` | no | — | min length 1, max length 255 | drive_item only: rename while moving. |

**Output** (`structuredContent`): `resource`, `previous_id`, `id`, `status`, `destination_id`, `summary`.

---

<a id="m365_delete"></a>

#### `m365_delete`

Delete one email, mail folder, inbox rule, event, calendar, contact, contact folder or OneDrive item. Always requires confirm=true after the user approves. Deleting a meeting you organise sends cancellations to its attendees. OneDrive items go to the recycle bin. Returns what happened and whether it can be recovered.

**Title:** Delete Item  
**Tier:** `core`  
**Safety level:** `critical`  
**Category:** `m365`  
**Hints:** readOnlyHint=`false`, destructiveHint=`true`, idempotentHint=`false`, openWorldHint=`true`  
**Confirm:** `always` (Always required.)

| Parameter | Type | Required | Default | Limits | Description |
|---|---|---|---|---|---|
| `resource` | `"email" \| "email_folder" \| "email_rule" \| "event" \| "calendar" \| "contact" \| "contact_folder" \| "drive_item"` | yes | — | — | Type of item. |
| `account_id` | `string` | no | — | min length 1, max length 320 | Account ID or email address. Omit when only one account is signed in. |
| `id` | `string` | yes | — | min length 1, max length 1024 | Item ID. Aliases are not accepted. |
| `cancellation_message` | `string` | no | — | max length 2000 | event only: note sent with the cancellation when you organise the meeting. |
| `confirm` | `boolean` | yes | `false` | — | Must be true to delete this item; set only after the user approves. |

**Output** (`structuredContent`): `resource`, `id`, `status`, `recoverable`, `summary`.

---

### 5.2 Email (7 tools)

Compose, send, reply, forward and organise mail.

<a id="email_create_draft"></a>

#### `email_create_draft`

Create an unsent email draft to review, then send later with email_send(mode='draft'). Sends nothing. Returns the draft ID.

**Title:** Create Email Draft  
**Tier:** `core`  
**Safety level:** `moderate`  
**Category:** `email`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Confirm:** `never`

| Parameter | Type | Required | Default | Limits | Description |
|---|---|---|---|---|---|
| `account_id` | `string` | no | — | min length 1, max length 320 | Account ID or email address. Omit when only one account is signed in. |
| `to` | `array<string>` | yes | — | min items 1, max items 500 | Recipients (To). |
| `cc` | `array<string>` | no | — | max items 500 | Cc recipients. |
| `bcc` | `array<string>` | no | — | max items 500 | Bcc recipients. |
| `subject` | `string` | yes | — | min length 1, max length 998 | Subject line. |
| `body` | `string` | yes | — | max length 1000000 | Message body. |
| `body_format` | `"text" \| "html"` | no | `"text"` | — | Format of the body text you supply. |
| `attachments` | `array<string>` | no | — | max items 10 | Local files to attach: at most 10, each at most 25 MB. |
| `importance` | `"low" \| "normal" \| "high"` | no | — | — | Message importance. |

**Output** (`structuredContent`): `draft_id`, `subject`, `to`, `cc`, `bcc`, `attachment_count`, `web_link`, `summary`.

---

<a id="email_send"></a>

#### `email_send`

Send an email now: a new message (mode='new') or a draft you created earlier (mode='draft'). Requires confirm=true after the user approves the recipients and content. Cannot be undone. Never infer recipients.

**Title:** Send Email  
**Tier:** `core`  
**Safety level:** `dangerous`  
**Category:** `email`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Confirm:** `always` (Always required.)

| Parameter | Type | Required | Default | Limits | Description |
|---|---|---|---|---|---|
| `mode` | `"new" \| "draft"` | yes | — | — | Send a new message or an existing draft. |
| `account_id` | `string` | no | — | min length 1, max length 320 | Account ID or email address. Omit when only one account is signed in. |
| `to` | `array<string>` | no | — | min items 1, max items 500 | Recipients (To). |
| `cc` | `array<string>` | no | — | max items 500 | Cc recipients. |
| `bcc` | `array<string>` | no | — | max items 500 | Bcc recipients. |
| `subject` | `string` | no | — | min length 1, max length 998 | Subject line. |
| `body` | `string` | no | — | max length 1000000 | Message body. |
| `body_format` | `"text" \| "html"` | no | `"text"` | — | Format of the body text you supply. |
| `attachments` | `array<string>` | no | — | max items 10 | Local files to attach: at most 10, each at most 25 MB. |
| `importance` | `"low" \| "normal" \| "high"` | no | — | — | Message importance. |
| `save_to_sent` | `boolean` | no | `true` | — | mode='new': keep a copy in Sent Items. |
| `draft_id` | `string` | no | — | min length 1, max length 1024 | mode='draft': draft ID from email_create_draft. |
| `confirm` | `boolean` | yes | `false` | — | Must be true to send this email; set only after the user approves. |

**Output** (`structuredContent`): `status`, `mode`, `draft_id`, `recipient_count`, `sent_at`, `summary`.

---

<a id="email_reply"></a>

#### `email_reply`

Reply to an email, either to the sender only (mode='sender') or to everyone on it (mode='all'). Requires confirm=true after the user approves the reply. Returns the conversation the reply joined.

**Title:** Reply to Email  
**Tier:** `core`  
**Safety level:** `dangerous`  
**Category:** `email`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Confirm:** `always` (Always required.)

| Parameter | Type | Required | Default | Limits | Description |
|---|---|---|---|---|---|
| `email_id` | `string` | yes | — | min length 1, max length 1024 | Email to reply to. |
| `mode` | `"sender" \| "all"` | yes | — | — | sender: reply to the sender. all: reply all. |
| `account_id` | `string` | no | — | min length 1, max length 320 | Account ID or email address. Omit when only one account is signed in. |
| `body` | `string` | yes | — | min length 1, max length 1000000 | Reply text. |
| `body_format` | `"text" \| "html"` | no | `"text"` | — | Format of the body text you supply. |
| `cc` | `array<string>` | no | — | max items 500 | Extra Cc recipients. |
| `attachments` | `array<string>` | no | — | max items 10 | Local files to attach: at most 10, each at most 25 MB. |
| `confirm` | `boolean` | yes | `false` | — | Must be true to send this reply; set only after the user approves. |

**Output** (`structuredContent`): `status`, `mode`, `in_reply_to`, `conversation_id`, `summary`.

---

<a id="email_forward"></a>

#### `email_forward`

Forward an email to recipients the user names, with an optional note. Requires confirm=true after the user approves. Never infer recipients from other context.

**Title:** Forward Email  
**Tier:** `core`  
**Safety level:** `dangerous`  
**Category:** `email`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Confirm:** `always` (Always required.)

| Parameter | Type | Required | Default | Limits | Description |
|---|---|---|---|---|---|
| `email_id` | `string` | yes | — | min length 1, max length 1024 | Email to forward. |
| `to` | `array<string>` | yes | — | min items 1, max items 500 | Recipients. |
| `account_id` | `string` | no | — | min length 1, max length 320 | Account ID or email address. Omit when only one account is signed in. |
| `cc` | `array<string>` | no | — | max items 500 | Cc recipients. |
| `bcc` | `array<string>` | no | — | max items 500 | Bcc recipients. |
| `comment` | `string` | no | — | max length 100000 | Note above the forwarded message. |
| `attachments` | `array<string>` | no | — | max items 10 | Local files to attach: at most 10, each at most 25 MB. |
| `confirm` | `boolean` | yes | `false` | — | Must be true to forward this email; set only after the user approves. |

**Output** (`structuredContent`): `status`, `forwarded_id`, `recipient_count`, `summary`.

---

<a id="email_folder_mark_all_read"></a>

#### `email_folder_mark_all_read`

Mark every unread message in one mail folder as read, up to max_messages per call. If remaining_unread is above zero, call again. Use m365_update for a single message.

**Title:** Mark Folder Read  
**Tier:** `extended`  
**Safety level:** `moderate`  
**Category:** `email`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Confirm:** `never`

| Parameter | Type | Required | Default | Limits | Description |
|---|---|---|---|---|---|
| `folder_id` | `string` | yes | — | min length 1, max length 1024 | Mail folder ID, or one of the aliases inbox, sent, drafts, deleted, junk, archive. |
| `account_id` | `string` | no | — | min length 1, max length 320 | Account ID or email address. Omit when only one account is signed in. |
| `max_messages` | `integer` | no | `1000` | min 1, max 5000 | Most messages to change in this call. |

**Output** (`structuredContent`): `folder_id`, `marked`, `remaining_unread`, `summary`.

---

<a id="email_folder_empty"></a>

#### `email_folder_empty`

Delete all messages in one mail folder, such as Junk Email or Deleted Items, up to max_messages per call. Subfolders are kept. Requires confirm=true after the user approves. Deleted messages cannot be restored with these tools.

**Title:** Empty Mail Folder  
**Tier:** `extended`  
**Safety level:** `critical`  
**Category:** `email`  
**Hints:** readOnlyHint=`false`, destructiveHint=`true`, idempotentHint=`true`, openWorldHint=`true`  
**Confirm:** `always` (Always required.)

| Parameter | Type | Required | Default | Limits | Description |
|---|---|---|---|---|---|
| `folder_id` | `string` | yes | — | min length 1, max length 1024 | Mail folder ID, or one of the aliases inbox, sent, drafts, deleted, junk, archive. |
| `account_id` | `string` | no | — | min length 1, max length 320 | Account ID or email address. Omit when only one account is signed in. |
| `max_messages` | `integer` | no | `1000` | min 1, max 5000 | Most messages to delete in this call. |
| `confirm` | `boolean` | yes | `false` | — | Must be true to delete every message in this folder; set only after the user approves. |

**Output** (`structuredContent`): `folder_id`, `deleted`, `remaining`, `summary`.

---

<a id="email_rule_manage"></a>

#### `email_rule_manage`

Create, change, enable or disable, or reorder an Inbox rule. Rules that forward, redirect or delete mail require confirm=true because they act silently on future mail. Read rules with m365_list or m365_get; delete one with m365_delete. Returns the rule.

**Title:** Manage Inbox Rule  
**Tier:** `extended`  
**Safety level:** `dangerous`  
**Category:** `email`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Confirm:** `conditional` (Required when the resulting rule forwards, redirects or deletes mail (forward_to, forward_as_attachment_to, redirect_to, delete, permanent_delete).)

| Parameter | Type | Required | Default | Limits | Description |
|---|---|---|---|---|---|
| `action` | `"create" \| "update" \| "set_enabled" \| "reorder"` | yes | — | — | What to do. |
| `account_id` | `string` | no | — | min length 1, max length 320 | Account ID or email address. Omit when only one account is signed in. |
| `rule_id` | `string` | no | — | min length 1, max length 1024 | Existing rule (update, set_enabled, reorder). |
| `rule` | `object` | no | — | — | Rule definition. create requires display_name, conditions and actions; update applies only the supplied fields. |
| `is_enabled` | `boolean` | no | — | — | set_enabled: turn the rule on (true) or off (false). |
| `position` | `"top" \| "bottom" \| "up" \| "down" \| "before" \| "after"` | no | — | — | reorder: new position. before/after need relative_to_rule_id. |
| `relative_to_rule_id` | `string` | no | — | min length 1, max length 1024 | reorder with before/after: the other rule. |
| `confirm` | `boolean` | no | `false` | — | Must be true to save a rule that forwards, redirects or deletes mail; set only after the user approves. |

**Output** (`structuredContent`): `action`, `rule`, `summary`.

---

### 5.3 Calendar (5 tools)

Events, invitations, responses and availability.

<a id="calendar_create_event"></a>

#### `calendar_create_event`

Add an event to your calendar. With attendees, Outlook emails them an invitation, so confirm=true is then required. Without attendees it is a private appointment and needs no confirmation. Returns the event.

**Title:** Create Event  
**Tier:** `core`  
**Safety level:** `dangerous`  
**Category:** `calendar`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Confirm:** `conditional` (Required when attendees is non-empty (Outlook emails each attendee an invitation).)

| Parameter | Type | Required | Default | Limits | Description |
|---|---|---|---|---|---|
| `account_id` | `string` | no | — | min length 1, max length 320 | Account ID or email address. Omit when only one account is signed in. |
| `subject` | `string` | yes | — | min length 1, max length 255 | Title. |
| `start` | `string` | yes | — | — | RFC 3339 date-time with offset, e.g. 2026-10-01T09:00:00+09:30. |
| `end` | `string` | yes | — | — | RFC 3339 date-time with offset, e.g. 2026-10-01T09:00:00+09:30. |
| `time_zone` | `string` | no | — | min length 1, max length 64 | IANA time-zone name, e.g. Australia/Adelaide. Defaults to the mailbox time zone. |
| `is_all_day` | `boolean` | no | — | — | All-day event (start and end at midnight in time_zone). |
| `location` | `string` | no | — | max length 255 | Location text. |
| `body` | `string` | no | — | max length 100000 | Description. |
| `body_format` | `"text" \| "html"` | no | `"text"` | — | Format of the body text you supply. |
| `reminder_minutes` | `integer` | no | — | min 0, max 40320 | Reminder before start, in minutes. |
| `show_as` | `"free" \| "tentative" \| "busy" \| "oof" \| "workingElsewhere"` | no | — | — | How the time shows in your calendar. |
| `attendees` | `array<object>` | no | — | max items 500 | People to invite. |
| `calendar_id` | `string` | no | — | min length 1, max length 1024 | Calendar ID (default: your default calendar). |
| `confirm` | `boolean` | no | `false` | — | Must be true to send invitations to the attendees; set only after the user approves. |

**Output** (`structuredContent`): `event`, `invitations_sent`, `summary`.

---

<a id="calendar_update_event"></a>

#### `calendar_update_event`

Change an event's time, title, location, description, reminder or attendees. If the event has attendees, or you add some, Outlook emails them an update, so confirm=true is then required. Returns the updated event.

**Title:** Update Event  
**Tier:** `core`  
**Safety level:** `dangerous`  
**Category:** `calendar`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Confirm:** `conditional` (Required when the event has attendees or the change adds any (Outlook emails them an update).)

| Parameter | Type | Required | Default | Limits | Description |
|---|---|---|---|---|---|
| `event_id` | `string` | yes | — | min length 1, max length 1024 | Event to change. |
| `account_id` | `string` | no | — | min length 1, max length 320 | Account ID or email address. Omit when only one account is signed in. |
| `changes` | `object` | yes | — | — | Fields to change (at least one). |
| `confirm` | `boolean` | no | `false` | — | Must be true to send updates to the attendees; set only after the user approves. |

**Output** (`structuredContent`): `event`, `attendees_notified`, `changed_fields`, `summary`.

---

<a id="calendar_respond"></a>

#### `calendar_respond`

Accept, tentatively accept or decline a meeting invitation, optionally proposing a new time (with tentative or decline). When a response is emailed to the organiser (the default), confirm=true is required.

**Title:** Respond to Invitation  
**Tier:** `core`  
**Safety level:** `dangerous`  
**Category:** `calendar`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Confirm:** `conditional` (Required when send_response is true (the organiser is emailed).)

| Parameter | Type | Required | Default | Limits | Description |
|---|---|---|---|---|---|
| `event_id` | `string` | yes | — | min length 1, max length 1024 | Invitation's event ID. |
| `action` | `"accept" \| "tentative" \| "decline"` | yes | — | — | Your response. |
| `account_id` | `string` | no | — | min length 1, max length 320 | Account ID or email address. Omit when only one account is signed in. |
| `comment` | `string` | no | — | max length 2000 | Message to the organiser. |
| `send_response` | `boolean` | no | `true` | — | Email the response to the organiser. |
| `proposed_start` | `string` | no | — | — | Proposed new start (tentative or decline only). |
| `proposed_end` | `string` | no | — | — | Proposed new end (tentative or decline only). |
| `confirm` | `boolean` | no | `false` | — | Must be true to send this response to the organiser; set only after the user approves. |

**Output** (`structuredContent`): `event_id`, `action`, `response_sent`, `proposed_start`, `proposed_end`, `summary`.

---

<a id="calendar_find_availability"></a>

#### `calendar_find_availability`

Show when you are busy in your own calendar during a time range and, given slot_minutes, suggest free slots of that length within your working hours. Personal accounts cannot see other people's availability, so this covers your calendar only.

**Title:** Find Free Time  
**Tier:** `core`  
**Safety level:** `safe`  
**Category:** `calendar`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Confirm:** `never`

| Parameter | Type | Required | Default | Limits | Description |
|---|---|---|---|---|---|
| `start` | `string` | yes | — | — | RFC 3339 date-time with offset, e.g. 2026-10-01T09:00:00+09:30. |
| `end` | `string` | yes | — | — | Range end; at most 62 days after start. |
| `account_id` | `string` | no | — | min length 1, max length 320 | Account ID or email address. Omit when only one account is signed in. |
| `time_zone` | `string` | no | — | min length 1, max length 64 | IANA time-zone name, e.g. Australia/Adelaide. Defaults to the mailbox time zone. |
| `slot_minutes` | `integer` | no | — | min 15, max 480 | Length of free slots to suggest. |
| `working_hours_only` | `boolean` | no | `true` | — | Only suggest slots inside your Outlook working hours. |
| `min_gap_minutes` | `integer` | no | `0` | min 0, max 120 | Buffer to keep before and after busy time. |
| `max_slots` | `integer` | no | `10` | min 1, max 50 | Most free slots to return. |

**Output** (`structuredContent`): `time_zone`, `busy`, `free_slots`, `working_hours`, `summary`.

---

<a id="calendar_forward"></a>

#### `calendar_forward`

Forward a meeting invitation to people the user names, with an optional note. Requires confirm=true after the user approves.

**Title:** Forward Invitation  
**Tier:** `extended`  
**Safety level:** `dangerous`  
**Category:** `calendar`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Confirm:** `always` (Always required.)

| Parameter | Type | Required | Default | Limits | Description |
|---|---|---|---|---|---|
| `event_id` | `string` | yes | — | min length 1, max length 1024 | Event to forward. |
| `to` | `array<string>` | yes | — | min items 1, max items 100 | Recipients. |
| `account_id` | `string` | no | — | min length 1, max length 320 | Account ID or email address. Omit when only one account is signed in. |
| `comment` | `string` | no | — | max length 2000 | Note to include. |
| `confirm` | `boolean` | yes | `false` | — | Must be true to forward this invitation; set only after the user approves. |

**Output** (`structuredContent`): `event_id`, `status`, `recipient_count`, `summary`.

---

### 5.4 OneDrive (3 tools)

Upload, copy and share OneDrive files.

<a id="drive_upload"></a>

#### `drive_upload`

Upload a local file to OneDrive, as a new file (parent_id or parent_path) or by replacing an existing file's contents (item_id). Reads from the local disk, inside the allowed folders only. Returns the OneDrive item.

**Title:** Upload File  
**Tier:** `extended`  
**Safety level:** `moderate`  
**Category:** `drive`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Confirm:** `never`

| Parameter | Type | Required | Default | Limits | Description |
|---|---|---|---|---|---|
| `local_path` | `string` | yes | — | min length 1, max length 4096 | Local file path inside the server's allowed folders. Hidden and secret files are refused. |
| `account_id` | `string` | no | — | min length 1, max length 320 | Account ID or email address. Omit when only one account is signed in. |
| `parent_id` | `string` | no | — | min length 1, max length 1024 | New file: destination folder ID ('root' allowed). |
| `parent_path` | `string` | no | — | min length 1, max length 2048 | New file: destination folder path, e.g. /Documents. |
| `name` | `string` | no | — | min length 1, max length 255 | New file: name in OneDrive (default: local file name). |
| `item_id` | `string` | no | — | min length 1, max length 1024 | Replace the contents of this existing file. |
| `if_exists` | `"fail" \| "replace" \| "rename"` | no | `"fail"` | — | New file: what to do if the name is taken. |

**Output** (`structuredContent`): `item`, `status`, `summary`.

---

<a id="drive_copy"></a>

#### `drive_copy`

Copy a OneDrive file or folder to another folder. Copying runs in the background: this returns an operation_id to check with m365_get(resource='operation').

**Title:** Copy File  
**Tier:** `extended`  
**Safety level:** `moderate`  
**Category:** `drive`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Confirm:** `never`

| Parameter | Type | Required | Default | Limits | Description |
|---|---|---|---|---|---|
| `item_id` | `string` | yes | — | min length 1, max length 1024 | File or folder to copy. |
| `account_id` | `string` | no | — | min length 1, max length 320 | Account ID or email address. Omit when only one account is signed in. |
| `destination_id` | `string` | no | — | min length 1, max length 1024 | Destination folder ID ('root' allowed). |
| `destination_path` | `string` | no | — | min length 1, max length 2048 | Destination folder path instead of destination_id. |
| `new_name` | `string` | no | — | min length 1, max length 255 | Name for the copy (default: same name). |

**Output** (`structuredContent`): `operation_id`, `status`, `summary`.

---

<a id="drive_share"></a>

#### `drive_share`

Share a OneDrive file or folder by link (mode='link') or by inviting named people (mode='invite'). A view or edit link works for anyone who has it. Always requires confirm=true after the user approves who gets access. Returns the link or the invitation results.

**Title:** Share File  
**Tier:** `extended`  
**Safety level:** `dangerous`  
**Category:** `drive`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Confirm:** `always` (Always required.)

| Parameter | Type | Required | Default | Limits | Description |
|---|---|---|---|---|---|
| `item_id` | `string` | yes | — | min length 1, max length 1024 | File or folder to share (not the OneDrive root). |
| `mode` | `"link" \| "invite"` | yes | — | — | Share by link or invite specific people. |
| `account_id` | `string` | no | — | min length 1, max length 320 | Account ID or email address. Omit when only one account is signed in. |
| `link_type` | `"view" \| "edit" \| "embed"` | no | — | — | link: view (read-only), edit, or embed (files only). |
| `recipients` | `array<string>` | no | — | min items 1, max items 50 | invite: people to share with. |
| `role` | `"read" \| "write"` | no | — | — | invite: access level. |
| `message` | `string` | no | — | max length 2000 | invite: note in the invitation email. |
| `send_invitation` | `boolean` | no | `true` | — | invite: email the recipients. |
| `require_sign_in` | `boolean` | no | `true` | — | invite: recipients must sign in. |
| `password` | `string` | no | — | min length 4, max length 256 | Optional password for the link or invitation. |
| `expires_at` | `string` | no | — | — | Optional expiry (invite expiry needs a premium OneDrive). |
| `confirm` | `boolean` | yes | `false` | — | Must be true to grant this access; set only after the user approves. |

**Output** (`structuredContent`): `mode`, `permission_ids`, `link_url`, `created`, `recipients`, `summary`.

---

### 5.5 Accounts (3 tools)

Discover signed-in accounts and add new ones.

<a id="account_list"></a>

#### `account_list`

List the Microsoft accounts signed in to this server. Needed only when more than one account is signed in, to choose account_id.

**Title:** List Accounts  
**Tier:** `admin`  
**Safety level:** `safe`  
**Category:** `account`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Confirm:** `never`

_No parameters._

**Output** (`structuredContent`): `accounts`, `summary`.

---

<a id="account_auth_begin"></a>

#### `account_auth_begin`

Start signing in a personal Microsoft account. Returns a web address and code for the user to enter, and an auth_session_id to pass to account_auth_complete. Prefer `uv run authenticate.py` when available.

**Title:** Start Sign-in  
**Tier:** `admin`  
**Safety level:** `moderate`  
**Category:** `account`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`false`, openWorldHint=`true`  
**Confirm:** `never`

_No parameters._

**Output** (`structuredContent`): `auth_session_id`, `verification_url`, `user_code`, `expires_in`, `summary`.

---

<a id="account_auth_complete"></a>

#### `account_auth_complete`

Finish a sign-in started with account_auth_begin, after the user has entered the code. Returns pending (try again shortly) or the signed-in account. Work or school accounts are rejected.

**Title:** Finish Sign-in  
**Tier:** `admin`  
**Safety level:** `moderate`  
**Category:** `account`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Confirm:** `never`

| Parameter | Type | Required | Default | Limits | Description |
|---|---|---|---|---|---|
| `auth_session_id` | `string` | yes | — | min length 1, max length 128 | From account_auth_begin. |

**Output** (`structuredContent`): `status`, `account`, `summary`.

---

### 5.6 Administration (3 tools)

Inspect and control the cache and the server.

<a id="admin_cache_get"></a>

#### `admin_cache_get`

Inspect the local encrypted cache: overall statistics (view='stats'), background tasks (view='tasks'), one task (view='task') or cache warming progress (view='warming').

**Title:** Cache Status  
**Tier:** `admin`  
**Safety level:** `safe`  
**Category:** `admin`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Confirm:** `never`

| Parameter | Type | Required | Default | Limits | Description |
|---|---|---|---|---|---|
| `view` | `"stats" \| "tasks" \| "task" \| "warming"` | yes | — | — | What to show. |
| `task_id` | `string` | no | — | min length 1, max length 128 | view='task': task ID. |
| `status` | `"queued" \| "running" \| "completed" \| "failed"` | no | — | — | view='tasks': filter by status. |
| `account_id` | `string` | no | — | min length 1, max length 320 | Account ID or email address. Omit when only one account is signed in. |
| `limit` | `integer` | no | `50` | min 1, max 200 | view='tasks': most tasks to return. |

**Output** (`structuredContent`): `view`, `stats`, `tasks`, `warming`, `summary`.

---

<a id="admin_cache_invalidate"></a>

#### `admin_cache_invalidate`

Remove cached results so the next call fetches fresh data: for one resource type or all, for one account or all.

**Title:** Clear Cache  
**Tier:** `admin`  
**Safety level:** `moderate`  
**Category:** `admin`  
**Hints:** readOnlyHint=`false`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Confirm:** `never`

| Parameter | Type | Required | Default | Limits | Description |
|---|---|---|---|---|---|
| `scope` | `"email" \| "email_folder" \| "email_rule" \| "event" \| "calendar" \| "contact" \| "contact_folder" \| "drive_item" \| "all"` | yes | — | — | Resource type to clear, or all. |
| `account_id` | `string` | no | — | min length 1, max length 320 | Account ID or email address. Omit when only one account is signed in. |
| `reason` | `string` | no | — | max length 500 | Why (recorded in the audit log). |

**Output** (`structuredContent`): `scope`, `entries_removed`, `summary`.

---

<a id="admin_server_info"></a>

#### `admin_server_info`

Report the server version, supported MCP protocol versions and enabled toolsets.

**Title:** Server Info  
**Tier:** `admin`  
**Safety level:** `safe`  
**Category:** `admin`  
**Hints:** readOnlyHint=`true`, destructiveHint=`false`, idempotentHint=`true`, openWorldHint=`true`  
**Confirm:** `never`

_No parameters._

**Output** (`structuredContent`): `version`, `protocol_versions`, `toolsets_enabled`, `tool_count`, `cache_enabled`, `summary`.

---
