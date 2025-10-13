# Cache System Architecture - Overview

## Executive Summary

This document outlines a comprehensive SQLite-based caching system for the M365 MCP Server to dramatically improve performance and reduce Microsoft Graph API calls for frequently accessed data.

## Current Problem

The M365 MCP Server currently makes fresh API calls for every request, leading to:
- **Slow response times** for expensive operations (folder_get_tree can take 30+ seconds)
- **High API usage** causing rate limiting and quota exhaustion
- **Poor user experience** due to repetitive wait times for unchanged data
- **Scalability concerns** as usage increases

## Proposed Solution: 3-Tier Hybrid Cache

### Design Philosophy

Instead of making every operation queue-based (adding complexity), we implement a **3-tier hybrid approach**:

1. **Transparent Caching** - Fast operations return cached data immediately with no behavior change
2. **Background Refresh** - Stale cache triggers async refresh while returning cached data
3. **Task Queue** - Optional explicit queue system for expensive operations when needed

### Cache States

```
FRESH (0 - fresh_ttl)
├─> Return cached data immediately
└─> No refresh needed

STALE (fresh_ttl - stale_ttl)
├─> Return cached data immediately
└─> Trigger background refresh

EXPIRED (> stale_ttl)
├─> Fetch fresh data from API
└─> Block until complete
```

## Key Benefits

### Performance Improvements
- **folder_get_tree**: 30s → 100ms (300x faster when cached)
- **email_list**: 2-5s → 50ms (40-100x faster)
- **file_list**: 1-3s → 30ms (30-100x faster)

### API Call Reduction
- **80%+ reduction** for repeated queries
- **Intelligent invalidation** ensures fresh data after writes
- **Background refresh** reduces perceived latency

### User Experience
- **Instant responses** for cached operations
- **Transparent behavior** - tools work the same with/without cache
- **Optional cache control** - users can force refresh when needed

### Scalability
- **SQLite storage** - single file, no external dependencies
- **Efficient indexing** - fast lookups even with thousands of entries
- **Automatic cleanup** - expired entries removed periodically

## Architecture Components

### 1. SQLite Database
- **cache_entries** - Stores cached data with TTL
- **cache_tasks** - Background task queue
- **cache_invalidation** - Tracks invalidation events
- **cache_stats** - Performance metrics

### 2. CacheManager Class
- **get_cached()** - Retrieve with fresh/stale/expired logic
- **set_cached()** - Store with TTL
- **invalidate_pattern()** - Remove related cache entries
- **enqueue_task()** - Queue background jobs

### 3. Background Worker
- **Async task processor** - Executes queued operations
- **Retry logic** - Handles transient failures
- **Progress tracking** - Reports task status

### 4. Tool Integration
- **Read-only tools** - Add caching support with minimal changes
- **Write tools** - Auto-invalidate related caches
- **New cache tools** - Manage cache and view statistics

## Design Decisions

### ✅ What We're Building

- **Transparent caching** - Tools work identically with/without cache
- **Smart TTL policies** - Different expiration times per resource type
- **Automatic invalidation** - Write operations invalidate related caches
- **Background refresh** - Return stale data + refresh in background
- **Task queue system** - Optional async mode for expensive operations
- **SQLite storage** - Single file, embedded, no setup required

### ❌ What We're NOT Building

- **Distributed caching** - Single-instance only, no multi-server support
- **Real-time sync** - Polling-based refresh, not push-based
- **Cross-account sharing** - Cache isolated per account for security
- **LRU eviction** - Simple TTL-based expiration (can add later)

## Success Metrics

### Performance Targets
- **90%+ cache hit rate** for repeated queries
- **<100ms response time** for cached reads
- **<5s background refresh** for stale data

### Quality Targets
- **0 stale data issues** - Proper invalidation on writes
- **0 cache corruption** - Atomic SQLite operations
- **Graceful degradation** - System works if cache fails

## Implementation Timeline

### Phase 1: Core Infrastructure (2 days)
- Database schema and migrations
- CacheManager class implementation
- Cache configuration and policies

### Phase 2: Background Tasks (2 days)
- Task queue processor
- Background worker implementation
- Task management tools

### Phase 3: Tool Integration (3 days)
- Add caching to high-value read tools
- Add invalidation to write tools
- Testing and validation

### Phase 4: Polish & Documentation (2 days)
- Integration tests
- Performance benchmarks
- Documentation updates

**Total Estimated Time: 9 days**

## Risk Mitigation

### Technical Risks
- **Cache inconsistency** → Aggressive invalidation on writes
- **Storage growth** → Automatic cleanup of expired entries
- **Query complexity** → Indexed SQLite tables for performance

### Operational Risks
- **Cache corruption** → Fall back to direct API calls
- **Performance regression** → Cache can be disabled per-tool
- **API rate limiting** → Background refresh respects rate limits

## Next Steps

1. Review this architecture document
2. Examine detailed database schema (02-database-schema.md)
3. Review cache strategy details (03-cache-strategy.md)
4. Approve implementation plan (07-implementation-plan.md)
5. Begin Phase 1 development

## Design Decisions

### Cache Size Limits: 2GB Soft Limit ✅

**Decision:** Implement 2GB soft limit with proactive cleanup at 80% (1.6GB)

**Rationale:**
- Prevents disk space exhaustion
- Holds 20,000+ typical operations (more than sufficient)
- Soft limit = graceful cleanup, no disruption
- When 80% full, clean down to 60% (1.2GB)
- Removes expired entries first, then least-recently-used

### Compression: Selective (≥50KB entries) ✅

**Decision:** Compress entries ≥50KB with gzip level 6

**Rationale:**
- 80% space savings on large entries (folder trees, big lists)
- 2GB cache effectively holds 5-10GB of data
- CPU cost: ~20-35ms (negligible vs 30s API call)
- Small entries (<50KB) stored uncompressed for speed

**Trade-offs:**
- Pro: 5x more data fits in cache
- Pro: Reduces cache misses significantly
- Con: 20-35ms CPU overhead per large entry
- Verdict: Worth it - cache hit still <50ms vs 30,000ms API call

### Cache Warming: Progressive Async ✅

**Decision:** Warm cache on startup with prioritized, throttled background loading

**Strategy:**
- Non-blocking: Server starts immediately, warming in background
- Prioritized: folder_get_tree (slowest) → email_list → contacts
- Throttled: 2-3 seconds between operations (respects rate limits)
- Smart: Skips already-cached entries
- Resilient: Failures don't crash server

**User Experience:**
- T+0s: Server ready instantly
- T+1-2min: Most common operations cached
- First uncached request: Normal API speed (no slowdown)

### Metrics Dashboard: Later ⏸️

**Decision:** Not in initial implementation, add in future enhancement

**Rationale:**
- Cache management tools (cache_get_stats) provide CLI metrics
- Dashboard adds complexity without critical value for MVP
- Can add later based on user feedback

---

**Document Version**: 1.0
**Last Updated**: 2025-10-14
**Status**: Proposed Architecture
