# Database Schema

## Overview

The M365 MCP Cache uses SQLCipher for encrypted SQLite storage. All data is encrypted at rest using AES-256-CBC encryption with automatic key management via system keyring.

**Database Location**: `~/.m365_mcp_cache.db`
**Encryption**: AES-256-CBC via SQLCipher
**Size Limit**: 2GB soft limit (automatic cleanup at 80%)

## SQLCipher Configuration

### Encryption Settings

```sql
-- Applied on every database connection
PRAGMA key = '<encryption_key_from_keyring>';
PRAGMA cipher_page_size = 4096;
PRAGMA kdf_iter = 256000;
PRAGMA cipher_hmac_algorithm = HMAC_SHA512;
PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512;
```

### Security Specifications

| Setting | Value | Purpose |
|---------|-------|---------|
| Cipher | AES-256-CBC | FIPS-compliant encryption |
| Key Derivation | PBKDF2-HMAC-SHA512 | Secure key derivation function |
| KDF Iterations | 256,000 | Resistance to brute-force attacks |
| Page Size | 4096 bytes | Optimal performance/security balance |
| HMAC | SHA512 | Authentication and integrity verification |

## Database Tables

### Table: cache_entries

Primary table storing all cached data with TTL management, compression, and encryption metadata.

```sql
CREATE TABLE cache_entries (
    -- Primary Key
    cache_key TEXT PRIMARY KEY,

    -- Account & Resource Identification
    account_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,

    -- Data Storage (encrypted by SQLCipher)
    data_blob BLOB NOT NULL,
    is_compressed INTEGER DEFAULT 0,

    -- Metadata
    metadata_json TEXT,
    size_bytes INTEGER NOT NULL,
    uncompressed_size INTEGER,

    -- TTL Management
    created_at REAL NOT NULL,
    accessed_at REAL NOT NULL,
    expires_at REAL NOT NULL,

    -- Statistics
    hit_count INTEGER DEFAULT 0,
    version INTEGER DEFAULT 1,

    -- Constraints
    CHECK (is_compressed IN (0, 1)),
    CHECK (size_bytes > 0),
    CHECK (expires_at > created_at)
);

-- Performance Indexes
CREATE INDEX idx_cache_account ON cache_entries(account_id);
CREATE INDEX idx_cache_resource ON cache_entries(resource_type);
CREATE INDEX idx_cache_expires ON cache_entries(expires_at);
CREATE INDEX idx_cache_accessed ON cache_entries(accessed_at);
CREATE INDEX idx_cache_size ON cache_entries(size_bytes);
```

**Field Descriptions**:

| Field | Type | Description |
|-------|------|-------------|
| cache_key | TEXT | Unique identifier: `operation:account_id:params_hash` |
| account_id | TEXT | Microsoft account identifier for isolation |
| resource_type | TEXT | Operation type: `folder_get_tree`, `email_list`, etc. |
| data_blob | BLOB | Encrypted JSON data (optionally compressed) |
| is_compressed | INTEGER | 0=uncompressed, 1=gzip compressed |
| metadata_json | TEXT | Query parameters, item counts, etc. |
| size_bytes | INTEGER | Size of data_blob in bytes |
| uncompressed_size | INTEGER | Original size before compression (if compressed) |
| created_at | REAL | Unix timestamp of cache entry creation |
| accessed_at | REAL | Unix timestamp of last access (for LRU) |
| expires_at | REAL | Unix timestamp when entry expires |
| hit_count | INTEGER | Number of times entry was accessed |
| version | INTEGER | Schema version for future migrations |

**Compression Logic**:
- Entries < 50KB: is_compressed=0, data_blob=raw JSON
- Entries ≥ 50KB: is_compressed=1, data_blob=gzip(JSON)
- uncompressed_size stores original size for statistics

### Table: cache_tasks

Background task queue for asynchronous operations and cache refresh.

