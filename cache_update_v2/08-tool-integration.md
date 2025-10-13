# Tool Integration

## Overview

This document provides integration patterns for adding caching to existing MCP tools and proper naming conventions for new cache management tools.

## Integration Pattern for Read-Only Tools

### Example: folder_get_tree

**Location**: `src/m365_mcp/tools/folder.py`

```python
from ..cache import cache_manager
from ..cache_config import TTL_POLICIES

@mcp.tool(name="folder_get_tree")
def folder_get_tree(
    account_id: str,
    path: str = "/",
    folder_id: str | None = None,
    max_depth: int = 10,
    use_cache: bool = True,
    force_refresh: bool = False
):
    """
    📖 Recursively build OneDrive folder tree (cached, read-only).

    Args:
        account_id: Microsoft account identifier
        path: Starting path (default: "/")
        folder_id: Starting folder ID (optional)
        max_depth: Maximum recursion depth
        use_cache: Use cached data if available (default: True)
        force_refresh: Force fresh fetch ignoring cache (default: False)

    Returns:
        Dictionary with folder tree structure and cache status
    """

    # Check cache first
    if use_cache and not force_refresh:
        cached_data, status = cache_manager.get_cached(
            operation="folder_get_tree",
            account_id=account_id,
            fresh_ttl=TTL_POLICIES["folder_get_tree"]["fresh"],
            stale_ttl=TTL_POLICIES["folder_get_tree"]["stale"],
            path=path,
            folder_id=folder_id,
            max_depth=max_depth
        )

        if cached_data:
            cached_data["_cache_status"] = status
            return cached_data

    # Fetch fresh data from API
    tree_data = _build_folder_tree(account_id, path, folder_id, max_depth)

    # Add cache metadata
    tree_data["_cached_at"] = time.time()
    tree_data["_cache_status"] = "fresh"

    # Store in cache
    if use_cache:
        cache_manager.set_cached(
            operation="folder_get_tree",
            account_id=account_id,
            data=tree_data,
            ttl=TTL_POLICIES["folder_get_tree"]["stale"],
            path=path,
            folder_id=folder_id,
            max_depth=max_depth
        )

    return tree_data
```

### Example: email_list

```python
@mcp.tool(name="email_list")
def email_list(
    account_id: str,
    folder: str = "inbox",
    limit: int = 10,
    use_cache: bool = True,
    force_refresh: bool = False
):
    """📖 List emails in folder (cached, read-only)."""

    # Check cache
    if use_cache and not force_refresh:
        cached_data, status = cache_manager.get_cached(
            operation="email_list",
            account_id=account_id,
            fresh_ttl=120,  # 2 minutes
            stale_ttl=600,  # 10 minutes
            folder=folder,
            limit=limit
        )

        if cached_data:
            return {**cached_data, "_cache_status": status}

    # Fetch from API
    emails = _fetch_emails(account_id, folder, limit)

    # Cache result
    if use_cache:
        cache_manager.set_cached(
            operation="email_list",
            account_id=account_id,
            data={"emails": emails},
            ttl=600,
            folder=folder,
            limit=limit
        )

    return {"emails": emails, "_cache_status": "fresh"}
```

## Integration Pattern for Write Tools

### Example: email_delete

```python
@mcp.tool(
    name="email_delete",
    annotations={
        "title": "Delete Email",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True
    },
    meta={"category": "email", "safety_level": "critical"}
)
def email_delete(account_id: str, email_id: str, confirm: bool = False):
    """🔴 Delete email (always require user confirmation)."""

    if not confirm:
        raise ValueError("confirm=True required for destructive operation")

    # Perform deletion
    result = graph.request("DELETE", f"/me/messages/{email_id}", account_id)

    # Invalidate related caches
    cache_manager.invalidate_pattern(
        account_id=account_id,
        resource_type="email_list",
        pattern="*",
        reason="email_delete"
    )

    cache_manager.invalidate_pattern(
        account_id=account_id,
        resource_type="email_get",
        pattern=f"*email_id={email_id}*",
        reason="email_delete"
    )

    return {"status": "deleted", "email_id": email_id}
```

### Example: file_create

