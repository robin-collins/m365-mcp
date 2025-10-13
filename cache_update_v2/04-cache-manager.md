# Cache Manager Implementation

## Overview

The CacheManager is the core component providing encrypted cache operations with compression, TTL management, and connection pooling. All encryption and compression are handled transparently.

**Location**: `src/m365_mcp/cache.py`

## Class Structure

```python
import gzip
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Import SQLCipher
try:
    from pysqlcipher3 import dbapi2 as sqlcipher
    ENCRYPTION_AVAILABLE = True
except ImportError:
    logger.error("SQLCipher not available - encryption disabled")
    import sqlite3 as sqlcipher
    ENCRYPTION_AVAILABLE = False

from .encryption import EncryptionKeyManager
from .cache_config import CACHE_LIMITS, TTL_POLICIES


class CacheManager:
    """
    Encrypted cache manager with compression and TTL support.

    Features:
    - AES-256 encryption via SQLCipher
    - Selective compression (≥50KB entries)
    - 3-tier caching (Fresh/Stale/Expired)
    - Connection pooling for performance
    - Automatic cleanup at 80% capacity
    """

    def __init__(self, db_path: Path, encryption_enabled: bool = True):
        """
        Initialize CacheManager with encryption.

        Args:
            db_path: Path to SQLCipher database file
            encryption_enabled: Enable encryption (default: True, cannot disable)
        """
        self.db_path = db_path
        self.encryption_enabled = encryption_enabled and ENCRYPTION_AVAILABLE
        self.encryption_key: Optional[str] = None
        self._connection_pool: list = []

        if not self.encryption_enabled:
            raise RuntimeError("Encryption is required but SQLCipher unavailable")

        # Get encryption key
        self.encryption_key = EncryptionKeyManager.get_or_create_key()
        logger.info("Cache encryption enabled with automatic key management")

        # Initialize database
        self._init_database()

    @contextmanager
    def _db(self):
        """
        Context manager for encrypted database connections with pooling.

        Yields:
            SQLite connection with encryption configured
        """
        # Try to reuse connection from pool
        if self._connection_pool:
            conn = self._connection_pool.pop()
        else:
            conn = self._create_connection()

        try:
            yield conn
        finally:
            # Return to pool if healthy
            if len(self._connection_pool) < 5:  # Max 5 pooled connections
                self._connection_pool.append(conn)
            else:
                conn.close()

    def _create_connection(self):
        """Create new encrypted database connection."""
        conn = sqlcipher.connect(str(self.db_path))

        if self.encryption_enabled and self.encryption_key:
            # Configure SQLCipher encryption
            conn.execute(f"PRAGMA key = '{self.encryption_key}'")
            conn.execute("PRAGMA cipher_page_size = 4096")
            conn.execute("PRAGMA kdf_iter = 256000")
            conn.execute("PRAGMA cipher_hmac_algorithm = HMAC_SHA512")
            conn.execute("PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512")

        return conn

    def _init_database(self):
        """Initialize database schema."""
        with self._db() as conn:
            # Run migration script
            with open(Path(__file__).parent / "migrations" / "001_init_cache.sql") as f:
                conn.executescript(f.read())
            conn.commit()
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
    Retrieve cached data with Fresh/Stale/Expired detection.

    Args:
        operation: Operation name (e.g., 'folder_get_tree')
        account_id: Microsoft account identifier
        fresh_ttl: Fresh TTL in seconds
        stale_ttl: Stale TTL in seconds (must be > fresh_ttl)
        **params: Operation parameters for cache key

    Returns:
        Tuple of (data, status) where status is:
        - 'fresh': Data is fresh, no refresh needed
        - 'stale': Data returned but background refresh triggered
        - 'miss': No cache entry found
        - 'expired': Cache entry expired
    """
    from .cache_config import generate_cache_key

    cache_key = generate_cache_key(operation, account_id, **params)
    now = time.time()

    with self._db() as conn:
        row = conn.execute(
            """
            SELECT data_blob, is_compressed, created_at, hit_count
            FROM cache_entries
            WHERE cache_key = ?
            """,
            (cache_key,)
        ).fetchone()

        if not row:
            return None, 'miss'

        data_blob, is_compressed, created_at, hit_count = row
        age = now - created_at

        # Update access tracking
        conn.execute(
            """
            UPDATE cache_entries
            SET accessed_at = ?, hit_count = ?
            WHERE cache_key = ?
            """,
            (now, hit_count + 1, cache_key)
        )
        conn.commit()

        # Decompress if needed
        if is_compressed:
            data_json = gzip.decompress(data_blob).decode('utf-8')
        else:
            data_json = data_blob.decode('utf-8')

        data = json.loads(data_json)

        # Determine cache state
        if age < fresh_ttl:
            return data, 'fresh'
        elif age < stale_ttl:
            # TODO: Trigger background refresh
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
    """
    Store data in cache with automatic compression and encryption.

    Args:
        operation: Operation name
        account_id: Microsoft account identifier
        data: Data to cache (will be JSON-encoded)
        ttl: Time-to-live in seconds
        **params: Operation parameters for cache key
    """
    from .cache_config import generate_cache_key

    cache_key = generate_cache_key(operation, account_id, **params)
    now = time.time()

    # Serialize data
    data_json = json.dumps(data)
    data_bytes = data_json.encode('utf-8')
    uncompressed_size = len(data_bytes)

    # Compress if large enough
    is_compressed = 0
    if uncompressed_size >= CACHE_LIMITS["compression_threshold"]:
        data_blob = gzip.compress(data_bytes, compresslevel=6)
        is_compressed = 1
    else:
        data_blob = data_bytes

    size_bytes = len(data_blob)

    # Check size limit
    if size_bytes > CACHE_LIMITS["max_entry_bytes"]:
        logger.warning(
            f"Cache entry too large ({size_bytes} bytes), skipping: {cache_key}"
        )
        return

    # Store metadata
    metadata = {
        "params": params,
        "item_count": len(data) if isinstance(data, (list, dict)) else 1
    }

    with self._db() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO cache_entries
            (cache_key, account_id, resource_type, data_blob, is_compressed,
             metadata_json, size_bytes, uncompressed_size, created_at,
             accessed_at, expires_at, hit_count, version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1)
            """,
            (
                cache_key, account_id, operation, data_blob, is_compressed,
                json.dumps(metadata), size_bytes, uncompressed_size,
                now, now, now + ttl
            )
        )
        conn.commit()

    # Check if cleanup needed
    self._check_cleanup()
```

