"""Load a tool surface backed by the fake Graph.

The real server modules run unchanged; only the HTTP transport, the access
token, the signed-in account list and retry sleeps are replaced. Each case
gets a fresh fake Graph and a fresh cache database, so cases cannot leak
state into each other.
"""

from __future__ import annotations

import importlib
import os
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from m365_mcp import auth, cache, cache_config
from m365_mcp import graph as graph_module

from .fake_graph import ACCOUNT_EMAIL, ACCOUNT_ID, FakeGraph

SURFACES = ("legacy", "unified")

LEGACY_SURFACE_REMOVED = (
    "The legacy 85-tool surface was removed in v1.0.0. To re-run the legacy "
    "baseline, check out the git tag v0.2.3-final in a worktree; see "
    "'Running the legacy baseline' in evals/README.md."
)


class _NoSleepTime:
    """``time`` stand-in for ``graph.py`` whose ``sleep`` returns at once."""

    def __getattr__(self, name: str) -> Any:
        return getattr(time, name)

    @staticmethod
    def sleep(seconds: float) -> None:
        """Skip retry back-off so throttling paths run instantly."""


@dataclass
class Surface:
    """A running tool surface for one evaluation case."""

    name: str
    server: Any
    graph: FakeGraph
    sandbox: Path


def _load_server(name: str, toolsets: str | None) -> Any:
    """Return the FastMCP server object for ``name``."""
    if name == "legacy":
        raise RuntimeError(LEGACY_SURFACE_REMOVED)
    if name == "unified":
        if toolsets:
            os.environ["M365_MCP_TOOLSETS"] = toolsets
        try:
            registry = importlib.import_module("m365_mcp.tools.registry")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "The unified surface is not implemented yet "
                "(m365_mcp.tools.registry is missing; see task U2.2)."
            ) from exc
        return registry.build_server()
    raise ValueError(f"Unknown surface {name!r}; expected one of {SURFACES}")


def _reset_cache(db_path: Path) -> None:
    """Point the cache at a fresh database and drop any open manager."""
    os.environ["M365_MCP_CACHE_DB_PATH"] = str(db_path)
    cache_config.CACHE_DB_PATH = str(db_path)
    if hasattr(cache, "CACHE_DB_PATH"):
        setattr(cache, "CACHE_DB_PATH", str(db_path))  # noqa: B010
    if cache._cache_manager is not None:
        cache._cache_manager.close()
        cache._cache_manager = None


def _fake_accounts() -> list[Any]:
    fields = auth.Account._fields
    values: dict[str, str] = {
        "username": ACCOUNT_EMAIL,
        "account_id": ACCOUNT_ID,
        "account_type": "personal",
        "email": ACCOUNT_EMAIL,
        "display_name": "Alex Morgan",
    }
    return [auth.Account(**{f: values[f] for f in fields})]


@contextmanager
def open_surface(
    name: str, anchor: date, toolsets: str | None = None
) -> Iterator[Surface]:
    """Yield a surface wired to a freshly seeded fake Graph."""
    fake = FakeGraph.seeded(anchor)

    # A bare Graph client ID and cache key, so ``_load_server`` (which needs
    # both) works even when the caller never set real ones. Scoped to this
    # context and restored on exit, not a module-level default: merely
    # importing this module must never shadow a real M365_MCP_CLIENT_ID for
    # the rest of the process (see tests/test_eval_surface_env_isolation.py
    # — this used to break the live integration tests).
    env_defaults = {
        "M365_MCP_CLIENT_ID": "eval-client-id",
        "M365_MCP_CACHE_KEY": "eval-cache-key-not-secret-0000000000",
    }
    env_originals = {key: os.environ.get(key) for key in env_defaults}
    for key, value in env_defaults.items():
        os.environ.setdefault(key, value)

    try:
        yield from _open_surface_dir(name, toolsets, fake)
    finally:
        for key, original in env_originals.items():
            if original is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original


def _open_surface_dir(
    name: str, toolsets: str | None, fake: FakeGraph
) -> Iterator[Surface]:
    """The rest of ``open_surface``, run with the env defaults already set."""
    with tempfile.TemporaryDirectory(prefix="m365-eval-") as tmp:
        tmp_path = Path(tmp)
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        (sandbox / "report.pdf").write_bytes(b"%PDF-1.4 fake report\n")
        (sandbox / "notes-new.txt").write_text("milk\neggs\nbread\n")
        (sandbox / "photo.jpg").write_bytes(b"\xff\xd8\xff fake jpeg")
        (sandbox / ".env").write_text("SECRET=do-not-upload\n")
        _reset_cache(tmp_path / "cache.db")

        real_client = httpx.Client

        class RoutedClient(real_client):  # type: ignore[valid-type, misc]
            """``httpx.Client`` that always talks to the fake Graph.

            A subclass, not a function, so libraries that subclass
            ``httpx.Client`` on import (authlib) keep working.
            """

            def __init__(self, *args: Any, **kwargs: Any) -> None:
                kwargs["transport"] = fake.transport()
                super().__init__(*args, **kwargs)

        def fake_token(*args: Any, **kwargs: Any) -> str:
            return "fake-token"

        fake_http = real_client(transport=fake.transport(), follow_redirects=True)
        patches: list[tuple[Any, str, Any]] = [
            (graph_module, "_client", fake_http),
            (graph_module, "get_token", fake_token),
            (graph_module, "time", _NoSleepTime()),
            (auth, "get_token", fake_token),
            (auth, "list_accounts", _fake_accounts),
            (httpx, "Client", RoutedClient),
        ]
        originals = [(obj, attr, getattr(obj, attr)) for obj, attr, _ in patches]
        cwd = os.getcwd()
        for obj, attr, value in patches:
            setattr(obj, attr, value)
        os.chdir(sandbox)
        try:
            server = _load_server(name, toolsets)
            yield Surface(name=name, server=server, graph=fake, sandbox=sandbox)
        finally:
            os.chdir(cwd)
            for obj, attr, value in reversed(originals):
                setattr(obj, attr, value)
            fake_http.close()
            _reset_cache(tmp_path / "closed.db")
