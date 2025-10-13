# Cache Strategy

## Cache Key Generation

```python
def generate_cache_key(operation: str, account_id: str, **params) -> str:
    """Generate deterministic cache key"""
    sorted_params = sorted(params.items())
    param_str = "&".join(f"{k}={v}" for k, v in sorted_params)

    # Hash if too long
    if len(param_str) > 100:
        import hashlib
        param_hash = hashlib.sha256(param_str.encode()).hexdigest()[:16]
        return f"{operation}:{account_id}:{param_hash}"

    return f"{operation}:{account_id}:{param_str}"
```

**Examples:**
- `folder_get_tree:acc123:path=/&max_depth=10`
- `email_list:acc123:folder=inbox&limit=50`
- `file_list:acc456:folder_id=ABC123&limit=100`

## TTL (Time-To-Live) Policies

| Resource Type | Fresh TTL | Stale TTL | Rationale |
|---------------|-----------|-----------|-----------|
| `folder_tree` | 30 min | 2 hours | Folder structure changes infrequently |
| `folder_list` | 15 min | 1 hour | Moderate change frequency |
| `email_list` | 2 min | 10 min | Emails arrive frequently |
| `email_get` | 15 min | 1 hour | Individual emails rarely change |
| `file_list` | 10 min | 1 hour | Files updated moderately |
| `file_get` | 20 min | 2 hours | File metadata stable |
| `contact_list` | 20 min | 2 hours | Contacts change occasionally |
| `contact_get` | 30 min | 4 hours | Individual contacts very stable |
| `calendar_list_events` | 5 min | 30 min | Calendar needs freshness |
| `calendar_get_event` | 10 min | 1 hour | Individual events moderately stable |
| `search_*` | 1 min | 5 min | Search should be fresh |

## Cache States

### FRESH (0 → fresh_ttl)
- **Action**: Return cached data immediately
- **Background**: No refresh triggered
- **User Experience**: Instant response

### STALE (fresh_ttl → stale_ttl)
- **Action**: Return cached data immediately
- **Background**: Trigger async refresh
- **User Experience**: Instant response + eventual consistency

### EXPIRED (> stale_ttl)
- **Action**: Fetch fresh data from API
- **Background**: Update cache with new data
- **User Experience**: Wait for API response

## Invalidation Rules

### Write Operation Invalidation Patterns

| Operation | Invalidation Pattern |
|-----------|---------------------|
| `email_send` | `email_list:*:folder=sent*` |
| `email_move` | `email_list:*` (all email lists) |
| `email_delete` | `email_list:*`, `email_get:*:email_id={id}` |
| `email_update` | `email_get:*:email_id={id}` |
| `file_create` | `file_list:*:folder_id={parent}*`, `folder_tree:*` |
| `file_delete` | `file_list:*`, `file_get:*:file_id={id}`, `folder_tree:*` |
| `file_update` | `file_get:*:file_id={id}` |
| `contact_create` | `contact_list:*` |
| `contact_update` | `contact_list:*`, `contact_get:*:contact_id={id}` |
| `contact_delete` | `contact_list:*`, `contact_get:*:contact_id={id}` |
| `calendar_create_event` | `calendar_list_events:*` |
| `calendar_update_event` | `calendar_list_events:*`, `calendar_get_event:*:event_id={id}` |
| `calendar_delete_event` | `calendar_list_events:*`, `calendar_get_event:*:event_id={id}` |

### Wildcard Matching

Pattern `email_list:acc123:*` matches:
- `email_list:acc123:folder=inbox&limit=50`
- `email_list:acc123:folder=sent&limit=100`
- But NOT: `email_get:acc123:email_id=xyz`

## Size Limits

| Limit Type | Value | Rationale |
|------------|-------|-----------|
| Max entry size | 10 MB | Prevent memory issues |
| Max cache size (soft) | 2 GB | Ample storage for 20,000+ operations |
| Max entries per account | 10,000 | Prevent unbounded growth |
| Cleanup threshold | 80% (1.6GB) | Trigger proactive cleanup |

### Soft Limit vs Hard Limit

**Soft Limit (What We Use):**
- When cache reaches 80% of 2GB (1.6GB), trigger cleanup of expired/stale entries
- New cache writes still allowed during cleanup
- Graceful degradation - no disruption to users
- Prevents disk space exhaustion proactively

**Hard Limit (Not Used):**
- Would reject new cache writes once limit is hit
- Too disruptive - breaks caching functionality
- Not necessary with proper cleanup strategy

## Compression

**Selective Compression Strategy:**
- Entries **< 50KB**: Stored uncompressed (fast access)
- Entries **≥ 50KB**: Compressed with gzip level 6
- Average compression ratio: 80% savings
- CPU overhead: ~15-25ms write, ~8-12ms read

**Benefits:**
- 80% disk space savings on large entries
- 2GB cache can hold ~5-10GB effective data
- Compression cost negligible vs API call time (30s)

**Trade-offs:**
- Small CPU cost (20-35ms) vs massive space savings
- Only applied to large entries (folder trees, big email lists)
- Still returns in <50ms (vs 30,000ms uncached API call)

## Eviction Strategy

**Priority Order (when cleanup triggered at 80% full):**
1. Expired entries (expires_at < now) - **Remove first**
2. Least recently accessed (lowest accessed_at) - **Remove next**
3. Largest entries (highest size_bytes) - **Remove if still needed**

**Cleanup Target:** Reduce cache to 60% full (1.2GB), leaving headroom

## Configuration

Location: `src/m365_mcp/cache_config.py`

```python
CACHE_TTL_POLICIES = {
    "folder_get_tree": {"fresh": 1800, "stale": 7200},
    "email_list": {"fresh": 120, "stale": 600},
    "file_list": {"fresh": 600, "stale": 3600},
    # ... etc
}

CACHE_LIMITS = {
    "max_entry_bytes": 10 * 1024 * 1024,  # 10 MB
    "max_total_bytes": 2 * 1024 * 1024 * 1024,  # 2 GB (soft limit)
    "cleanup_threshold": 0.8,  # Cleanup at 80% (1.6GB)
    "cleanup_target": 0.6,  # Clean down to 60% (1.2GB)
    "max_entries_per_account": 10000,
    "compression_threshold": 50 * 1024,  # Compress entries > 50KB
}

CACHE_WARMING_ENABLED = True
CACHE_WARMING_OPERATIONS = [
    {"operation": "folder_get_tree", "priority": 1, "throttle_sec": 3},
    {"operation": "email_list", "priority": 2, "params": {"folder": "inbox", "limit": 50}, "throttle_sec": 2},
    {"operation": "contact_list", "priority": 3, "params": {"limit": 100}, "throttle_sec": 1},
]
```
