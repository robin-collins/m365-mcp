# Cache Strategy

## Overview

The cache strategy defines TTL policies, invalidation rules, cache key generation, and eviction policies to ensure optimal performance while maintaining data freshness and consistency.

## Cache Key Generation

### Deterministic Key Format

```python
def generate_cache_key(operation: str, account_id: str, **params) -> str:
    """
    Generate deterministic cache key from operation and parameters.

    Format: operation:account_id:params_hash
    """
    # Sort parameters for deterministic output
    sorted_params = sorted(params.items())
    param_str = "&".join(f"{k}={v}" for k, v in sorted_params)

    # Hash if too long (>100 chars)
    if len(param_str) > 100:
        import hashlib
        param_hash = hashlib.sha256(param_str.encode()).hexdigest()[:16]
        return f"{operation}:{account_id}:{param_hash}"

    return f"{operation}:{account_id}:{param_str}"
```

### Examples

```python
# Short parameters - no hashing
folder_get_tree:acc123:path=/&max_depth=10

# Query parameters included
email_list:acc123:folder=inbox&limit=50

# File operations
file_list:acc456:folder_id=ABC123&limit=100

# Hashed (long parameters)
folder_get_tree:acc123:a1b2c3d4e5f6g7h8
```

## TTL Policies

### TTL Configuration by Resource Type

| Resource Type | Fresh TTL | Stale TTL | Rationale |
|---------------|-----------|-----------|-----------|
| folder_get_tree | 30 min | 2 hours | Folder structure changes infrequently |
| folder_list | 15 min | 1 hour | Moderate change frequency |
| email_list | 2 min | 10 min | Emails arrive frequently |
| email_get | 15 min | 1 hour | Individual emails rarely change after read |
| file_list | 10 min | 1 hour | Files updated moderately |
| file_get | 20 min | 2 hours | File metadata stable |
| contact_list | 20 min | 2 hours | Contacts change occasionally |
| contact_get | 30 min | 4 hours | Individual contacts very stable |
| calendar_list_events | 5 min | 30 min | Calendar needs freshness |
| calendar_get_event | 10 min | 1 hour | Individual events moderately stable |
| search_* | 1 min | 5 min | Search results should be current |

### Cache State Behavior

**FRESH State (age < fresh_ttl)**:
- Return cached data immediately
- No background refresh triggered
- Highest confidence in data freshness
- User Experience: Instant response (<100ms)

**STALE State (fresh_ttl ≤ age < stale_ttl)**:
- Return cached data immediately
- Trigger background refresh (non-blocking)
- Acceptable staleness for UX
- User Experience: Instant response + auto-update

**EXPIRED State (age ≥ stale_ttl)**:
- Discard cached data
- Fetch fresh from API (blocking)
- Data too old to be useful
- User Experience: Wait for API response

## Invalidation Rules

### Write Operation Invalidation Patterns

| Write Operation | Invalidation Pattern | Rationale |
|-----------------|---------------------|-----------|
| email_send | `email_list:*:folder=sent*` | Sent folder updated |
| email_delete | `email_list:*`, `email_get:*:email_id={id}` | Lists + specific email |
| email_move | `email_list:*` | Both source and dest folders affected |
| email_update | `email_get:*:email_id={id}` | Specific email modified |
| file_create | `file_list:*:folder_id={parent}*`, `folder_get_tree:*` | Parent folder + tree structure |
| file_delete | `file_list:*`, `file_get:*:file_id={id}`, `folder_get_tree:*` | Lists, file, and tree |
| file_update | `file_get:*:file_id={id}` | Specific file metadata |
| file_move | `file_list:*`, `folder_get_tree:*` | Multiple folders + tree |
| contact_create | `contact_list:*` | Contact lists |
| contact_update | `contact_list:*`, `contact_get:*:contact_id={id}` | Lists + specific contact |
| contact_delete | `contact_list:*`, `contact_get:*:contact_id={id}` | Lists + specific contact |
| calendar_create_event | `calendar_list_events:*` | Calendar lists |
| calendar_update_event | `calendar_list_events:*`, `calendar_get_event:*:event_id={id}` | Lists + event |
| calendar_delete_event | `calendar_list_events:*`, `calendar_get_event:*:event_id={id}` | Lists + event |

### Wildcard Pattern Matching

**Pattern**: `email_list:acc123:*`

**Matches**:
- `email_list:acc123:folder=inbox&limit=50`
- `email_list:acc123:folder=sent&limit=100`
- `email_list:acc123:folder=deleted&limit=25`

**Does NOT Match**:
- `email_get:acc123:email_id=xyz` (different operation)
- `email_list:acc456:folder=inbox` (different account)

## Size Management

### Cache Limits

| Limit Type | Value | Behavior |
|------------|-------|----------|
| Max entry size | 10 MB | Reject entries larger than 10MB |
| Max total cache size | 2 GB (soft) | Cleanup triggered at 80% (1.6GB) |
| Cleanup target | 60% (1.2GB) | Clean down to 1.2GB when triggered |
| Max entries per account | 10,000 | Prevent single account dominance |

### Eviction Strategy

**Priority Order (when cleanup triggered)**:

1. **Expired entries** (expires_at < now)
   - Remove first, highest priority
   - Already invalid data

