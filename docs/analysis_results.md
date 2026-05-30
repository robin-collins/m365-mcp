# Codebase Analysis Report: M365 MCP Server

An in-depth technical analysis of the M365 MCP Server codebase was conducted. The
original report's findings were independently re-verified against the current
`src/` tree (commit `3ec38f0`), with each claim either **confirmed**, **partially
confirmed (mechanism corrected)**, or **refuted** with supporting evidence. New
findings discovered during verification are listed in a dedicated section.

> **Verification environment:** Windows 11, CPython 3.12 (`requires-python
> >=3.11`). Import-precedence and `pathlib` behaviours below were tested
> empirically on this interpreter.

---

## Verification Summary

| # | Original Finding | Status | Notes |
| :-- | :--- | :--- | :--- |
| 1 | Zero registered tools on startup | ❌ **REFUTED** | Package `tools/` shadows module `tools.py`; `from .tools import mcp` loads the package `__init__.py`, which **does** import every submodule. Tools register correctly. |
| 2 | Broken ADS path validation on Windows | ✅ **CONFIRMED (Critical)** | `parts[0]` is `'C:\\'`, `drive` is `'C:'` → every absolute Windows path raises. Breaks all local file I/O. |
| 3 | Missing `tzdata` dependency | ✅ **CONFIRMED (High)** | Not in `pyproject.toml`; `zoneinfo` is used and has no embedded DB on Windows. |
| 4 | Ephemeral key crash on restart | ⚠️ **CONFIRMED, mechanism corrected** | Real crash is in `cache.py::_init_database` (executescript with wrong key), **not** `detect_and_migrate` (which is dead code, never called). Only triggers when keyring is unavailable **and** env key unset. |
| 5 | Missing `check_same_thread=False` | ✅ **CONFIRMED (High)** | Plus the connection pool list itself has no lock — also thread-unsafe. |
| 6 | Background worker TOCTOU | ✅ **CONFIRMED (latent)** | Real, but currently only one logical consumer and the worker is never started (see N2). Becomes live as soon as concurrency is enabled. |
| 7 | Deceptive plaintext fallback | ✅ **CONFIRMED (High)** | No `USING_SQLCIPHER` guard; logs "encryption enabled" unconditionally. Mitigated in practice by the pinned `sqlcipher3-wheels` dep, but the defensive fix is still warranted. |
| 8 | Connection pool resource leak | ✅ **CONFIRMED (Medium)** | No `close()` method exists on `CacheManager`. |
| 9 | Hanging device-flow auth (headless) | ✅ **CONFIRMED (Medium)** | `auth.py:248` blocks until the flow expires (~15 min), not literally forever, then errors. Still unacceptable inside an MCP request. |
| 10 | Windows case-sensitive `relative_to` | ❌ **REFUTED** | `PureWindowsPath.relative_to` is case-insensitive on 3.11/3.12 (tested); `resolve()` also normalises drive case. Not a bug. |
| 11 | `tools.py` vs `tools/` namespace collision | ✅ **CONFIRMED (Low)** | This is the *real* issue behind Finding 1: `tools.py` is dead, shadowed code. |
| 12 | Windows test-teardown `PermissionError` | ➖ **PLAUSIBLE (not re-verified)** | Pattern is consistent with a real Windows file-lock issue; not re-run in this pass. |

**New findings (this pass):** N1–N8 below.

---

## Corrections to the Original Report

### Finding 1 — REFUTED: Tools *do* register

The original report concluded the server exposes zero tools because `tools.py`
never imports the submodules. This is incorrect. Two files coexist:
`src/m365_mcp/tools.py` and the package `src/m365_mcp/tools/`. When a module and a
package share a name in the same directory, **Python's `FileFinder` resolves the
package first**. Verified empirically:

```text
# pkg/tools.py        -> mcp = "FROM_MODULE_tools_py"
# pkg/tools/__init__.py -> mcp = "FROM_PACKAGE_tools_init"
>>> from pkg.tools import mcp
RESOLVED: FROM_PACKAGE_tools_init
```

`server.py:90` does `from .tools import mcp`, which therefore loads
[tools/__init__.py](src/m365_mcp/tools/__init__.py) — and that file imports every
submodule (`account`, `calendar`, `email`, …), triggering all `@mcp.tool`
decorators. **Tools register correctly.**

