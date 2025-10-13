# Tool Integration Examples

## Adding Cache Support to Read-Only Tools

### Example 1: folder_get_tree (High Priority)

**Before:**
```python
@mcp.tool(name="folder_get_tree")
def folder_get_tree(account_id: str, path: str = "/", max_depth: int = 10):
    # ... fetch data from API ...
    return tree_data
```

**After:**
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
    force_refresh: bool = False,
):
    """📖 Recursively build OneDrive folder tree (cached)

    Args:
        use_cache: Use cached data if available (default: True)
        force_refresh: Force fresh fetch ignoring cache (default: False)
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
            max_depth=max_depth,
        )

        if cached_data:
            cached_data["_cache_status"] = status
            return cached_data

    # Fetch fresh data
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
            max_depth=max_depth,
        )

    return tree_data
```

### Example 2: email_list

```python
@mcp.tool(name="email_list")
def email_list(
    account_id: str,
    folder: str = "inbox",
    limit: int = 10,
    use_cache: bool = True,
    force_refresh: bool = False,
):
    # Check cache
    if use_cache and not force_refresh:
        cached_data, status = cache_manager.get_cached(
            operation="email_list",
            account_id=account_id,
            fresh_ttl=120,  # 2 minutes
            stale_ttl=600,  # 10 minutes
            folder=folder,
            limit=limit,
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
            limit=limit,
        )

    return {"emails": emails, "_cache_status": "fresh"}
```

## Adding Invalidation to Write Tools

### Example 1: email_delete

```python
@mcp.tool(name="email_delete")
def email_delete(account_id: str, email_id: str, confirm: bool = False):
    # Perform deletion
    result = graph.request("DELETE", f"/me/messages/{email_id}", account_id)

    # Invalidate related caches
    cache_manager.invalidate_pattern(
        account_id=account_id,
        resource_type="email_list",
        pattern="*"  # Invalidate all email lists
    )

    cache_manager.invalidate_pattern(
        account_id=account_id,
        resource_type="email_get",
        pattern=f"*email_id={email_id}*"
    )

    return {"status": "deleted", "email_id": email_id}
```

### Example 2: file_create

```python
@mcp.tool(name="file_create")
def file_create(account_id: str, local_file_path: str, onedrive_path: str):
    # Upload file
    result = _upload_file(account_id, local_file_path, onedrive_path)

    # Invalidate parent folder cache
    parent_folder_id = result.get("parentReference", {}).get("id")

    cache_manager.invalidate_pattern(
        account_id=account_id,
        resource_type="file_list",
        pattern=f"*folder_id={parent_folder_id}*"
    )

    # Invalidate folder tree (structure changed)
    cache_manager.invalidate_pattern(
        account_id=account_id,
        resource_type="folder_get_tree",
        pattern="*"
    )

    return result
```

## Priority Implementation Order

### Phase 1: High-Value Read Tools
1. **folder_get_tree** - Most expensive operation (30s → 100ms)
2. **email_list** - Frequently called
3. **file_list** - Moderate usage, good benefit

### Phase 2: Supporting Read Tools
4. **folder_list**
5. **email_get**
6. **file_get**

### Phase 3: Write Tool Invalidation
7. **email_delete, email_move** - Invalidate email_list
8. **file_create, file_delete** - Invalidate file_list + folder_tree
9. **All other write operations**

## Testing Pattern

```python
# tests/test_cache_integration.py

def test_folder_tree_caching():
    # First call - cache miss
    result1 = folder_get_tree(account_id="test", path="/", use_cache=True)
    assert result1["_cache_status"] == "fresh"

    # Second call - cache hit
    result2 = folder_get_tree(account_id="test", path="/", use_cache=True)
    assert result2["_cache_status"] == "fresh"

    # Force refresh
    result3 = folder_get_tree(account_id="test", path="/", force_refresh=True)
    assert result3["_cache_status"] == "fresh"

def test_cache_invalidation():
    # Populate cache
    email_list(account_id="test", folder="inbox")

    # Delete email
    email_delete(account_id="test", email_id="123", confirm=True)

    # Cache should be invalidated
    # Next call will be a cache miss
```
