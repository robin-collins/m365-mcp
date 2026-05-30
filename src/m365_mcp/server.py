import os
import sys
import signal
import atexit
import argparse
import asyncio
import inspect
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from dotenv import load_dotenv
from importlib.metadata import version, PackageNotFoundError

# Logger will be initialized after argument parsing
logger: logging.Logger | None = None


def _parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Microsoft MCP Server - Provide AI assistants with Microsoft 365 access"
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="Path to .env file (default: .env)",
    )
    return parser.parse_args()


def _setup_signal_handlers() -> None:
    """Setup graceful shutdown handlers."""

    def signal_handler(signum, frame):
        sig_name = signal.Signals(signum).name
        assert logger is not None
        logger.warning(
            f"Received signal {sig_name} ({signum}), shutting down gracefully"
        )
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)


def _log_startup_info() -> None:
    """Log server startup information."""
    assert logger is not None
    # Get version dynamically
    try:
        pkg_version = version("m365-mcp")
    except PackageNotFoundError:
        pkg_version = "dev"

    logger.info("=" * 80)
    logger.info(f"M365 MCP Server Starting v{pkg_version}")
    logger.info("=" * 80)
    logger.info(f"PID: {os.getpid()}")
    logger.info(f"Python: {sys.version}")
    logger.info(f"Working Directory: {os.getcwd()}")
    logger.info("Environment Variables:")
    for key in [
        "M365_MCP_CLIENT_ID",
        "MCP_TRANSPORT",
        "MCP_HOST",
        "MCP_PORT",
        "MCP_AUTH_METHOD",
    ]:
        value = os.getenv(key, "not set")
        # Mask sensitive values
        if "CLIENT_ID" in key and value != "not set":
            value = f"{value[:8]}...{value[-4:]}"
        logger.info(f"  {key}: {value}")
    logger.info("=" * 80)


@dataclass
class CacheRuntime:
    """Owns cache background services for the running server."""

    cache_manager: Any
    worker: Any
    warmer: Any

    async def stop(self) -> None:
        """Stop background services and release cache handles."""
        from .tools import cache_tools

        active_logger = logger or logging.getLogger(__name__)
        try:
            await self.warmer.stop()
        finally:
            await self.worker.stop()
            cache_tools.set_warming_status_provider(None)
            self.cache_manager.close()
            active_logger.info("Cache runtime stopped")


def _get_cache_warming_accounts() -> list[dict[str, str]]:
    """Return authenticated accounts in the shape expected by CacheWarmer."""
    from . import auth

    return [
        {"account_id": account.account_id, "username": account.username}
        for account in auth.list_accounts()
    ]


async def _execute_cache_refresh_tool(
    account_id: str,
    operation: str,
    parameters: dict[str, Any],
) -> Any:
    """Execute a cacheable tool operation for warming or stale refresh."""
    from .tools import contact, email, file, folder

    tool_functions = {
        "contact_list": contact.contact_list.fn,
        "email_list": email.email_list.fn,
        "file_list": file.file_list.fn,
        "folder_get_tree": folder.folder_get_tree.fn,
    }
    tool_function = tool_functions.get(operation)
    if tool_function is None:
        raise ValueError(f"Unsupported cache refresh operation: {operation}")

    call_parameters = dict(parameters)
    call_parameters["account_id"] = account_id
    signature = inspect.signature(tool_function)
    if "force_refresh" in signature.parameters:
        call_parameters["force_refresh"] = True
    if "use_cache" in signature.parameters:
        call_parameters.setdefault("use_cache", True)

    result = tool_function(**call_parameters)
    if asyncio.iscoroutine(result):
        return await result
    return result


async def _execute_background_refresh(
    operation: str,
    parameters: dict[str, Any],
) -> Any:
    """Execute a queued stale-cache refresh operation."""
    call_parameters = dict(parameters)
    account_id = call_parameters.pop("account_id", None)
    if not account_id:
        raise ValueError("Background refresh task is missing account_id")
    return await _execute_cache_refresh_tool(account_id, operation, call_parameters)


async def _execute_warming_operation(
    account_id: str,
    operation: str,
    parameters: dict[str, Any],
) -> Any:
    """Execute a startup cache warming operation."""
    return await _execute_cache_refresh_tool(account_id, operation, parameters)


async def _start_cache_runtime() -> CacheRuntime | None:
    """Start cache warming/background refresh services when enabled."""
    from .background_worker import BackgroundWorker
    from .cache_config import CACHE_WARMING_ENABLED
    from .cache_warming import CacheWarmer
    from .tools import cache_tools

    active_logger = logger or logging.getLogger(__name__)
    if not CACHE_WARMING_ENABLED:
        cache_tools.set_warming_status_provider(None)
        active_logger.info("Cache warming/background refresh disabled")
        return None

    cache_manager = cache_tools.get_cache_manager()
    worker = BackgroundWorker(cache_manager, _execute_background_refresh)
    accounts = _get_cache_warming_accounts()
    warmer = CacheWarmer(cache_manager, _execute_warming_operation, accounts)
    worker.set_cache_warmer(warmer)
    cache_tools.set_background_worker(worker)

    try:
        await worker.start()
        await warmer.start_warming()
    except Exception:
        await worker.stop()
        cache_tools.set_warming_status_provider(None)
        cache_manager.close()
        active_logger.exception("Failed to start cache runtime")
        raise

    active_logger.info(
        "Cache runtime started",
        extra={"account_count": len(accounts), "warming_enabled": True},
    )
    return CacheRuntime(cache_manager=cache_manager, worker=worker, warmer=warmer)


