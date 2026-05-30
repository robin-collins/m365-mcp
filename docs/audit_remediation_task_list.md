# Code Audit Remediation Task List

Source audit: `docs/analysis_results.md`

This checklist converts the confirmed audit findings into an implementation
sequence. Tasks are ordered so that each phase can be tested before later phases
depend on it. Refuted findings from the audit are intentionally excluded from
implementation work except where they reveal documentation drift.

## Global Rules For This Work

- Keep each phase independently reviewable and testable.
- Write or update regression tests before fixing the behavior they cover.
- Run the phase gate before moving to the next phase.
- Do not enable cache warming or multiple background workers until the cache
  connection pool, task claiming, and shutdown lifecycle are hardened.
- Preserve the public MCP tool surface unless a task explicitly calls for a
  compatibility decision and migration note.

## Phase 0 - Baseline And Test Harness

- [ ] T0.1 Capture the current quality baseline.
  - Report references: Methodology note, N9, N10, N12.
  - Changes: none expected.
  - Verification: run `uv sync`, `uv run pyright`, and the currently passing
    targeted suites named in the audit:
    `uv run pytest tests/test_account_validation.py -q -s` and
    `uv run pytest tests/test_cache_tools.py -q -s`.
  - Dependency: none.

- [ ] T0.2 Add regression-test scaffolding for Windows-sensitive validation and
  cache file teardown.
  - Report references: Finding 2, Finding 8, Finding 12.
  - Changes: add fixtures/helpers that can exercise Windows path behavior
    without relying on a developer's absolute user path where possible.
  - Verification: the new tests should fail or be skipped with a clear reason
    before the implementation tasks that fix them.
  - Dependency: T0.1.

- [ ] T0.3 Define the phase gate command set for this remediation branch.
  - Report references: Repository guidelines, Methodology note.
  - Changes: document the minimum per-phase commands in the PR notes or a
    temporary checklist.
  - Verification: every later phase records which commands passed.
  - Dependency: T0.1.

## Phase 1 - Restore MCP-Native Authentication

- [ ] T1.1 Fix account device-flow startup.
  - Report reference: N9.
  - Files: `src/m365_mcp/tools/account.py`, `src/m365_mcp/auth.py`.
  - Changes: unpack `auth.get_app()` as `(app, tenant_id)` in
    `account_authenticate`; call `auth._initiate_device_flow(app, tenant_id)`.
  - Verification: add or update a test that mocks `auth.get_app` with the real
    tuple shape and proves `initiate_device_flow` is reached.
  - Dependency: T0.1.

- [ ] T1.2 Fix account device-flow completion.
  - Report reference: N9.
  - Files: `src/m365_mcp/tools/account.py`.
  - Changes: unpack `auth.get_app()` before calling
    `acquire_token_by_device_flow(flow)`.
  - Verification: update completion tests so the tuple-shaped contract is
    covered.
  - Dependency: T1.1.

- [ ] T1.3 Phase 1 gate.
  - Verification: run `uv run pyright` and
    `uv run pytest tests/test_account_validation.py -q`.
  - Dependency: T1.1, T1.2.

## Phase 2 - Local File Safety And Windows Runtime Correctness

- [ ] T2.1 Add the missing timezone database dependency.
  - Report reference: Finding 3.
  - Files: `pyproject.toml`, `uv.lock`.
  - Changes: add `tzdata>=2024.1` or the project-approved pinned equivalent;
    refresh the lockfile with `uv sync`.
  - Verification: add or update a Windows-safe timezone validation test that
    covers at least `UTC`.
  - Dependency: T1.3.

- [ ] T2.2 Fix Windows alternate-data-stream path validation.
  - Report reference: Finding 2.
  - Files: `src/m365_mcp/validators.py`, `tests/test_validators.py`.
  - Changes: skip the drive component explicitly when checking Windows path
    parts for `:`; keep reserved-name validation intact.
  - Verification: add tests proving normal absolute paths under an allowed root
    are accepted and ADS paths are rejected.
  - Dependency: T0.2.

