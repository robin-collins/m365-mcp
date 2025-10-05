import os
import sys
from .tools import mcp


def main() -> None:
    if not os.getenv("MICROSOFT_MCP_CLIENT_ID"):
        print(
            "Error: MICROSOFT_MCP_CLIENT_ID environment variable is required",
            file=sys.stderr,
        )
        sys.exit(1)

    # Configure transport based on environment variable
    transport = os.getenv("MCP_TRANSPORT", "stdio").lower()

    if transport == "http":
        host = os.getenv("MCP_HOST", "127.0.0.1")
        port = int(os.getenv("MCP_PORT", "8000"))
        path = os.getenv("MCP_PATH", "/mcp")

        # SECURITY: Warn if binding to all interfaces
        if host in ["0.0.0.0", "::", ""]:
            print(
                "⚠️  WARNING: Binding to all network interfaces. Ensure firewall is configured!",
                file=sys.stderr,
            )

        # SECURITY: Check for auth configuration
        auth_method = os.getenv("MCP_AUTH_METHOD", "none").lower()

        if auth_method == "none":
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
                print(
                    "Error: Refusing to start insecure HTTP server. Set MCP_ALLOW_INSECURE=true to override",
                    file=sys.stderr,
                )
                sys.exit(1)

        print(
            f"Starting MCP server with Streamable HTTP transport on {host}:{port}{path}",
            file=sys.stderr,
        )

        if auth_method == "bearer":
            _run_http_with_bearer_auth(host, port, path)
        elif auth_method == "oauth":
            # Use FastMCP built-in OAuth (requires FastMCP 2.0+)
            mcp.run(transport="http", host=host, port=port, path=path, auth="oauth")
        else:
            # No auth (insecure mode - requires MCP_ALLOW_INSECURE=true)
            mcp.run(transport="http", host=host, port=port, path=path)

    elif transport == "stdio":
        mcp.run()
    else:
        print(
            f"Error: Invalid MCP_TRANSPORT '{transport}'. Must be 'stdio' or 'http'",
            file=sys.stderr,
        )
        sys.exit(1)


def _run_http_with_bearer_auth(host: str, port: int, path: str) -> None:
    """Run Streamable HTTP server with bearer token authentication"""
    from fastapi import FastAPI, Request, HTTPException
    import uvicorn

    auth_token = os.getenv("MCP_AUTH_TOKEN")
    if not auth_token:
        print(
            "Error: MCP_AUTH_TOKEN required when MCP_AUTH_METHOD=bearer",
            file=sys.stderr,
        )
        sys.exit(1)

    # Validate token is sufficiently secure
    if len(auth_token) < 32:
        print(
            "⚠️  WARNING: MCP_AUTH_TOKEN is too short (minimum 32 characters recommended)",
            file=sys.stderr,
        )
        print(
            "⚠️  Generate a secure token with: openssl rand -hex 32",
            file=sys.stderr,
        )

    app = FastAPI()

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        """Validate bearer token on all requests"""
        # Skip auth for health check endpoint
        if request.url.path == "/health":
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        if not auth_header:
            raise HTTPException(
                status_code=401,
                detail="Missing Authorization header",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=401,
                detail="Invalid Authorization header format. Expected: Bearer <token>",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = auth_header[7:]  # Remove "Bearer " prefix
        if token != auth_token:
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return await call_next(request)

    @app.get("/health")
    async def health_check():
        """Health check endpoint (no auth required)"""
        return {"status": "ok", "transport": "http", "auth": "bearer"}

    # Get the Streamable HTTP app from FastMCP and mount it
    http_app = mcp.get_asgi_app()
    app.mount(path, http_app)

    print("✅ Bearer token authentication enabled", file=sys.stderr)
    print(f"✅ Health check available at http://{host}:{port}/health", file=sys.stderr)
    print(f"✅ MCP endpoint: http://{host}:{port}{path}", file=sys.stderr)

    # Run the server
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
