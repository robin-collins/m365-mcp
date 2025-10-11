"""
Comprehensive logging configuration for Microsoft MCP Server.

This module provides structured logging with rotation, detailed formatting,
and separate log levels for different components.
"""

import logging
import logging.handlers
import os
import sys
from pathlib import Path
from datetime import datetime
import json


class StructuredFormatter(logging.Formatter):
    """JSON structured formatter for machine-readable logs."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add extra fields if present
        for key in ["account_id", "tool_name", "operation_id", "duration_ms"]:
            if hasattr(record, key):
                log_entry[key] = getattr(record, key)

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry)


class HumanReadableFormatter(logging.Formatter):
    """Human-readable formatter with colors for console output."""

    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
        "RESET": "\033[0m",
    }

    def format(self, record: logging.LogRecord) -> str:
        # Add color if outputting to terminal
        if sys.stderr.isatty():
            color = self.COLORS.get(record.levelname, self.COLORS["RESET"])
            reset = self.COLORS["RESET"]
            record.levelname = f"{color}{record.levelname}{reset}"

        # Format: timestamp [LEVEL] logger.module.function:line - message
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        location = f"{record.module}.{record.funcName}:{record.lineno}"

        formatted = f"{timestamp} [{record.levelname}] {record.name}.{location} - {record.getMessage()}"

        # Add exception info if present
        if record.exc_info:
            formatted += "\n" + self.formatException(record.exc_info)

        return formatted


def setup_logging(
    log_dir: str = "logs",
    log_level: str = "INFO",
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 10,
) -> None:
    """
    Setup comprehensive logging for the MCP server.

    Args:
        log_dir: Directory to store log files
        log_level: Minimum log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        max_bytes: Maximum size of each log file before rotation
        backup_count: Number of backup log files to keep
    """
    # Create log directory
    log_path = Path(log_dir)
    log_path.mkdir(exist_ok=True)

    # Convert log level string to logging constant
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Capture all levels, filter per handler

    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()

    # === File Handler: All logs (JSON structured) ===
    all_logs_file = log_path / "mcp_server_all.jsonl"
    all_handler = logging.handlers.RotatingFileHandler(
        all_logs_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    all_handler.setLevel(logging.DEBUG)
    all_handler.setFormatter(StructuredFormatter())
    root_logger.addHandler(all_handler)

    # === File Handler: Error logs only (JSON structured) ===
    error_logs_file = log_path / "mcp_server_errors.jsonl"
    error_handler = logging.handlers.RotatingFileHandler(
        error_logs_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(StructuredFormatter())
    root_logger.addHandler(error_handler)

    # === File Handler: Human-readable logs ===
    readable_logs_file = log_path / "mcp_server.log"
    readable_handler = logging.handlers.RotatingFileHandler(
        readable_logs_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    readable_handler.setLevel(numeric_level)
    readable_handler.setFormatter(HumanReadableFormatter())
    root_logger.addHandler(readable_handler)

    # === Console Handler: Human-readable (stderr) ===
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(HumanReadableFormatter())
    root_logger.addHandler(console_handler)

    # Set specific log levels for noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    # Log the startup
    logger = logging.getLogger("microsoft_mcp.logging")
    logger.info(f"Logging initialized - Level: {log_level}")
    logger.info(f"Log directory: {log_path.absolute()}")
    logger.info(f"All logs: {all_logs_file.name}")
    logger.info(f"Error logs: {error_logs_file.name}")
    logger.info(f"Readable logs: {readable_logs_file.name}")


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with the given name.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)