async def _run_mcp_with_cache_lifecycle(
    mcp,
    transport: str | None = None,
    **transport_kwargs: Any,
) -> None:
    """Run FastMCP with cache runtime startup and shutdown."""
    runtime = await _start_cache_runtime()
    try:
        await mcp.run_async(transport=transport, **transport_kwargs)
    finally:
        if runtime is not None:
            await runtime.stop()


def main() -> None:
    # Parse arguments first to get env file path
    args = _parse_arguments()

    # Load environment variables from custom path
    env_file = args.env_file
    if env_file.exists():
        load_dotenv(dotenv_path=env_file)
        print(f"Loaded environment from: {env_file}", file=sys.stderr)
    else:
        print(f"Warning: Environment file not found: {env_file}", file=sys.stderr)
        print("Continuing with system environment variables...", file=sys.stderr)

    # Import local modules after loading environment
    # (This allows auth.py to access environment variables)
    from .tools import mcp
    from .logging_config import setup_logging, get_logger

    # Initialize logger after loading environment
    global logger
    logger = get_logger(__name__)
    assert logger is not None  # Ensure logger is properly initialized

    # Setup logging
    log_level = os.getenv("MCP_LOG_LEVEL", "INFO")
    log_dir = os.getenv("MCP_LOG_DIR", "logs")
    setup_logging(log_dir=log_dir, log_level=log_level)

    # Setup signal handlers for graceful shutdown
    _setup_signal_handlers()

    # Register cleanup handler
    def _cleanup():
        assert logger is not None
        logger.info("Server shutting down")

    atexit.register(_cleanup)

    # Log startup information
    _log_startup_info()

    if not os.getenv("M365_MCP_CLIENT_ID"):
        logger.error("M365_MCP_CLIENT_ID environment variable is required")
        print(
            "Error: M365_MCP_CLIENT_ID environment variable is required",
            file=sys.stderr,
        )
        sys.exit(1)

    # Configure transport based on environment variable
    transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
    logger.info(f"Transport mode: {transport}")

    if transport == "http":
        host = os.getenv("MCP_HOST", "127.0.0.1")
        port = int(os.getenv("MCP_PORT", "8000"))
        path = os.getenv("MCP_PATH", "/mcp")

        # SECURITY: Warn if binding to all interfaces
        if host in ["0.0.0.0", "::", ""]:
            logger.warning(
                f"Binding to all network interfaces ({host}) - ensure firewall is configured!"
            )
            print(
                "⚠️  WARNING: Binding to all network interfaces. Ensure firewall is configured!",
                file=sys.stderr,
            )

        # SECURITY: Check for auth configuration
        auth_method = os.getenv("MCP_AUTH_METHOD", "none").lower()
        logger.info(f"Authentication method: {auth_method}")

        if auth_method == "none":
            logger.warning("Running HTTP server without authentication!")
            print(
                "⚠️  WARNING: Running HTTP server without authentication!",
                file=sys.stderr,
            )
            print(
                "⚠️  Anyone who can reach this server will have full access to your Microsoft account!",
                file=sys.stderr,
            )
            print(
                "⚠️  Set MCP_AUTH_METHOD=bearer and MCP_AUTH_TOKEN=<token> to enable auth",
                file=sys.stderr,
            )

            # Require explicit opt-in to run without auth
            if os.getenv("MCP_ALLOW_INSECURE") != "true":
                logger.error(
                    "Refusing to start insecure HTTP server without MCP_ALLOW_INSECURE=true"
                )
                print(
                    "Error: Refusing to start insecure HTTP server. Set MCP_ALLOW_INSECURE=true to override",
                    file=sys.stderr,
                )
                sys.exit(1)

        logger.info(f"Starting HTTP transport on {host}:{port}{path}")
        print(
            f"Starting MCP server with Streamable HTTP transport on {host}:{port}{path}",
            file=sys.stderr,
        )

        try:
            if auth_method == "bearer":
                _run_http_with_bearer_auth(mcp, host, port, path)
            elif auth_method == "oauth":
                logger.info("Using FastMCP built-in OAuth authentication")
                # Use FastMCP built-in OAuth (requires FastMCP 2.0+)
                asyncio.run(
                    _run_mcp_with_cache_lifecycle(
                        mcp,
                        transport="http",
                        host=host,
                        port=port,
                        path=path,
                        auth="oauth",
                    )
                )
            else:
                logger.warning("Running in insecure mode (no authentication)")
                # No auth (insecure mode - requires MCP_ALLOW_INSECURE=true)
                asyncio.run(
                    _run_mcp_with_cache_lifecycle(
                        mcp,
                        transport="http",
                        host=host,
                        port=port,
                        path=path,
                    )
                )
        except Exception as e:
            logger.critical(f"Failed to start HTTP server: {e}", exc_info=True)
            raise

    elif transport == "stdio":
        logger.info("Starting stdio transport")
        try:
            asyncio.run(_run_mcp_with_cache_lifecycle(mcp))
        except Exception as e:
            logger.critical(f"Failed to start stdio server: {e}", exc_info=True)
            raise
    else:
        logger.error(f"Invalid MCP_TRANSPORT '{transport}'. Must be 'stdio' or 'http'")
        print(
            f"Error: Invalid MCP_TRANSPORT '{transport}'. Must be 'stdio' or 'http'",
            file=sys.stderr,
        )
        sys.exit(1)


