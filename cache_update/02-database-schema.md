# Database Schema

## SQLite Database: `~/.m365_mcp_cache.db`

**Encryption**: This database uses SQLCipher for AES-256 encryption. All data is encrypted at rest with automatic key management via system keyring. See [09-encryption-security.md](./09-encryption-security.md) for details.

### Table: cache_entries

Stores cached data with TTL management.

```sql
CREATE TABLE cache_entries (
    cache_key TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,  -- 'folder_tree', 'email_list', etc.
    data_blob BLOB NOT NULL,       -- JSON or compressed data
    is_compressed INTEGER DEFAULT 0,  -- 0=uncompressed, 1=gzip compressed
    metadata_json TEXT,            -- Query params, item count, etc.
    size_bytes INTEGER NOT NULL,   -- Size of data_blob in bytes
    uncompressed_size INTEGER,     -- Original size if compressed
    created_at REAL NOT NULL,      -- Unix timestamp
    accessed_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    hit_count INTEGER DEFAULT 0,
    version INTEGER DEFAULT 1
);

CREATE INDEX idx_cache_account ON cache_entries(account_id);
CREATE INDEX idx_cache_resource ON cache_entries(resource_type);
CREATE INDEX idx_cache_expires ON cache_entries(expires_at);
CREATE INDEX idx_cache_accessed ON cache_entries(accessed_at);
```

### Table: cache_tasks

Background task queue for async operations.

```sql
CREATE TABLE cache_tasks (
    task_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    task_type TEXT NOT NULL,
    operation TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    cache_key TEXT,
    status TEXT NOT NULL,          -- 'queued', 'running', 'completed', 'failed'
    priority INTEGER DEFAULT 5,    -- 1=highest, 10=lowest
    result_json TEXT,
    error_text TEXT,
    progress_pct INTEGER DEFAULT 0,
    created_at REAL NOT NULL,
    started_at REAL,
    completed_at REAL,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3
);

CREATE INDEX idx_tasks_status ON cache_tasks(status, priority);
CREATE INDEX idx_tasks_account ON cache_tasks(account_id);
CREATE INDEX idx_tasks_created ON cache_tasks(created_at);
```

### Table: cache_invalidation

Tracks cache invalidation events for debugging.

```sql
CREATE TABLE cache_invalidation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    pattern TEXT NOT NULL,
    reason TEXT,
    invalidated_at REAL NOT NULL,
    invalidated_count INTEGER DEFAULT 0
);

CREATE INDEX idx_invalidation_account ON cache_invalidation(account_id, resource_type);
```

### Table: cache_stats

Performance metrics for monitoring.

```sql
CREATE TABLE cache_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    resource_type TEXT NOT NULL,
    hit_count INTEGER DEFAULT 0,
    miss_count INTEGER DEFAULT 0,
    eviction_count INTEGER DEFAULT 0,
    avg_response_time_ms REAL
);
```

## Migration Script

Location: `src/m365_mcp/migrations/001_init_cache.sql`

```sql
-- All CREATE TABLE and CREATE INDEX statements above
-- Plus initial configuration:

INSERT INTO cache_stats (timestamp, resource_type, hit_count, miss_count)
VALUES (strftime('%s', 'now'), 'system', 0, 0);
```