The genuine problem is that [tools.py](src/m365_mcp/tools.py) is **dead, shadowed
code** that can never execute, while its docstring claims to be "the central
registry." This is the same root cause as Finding 11. **Remediation:** delete
`tools.py` (preferred) or rename the package entry point so the two names no
longer collide.

### Finding 10 — REFUTED: `relative_to` is case-insensitive on Windows

```python
Path("c:\\Users\\tech\\file.txt").relative_to(Path("C:\\Users\\tech"))
# -> WindowsPath('file.txt')   (no ValueError)
```

`_is_subpath` in [validators.py:647](src/m365_mcp/validators.py) is safe as-is on
Python 3.11/3.12. Both operands are produced via `.resolve()`, which canonicalises
drive-letter case anyway. No change required.

---

## Confirmed Findings & Remediation

### 2. Broken Alternate Data Stream Validation on Windows — CONFIRMED (Critical)
* **File:** [validators.py:708](src/m365_mcp/validators.py)
* **Evidence:**
  ```python
  p = Path("C:\\Users\\tech\\file.txt").resolve(strict=False)
  p.parts                  # ('C:\\', 'Users', 'tech', 'file.txt')
  p.drive                  # 'C:'
  p.parts[0] == p.drive    # False  -> the `continue` never fires
  ":" in p.parts[0]        # True   -> raises for EVERY absolute path
  ```
* **Blast radius (all break on Windows):** file download
  [file.py:250](src/m365_mcp/tools/file.py), file upload/create
  [file.py:382](src/m365_mcp/tools/file.py), file update
  [file.py:435](src/m365_mcp/tools/file.py), attachment save
  [email.py:1234](src/m365_mcp/tools/email.py), and outgoing attachments via
  `validate_attachments` -> [validators.py:912](src/m365_mcp/validators.py).
* **Remediation:** skip the drive component explicitly.
  ```python
  if os.name == "nt":
      parts_to_check = resolved.parts[1:] if resolved.drive else resolved.parts
      for part in parts_to_check:
          if ":" in part:
              reason = "alternate data streams are not allowed"
              _log_failure(param_name, reason, candidate_str)
              raise ValidationError(format_validation_error(
                  param_name, candidate_str, reason,
                  "Filenames without ':' segments"))
          upper = part.split(".")[0].upper()
          if upper in WINDOWS_RESERVED_NAMES:
              ...  # unchanged
  ```
* **Test gap:** the suite ([test_validators.py](tests/test_validators.py)) only
  checks traversal and reserved names. Add a test asserting a normal absolute path
  under an allowed root is accepted on Windows so this regression cannot recur.

---

### 3. Missing `tzdata` Dependency — CONFIRMED (High)
* **File:** [pyproject.toml](pyproject.toml) (deps end at line 31)
* **Usage:** [validators.py:14,350](src/m365_mcp/validators.py)
  (`ZoneInfo(...)` in `validate_timezone`) plus calendar tooling.
* **Impact:** On Windows `zoneinfo` ships no database. Without `tzdata`, even
  `ZoneInfo("UTC")` raises `ZoneInfoNotFoundError`, which `validate_timezone`
  surfaces as a `ValidationError` — any timezone-bearing operation fails on a
  stock Windows install.
* **Remediation:**
  ```toml
  dependencies = [
      # ... existing ...
      "tzdata>=2024.1",  # Required for zoneinfo on Windows
  ]
  ```

---

### 4. Mismatched-Key Crash on Restart — CONFIRMED (mechanism corrected)
* **Files:** [encryption.py](src/m365_mcp/encryption.py),
  [cache.py:128](src/m365_mcp/cache.py)
* **Correction:** the crash is **not** in `detect_and_migrate()` — that function
  is never called anywhere in `src/` (dead code, confirmed by grep). The real path
  is:
  1. `get_or_create_key()` generates an **ephemeral** key when keyring is
     unavailable *and* `M365_MCP_CACHE_KEY` is unset
     ([encryption.py:113-127](src/m365_mcp/encryption.py)).
  2. Next start, `_init_database()` opens the existing DB with the new key and runs
     `conn.executescript(migration_sql)` ([cache.py:144](src/m365_mcp/cache.py)).
  3. SQLCipher cannot decrypt -> `DatabaseError: file is not a database`, which
     propagates out of `__init__`.
