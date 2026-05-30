# M365 MCP Cache Security Guide

**Version**: 1.1
**Last Updated**: 2026-05-30
**Security Posture**: Encrypted by default with fail-fast SQLCipher checks

## Table of Contents

1. [Overview](#overview)
2. [Encryption Details](#encryption-details)
3. [Key Management](#key-management)
4. [Compliance](#compliance)
5. [Security Best Practices](#security-best-practices)
6. [Threat Model](#threat-model)
7. [Backup and Recovery](#backup-and-recovery)

---

## Overview

The M365 MCP cache implements encrypted local storage by default:

- **AES-256 Encryption**: Cached data is encrypted at rest via SQLCipher by default
- **Secure Key Storage**: System keyring integration (macOS Keychain, Windows Credential Manager, Linux Secret Service)
- **Fail-Fast Runtime**: Encryption-enabled startup fails if SQLCipher is unavailable
- **Regulated Deployment Support**: Encryption, TTL, and account isolation controls for GDPR/HIPAA-aligned deployments
- **Explicit Plaintext Mode**: Plaintext cache files are written only when encryption is explicitly disabled by code

### Security Guarantees

- Cache data encrypted at rest by default (AES-256 via SQLCipher)
- Encryption keys loaded from system keyring when available
- No keys logged or exposed in errors
- Account isolation for cache entries and invalidation
- Automatic key generation
- Environment variable fallback for headless servers
- Warning when generated keys cannot be persisted and are therefore ephemeral

---

## Encryption Details

### Algorithm: AES-256-CBC

**Implementation**: SQLCipher with `cipher_compatibility = 4`

- **Encryption**: AES-256 in CBC mode
- **Key Derivation**: PBKDF2 with 256,000 iterations
- **Page Size**: 4096 bytes
- **HMAC**: SHA-512

### What Gets Encrypted

**Encrypted**:
- All cache entry data
- All cache metadata
- Database schema

**Not Encrypted** (by design):
- Temporary files in memory
- Application logs (keys never logged)

### Encryption Overhead

- **Performance Impact**: <1ms per operation
- **Storage Overhead**: ~5% (minimal)
- **CPU Impact**: Negligible on modern hardware

---

## Key Management

### Automatic Key Generation

On first use, M365 MCP automatically:

1. Generates a 256-bit (32-byte) encryption key
2. Base64-encodes the key for storage
3. Stores in system keyring
4. Uses key for all cache operations

**No user action required!**

### Key Storage Hierarchy

1. **System Keyring** (preferred):
   - macOS: Keychain
   - Windows: Credential Manager
   - Linux: Secret Service (GNOME Keyring, KWallet, etc.)

2. **Environment Variable** (fallback):
   - `M365_MCP_CACHE_KEY` - base64-encoded 256-bit key

3. **Generation** (last resort):
   - Auto-generate if no key found
   - Store in keyring if possible
   - Log a warning if the generated key is ephemeral because neither keyring nor `M365_MCP_CACHE_KEY` provides durable storage

### System Keyring Integration

#### macOS Keychain

```bash
# View stored key (requires password)
security find-generic-password -s "m365-mcp-cache" -a "encryption-key" -w

# Delete key
security delete-generic-password -s "m365-mcp-cache" -a "encryption-key"
```

#### Windows Credential Manager

```powershell
# View stored credentials
cmdkey /list | findstr m365-mcp-cache

# Delete key
cmdkey /delete:m365-mcp-cache
```

#### Linux Secret Service

```bash
# View keys (using secret-tool)
secret-tool search service m365-mcp-cache username encryption-key

# Delete key
secret-tool clear service m365-mcp-cache username encryption-key
```

### Headless Server Setup

For servers without keyring (Docker, systemd services):

```bash
# Generate secure key
export M365_MCP_CACHE_KEY=$(openssl rand -base64 32)

# Add to service configuration
echo "M365_MCP_CACHE_KEY=$M365_MCP_CACHE_KEY" >> /etc/m365-mcp/env

# Or use systemd environment file
echo "M365_MCP_CACHE_KEY=$M365_MCP_CACHE_KEY" > /etc/systemd/system/m365-mcp.env
```

### Key Rotation

**Current**: Keys are persistent (no rotation)

**Future Enhancement**: Key rotation planned for v2.0

**Workaround** (if key rotation needed):
```bash
# 1. Export old cache (not yet implemented)
# 2. Delete old cache
rm ~/.m365_mcp_cache.db

# 3. Generate new key
unset M365_MCP_CACHE_KEY  # Force regeneration

# 4. Restart server (new key auto-generated)
uv run m365-mcp
```

### SQLCipher Availability

`sqlcipher3-wheels` is a runtime dependency. When cache encryption is enabled,
M365 MCP raises an import error instead of silently opening a plaintext SQLite
database if SQLCipher cannot be imported. Plaintext cache mode is reserved for
explicit test or diagnostic construction with encryption disabled.

---

## Compliance

### GDPR (General Data Protection Regulation)

#### Article 32: Security of Processing

✅ **Requirement**: "Appropriate technical and organizational measures"

**Implementation**:
- AES-256 encryption at rest
- Secure key management (system keyring)
- Automatic data minimization (TTL expiration)
- Audit logging for cache operations
- Account isolation (multi-tenant)

✅ **Supports compliant deployments when combined with appropriate operational controls**

#### Article 5: Data Minimization

✅ **Requirement**: "Adequate, relevant, and limited to what is necessary"

**Implementation**:
- Fresh TTL: 5 minutes
- Stale TTL: 30 minutes
- Expired: Automatic deletion
- Maximum cache size: 2GB
- Automatic cleanup at 80% threshold

✅ **Supports compliant deployments when combined with appropriate operational controls**

#### Article 17: Right to Erasure

✅ **Requirement**: Ability to delete personal data

**Implementation**:
```python
# Delete all cache for account
cache_invalidate("*", account_id="account-123")

# Or delete entire cache database
rm ~/.m365_mcp_cache.db
```

✅ **Supports compliant deployments when combined with appropriate operational controls**

### HIPAA (Health Insurance Portability and Accountability Act)

#### §164.312(a)(2)(iv): Encryption and Decryption

✅ **Requirement**: "Implement a mechanism to encrypt electronic protected health information"

**Implementation**:
- AES-256 encryption for cached data
- SQLCipher with modern encryption primitives
- Secure key storage (system keyring)

✅ **Supports compliant deployments when combined with appropriate operational controls**

#### §164.312(a)(1): Access Control

✅ **Requirement**: "Implement technical policies and procedures"

**Implementation**:
- Account-based isolation
- System-level access controls (file permissions)
- Encryption key access control

✅ **Supports compliant deployments when combined with appropriate operational controls**

#### §164.312(b): Audit Controls

✅ **Requirement**: "Hardware, software, and/or procedural mechanisms to record and examine activity"

**Implementation**:
- Structured JSON logging
- Cache operation tracking
- Invalidation audit trail

✅ **Supports compliant deployments when combined with appropriate operational controls**

#### §164.312(c)(1): Integrity

✅ **Requirement**: "Policies to protect electronic PHI from improper alteration or destruction"

**Implementation**:
- WAL (Write-Ahead Logging) mode
- Atomic database operations
- TTL-based expiration (controlled deletion)

✅ **Supports compliant deployments when combined with appropriate operational controls**

### SOC 2 Type II

**Common Criteria**:
- CC6.1: Logical access controls ✅
- CC6.6: Encryption ✅
- CC6.7: Key management ✅

**Availability**:
- A1.2: Environmental protections ✅ (automatic cleanup)

### ISO 27001

**A.10: Cryptography**:
- A.10.1.1: Policy on cryptographic controls ✅
- A.10.1.2: Key management ✅

**A.12: Operations Security**:
- A.12.3.1: Information backup ✅ (user-managed)

---

## Security Best Practices

### 1. Use System Keyring (Preferred)

✅ **DO**: Let M365 MCP use system keyring automatically

❌ **DON'T**: Override with environment variable unnecessarily

### 2. Protect Environment Variables

✅ **DO**: Use secure environment management
```bash
# Good: Use systemd environment files
EnvironmentFile=/etc/m365-mcp/secure.env

# Good: Use Docker secrets
docker secret create m365_cache_key - < key.txt
```

❌ **DON'T**: Put keys in shell history or scripts
```bash
# Bad: Exposes key in process list
export M365_MCP_CACHE_KEY=dGVzdGtleQ==
```

### 3. File Permissions

✅ **DO**: Restrict cache database permissions
```bash
chmod 600 ~/.m365_mcp_cache.db
```

### 4. Key Backup

✅ **DO**: Back up encryption key securely
```bash
# Export key from keyring
security find-generic-password -s "m365-mcp-cache" -a "encryption-key" -w > key.backup

# Store securely (password manager, vault, etc.)
# chmod 400 key.backup
```

### 5. Regular Security Audits

✅ **DO**: Periodically review:
- Cache size and cleanup
- Encryption key access
- System keyring integration
- Log files for anomalies

### 6. Network Security

✅ **DO**: Use stdio mode for local deployments (inherently secure)

⚠️ **CAUTION**: HTTP mode requires additional security:
- Use bearer token authentication
- Deploy behind reverse proxy (nginx, Apache)
- Enable TLS/SSL
- Restrict network access

### 7. Incident Response

If encryption key is compromised:

1. Delete cache database: `rm ~/.m365_mcp_cache.db`
2. Delete encryption key from keyring
3. Restart server (generates new key)
4. Review access logs
5. Consider rotating Microsoft Graph tokens

---

## Threat Model

### Threats Mitigated

✅ **Data at Rest Theft**:
- **Threat**: Attacker copies cache database file
- **Mitigation**: AES-256 encryption, useless without key

✅ **Key Extraction**:
- **Threat**: Attacker attempts to extract encryption key
- **Mitigation**: System keyring with OS-level protection

✅ **Multi-Tenant Data Leakage**:
- **Threat**: One account accesses another account's cache
- **Mitigation**: Account-based cache isolation

✅ **Stale Data Exposure**:
- **Threat**: Sensitive data remains cached indefinitely
- **Mitigation**: TTL-based expiration (5-30 minutes)

### Threats Not Addressed

❌ **Memory Dump Attacks**:
- **Threat**: Attacker with root access dumps process memory
- **Mitigation**: None (requires OS-level protection)
- **Note**: Decrypted data exists in memory during processing

❌ **Malicious Code Injection**:
- **Threat**: Attacker modifies M365 MCP code
- **Mitigation**: Code signing, file integrity monitoring (user responsibility)

❌ **Keylogger/Screen Capture**:
- **Threat**: Attacker captures user input/output
- **Mitigation**: Endpoint security (user responsibility)

### Security Assumptions

The security model assumes:

1. **Trusted Runtime**: Python runtime and dependencies are trusted
2. **OS Security**: Operating system keyring is secure
3. **File System Security**: Cache database file permissions enforced
4. **No Root Compromise**: Attacker does not have root/admin access

---

## Backup and Recovery

### Backup Strategy

**What to Back Up**:
1. Encryption key (from keyring)
2. Cache database file (optional)

**What NOT to Back Up**:
- Temporary files
- Log files with sensitive data

### Backup Encryption Key

```bash
# macOS: Export from Keychain
security find-generic-password -s "m365-mcp-cache" -a "encryption-key" -w > key.backup

# Store securely (password manager, encrypted vault, etc.)
chmod 400 key.backup
```

### Recovery Procedures

#### Scenario 1: Lost Encryption Key

**Impact**: Cannot decrypt existing cache

**Recovery**:
```bash
# Delete old cache (data lost but encrypted)
rm ~/.m365_mcp_cache.db

# Restart server (generates new key, rebuilds cache)
uv run m365-mcp
```

#### Scenario 2: Corrupted Cache Database

**Impact**: Cache operations fail

**Recovery**:
```bash
# Delete corrupted database
rm ~/.m365_mcp_cache.db

# Restart server (rebuilds cache)
uv run m365-mcp
```

#### Scenario 3: System Migration

**Goal**: Preserve cache on new system

**Steps**:
```bash
# Old system: Export key
security find-generic-password -s "m365-mcp-cache" -a "encryption-key" -w > key.backup

# Old system: Copy cache database
cp ~/.m365_mcp_cache.db /backup/

# New system: Import key
export M365_MCP_CACHE_KEY=$(cat key.backup)

# New system: Restore cache
cp /backup/.m365_mcp_cache.db ~/.m365_mcp_cache.db

# New system: Start server
uv run m365-mcp
```

---

## Summary

- **Enterprise-Grade Encryption**: AES-256 via SQLCipher
- **Secure Key Management**: System keyring integration
- **GDPR/HIPAA Alignment**: Provides encryption, TTL, and isolation controls that support regulated deployments
- **Encrypted By Default**: Plaintext cache files require explicit encryption disablement
- **Automatic Security**: Works out-of-the-box
- **Recovery Options**: Clear backup and recovery procedures

**Security Contact**: For security issues, see `SECURITY.md` in the repository root.

---

**Document Version**: 1.1
**Last Updated**: 2026-05-30
**Security Audit**: See `docs/analysis_results.md`
**Next Review**: Quarterly or after security incidents
