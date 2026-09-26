"""HTTP transport hardening (task H1, audit BP6)."""

from __future__ import annotations

import logging
import sys

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from m365_mcp import http_security, server

TOKEN = "t" * 40


def _app(allowed: list[str] | None = None) -> Starlette:
    async def ok(request):
        return PlainTextResponse("ok")

    return Starlette(
        routes=[Route("/mcp", ok, methods=["GET", "POST"])],
        middleware=[
            Middleware(
                http_security.OriginValidationMiddleware, allowed_origins=allowed
            )
        ],
    )


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost",
        "http://localhost:6274",
        "https://127.0.0.1:8443",
        "http://[::1]:3000",
    ],
)
def test_local_origins_are_allowed_by_default(origin) -> None:
    response = TestClient(_app()).post("/mcp", headers={"Origin": origin})
    assert response.status_code == 200


@pytest.mark.parametrize(
    "origin",
    [
        "http://evil.example",
        "http://localhost.evil.example",
        "http://127.0.0.1.nip.io",
        "null",
        "file://",
    ],
)
def test_foreign_origins_are_rejected(origin) -> None:
    response = TestClient(_app()).post("/mcp", headers={"Origin": origin})
    assert response.status_code == 403
    assert response.json() == {"detail": "Origin not allowed"}


def test_requests_without_origin_are_allowed() -> None:
    assert TestClient(_app()).post("/mcp").status_code == 200


def test_configured_origins_replace_the_default(monkeypatch) -> None:
    monkeypatch.setenv(
        "MCP_ALLOWED_ORIGINS", "https://app.example.com, https://b.example.com"
    )
    allowed = http_security.allowed_origins_from_env()
    client = TestClient(_app(allowed))
    assert (
        client.post("/mcp", headers={"Origin": "https://app.example.com"}).status_code
        == 200
    )
    assert (
        client.post("/mcp", headers={"Origin": "http://localhost"}).status_code == 403
    )


def test_token_comparison_is_constant_time(monkeypatch) -> None:
    calls = []
    real = http_security.hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(http_security.hmac, "compare_digest", spy)
    assert http_security.token_matches(TOKEN, TOKEN)
    assert not http_security.token_matches("x" * 40, TOKEN)
    assert not http_security.token_matches("", TOKEN)
    assert len(calls) == 3


@pytest.fixture
def bearer_client(monkeypatch) -> TestClient:
    monkeypatch.setenv("M365_MCP_CLIENT_ID", "test-client")
    from m365_mcp.tools import registry

    app = server.build_bearer_app(
        registry.build_server("core"), TOKEN, http_security.DEFAULT_ALLOWED_ORIGINS
    )
    return TestClient(app)


def test_bearer_app_checks_token_and_origin(bearer_client) -> None:
    assert bearer_client.get("/health").status_code == 200
    assert bearer_client.post("/mcp").status_code == 401
    wrong = bearer_client.post("/mcp", headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401
    foreign = bearer_client.get("/health", headers={"Origin": "http://evil.example"})
    assert foreign.status_code == 403


@pytest.fixture
def restore_logging():
    """Undo the handlers server.main() installs (they hold captured streams)."""
    loggers = [logging.getLogger()] + [
        logging.getLogger(name) for name in list(logging.root.manager.loggerDict)
    ]
    saved = {lg.name: (list(lg.handlers), lg.level) for lg in loggers}
    yield
    for name in list(logging.root.manager.loggerDict) + ["root"]:
        lg = logging.getLogger() if name == "root" else logging.getLogger(name)
        handlers, level = saved.get(lg.name, ([], logging.NOTSET))
        for handler in list(lg.handlers):
            if handler not in handlers:
                lg.removeHandler(handler)
                handler.close()
        lg.setLevel(level)


def test_oauth_auth_method_fails_at_startup_with_a_clear_message(
    monkeypatch, capsys, tmp_path, restore_logging
) -> None:
    monkeypatch.setenv("M365_MCP_CLIENT_ID", "test-client")
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    monkeypatch.setenv("MCP_AUTH_METHOD", "oauth")
    monkeypatch.setenv("MCP_LOG_DIR", str(tmp_path))
    monkeypatch.setattr(
        sys, "argv", ["m365-mcp", "--env-file", str(tmp_path / "none.env")]
    )
    with pytest.raises(SystemExit) as info:
        server.main()
    assert info.value.code == 1
    err = capsys.readouterr().err
    assert "MCP_AUTH_METHOD=oauth is not supported" in err
    assert "bearer" in err


def test_unknown_auth_method_fails_instead_of_running_without_auth(
    monkeypatch, capsys, tmp_path, restore_logging
) -> None:
    monkeypatch.setenv("M365_MCP_CLIENT_ID", "test-client")
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    monkeypatch.setenv("MCP_AUTH_METHOD", "berer")
    monkeypatch.delenv("MCP_ALLOW_INSECURE", raising=False)
    monkeypatch.setenv("MCP_LOG_DIR", str(tmp_path))
    monkeypatch.setattr(
        sys, "argv", ["m365-mcp", "--env-file", str(tmp_path / "none.env")]
    )
    with pytest.raises(SystemExit) as info:
        server.main()
    assert info.value.code == 1
    assert "Invalid MCP_AUTH_METHOD 'berer'" in capsys.readouterr().err
