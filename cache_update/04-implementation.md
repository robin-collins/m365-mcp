# CacheManager Implementation

**Note**: This document shows the basic CacheManager implementation. For the production version with AES-256 encryption support, see [09-encryption-security.md](./09-encryption-security.md) which includes SQLCipher integration, encryption key management, and automatic migration from unencrypted cache.

## Class Structure

Location: `src/m365_mcp/cache.py`

```python
import sqlite3
import json
import time
from pathlib import Path
from typing import Any, Optional
from contextlib import contextmanager

class CacheManager:
    """Multi-tier cache manager with TTL and background tasks"""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_database()

    @contextmanager
    def _db(self):
        """Context manager for database connections"""
        conn = sqlite3.connect(str(self.db_path))
        try:
            yield conn
        finally:
            conn.close()
```

## Core Methods

### get_cached()

```python
def get_cached(
    self,
    operation: str,
    account_id: str,
    fresh_ttl: int,
    stale_ttl: int,
    **params
) -> tuple[Optional[dict], str]:
    """
    Get cached data with smart refresh

    Returns:
        (data, status) where status is:
        - 'fresh': Return immediately, no refresh
        - 'stale': Return + trigger background refresh
        - 'miss': No cache found
        - 'expired': Cache too old
    """
    cache_key = generate_cache_key(operation, account_id, **params)

    with self._db() as conn:
        row = conn.execute(
            "SELECT data_json, created_at FROM cache_entries WHERE cache_key = ?",
            (cache_key,)
        ).fetchone()

        if not row:
            return None, 'miss'

        data_json, created_at = row
        age = time.time() - created_at

        # Update access tracking
        conn.execute(
            "UPDATE cache_entries SET accessed_at = ?, hit_count = hit_count + 1 WHERE cache_key = ?",
            (time.time(), cache_key)
        )
        conn.commit()

        data = json.loads(data_json)

        if age < fresh_ttl:
            return data, 'fresh'
        elif age < stale_ttl:
            # Trigger background refresh here
            return data, 'stale'
        else:
            return None, 'expired'
```

### set_cached()

```python
def set_cached(
    self,
    operation: str,
    account_id: str,
    data: dict,
    ttl: int,
    **params
):
    """Store data in cache with TTL"""
    cache_key = generate_cache_key(operation, account_id, **params)
    data_json = json.dumps(data)
    now = time.time()

    with self._db() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO cache_entries
            (cache_key, account_id, resource_type, data_json,
             size_bytes, created_at, accessed_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (cache_key, account_id, operation, data_json,
             len(data_json), now, now, now + ttl)
        )
        conn.commit()
```

### invalidate_pattern()

```python
def invalidate_pattern(
    self,
    account_id: str,
    resource_type: str,
    pattern: str = "*"
):
    """Invalidate cache entries matching pattern"""
    with self._db() as conn:
        sql_pattern = pattern.replace("*", "%")

        cursor = conn.execute(
            """
            DELETE FROM cache_entries
            WHERE account_id = ? AND resource_type = ? AND cache_key LIKE ?
            """,
            (account_id, resource_type, sql_pattern)
        )

        # Log invalidation
        conn.execute(
            """
            INSERT INTO cache_invalidation
            (account_id, resource_type, pattern, invalidated_at, invalidated_count)
            VALUES (?, ?, ?, ?, ?)
            """,
            (account_id, resource_type, pattern, time.time(), cursor.rowcount)
        )
        conn.commit()
```

### cleanup_expired()

```python
def cleanup_expired(self):
    """Remove expired entries"""
    now = time.time()

    with self._db() as conn:
        conn.execute("DELETE FROM cache_entries WHERE expires_at < ?", (now,))
        conn.execute(
            "DELETE FROM cache_tasks WHERE status = 'completed' AND completed_at < ?",
            (now - 86400,)  # Keep completed for 24h
        )
        conn.commit()
```

## Usage in Tools

### Decorator Pattern

```python
from functools import wraps

def with_cache(operation: str, fresh_ttl: int, stale_ttl: int):
    """Decorator to add caching to tool functions"""

    def decorator(func):
        @wraps(func)
        def wrapper(account_id: str, use_cache: bool = True, force_refresh: bool = False, **kwargs):
            # Check cache
            if use_cache and not force_refresh:
                cached_data, status = cache_manager.get_cached(
                    operation, account_id, fresh_ttl, stale_ttl, **kwargs
                )

                if cached_data:
                    cached_data["_cache_status"] = status
                    return cached_data

            # Fetch fresh data
            result = func(account_id, **kwargs)

            # Store in cache
            if use_cache:
                cache_manager.set_cached(
                    operation, account_id, result, stale_ttl, **kwargs
                )

            result["_cache_status"] = "fresh"
            return result

        return wrapper
    return decorator
```

## Configuration

```python
# src/m365_mcp/cache_config.py

from pathlib import Path
import os

# Database location
CACHE_DB_PATH = Path.home() / ".m365_mcp_cache.db"

# TTL policies (seconds)
TTL_POLICIES = {
    "folder_get_tree": {"fresh": 1800, "stale": 7200},
    "email_list": {"fresh": 120, "stale": 600},
    "file_list": {"fresh": 600, "stale": 3600},
}

# Size limits
MAX_ENTRY_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_CACHE_SIZE = 500 * 1024 * 1024  # 500 MB
```
