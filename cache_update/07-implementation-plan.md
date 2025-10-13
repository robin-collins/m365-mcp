# Implementation Plan

## Overview

**Total Estimated Time**: 14 days
**Phases**: 5 (includes encryption + cache warming)
**Target**: Zero breaking changes, optional cache usage, GDPR/HIPAA compliant encryption

---

## Phase 1: Core Infrastructure + Encryption (Days 1-3)

### Day 1: Encryption Foundation

**Tasks:**
1. Add encryption dependencies to `pyproject.toml`
   - sqlcipher3>=0.5.0
   - keyring>=24.0.0

2. Create `src/m365_mcp/encryption.py`
   - EncryptionKeyManager class
   - get_or_create_key() method
   - System keyring integration
   - Environment variable fallback

3. Unit tests for encryption
   - Key generation tests
   - Keyring storage/retrieval tests
   - Environment variable fallback tests

**Deliverables:**
- Encryption module (~250 lines)
- Encryption unit tests
- Cross-platform keyring integration

**Testing:**
- Key generation produces secure 256-bit keys
- Keys persist across sessions (keyring)
- Environment variable fallback works

### Day 2: Database Schema & Config

**Tasks:**
1. Create `src/m365_mcp/migrations/001_init_cache.sql`
   - All table definitions (cache_entries, cache_tasks, etc.)
   - Indexes for performance
   - Encryption-ready schema

2. Create `src/m365_mcp/cache_config.py`
   - TTL_POLICIES dictionary
   - CACHE_LIMITS configuration (including compression threshold)
   - CACHE_WARMING_OPERATIONS configuration
   - generate_cache_key() function

3. Initialize database on server startup
   - Modify `src/m365_mcp/server.py`
   - Run migration on first start
   - Create global cache_manager instance with encryption

**Deliverables:**
- Database schema file
- Configuration module
- Server initialization code

**Testing:**
- Database creates successfully with encryption
- Migrations run without errors
- Cache manager instantiates with encryption enabled

### Day 3: Encrypted CacheManager Implementation

**Tasks:**
1. Create `src/m365_mcp/cache.py` with encrypted CacheManager class
   - `__init__()` with encryption support
   - `_init_database()` with SQLCipher integration
   - `_db()` context manager with encryption key setup
   - `get_cached()` with fresh/stale/expired logic (compressed/encrypted data)
   - `set_cached()` with TTL and compression support
   - `invalidate_pattern()` for write operations
   - `cleanup_expired()` for maintenance

2. Create `src/m365_mcp/cache_migration.py`
   - migrate_to_encrypted_cache() function
   - Automatic migration detection and execution

3. Add utility methods
   - `get_stats()` for metrics
   - Compression/decompression helpers
   - Error handling and logging

**Deliverables:**
- Complete encrypted CacheManager class (~600 lines)
- Cache migration module (~150 lines)
- Unit tests for all methods including encryption

**Testing:**
- Encrypted cache set/get operations
- Encryption key mismatch handling
- TTL expiration behavior
- Pattern invalidation
- Compression for large entries (≥50KB)
- Cleanup functionality
- Migration from unencrypted to encrypted cache

---

## Phase 2: Background Tasks + Cache Warming (Days 4-6)

### Day 4: Task Queue

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

### Day 5: Cache Management Tools

**Tasks:**
1. Create `src/m365_mcp/tools/cache_tools.py`
   - `cache_task_get_status()` tool (with proper annotations)
   - `cache_task_list()` tool (with proper annotations)
   - `cache_get_stats()` tool (with proper annotations)
   - `cache_invalidate()` tool (with proper annotations)
   - `cache_warming_status()` tool (with proper annotations)

2. Register tools with MCP instance

**Deliverables:**
- 5 new cache management tools with proper safety annotations
- Tool documentation following steering guidelines

**Testing:**
- Task status retrieval
- Cache stats calculation
- Manual invalidation
- Tool annotations comply with tool-names.md standards

### Day 6: Cache Warming Implementation

**Tasks:**
1. Create `src/m365_mcp/cache_warming.py`
   - CacheWarmer class
   - start_warming() method
   - _build_warming_queue() method
   - _warming_loop() with throttling
   - get_status() for monitoring