- [ ] T2.3 Centralize outbound attachment validation.
  - Report reference: N11.
  - Files: `src/m365_mcp/tools/email.py`, `src/m365_mcp/validators.py`.
  - Changes: create or reuse one helper for outbound attachment preparation;
    call `ensure_safe_path`; enforce allowed roots, existence, attachment-count
    limits, and request-size limits before reading bytes.
  - Verification: add tests for accepted attachments, path traversal rejection,
    disallowed roots, oversize files, and attachment-count limits.
  - Dependency: T2.2.

- [ ] T2.4 Align draft-recipient validation with send-recipient validation.
  - Report reference: N11.
  - Files: `src/m365_mcp/tools/email.py`.
  - Changes: apply `normalize_recipients` and the same dedupe/limit behavior
    used by `email_send` to `email_create_draft`.
  - Verification: add tests for invalid recipient values, duplicate
    recipients, and recipient-limit behavior in draft creation.
  - Dependency: T2.3.

- [ ] T2.5 Phase 2 gate.
  - Verification: run validator tests, targeted email tool tests, `uv run
    pyright`, and `uvx ruff check .`.
  - Dependency: T2.1, T2.2, T2.3, T2.4.

## Phase 3 - Cache Correctness Before Background Work

- [ ] T3.1 Fix mutation invalidation argument order.
  - Report reference: N10.
  - Files: `src/m365_mcp/tools/email.py`, `src/m365_mcp/tools/file.py`, any
    other mutation call sites found by grep.
  - Changes: call `invalidate_pattern("resource:*", account_id=account)` rather
    than passing account ID as the pattern.
  - Verification: add tests that seed cache entries and prove each write tool
    deletes the expected account-scoped entries.
  - Dependency: T2.5.

- [ ] T3.2 Replace impossible targeted invalidation patterns.
  - Report reference: N10.
  - Files: `src/m365_mcp/tools/email.py`, `src/m365_mcp/tools/file.py`,
    `src/m365_mcp/cache.py` if metadata support is chosen.
  - Changes: either broaden invalidation to match the existing
    `resource_type:account_id:param_hash` key structure, or add explicit
    metadata columns for resource IDs and query them directly.
  - Verification: tests cover invalidating list caches and affected get caches
    for the correct account only.
  - Dependency: T3.1.

- [ ] T3.3 Fix cache statistics reported by `cache_get_stats`.
  - Report reference: N1.
  - Files: `src/m365_mcp/tools/cache_tools.py`, optionally
    `src/m365_mcp/cache.py`.
  - Changes: use `total_bytes`, `total_hits`, `entry_count`, and
    `usage_percent`; either implement real miss tracking or remove/mark
    unavailable hit-rate fields.
  - Verification: update `tests/test_cache_tools.py` to assert nonzero size and
    correct cleanup-trigger calculation.
  - Dependency: T3.1.

- [ ] T3.4 Stop advertising inactive cache warming until it is safe to enable.
  - Report reference: N2.
  - Files: `.projects/steering/tech.md`, `docs/cache_user_guide.md`,
    `docs/cache_examples.md`, or runtime status text as applicable.
  - Changes: either mark cache warming as currently inactive, or add a feature
    flag note that startup warming remains disabled until Phase 5 hardening is
    complete.
  - Verification: documentation and `cache_warming_status` messaging no longer
    claim an active worker before one exists.
  - Dependency: T3.3.

- [ ] T3.5 Phase 3 gate.
  - Verification: run `uv run pytest tests/test_cache_tools.py -q`, targeted
    mutation invalidation tests, `uv run pyright`, and `uvx ruff check .`.
  - Dependency: T3.1, T3.2, T3.3, T3.4.

## Phase 4 - Tool Registry And Documentation Drift

- [ ] T4.1 Delete the shadowed root `tools.py` or rename the package entry point.
  - Report references: Finding 11, Finding 1 correction, N14.
  - Files: `src/m365_mcp/tools.py`, `src/m365_mcp/tools/__init__.py`,
    `src/m365_mcp/server.py`, tests.
  - Changes: remove the dead, shadowed registry file if no live imports require
    it; update any stale imports to the package layout.
  - Verification: import `m365_mcp.tools`, start FastMCP registration, and
    confirm the runtime tool count remains unchanged.
  - Dependency: T3.5.

