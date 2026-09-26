"""Tests for the unified-tool resource cache (U2.12)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from m365_mcp import cache as cache_module
from m365_mcp import resource_cache as rc
from m365_mcp.cache import CacheManager
from m365_mcp.cache_config import RESOURCE_TTL_POLICIES
from m365_mcp.tool_specs import load_index, load_tool_spec

ACCOUNT_A = "account-a"
ACCOUNT_B = "account-b"


class _Clock:
    """Controllable replacement for the cache module's ``time``."""

    def __init__(self) -> None:
        self.now = 1_000_000.0

    def time(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    """Drive CacheManager timestamps from a fake clock."""
    fake = _Clock()
    monkeypatch.setattr(cache_module, "time", SimpleNamespace(time=fake.time))
    return fake


@pytest.fixture
def manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: _Clock) -> Any:
    """Install a temporary CacheManager as the process-wide manager."""
    instance = CacheManager(
        db_path=str(tmp_path / "cache.db"), encryption_enabled=False
    )
    monkeypatch.setattr(cache_module, "_cache_manager", instance)
    yield instance
    instance.close()


class _Fetcher:
    """Callable counting how often the cache fell through to Graph."""

    def __init__(self, value: Any) -> None:
        self.value = value
        self.calls = 0

    def __call__(self) -> Any:
        self.calls += 1
        return self.value


def _entry_count(manager: CacheManager, account_id: str, resource: str) -> int:
    with manager._db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM cache_entries "
            "WHERE account_id = ? AND resource_type = ?",
            (account_id, resource),
        ).fetchone()
    return int(row["n"])


def _mutating_tools() -> list[str]:
    names = []
    for name in load_index()["tool_order"]:
        if name.startswith(("account_", "admin_")):
            continue
        if not load_tool_spec(name)["annotations"]["readOnlyHint"]:
            names.append(name)
    return names


def _resource_enum(tool: str) -> list[str] | None:
    props = load_tool_spec(tool)["inputSchema"].get("properties", {})
    return props.get("resource", {}).get("enum")


# --------------------------------------------------------------------------
# Keys
# --------------------------------------------------------------------------


class TestCacheKey:
    def test_equivalent_requests_share_a_key(self) -> None:
        first = rc.cache_key(
            ACCOUNT_A,
            "email",
            {
                "resource": "email",
                "limit": 10,
                "container_id": "inbox",
                "refresh": True,
                "account_id": "someone@example.com",
                "path": None,
            },
        )
        second = rc.cache_key(
            ACCOUNT_A,
            "email",
            {"container_id": "inbox", "limit": 10, "resource": "email"},
        )
        assert first == second

    def test_nested_parameter_order_does_not_matter(self) -> None:
        first = rc.cache_key(ACCOUNT_A, "email", {"email_filter": {"a": 1, "b": 2}})
        second = rc.cache_key(ACCOUNT_A, "email", {"email_filter": {"b": 2, "a": 1}})
        assert first == second

    def test_different_cursor_params_account_or_resource_differ(
        self,
    ) -> None:
        base = {"container_id": "inbox", "limit": 10}
        key = rc.cache_key(ACCOUNT_A, "email", base)
        assert key != rc.cache_key(ACCOUNT_A, "email", {**base, "cursor": "abc"})
        assert rc.cache_key(
            ACCOUNT_A, "email", {**base, "cursor": "abc"}
        ) != rc.cache_key(ACCOUNT_A, "email", {**base, "cursor": "def"})
        assert key != rc.cache_key(ACCOUNT_A, "email", {**base, "limit": 11})
        assert key != rc.cache_key(ACCOUNT_B, "email", base)
        assert key != rc.cache_key(ACCOUNT_A, "email_folder", base)

    def test_key_does_not_contain_raw_parameter_values(self) -> None:
        key = rc.cache_key(
            ACCOUNT_A,
            "email",
            {"container_id": "secret-folder", "cursor": "secret-cursor"},
        )
        assert key.startswith(f"email:{ACCOUNT_A}:")
        assert "secret" not in key

    def test_unknown_resource_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid resource 'operation'"):
            rc.cache_key(ACCOUNT_A, "operation", {})


# --------------------------------------------------------------------------
# get_or_fetch
# --------------------------------------------------------------------------


