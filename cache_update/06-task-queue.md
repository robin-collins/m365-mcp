# Background Task Queue System

## Purpose

Handle expensive operations asynchronously and provide progress tracking.

## Task Lifecycle

```
QUEUED → RUNNING → COMPLETED
                 ↘ FAILED (retry) → QUEUED
```

## CacheManager Task Methods

### enqueue_task()

```python
def enqueue_task(
    self,
    operation: str,
    account_id: str,
    parameters: dict,
    priority: int = 5
) -> str:
    """Queue background task, return task_id"""
    import uuid

    task_id = str(uuid.uuid4())

    with self._db() as conn:
        conn.execute(
            """
            INSERT INTO cache_tasks
            (task_id, account_id, task_type, operation,
             parameters_json, status, priority)
            VALUES (?, ?, ?, ?, ?, 'queued', ?)
            """,
            (task_id, account_id, f"{operation}_bg", operation,
             json.dumps(parameters), priority)
        )
        conn.commit()

    return task_id
```

### get_task_status()

```python
def get_task_status(self, task_id: str) -> dict:
    """Get task status and result"""
    with self._db() as conn:
        row = conn.execute(
            """
            SELECT status, progress_pct, result_json, error_text
            FROM cache_tasks WHERE task_id = ?
            """,
            (task_id,)
        ).fetchone()

        if not row:
            raise ValueError(f"Task {task_id} not found")

        status, progress, result_json, error = row

        result = {"task_id": task_id, "status": status, "progress": progress}

        if status == "completed" and result_json:
            result["result"] = json.loads(result_json)

        if status == "failed" and error:
            result["error"] = error

        return result
```

### list_tasks()

```python
def list_tasks(
    self,
    account_id: str,
    status: str | None = None,
    limit: int = 50
) -> list[dict]:
    """List tasks for account"""
    with self._db() as conn:
        if status:
            rows = conn.execute(
                """
                SELECT task_id, operation, status, progress_pct, created_at
                FROM cache_tasks
                WHERE account_id = ? AND status = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (account_id, status, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT task_id, operation, status, progress_pct, created_at
                FROM cache_tasks
                WHERE account_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (account_id, limit)
            ).fetchall()

        return [
            {
                "task_id": row[0],
                "operation": row[1],
                "status": row[2],
                "progress": row[3],
                "created_at": row[4],
            }
            for row in rows
        ]
```

## Background Worker

Location: `src/m365_mcp/background_worker.py`

```python
import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

class BackgroundWorker:
    """Process background tasks from queue"""

    def __init__(self, cache_manager):
        self.cache_manager = cache_manager
        self.running = False

    async def start(self):
        """Start worker loop"""
        self.running = True
        while self.running:
            await self.process_next_task()
            await asyncio.sleep(1)

    async def process_next_task(self):
        """Process highest priority queued task"""
        task = self._get_next_task()

        if not task:
            return

        task_id = task["task_id"]
        operation = task["operation"]
        parameters = json.loads(task["parameters_json"])

        try:
            # Mark as running
            self._update_task_status(task_id, "running", 0)

            # Execute operation
            result = await self._execute_operation(operation, parameters)

            # Mark as completed
            self._update_task_status(task_id, "completed", 100, result)

        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}")
            self._handle_task_failure(task_id, str(e))

    def _get_next_task(self) -> dict | None:
        """Get next queued task by priority"""
        with self.cache_manager._db() as conn:
            row = conn.execute(
                """
                SELECT task_id, operation, parameters_json
                FROM cache_tasks
                WHERE status = 'queued'
                ORDER BY priority ASC, created_at ASC
                LIMIT 1
                """,
            ).fetchone()

            if not row:
                return None

            return {
                "task_id": row[0],
                "operation": row[1],
                "parameters_json": row[2],
            }
```

## New MCP Tools

```python
# src/m365_mcp/tools/cache_tools.py

@mcp.tool(name="task_get_status")
def task_get_status(task_id: str) -> dict:
    """Get background task status"""
    return cache_manager.get_task_status(task_id)

@mcp.tool(name="task_list")
def task_list(account_id: str, status: str | None = None, limit: int = 50) -> list:
    """List background tasks"""
    return cache_manager.list_tasks(account_id, status, limit)

@mcp.tool(name="cache_get_stats")
def cache_get_stats(account_id: str) -> dict:
    """Get cache statistics"""
    # Implement stats retrieval
    pass

@mcp.tool(name="cache_invalidate")
def cache_invalidate(account_id: str, resource_type: str, pattern: str = "*"):
    """Manually invalidate cache entries"""
    cache_manager.invalidate_pattern(account_id, resource_type, pattern)
    return {"status": "invalidated", "pattern": pattern}
```

## Usage Example

```python
# Queue expensive operation
task_id = cache_manager.enqueue_task(
    operation="folder_get_tree",
    account_id="acc123",
    parameters={"path": "/", "max_depth": 25},
    priority=1  # High priority
)

# Check status
status = cache_manager.get_task_status(task_id)
# {"task_id": "...", "status": "queued", "progress": 0}

# Later...
status = cache_manager.get_task_status(task_id)
# {"task_id": "...", "status": "completed", "progress": 100, "result": {...}}
```