* **Scope:** on the user's Windows 11 host the Credential Manager keyring is
  normally available, so the key persists and this does not fire. It is a real
  hazard for headless Linux/Docker/CI without a Secret Service backend.
* **Remediation (in `_init_database`):**
  ```python
  try:
      with self._db() as conn:
          conn.executescript(migration_sql)
  except sqlite3.DatabaseError as e:
      msg = str(e).lower()
      if "file is not a database" in msg or "encrypt" in msg:
          logger.warning("Cache key mismatch/corruption - recreating DB")
          self._connection_pool.clear()
          self.db_path.unlink(missing_ok=True)
          with self._db() as conn:
              conn.executescript(migration_sql)
      else:
          raise
  ```
  Also emit a startup warning whenever a *generated* (non-keyring, non-env) key is
  used so operators know the cache is not durable.

---

### 5. Missing `check_same_thread=False` + Unlocked Pool — CONFIRMED (High)
* **File:** [cache.py:84](src/m365_mcp/cache.py); pool at
  [cache.py:62,108-126](src/m365_mcp/cache.py)
* **Two defects:** (1) `sqlite3.connect()` defaults to `check_same_thread=True`,
  so a connection reused across uvicorn threadpool threads raises
  `ProgrammingError`; (2) `_connection_pool` is a bare `list` mutated without a
  lock, so concurrent `_db()` calls can hand one connection to two threads.
* **Remediation:**
  ```python
  import threading
  self._pool_lock = threading.Lock()      # in __init__

  conn = sqlite3.connect(
      str(self.db_path), timeout=CONNECTION_TIMEOUT, check_same_thread=False
  )                                         # in _create_connection

  # guard every pop()/append() with self._pool_lock in _db()
  ```

---

### 6. Background Worker TOCTOU — CONFIRMED (latent)
* **File:** [background_worker.py:153-174](src/m365_mcp/background_worker.py)
* `_get_next_task()` (SELECT) and `_update_task_status(...,"running")` (UPDATE) run
  in separate transactions, so two workers could claim the same row. Currently
  latent because no worker is started at runtime (see N2); fix before enabling
  concurrency.
* **Remediation:** atomic claim via `UPDATE ... RETURNING` (SQLite >= 3.35):
  ```python
  row = conn.execute("""
      UPDATE cache_tasks SET status='running', started_at=?
      WHERE task_id = (
          SELECT task_id FROM cache_tasks WHERE status='queued'
          ORDER BY priority ASC, created_at ASC LIMIT 1
      )
      RETURNING task_id, account_id, operation, parameters_json,
                priority, retry_count
  """, (time.time(),)).fetchone()
  ```

---

### 7. Deceptive Plaintext Encryption Fallback — CONFIRMED (High)
* **File:** [cache.py:16-19,66-69](src/m365_mcp/cache.py)
* On `ImportError` the module silently swaps in stdlib `sqlite3` (which ignores
  `PRAGMA key`), yet `__init__` still logs `"Cache encryption enabled"`. Mitigated
  in practice by the pinned `sqlcipher3-wheels` dependency, but a hard guard is
  still warranted.
* **Remediation:**
  ```python
  USING_SQLCIPHER = True
  try:
      import sqlcipher3 as sqlite3
  except ImportError:
      import sqlite3
      USING_SQLCIPHER = False

  if self.encryption_enabled and not USING_SQLCIPHER:   # in __init__
      raise ImportError(
          "Cache encryption requested but sqlcipher3 is unavailable.")
  ```

---

### 8. Connection Pool Has No Teardown — CONFIRMED (Medium)
* **File:** [cache.py:33-127](src/m365_mcp/cache.py) — no `close()` exists; on
  Windows lingering handles also block deletion of the DB file.
* **Remediation:** add `close()` (locked, pops and closes every pooled
  connection) and register it with `atexit` where the singleton is created
  ([cache_tools.py:13-23](src/m365_mcp/tools/cache_tools.py)). Do not rely on
  `__del__` alone — shutdown GC ordering is unreliable.