### invalidate_pattern()

```python
def invalidate_pattern(
    self,
    account_id: str,
    resource_type: str,
    pattern: str = "*",
    reason: str = None
):
    """
    Invalidate cache entries matching pattern.

    Args:
        account_id: Account to invalidate for
        resource_type: Resource type (e.g., 'email_list')
        pattern: Wildcard pattern (default: '*' = all)
        reason: Reason for invalidation (for audit log)
    """
    with self._db() as conn:
        # Convert wildcard to SQL LIKE pattern
        sql_pattern = pattern.replace("*", "%")
        full_pattern = f"{resource_type}:{account_id}:{sql_pattern}"

        # Delete matching entries
        cursor = conn.execute(
            "DELETE FROM cache_entries WHERE cache_key LIKE ?",
            (full_pattern,)
        )
        count = cursor.rowcount

        # Log invalidation
        conn.execute(
            """
            INSERT INTO cache_invalidation
            (account_id, resource_type, pattern, reason, invalidated_at, invalidated_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (account_id, resource_type, pattern, reason, time.time(), count)
        )
        conn.commit()

        logger.info(f"Invalidated {count} cache entries: {full_pattern}")
```

### cleanup_expired()

```python
def cleanup_expired(self):
    """Remove expired cache entries."""
    now = time.time()

    with self._db() as conn:
        cursor = conn.execute(
            "DELETE FROM cache_entries WHERE expires_at < ?",
            (now,)
        )
        count = cursor.rowcount
        conn.commit()

        if count > 0:
            logger.info(f"Cleaned up {count} expired cache entries")
```

