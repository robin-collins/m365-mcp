"""Cache management tools for M365 MCP Server."""

import atexit
from datetime import datetime
from typing import Any, Optional, Protocol
from ..mcp_instance import mcp
from ..cache import CacheManager
from ..cache_warming import get_inactive_warming_status


class WarmingStatusProvider(Protocol):
    """Object capable of reporting cache warming status."""

    def get_warming_status(self) -> dict[str, Any]:
        """Return the current cache warming status."""
        ...


# Global cache manager instance (lazy-initialized)
_cache_manager: Optional[CacheManager] = None
_warming_status_provider: Optional[WarmingStatusProvider] = None
_cache_manager_atexit_registered = False


def _close_cache_manager() -> None:
    """Close the singleton cache manager during process shutdown."""
    if _cache_manager is not None:
        _cache_manager.close()


def get_cache_manager() -> CacheManager:
    """
    Get or create the global cache manager instance.

    Returns:
        CacheManager: The global cache manager instance.
    """
    global _cache_manager
    global _cache_manager_atexit_registered
    if _cache_manager is None:
        _cache_manager = CacheManager()
        if not _cache_manager_atexit_registered:
            atexit.register(_close_cache_manager)
            _cache_manager_atexit_registered = True
    return _cache_manager


def set_warming_status_provider(provider: Optional[WarmingStatusProvider]) -> None:
    """Set the object that owns cache warming status."""
    global _warming_status_provider
    _warming_status_provider = provider


def set_cache_warmer(warmer: Optional[WarmingStatusProvider]) -> None:
    """Set the cache warmer used by `cache_warming_status`."""
    set_warming_status_provider(warmer)


def set_background_worker(worker: Optional[WarmingStatusProvider]) -> None:
    """
    Set a background worker that proxies cache warming status.

    Args:
        worker: BackgroundWorker instance with get_warming_status().
    """
    set_warming_status_provider(worker)


# cache_task_get_status
@mcp.tool(
    name="cache_task_get_status",
    annotations={
        "title": "Get Cache Task Status",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "cache", "safety_level": "safe"},
)
def cache_task_get_status(task_id: str) -> dict[str, Any]:
    """📖 Get status of a background cache task (read-only, safe for unsupervised use)

    Retrieve the current status, progress, and result/error information for a
    specific background cache task.

    Args:
        task_id: The unique identifier for the cache task.

    Returns:
        Dictionary containing task status information:
        - task_id: Task identifier
        - status: Current status (queued, running, completed, failed)
        - operation: Operation type (e.g., folder_get_tree, email_list)
        - account_id: Associated account
        - progress: Progress percentage (0-100)
        - created_at: Task creation timestamp
        - updated_at: Last update timestamp
        - result: Operation result (if completed)
        - error: Error message (if failed)
        - retry_count: Number of retries attempted

    Raises:
        ValueError: If task_id is not found.
    """
    cache_mgr = get_cache_manager()
    task = cache_mgr.get_task_status(task_id)

    if not task:
        raise ValueError(f"Task not found: {task_id}")

    return task


# cache_task_list
@mcp.tool(
    name="cache_task_list",
    annotations={
        "title": "List Cache Tasks",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "cache", "safety_level": "safe"},
)
def cache_task_list(
    account_id: Optional[str] = None, status: Optional[str] = None, limit: int = 50
) -> list[dict[str, Any]]:
    """📖 List background cache tasks (read-only, safe for unsupervised use)

    Retrieve a list of background cache tasks, optionally filtered by account
    and status.

    Args:
        account_id: Optional account ID to filter tasks (None = all accounts).
        status: Optional status filter (queued, running, completed, failed).
        limit: Maximum number of tasks to return (default: 50).

    Returns:
        List of task dictionaries, each containing:
        - task_id: Task identifier
        - status: Current status
        - operation: Operation type
        - account_id: Associated account
        - priority: Task priority (1=highest, 10=lowest)
        - created_at: Creation timestamp
        - updated_at: Last update timestamp
        - retry_count: Number of retries

    Example:
        # List all tasks for a specific account
        tasks = cache_task_list(account_id="user@example.com")

        # List only failed tasks
        failed = cache_task_list(status="failed")

        # List recent queued tasks
        queued = cache_task_list(status="queued", limit=10)
    """
    cache_mgr = get_cache_manager()
    tasks = cache_mgr.list_tasks(account_id=account_id, status=status, limit=limit)

    return tasks