2. Integrate cache warming into server.py startup
   - Initialize CacheWarmer on server start
   - Non-blocking background warming
   - Prioritized operation queue

3. Add cache warming configuration
   - Update cache_config.py with CACHE_WARMING_ENABLED
   - Define CACHE_WARMING_OPERATIONS list
   - Throttling configuration

**Deliverables:**
- Cache warming module (~250 lines)
- Server integration
- Warming configuration

**Testing:**
- Cache warming starts on server startup
- Operations queued in priority order
- Throttling respects rate limits
- Failures don't crash server
- Already-cached entries skipped

---

## Phase 3: Tool Integration (Days 7-9)

### Day 7: High-Priority Tools

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

### Day 8: Supporting Tools + Write Invalidation

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

### Day 9: Remaining Tools

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

## Phase 4: Integration Testing (Days 10-11)

### Day 10: Comprehensive Integration Testing

**Tasks:**
1. Integration tests (tests/test_cache_integration.py)
   - Cache hit/miss scenarios
   - TTL expiration behavior
   - Invalidation on writes
   - Background task execution
   - Multi-account isolation
   - Cache warming functionality
   - Encryption integration tests

2. Encryption-specific tests (tests/test_encryption.py)
   - Encrypted read/write operations
   - Key mismatch handling
   - Migration from unencrypted cache
   - Cross-platform keyring compatibility

3. Performance benchmarks
   - Before/after comparisons (with/without cache)
   - Encrypted vs unencrypted performance
   - Cache hit rate measurements
   - Response time improvements
   - Cache warming impact

**Deliverables:**
- Complete integration test suite
- Encryption test suite
- Performance benchmark report

**Testing:**
- All tests pass on Linux, macOS, Windows
- Encryption overhead <1ms per operation
- Cache hit rate >80% for repeated queries

### Day 11: Security Testing & Load Testing

**Tasks:**
1. Security audit
   - Verify encryption key never logged
   - Test encryption key mismatch scenarios
   - Validate no sensitive data in error messages
   - Confirm GDPR/HIPAA compliance checklist

2. Load testing
   - Large cache sizes (approaching 2GB limit)
   - Many concurrent operations
   - Cleanup under load
   - Cache warming with multiple accounts
   - Background task queue under pressure

3. Edge case testing
   - No keyring available (headless server)
   - Corrupted cache database
   - Encryption key rotation
   - Concurrent access from multiple processes

**Deliverables:**
- Security audit report
- Load test results
- Edge case test coverage

**Testing:**
- No encryption keys exposed in logs/errors
- System handles 2GB cache gracefully
- Concurrent operations don't corrupt cache
- Graceful degradation when keyring unavailable

---

## Phase 5: Documentation & Release (Days 12-14)

### Day 12: Core Documentation Updates

**Tasks:**
1. Update CLAUDE.md
   - Add caching architecture section
   - Document encryption implementation
   - Add cache tool usage patterns
   - Update common patterns with cache examples

2. Update steering documents (if needed)
   - .projects/steering/tech.md (add encryption dependencies)
   - .projects/steering/structure.md (add cache modules)

3. Update README.md
   - Add cache features section
   - Document encryption capabilities
   - Add cache warming information

**Deliverables:**
- Updated project documentation
- Steering documents current
- README reflects new capabilities

### Day 13: User Documentation & Examples

**Tasks:**
1. Create docs/cache_user_guide.md
   - How to use cache parameters (use_cache, force_refresh)
   - When to force refresh
   - Viewing cache statistics
   - Manual cache invalidation
   - Cache warming monitoring
   - Troubleshooting encryption issues

2. Create docs/cache_security.md
   - Encryption details and compliance
   - Key management best practices
   - Security considerations
   - GDPR/HIPAA compliance information

3. Add cache examples
   - Common caching patterns
   - Performance optimization tips
   - Multi-account cache management

**Deliverables:**
- User guide (~300 lines)
- Security documentation
- Example code and patterns

### Day 14: Final Polish & Release Prep

**Tasks:**
1. Update CHANGELOG.md
   - Document all new features
   - List new cache tools
   - Document encryption implementation
   - Note breaking changes (none expected)

