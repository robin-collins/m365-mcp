# M365 MCP Cache Examples

**Version**: 1.0.0
**Last Updated**: 2026-09-26

The examples show the MCP tool calls an assistant (or a script using an MCP
client) makes. The cache tools `admin_cache_get` and `admin_cache_invalidate`
are in the `admin` tier: set `M365_MCP_TOOLSETS=core,extended,admin` to use
them. `account_id` is optional when only one account is signed in.

## Table of Contents

1. [Basic Cache Usage](#basic-cache-usage)
2. [Multi-Account Cache Behaviour](#multi-account-cache-behaviour)
3. [Invalidation](#invalidation)
4. [Monitoring and Debugging](#monitoring-and-debugging)
5. [Common Workflows](#common-workflows)
6. [Best Practices Summary](#best-practices-summary)
7. [Troubleshooting Examples](#troubleshooting-examples)

---

## Basic Cache Usage

### Example 1: Default caching (recommended)

```python
# First call: cache miss, fetched from Graph
m365_list(resource="drive_item", path="/Documents")

# Second call, same request: served from the cache (no Graph call)
m365_list(resource="drive_item", path="/Documents")
```

The two calls share one entry because the account, resource and normalised
parameters are identical. Changing `limit`, a filter or the `cursor` creates a
different entry.

### Example 2: Writes clear the cache for you

```python
# Upload a file. The server clears cached drive_item entries for this account.
drive_upload(local_path="C:/Users/me/report.pdf", parent_path="/Uploads")

# The next list already includes the new file; refresh is not needed.
m365_list(resource="drive_item", path="/Uploads")
```

### Example 3: Force a fresh read

```python
# Something changed outside this server (for example in Outlook on your phone)
m365_list(resource="email", container_id="inbox", refresh=True)
m365_get(resource="email", id=email_id, refresh=True)
```

`refresh=true` bypasses the cache for that request, fetches from Graph and
updates the entry. It exists only on `m365_list` and `m365_get`.

---

## Multi-Account Cache Behaviour

### Account isolation

```python
# Completely separate entries: the account is part of the key
m365_list(resource="email", account_id="me@outlook.com")
m365_list(resource="email", account_id="family@hotmail.com")
```

`account_id` accepts the ID or the email address; both resolve to the same
account and the same entries.

### Refresh or clear one account only

```python
# Fresh read for one account
m365_list(resource="event", account_id="me@outlook.com", refresh=True)

# Clear cached emails for one account; the other account is untouched
admin_cache_invalidate(scope="email", account_id="me@outlook.com")
```

### Statistics across accounts

```python
admin_cache_get(view="stats")   # totals and a per-resource breakdown
```

---

## Invalidation

### Automatic invalidation on write

Every mutating tool clears the affected resources for its own account. For
example:

- `m365_update(resource="email", ...)` clears `email` and `email_folder`
  (unread counts change)
- `m365_delete(resource="calendar", ...)` clears `calendar` and `event`
- `email_rule_manage(...)` clears `email_rule`

See [cache_user_guide.md](cache_user_guide.md#automatic-invalidation) for the
full table.

### Targeted manual invalidation

```python
admin_cache_invalidate(scope="email")
admin_cache_invalidate(scope="drive_item", account_id="me@outlook.com")
```

Scopes are typed: `email`, `email_folder`, `email_rule`, `event`, `calendar`,
`contact`, `contact_folder`, `drive_item` or `all`.

### Invalidation with an audit note

```python
admin_cache_invalidate(scope="all", reason="Cleaning up after a test run")
```

The reason is recorded in the audit log.

---

## Monitoring and Debugging

### Example 1: Cache health

```python
result = admin_cache_get(view="stats")
stats = result["stats"]
print(stats["entry_count"], "entries")
print(stats["usage_percent"], "% of the size limit")
print(stats["total_hits"], "hits")
print(stats["by_resource"])
```

### Example 2: Debug a stale result

```python
# 1. Compare the cached and the fresh read
cached = m365_list(resource="email", container_id="inbox", limit=10)
fresh = m365_list(resource="email", container_id="inbox", limit=10, refresh=True)

# 2. If they differ, the entry was stale; refresh already updated it.
# 3. If stale results keep recurring, clear the resource and look at the stats.
admin_cache_invalidate(scope="email")
admin_cache_get(view="stats")
```

### Example 3: Background tasks

```python
admin_cache_get(view="tasks", status="failed")
admin_cache_get(view="task", task_id="task-123")
```

---

## Common Workflows

### Workflow 1: Daily email processing

```python
# Newest unread mail; repeated calls within a couple of minutes are cached
page = m365_list(resource="email", email_filter={"unread": True}, limit=20)

for item in page["items"]:
    m365_update(resource="email", id=item["id"],
                email_changes={"is_read": True})   # clears email + email_folder
    m365_move(resource="email", id=item["id"], destination_id="archive")
```

### Workflow 2: Document management

```python
m365_list(resource="drive_item", path="/Projects")          # cached
drive_upload(local_path="C:/Users/me/plan.docx",
             parent_path="/Projects")                      # clears drive_item
m365_list(resource="drive_item", path="/Projects")          # sees the new file
```

### Workflow 3: Several accounts

```python
for account in ["me@outlook.com", "family@hotmail.com"]:
    m365_list(resource="event", account_id=account)
```

Each account has its own entries, so the second call never reuses the first
account's data.

### Workflow 4: Optional cache warming

Startup warming and background tasks are available when the server starts with
`M365_MCP_CACHE_WARMING=true`. Leave the variable unset or `false` for the
default on-demand behaviour.

```bash
export M365_MCP_CACHE_WARMING=true
uv run m365-mcp
```

```python
status = admin_cache_get(view="warming")
print(status["warming"]["status"])
```

### Workflow 5: Occasional maintenance

```python
result = admin_cache_get(view="stats")
if result["stats"]["usage_percent"] > 75:
    admin_cache_invalidate(scope="email", reason="Free space")
```

The server already trims the cache automatically (starts at 80% of 2 GB and
reduces to 60%), so this is rarely needed.

---

## Best Practices Summary

### DO

1. **Let the cache work automatically**: the default is optimal.
2. **Use `refresh=true` only for outside changes** or a result that looks stale.
3. **Trust account isolation**: entries are keyed by account.
4. **Trust automatic invalidation** after writes made through this server.
5. **Use `admin_cache_get(view="stats")`** to check hits and size.

### DON'T

1. **Pass `refresh=true` on every call**: it defeats the cache.
2. **Invalidate more than needed**: prefer a typed scope over `all`.
3. **Manage cache size by hand**: automatic cleanup handles it.
4. **Hardcode encryption keys**: use the system keyring or
   `M365_MCP_CACHE_KEY`.

---

## Troubleshooting Examples

### Problem: Seeing stale data

```python
m365_list(resource="drive_item", path="/", refresh=True)
```

### Problem: No cache hits

```python
# Check whether requests vary; a different limit, filter or cursor is a new key
admin_cache_get(view="stats")
```

### Problem: Cache too large

```python
# Emails are usually the largest resource
admin_cache_invalidate(scope="email")
```

---

**Document Version**: 1.0.0
**Last Updated**: 2026-09-26
**See Also**: `cache_user_guide.md`, `cache_security.md`
