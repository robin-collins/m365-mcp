"""Registry-level caching for the unified tools (tasks U2.12, U3.1, U3.2)."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from m365_mcp import resource_cache
from m365_mcp.tool_specs import load_tool_spec
from m365_mcp.tools import handlers

LIST_EXAMPLE = load_tool_spec("m365_list")["examples"][0]
UPDATE_EXAMPLE = load_tool_spec("m365_update")["examples"][0]


@pytest.fixture
def counting(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Replace the m365_list and m365_update handlers with counters."""
    counts = {"m365_list": 0, "m365_update": 0}
    table = dict(handlers.HANDLERS)

    def list_handler(args: dict[str, Any]) -> dict[str, Any]:
        counts["m365_list"] += 1
        return copy.deepcopy(LIST_EXAMPLE["output"])

    def update_handler(args: dict[str, Any]) -> dict[str, Any]:
        counts["m365_update"] += 1
        return copy.deepcopy(UPDATE_EXAMPLE["output"])

    table["m365_list"] = list_handler
    table["m365_update"] = update_handler
    monkeypatch.setattr(handlers, "HANDLERS", table)
    return counts


def test_identical_reads_are_served_from_cache(harness, counting) -> None:
    args = LIST_EXAMPLE["input"]
    first = harness.ok("m365_list", args)
    second = harness.ok("m365_list", args)
    assert counting["m365_list"] == 1
    assert first == second
    assert not any(key.startswith("_cache") for key in json.dumps(second))


def test_refresh_bypasses_the_cache(harness, counting) -> None:
    args = LIST_EXAMPLE["input"]
    harness.ok("m365_list", args)
    harness.ok("m365_list", {**args, "refresh": True})
    assert counting["m365_list"] == 2


def test_different_arguments_are_cached_separately(harness, counting) -> None:
    harness.ok("m365_list", LIST_EXAMPLE["input"])
    harness.ok("m365_list", {**LIST_EXAMPLE["input"], "limit": 2})
    assert counting["m365_list"] == 2


def test_mutations_invalidate_matching_resources(harness, counting) -> None:
    args = LIST_EXAMPLE["input"]
    harness.ok("m365_list", args)
    harness.ok("m365_update", UPDATE_EXAMPLE["input"])
    harness.ok("m365_list", args)
    assert counting == {"m365_list": 2, "m365_update": 1}


def test_failed_mutations_do_not_invalidate(harness, counting, monkeypatch) -> None:
    args = LIST_EXAMPLE["input"]
    harness.ok("m365_list", args)

    def failing(args: dict[str, Any]) -> dict[str, Any]:
        raise ValueError("Invalid id: nope")

    monkeypatch.setitem(handlers.HANDLERS, "m365_update", failing)
    harness.error("m365_update", UPDATE_EXAMPLE["input"])
    harness.ok("m365_list", args)
    assert counting["m365_list"] == 1


def test_cache_failures_fall_back_to_a_direct_call(
    harness, counting, monkeypatch
) -> None:
    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("cache database is locked")

    monkeypatch.setattr(resource_cache, "get_or_fetch", broken)
    monkeypatch.setattr(resource_cache, "invalidate_for_call", broken)
    harness.ok("m365_list", LIST_EXAMPLE["input"])
    harness.ok("m365_update", UPDATE_EXAMPLE["input"])
    assert counting == {"m365_list": 1, "m365_update": 1}


def test_operation_status_is_never_cached(harness, monkeypatch) -> None:
    example = next(
        e
        for e in load_tool_spec("m365_get")["examples"]
        if e["input"]["resource"] == "operation"
    )
    calls: list[dict[str, Any]] = []

    def get_handler(args: dict[str, Any]) -> dict[str, Any]:
        calls.append(args)
        return copy.deepcopy(example["output"])

    monkeypatch.setitem(handlers.HANDLERS, "m365_get", get_handler)
    harness.ok("m365_get", example["input"])
    harness.ok("m365_get", example["input"])
    assert len(calls) == 2