```sql
CREATE TABLE cache_tasks (
    -- Primary Key
    task_id TEXT PRIMARY KEY,

    -- Task Identification
    account_id TEXT NOT NULL,
    task_type TEXT NOT NULL,
    operation TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    cache_key TEXT,

    -- Status Management
    status TEXT NOT NULL,
    priority INTEGER DEFAULT 5,

    -- Results
    result_json TEXT,
    error_text TEXT,
    progress_pct INTEGER DEFAULT 0,

    -- Timing
    created_at REAL NOT NULL,
    started_at REAL,
    completed_at REAL,

    -- Retry Logic
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,

    -- Constraints
    CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    CHECK (priority BETWEEN 1 AND 10),
    CHECK (progress_pct BETWEEN 0 AND 100)
);

-- Performance Indexes
CREATE INDEX idx_tasks_status ON cache_tasks(status, priority);
CREATE INDEX idx_tasks_account ON cache_tasks(account_id);
CREATE INDEX idx_tasks_created ON cache_tasks(created_at);
```

**Field Descriptions**:

| Field | Type | Description |
|-------|------|-------------|
| task_id | TEXT | Unique UUID for task tracking |
| account_id | TEXT | Account this task belongs to |
| task_type | TEXT | Type: `cache_refresh`, `folder_tree_bg`, etc. |
| operation | TEXT | MCP tool name: `folder_get_tree`, etc. |
| parameters_json | TEXT | JSON-encoded operation parameters |
| cache_key | TEXT | Associated cache key (if applicable) |
| status | TEXT | Current status: queued/running/completed/failed |
| priority | INTEGER | Priority 1-10 (1=highest, 10=lowest) |
| result_json | TEXT | Operation result (on success) |
| error_text | TEXT | Error message (on failure) |
| progress_pct | INTEGER | Progress percentage (0-100) |
| created_at | REAL | Task creation timestamp |
| started_at | REAL | Task execution start timestamp |
| completed_at | REAL | Task completion timestamp |
| retry_count | INTEGER | Number of retry attempts |
| max_retries | INTEGER | Maximum allowed retries |

**Task Lifecycle**:
1. Created with status='queued', priority set
2. BackgroundWorker picks up, sets status='running', started_at
3. On success: status='completed', result_json set, completed_at
4. On failure: retry_count++, back to 'queued' or 'failed'

### Table: cache_invalidation

Audit log for cache invalidation events (debugging and monitoring).

```sql
CREATE TABLE cache_invalidation (
    -- Primary Key
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Invalidation Details
    account_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    pattern TEXT NOT NULL,
    reason TEXT,

    -- Timing & Impact
    invalidated_at REAL NOT NULL,
    invalidated_count INTEGER DEFAULT 0
);

-- Performance Indexes
CREATE INDEX idx_invalidation_account ON cache_invalidation(account_id, resource_type);
CREATE INDEX idx_invalidation_time ON cache_invalidation(invalidated_at);
```

**Field Descriptions**:

| Field | Type | Description |
|-------|------|-------------|
| id | INTEGER | Auto-incrementing primary key |
| account_id | TEXT | Account where invalidation occurred |
| resource_type | TEXT | Resource type invalidated |
| pattern | TEXT | Pattern used for matching (wildcards) |
| reason | TEXT | Reason: `email_delete`, `file_create`, etc. |
| invalidated_at | REAL | Timestamp of invalidation |
| invalidated_count | INTEGER | Number of entries invalidated |

**Use Cases**:
- Debugging cache inconsistencies
- Monitoring invalidation frequency
- Analyzing cache effectiveness
- Compliance audit trails

### Table: cache_stats

Performance metrics and statistics (periodically aggregated).

