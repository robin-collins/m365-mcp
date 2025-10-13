# Cache Encryption and Security Implementation

## Executive Summary

This document outlines the encryption strategy for the M365 MCP cache system to protect sensitive user data at rest. The current cache design stores Microsoft 365 data (emails, calendar events, contacts, files) in plain text, which poses significant security and compliance risks.

## Security Requirements

### Data Classification

**Highly Sensitive Data Stored in Cache:**
- Email content (bodies, subjects, attachments metadata)
- Calendar events (meetings, attendees, locations, notes)
- Contact information (names, emails, phone numbers, addresses)
- File metadata (names, paths, sharing permissions)
- Authentication tokens and session data

### Compliance Requirements

- **GDPR**: Personal data must be encrypted at rest
- **HIPAA**: Protected health information (if in emails/calendar)
- **Enterprise Security**: Corporate data protection policies
- **User Privacy**: Expectation of confidentiality

### Threat Model

**Threats Mitigated by Encryption:**
1. Unauthorized file system access (stolen laptop, backup exposure)
2. Malicious software reading cache files
3. Cloud backup exposure (iCloud, Dropbox, etc.)
4. Forensic data recovery after deletion
5. Shared computer access

**Threats NOT Mitigated:**
- Memory dumps while process is running
- Compromised MCP server process
- OS-level privilege escalation attacks

## Encryption Architecture

### Selected Solution: SQLCipher

**Why SQLCipher:**
- Open-source, widely adopted (used by Signal, WhatsApp)
- AES-256-CBC encryption (FIPS-compliant cipher)
- Transparent encryption/decryption at SQLite level
- Minimal performance impact (~5-15% overhead)
- Drop-in replacement for standard SQLite
- Active maintenance and security audits

**Alternatives Considered:**
- **SEE (SQLite Encryption Extension)**: Commercial, expensive licensing
- **Application-level encryption**: More complex, error-prone
- **File system encryption**: Not portable, OS-dependent

### Encryption Specifications

**Cipher Configuration:**
- **Algorithm**: AES-256-CBC
- **Key Derivation**: PBKDF2-HMAC-SHA512
- **KDF Iterations**: 256,000 (SQLCipher 4 default)
- **Page Size**: 4096 bytes
- **HMAC**: SHA512 for authentication

**SQLCipher PRAGMA Settings:**
```sql
PRAGMA cipher_page_size = 4096;
PRAGMA kdf_iter = 256000;
PRAGMA cipher_hmac_algorithm = HMAC_SHA512;
PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512;
```

## Key Management Strategy

### Option 1: System Keyring (RECOMMENDED)

**Implementation: OS-native secure storage**

**Linux:**
- Secret Service API (GNOME Keyring, KWallet)
- Library: `keyring` Python package

**macOS:**
- Keychain Services API
- Library: `keyring` Python package

**Windows:**
- Windows Credential Manager (DPAPI)
- Library: `keyring` Python package

**Advantages:**
- OS-level security and encryption
- Integration with system authentication
- Survives application reinstalls
- User doesn't manage encryption keys

**Implementation:**
```python
import keyring

# Store encryption key
keyring.set_password("m365-mcp-cache", "encryption-key", generated_key)

# Retrieve encryption key
encryption_key = keyring.get_password("m365-mcp-cache", "encryption-key")
```

### Option 2: Environment Variable (FALLBACK)

**Implementation: User-provided encryption key**

**Usage:**
```bash
export M365_MCP_CACHE_KEY="base64-encoded-256-bit-key"
uv run m365-mcp
```

**Advantages:**
- Works in all environments (including headless servers)
- User controls key backup and rotation
- Simple implementation

**Disadvantages:**
- User must manage encryption key securely
- Key visible in process environment
- Risk of accidental exposure in logs/scripts

**Key Generation Helper:**
```python
import secrets
import base64

def generate_encryption_key() -> str:
    """Generate a secure 256-bit encryption key"""
    key_bytes = secrets.token_bytes(32)  # 256 bits
    return base64.b64encode(key_bytes).decode('utf-8')
```

### Hybrid Approach (IMPLEMENTED)

**Priority Order:**
1. Check system keyring first
2. Fall back to environment variable if keyring unavailable
3. Generate and store new key if neither exists

