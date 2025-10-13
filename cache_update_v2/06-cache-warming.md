# Cache Warming

## Overview

Cache warming pre-populates the cache on server startup with frequently-accessed expensive operations. This ensures users get instant responses from their first request without waiting 1-2 minutes for cache to populate organically.

**Key Features**:
- Non-blocking background warming (server starts immediately)
- Prioritized operation queue (expensive operations first)
- Throttled API calls (respects Microsoft Graph rate limits)
- Smart skipping (already-cached entries not re-fetched)
- Resilient (failures don't crash server)

## CacheWarmer Class

**Location**: `src/m365_mcp/cache_warming.py`

```python
import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

class CacheWarmer:
    """Progressive cache warming on server startup."""

    def __init__(self, cache_manager, tool_executor):
        """
        Initialize CacheWarmer.

        Args:
            cache_manager: CacheManager instance
            tool_executor: Function to execute MCP tools
        """
        self.cache_manager = cache_manager
        self.tool_executor = tool_executor
        self.warming_queue = []
        self.is_warming = False

    async def start_warming(self, accounts: list[str]):
        """
        Start progressive cache warming for all accounts.

        Args:
            accounts: List of account IDs to warm cache for
        """
        if not accounts:
            logger.info("No accounts found, skipping cache warming")
            return

        logger.info(f"Starting cache warming for {len(accounts)} accounts")
        self._build_warming_queue(accounts)
        asyncio.create_task(self._warming_loop())

    def _build_warming_queue(self, accounts: list[str]):
        """
        Build prioritized queue of operations to warm.

        Priority order:
        1. folder_get_tree (slowest, 20-30s each)
        2. email_list (moderate, 2-5s each)
        3. contact_list (fast, 1-3s each)
        """
        from .cache_config import CACHE_WARMING_OPERATIONS

        for operation_config in CACHE_WARMING_OPERATIONS:
            for account_id in accounts:
                self.warming_queue.append({
                    "priority": operation_config["priority"],
                    "operation": operation_config["operation"],
                    "account_id": account_id,
                    "params": operation_config["params"],
                    "throttle_sec": operation_config["throttle_sec"]
                })

        # Sort by priority
        self.warming_queue.sort(key=lambda x: x["priority"])
        logger.info(f"Built warming queue with {len(self.warming_queue)} operations")

    async def _warming_loop(self):
        """Process warming queue with throttling."""
        self.is_warming = True
        completed = 0
        skipped = 0
        failed = 0

        for item in self.warming_queue:
            try:
                # Check if already cached
                cached_data, status = self.cache_manager.get_cached(
                    operation=item["operation"],
                    account_id=item["account_id"],
                    fresh_ttl=1800,  # Accept if < 30min old
                    stale_ttl=7200,
                    **item["params"]
                )

                if cached_data:
                    logger.debug(f"Skipping {item['operation']} - already cached")
                    skipped += 1
                    continue

                # Execute operation to warm cache
                logger.info(
                    f"Warming cache [{completed + 1}/{len(self.warming_queue)}]: "
                    f"{item['operation']} for account {item['account_id'][:8]}..."
                )

                result = await self.tool_executor(
                    item["operation"],
                    item["account_id"],
                    item["params"]
                )

                completed += 1

                # Throttle to respect rate limits
                await asyncio.sleep(item["throttle_sec"])

            except Exception as e:
                logger.warning(f"Cache warming failed for {item['operation']}: {e}")
                failed += 1
                continue

        self.is_warming = False
        logger.info(
            f"Cache warming complete: {completed} warmed, "
            f"{skipped} skipped, {failed} failed"
        )

    def get_status(self) -> dict[str, Any]:
        """Get current warming status."""
        return {
            "is_warming": self.is_warming,
            "total_operations": len(self.warming_queue),
            "remaining": sum(1 for _ in self.warming_queue if self.is_warming)
        }
```

## Server Integration

**In `src/m365_mcp/server.py`**:

```python
from .cache_warming import CacheWarmer
from .cache_config import CACHE_WARMING_ENABLED

async def startup():
    """Server startup with cache warming."""

    # Initialize cache
    cache_manager = CacheManager(db_path=CACHE_DB_PATH)

    # Get authenticated accounts
    accounts = list_accounts()
    account_ids = [acc["account_id"] for acc in accounts]

    if account_ids and CACHE_WARMING_ENABLED:
        # Start cache warming (non-blocking)
        warmer = CacheWarmer(cache_manager, tool_executor=execute_tool)
        asyncio.create_task(warmer.start_warming(account_ids))
        logger.info(f"Initiated cache warming for {len(account_ids)} accounts")
    else:
        logger.info("Cache warming disabled or no accounts available")

    return cache_manager
```

## Warming Timeline Example

For 2 accounts with 3 operations each:

```
T+0s:     Server starts (ready for requests)
T+1s:     Start warming account_1 folder_tree (takes ~28s)
T+29s:    Complete account_1 folder_tree
T+32s:    Start warming account_2 folder_tree (throttled 3s)
T+60s:    Complete account_2 folder_tree
T+63s:    Start warming account_1 email_list (throttled 3s)
T+66s:    Complete account_1 email_list (takes ~3s)
T+68s:    Start warming account_2 email_list (throttled 2s)
T+71s:    Complete account_2 email_list
T+73s:    Start warming account_1 contact_list (throttled 2s)
T+75s:    Complete account_1 contact_list (takes ~2s)
T+76s:    Start warming account_2 contact_list (throttled 1s)
T+78s:    Complete account_2 contact_list
T+78s:    Cache warming complete!
```

**Total Time**: ~78 seconds
**User Impact**: Zero - server responsive from T+0s

## Configuration

**In `src/m365_mcp/cache_config.py`**:

```python
# Enable/disable cache warming
CACHE_WARMING_ENABLED = True

# Operations to warm (in priority order)
CACHE_WARMING_OPERATIONS = [
    {
        "operation": "folder_get_tree",
        "priority": 1,
        "params": {"path": "/", "max_depth": 10},
        "throttle_sec": 3,
    },
    {
        "operation": "email_list",
        "priority": 2,
        "params": {"folder": "inbox", "limit": 50},
        "throttle_sec": 2,
    },
    {
        "operation": "contact_list",
        "priority": 3,
        "params": {"limit": 100},
        "throttle_sec": 1,
    },
]
```

## Monitoring Tool

```python
@mcp.tool(
    name="cache_warming_status",
    annotations={
        "title": "Get Cache Warming Status",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    },
    meta={
        "category": "cache",
        "safety_level": "safe"
    }
)
def cache_warming_status() -> dict:
    """📖 Get current cache warming status (read-only, safe)."""
    if not warmer:
        return {"enabled": False}

    status = warmer.get_status()
    return {
        "enabled": True,
        "is_warming": status["is_warming"],
        "total_operations": status["total_operations"],
        "remaining": status["remaining"]
    }
```

---

**Document Version**: 2.0
**Last Updated**: 2025-10-14
**Status**: Production-Ready Cache Warming