- [ ] T4.2 Update contributor guidance to the real package layout.
  - Report reference: N14.
  - Files: `.projects/steering/structure.md`, `.projects/steering/tech.md`,
    `FILETREE.md`, relevant docs.
  - Changes: replace references to a monolithic `tools.py` registry and stale
    tool counts with `src/m365_mcp/tools/` package guidance.
  - Verification: docs mention the package import path and current tool export
    expectations.
  - Dependency: T4.1.

- [ ] T4.3 Add a public tool-surface regression test.
  - Report reference: N14.
  - Files: tests under `tests/`.
  - Changes: compare `await mcp.get_tools()` against the documented/exported
    public tool list, or at minimum assert known modules are represented.
  - Verification: the test fails if a new tool registers at runtime but is
    omitted from the expected public surface.
  - Dependency: T4.2.

- [ ] T4.4 Phase 4 gate.
  - Verification: run tool-registration tests, `uv run pyright`, and
    `uvx ruff check .`.
  - Dependency: T4.1, T4.2, T4.3.

## Phase 5 - Cache Security, Concurrency, And Lifecycle Hardening

- [ ] T5.1 Add a hard SQLCipher availability guard.
  - Report reference: Finding 7.
  - Files: `src/m365_mcp/cache.py`, cache tests.
  - Changes: track `USING_SQLCIPHER`; raise a clear error when encryption is
    requested but `sqlcipher3` is unavailable; stop logging "encryption enabled"
    for plaintext fallback.
  - Verification: test the import-fallback path and the encrypted path.
  - Dependency: T4.4.

- [ ] T5.2 Apply configured SQLCipher and connection settings.
  - Report reference: N4.
  - Files: `src/m365_mcp/cache.py`, `src/m365_mcp/cache_config.py`.
  - Changes: use `CONNECTION_TIMEOUT`, `CONNECTION_POOL_SIZE`, and
    `SQLCIPHER_SETTINGS` when creating connections.
  - Verification: unit tests inspect connection setup or use a mock connection
    to confirm the expected PRAGMAs are applied.
  - Dependency: T5.1.

- [ ] T5.3 Make the SQLite connection pool thread-safe.
  - Report reference: Finding 5.
  - Files: `src/m365_mcp/cache.py`.
  - Changes: pass `check_same_thread=False` to `sqlite3.connect`; protect all
    pool pop/append/clear operations with a lock.
  - Verification: add a threadpool stress test that performs concurrent cache
    reads/writes without `ProgrammingError` or duplicate connection checkout.
  - Dependency: T5.2.

- [ ] T5.4 Discard poisoned connections after errors.
  - Report reference: N8.
  - Files: `src/m365_mcp/cache.py`.
  - Changes: do not return a connection to the pool after rollback-worthy
    exceptions or SQLCipher key failures.
  - Verification: test that an erroring operation closes or discards the
    connection instead of reusing it.
  - Dependency: T5.3.

- [ ] T5.5 Add explicit cache teardown.
  - Report references: Finding 8, Finding 12.
  - Files: `src/m365_mcp/cache.py`, `src/m365_mcp/tools/cache_tools.py`, tests.
  - Changes: add locked `CacheManager.close()` that closes all pooled
    connections; register singleton teardown with `atexit`; update tests and
    fixtures to call `close()` before deleting temporary DB files.
  - Verification: rerun cache tests on Windows and confirm teardown no longer
    leaves locked files.
  - Dependency: T5.4.

- [ ] T5.6 Recover cleanly from cache key mismatch or corruption.
  - Report reference: Finding 4.
  - Files: `src/m365_mcp/cache.py`, `src/m365_mcp/encryption.py`.
  - Changes: catch SQLCipher "file is not a database" or encryption failures in
    `_init_database`; close/clear the pool; delete the bad cache DB; recreate it
    with the current key.
  - Verification: simulate a wrong key and assert initialization recreates the
    cache instead of crashing.
  - Dependency: T5.5.

