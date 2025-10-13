# Implementation Plan

## Overview

**Total Estimated Time**: 9 days
**Phases**: 4
**Target**: Zero breaking changes, optional cache usage

---

## Phase 1: Core Infrastructure (Days 1-2)

### Day 1: Database & Config

**Tasks:**
1. Create `src/m365_mcp/migrations/001_init_cache.sql`
   - All table definitions
   - Indexes for performance

2. Create `src/m365_mcp/cache_config.py`
   - TTL_POLICIES dictionary
   - CACHE_LIMITS configuration
   - generate_cache_key() function

3. Initialize database on server startup
   - Modify `src/m365_mcp/server.py`
   - Run migration on first start
   - Create global cache_manager instance

**Deliverables:**
- Database schema file
- Configuration module
- Server initialization code

**Testing:**
- Database creates successfully
- Migrations run without errors
- Cache manager instantiates

### Day 2: CacheManager Implementation

**Tasks:**
1. Create `src/m365_mcp/cache.py` with CacheManager class
   - `__init__()` and `_init_database()`
   - `get_cached()` with fresh/stale/expired logic
   - `set_cached()` with TTL support
   - `invalidate_pattern()` for write operations
   - `cleanup_expired()` for maintenance

2. Add utility methods
   - `get_stats()` for metrics
   - `_db()` context manager
   - Error handling and logging

**Deliverables:**
- Complete CacheManager class (~500 lines)
- Unit tests for all methods

**Testing:**
- Cache set/get operations
- TTL expiration behavior
- Pattern invalidation
- Cleanup functionality

---

## Phase 2: Background Task System (Days 3-4)

### Day 3: Task Queue

**Tasks:**
1. Add task methods to CacheManager
   - `enqueue_task()`
   - `get_task_status()`
   - `list_tasks()`
   - `_update_task_status()`

2. Create `src/m365_mcp/background_worker.py`
   - BackgroundWorker class
   - Task processing loop
   - Error handling and retries

**Deliverables:**
- Task queue methods
- Background worker implementation

**Testing:**
- Task enqueueing
- Status tracking
- Task listing

### Day 4: Cache Management Tools

**Tasks:**
1. Create `src/m365_mcp/tools/cache_tools.py`
   - `task_get_status()` tool
   - `task_list()` tool
   - `cache_get_stats()` tool
   - `cache_invalidate()` tool

2. Register tools with MCP instance

**Deliverables:**
- 4 new cache management tools
- Tool documentation

**Testing:**
- Task status retrieval
- Cache stats calculation
- Manual invalidation

---

## Phase 3: Tool Integration (Days 5-7)

### Day 5: High-Priority Tools

**Integrate caching into:**
1. `folder_get_tree` (src/m365_mcp/tools/folder.py:163)
   - Add use_cache and force_refresh parameters
   - Implement cache check before API call
   - Store result in cache after fetch
   - TTL: fresh=30min, stale=2h

2. `email_list` (src/m365_mcp/tools/email.py)
   - Add cache support
   - TTL: fresh=2min, stale=10min

**Testing:**
- Cache hit/miss scenarios
- Force refresh functionality
- Performance benchmarks

### Day 6: Supporting Tools + Write Invalidation

**Read tools:**
3. `file_list`
4. `folder_list`
5. `email_get`

**Write tools (add invalidation):**
1. `email_delete` → invalidate email_list
2. `email_move` → invalidate email_list
3. `email_send` → invalidate email_list (sent folder)
4. `file_create` → invalidate file_list + folder_tree
5. `file_delete` → invalidate file_list + folder_tree

**Testing:**
- Verify cache invalidation triggers
- Test across multiple accounts
- Edge cases (concurrent operations)

### Day 7: Remaining Tools

**Complete caching for:**
- `file_get`
- `contact_list`
- `contact_get`
- All remaining write operations

**Testing:**
- End-to-end integration tests
- Multi-account scenarios
- Cache isolation verification

---

## Phase 4: Testing & Documentation (Days 8-9)

### Day 8: Comprehensive Testing

**Tasks:**
1. Integration tests (tests/test_cache_integration.py)
   - Cache hit/miss scenarios
   - TTL expiration behavior
   - Invalidation on writes
   - Background task execution
   - Multi-account isolation

2. Performance benchmarks
   - Before/after comparisons
   - Cache hit rate measurements
   - Response time improvements

3. Load testing
   - Large cache sizes
   - Many concurrent operations
   - Cleanup under load

**Deliverables:**
- Complete test suite
- Performance benchmark report

### Day 9: Documentation & Polish

**Tasks:**
1. Update documentation
   - CLAUDE.md: Add caching patterns
   - CHANGELOG.md: Document new features
   - FILETREE.md: New files added

2. Create user guide
   - How to use cache parameters
   - When to force refresh
   - Viewing cache statistics

3. Code review and cleanup
   - Remove debug logging
   - Optimize queries
   - Final polish

**Deliverables:**
- Updated documentation
- User guide for caching features
- Release-ready code

---

## Files Created

### New Files (8 total)
1. `src/m365_mcp/cache.py` (~500 lines)
2. `src/m365_mcp/cache_config.py` (~150 lines)
3. `src/m365_mcp/background_worker.py` (~300 lines)
4. `src/m365_mcp/tools/cache_tools.py` (~200 lines)
5. `src/m365_mcp/migrations/001_init_cache.sql` (~100 lines)
6. `tests/test_cache_integration.py` (~400 lines)
7. `docs/cache_user_guide.md` (~200 lines)
8. `cache_update/` folder (this documentation)

### Modified Files (7 total)
1. `src/m365_mcp/server.py` - Initialize cache on startup
2. `src/m365_mcp/tools/folder.py` - Add caching to folder_get_tree
3. `src/m365_mcp/tools/email.py` - Add caching + invalidation
4. `src/m365_mcp/tools/file.py` - Add caching + invalidation
5. `pyproject.toml` - Add aiosqlite dependency
6. `CHANGELOG.md` - Document changes
7. `FILETREE.md` - Update file tree

---

## Dependencies

### New Python Packages
```toml
# Add to pyproject.toml
dependencies = [
    # ... existing ...
    "aiosqlite>=0.19.0",  # For async SQLite operations (optional)
]
```

**Note**: Standard library `sqlite3` is sufficient for sync operations. `aiosqlite` only needed if we implement async background worker.

---

## Rollback Plan

If caching causes issues:

1. **Disable caching globally**
   ```python
   # In cache_config.py
   CACHE_ENABLED = False
   ```

2. **Per-tool disable**
   ```python
   folder_get_tree(account_id, use_cache=False)
   ```

3. **Complete removal**
   - Remove cache_manager initialization from server.py
   - Cache parameters are optional, tools work without them

---

## Success Metrics

### Performance Targets
- **folder_get_tree**: 30s → <100ms (cached)
- **Cache hit rate**: >80% for repeated queries
- **API call reduction**: >70%

### Quality Targets
- **Zero data inconsistencies** after writes
- **Zero cache corruption** under normal operation
- **Graceful degradation** if cache unavailable

### User Experience
- **Transparent operation** - tools work identically
- **Optional control** - users can force refresh
- **Clear status** - cache status included in responses

---

## Post-Launch

### Monitoring
- Track cache hit rates
- Monitor cache size growth
- Identify invalidation patterns

### Optimizations (Future)
- LRU eviction policy
- Compression for large entries
- Cache warming on startup
- Predictive pre-fetching

### Potential Enhancements
- Cache statistics dashboard tool
- Cache export/import for debugging
- Distributed cache (Redis) option
- Real-time cache invalidation via webhooks