---

### 9. Blocking Device-Flow Auth Inside MCP Requests — CONFIRMED (Medium)
* **File:** [auth.py:238-248](src/m365_mcp/auth.py)
* When `acquire_token_silent` returns nothing, `get_token()` calls the blocking
  `acquire_token_by_device_flow(flow)`, hanging the handler until the flow expires
  (~15 min). (It does correctly print to stderr, not stdout.)
* **Remediation:** fail fast in server context and direct the client to
  `account_authenticate`; gate interactive device flow behind a flag set only by
  `authenticate.py`:
  ```python
  if not result:
      if os.getenv("M365_MCP_INTERACTIVE_AUTH") != "true":
          raise Exception(
              "Token expired and no interactive console. "
              "Call account_authenticate to re-authenticate.")
      app, flow = _initiate_device_flow(app, tenant_id)
      ...
  ```

---

## New Findings (discovered during verification)

### N1. `cache_get_stats` reads keys the cache never returns — Medium (logic)
* **Files:** [cache_tools.py:176-194](src/m365_mcp/tools/cache_tools.py) vs
  [cache.py:444-503](src/m365_mcp/cache.py)
* `CacheManager.get_stats()` returns keys `total_bytes`, `total_hits`,
  `entry_count`, `usage_percent`. The tool reads `total_size_bytes`, `hit_count`,
  and `miss_count` — none of which exist. Consequences:
  - `total_size_mb` is always `0.0`
  - `size_percentage` is always `0.0`
  - `hit_rate` is always `0.0`
  - `cleanup_triggered` is therefore always `False`
* The cache already exposes `usage_percent`; the tool recomputes (incorrectly)
  instead of reusing it, and there is no `miss_count` tracked anywhere.
* **Remediation:** align the keys, reuse `usage_percent`, and either start
  tracking misses in `get_cached`/`set_cached` or stop reporting `hit_rate`.
  ```python
  total_bytes = stats.get("total_bytes", 0)
  stats["total_size_mb"] = total_bytes / (1024 * 1024)
  stats["size_percentage"] = stats.get("usage_percent", 0.0)
  stats["cleanup_triggered"] = stats["size_percentage"] >= 80.0
  ```

### N2. Cache warming & background worker are never started — Medium (omission / doc mismatch)
* **Evidence:** grep shows `CacheWarmer(...)`, `BackgroundWorker(...)`,
  `start_warming()`, and `set_background_worker(...)` are referenced **only in
  tests**. [server.py:main()](src/m365_mcp/server.py) never instantiates or starts
  either.
* **Consequences:**
  - The "automatic cache warming on server startup" promised in `CLAUDE.md` and
    `tech.md` never happens.
  - The three-state TTL collapses to two states in practice: `get_cached`
    ([cache.py:200-224](src/m365_mcp/cache.py)) returns `STALE` data, but nothing
    enqueues a refresh and no worker would run it, so stale entries are simply
    served until they expire (no "refresh in background").
  - `cache_warming_status` always reports `"Background worker not initialized"`.
* **Remediation:** wire a `CacheWarmer`/worker into the FastMCP lifespan/startup
  (respecting `CACHE_WARMING_ENABLED`), and call `set_background_worker(...)`; or,
  if intentionally deferred, correct the documentation so it stops claiming an
  active feature.

### N3. `cache_warming_status` calls a method the worker type lacks — Low (latent)
* **File:** [cache_tools.py:322](src/m365_mcp/tools/cache_tools.py)
* It calls `_background_worker.get_warming_status()`. `get_warming_status` exists on
  `CacheWarmer` ([cache_warming.py:212](src/m365_mcp/cache_warming.py)) but **not**
  on `BackgroundWorker` ([background_worker.py](src/m365_mcp/background_worker.py)).
  The setter is named `set_background_worker` — if a `BackgroundWorker` is ever
  passed (as the name invites), this raises `AttributeError`. Latent only because
  the setter is never called today.
* **Remediation:** standardise on one type; have the tool accept the `CacheWarmer`
  explicitly, or add `get_warming_status` to `BackgroundWorker`.