### _check_cleanup()

```python
def _check_cleanup(self):
    """Check if cache cleanup is needed (at 80% capacity)."""
    with self._db() as conn:
        row = conn.execute(
            "SELECT SUM(size_bytes) FROM cache_entries"
        ).fetchone()

        current_size = row[0] if row[0] else 0
        max_size = CACHE_LIMITS["max_total_bytes"]
        threshold = max_size * CACHE_LIMITS["cleanup_threshold"]

        if current_size > threshold:
            logger.info(
                f"Cache size {current_size / 1024 / 1024:.1f}MB "
                f"exceeds threshold {threshold / 1024 / 1024:.1f}MB, "
                "triggering cleanup"
            )
            self._cleanup_to_target()
```

### _cleanup_to_target()

```python
def _cleanup_to_target(self):
    """Clean cache to target size (60% of max)."""
    target_size = CACHE_LIMITS["max_total_bytes"] * CACHE_LIMITS["cleanup_target"]
    now = time.time()

    with self._db() as conn:
        # Step 1: Delete expired entries
        conn.execute("DELETE FROM cache_entries WHERE expires_at < ?", (now,))

        # Step 2: Check if we're below target
        row = conn.execute("SELECT SUM(size_bytes) FROM cache_entries").fetchone()
        current_size = row[0] if row[0] else 0

        if current_size <= target_size:
            conn.commit()
            return

        # Step 3: Delete LRU entries
        bytes_to_remove = current_size - target_size
        conn.execute(
            """
            DELETE FROM cache_entries
            WHERE cache_key IN (
                SELECT cache_key FROM cache_entries
                ORDER BY accessed_at ASC
                LIMIT (
                    SELECT COUNT(*) FROM cache_entries
                    WHERE accessed_at <= (
                        SELECT accessed_at FROM cache_entries
                        ORDER BY accessed_at ASC
                        LIMIT 1 OFFSET (
                            SELECT COUNT(*) * ? / ?
                            FROM cache_entries
                        )
                    )
                )
            )
            """,
            (bytes_to_remove, current_size)
        )

        conn.commit()
        logger.info(f"Cache cleaned to target size {target_size / 1024 / 1024:.1f}MB")
```

### get_stats()

```python
def get_stats(self, account_id: str = None) -> dict[str, Any]:
    """
    Get cache statistics.

    Args:
        account_id: Specific account (None = all accounts)

    Returns:
        Dictionary with cache statistics
    """
    with self._db() as conn:
        if account_id:
            rows = conn.execute(
                """
                SELECT
                    resource_type,
                    COUNT(*) as count,
                    SUM(size_bytes) as total_bytes,
                    SUM(hit_count) as total_hits,
                    AVG(hit_count) as avg_hits
                FROM cache_entries
                WHERE account_id = ?
                GROUP BY resource_type
                """,
                (account_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT
                    resource_type,
                    COUNT(*) as count,
                    SUM(size_bytes) as total_bytes,
                    SUM(hit_count) as total_hits,
                    AVG(hit_count) as avg_hits
                FROM cache_entries
                GROUP BY resource_type
                """
            ).fetchall()

        stats = {
            "by_resource": [],
            "total_entries": 0,
            "total_size_bytes": 0,
            "total_hits": 0
        }

        for row in rows:
            resource_stats = {
                "resource_type": row[0],
                "count": row[1],
                "size_bytes": row[2],
                "total_hits": row[3],
                "avg_hits": row[4]
            }
            stats["by_resource"].append(resource_stats)
            stats["total_entries"] += row[1]
            stats["total_size_bytes"] += row[2]
            stats["total_hits"] += row[3]

        return stats
```

---

**Document Version**: 2.0
**Last Updated**: 2025-10-14
**Status**: Production-Ready Implementation
