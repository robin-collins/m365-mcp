# Background Tasks

## Overview

The background task system provides asynchronous operation execution with retry logic, priority scheduling, and progress tracking. Used for cache refresh operations and expensive background jobs.

## BackgroundWorker Class

**Location**: `src/m365_mcp/background_worker.py`

```python
import asyncio
import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

class BackgroundWorker:
    """Process background tasks from queue with retry logic."""

    def __init__(self, cache_manager, tool_executor):
        """
        Initialize BackgroundWorker.

        Args:
            cache_manager: CacheManager instance for task queue
            tool_executor: Function to execute MCP tools
        """
        self.cache_manager = cache_manager
        self.tool_executor = tool_executor
        self.running = False

    async def start(self):
        """Start worker loop."""
        self.running = True
        logger.info("Background worker started")

        while self.running:
            await self.process_next_task()
            await asyncio.sleep(1)

    def stop(self):
        """Stop worker loop."""
        self.running = False
        logger.info("Background worker stopped")

    async def process_next_task(self):
        """Process highest priority queued task."""
        task = self._get_next_task()

        if not task:
            return

        task_id = task["task_id"]
        operation = task["operation"]
        parameters = json.loads(task["parameters_json"])
        account_id = task["account_id"]

        try:
            # Mark as running
            self._update_task_status(task_id, "running", 0)

            # Execute operation
            result = await self._execute_operation(operation, account_id, parameters)

            # Mark as completed
            self._update_task_status(task_id, "completed", 100, result)
            logger.info(f"Task {task_id[:8]} completed: {operation}")

        except Exception as e:
            logger.error(f"Task {task_id[:8]} failed: {e}")
            self._handle_task_failure(task_id, str(e), task["retry_count"])

    def _get_next_task(self) -> dict | None:
        """Get next queued task by priority."""
        with self.cache_manager._db() as conn:
            row = conn.execute(
                """
                SELECT task_id, account_id, operation, parameters_json, retry_count
                FROM cache_tasks
                WHERE status = 'queued'
                ORDER BY priority ASC, created_at ASC
                LIMIT 1
                """
            ).fetchone()

            if not row:
                return None

            return {
                "task_id": row[0],
                "account_id": row[1],
                "operation": row[2],
                "parameters_json": row[3],
                "retry_count": row[4]
            }

    def _update_task_status(self, task_id: str, status: str, progress: int, result: dict = None):
        """Update task status in database."""
        now = time.time()

        with self.cache_manager._db() as conn:
            if status == "running":
                conn.execute(
                    "UPDATE cache_tasks SET status = ?, started_at = ?, progress_pct = ? WHERE task_id = ?",
                    (status, now, progress, task_id)
                )
            elif status == "completed":
                conn.execute(
                    """
                    UPDATE cache_tasks
                    SET status = ?, completed_at = ?, progress_pct = ?, result_json = ?
                    WHERE task_id = ?
                    """,
                    (status, now, progress, json.dumps(result) if result else None, task_id)
                )
            conn.commit()

    def _handle_task_failure(self, task_id: str, error: str, retry_count: int):
        """Handle task failure with retry logic."""
        now = time.time()

        with self.cache_manager._db() as conn:
            row = conn.execute(
                "SELECT max_retries FROM cache_tasks WHERE task_id = ?",
                (task_id,)
            ).fetchone()

            max_retries = row[0] if row else 3

            if retry_count < max_retries:
                # Retry
                conn.execute(
                    """
                    UPDATE cache_tasks
                    SET status = 'queued', retry_count = ?, error_text = ?
                    WHERE task_id = ?
                    """,
                    (retry_count + 1, error, task_id)
                )
                logger.info(f"Task {task_id[:8]} queued for retry ({retry_count + 1}/{max_retries})")
            else:
                # Failed permanently
                conn.execute(
                    """
                    UPDATE cache_tasks
                    SET status = 'failed', completed_at = ?, error_text = ?
                    WHERE task_id = ?
                    """,
                    (now, error, task_id)
                )
                logger.error(f"Task {task_id[:8]} failed permanently after {max_retries} retries")

            conn.commit()

    async def _execute_operation(self, operation: str, account_id: str, parameters: dict) -> dict:
        """Execute MCP tool operation."""
        result = await self.tool_executor(operation, account_id, parameters)
        return result
```

## Task Management Methods (CacheManager)

Add to `CacheManager` class in `cache.py`:

```python
def enqueue_task(
    self,
    operation: str,
    account_id: str,
    parameters: dict,
    priority: int = 5
) -> str:
    """
    Queue background task.

    Args:
        operation: MCP tool name
        account_id: Account identifier
        parameters: Operation parameters
        priority: Priority 1-10 (1=highest)

    Returns:
        task_id: UUID for tracking
    """
    import uuid

    task_id = str(uuid.uuid4())
    now = time.time()

    with self._db() as conn:
        conn.execute(
            """
            INSERT INTO cache_tasks
            (task_id, account_id, task_type, operation, parameters_json,
             status, priority, created_at)
            VALUES (?, ?, ?, ?, ?, 'queued', ?, ?)
            """,
            (task_id, account_id, f"{operation}_bg", operation,
             json.dumps(parameters), priority, now)
        )
        conn.commit()

    logger.info(f"Enqueued task {task_id[:8]}: {operation}")
    return task_id

def get_task_status(self, task_id: str) -> dict:
    """Get task status and result."""
    with self._db() as conn:
        row = conn.execute(
            """
            SELECT status, progress_pct, result_json, error_text, created_at, completed_at
            FROM cache_tasks WHERE task_id = ?
            """,
            (task_id,)
        ).fetchone()

        if not row:
            raise ValueError(f"Task {task_id} not found")

        result = {
            "task_id": task_id,
            "status": row[0],
            "progress": row[1],
            "created_at": row[4],
            "completed_at": row[5]
        }

        if row[0] == "completed" and row[2]:
            result["result"] = json.loads(row[2])

        if row[0] == "failed" and row[3]:
            result["error"] = row[3]

        return result

def list_tasks(
    self,
    account_id: str,
    status: str | None = None,
    limit: int = 50
) -> list[dict]:
    """List tasks for account."""
    with self._db() as conn:
        if status:
            rows = conn.execute(
                """
                SELECT task_id, operation, status, progress_pct, created_at
                FROM cache_tasks
                WHERE account_id = ? AND status = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (account_id, status, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT task_id, operation, status, progress_pct, created_at
                FROM cache_tasks
                WHERE account_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (account_id, limit)
            ).fetchall()

        return [
            {
                "task_id": row[0],
                "operation": row[1],
                "status": row[2],
                "progress": row[3],
                "created_at": row[4]
            }
            for row in rows
        ]
```

## Cache Management Tools

```python
@mcp.tool(
    name="cache_task_get_status",
    annotations={
        "title": "Get Cache Task Status",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    },
    meta={"category": "cache", "safety_level": "safe"}
)
def cache_task_get_status(task_id: str) -> dict:
    """📖 Get background task status (read-only, safe)."""
    return cache_manager.get_task_status(task_id)

@mcp.tool(
    name="cache_task_list",
    annotations={
        "title": "List Cache Tasks",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    },
    meta={"category": "cache", "safety_level": "safe"}
)
def cache_task_list(account_id: str, status: str | None = None, limit: int = 50) -> list:
    """📖 List background tasks (read-only, safe)."""
    return cache_manager.list_tasks(account_id, status, limit)
```

---

**Document Version**: 2.0
**Last Updated**: 2025-10-14
**Status**: Production-Ready Background Tasks