```python
@mcp.tool(name="file_create")
def file_create(account_id: str, local_file_path: str, onedrive_path: str):
    """✏️ Create file in OneDrive (requires user confirmation recommended)."""

    # Upload file
    result = _upload_file(account_id, local_file_path, onedrive_path)

    # Invalidate parent folder cache
    parent_folder_id = result.get("parentReference", {}).get("id")

    cache_manager.invalidate_pattern(
        account_id=account_id,
        resource_type="file_list",
        pattern=f"*folder_id={parent_folder_id}*",
        reason="file_create"
    )

    # Invalidate folder tree (structure changed)
    cache_manager.invalidate_pattern(
        account_id=account_id,
        resource_type="folder_get_tree",
        pattern="*",
        reason="file_create"
    )

    return result
```

## Cache Management Tools

**Location**: `src/m365_mcp/tools/cache_tools.py`

```python
from ..cache import cache_manager

@mcp.tool(
    name="cache_get_stats",
    annotations={
        "title": "Get Cache Statistics",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    },
    meta={"category": "cache", "safety_level": "safe"}
)
def cache_get_stats(account_id: str) -> dict:
    """📖 Get cache statistics (read-only, safe)."""
    return cache_manager.get_stats(account_id)

@mcp.tool(
    name="cache_invalidate",
    annotations={
        "title": "Invalidate Cache Entries",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False
    },
    meta={"category": "cache", "safety_level": "moderate"}
)
def cache_invalidate(account_id: str, resource_type: str, pattern: str = "*") -> dict:
    """✏️ Manually invalidate cache entries (requires user confirmation recommended)."""
    cache_manager.invalidate_pattern(account_id, resource_type, pattern)
    return {"status": "invalidated", "pattern": pattern}

# Task management tools from 07-background-tasks.md
# cache_task_get_status(), cache_task_list()

# Warming status tool from 06-cache-warming.md
# cache_warming_status()
```

## Tool Naming Conventions

All cache tools follow the pattern: `cache_[action]_[entity]`

| Tool Name | Category | Safety Level | Description |
|-----------|----------|--------------|-------------|
| cache_get_stats | cache | safe (📖) | Get cache statistics |
| cache_invalidate | cache | moderate (✏️) | Invalidate cache entries |
| cache_task_get_status | cache | safe (📖) | Get task status |
| cache_task_list | cache | safe (📖) | List tasks |
| cache_warming_status | cache | safe (📖) | Get warming status |

## Priority Implementation Order

### Phase 1: High-Value Read Tools (Days 7-8)
1. **folder_get_tree** - Most expensive (30s → 100ms)
2. **email_list** - Frequently called (2-5s → 50ms)
3. **file_list** - Moderate usage (1-3s → 30ms)

### Phase 2: Supporting Read Tools (Day 8)
4. **folder_list**
5. **email_get**
6. **file_get**
7. **contact_list**
8. **contact_get**

### Phase 3: Write Tool Invalidation (Day 9)
9. **email_delete, email_move, email_send** → invalidate email_list
10. **file_create, file_delete, file_move** → invalidate file_list + folder_tree
11. **contact_create, contact_update, contact_delete** → invalidate contact_list
12. **calendar operations** → invalidate calendar_list_events

## Testing Pattern

```python
def test_folder_tree_caching():
    """Test folder_get_tree caching behavior."""
    account_id = "test-account"

    # First call - cache miss
    result1 = folder_get_tree(account_id, path="/", use_cache=True)
    assert result1["_cache_status"] == "fresh"

    # Second call - cache hit (fresh)
    result2 = folder_get_tree(account_id, path="/", use_cache=True)
    assert result2["_cache_status"] == "fresh"
    assert result2 == result1  # Same data

    # Force refresh
    result3 = folder_get_tree(account_id, path="/", force_refresh=True)
    assert result3["_cache_status"] == "fresh"

def test_cache_invalidation():
    """Test cache invalidation on write operations."""
    account_id = "test-account"

    # Populate cache
    email_list(account_id, folder="inbox")

    # Delete email
    email_delete(account_id, email_id="123", confirm=True)

    # Cache should be invalidated
    # Next call will be cache miss
    result = email_list(account_id, folder="inbox")
    assert result["_cache_status"] == "fresh"
```

---

**Document Version**: 2.0
**Last Updated**: 2025-10-14
**Status**: Production-Ready Tool Integration