2. Update FILETREE.md
   - Add all new cache-related files
   - Update module structure

3. Code review and cleanup
   - Remove debug logging
   - Optimize database queries
   - Ensure PEP 8 compliance
   - Type hint verification (pyright)
   - Format with ruff

4. Final testing sweep
   - Run full test suite
   - Verify all documentation links
   - Test on clean environment

**Deliverables:**
- Complete changelog
- Updated file tree
- Production-ready code
- Release notes

**Final Checklist:**
- [ ] All tests passing (pytest)
- [ ] Type checking clean (pyright)
- [ ] Code formatted (ruff format)
- [ ] Linting clean (ruff check)
- [ ] Documentation complete
- [ ] Security audit passed
- [ ] Performance benchmarks documented
- [ ] CHANGELOG.md updated
- [ ] FILETREE.md updated

---

## Files Created

### New Files (14 total)
1. `src/m365_mcp/encryption.py` (~250 lines) - Encryption key management
2. `src/m365_mcp/cache.py` (~600 lines) - Encrypted CacheManager
3. `src/m365_mcp/cache_config.py` (~200 lines) - Configuration and TTL policies
4. `src/m365_mcp/cache_migration.py` (~150 lines) - Unencrypted → encrypted migration
5. `src/m365_mcp/cache_warming.py` (~250 lines) - Progressive cache warming
6. `src/m365_mcp/background_worker.py` (~300 lines) - Background task processor
7. `src/m365_mcp/tools/cache_tools.py` (~300 lines) - 5 cache management tools
8. `src/m365_mcp/migrations/001_init_cache.sql` (~100 lines) - Database schema
9. `tests/test_encryption.py` (~300 lines) - Encryption tests
10. `tests/test_cache_integration.py` (~500 lines) - Integration tests
11. `docs/cache_user_guide.md` (~300 lines) - User documentation
12. `docs/cache_security.md` (~200 lines) - Security documentation
13. `cache_update/` folder (this documentation - 9 files)
14. `reports/cache_performance_benchmarks.md` (~150 lines) - Performance report

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
    # ... existing dependencies ...
    "sqlcipher3>=0.5.0",    # SQLCipher for encrypted database (required)
    "keyring>=24.0.0",      # System keyring integration (required)
]
```

**Key Dependencies:**
- **sqlcipher3**: Replaces standard sqlite3, provides AES-256 encryption
- **keyring**: Cross-platform system keyring access (Linux/macOS/Windows)

**Note**: These dependencies are required for encryption. Standard library `sqlite3` is NOT sufficient due to encryption requirements.

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
- **Encryption overhead**: <1ms per operation
- **Cache warming**: Complete in <2 minutes for 2 accounts

### Quality Targets
- **Zero data inconsistencies** after writes
- **Zero cache corruption** under normal operation
- **Graceful degradation** if cache or encryption unavailable
- **GDPR/HIPAA compliance** - all data encrypted at rest

### Security Targets
- **No encryption keys** in logs or error messages
- **Automatic key management** via system keyring
- **Encrypted migration** from unencrypted cache without data loss
- **Cross-platform** encryption (Linux, macOS, Windows)

### User Experience
- **Transparent operation** - tools work identically with encryption
- **Zero configuration** - encryption automatic
- **Optional control** - users can force refresh, disable cache
- **Clear status** - cache status included in responses
- **Performance** - no perceptible slowdown from encryption

---

## Post-Launch

### Monitoring
- Track cache hit rates per tool
- Monitor cache size growth and cleanup
- Identify invalidation patterns
- Track encryption performance overhead
- Monitor cache warming effectiveness

### Optimizations (Future - Phase 6+)
- **LRU eviction policy** (in addition to TTL-based)
- **Predictive pre-fetching** based on usage patterns
- **Adaptive TTL** - adjust based on update frequency
- **Intelligent warming** - learn most-used operations per account

### Potential Enhancements
- **Cache statistics dashboard** (web-based visualization)
- **Cache export/import** for debugging and migration
- **Distributed cache** (Redis) option for multi-server deployments
- **Real-time invalidation** via Microsoft Graph webhooks
- **Compression algorithm tuning** for specific data types
- **Encryption key rotation** support