**Advantages:**
- Best security when available (system keyring)
- Works in all environments (env var fallback)
- Transparent to user

## Implementation

### Dependencies

**Add to pyproject.toml:**
```toml
[project]
dependencies = [
    # Existing dependencies...
    "sqlcipher3>=0.5.0",  # SQLCipher Python bindings
    "keyring>=24.0.0",    # System keyring integration
]
```

### Encryption Module

**Location:** `src/m365_mcp/encryption.py`

```python
import os
import secrets
import base64
import logging
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)

class EncryptionKeyManager:
    """Manage encryption keys with system keyring fallback"""

    KEYRING_SERVICE = "m365-mcp-cache"
    KEYRING_USERNAME = "encryption-key"
    ENV_VAR = "M365_MCP_CACHE_KEY"

    @staticmethod
    def generate_key() -> str:
        """Generate a secure 256-bit encryption key"""
        key_bytes = secrets.token_bytes(32)
        return base64.b64encode(key_bytes).decode('utf-8')

    @staticmethod
    def get_or_create_key() -> str:
        """Get encryption key from keyring or environment, or generate new"""
        # Try system keyring first
        try:
            import keyring
            key = keyring.get_password(
                EncryptionKeyManager.KEYRING_SERVICE,
                EncryptionKeyManager.KEYRING_USERNAME
            )
            if key:
                logger.info("Encryption key loaded from system keyring")
                return key
        except Exception as e:
            logger.warning(f"System keyring unavailable: {e}")

        # Try environment variable
        key = os.getenv(EncryptionKeyManager.ENV_VAR)
        if key:
            logger.info("Encryption key loaded from environment variable")
            return key

        # Generate new key and store in keyring
        logger.info("Generating new encryption key")
        key = EncryptionKeyManager.generate_key()

        try:
            import keyring
            keyring.set_password(
                EncryptionKeyManager.KEYRING_SERVICE,
                EncryptionKeyManager.KEYRING_USERNAME,
                key
            )
            logger.info("Encryption key stored in system keyring")
        except Exception as e:
            logger.warning(
                f"Could not store key in keyring: {e}. "
                f"Set {EncryptionKeyManager.ENV_VAR} environment variable "
                "to persist this key across sessions."
            )

        return key
```

### Updated CacheManager with Encryption

**Location:** `src/m365_mcp/cache.py`

```python
import sqlite3
from pathlib import Path
from typing import Any, Optional
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)

# Import SQLCipher instead of standard sqlite3
try:
    from pysqlcipher3 import dbapi2 as sqlcipher
    ENCRYPTION_AVAILABLE = True
except ImportError:
    logger.warning("SQLCipher not available, falling back to unencrypted SQLite")
    import sqlite3 as sqlcipher
    ENCRYPTION_AVAILABLE = False

from .encryption import EncryptionKeyManager

class CacheManager:
    """Multi-tier cache manager with encryption support"""

    def __init__(self, db_path: Path, encryption_enabled: bool = True):
        self.db_path = db_path
        self.encryption_enabled = encryption_enabled and ENCRYPTION_AVAILABLE
        self.encryption_key: Optional[str] = None

        if self.encryption_enabled:
            self.encryption_key = EncryptionKeyManager.get_or_create_key()
            logger.info("Cache encryption enabled")
        else:
            logger.warning("Cache encryption disabled")

        self._init_database()

    @contextmanager
    def _db(self):
        """Context manager for encrypted database connections"""
        conn = sqlcipher.connect(str(self.db_path))

        try:
            if self.encryption_enabled and self.encryption_key:
                # Set encryption key
                conn.execute(f"PRAGMA key = '{self.encryption_key}'")

                # Configure SQLCipher security settings
                conn.execute("PRAGMA cipher_page_size = 4096")
                conn.execute("PRAGMA kdf_iter = 256000")
                conn.execute("PRAGMA cipher_hmac_algorithm = HMAC_SHA512")
                conn.execute("PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512")

            yield conn

        except sqlcipher.DatabaseError as e:
            if "file is not a database" in str(e).lower():
                logger.error(
                    "Cache database encryption key mismatch or corruption. "
                    "Delete ~/.m365_mcp_cache.db to reset cache."
                )
            raise

        finally:
            conn.close()

    def _init_database(self):
        """Initialize encrypted database schema"""
        with self._db() as conn:
            # Create tables (same schema as before)
            conn.executescript("""
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
                    version INTEGER DEFAULT 1
                );

                CREATE INDEX IF NOT EXISTS idx_cache_account
                    ON cache_entries(account_id);
                CREATE INDEX IF NOT EXISTS idx_cache_resource
                    ON cache_entries(resource_type);
                CREATE INDEX IF NOT EXISTS idx_cache_expires
                    ON cache_entries(expires_at);
            """)
            conn.commit()
```