```sql
CREATE TABLE cache_stats (
    -- Primary Key
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Aggregation Period
    timestamp REAL NOT NULL,
    period_start REAL NOT NULL,
    period_end REAL NOT NULL,

    -- Resource Type
    resource_type TEXT NOT NULL,

    -- Cache Performance
    hit_count INTEGER DEFAULT 0,
    miss_count INTEGER DEFAULT 0,
    eviction_count INTEGER DEFAULT 0,

    -- Timing Statistics
    avg_response_time_ms REAL,
    p50_response_time_ms REAL,
    p95_response_time_ms REAL,
    p99_response_time_ms REAL,

    -- Size Statistics
    total_entries INTEGER DEFAULT 0,
    total_size_bytes INTEGER DEFAULT 0,
    avg_entry_size_bytes INTEGER DEFAULT 0
);

-- Performance Indexes
CREATE INDEX idx_stats_resource ON cache_stats(resource_type, timestamp);
CREATE INDEX idx_stats_time ON cache_stats(timestamp);
```

**Field Descriptions**:

| Field | Type | Description |
|-------|------|-------------|
| id | INTEGER | Auto-incrementing primary key |
| timestamp | REAL | Aggregation timestamp |
| period_start | REAL | Start of measurement period |
| period_end | REAL | End of measurement period |
| resource_type | TEXT | Resource type or 'global' for overall |
| hit_count | INTEGER | Cache hits in period |
| miss_count | INTEGER | Cache misses in period |
| eviction_count | INTEGER | Entries evicted in period |
| avg_response_time_ms | REAL | Average response time |
| p50_response_time_ms | REAL | Median response time |
| p95_response_time_ms | REAL | 95th percentile response time |
| p99_response_time_ms | REAL | 99th percentile response time |
| total_entries | INTEGER | Total entries at end of period |
| total_size_bytes | INTEGER | Total cache size at end of period |
| avg_entry_size_bytes | INTEGER | Average entry size |

**Aggregation**:
- Computed every hour for per-resource stats
- Computed daily for global stats
- Used by `cache_get_stats` tool

## Migration Script

### Location

`src/m365_mcp/migrations/001_init_cache.sql`

### Complete Schema

```sql
-- ============================================================
-- M365 MCP Cache Database Schema v1.0
-- Encrypted with SQLCipher AES-256-CBC
-- ============================================================

-- Table 1: cache_entries
CREATE TABLE IF NOT EXISTS cache_entries (
    cache_key TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    data_blob BLOB NOT NULL,
    is_compressed INTEGER DEFAULT 0,
    metadata_json TEXT,
    size_bytes INTEGER NOT NULL,
    uncompressed_size INTEGER,
    created_at REAL NOT NULL,
    accessed_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    hit_count INTEGER DEFAULT 0,
    version INTEGER DEFAULT 1,
    CHECK (is_compressed IN (0, 1)),
    CHECK (size_bytes > 0),
    CHECK (expires_at > created_at)
);

CREATE INDEX IF NOT EXISTS idx_cache_account ON cache_entries(account_id);
CREATE INDEX IF NOT EXISTS idx_cache_resource ON cache_entries(resource_type);
CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache_entries(expires_at);
CREATE INDEX IF NOT EXISTS idx_cache_accessed ON cache_entries(accessed_at);
CREATE INDEX IF NOT EXISTS idx_cache_size ON cache_entries(size_bytes);

-- Table 2: cache_tasks
CREATE TABLE IF NOT EXISTS cache_tasks (
    task_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    task_type TEXT NOT NULL,
    operation TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    cache_key TEXT,
    status TEXT NOT NULL,
    priority INTEGER DEFAULT 5,
    result_json TEXT,
    error_text TEXT,
    progress_pct INTEGER DEFAULT 0,
    created_at REAL NOT NULL,
    started_at REAL,
    completed_at REAL,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    CHECK (priority BETWEEN 1 AND 10),
    CHECK (progress_pct BETWEEN 0 AND 100)
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON cache_tasks(status, priority);
CREATE INDEX IF NOT EXISTS idx_tasks_account ON cache_tasks(account_id);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON cache_tasks(created_at);

-- Table 3: cache_invalidation
CREATE TABLE IF NOT EXISTS cache_invalidation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    pattern TEXT NOT NULL,
    reason TEXT,
    invalidated_at REAL NOT NULL,
    invalidated_count INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_invalidation_account
    ON cache_invalidation(account_id, resource_type);
CREATE INDEX IF NOT EXISTS idx_invalidation_time
    ON cache_invalidation(invalidated_at);

-- Table 4: cache_stats
CREATE TABLE IF NOT EXISTS cache_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    period_start REAL NOT NULL,
    period_end REAL NOT NULL,
    resource_type TEXT NOT NULL,
    hit_count INTEGER DEFAULT 0,
    miss_count INTEGER DEFAULT 0,
    eviction_count INTEGER DEFAULT 0,
    avg_response_time_ms REAL,
    p50_response_time_ms REAL,
    p95_response_time_ms REAL,
    p99_response_time_ms REAL,
    total_entries INTEGER DEFAULT 0,
    total_size_bytes INTEGER DEFAULT 0,
    avg_entry_size_bytes INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_stats_resource
    ON cache_stats(resource_type, timestamp);
CREATE INDEX IF NOT EXISTS idx_stats_time
    ON cache_stats(timestamp);

-- Initial stats entry
INSERT INTO cache_stats (
    timestamp, period_start, period_end, resource_type,
    hit_count, miss_count
)
VALUES (
    strftime('%s', 'now'),
    strftime('%s', 'now'),
    strftime('%s', 'now'),
    'system',
    0, 0
);
```

