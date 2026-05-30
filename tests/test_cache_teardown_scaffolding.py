from __future__ import annotations

from pathlib import Path

import pytest

from src.m365_mcp.cache import CacheManager


@pytest.mark.xfail(
    not hasattr(CacheManager, "close"),
    reason="Finding 8: CacheManager does not yet expose explicit teardown.",
    strict=True,
)
def test_cache_manager_exposes_explicit_close() -> None:
    """Require an explicit teardown API before Windows DB deletion tests run."""
    assert callable(getattr(CacheManager, "close", None))


@pytest.mark.skipif(
    not hasattr(CacheManager, "close"),
    reason="CacheManager.close() is added in the lifecycle hardening phase.",
)
def test_cache_manager_close_releases_database_for_deletion(
    tmp_path: Path,
) -> None:
    """Document the expected Windows-safe teardown behavior."""
    db_path = tmp_path / "cache.db"
    manager = CacheManager(db_path=str(db_path), encryption_enabled=False)
    close = getattr(manager, "close", None)
    assert callable(close)

    manager.set_cached("account-1", "email_list", {}, {"emails": []})
    close()
    db_path.unlink()

    assert not db_path.exists()
