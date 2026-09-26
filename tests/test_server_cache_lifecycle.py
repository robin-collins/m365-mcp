from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.m365_mcp import cache, cache_config, server, warming_status
from src.m365_mcp.cache import CacheManager


@pytest.mark.asyncio
async def test_cache_runtime_disabled_leaves_behavior_unchanged(monkeypatch) -> None:
    """Disabled warming should not create cache services or keep a provider."""
    warming_status.set_warming_status_provider(MagicMock())
    monkeypatch.setattr(cache_config, "CACHE_WARMING_ENABLED", False)
    monkeypatch.setattr(
        cache,
        "get_cache_manager",
        MagicMock(side_effect=AssertionError("cache manager should not be created")),
    )

    runtime = await server._start_cache_runtime()

    assert runtime is None
    assert warming_status.get_warming_status_provider() is None


@pytest.mark.asyncio
async def test_cache_runtime_enabled_reports_worker_and_stops_cleanly(
    tmp_path,
    monkeypatch,
) -> None:
    """Enabled warming should wire the worker as the status provider."""
    manager = CacheManager(
        db_path=str(tmp_path / "runtime.db"),
        encryption_enabled=False,
    )
    monkeypatch.setattr(cache_config, "CACHE_WARMING_ENABLED", True)
    monkeypatch.setattr(cache, "get_cache_manager", lambda: manager)
    monkeypatch.setattr(server, "_get_cache_warming_accounts", list)

    runtime = await server._start_cache_runtime()

    assert runtime is not None
    try:
        assert runtime.worker.is_running is True
        assert warming_status.get_warming_status_provider() is runtime.worker

        provider = warming_status.get_warming_status_provider()
        assert provider is not None
        status = provider.get_warming_status()
        assert status["is_warming"] is False
        assert status["operations_total"] == 0
    finally:
        await runtime.stop()

    assert runtime.worker.is_running is False
    assert warming_status.get_warming_status_provider() is None
