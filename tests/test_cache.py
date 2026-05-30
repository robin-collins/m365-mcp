"""
Tests for encrypted cache manager.
"""

import pytest
import tempfile
from pathlib import Path
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from src.m365_mcp import cache as cache_module
from src.m365_mcp.cache import CacheManager, CacheState
from src.m365_mcp.cache_config import (
    CONNECTION_POOL_SIZE,
    CONNECTION_TIMEOUT,
    SQLCIPHER_SETTINGS,
    generate_cache_key,
)
from src.m365_mcp.encryption import EncryptionKeyManager


@pytest.fixture
def temp_cache_db():
    """Create temporary cache database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    yield str(db_path)

    # Cleanup
    if db_path.exists():
        db_path.unlink()


@pytest.fixture
def cache_manager(temp_cache_db):
    """Create cache manager instance for testing."""
    manager = CacheManager(db_path=temp_cache_db, encryption_enabled=True)
    yield manager
    manager.close()


@pytest.fixture
def cache_manager_no_encryption(temp_cache_db):
    """Create cache manager without encryption for testing."""
    manager = CacheManager(db_path=temp_cache_db, encryption_enabled=False)
    yield manager
    manager.close()


class TestCacheBasics:
    """Test basic cache operations."""

    def test_cache_uses_configured_pool_size_by_default(self, temp_cache_db):
        """Default pool size should come from cache configuration."""
        manager = CacheManager(db_path=temp_cache_db, encryption_enabled=False)

        assert manager.max_connections == CONNECTION_POOL_SIZE
        manager.close()

    def test_cache_initialization(self, cache_manager):
        """Test cache manager initializes correctly."""
        assert cache_manager is not None
        assert cache_manager.db_path.exists()
        assert cache_manager.encryption_enabled is True

    def test_cache_initialization_no_encryption(self, cache_manager_no_encryption):
        """Test cache manager initializes without encryption."""
        assert cache_manager_no_encryption is not None
        assert cache_manager_no_encryption.encryption_enabled is False

    def test_set_and_get_cached(self, cache_manager):
        """Test basic set and get operations."""
        account_id = "test-account-123"
        resource_type = "folder_get_tree"
        params = {"folder_id": "root"}
        data = {"folders": ["Inbox", "Sent", "Draft"]}

        # Set cache
        cache_manager.set_cached(account_id, resource_type, params, data)

        # Get cache
        result = cache_manager.get_cached(account_id, resource_type, params)

        assert result is not None
        cached_data, state = result
        assert cached_data == data
        assert state == CacheState.FRESH

    def test_cache_miss(self, cache_manager):
        """Test cache miss returns None."""
        result = cache_manager.get_cached(
            "nonexistent-account", "email_list", {"folder_id": "inbox"}
        )
        assert result is None

    def test_cache_key_generation(self):
        """Test cache key generation is consistent."""
        key1 = generate_cache_key("acc1", "email_list", {"folder": "inbox"})
        key2 = generate_cache_key("acc1", "email_list", {"folder": "inbox"})
        key3 = generate_cache_key("acc1", "email_list", {"folder": "sent"})

        assert key1 == key2
        assert key1 != key3

    def test_cache_operations_across_threads(self, tmp_path):
        """Connections reused from the pool should work across worker threads."""
        manager = CacheManager(
            db_path=str(tmp_path / "threaded.db"),
            encryption_enabled=False,
            max_connections=2,
        )

        def round_trip(index: int) -> dict[str, int]:
            params = {"index": index}
            data = {"value": index}
            manager.set_cached("thread-account", "email_list", params, data)
            result = manager.get_cached("thread-account", "email_list", params)
            assert result is not None
            cached_data, state = result
            assert state == CacheState.FRESH
            return cached_data

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(round_trip, range(24)))

        assert results == [{"value": index} for index in range(24)]
        manager.close()

    def test_erroring_connection_is_not_returned_to_pool(self, tmp_path):
        """Connections that error should be discarded instead of reused."""
        manager = CacheManager(
            db_path=str(tmp_path / "poisoned.db"),
            encryption_enabled=False,
            max_connections=1,
        )

        with manager._db():
            pass

        assert len(manager._connection_pool) == 1

        with pytest.raises(RuntimeError, match="boom"):
            with manager._db():
                raise RuntimeError("boom")

        assert manager._connection_pool == []
        manager.close()

    def test_cache_initialization_recovers_corrupt_database(self, tmp_path):
        """Recoverable startup corruption should recreate an empty cache DB."""
        db_path = tmp_path / "corrupt.db"
        db_path.write_bytes(b"not a sqlite database")

        manager = CacheManager(db_path=str(db_path), encryption_enabled=False)

        try:
            assert manager.get_stats()["entry_count"] == 0
            manager.set_cached("account-1", "email_list", {}, {"emails": []})
            assert manager.get_cached("account-1", "email_list", {}) is not None
        finally:
            manager.close()

    @pytest.mark.skipif(
        not cache_module.USING_SQLCIPHER,
        reason="SQLCipher is required to exercise encrypted key mismatch recovery.",
    )
    def test_cache_initialization_recovers_encrypted_key_mismatch(
        self,
        tmp_path,
        monkeypatch,
    ):
        """A stale encrypted cache with the wrong key should be recreated."""
        db_path = tmp_path / "key_mismatch.db"
        first_key = EncryptionKeyManager.generate_key()
        second_key = EncryptionKeyManager.generate_key()

        monkeypatch.setattr(
            EncryptionKeyManager,
            "get_or_create_key",
            staticmethod(lambda: first_key),
        )
        first_manager = CacheManager(db_path=str(db_path), encryption_enabled=True)
        first_manager.set_cached("account-1", "email_list", {}, {"emails": [1]})
        first_manager.close()

        monkeypatch.setattr(
            EncryptionKeyManager,
            "get_or_create_key",
            staticmethod(lambda: second_key),
        )
        recovered_manager = CacheManager(db_path=str(db_path), encryption_enabled=True)

        try:
            assert recovered_manager.get_cached("account-1", "email_list", {}) is None
            recovered_manager.set_cached("account-1", "email_list", {}, {"emails": [2]})
            assert (
                recovered_manager.get_cached("account-1", "email_list", {})[0]
                == {"emails": [2]}
            )
        finally:
            recovered_manager.close()

    def test_stale_cache_entry_enqueues_background_refresh(
        self,
        tmp_path,
        monkeypatch,
    ):
        """Stale reads should enqueue one refresh task when warming is enabled."""
        monkeypatch.setattr(cache_module, "CACHE_WARMING_ENABLED", True)
        manager = CacheManager(
            db_path=str(tmp_path / "stale_refresh.db"),
            encryption_enabled=False,
        )
        params = {"folder_id": "inbox"}

        try:
            manager.set_cached("account-1", "email_list", params, {"emails": []})
            cache_key = generate_cache_key("account-1", "email_list", params)
            with manager._db() as conn:
                conn.execute(
                    "UPDATE cache_entries SET created_at = ? WHERE cache_key = ?",
                    (time.time() - 180, cache_key),
                )

            result = manager.get_cached("account-1", "email_list", params)
            assert result is not None
            _, state = result
            assert state == CacheState.STALE

            # A second stale read should not duplicate an existing queued refresh.
            manager.get_cached("account-1", "email_list", params)

            tasks = manager.list_tasks(account_id="account-1", status="queued")
            assert len(tasks) == 1
            assert tasks[0]["operation"] == "email_list"
            assert tasks[0]["parameters"] == params
        finally:
            manager.close()

    def test_stale_cache_entry_does_not_enqueue_when_disabled(
        self,
        tmp_path,
        monkeypatch,
    ):
        """The default disabled flag should leave stale cache reads unchanged."""
        monkeypatch.setattr(cache_module, "CACHE_WARMING_ENABLED", False)
        manager = CacheManager(
            db_path=str(tmp_path / "stale_no_refresh.db"),
            encryption_enabled=False,
        )
        params = {"folder_id": "inbox"}

        try:
            manager.set_cached("account-1", "email_list", params, {"emails": []})
            cache_key = generate_cache_key("account-1", "email_list", params)
            with manager._db() as conn:
                conn.execute(
                    "UPDATE cache_entries SET created_at = ? WHERE cache_key = ?",
                    (time.time() - 180, cache_key),
                )

            result = manager.get_cached("account-1", "email_list", params)
            assert result is not None
            _, state = result
            assert state == CacheState.STALE
            assert manager.list_tasks(account_id="account-1") == []
        finally:
            manager.close()


class TestCacheCompression:
    """Test compression functionality."""

    def test_small_entry_no_compression(self, cache_manager):
        """Test small entries are not compressed."""
        account_id = "test-account"
        resource_type = "email_get"
        params = {"email_id": "123"}
        data = {"subject": "Test", "body": "Small email"}

        cache_manager.set_cached(account_id, resource_type, params, data)

        # Check database directly
        cache_key = generate_cache_key(account_id, resource_type, params)
        with cache_manager._db() as conn:
            cursor = conn.execute(
                "SELECT is_compressed FROM cache_entries WHERE cache_key = ?",
                (cache_key,),
            )
            row = cursor.fetchone()
            assert row["is_compressed"] == 0

    def test_large_entry_compression(self, cache_manager):
        """Test large entries are compressed."""
        account_id = "test-account"
        resource_type = "email_list"
        params = {"folder_id": "inbox"}

        # Create large data (>50KB)
        data = {"emails": [{"id": str(i), "subject": "X" * 1000} for i in range(100)]}

        cache_manager.set_cached(account_id, resource_type, params, data)

        # Check database directly
        cache_key = generate_cache_key(account_id, resource_type, params)
        with cache_manager._db() as conn:
            cursor = conn.execute(
                "SELECT is_compressed FROM cache_entries WHERE cache_key = ?",
                (cache_key,),
            )
            row = cursor.fetchone()
            assert row["is_compressed"] == 1

        # Verify data is still retrievable
        result = cache_manager.get_cached(account_id, resource_type, params)
        assert result is not None
        cached_data, _ = result
        assert cached_data == data


class TestCacheTTL:
    """Test TTL and state detection."""

    def test_fresh_state(self, cache_manager):
        """Test fresh cache state."""
        account_id = "test-account"
        resource_type = "folder_get_tree"
        params = {"folder_id": "root"}
        data = {"folders": ["Inbox"]}

        cache_manager.set_cached(account_id, resource_type, params, data)

        # Immediately retrieve (should be FRESH)
        result = cache_manager.get_cached(account_id, resource_type, params)
        assert result is not None
        _, state = result
        assert state == CacheState.FRESH

    def test_stale_state(self, cache_manager, monkeypatch):
        """Test stale cache state."""
        account_id = "test-account"
        resource_type = "folder_get_tree"  # fresh=1800s, stale=7200s
        params = {"folder_id": "root"}
        data = {"folders": ["Inbox"]}

        # Set cache
        cache_manager.set_cached(account_id, resource_type, params, data)

        # Modify created_at to simulate age
        cache_key = generate_cache_key(account_id, resource_type, params)
        old_time = time.time() - 3600  # 1 hour ago (past fresh, within stale)

        with cache_manager._db() as conn:
            conn.execute(
                "UPDATE cache_entries SET created_at = ? WHERE cache_key = ?",
                (old_time, cache_key),
            )

        # Retrieve (should be STALE)
        result = cache_manager.get_cached(account_id, resource_type, params)
        assert result is not None
        _, state = result
        assert state == CacheState.STALE

    def test_expired_state(self, cache_manager):
        """Test expired cache returns None."""
        account_id = "test-account"
        resource_type = "folder_get_tree"  # stale=7200s
        params = {"folder_id": "root"}
        data = {"folders": ["Inbox"]}

        # Set cache
        cache_manager.set_cached(account_id, resource_type, params, data)

        # Modify created_at to simulate old age
        cache_key = generate_cache_key(account_id, resource_type, params)
        old_time = time.time() - 10000  # Way past stale threshold

        with cache_manager._db() as conn:
            conn.execute(
                "UPDATE cache_entries SET created_at = ? WHERE cache_key = ?",
                (old_time, cache_key),
            )

        # Retrieve (should be None - expired)
        result = cache_manager.get_cached(account_id, resource_type, params)
        assert result is None


class TestCacheInvalidation:
    """Test cache invalidation."""

    def test_invalidate_exact_match(self, cache_manager):
        """Test invalidation with exact pattern."""
        account_id = "test-account"

        # Set multiple cache entries
        for i in range(3):
            cache_manager.set_cached(
                account_id, "email_list", {"folder_id": f"folder-{i}"}, {"emails": []}
            )

        # Invalidate specific entry
        pattern = generate_cache_key(
            account_id, "email_list", {"folder_id": "folder-1"}
        )
        count = cache_manager.invalidate_pattern(pattern)

        assert count == 1

    def test_invalidate_wildcard(self, cache_manager):
        """Test invalidation with wildcard pattern."""
        account_id = "test-account"

        # Set entries for different resource types
        cache_manager.set_cached(
            account_id, "email_list", {"folder": "inbox"}, {"emails": []}
        )
        cache_manager.set_cached(
            account_id, "email_get", {"id": "123"}, {"subject": "Test"}
        )
        cache_manager.set_cached(account_id, "folder_list", {}, {"folders": []})

        # Invalidate all email_* entries
        count = cache_manager.invalidate_pattern("email_*")

        assert count >= 2  # Should invalidate email_list and email_get

    def test_invalidate_by_account(self, cache_manager):
        """Test invalidating all entries for an account."""
        # Set entries for different accounts
        cache_manager.set_cached("account-1", "email_list", {}, {"emails": []})
        cache_manager.set_cached("account-2", "email_list", {}, {"emails": []})
        cache_manager.set_cached("account-1", "folder_list", {}, {"folders": []})

        # Invalidate all for account-1
        count = cache_manager.invalidate_pattern("*account-1*")

        assert count == 2


class TestCacheCleanup:
    """Test cache cleanup functionality."""

    def test_cleanup_expired(self, cache_manager):
        """Test manual cleanup of expired entries."""
        account_id = "test-account"
        resource_type = "email_list"

        # Add entry
        cache_manager.set_cached(
            account_id, resource_type, {"folder": "inbox"}, {"emails": []}
        )

        # Make it expired
        cache_key = generate_cache_key(account_id, resource_type, {"folder": "inbox"})
        old_time = time.time() - 10000

        with cache_manager._db() as conn:
            conn.execute(
                "UPDATE cache_entries SET created_at = ?, expires_at = ? WHERE cache_key = ?",
                (old_time, old_time, cache_key),
            )

        # Cleanup
        count = cache_manager.cleanup_expired()

        assert count == 1

        # Verify entry is gone
        result = cache_manager.get_cached(
            account_id, resource_type, {"folder": "inbox"}
        )
        assert result is None


class TestCacheStats:
    """Test cache statistics."""

    def test_get_stats_empty(self, cache_manager):
        """Test stats for empty cache."""
        stats = cache_manager.get_stats()

        assert stats["entry_count"] == 0
        assert stats["total_bytes"] == 0
        assert stats["usage_percent"] >= 0

    def test_get_stats_with_entries(self, cache_manager):
        """Test stats with cache entries."""
        # Add entries
        cache_manager.set_cached("account-1", "email_list", {}, {"emails": []})
        cache_manager.set_cached("account-1", "folder_list", {}, {"folders": []})
        cache_manager.set_cached("account-2", "email_list", {}, {"emails": []})

        stats = cache_manager.get_stats()

        assert stats["entry_count"] == 3
        assert stats["total_bytes"] > 0
        assert len(stats["by_account"]) == 2
        assert "account-1" in stats["by_account"]
        assert "account-2" in stats["by_account"]

    def test_hit_count_tracking(self, cache_manager):
        """Test cache hit count is tracked."""
        account_id = "test-account"
        resource_type = "email_list"
        params = {"folder": "inbox"}

        cache_manager.set_cached(account_id, resource_type, params, {"emails": []})

        # Access multiple times
        for _ in range(5):
            cache_manager.get_cached(account_id, resource_type, params)

        # Check hit count in database
        cache_key = generate_cache_key(account_id, resource_type, params)
        with cache_manager._db() as conn:
            cursor = conn.execute(
                "SELECT hit_count FROM cache_entries WHERE cache_key = ?", (cache_key,)
            )
            row = cursor.fetchone()
            assert row["hit_count"] == 5


class TestCacheEncryption:
    """Test encryption functionality."""

    def test_connection_uses_configured_timeout_and_sqlcipher_pragmas(
        self,
        tmp_path,
        monkeypatch,
    ):
        """Connection setup should apply central cache configuration."""
        statements: list[str] = []
        captured: dict[str, object] = {}

        class FakeConnection:
            row_factory = None

            def execute(self, statement: str):
                statements.append(statement)
                return self

        def fake_connect(path: str, **kwargs):
            captured["path"] = path
            captured["kwargs"] = kwargs
            return FakeConnection()

        monkeypatch.setattr(
            cache_module,
            "sqlite3",
            SimpleNamespace(connect=fake_connect, Row=object),
        )

        manager = CacheManager.__new__(CacheManager)
        manager.db_path = tmp_path / "configured.db"
        manager.encryption_enabled = True
        manager.encryption_key = EncryptionKeyManager.generate_key()

        conn = manager._create_connection()

        assert isinstance(conn, FakeConnection)
        assert captured["path"] == str(manager.db_path)
        assert captured["kwargs"] == {
            "timeout": CONNECTION_TIMEOUT,
            "check_same_thread": False,
        }
        assert EncryptionKeyManager.sqlcipher_key_pragma(
            manager.encryption_key
        ) in statements
        for setting, value in SQLCIPHER_SETTINGS.items():
            pragma_value = int(value) if isinstance(value, bool) else value
            assert f"PRAGMA {setting} = {pragma_value}" in statements
        assert "PRAGMA cipher_compatibility = 4" in statements

    def test_encryption_requires_sqlcipher(self, tmp_path, monkeypatch):
        """Encrypted mode should fail loudly without SQLCipher."""
        monkeypatch.setattr(cache_module, "USING_SQLCIPHER", False)

        with pytest.raises(ImportError, match="sqlcipher3 is unavailable"):
            CacheManager(
                db_path=str(tmp_path / "missing_sqlcipher.db"),
                encryption_enabled=True,
            )

    def test_plaintext_mode_allows_sqlite_fallback(self, tmp_path, monkeypatch):
        """Plaintext mode can still use stdlib sqlite fallback explicitly."""
        monkeypatch.setattr(cache_module, "USING_SQLCIPHER", False)

        manager = CacheManager(
            db_path=str(tmp_path / "plaintext.db"),
            encryption_enabled=False,
        )

        assert manager.encryption_enabled is False
        manager.close()

    def test_encrypted_cache_creation(self, cache_manager):
        """Test encrypted cache is created."""
        assert cache_manager.encryption_enabled is True
        assert cache_manager.encryption_key is not None

    def test_data_encrypted_at_rest(self, cache_manager):
        """Test data is encrypted in database file."""
        account_id = "test-account"
        sensitive_data = {"password": "super-secret-123", "token": "abc123"}

        cache_manager.set_cached(account_id, "test_type", {}, sensitive_data)

        # Read raw database file
        with open(cache_manager.db_path, "rb") as f:
            raw_content = f.read()

        # Sensitive data should NOT appear in plaintext
        assert b"super-secret-123" not in raw_content
        assert b"abc123" not in raw_content
