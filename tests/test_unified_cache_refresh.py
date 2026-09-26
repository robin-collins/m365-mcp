"""Warming and stale-refresh for the unified tools' cache (U2.12 follow-up).

Stale ``m365_list`` / ``m365_get`` entries queue a background refresh, and
startup warming populates the same resource-keyed entries the tools read.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from m365_mcp import cache as cache_module
from m365_mcp import cache_config, resource_cache
from m365_mcp import server as server_module
from m365_mcp.cache import CacheManager
from m365_mcp.cache_config import CACHE_WARMING_OPERATIONS, CacheState
from m365_mcp.cache_warming import CacheWarmer
from m365_mcp.tool_specs import load_tool_spec
from m365_mcp.tools import handlers, registry

ACCOUNT = "account-1"
ARGS = {"resource": "email", "limit": 5}
LIST_OUTPUT = load_tool_spec("m365_list")["examples"][0]["output"]


class _Clock:
    def __init__(self) -> None:
        self.now = 2_000_000.0

    def time(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    fake = _Clock()
    monkeypatch.setattr(cache_module, "time", SimpleNamespace(time=fake.time))
    return fake


@pytest.fixture
def manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: _Clock):
    instance = CacheManager(db_path=str(tmp_path / "c.db"), encryption_enabled=False)
    monkeypatch.setattr(cache_module, "_cache_manager", instance)
    monkeypatch.setattr(cache_module, "CACHE_WARMING_ENABLED", True)
    yield instance
    instance.close()


def _tasks(manager: CacheManager) -> list[dict[str, Any]]:
    with manager._db() as conn:
        rows = conn.execute(
            "SELECT account_id, operation, parameters_json, status FROM cache_tasks"
        ).fetchall()
    return [dict(r) for r in rows]


def _make_stale(clock: _Clock, resource: str = "email") -> None:
    policy = cache_config.RESOURCE_TTL_POLICIES[resource]
    clock.now += policy.fresh_seconds + 1


def test_stale_hit_queues_a_unified_refresh(manager, clock) -> None:
    fetch_calls = []

    def fetch():
        fetch_calls.append(1)
        return {"n": len(fetch_calls)}

    call = ("m365_list", dict(ARGS))
    resource_cache.get_or_fetch(ACCOUNT, "email", ARGS, fetch, refresh_call=call)
    assert _tasks(manager) == [], "a miss queues nothing"
    resource_cache.get_or_fetch(ACCOUNT, "email", ARGS, fetch, refresh_call=call)
    assert _tasks(manager) == [], "a fresh hit queues nothing"

    _make_stale(clock)
    served = resource_cache.get_or_fetch(
        ACCOUNT, "email", ARGS, fetch, refresh_call=call
    )
    assert served == {"n": 1}, "the stale value is served immediately"
    (task,) = _tasks(manager)
    assert task["account_id"] == ACCOUNT
    assert task["operation"] == "unified:m365_list"
    assert json.loads(task["parameters_json"]) == ARGS

    resource_cache.get_or_fetch(ACCOUNT, "email", ARGS, fetch, refresh_call=call)
    assert len(_tasks(manager)) == 1, "no duplicate task while one is queued"


def test_no_refresh_task_without_a_refresh_call(manager, clock) -> None:
    resource_cache.get_or_fetch(ACCOUNT, "email", ARGS, lambda: {"n": 1})
    _make_stale(clock)
    resource_cache.get_or_fetch(ACCOUNT, "email", ARGS, lambda: {"n": 2})
    assert _tasks(manager) == []


def test_peek_state_reports_cache_state_without_side_effects(manager, clock) -> None:
    assert resource_cache.peek_state(ACCOUNT, "email", ARGS) is None
    resource_cache.get_or_fetch(ACCOUNT, "email", ARGS, lambda: {"n": 1})
    assert resource_cache.peek_state(ACCOUNT, "email", ARGS) == CacheState.FRESH
    _make_stale(clock)
    assert resource_cache.peek_state(ACCOUNT, "email", ARGS) == CacheState.STALE
    assert _tasks(manager) == []


def test_refresh_executor_reruns_the_tool_and_stores_the_result(
    manager, monkeypatch
) -> None:
    calls: list[dict[str, Any]] = []

    def handler(args: dict[str, Any]) -> dict[str, Any]:
        calls.append(args)
        return json.loads(json.dumps(LIST_OUTPUT))

    monkeypatch.setattr(
        handlers, "HANDLERS", {**handlers.HANDLERS, "m365_list": handler}
    )
    monkeypatch.setattr(
        registry, "resolve_account_id", lambda value=None: value or ACCOUNT
    )
    asyncio.run(
        server_module._execute_cache_refresh_tool(
            ACCOUNT, "unified:m365_list", dict(ARGS)
        )
    )
    assert len(calls) == 1
    assert resource_cache.peek_state(ACCOUNT, "email", ARGS) == CacheState.FRESH
    # A later user call is now a cache hit.
    resource_cache.get_or_fetch(ACCOUNT, "email", ARGS, lambda: pytest.fail("miss"))


def test_refresh_executor_rejects_unknown_operations() -> None:
    with pytest.raises(ValueError, match="Unsupported cache refresh operation"):
        asyncio.run(server_module._execute_cache_refresh_tool(ACCOUNT, "nonsense", {}))


def test_warming_operations_name_unified_tools() -> None:
    assert CACHE_WARMING_OPERATIONS, "warming must not be empty"
    for operation in CACHE_WARMING_OPERATIONS:
        assert operation["operation"].startswith("unified:m365_")
        assert operation["resource"] in resource_cache.RESOURCES
        assert operation["params"]["resource"] == operation["resource"]


def test_warmer_skips_fresh_and_warms_missing_entries(manager, clock) -> None:
    executed: list[tuple[str, str, dict[str, Any]]] = []

    def executor(account_id: str, operation: str, params: dict[str, Any]) -> Any:
        executed.append((account_id, operation, params))
        # The real executor stores through the resource cache.
        resource_cache.get_or_fetch(
            account_id,
            params["resource"],
            params,
            lambda: {"warmed": True},
            refresh=True,
        )
        return {"warmed": True}

    first = CACHE_WARMING_OPERATIONS[0]
    resource_cache.get_or_fetch(
        ACCOUNT, first["resource"], first["params"], lambda: {"already": True}
    )
    warmer = CacheWarmer(manager, executor, [{"account_id": ACCOUNT, "username": "u"}])
    queue = warmer._build_warming_queue()
    for item in queue:
        item["throttle_sec"] = 0
    asyncio.run(warmer._warming_loop(queue))

    warmed_params = [params for _, _, params in executed]
    assert first["params"] not in warmed_params, "the fresh entry is skipped"
    assert len(executed) == len(CACHE_WARMING_OPERATIONS) - 1
    assert warmer.operations_skipped == 1 and warmer.operations_failed == 0
    for operation in CACHE_WARMING_OPERATIONS:
        state = resource_cache.peek_state(
            ACCOUNT, operation["resource"], operation["params"]
        )
        assert state == CacheState.FRESH
