# M365 MCP Cache User Guide

**Version**: 1.0.0
**Last Updated**: 2026-09-26

## Table of Contents

1. [Overview](#overview)
2. [Getting Started](#getting-started)
3. [The refresh Parameter](#the-refresh-parameter)
4. [Viewing Cache Statistics](#viewing-cache-statistics)
5. [Manual Cache Invalidation](#manual-cache-invalidation)
6. [Cache Warming](#cache-warming)
7. [Troubleshooting](#troubleshooting)
8. [Best Practices](#best-practices)

---

## Overview

The M365 MCP cache reduces redundant calls to Microsoft Graph. The cache is:

- **Automatic**: works out of the box with no configuration
- **Encrypted**: all data is encrypted at rest with AES-256 (SQLCipher)
- **Resource-based**: entries are keyed by account and resource, not by tool
- **Invisible to the model**: results never contain cache metadata; the only
  model-facing control is the `refresh` parameter
- **Intelligent**: a three-state lifecycle (Fresh, Stale, Expired) keeps data
  reasonably current

Repeated reads of the same mailbox folder, calendar window, contact list or
OneDrive folder are served from the local cache instead of Graph.

### How entries are keyed

A cache key combines:

1. the resolved account ID (so accounts never share entries)
2. the resource (`email`, `email_folder`, `email_rule`, `event`, `calendar`,
   `contact`, `contact_folder`, `drive_item`)
3. a hash of the normalised request parameters
4. the cursor, for later pages

`refresh` and `account_id` spelling (ID or email address) do not change the
key, so the same request always hits the same entry.

---

## Getting Started

### Automatic Caching

`m365_list` and `m365_get` read through the cache. Other tools (search,
content, and every write) always go to Graph. No configuration is needed:

```python
# Served from the cache when the entry is fresh
m365_list(resource="drive_item", path="/Documents")
m365_list(resource="email", container_id="inbox", limit=20)
m365_get(resource="event", id=event_id)
```

### Freshness by resource

Each resource has its own lifecycle:

| Resource | Fresh (served immediately) | Stale (still served) | Expired (refetched) |
|---|---|---|---|
| `email` | 0-2 min | 2-10 min | after 10 min |
| `email_folder` | 0-5 min | 5-30 min | after 30 min |
| `email_rule` | 0-15 min | 15-60 min | after 1 hour |
| `event` | 0-5 min | 5-30 min | after 30 min |
| `calendar` | 0-30 min | 30 min-2 h | after 2 hours |
| `contact` | 0-20 min | 20 min-2 h | after 2 hours |
| `contact_folder` | 0-30 min | 30 min-4 h | after 4 hours |
| `drive_item` | 0-10 min | 10-60 min | after 1 hour |

Stale entries for the unified tools are simply served until they expire; no
background refresh is queued for them.

### First Use

On first server startup:

1. The cache is empty
2. Startup warming is disabled by default
3. First requests go to Graph (cache miss)
4. Repeated requests are served from the cache (cache hit)

---

## The refresh Parameter

`refresh` is the only cache control a tool exposes. It exists on `m365_list`
and `m365_get`.

```python
# Default: use the cache when fresh
m365_list(resource="email", container_id="inbox")

# Bypass the cache, fetch from Graph and update the entry
m365_list(resource="email", container_id="inbox", refresh=True)
m365_get(resource="email", id=email_id, refresh=True)
```

**When to use `refresh=true`:**

- something changed outside this server (in Outlook or on another device)
  and you need it right now
- troubleshooting a result that looks stale

You do not need it after changes made through this server: every write clears
the affected entries for that account automatically.

There is no parameter to disable the cache for a single request; use
`refresh=true` for a guaranteed fresh read.

---

## Viewing Cache Statistics

The cache tools are in the `admin` tier, hidden by default. Enable them by
adding `admin` to `M365_MCP_TOOLSETS`:

```bash
export M365_MCP_TOOLSETS=core,extended,admin
```

### admin_cache_get

```python
admin_cache_get(view="stats")
```

Returns:

```json
{
  "view": "stats",
  "stats": {
    "entry_count": 150,
    "total_bytes": 45000000,
    "max_bytes": 2147483648,
    "usage_percent": 2.1,
    "total_hits": 5432,
    "by_resource": {"email": {}, "drive_item": {}}
  },
  "tasks": null,
  "warming": null,
  "summary": "<one-line summary of the cache statistics>"
}
```

Other views:

| Call | Shows |
|---|---|
| `admin_cache_get(view="tasks", status="running", limit=50)` | Queued, running, completed or failed background tasks |
| `admin_cache_get(view="task", task_id="...")` | One background task |
| `admin_cache_get(view="warming")` | Warming status and progress; `disabled` when warming is off |

---

## Manual Cache Invalidation

### admin_cache_invalidate

Clear cached results by resource type instead of by pattern:

```python
# All cached emails (all accounts)
admin_cache_invalidate(scope="email")

# Cached OneDrive items for one account
admin_cache_invalidate(scope="drive_item", account_id="me@outlook.com")

# Everything, with an audit note
admin_cache_invalidate(scope="all", reason="testing")
```

`scope` is one of `email`, `email_folder`, `email_rule`, `event`, `calendar`,
`contact`, `contact_folder`, `drive_item` or `all`. `account_id` is optional;
`reason` is recorded in the audit log.

### Automatic Invalidation

Every mutating tool clears the affected resources for its own account, so you
rarely need manual invalidation:

| Tool | Clears |
|---|---|
| `m365_create`, `m365_update`, `m365_move` | the matching resource; email changes also clear `email_folder`, because unread counts change |
| `m365_delete` | the deleted resource; a deleted mail folder also clears `email`, a deleted calendar also clears `event`, a deleted contact folder also clears `contact` |
| `email_create_draft`, `email_send`, `email_reply`, `email_forward`, `calendar_forward`, `email_folder_mark_all_read`, `email_folder_empty` | `email` and `email_folder` |
| `calendar_create_event`, `calendar_update_event`, `calendar_respond` | `event` |
| `drive_upload`, `drive_copy`, `drive_share` | `drive_item` |
| `email_rule_manage` | `email_rule` |
| `m365_get_content` | nothing (it only writes a local file or reads) |

The authoritative table is `MUTATION_INVALIDATES` in
`src/m365_mcp/resource_cache.py`.

---

## Cache Warming

Cache warming pre-populates the cache in the background. It is opt-in.

Default behaviour: the server starts without a warming worker and the cache
fills on demand.

Enabled behaviour (`M365_MCP_CACHE_WARMING=true`): the server starts the
background worker and warmer, and stops them on shutdown. For every signed-in
account it warms the mail folder tree, the newest inbox messages, upcoming
events and contacts: the same entries a first `m365_list` call reads. Entries
that are already fresh are skipped.

Stale entries (older than the fresh window but still inside the stale window)
are still served immediately; with warming enabled, serving one also queues a
background refresh of that exact `m365_list` or `m365_get` request, so the next
call is fresh. Without warming, a stale entry is served until it expires.

```bash
export M365_MCP_CACHE_WARMING=true
uv run m365-mcp
```

Check progress with `admin_cache_get(view="warming")`.

---

## Troubleshooting

### Problem: Stale data

**Symptoms**: old data, recent changes made elsewhere not shown.

**Solutions**:

```python
# Fetch fresh data for this request
m365_list(resource="drive_item", path="/Documents", refresh=True)

# Or clear the cache for the resource and retry
admin_cache_invalidate(scope="drive_item")
```

### Problem: Cache not helping

**Check**:

1. `admin_cache_get(view="stats")`: is `total_hits` growing?
2. Are requests identical? Changing `limit`, filters or cursor creates a new key.
3. Encryption key: check the system keyring or `M365_MCP_CACHE_KEY`.

**Solutions**:

```bash
# Reset the cache database
rm ~/.m365_mcp_cache.db

# Restart the server (the cache rebuilds)
uv run m365-mcp
```

### Problem: Cache too large

**Automatic**: cleanup starts at 80% of 2 GB (1.6 GB) and reduces to 60%
(1.2 GB), removing the oldest entries first.

**Manual**:

```python
admin_cache_get(view="stats")            # see usage
admin_cache_invalidate(scope="email")    # emails are usually largest
```

### Problem: Encryption or SQLCipher error

**Symptoms**: "Invalid encryption key", "Cannot decrypt cache", or a SQLCipher
import failure.

**Cause**: the encryption key changed or was lost, SQLCipher is unavailable, or
the database is corrupt. If the database cannot be opened because of a key
mismatch or recoverable corruption, M365 MCP recreates the cache file and
rebuilds entries on demand. If SQLCipher is unavailable while encryption is
enabled, startup fails instead of falling back to plaintext.

**Solution**:

```bash
# Delete and recreate the cache
rm ~/.m365_mcp_cache.db

# For headless servers, set the key explicitly
export M365_MCP_CACHE_KEY="your-base64-key-here"
```

---

## Best Practices

1. **Use the default.** Do not pass `refresh=true` on every call; it defeats the
   cache.
2. **Trust automatic invalidation** after writes made through this server.
3. **Use `refresh=true` after outside changes** or when a result looks stale.
4. **Trust account isolation.** Entries are keyed by account, so calls with
   different `account_id` values never share data.
5. **Trust automatic cleanup.** Manage size manually only if needed.
6. **Protect the key.** Use the system keyring, or for headless servers:

   ```bash
   export M365_MCP_CACHE_KEY=$(openssl rand -base64 32)
   ```

   Never hardcode encryption keys.

---

## Summary

- **Automatic**: `m365_list` and `m365_get` read through the cache
- **One control**: `refresh=true` bypasses it
- **Encrypted**: AES-256 SQLCipher by default
- **Per resource**: separate freshness rules and invalidation per resource,
  keyed by account
- **Admin tools**: `admin_cache_get` and `admin_cache_invalidate` (enable with
  `M365_MCP_TOOLSETS=core,extended,admin`)

See `cache_security.md` for encryption details and `cache_examples.md` for
workflows.

---

**Document Version**: 1.0.0
**Last Updated**: 2026-09-26
