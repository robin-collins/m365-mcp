import os
import sys
import atexit
from microsoft_mcp.tools import mcp
from microsoft_mcp.token_refresh import start_token_refresh, stop_token_refresh
from microsoft_mcp.logging_config import setup_logging


def main() -> None:
    if not os.getenv("MICROSOFT_MCP_CLIENT_ID"):
        print(
            "Error: MICROSOFT_MCP_CLIENT_ID environment variable is required",
            file=sys.stderr,
        )
        print("Please set it to your Azure AD application ID", file=sys.stderr)
        sys.exit(1)

    logger = setup_logging()
    logger.info("Starting Microsoft MCP server")

    start_token_refresh()
    atexit.register(stop_token_refresh)

    mcp.run()


if __name__ == "__main__":
    main()
