# Encryption & Security

## Overview

All cached data is encrypted at rest using SQLCipher with AES-256-CBC encryption. Encryption keys are automatically managed via OS-native keyrings with environment variable fallback for headless servers.

## Encryption Specifications

### Cipher Configuration

- **Algorithm**: AES-256-CBC (FIPS-compliant)
- **Key Derivation**: PBKDF2-HMAC-SHA512
- **KDF Iterations**: 256,000 (resistance to brute-force)
- **Page Size**: 4096 bytes
- **HMAC**: SHA512 for authentication and integrity
- **Implementation**: SQLCipher 4.x

### SQLCipher Settings

```sql
PRAGMA key = '<encryption_key>';
PRAGMA cipher_page_size = 4096;
PRAGMA kdf_iter = 256000;
PRAGMA cipher_hmac_algorithm = HMAC_SHA512;
PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512;
```

## Key Management

### EncryptionKeyManager Class

**Location**: `src/m365_mcp/encryption.py`

```python
import os
import secrets
import base64
import logging

logger = logging.getLogger(__name__)

class EncryptionKeyManager:
    """Manage encryption keys with system keyring integration."""

    KEYRING_SERVICE = "m365-mcp-cache"
    KEYRING_USERNAME = "encryption-key"
    ENV_VAR = "M365_MCP_CACHE_KEY"

    @staticmethod
    def generate_key() -> str:
        """Generate cryptographically secure 256-bit key."""
        key_bytes = secrets.token_bytes(32)  # 256 bits
        return base64.b64encode(key_bytes).decode('utf-8')

    @staticmethod
    def get_or_create_key() -> str:
        """
        Get encryption key with priority order:
        1. System keyring
        2. Environment variable
        3. Generate new (and store in keyring)
        """
        # Try system keyring
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

        # Generate new key
        logger.info("Generating new encryption key")
        key = EncryptionKeyManager.generate_key()

        # Try to store in keyring
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
                f"Set {EncryptionKeyManager.ENV_VAR} to persist key."
            )

        return key
```

### Platform Support

| Platform | Keyring Backend | Status |
|----------|----------------|--------|
| Linux | Secret Service API (GNOME Keyring, KWallet) | ✅ Supported |
| macOS | Keychain Services | ✅ Supported |
| Windows | Credential Manager (DPAPI) | ✅ Supported |
| Headless | Environment variable (M365_MCP_CACHE_KEY) | ✅ Supported |

## Migration Strategy

### Automatic Migration

**Location**: `src/m365_mcp/cache_migration.py`

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
    """Migrate unencrypted cache to encrypted format."""
    try:
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

        logger.info(f"Cache migrated successfully. Backup: {backup_path}")
        return True

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return False
```

## Security Best Practices

### Key Management Guidelines

**DO**:
- ✅ Use system keyring when available
- ✅ Generate cryptographically secure keys
- ✅ Use 256-bit keys minimum
- ✅ Log encryption status (not keys!)
- ✅ Provide clear error messages

**DON'T**:
- ❌ Store keys in code or config files
- ❌ Log or print encryption keys
- ❌ Use weak keys (passwords, predictable values)
- ❌ Share keys across systems
- ❌ Include keys in version control

### Secure Coding

```python
# ❌ BAD - Logs encryption key
logger.info(f"Using encryption key: {encryption_key}")

# ✅ GOOD - Logs key source only
logger.info("Encryption key loaded from system keyring")

# ❌ BAD - Exposes key in error
raise ValueError(f"Invalid key: {encryption_key}")

# ✅ GOOD - Generic error
raise ValueError("Encryption key validation failed")
```

## Compliance

### GDPR Article 32 - Security of Processing

- ✅ Encryption at rest (AES-256)
- ✅ Secure key management (OS keyring)
- ✅ Data minimization (TTL-based expiration)
- ✅ Audit logging (cache invalidation tracking)

### HIPAA Technical Safeguards

- ✅ Encryption (164.312(a)(2)(iv))
- ✅ Access controls (OS-level keyring)
- ✅ Audit controls (cache statistics)
- ✅ Integrity controls (SQLCipher HMAC)

### SOC 2 CC6.7 - Encryption at Rest

- ✅ AES-256 encryption for all cached data
- ✅ Automated key management
- ✅ Encryption key rotation support
- ✅ Comprehensive audit logging

## Troubleshooting

### Problem: "File is not a database" error

**Cause**: Encryption key mismatch or corrupted database

**Solution**:
```bash
# Option 1: Reset cache (loses data)
rm ~/.m365_mcp_cache.db

# Option 2: Recover with backup key
export M365_MCP_CACHE_KEY="backup-key-here"
uv run m365-mcp

# Option 3: Restore from backup
cp ~/.m365_mcp_cache.db.backup ~/.m365_mcp_cache.db
```

### Problem: Keyring not available (headless server)

**Solution**:
```bash
# Generate encryption key
python -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"

# Save to environment
export M365_MCP_CACHE_KEY="<generated-key>"

# Add to service or profile
echo 'export M365_MCP_CACHE_KEY="..."' >> ~/.profile
```

---

**Document Version**: 2.0
**Last Updated**: 2025-10-14
**Status**: Production-Ready Security