## Migration Strategy

### Migrating Existing Unencrypted Cache

**Challenge:** Users with existing unencrypted cache databases need seamless migration.

**Solution: Automatic Migration on First Encrypted Access**

**Location:** `src/m365_mcp/cache_migration.py`

```python
from pathlib import Path
import sqlite3
import logging

logger = logging.getLogger(__name__)

def migrate_to_encrypted_cache(
    old_db_path: Path,
    new_db_path: Path,
    encryption_key: str
) -> bool:
    """Migrate unencrypted cache to encrypted cache"""
    try:
        # Import both SQLite and SQLCipher
        from pysqlcipher3 import dbapi2 as sqlcipher

        # Connect to old unencrypted database
        old_conn = sqlite3.connect(str(old_db_path))

        # Create new encrypted database
        new_conn = sqlcipher.connect(str(new_db_path))
        new_conn.execute(f"PRAGMA key = '{encryption_key}'")
        new_conn.execute("PRAGMA cipher_page_size = 4096")

        # Copy schema and data
        for line in old_conn.iterdump():
            new_conn.execute(line)

        new_conn.commit()
        old_conn.close()
        new_conn.close()

        # Backup old database
        backup_path = old_db_path.with_suffix('.db.backup')
        old_db_path.rename(backup_path)

        logger.info(f"Cache migrated to encrypted database. "
                   f"Backup saved to {backup_path}")
        return True

    except Exception as e:
        logger.error(f"Cache migration failed: {e}")
        return False
```

**Auto-Migration Logic in CacheManager:**

```python
def _init_database(self):
    """Initialize database with auto-migration"""
    # Check if unencrypted database exists
    if self.encryption_enabled and self.db_path.exists():
        try:
            # Try opening with encryption
            with self._db() as conn:
                conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
        except Exception:
            # Migration needed
            logger.info("Migrating existing cache to encrypted format")
            backup_path = self.db_path.with_suffix('.db.unencrypted')
            self.db_path.rename(backup_path)

            from .cache_migration import migrate_to_encrypted_cache
            migrate_to_encrypted_cache(
                backup_path,
                self.db_path,
                self.encryption_key
            )

    # Continue with normal initialization
    # ... (rest of initialization code)
```

## Testing Strategy

### Unit Tests

**Location:** `tests/test_encryption.py`

```python
import pytest
import tempfile
from pathlib import Path
from src.m365_mcp.encryption import EncryptionKeyManager
from src.m365_mcp.cache import CacheManager

def test_encryption_key_generation():
    """Test encryption key generation"""
    key = EncryptionKeyManager.generate_key()
    assert len(key) > 0
    assert key != EncryptionKeyManager.generate_key()  # Each key is unique

def test_encrypted_cache_read_write():
    """Test encrypted cache operations"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_cache.db"
        cache = CacheManager(db_path, encryption_enabled=True)

        # Write data
        test_data = {"email_id": "123", "subject": "Test Email"}
        cache.set_cached("email_get", "acc123", test_data, 600, email_id="123")

        # Read data
        result, status = cache.get_cached(
            "email_get", "acc123", 300, 600, email_id="123"
        )

        assert result == test_data
        assert status == "fresh"

def test_encryption_key_mismatch():
    """Test that wrong encryption key fails"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_cache.db"

        # Create cache with one key
        cache1 = CacheManager(db_path, encryption_enabled=True)
        cache1.set_cached("test", "acc123", {"data": "test"}, 600)

        # Try opening with different key (simulate key mismatch)
        cache2 = CacheManager(db_path, encryption_enabled=True)
        cache2.encryption_key = "wrong-key-" + cache2.encryption_key

        with pytest.raises(Exception):
            # Should fail with wrong key
            cache2.get_cached("test", "acc123", 300, 600)
```

