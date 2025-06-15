import logging
import os
import sys
from typing import Any


def _get_log_level() -> str:
    return os.getenv("MICROSOFT_MCP_LOG_LEVEL", "INFO").upper()


def _should_log_requests() -> bool:
    return os.getenv("MICROSOFT_MCP_LOG_REQUESTS", "false").lower() == "true"


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("microsoft_mcp")
    logger.setLevel(_get_log_level())

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


def log_request(
    logger: logging.Logger, method: str, url: str, data: Any = None
) -> None:
    if _should_log_requests():
        logger.debug(f"Request: {method} {url}")
        if data:
            logger.debug(f"Request data: {data}")


def log_response(logger: logging.Logger, status: int, data: Any = None) -> None:
    if _should_log_requests():
        logger.debug(f"Response: {status}")
        if data:
            logger.debug(f"Response data: {data}")