def _run_http_with_bearer_auth(mcp, host: str, port: int, path: str) -> None:
    """Run Streamable HTTP server with bearer token authentication"""
    assert logger is not None
    from fastapi import FastAPI, Request
    import uvicorn

    logger.info("Configuring bearer token authentication")

    auth_token = os.getenv("MCP_AUTH_TOKEN")
    if not auth_token:
        logger.error("MCP_AUTH_TOKEN required when MCP_AUTH_METHOD=bearer")
        print(
            "Error: MCP_AUTH_TOKEN required when MCP_AUTH_METHOD=bearer",
            file=sys.stderr,
        )
        sys.exit(1)

    # Validate token is sufficiently secure
    if len(auth_token) < 32:
        logger.warning(
            f"MCP_AUTH_TOKEN is too short ({len(auth_token)} chars, minimum 32 recommended)"
        )
        print(
            "⚠️  WARNING: MCP_AUTH_TOKEN is too short (minimum 32 characters recommended)",
            file=sys.stderr,
        )
        print(
            "⚠️  Generate a secure token with: openssl rand -hex 32",
            file=sys.stderr,
        )

    # Get the Streamable HTTP app from FastMCP and mount it.
    # Note: http_app() already includes routes at the configured path (e.g., /mcp)
    # so we mount it at root "/" to avoid double-pathing (e.g., /mcp/mcp).
    http_app = mcp.http_app()
    http_lifespan = None
    if hasattr(http_app, "router") and hasattr(http_app.router, "lifespan_context"):
        http_lifespan = http_app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        runtime = await _start_cache_runtime()
        try:
            if http_lifespan is not None:
                async with http_lifespan(app):
                    yield
            else:
                yield
        finally:
            if runtime is not None:
                await runtime.stop()

    app = FastAPI(lifespan=lifespan)

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        """Validate bearer token on all requests"""
        assert logger is not None
        from fastapi.responses import JSONResponse
        import time

        start_time = time.time()
        client_ip = request.client.host if request.client else "unknown"

        # Skip auth for health check endpoint
        if request.url.path == "/health":
            logger.debug(f"Health check request from {client_ip}")
            return await call_next(request)

        # Skip auth for common browser requests (return 404 instead of 401)
        if request.url.path in ["/favicon.ico", "/robots.txt"]:
            logger.debug(
                f"Ignoring browser request: {request.url.path} from {client_ip}"
            )
            return JSONResponse(status_code=404, content={"detail": "Not Found"})

        logger.debug(f"Request: {request.method} {request.url.path} from {client_ip}")

        auth_header = request.headers.get("Authorization")
        if not auth_header:
            logger.warning(
                f"Unauthorized request (missing auth header) from {client_ip} to {request.url.path}"
            )
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing Authorization header"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not auth_header.startswith("Bearer "):
            logger.warning(
                f"Unauthorized request (invalid auth format) from {client_ip} to {request.url.path}"
            )
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Invalid Authorization header format. Expected: Bearer <token>"
                },
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = auth_header[7:]  # Remove "Bearer " prefix
        if token != auth_token:
            logger.warning(
                f"Unauthorized request (invalid token) from {client_ip} to {request.url.path}"
            )
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid authentication token"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Process authenticated request
        response = await call_next(request)
        duration = (time.time() - start_time) * 1000  # Convert to ms

        logger.info(
            f"Request processed: {request.method} {request.url.path} from {client_ip} - "
            f"Status: {response.status_code} - Duration: {duration:.2f}ms"
        )

        return response

    @app.get("/health")
    async def health_check():
        """Health check endpoint (no auth required)"""
        return {"status": "ok", "transport": "http", "auth": "bearer"}

    # Mount at root since http_app already has path-prefixed routes
    app.mount("/", http_app)

    print("✅ Bearer token authentication enabled", file=sys.stderr)
    print(f"✅ Health check available at http://{host}:{port}/health", file=sys.stderr)
    print(f"✅ MCP endpoint: http://{host}:{port}{path}", file=sys.stderr)

    # Run the server
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