## Common Queries

### Get Cache Statistics

```sql
-- Overall cache size and entry count
SELECT
    COUNT(*) as total_entries,
    SUM(size_bytes) as total_bytes,
    SUM(size_bytes) / 1024.0 / 1024.0 as total_mb,
    AVG(size_bytes) as avg_bytes,
    SUM(CASE WHEN is_compressed = 1 THEN 1 ELSE 0 END) as compressed_entries
FROM cache_entries;
```

### Find Expired Entries

```sql
-- Find all expired cache entries
SELECT cache_key, resource_type, account_id, expires_at
FROM cache_entries
WHERE expires_at < strftime('%s', 'now')
ORDER BY expires_at ASC
LIMIT 100;
```

### Cache Hit Rate by Resource Type

```sql
-- Cache hit rate per resource type
SELECT
    resource_type,
    COUNT(*) as entries,
    SUM(hit_count) as total_hits,
    AVG(hit_count) as avg_hits_per_entry,
    MIN(created_at) as oldest_entry,
    MAX(created_at) as newest_entry
FROM cache_entries
GROUP BY resource_type
ORDER BY total_hits DESC;
```

### Top Cached Entries by Size

```sql
-- Largest cache entries
SELECT
    cache_key,
    resource_type,
    size_bytes,
    size_bytes / 1024.0 as size_kb,
    is_compressed,
    hit_count,
    datetime(created_at, 'unixepoch') as created
FROM cache_entries
ORDER BY size_bytes DESC
LIMIT 20;
```

### Task Queue Status

```sql
-- Current task queue status
SELECT
    status,
    COUNT(*) as count,
    AVG(priority) as avg_priority,
    MIN(created_at) as oldest_task,
    AVG(retry_count) as avg_retries
FROM cache_tasks
GROUP BY status;
```

### Recent Invalidations

```sql
-- Recent cache invalidations
SELECT
    account_id,
    resource_type,
    pattern,
    reason,
    invalidated_count,
    datetime(invalidated_at, 'unixepoch') as invalidated_time
FROM cache_invalidation
ORDER BY invalidated_at DESC
LIMIT 50;
```

## Database Maintenance

### Cleanup Expired Entries

```sql
-- Remove expired cache entries
DELETE FROM cache_entries
WHERE expires_at < strftime('%s', 'now');
```

### Cleanup Old Tasks

```sql
-- Remove completed tasks older than 24 hours
DELETE FROM cache_tasks
WHERE status = 'completed'
  AND completed_at < strftime('%s', 'now') - 86400;
```

### Vacuum Database

```sql
-- Reclaim space after deletions (run periodically)
VACUUM;
```

### Analyze for Query Optimization

```sql
-- Update table statistics for query planner
ANALYZE;
```

---

**Document Version**: 2.0
**Last Updated**: 2025-10-14
**Status**: Production-Ready Schema