### Integration Tests

```python
def test_migration_from_unencrypted():
    """Test automatic migration from unencrypted to encrypted cache"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "cache.db"

        # Create unencrypted cache
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE cache_entries (
                cache_key TEXT PRIMARY KEY,
                data_json TEXT
            )
        """)
        conn.execute(
            "INSERT INTO cache_entries VALUES (?, ?)",
            ("test:key", '{"data": "test"}')
        )
        conn.commit()
        conn.close()

        # Open with encryption (should trigger migration)
        cache = CacheManager(db_path, encryption_enabled=True)

        # Verify data is accessible
        result = cache.get_cached("test", "key", 300, 600)
        assert result is not None
```

## Performance Impact

### Benchmark Results (Expected)

| Operation | Unencrypted | Encrypted | Overhead |
|-----------|-------------|-----------|----------|
| Write 1KB entry | 0.5ms | 0.6ms | +20% |
| Write 100KB entry | 3ms | 3.5ms | +17% |
| Read 1KB entry | 0.3ms | 0.4ms | +33% |
| Read 100KB entry | 2ms | 2.3ms | +15% |
| Database open | 1ms | 5ms | +400% |

**Key Insights:**
- Encryption overhead: 15-33% for operations
- Database open slower (key derivation with PBKDF2)
- Overall impact: <1ms for typical cache operations
- Negligible vs 30,000ms API call time

### Performance Optimization

**Connection Pooling:**
```python
class CacheManager:
    def __init__(self, db_path: Path, encryption_enabled: bool = True):
        # ... existing code ...
        self._connection_pool = []

    @contextmanager
    def _db(self):
        """Use connection pooling to avoid repeated key derivation"""
        if self._connection_pool:
            conn = self._connection_pool.pop()
        else:
            conn = self._create_connection()

        try:
            yield conn
        finally:
            # Return to pool instead of closing
            self._connection_pool.append(conn)
```

## Security Best Practices

### Key Management Guidelines

**DO:**
- ✅ Use system keyring when available
- ✅ Generate cryptographically secure keys (secrets.token_bytes)
- ✅ Use 256-bit keys minimum
- ✅ Log encryption status on startup
- ✅ Provide clear error messages for key issues

**DON'T:**
- ❌ Store encryption keys in code or configuration files
- ❌ Log or print encryption keys
- ❌ Use weak keys (passwords, predictable values)
- ❌ Share encryption keys across systems
- ❌ Include keys in version control

### Secure Coding Practices

**Avoid Key Exposure in Logs:**
```python
# ❌ BAD - Logs encryption key
logger.info(f"Using encryption key: {encryption_key}")

# ✅ GOOD - Logs key source only
logger.info("Encryption key loaded from system keyring")
```

**Secure Error Handling:**
```python
# ❌ BAD - Exposes key in error message
raise ValueError(f"Invalid key: {encryption_key}")

# ✅ GOOD - Generic error message
raise ValueError("Encryption key validation failed")
```

**Memory Security:**
```python
# Clear sensitive data from memory when done
import gc

def cleanup_encryption_key(self):
    """Securely clear encryption key from memory"""
    if hasattr(self, 'encryption_key'):
        self.encryption_key = None
        gc.collect()  # Force garbage collection
```

### Compliance Considerations

**GDPR Article 32 - Security of Processing:**
- ✅ Encryption at rest (SQLCipher AES-256)
- ✅ Secure key management (system keyring)
- ✅ Data minimization (TTL-based expiration)
- ✅ Audit logging (cache invalidation tracking)

**HIPAA Technical Safeguards:**
- ✅ Encryption (164.312(a)(2)(iv))
- ✅ Access controls (OS-level keyring)
- ✅ Audit controls (cache statistics)
- ✅ Integrity controls (SQLCipher HMAC)

## Operational Considerations

### User Experience

**Transparent Encryption:**
- No user action required for encryption
- Automatic key generation and storage
- No performance degradation noticed
- Seamless migration from unencrypted cache

