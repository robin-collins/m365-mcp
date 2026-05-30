# Audit Remediation Phase Gates

This file records the minimum verification commands for the audit remediation
branch. Individual task reports in `docs/tasks/` may add narrower commands, but
phase work should not move forward until the applicable gate below has been run
and recorded.

## Baseline Gate

```powershell
uv sync
uv run pyright
uv run pytest tests/test_account_validation.py -q -s
uv run pytest tests/test_cache_tools.py -q -s
```

Known baseline status: `pyright` fails before remediation because of audit
finding N9 and existing test typing issues in
`tests/test_email_folders_integration.py`.

## Phase 0 Gate

```powershell
uv run pytest tests/test_windows_path_scaffolding.py -q
uv run pytest tests/test_cache_teardown_scaffolding.py -q
git status --short
```

Expected pre-fix status: Windows path scaffolding has one strict expected
failure; cache teardown scaffolding has one strict expected failure and one skip
until `CacheManager.close()` exists.

## Phase 1 Gate

```powershell
uv run pytest tests/test_account_validation.py -q
uv run pyright
uvx ruff check .
```

Expected after Phase 1: account-tool pyright errors are fixed. Any remaining
pyright errors should be unrelated baseline test typing issues and documented in
the task report.

## Phase 2 Gate

```powershell
uv run pytest tests/test_validators.py tests/test_windows_path_scaffolding.py -q
uv run pytest tests/test_email_validation.py -q
uv run pyright
uvx ruff check .
```

Expected after Phase 2: normal Windows absolute paths under allowed roots pass,
ADS paths fail, timezone validation works with `tzdata`, and outbound email
attachments/recipients are validated locally.

## Phase 3 Gate

```powershell
uv run pytest tests/test_cache_tools.py -q
uv run pytest tests/test_tool_caching.py -q
uv run pyright
uvx ruff check .
```

Expected after Phase 3: mutation invalidation and cache statistics are correct;
cache warming is either accurately documented as inactive or safely feature
flagged for later enablement.

## Phase 4 Gate

```powershell
uv run pytest tests/test_integration.py -q
uv run pytest tests/test_tool_caching.py -q
uv run pyright
uvx ruff check .
```

Expected after Phase 4: the shadowed root `tools.py` is gone or renamed, runtime
tool registration is unchanged, and contributor documentation matches the
package-based tool layout.

## Phase 5 Gate

```powershell
uv run pytest tests/test_cache.py tests/test_cache_schema.py -q
uv run pytest tests/test_cache_warming.py tests/test_background_worker.py -q
uv run pytest tests/test_cache_teardown_scaffolding.py -q
uv run pyright
uvx ruff check .
```

Expected after Phase 5: encrypted cache setup is explicit, connection pooling is
thread-safe, poisoned connections are discarded, teardown is reliable on
Windows, and background refresh is only enabled after worker claiming is safe.

## Phase 6 Gate

```powershell
uv run pytest tests/test_search_validation.py -q
uv run pytest tests/test_email_rules_validation.py -q
uv run pytest tests/test_account_validation.py -q
uv run pyright
uvx ruff check .
```

Expected after Phase 6: contact search escapes OData literals, rule creation
uses the same validators as updates, and non-interactive MCP token refresh fails
fast instead of blocking on device flow.

## Phase 7 Gate

```powershell
uv run pytest tests/ -q
uv run pyright
uvx ruff format .
uvx ruff check --fix --unsafe-fixes .
git status --short
```

Expected after Phase 7: cleanup decisions and public API compatibility policy
are documented, and generated formatting/lint fixes are committed with their
own task.

## Final Release Gate

```powershell
uv run pytest tests/ -v
uv run pyright
uvx ruff format .
uvx ruff check --fix --unsafe-fixes .
```

Additionally verify FastMCP runtime tool introspection with `await
mcp.get_tools()` and record the final documented tool count.
