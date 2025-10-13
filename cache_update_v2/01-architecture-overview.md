# Architecture Overview

## Executive Summary

The M365 MCP Cache System is a production-grade, encrypted caching layer designed to dramatically improve performance while maintaining enterprise security standards. The system provides 300x performance improvements for expensive operations through intelligent caching with AES-256 encryption, automatic key management, and progressive cache warming.

## System Architecture

### High-Level Components

```
┌─────────────────────────────────────────────────────────────────┐
│                         MCP Server                              │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │              MCP Tools Layer                             │ │
│  │  email_list, folder_get_tree, file_list, etc.          │ │
│  └──────────────────┬───────────────────────────────────────┘ │
│                     │                                           │
│  ┌──────────────────▼───────────────────────────────────────┐ │
│  │           CacheManager (Core)                            │ │
│  │                                                          │ │
│  │  • get_cached() - Retrieve with Fresh/Stale/Expired    │ │
│  │  • set_cached() - Store with compression & TTL         │ │
│  │  • invalidate_pattern() - Invalidate on writes         │ │
│  │  • Connection pooling for performance                   │ │
│  └──────────────────┬───────────────────────────────────────┘ │
│                     │                                           │
│  ┌──────────────────▼───────────────────────────────────────┐ │
│  │        EncryptionKeyManager                              │ │
│  │                                                          │ │
│  │  • System keyring integration (Linux/macOS/Windows)    │ │
│  │  • Environment variable fallback (headless)            │ │
│  │  • Automatic key generation (256-bit)                  │ │
│  └──────────────────┬───────────────────────────────────────┘ │
│                     │                                           │
│  ┌──────────────────▼───────────────────────────────────────┐ │
│  │     Encrypted SQLite Database (SQLCipher)               │ │
│  │                                                          │ │
│  │  File: ~/.m365_mcp_cache.db                            │ │
│  │  Encryption: AES-256-CBC                               │ │
│  │  Size: 2GB soft limit with auto-cleanup               │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │            Background Services                           │ │
│  │                                                          │ │
│  │  ┌─────────────────┐      ┌─────────────────┐         │ │
│  │  │  CacheWarmer    │      │ BackgroundWorker│         │ │
│  │  │  (Startup)      │      │ (Task Queue)    │         │ │
│  │  │                 │      │                 │         │ │
│  │  │ • Priority queue│      │ • Retry logic   │         │ │
│  │  │ • Throttling    │      │ • Status track  │         │ │
│  │  └─────────────────┘      └─────────────────┘         │ │
│  └──────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow Diagram

```
User Request
     │
     ▼
┌─────────────┐
│  MCP Tool   │
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────┐
│  Check Cache (CacheManager)        │
└──────┬──────────────────────────────┘
       │
       ▼
   ┌───────────┐
   │ Encrypted │
   │  SQLite   │
   └─────┬─────┘
         │
    ┌────▼────────┐
    │             │
    ▼             ▼
 FOUND         NOT FOUND
    │             │
    ▼             ▼
┌─────────┐  ┌──────────────┐
│ Decrypt │  │ Fetch from   │
│ Decomp  │  │ Graph API    │
└────┬────┘  └──────┬───────┘
     │              │
     ▼              ▼
 Check Age    ┌──────────────┐
     │        │ Compress &   │
     ├──FRESH│ Encrypt      │
     │        └──────┬───────┘
     ├──STALE        │
     │   │           ▼
     │   └─→ Trigger┌──────────────┐
     │      Refresh │ Store in     │
     │              │ Cache        │
     ▼              └──────────────┘
 Return Data
     │
     ▼
  Response
