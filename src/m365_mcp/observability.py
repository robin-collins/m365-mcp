"""Per-call audit log for the unified tools (concept §12.6).

:class:`AuditLogMiddleware` writes one JSON line per tool call to the
``m365_mcp.audit`` logger: the tool, the resource, a hash of the account,
duration, outcome and error class, Graph retries, result size and whether
the tool changes data. Argument values other than ``resource`` are never
logged, so tokens, passwords, URLs and message content cannot leak.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

import mcp.types as mt
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult

from . import graph

AUDIT_LOGGER_NAME = "m365_mcp.audit"
_audit_logger = logging.getLogger(AUDIT_LOGGER_NAME)


def hash_account(account_id: Any) -> str:
    """Return a short, stable hash of an account ID or email.

    Args:
        account_id: The ``account_id`` argument, or ``None`` when omitted.

    Returns:
        ``"default"`` when no account was given, otherwise the first 12 hex
        characters of the SHA-256 of the lower-cased value.
    """
    if not isinstance(account_id, str) or not account_id.strip():
        return "default"
    digest = hashlib.sha256(account_id.strip().lower().encode()).hexdigest()
    return digest[:12]


def _result_bytes(result: ToolResult) -> int:
    if result.structured_content is not None:
        return len(json.dumps(result.structured_content, default=str))
    return sum(len(getattr(block, "text", "") or "") for block in result.content)


class AuditLogMiddleware(Middleware):
    """Log one JSON line for every tool call."""

    def __init__(self, mutating_tools: set[str]) -> None:
        """Create the middleware.

        Args:
            mutating_tools: Names of tools whose ``readOnlyHint`` is false.
        """
        self.mutating_tools = frozenset(mutating_tools)

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        """Run the call and log its outcome, even when it fails."""
        name = context.message.name
        arguments = context.message.arguments or {}
        resource = arguments.get("resource")
        record: dict[str, Any] = {
            "event": "tool_call",
            "tool": name,
            "resource": resource if isinstance(resource, str) else None,
            "account": hash_account(arguments.get("account_id")),
            "duration_ms": 0.0,
            "outcome": "ok",
            "error_class": None,
            "retries": 0,
            "result_bytes": 0,
            "mutation": name in self.mutating_tools,
        }
        token = graph.reset_retry_count()
        started = time.perf_counter()
        try:
            result = await call_next(context)
            record["result_bytes"] = _result_bytes(result)
            return result
        except Exception as exc:
            record["outcome"] = "error"
            record["error_class"] = _error_class(exc)
            raise
        finally:
            record["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
            record["retries"] = graph.retry_count()
            graph.restore_retry_count(token)
            _audit_logger.info(json.dumps(record, sort_keys=True))


def _error_class(exc: BaseException) -> str:
    """Name the root error: the translated cause if a ToolError wraps one."""
    cause = exc.__cause__
    if cause is not None and type(exc).__name__ == "ToolError":
        return type(cause).__name__
    return type(exc).__name__