- [ ] T5.7 Warn when an ephemeral cache key is used.
  - Report reference: Finding 4.
  - Files: `src/m365_mcp/encryption.py`.
  - Changes: emit a startup warning when neither keyring nor
    `M365_MCP_CACHE_KEY` provides a durable key.
  - Verification: test/log assertion for the generated-key path.
  - Dependency: T5.6.

- [ ] T5.8 Parameterize or safely encode SQLCipher `PRAGMA key`.
  - Report reference: N5.
  - Files: `src/m365_mcp/cache.py`, `src/m365_mcp/cache_migration.py`.
  - Changes: replace f-string key interpolation with a parameterized PRAGMA or
    a correctly encoded SQLCipher hex-key form.
  - Verification: tests cover env-provided base64 keys and generated keys.
  - Dependency: T5.2.

- [ ] T5.9 Make background task claiming atomic.
  - Report reference: Finding 6.
  - Files: `src/m365_mcp/background_worker.py`, worker tests.
  - Changes: replace separate SELECT and UPDATE transactions with an atomic
    `UPDATE ... RETURNING` claim or an equivalent SQLite-safe transaction.
  - Verification: concurrency test with two workers proves a queued task is
    claimed once.
  - Dependency: T5.3.

- [ ] T5.10 Standardize cache warming status ownership.
  - Report reference: N3.
  - Files: `src/m365_mcp/tools/cache_tools.py`,
    `src/m365_mcp/cache_warming.py`, `src/m365_mcp/background_worker.py`.
  - Changes: have `cache_warming_status` receive the type that actually exposes
    `get_warming_status`, or add a compatible method to the worker and rename
    setters to avoid type confusion.
  - Verification: tests cover initialized and uninitialized warming status.
  - Dependency: T5.9.

- [ ] T5.11 Wire cache warming and background refresh only after hardening.
  - Report reference: N2.
  - Files: `src/m365_mcp/server.py`, `src/m365_mcp/cache_warming.py`,
    `src/m365_mcp/background_worker.py`, `src/m365_mcp/tools/cache_tools.py`.
  - Changes: instantiate `CacheWarmer`/worker during FastMCP startup or lifespan,
    respect `CACHE_WARMING_ENABLED`, call the appropriate setter, and shut the
    worker down cleanly.
  - Verification: integration test proves stale cache entries enqueue refresh,
    `cache_warming_status` reports a real worker when enabled, and disabling the
    env flag leaves behavior unchanged.
  - Dependency: T5.5, T5.9, T5.10.

- [ ] T5.12 Phase 5 gate.
  - Verification: run all cache, cache schema, cache warming, and background
    worker tests; run the Windows teardown regression; run `uv run pyright` and
    `uvx ruff check .`.
  - Dependency: T5.1 through T5.11.

## Phase 6 - Request Shaping And Validation Parity

- [ ] T6.1 Escape OData contact-search string literals.
  - Report reference: N12.
  - Files: `src/m365_mcp/search_router.py`, search tests.
  - Changes: add an OData string-literal escaping helper and use it in
    `_search_contacts_filter`.
  - Verification: regression tests for apostrophes, doubled quotes, and hostile
    filter fragments.
  - Dependency: T5.12.

- [ ] T6.2 Validate `emailrules_create` like `emailrules_update`.
  - Report reference: N13.
  - Files: `src/m365_mcp/tools/email_rules.py`, email-rule tests.
  - Changes: trim and validate display name; validate sequence, booleans,
    predicates, actions, and exceptions before calling Graph.
  - Verification: tests prove invalid create payloads fail locally and valid
    payloads match update validation behavior.
  - Dependency: T6.1.

- [ ] T6.3 Prevent blocking device-flow auth inside normal MCP requests.
  - Report reference: Finding 9.
  - Files: `src/m365_mcp/auth.py`, `authenticate.py`, account/auth tests.
  - Changes: make `get_token()` fail fast unless
    `M365_MCP_INTERACTIVE_AUTH=true`; set that flag only in the interactive
    authentication script.
  - Verification: test silent-token miss in server context raises an actionable
    error immediately; test interactive script path still permits device flow.
  - Dependency: T1.3.

