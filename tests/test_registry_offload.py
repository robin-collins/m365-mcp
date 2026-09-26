"""Synchronous handlers must not run on the event-loop thread (hardening)."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastmcp import Client, FastMCP

from m365_mcp.tools import handlers, registry

DELETE_OK = {
    "resource": "email",
    "id": "x",
    "status": "deleted",
    "recoverable": False,
    "summary": "Deleted the email.",
}
DELETE_ARGS = {"resource": "email", "id": "x", "confirm": True}


@pytest.fixture(autouse=True)
def isolated_registries(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(handlers, "HANDLERS", {})
    monkeypatch.setattr(handlers, "VALIDATION_RULES", {})
    yield


@pytest.fixture(scope="module")
def server() -> FastMCP:
    return registry.build_server("core,extended,admin")


def test_sync_handler_runs_off_the_event_loop_thread(server: FastMCP) -> None:
    seen: list[int] = []

    def handler(args: dict[str, Any]) -> dict[str, Any]:
        seen.append(threading.get_ident())
        return dict(DELETE_OK)

    handlers.register_handler("m365_delete")(handler)

    async def run() -> int:
        async with Client(server) as client:
            result = await client.call_tool("m365_delete", DELETE_ARGS)
            assert not result.is_error
        return threading.get_ident()

    loop_thread = asyncio.run(run())
    assert seen and seen[0] != loop_thread


def test_slow_handlers_overlap_and_do_not_stall_the_loop(server: FastMCP) -> None:
    def handler(args: dict[str, Any]) -> dict[str, Any]:
        time.sleep(0.4)  # a slow Graph call or a retry back-off
        return dict(DELETE_OK)

    handlers.register_handler("m365_delete")(handler)
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    async def run() -> float:
        async with Client(server) as client:
            background = asyncio.create_task(ticker())
            started = time.monotonic()
            await asyncio.gather(
                *(client.call_tool("m365_delete", DELETE_ARGS) for _ in range(3))
            )
            elapsed = time.monotonic() - started
            background.cancel()
            return elapsed

    elapsed = asyncio.run(run())
    assert elapsed < 0.9, f"handlers ran one after another ({elapsed:.2f}s)"
    assert ticks >= 20, f"the event loop was blocked (only {ticks} ticks)"


def test_async_handlers_still_run_on_the_loop(server: FastMCP) -> None:
    seen: list[int] = []

    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        seen.append(threading.get_ident())
        return dict(DELETE_OK)

    handlers.register_handler("m365_delete")(handler)

    async def run() -> int:
        async with Client(server) as client:
            await client.call_tool("m365_delete", DELETE_ARGS)
        return threading.get_ident()

    assert seen == [] and asyncio.run(run()) == seen[0]


def test_concurrency_limit_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(registry.MAX_CONCURRENCY_ENV, "3")
    assert registry.max_concurrency() == 3
    monkeypatch.setenv(registry.MAX_CONCURRENCY_ENV, "0")
    assert registry.max_concurrency() == registry.DEFAULT_MAX_CONCURRENCY
    monkeypatch.setenv(registry.MAX_CONCURRENCY_ENV, "lots")
    assert registry.max_concurrency() == registry.DEFAULT_MAX_CONCURRENCY
    monkeypatch.delenv(registry.MAX_CONCURRENCY_ENV)
    assert registry.max_concurrency() == registry.DEFAULT_MAX_CONCURRENCY