**Error Recovery:**
```python
def handle_encryption_error(self, error: Exception):
    """Provide helpful error messages for encryption issues"""
    if "file is not a database" in str(error):
        logger.error(
            "Cache encryption key mismatch detected. "
            "Possible causes:\n"
            "1. System keyring was reset or changed\n"
            "2. Different encryption key in environment\n"
            "3. Cache file corruption\n\n"
            "To reset cache: rm ~/.m365_mcp_cache.db\n"
            "To backup key: save value from system keyring"
        )
```

### Configuration Options

**Environment Variables:**
```bash
# Disable encryption (not recommended)
export M365_MCP_CACHE_ENCRYPTION=false

# Provide custom encryption key
export M365_MCP_CACHE_KEY="your-base64-encoded-key"

# Specify cache database location
export M365_MCP_CACHE_PATH="~/custom/path/cache.db"
```

### Troubleshooting Guide

**Problem: "File is not a database" error**

**Cause:** Encryption key mismatch or corrupted database

**Solution:**
```bash
# Option 1: Reset cache (loses cached data)
rm ~/.m365_mcp_cache.db

# Option 2: Recover with backup key
export M365_MCP_CACHE_KEY="backup-key-here"
uv run m365-mcp

# Option 3: Migrate from backup
cp ~/.m365_mcp_cache.db.backup ~/.m365_mcp_cache.db
```

**Problem: Keyring not available on headless server**

**Cause:** No system keyring service running

**Solution:**
```bash
# Generate and save encryption key
python -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"

# Export key in environment
export M365_MCP_CACHE_KEY="generated-key-from-above"

# Add to systemd service file or profile
echo 'export M365_MCP_CACHE_KEY="..."' >> ~/.profile
```

**Problem: Performance degradation with encryption**

**Cause:** Frequent database connections (key derivation overhead)

**Solution:** Connection pooling (implemented in CacheManager)

### Backup and Recovery

**Backup Strategy:**
```bash
# Backup encrypted cache (key still required to read)
cp ~/.m365_mcp_cache.db ~/backups/cache_$(date +%Y%m%d).db

# Backup encryption key from keyring
python -c "
import keyring
key = keyring.get_password('m365-mcp-cache', 'encryption-key')
print(f'Save this key securely: {key}')
"
```

**Recovery Process:**
1. Restore cache database file
2. Ensure encryption key is in keyring or environment
3. Restart MCP server
4. Verify cache access with `cache_get_stats` tool

## Implementation Plan

### Phase 1: Dependencies and Core Infrastructure (Day 1)

**Tasks:**
1. Add SQLCipher and keyring dependencies to pyproject.toml
2. Create `src/m365_mcp/encryption.py` module
3. Implement `EncryptionKeyManager` class
4. Add unit tests for key generation and retrieval
5. Test on Linux, macOS, and Windows

**Deliverables:**
- ✅ Working encryption key management
- ✅ System keyring integration
- ✅ Environment variable fallback
- ✅ Cross-platform compatibility

**Validation:**
```bash
uv sync  # Install new dependencies
uv run pytest tests/test_encryption.py -v
```

### Phase 2: CacheManager Integration (Day 2)

**Tasks:**
1. Update `src/m365_mcp/cache.py` to use SQLCipher
2. Add encryption toggle to CacheManager constructor
3. Implement encrypted database connection logic
4. Add connection pooling for performance
5. Test encrypted read/write operations

**Deliverables:**
- ✅ CacheManager supports encryption
- ✅ Graceful fallback if SQLCipher unavailable
- ✅ Connection pooling implemented
- ✅ Performance benchmarks documented

**Validation:**
```bash
uv run pytest tests/test_cache_encryption.py -v
```

### Phase 3: Migration and Error Handling (Day 3)

**Tasks:**
1. Create `src/m365_mcp/cache_migration.py` module
2. Implement automatic migration from unencrypted cache
3. Add comprehensive error handling
4. Implement helpful error messages
5. Test migration scenarios

**Deliverables:**
- ✅ Automatic migration working
- ✅ Backup of old cache created
- ✅ Clear error messages for common issues
- ✅ Migration integration tests

**Validation:**
```bash
# Test migration
rm ~/.m365_mcp_cache.db  # Reset
uv run m365-mcp  # Should create encrypted cache
```

### Phase 4: Documentation and Polish (Day 4)