- [ ] T6.4 Phase 6 gate.
  - Verification: run targeted search, email-rule, and auth tests; run
    `uv run pyright` and `uvx ruff check .`.
  - Dependency: T6.1, T6.2, T6.3.

## Phase 7 - Cleanup, Migration Decisions, And Public API Consistency

- [ ] T7.1 Decide whether to delete or wire cache migration utilities.
  - Report reference: N6.
  - Files: `src/m365_mcp/cache_migration.py`, cache startup code, docs.
  - Changes: delete dead migration code, or wire it to the real cache path and
    startup flow.
  - Verification: if deleted, imports and tests still pass; if wired, migration
    tests prove the manager opens the migrated database.
  - Dependency: T5.12.

- [ ] T7.2 Fix `cache_invalidate` account filtering.
  - Report reference: N7.
  - Files: `src/m365_mcp/tools/cache_tools.py`, cache tool tests.
  - Changes: pass `account_id` directly to `invalidate_pattern`; remove fragile
    pattern rewriting.
  - Verification: tests prove account-scoped invalidation deletes only the
    requested account's entries for both wildcard and non-wildcard patterns.
  - Dependency: T3.5.

- [ ] T7.3 Resolve the account-id-first signature drift.
  - Report reference: N15.
  - Files: multiple modules under `src/m365_mcp/tools/`,
    `.projects/steering/mcp-server.md`, changelog/docs.
  - Changes: make an explicit compatibility decision:
    - Option A: preserve current public signatures and update steering docs to
      describe the real API.
    - Option B: migrate account-scoped tools to `account_id` first, add
      compatibility shims or migration notes, and update generated-client tests.
  - Verification: AST/tool-registration test reports zero unexpected drift for
    the chosen policy.
  - Dependency: T4.4.

- [ ] T7.4 Refresh public documentation after all behavior changes.
  - Report references: N2, N14, N15, Finding 11.
  - Files: `README.md`, `QUICKSTART.md`, `SECURITY.md`, `FILETREE.md`,
    `.projects/steering/*.md`, cache docs.
  - Changes: update authentication flow, cache warming behavior, encryption
    fallback behavior, tool layout, and any signature policy changes.
  - Verification: docs no longer contradict runtime behavior or the selected
    compatibility policy.
  - Dependency: T7.1, T7.2, T7.3.

- [ ] T7.5 Phase 7 gate.
  - Verification: run `uv run pyright`, `uvx ruff format .`,
    `uvx ruff check --fix --unsafe-fixes .`, and the targeted tests affected by
    cleanup decisions.
  - Dependency: T7.1, T7.2, T7.3, T7.4.

## Final Release Gate

- [ ] T8.1 Run the full automated suite.
  - Verification: `uv run pytest tests/ -v`.
  - Dependency: T7.5.

- [ ] T8.2 Run type checking and linting from a clean worktree.
  - Verification: `uv run pyright`, `uvx ruff format .`, and
    `uvx ruff check --fix --unsafe-fixes .`.
  - Dependency: T8.1.

- [ ] T8.3 Re-run runtime MCP tool introspection.
  - Report references: Finding 1 correction, N14.
  - Verification: `await mcp.get_tools()` returns the expected documented tool
    count and includes tools from each package module.
  - Dependency: T8.2.

- [ ] T8.4 Verify Windows-specific regressions.
  - Report references: Finding 2, Finding 3, Finding 8, Finding 12.
  - Verification: path validation accepts normal Windows absolute paths,
    rejects ADS paths, timezone validation works with `tzdata`, and temporary
    cache DB directories can be deleted after tests.
  - Dependency: T8.3.

- [ ] T8.5 Prepare release or PR notes.
  - Changes: summarize user-visible behavior changes, security fixes,
    compatibility decisions, tests run, and any intentionally deferred work.
  - Dependency: T8.4.

## Findings With No Direct Code Task

- Finding 1 is refuted. No startup tool-registration fix is required, but its
  namespace-collision root cause is handled by T4.1 through T4.3.
- Finding 10 is refuted. No `relative_to` case-sensitivity fix is required.
- Finding 12 is plausible rather than fully re-verified. It is covered as a
  verification and fixture-hardening concern in T0.2, T5.5, and T8.4.