2. **Least Recently Accessed** (lowest accessed_at)
   - Remove if cleanup target not met
   - LRU policy for active entries

3. **Largest entries** (highest size_bytes)
   - Remove if still over target
   - Maximize space reclaimed

**Cleanup Process**:
```python
def cleanup_cache(target_size_bytes: int):
    """
    Clean cache to target size.

    1. Delete expired entries
    2. If still over target, delete LRU entries
    3. If still over target, delete largest entries
    """
    # Step 1: Expired
    DELETE FROM cache_entries WHERE expires_at < now();

    # Step 2: LRU (if needed)
    if current_size > target_size:
        DELETE FROM cache_entries
        WHERE cache_key IN (
            SELECT cache_key FROM cache_entries
            ORDER BY accessed_at ASC
            LIMIT calculate_entries_to_remove()
        );

    # Step 3: Largest (if still needed)
    if current_size > target_size:
        DELETE FROM cache_entries
        WHERE cache_key IN (
            SELECT cache_key FROM cache_entries
            ORDER BY size_bytes DESC
            LIMIT calculate_entries_to_remove()
        );
```

## Compression Strategy

### Selective Compression

**Threshold**: 50 KB

**Logic**:
- Entries < 50KB: Store uncompressed (fast access)
- Entries ≥ 50KB: Compress with gzip level 6

**Implementation**:
```python
def compress_if_needed(data: str) -> tuple[bytes, bool]:
    """Compress data if larger than threshold."""
    data_bytes = data.encode('utf-8')

    if len(data_bytes) < 50 * 1024:  # 50KB
        return data_bytes, False  # No compression

    import gzip
    compressed = gzip.compress(data_bytes, compresslevel=6)
    return compressed, True
```

### Compression Statistics

| Data Type | Avg Size Before | Avg Size After | Compression Ratio |
|-----------|-----------------|----------------|-------------------|
| folder_get_tree | 500 KB | 100 KB | 80% |
| email_list (50) | 150 KB | 40 KB | 73% |
| file_list (100) | 200 KB | 60 KB | 70% |
| contact_list | 80 KB | 25 KB | 69% |

**Benefits**:
- 2GB cache effectively holds 5-10GB of uncompressed data
- Reduces cache misses significantly
- CPU overhead (~20-35ms) negligible vs 30s API calls

## Configuration

### Location

`src/m365_mcp/cache_config.py`

### Configuration File

```python
"""Cache configuration for M365 MCP."""

from pathlib import Path

# Database location
CACHE_DB_PATH = Path.home() / ".m365_mcp_cache.db"

# TTL Policies (seconds)
TTL_POLICIES = {
    "folder_get_tree": {"fresh": 1800, "stale": 7200},   # 30min, 2h
    "folder_list": {"fresh": 900, "stale": 3600},        # 15min, 1h
    "email_list": {"fresh": 120, "stale": 600},          # 2min, 10min
    "email_get": {"fresh": 900, "stale": 3600},          # 15min, 1h
    "file_list": {"fresh": 600, "stale": 3600},          # 10min, 1h
    "file_get": {"fresh": 1200, "stale": 7200},          # 20min, 2h
    "contact_list": {"fresh": 1200, "stale": 7200},      # 20min, 2h
    "contact_get": {"fresh": 1800, "stale": 14400},      # 30min, 4h
    "calendar_list_events": {"fresh": 300, "stale": 1800}, # 5min, 30min
    "calendar_get_event": {"fresh": 600, "stale": 3600}, # 10min, 1h
    "search_emails": {"fresh": 60, "stale": 300},        # 1min, 5min
    "search_files": {"fresh": 60, "stale": 300},         # 1min, 5min
}

# Cache Limits
CACHE_LIMITS = {
    "max_entry_bytes": 10 * 1024 * 1024,              # 10 MB
    "max_total_bytes": 2 * 1024 * 1024 * 1024,        # 2 GB (soft limit)
    "cleanup_threshold": 0.8,                          # 80% - trigger cleanup
    "cleanup_target": 0.6,                             # 60% - clean down to
    "max_entries_per_account": 10000,
    "compression_threshold": 50 * 1024,                # 50 KB
}

# Cache Warming
CACHE_WARMING_ENABLED = True
CACHE_WARMING_OPERATIONS = [
    {
        "operation": "folder_get_tree",
        "priority": 1,
        "params": {"path": "/", "max_depth": 10},
        "throttle_sec": 3,  # Wait 3s after this operation
    },
    {
        "operation": "email_list",
        "priority": 2,
        "params": {"folder": "inbox", "limit": 50},
        "throttle_sec": 2,
    },
    {
        "operation": "contact_list",
        "priority": 3,
        "params": {"limit": 100},
        "throttle_sec": 1,
    },
]

# Encryption
CACHE_ENCRYPTION_ENABLED = True  # Cannot be disabled
ENCRYPTION_KEY_ENV_VAR = "M365_MCP_CACHE_KEY"
KEYRING_SERVICE = "m365-mcp-cache"
KEYRING_USERNAME = "encryption-key"
```

---

**Document Version**: 2.0
**Last Updated**: 2025-10-14
**Status**: Production-Ready Strategy