# cache_get_stats
@mcp.tool(
    name="cache_get_stats",
    annotations={
        "title": "Get Cache Statistics",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "cache", "safety_level": "safe"},
)
def cache_get_stats() -> dict[str, Any]:
    """📖 Get cache statistics and performance metrics (read-only, safe for unsupervised use)

    Retrieve comprehensive statistics about the cache system including size,
    hit rates, entry counts, and performance metrics.

    Returns:
        Dictionary containing cache statistics:
        - total_entries: Total number of cached entries
        - total_bytes: Total size of cache in bytes
        - total_size_mb: Total size in megabytes
        - size_percentage: Percentage of max cache size used
        - total_hits: Number of cache hits
        - hit_rate: None until cache misses are tracked
        - entries_by_resource_type: Count of entries per resource type
        - average_entry_size_bytes: Average size per entry
        - compressed_entries: Number of compressed entries
        - compression_ratio: Average compression ratio
        - oldest_entry_age_hours: Age of oldest entry in hours
        - cleanup_triggered: Whether cleanup threshold has been reached
        - last_cleanup: Timestamp of last cleanup operation

    Example:
        stats = cache_get_stats()
        print(f"Cache size: {stats['total_size_mb']:.2f} MB")
        print(f"Size used: {stats['size_percentage']:.1f}%")
    """
    cache_mgr = get_cache_manager()
    stats = cache_mgr.get_stats()

    # Add human-readable fields
    total_bytes = stats.get("total_bytes", 0)
    stats["total_size_bytes"] = total_bytes
    stats["total_size_mb"] = total_bytes / (1024 * 1024)

    stats["size_percentage"] = stats.get("usage_percent", 0.0)

    # Misses are not tracked yet, so a truthful hit rate cannot be computed.
    stats["miss_count"] = None
    stats["hit_rate"] = None

    # Check if cleanup should be triggered
    stats["cleanup_triggered"] = stats["size_percentage"] >= 80.0

    return stats


# cache_invalidate
@mcp.tool(
    name="cache_invalidate",
    annotations={
        "title": "Invalidate Cache Entries",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "cache", "safety_level": "moderate"},
)
def cache_invalidate(
    pattern: str, account_id: Optional[str] = None, reason: str = "manual_invalidation"
) -> dict[str, Any]:
    """✏️ Invalidate cache entries matching a pattern (requires user confirmation recommended)

    Delete cache entries that match the specified pattern. This is useful for
    forcing fresh data retrieval or clearing stale cache entries.

    Args:
        pattern: Pattern to match cache keys (supports wildcards):
                - "*" matches any characters within a segment
                - Use "email_list:*" to invalidate all email lists
                - Use "email_list:account@example.com:*" for specific account
                - Use "folder_get_tree:*" to invalidate all folder trees
        account_id: Optional account ID to scope invalidation (None = all accounts).
        reason: Reason for invalidation (for audit logging).

    Returns:
        Dictionary containing:
        - entries_deleted: Number of cache entries deleted
        - pattern: Pattern that was used
        - account_id: Account ID filter (if specified)
        - reason: Invalidation reason
        - timestamp: When invalidation occurred

    Examples:
        # Invalidate all email lists
        cache_invalidate("email_list:*", reason="email_sent")

        # Invalidate specific account's folder tree
        cache_invalidate(
            "folder_get_tree:user@example.com:*",
            account_id="user@example.com",
            reason="folder_created"
        )

        # Invalidate all cache for an account
        cache_invalidate("*:user@example.com:*", reason="account_refresh")
    """
    cache_mgr = get_cache_manager()

    # Add account_id to pattern if specified
    if account_id and ":*" in pattern and f":{account_id}:" not in pattern:
        # Insert account_id into pattern
        parts = pattern.split(":")
        if len(parts) >= 2:
            pattern = f"{parts[0]}:{account_id}:{':'.join(parts[1:])}"

    deleted_count = cache_mgr.invalidate_pattern(pattern, reason=reason)

    return {
        "entries_deleted": deleted_count,
        "pattern": pattern,
        "account_id": account_id,
        "reason": reason,
        "timestamp": datetime.now().isoformat(),
    }


# cache_warming_status
@mcp.tool(
    name="cache_warming_status",
    annotations={
        "title": "Get Cache Warming Status",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "cache", "safety_level": "safe"},
)
def cache_warming_status() -> dict[str, Any]:
    """📖 Get cache warming status and progress (read-only, safe for unsupervised use)

    Retrieve the current status of the cache warming process, including progress,
    completion estimates, and statistics.

    Returns:
        Dictionary containing warming status:
        - is_warming: Whether cache warming is currently active
        - started_at: When warming started (if active)
        - completed_at: When warming completed (if finished)
        - operations_total: Total number of warming operations
        - operations_completed: Number of completed operations
        - operations_failed: Number of failed operations
        - progress_percent: Progress percentage (0-100)
        - estimated_completion: Estimated completion time
        - accounts_warmed: Number of accounts warmed
        - operations_by_type: Breakdown of operations by type
        - status: Current status message

    Example:
        status = cache_warming_status()
        if status['is_warming']:
            print(f"Warming in progress: {status['progress_percent']:.1f}%")
        else:
            print("Cache warming complete or not started")
    """
    if _warming_status_provider is None:
        return get_inactive_warming_status(
            "Cache warming disabled: warming status provider not initialized."
        )

    # Get warming status from the configured owner.
    status = _warming_status_provider.get_warming_status()

    return status