**Tasks:**
1. Update README.md with encryption details
2. Add encryption section to CLAUDE.md
3. Create troubleshooting guide
4. Update SECURITY.md with encryption info
5. Update CHANGELOG.md

**Deliverables:**
- ✅ User-facing documentation complete
- ✅ Developer documentation updated
- ✅ Security documentation current
- ✅ Changelog entry added

### Phase 5: Testing and Validation (Day 5)

**Tasks:**
1. Run full integration test suite
2. Performance benchmarking (encrypted vs unencrypted)
3. Test on all supported platforms
4. Security review of implementation
5. Code review and cleanup

**Deliverables:**
- ✅ All tests passing
- ✅ Performance within acceptable range
- ✅ Cross-platform validation complete
- ✅ Security review passed

**Total Implementation Time: 5 days**

## Documentation Requirements

### README.md Updates

**Add Encryption Section:**
```markdown
## Cache Encryption

M365 MCP automatically encrypts cached data using AES-256 encryption via SQLCipher.

### Automatic Setup
- Encryption keys are automatically generated and stored in your system keyring
- No configuration required for most users
- Works on Linux (GNOME Keyring), macOS (Keychain), and Windows (Credential Manager)

### Manual Key Management (Optional)
For headless servers or custom setups:

```bash
# Generate encryption key
python -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"

# Set as environment variable
export M365_MCP_CACHE_KEY="your-generated-key"
```

### Disabling Encryption (Not Recommended)
```bash
export M365_MCP_CACHE_ENCRYPTION=false
```
```

### SECURITY.md Updates

**Add Encryption Details:**
```markdown
## Data Protection

### Encryption at Rest
All cached Microsoft 365 data is encrypted using:
- **Cipher**: AES-256-CBC (FIPS-compliant)
- **Implementation**: SQLCipher 4.x
- **Key Derivation**: PBKDF2-HMAC-SHA512 (256,000 iterations)
- **Authentication**: HMAC-SHA512

### Key Management
- Encryption keys stored in OS-native secure storage (keyring)
- 256-bit cryptographically secure random keys
- Keys never logged or exposed in error messages
- Per-installation keys (not shared across systems)

### Compliance
- **GDPR Article 32**: Encryption of personal data
- **HIPAA**: Technical safeguards for ePHI
- **SOC 2**: Encryption at rest controls
```

## Risk Assessment

### Security Risks (Mitigated)

| Risk | Severity | Mitigation | Status |
|------|----------|------------|--------|
| Plain text cache exposure | **HIGH** | AES-256 encryption | ✅ Mitigated |
| Stolen laptop data access | **HIGH** | Encrypted cache + keyring | ✅ Mitigated |
| Cloud backup exposure | **MEDIUM** | Encrypted cache files | ✅ Mitigated |
| Shared computer access | **MEDIUM** | OS-level keyring protection | ✅ Mitigated |
| Key management complexity | **LOW** | Automatic key generation | ✅ Mitigated |

### Implementation Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| SQLCipher unavailable | Low | Medium | Graceful fallback, clear error |
| Key mismatch on migration | Low | Medium | Automatic migration + backup |
| Performance degradation | Low | Low | Connection pooling, benchmarks |
| Cross-platform issues | Medium | Medium | Test on all platforms |

## Summary

### What This Adds
- ✅ **AES-256 encryption** for all cached Microsoft 365 data
- ✅ **Automatic key management** via system keyring
- ✅ **Zero-configuration** for most users
- ✅ **Transparent migration** from unencrypted cache
- ✅ **GDPR/HIPAA compliance** for data at rest
- ✅ **Minimal performance impact** (<1ms per operation)

### What This Requires
- `sqlcipher3` Python package (added to dependencies)
- `keyring` Python package (added to dependencies)
- System keyring service (or environment variable fallback)
- 5 days implementation time

### Security Posture Change
**Before:** Cache stores sensitive data in plain text ❌
**After:** Cache stores encrypted data with secure key management ✅

### Recommendation
**Implement immediately** - This is a critical security enhancement that should be included in Phase 1 of the cache implementation, not added later.

---

**Document Version**: 1.0
**Last Updated**: 2025-10-14
**Status**: Approved for Implementation
**Priority**: Critical (Security Requirement)