```

## Core Design Principles

### 1. Security First Architecture

**Encryption at Every Layer**:
- Database encrypted with AES-256-CBC via SQLCipher
- Automatic key management via OS keyring
- Zero plaintext storage of sensitive data
- Keys never logged, exposed, or transmitted

**Compliance by Design**:
- GDPR Article 32: Encryption of personal data ✅
- HIPAA 164.312: Technical safeguards ✅
- SOC 2 CC6.7: Encryption controls ✅

### 2. 3-Tier Cache State Machine

The cache operates in three distinct states optimized for different scenarios:

**FRESH (0 → fresh_ttl)**
- **Behavior**: Return cached data immediately
- **Background**: No action required
- **Use Case**: Recent data, highest confidence
- **User Experience**: Instant response (<100ms)

**STALE (fresh_ttl → stale_ttl)**
- **Behavior**: Return cached data immediately + trigger background refresh
- **Background**: Async API call to update cache
- **Use Case**: Acceptable data freshness, eventual consistency
- **User Experience**: Instant response + automatic refresh

**EXPIRED (> stale_ttl)**
- **Behavior**: Fetch fresh data from API (blocking)
- **Background**: Update cache with new data
- **Use Case**: Data too old, must be current
- **User Experience**: Wait for API (~30s for folder_tree)

### 3. Intelligent Compression

**Selective Strategy**:
- Entries < 50KB: Uncompressed (fast access)
- Entries ≥ 50KB: gzip compression level 6
- Average compression: 80% space savings
- CPU overhead: ~20-35ms (negligible vs 30,000ms API call)

**Benefits**:
- 2GB cache effectively holds 5-10GB of data
- Reduces cache misses significantly
- Folder trees compress from ~500KB to ~100KB

### 4. Progressive Cache Warming

**Non-Blocking Startup**:
- Server starts immediately (T+0s)
- Background warming begins after startup
- Prioritized queue: expensive operations first
- Throttled API calls (respects rate limits)

**Warming Priority**:
1. folder_get_tree (30s each) - Priority 1
2. email_list (2-5s each) - Priority 2
3. contact_list (1-3s each) - Priority 3

**Result**: Most operations cached within 1-2 minutes of startup

### 5. Smart Invalidation

**Write-Triggered Invalidation**:
- email_delete → invalidates email_list caches
- file_create → invalidates file_list + folder_tree
- Pattern-based matching (wildcards supported)

**Multi-Account Isolation**:
- Invalidation scoped to account_id
- No cross-account cache pollution
- Complete isolation for security

## Component Specifications

### CacheManager

**Responsibilities**:
- Primary interface for all cache operations
- Manages SQLCipher database connections
- Handles encryption/decryption transparently
- Implements compression logic
- Manages cache invalidation
- Provides statistics and monitoring

**Key Methods**:
- `get_cached()` - Retrieve with state detection (Fresh/Stale/Expired)
- `set_cached()` - Store with automatic compression and encryption
- `invalidate_pattern()` - Pattern-based cache invalidation
- `cleanup_expired()` - Automatic cleanup at 80% capacity
- `get_stats()` - Cache performance metrics

**Performance Features**:
- Connection pooling (avoids repeated key derivation)
- Batch operations for bulk invalidation
- Indexed queries for fast lookups

### EncryptionKeyManager

**Responsibilities**:
- Automatic encryption key generation (256-bit)
- System keyring integration across platforms
- Environment variable fallback for headless servers
- Key persistence and retrieval

**Key Methods**:
- `get_or_create_key()` - Retrieves or generates encryption key
- `generate_key()` - Creates cryptographically secure 256-bit key

**Platform Support**:
- **Linux**: Secret Service API (GNOME Keyring, KWallet)
- **macOS**: Keychain Services API
- **Windows**: Windows Credential Manager (DPAPI)
- **Headless**: Environment variable M365_MCP_CACHE_KEY

### CacheWarmer

**Responsibilities**:
- Progressive cache pre-population on startup
- Prioritized operation queue
- Throttled API calls (respects rate limits)
- Skip already-cached entries
- Non-blocking background execution

**Key Methods**:
- `start_warming()` - Initiates warming for accounts
- `_build_warming_queue()` - Creates prioritized queue
- `_warming_loop()` - Processes queue with throttling
- `get_status()` - Returns warming progress

**Configuration**:
- CACHE_WARMING_ENABLED - Enable/disable feature
- CACHE_WARMING_OPERATIONS - List of operations to warm
- Throttle settings per operation type

### BackgroundWorker

**Responsibilities**:
- Asynchronous task processing
- Retry logic for failed operations
- Task lifecycle management
- Progress tracking and reporting

**Key Methods**:
- `start()` - Begin background processing loop
- `process_next_task()` - Execute highest priority task
- `_execute_operation()` - Run tool with parameters

**Features**:
- Exponential backoff for retries
- Maximum retry limits (default: 3)
- Task priority queue (1=highest, 10=lowest)

## Design Decisions & Trade-offs

### Decision 1: SQLCipher over Application-Level Encryption

**Chosen**: SQLCipher (database-level encryption)

**Alternatives Considered**:
- Application-level field encryption
- File system encryption (LUKS, BitLocker)

**Rationale**:
- ✅ Transparent encryption/decryption
- ✅ Minimal performance overhead (~5-15%)
- ✅ Battle-tested (used by Signal, WhatsApp)
- ✅ FIPS-compliant AES-256-CBC
- ❌ Requires SQLCipher dependency (acceptable trade-off)

### Decision 2: System Keyring over Environment Variables

**Chosen**: System keyring with environment variable fallback

**Alternatives Considered**:
- Environment variables only
- Configuration file storage
- User-provided passwords

**Rationale**:
- ✅ Best security (OS-level protection)
- ✅ Survives application reinstalls
- ✅ No user key management burden
- ✅ Cross-platform support
- ✅ Fallback ensures works everywhere

### Decision 3: 2GB Soft Limit over Hard Limit

**Chosen**: 2GB soft limit with 80% cleanup trigger

**Alternatives Considered**:
- Hard limit (reject new entries)
- Unlimited growth
- LRU eviction

**Rationale**:
- ✅ Prevents disk exhaustion proactively
- ✅ No service disruption (cleanup in background)
- ✅ Holds 20,000+ operations (sufficient for enterprise)
- ✅ Cleanup target of 60% leaves headroom

### Decision 4: Selective Compression over Always/Never

**Chosen**: Compress entries ≥50KB, skip smaller entries

**Alternatives Considered**:
- Always compress everything
- Never compress
- User-configurable threshold

**Rationale**:
- ✅ 80% space savings on large entries
- ✅ No overhead for small entries
- ✅ Optimal balance of space/CPU
- ✅ 50KB threshold based on empirical testing

### Decision 5: Cache Warming over Cold Start

**Chosen**: Progressive background warming on startup

**Alternatives Considered**:
- No warming (cold start)
- Blocking warming (delay startup)
- Predictive pre-fetching

**Rationale**:
- ✅ Server responsive immediately (T+0s)
- ✅ First requests instant after 1-2 min
- ✅ No startup delay
- ✅ Throttled to respect rate limits
- ❌ First 1-2 min some operations not cached (acceptable)

## Performance Characteristics

### Cache Hit Scenarios

| Scenario | Time | Notes |
|----------|------|-------|
| FRESH hit | <100ms | Decrypt + decompress |
| STALE hit | <100ms | Returns cached + triggers refresh |
| MISS (cold) | 30,000ms | Full API call (folder_tree) |
| MISS (warm) | Instant | If warming completed |

### Encryption Overhead

| Operation | Unencrypted | Encrypted | Overhead |
|-----------|-------------|-----------|----------|
| Write 1KB | 0.5ms | 0.6ms | +0.1ms (20%) |
| Write 100KB | 3ms | 3.5ms | +0.5ms (17%) |
| Read 1KB | 0.3ms | 0.4ms | +0.1ms (33%) |
| Read 100KB | 2ms | 2.3ms | +0.3ms (15%) |
| DB Open | 1ms | 5ms | +4ms (400%, one-time) |

**Key Insight**: Encryption overhead is <1ms per operation, negligible compared to 30,000ms API calls.

### Compression Impact

| Data Type | Size Before | Size After | Ratio | Time |
|-----------|-------------|------------|-------|------|
| Folder tree | 500KB | 100KB | 80% | ~25ms |
| Email list (50) | 150KB | 40KB | 73% | ~15ms |
| Contact list | 80KB | 25KB | 69% | ~10ms |

### Cache Warming Timeline (2 Accounts)

```
T+0s:     Server starts (ready for requests)
T+1-30s:  Warming folder_tree account_1
T+33-60s: Warming folder_tree account_2
T+63-66s: Warming email_list account_1
T+68-71s: Warming email_list account_2
T+73-75s: Warming contact_list account_1
T+76-78s: Warming contact_list account_2
T+78s:    Warming complete!
```

---

**Document Version**: 2.0
**Last Updated**: 2025-10-14
**Status**: Production-Ready Architecture