class TestGetOrFetch:
    def test_second_call_is_served_from_cache_without_metadata(
        self, manager: CacheManager
    ) -> None:
        value = {"items": [{"id": "m1"}], "next_cursor": None}
        fetch = _Fetcher(value)

        first = rc.get_or_fetch(ACCOUNT_A, "email", {"limit": 5}, fetch)
        second = rc.get_or_fetch(ACCOUNT_A, "email", {"limit": 5}, fetch)

        assert fetch.calls == 1
        assert first == value
        assert second == value
        for result in (first, second):
            assert not any(k.startswith("_cache") for k in result)

    def test_equivalent_params_hit_the_same_entry(self, manager: CacheManager) -> None:
        fetch = _Fetcher({"items": []})
        rc.get_or_fetch(ACCOUNT_A, "email", {"limit": 5}, fetch)
        rc.get_or_fetch(
            ACCOUNT_A,
            "email",
            {"limit": 5, "refresh": False, "account_id": "x", "path": None},
            fetch,
        )
        assert fetch.calls == 1

    def test_refresh_bypasses_read_but_stores_new_value(
        self, manager: CacheManager
    ) -> None:
        rc.get_or_fetch(ACCOUNT_A, "email", {}, _Fetcher({"v": 1}))
        newer = _Fetcher({"v": 2})

        refreshed = rc.get_or_fetch(ACCOUNT_A, "email", {}, newer, refresh=True)
        later = rc.get_or_fetch(ACCOUNT_A, "email", {}, _Fetcher({"v": 3}))

        assert newer.calls == 1
        assert refreshed == {"v": 2}
        assert later == {"v": 2}

    @pytest.mark.parametrize("resource", sorted(RESOURCE_TTL_POLICIES))
    def test_fresh_stale_expired_lifecycle(
        self, manager: CacheManager, clock: _Clock, resource: str
    ) -> None:
        policy = RESOURCE_TTL_POLICIES[resource]
        start = clock.now
        fetch = _Fetcher({"v": 1})
        rc.get_or_fetch(ACCOUNT_A, resource, {}, fetch)

        clock.now = start + policy.fresh_seconds - 1  # fresh
        rc.get_or_fetch(ACCOUNT_A, resource, {}, fetch)
        clock.now = start + policy.stale_seconds - 1  # stale: still served
        rc.get_or_fetch(ACCOUNT_A, resource, {}, fetch)
        assert fetch.calls == 1

        clock.now = start + policy.stale_seconds + 1  # expired
        assert rc.get_or_fetch(ACCOUNT_A, resource, {}, fetch) == {"v": 1}
        assert fetch.calls == 2

    def test_stale_hit_does_not_queue_unrunnable_refresh_task(
        self,
        manager: CacheManager,
        clock: _Clock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(cache_module, "CACHE_WARMING_ENABLED", True)
        policy = RESOURCE_TTL_POLICIES["email"]
        start = clock.now
        fetch = _Fetcher({"v": 1})
        rc.get_or_fetch(ACCOUNT_A, "email", {}, fetch)
        clock.now = start + policy.fresh_seconds + 1

        rc.get_or_fetch(ACCOUNT_A, "email", {}, fetch)

        assert fetch.calls == 1
        assert manager.list_tasks() == []

    def test_accounts_are_isolated(self, manager: CacheManager) -> None:
        rc.get_or_fetch(ACCOUNT_A, "email", {}, _Fetcher({"owner": "a"}))
        fetch_b = _Fetcher({"owner": "b"})
        assert rc.get_or_fetch(ACCOUNT_B, "email", {}, fetch_b) == {"owner": "b"}
        assert fetch_b.calls == 1

    def test_different_cursor_is_a_different_page(self, manager: CacheManager) -> None:
        rc.get_or_fetch(ACCOUNT_A, "email", {"cursor": "p1"}, _Fetcher(1))
        page_two = _Fetcher(2)
        assert rc.get_or_fetch(ACCOUNT_A, "email", {"cursor": "p2"}, page_two) == 2
        assert page_two.calls == 1


# --------------------------------------------------------------------------
# Invalidation
# --------------------------------------------------------------------------


def _populate(accounts: tuple[str, ...] = (ACCOUNT_A, ACCOUNT_B)) -> None:
    for account_id in accounts:
        for resource in rc.RESOURCES:
            rc.get_or_fetch(account_id, resource, {"n": 1}, _Fetcher(1))


class TestInvalidate:
    def test_invalidate_only_named_resources_for_one_account(
        self, manager: CacheManager
    ) -> None:
        _populate()

        removed = rc.invalidate(ACCOUNT_A, ("email", "email_folder"))

        assert removed == 2
        for resource in rc.RESOURCES:
            expected = 0 if resource in ("email", "email_folder") else 1
            assert _entry_count(manager, ACCOUNT_A, resource) == expected
            assert _entry_count(manager, ACCOUNT_B, resource) == 1

    def test_invalidate_leaves_legacy_keys_alone(self, manager: CacheManager) -> None:
        manager.set_cached(ACCOUNT_A, "email_list", {"folder": "inbox"}, [1])
        _populate((ACCOUNT_A,))

        rc.invalidate(ACCOUNT_A, ("email",))

        assert (
            manager.get_cached(ACCOUNT_A, "email_list", {"folder": "inbox"}) is not None
        )

    def test_scope_enum_matches_admin_cache_invalidate_spec(self) -> None:
        spec = load_tool_spec("admin_cache_invalidate")
        enum = spec["inputSchema"]["properties"]["scope"]["enum"]
        assert set(enum) == {*rc.RESOURCES, "all"}
        assert set(RESOURCE_TTL_POLICIES) == set(rc.RESOURCES)

    def test_scope_single_resource_for_one_account(self, manager: CacheManager) -> None:
        _populate()
        assert rc.invalidate_scope("event", account_id=ACCOUNT_A) == 1
        assert _entry_count(manager, ACCOUNT_A, "event") == 0
        assert _entry_count(manager, ACCOUNT_B, "event") == 1

    def test_scope_single_resource_for_all_accounts(
        self, manager: CacheManager
    ) -> None:
        _populate()
        assert rc.invalidate_scope("contact") == 2
        assert _entry_count(manager, ACCOUNT_B, "contact") == 0
        assert _entry_count(manager, ACCOUNT_B, "email") == 1

    def test_scope_all(self, manager: CacheManager) -> None:
        _populate()
        manager.set_cached(ACCOUNT_A, "email_list", {}, [1])

        assert rc.invalidate_scope("all", account_id=ACCOUNT_A) == len(rc.RESOURCES)
        assert _entry_count(manager, ACCOUNT_B, "email") == 1
        assert manager.get_cached(ACCOUNT_A, "email_list", {}) is not None
        assert rc.invalidate_scope("all") == len(rc.RESOURCES)

    def test_scope_unknown_is_rejected(self, manager: CacheManager) -> None:
        with pytest.raises(ValueError, match="Invalid scope 'mail'"):
            rc.invalidate_scope("mail")


# --------------------------------------------------------------------------
# Invalidation matrix
# --------------------------------------------------------------------------


def _matrix_cases() -> list[tuple[str, str | None]]:
    cases: list[tuple[str, str | None]] = []
    for tool in _mutating_tools():
        enum = _resource_enum(tool)
        if enum is None:
            cases.append((tool, None))
        else:
            cases.extend((tool, resource) for resource in enum)
    return cases


class TestInvalidationMatrix:
    def test_every_mutating_tool_has_a_table_entry(self) -> None:
        tools = _mutating_tools()
        assert "m365_move" in tools and "drive_upload" in tools
        assert set(rc.MUTATION_INVALIDATES) == set(tools)
        for tool in tools:
            enum = _resource_enum(tool)
            expected_keys = {rc.ANY_RESOURCE} if enum is None else set(enum)
            assert set(rc.MUTATION_INVALIDATES[tool]) == expected_keys, tool
            for targets in rc.MUTATION_INVALIDATES[tool].values():
                assert set(targets) <= set(rc.RESOURCES), tool

    @pytest.mark.parametrize(
        ("tool", "resource", "expected"),
        [
            ("m365_move", "email", {"email", "email_folder"}),
            ("drive_upload", None, {"drive_item"}),
            ("calendar_respond", None, {"event"}),
            ("email_folder_empty", None, {"email", "email_folder"}),
            ("m365_delete", "calendar", {"calendar", "event"}),
            ("m365_get_content", "drive_item", set()),
        ],
    )
    def test_documented_examples(
        self, tool: str, resource: str | None, expected: set[str]
    ) -> None:
        key = rc.ANY_RESOURCE if resource is None else resource
        assert set(rc.MUTATION_INVALIDATES[tool][key]) == expected

    @pytest.mark.parametrize(("tool", "resource"), _matrix_cases())
    def test_invalidate_for_call_removes_exactly_expected_entries(
        self, manager: CacheManager, tool: str, resource: str | None
    ) -> None:
        _populate()
        key = rc.ANY_RESOURCE if resource is None else resource
        expected = set(rc.MUTATION_INVALIDATES[tool][key])
        args: dict[str, Any] = {"id": "x"}
        if resource is not None:
            args["resource"] = resource

        removed = rc.invalidate_for_call(tool, args, ACCOUNT_A)

        assert removed == len(expected)
        for cached in rc.RESOURCES:
            assert _entry_count(manager, ACCOUNT_A, cached) == (
                0 if cached in expected else 1
            ), (tool, resource, cached)
            assert _entry_count(manager, ACCOUNT_B, cached) == 1

    def test_read_only_tool_invalidates_nothing(self, manager: CacheManager) -> None:
        _populate()
        assert (
            rc.invalidate_for_call("m365_list", {"resource": "email"}, ACCOUNT_A) == 0
        )
        assert _entry_count(manager, ACCOUNT_A, "email") == 1