### N4. SQLCipher hardening settings are defined but never applied — Low
* **Files:** [cache_config.py:35-39](src/m365_mcp/cache_config.py) defines
  `SQLCIPHER_SETTINGS` (`kdf_iter`, `cipher_page_size`, `cipher_use_hmac`) and
  `CONNECTION_TIMEOUT`/`CONNECTION_POOL_SIZE`, but
  [cache.py:_create_connection](src/m365_mcp/cache.py) applies none of them — it
  only sets `cipher_compatibility = 4`, hardcodes `max_connections=5`, and omits
  the connection timeout.
* **Remediation:** apply the configured PRAGMAs after `PRAGMA key`, and pass
  `timeout=CONNECTION_TIMEOUT` / default `max_connections=CONNECTION_POOL_SIZE`.

### N5. `PRAGMA key` built via f-string — Low (defensive)
* **Files:** [cache.py:88](src/m365_mcp/cache.py),
  [cache_migration.py:62,125](src/m365_mcp/cache_migration.py)
* `f"PRAGMA key = '{self.encryption_key}'"`. Generated keys are base64 (never
  contain a single quote) and env keys are validated as base64, so injection is
  not currently reachable — but the pattern is brittle. Prefer the parameterised
  form `conn.execute("PRAGMA key = ?", (key,))` (SQLCipher supports it) or a hex
  key with `PRAGMA key = "x'...'"`.

### N6. `detect_and_migrate` / `migrate_to_encrypted_cache` are dead and misaligned — Low
* **File:** [cache_migration.py](src/m365_mcp/cache_migration.py)
* Neither is called from `src/`. Additionally, `migrate_to_encrypted_cache`
  defaults its output to `CACHE_DB_PATH.with_suffix(".encrypted.db")`, a path the
  `CacheManager` never opens — so even if invoked it would not take effect.
* **Remediation:** delete the module or finish wiring it to the actual cache path
  and a real startup hook.

### N7. `cache_invalidate` ignores the `account_id` filter — Low
* **File:** [cache_tools.py:250-259](src/m365_mcp/tools/cache_tools.py)
* It rewrites `pattern` by string-splitting on `:` and reassembling, then calls
  `invalidate_pattern(pattern, reason=reason)` **without** `account_id`. The
  dedicated account filter in
  [cache.py:invalidate_pattern](src/m365_mcp/cache.py) is never used, and the
  fragile pattern surgery silently no-ops for patterns lacking `:*`.
* **Remediation:** pass `account_id` straight through to `invalidate_pattern` and
  drop the pattern rewriting.

### N8. Erroring connections are returned to the pool — Low (robustness)
* **File:** [cache.py:114-126](src/m365_mcp/cache.py)
* The `finally` block re-pools a connection even after an exception/rollback
  (including an unusable wrong-key SQLCipher handle), so the next caller may reuse
  a poisoned connection. Discard the connection on error instead of pooling it.

---

## Recommended Remediation Order

1. **Finding 2 (ADS path bug)** + **Finding 3 (tzdata)** — these break core file
   and timezone functionality on Windows *today* (the user's platform). Ship first
   with the new regression tests.
2. **Finding 11 / Finding 1 correction** — delete the dead, shadowed
   [tools.py](src/m365_mcp/tools.py) to remove the namespace collision and the
   misleading "registry" docstring.
3. **Finding 7 + N1 + N2** — make encryption failures loud, fix the broken stats
   tool, and either wire up or stop advertising cache warming.
4. **Findings 5, 6, 8, N8** — concurrency/lifecycle hardening, required before the
   HTTP transport or any multi-worker setup is used in earnest.
5. **Finding 4, 9** — headless robustness (key persistence warning, non-blocking
   auth).
6. **N3–N7** — cleanup and defensive hardening.

## Methodology Note

Findings were verified by reading the implicated source files in full, grepping
for call sites across `src/` and `tests/`, and running two targeted CPython 3.12
experiments on Windows (package-vs-module import precedence; `pathlib` drive/ADS
and `relative_to` case behaviour). Where a claim could not be reproduced it is
marked **REFUTED** with the counter-evidence; where the symptom is real but the
stated cause was wrong, it is marked **mechanism corrected**.
