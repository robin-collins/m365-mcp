# Cache Warming Strategy

## Overview

Cache warming pre-populates the cache on server startup with frequently-accessed, expensive-to-fetch data. This ensures users get instant responses from the first request.

## Design Principles

1. **Non-blocking**: Server must start immediately, warming happens in background
2. **Prioritized**: Most expensive operations cached first
3. **Throttled**: Respects Microsoft Graph API rate limits
4. **Smart**: Skips entries already in cache
5. **Resilient**: Failures don't crash server or stop warming

---

## Implementation

### Cache Warmer Class

Location: `src/m365_mcp/cache_warming.py`

```python
import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

class CacheWarmer:
    """Progressive cache warming on server startup"""

    def __init__(self, cache_manager, tool_executor):
        self.cache_manager = cache_manager
        self.tool_executor = tool_executor  # Function to call tools
        self.warming_queue = []
        self.is_warming = False

    async def start_warming(self, accounts: list[str]):
        """
        Start progressive cache warming for all accounts

        Args:
            accounts: List of account IDs to warm cache for
        """
        if not accounts:
            logger.info("No accounts found, skipping cache warming")
            return

        logger.info(f"Starting cache warming for {len(accounts)} accounts")

        # Build warming queue with priorities
        self._build_warming_queue(accounts)

        # Start warming loop in background
        asyncio.create_task(self._warming_loop())

    def _build_warming_queue(self, accounts: list[str]):
        """Build prioritized queue of operations to warm"""

        # Priority 1: Folder trees (most expensive, 20-30s each)
        for account_id in accounts:
            self.warming_queue.append({
                "priority": 1,
                "operation": "folder_get_tree",
                "account_id": account_id,
                "params": {"path": "/", "max_depth": 10},
                "throttle_sec": 3,  # Wait 3s after this operation
            })

        # Priority 2: Email inbox (frequently accessed, 2-5s each)
        for account_id in accounts:
            self.warming_queue.append({
                "priority": 2,
                "operation": "email_list",
                "account_id": account_id,
                "params": {"folder": "inbox", "limit": 50},
                "throttle_sec": 2,
            })

        # Priority 3: Contact list (moderate access, 1-3s each)
        for account_id in accounts:
            self.warming_queue.append({
                "priority": 3,
                "operation": "contact_list",
                "account_id": account_id,
                "params": {"limit": 100},
                "throttle_sec": 1,
            })

        # Sort by priority (lower number = higher priority)
        self.warming_queue.sort(key=lambda x: x["priority"])

        logger.info(f"Built warming queue with {len(self.warming_queue)} operations")

    async def _warming_loop(self):
        """Process warming queue with throttling"""
        self.is_warming = True
        completed = 0
        skipped = 0
        failed = 0

        for item in self.warming_queue:
            try:
                # Check if already cached
                cache_key = self._generate_cache_key(
                    item["operation"],
                    item["account_id"],
                    item["params"]
                )

                cached_data, status = self.cache_manager.get_cached(
                    operation=item["operation"],
                    account_id=item["account_id"],
                    fresh_ttl=1800,  # Accept if less than 30min old
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
                logger.warning(
                    f"Cache warming failed for {item['operation']}: {e}"
                )
                failed += 1
                continue

        self.is_warming = False
        logger.info(
            f"Cache warming complete: {completed} warmed, "
            f"{skipped} skipped, {failed} failed"
        )

    def _generate_cache_key(self, operation: str, account_id: str, params: dict) -> str:
        """Generate cache key for checking"""
        from ..cache_config import generate_cache_key
        return generate_cache_key(operation, account_id, **params)

    def get_status(self) -> dict[str, Any]:
        """Get current warming status"""
        return {
            "is_warming": self.is_warming,
            "total_operations": len(self.warming_queue),
            "remaining": sum(1 for _ in self.warming_queue if not self.is_warming),
        }
```

---

## Server Integration

### Startup Hook

In `src/m365_mcp/server.py`:

```python
from .cache_warming import CacheWarmer
from .cache_config import CACHE_WARMING_ENABLED

async def startup():
    """Server startup with cache warming"""

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

    # Server continues starting...
    return cache_manager
```

---

## Timing Example

For 2 accounts with 3 operations each:

```
T+0s:     Server starts, ready to accept requests
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

**Total Time**: ~78 seconds for 2 accounts
**User Impact**: Zero - server responsive from T+0s

---

## Configuration

In `src/m365_mcp/cache_config.py`:

```python
# Enable/disable cache warming
CACHE_WARMING_ENABLED = True

# Operations to warm, in priority order
CACHE_WARMING_OPERATIONS = [
    {
        "operation": "folder_get_tree",
        "priority": 1,
        "params": {"path": "/", "max_depth": 10},
        "throttle_sec": 3,  # High throttle for expensive operation
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

---

## User Experience

### First Request Scenarios

**Scenario 1: User waits 2+ minutes after startup**
- Cache warming complete
- **Result**: Instant response (<100ms) from cache

**Scenario 2: User makes request immediately**
- Cache warming in progress, entry not yet cached
- **Result**: Normal API speed (~30s for folder_tree)
- Next request will be cached

**Scenario 3: Request different operation**
- Operation not in warming queue
- **Result**: Normal API speed first time, cached afterward

### No Disruption

- Server responds to requests immediately (not waiting for warming)
- Background warming doesn't compete with user requests
- Failures during warming don't affect server stability

---

## Monitoring

### New MCP Tool: cache_warming_status

```python
@mcp.tool(name="cache_warming_status")
def cache_warming_status() -> dict:
    """Get current cache warming status"""
    if not warmer:
        return {"enabled": False}

    status = warmer.get_status()
    return {
        "enabled": True,
        "is_warming": status["is_warming"],
        "total_operations": status["total_operations"],
        "remaining": status["remaining"],
    }
```

---

## Edge Cases

### No Authenticated Accounts

```python
if not account_ids:
    logger.info("No authenticated accounts, skipping cache warming")
    return
```

### Warming Disabled

```python
if not CACHE_WARMING_ENABLED:
    logger.info("Cache warming disabled in configuration")
    return
```

### Account Authentication Expires During Warming

```python
try:
    result = await tool_executor(operation, account_id, params)
except AuthenticationError:
    logger.warning(f"Authentication expired for {account_id}, skipping")
    continue  # Skip this account, continue with others
```

---

## Future Enhancements

### Intelligent Warming

- Track most-used operations per account
- Warm only frequently-accessed data
- Adjust priorities based on usage patterns

### Scheduled Re-warming

- Re-warm stale cache entries before expiration
- Background refresh during low-usage periods

### Configurable Per-Account

- Allow users to disable warming for specific accounts
- Configure different warming priorities per account type

---

**Document Version**: 1.0
**Last Updated**: 2025-10-14
**Status**: Implementation Ready
