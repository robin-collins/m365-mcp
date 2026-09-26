# Task Archive

Completed tasks moved out of the active task list (`202609_TASKS.md`),
newest programme first. Each entry keeps its original ID, completion date,
commit and verification evidence, so the history stays traceable without
cluttering the active list.

**Archiving rule:** when a task in `202609_TASKS.md` is done *and verified*,
move it here in the same commit, under its programme heading, with:
- the completion date (YYYY-MM-DD);
- the commit hash(es);
- the evidence: tests, commands run, live checks.

---

## 2026-09 v1.0.0 unified tools programme

| ID | Task | Completed | Commit | Evidence |
|---|---|---|---|---|
| U0.1 | Merge `202609` into `master` (PR #21) and tag `v0.2.3-final` before any surface change | 2026-09-26 | `706c8c3` (merge) | Tag pushed; `generate_tools_doc.py --check` on a clean worktree of the tag: up to date (85 tools); suite 544 passed before merge |
| U1.1 | `services/mail.py` from `tools/email.py` (list, get, draft, send, update, delete, move, reply, reply-all, forward, attachments) | 2026-09-26 | `5d6a097` | 22 service tests; tool surface unchanged |
| U1.2 | `services/mail_folders.py` from `tools/email_folders.py` | 2026-09-26 | `9ae8696` | Service tests added; tool surface unchanged |
| U1.3 | `services/mail_rules.py` from `tools/email_rules.py`, including reorder | 2026-09-26 | `c970d90` | 22 service tests |
| U1.4 | `services/calendar.py` from `tools/calendar.py` | 2026-09-26 | `9b48c6b` | 17 service tests |
| U1.5 | `services/contacts.py` from `tools/contact.py` | 2026-09-26 | `2ff3663` | 17 service tests |
| U1.6 | `services/drive.py` from `tools/file.py` + `tools/folder.py` | 2026-09-26 | `65f122b` | 25 service tests |
| U1.7 | `services/search.py` folds in `search_router.py` (now a re-export shim until U5.1), current behaviour kept | 2026-09-26 | `2688257` | 25 service tests |
| U1.8 | `services/accounts.py`: account listing and device-flow orchestration over `auth.py` (resolution deferred to U2.10) | 2026-09-26 | `f4d9642` | 6 service tests |
| U1.9 | Phase 1 gate. Cache-manager singleton moved from `tools/cache_tools.py` to `cache.py` (re-exported); `tests/test_services_boundaries.py` AST-checks that services import no FastMCP, `mcp_instance` or `tools` (nested imports included) | 2026-09-26 | this commit | Suite 544 → 710 passed; `generate_tools_doc.py --check` (85 tools) and `build_unified_tool_specs.py --check` pass; pyright 25 errors, identical to the pre-Phase-1 baseline (`tests/test_email_folders_integration.py`, `tests/test_account_validation.py`); ruff: no new findings |
| U2.6 | `cursors.py`: HMAC-protected opaque base64url cursors (version, keyed account hash, resource, request hash, nextLink/offset/per-resource sub-cursors, issued-at); checks MAC, request, 24 h expiry, Graph host allowlist. Key from `M365_MCP_CURSOR_KEY` or per-process random | 2026-09-26 | `fbc29bf` | `tests/test_cursors.py`: round-trip, tamper, expiry (fake clock), wrong request/resource/account, bad host |
| U2.13 | `local_files.py`: allowed roots (cwd, temp, `MCP_FILE_ALLOWED_ROOTS`), deny-list for read and write, symlink resolution, `overwrite=False`, file-name sanitisation | 2026-09-26 | `5217df7` | `tests/test_local_files.py`: traversal, real and patched symlinks, 11 deny-list cases, overwrite, sanitisation |
| U2.14 | `rate_limit.py`: per-account token buckets, sensitive ≤ 20/min, all ≤ 300/min, actionable error | 2026-09-26 | `e19ab1a` | `tests/test_rate_limit.py` (fake clock) |
| U2.16 | `operations.py`: `drive_copy` monitor URLs stored server-side (24 h TTL, account-bound), polled without `Authorization`, mapped to the spec operation shape | 2026-09-26 | `737b3a3` | `tests/test_operations.py`: in_progress → completed / failed, 303 completion, no Authorization header |
| U2.17 | `untrusted.py`: strips control, format and surrogate characters (bidi, zero-width, tag characters), HTML → text fallback, preview/body caps with truncated flag; also applied to attachment and sender/attendee display names | 2026-09-26 | `713f9be` | `tests/test_untrusted_content.py` (42), including a prompt-injection fixture |
| U2.5 | `projections.py`: Graph JSON → §5.2 records for email (summary/detail), email_folder (tree), email_rule (30 predicates / 11 actions, both directions), event (summary/detail), calendar, contact, contact_folder, drive_item (tree), operation | 2026-09-26 | `310ba1e` | `tests/test_projections.py` (38): one fixture test per projection validated against the spec `$defs` |
| U2.1 | Spec packaging: builder writes `src/m365_mcp/tool_specs/` (29 tool JSONs + `index.json`) as package data; `--check` covers both copies; hatch wheel includes them | 2026-09-26 | `65a4eb5` | `tests/test_tool_specs_package.py`: package copy equals docs copy; `uv build --wheel` contains the specs |
| U2.2 | `tools/registry.py`: `build_server(toolsets)` registers tools from spec JSON in index order (exact name, title, description, annotations, meta, input/output schemas); `M365_MCP_TOOLSETS` default `core,extended`, unknown values fail at startup; §12.4 server instructions; `mask_error_details=True` | 2026-09-26 | `69b4bb3` | `tests/test_tool_registry.py`: live `tools/list` equals spec for {core}, {core,extended}, {core,extended,admin}; byte-identical across two processes; admin hidden by default |
| U2.3 | Input pipeline: Draft 2020-12 validation (strict RFC 3339 date-time) converted to `Invalid <param> '<value>': <reason>. Expected: <expected>`; per-tool semantic rule hook (`tools/handlers.py`) | 2026-09-26 | `a167c54` | `tests/test_input_validation.py`: shared invalid-input corpus rejected at runtime; every spec example passes |
| U2.4 | Output contract: structuredContent plus one text block equal to `summary`; output validated against `outputSchema` in test mode (`M365_MCP_VALIDATE_OUTPUT`, on under pytest) | 2026-09-26 | `6ba7b1f` | `tests/test_output_contract.py`: spec example outputs round-trip; mismatches fail loudly |
| U2.7 | `errors.py`: `GraphAPIError` (subclass of `httpx.HTTPStatusError`) raised from `graph._send`; `to_tool_error` maps 400/401/403/404/409/412/413/423/429/5xx to actionable text with no URLs, codes or request IDs; FastMCP imported lazily so services never load it | 2026-09-26 | `9323a61`, `0d48aad` | `tests/test_graph_errors.py`: one test per status; no-URL check over 13 statuses × 10 resources; subprocess import test |
| U2.8 | `graph.batch()`: `POST /$batch` in chunks of 20, per-item results in input order, 429/5xx retried with Retry-After for idempotent items only; POST/PATCH never resent | 2026-09-26 | `9323a61` | `tests/test_graph_batch.py`: partial failure, throttling, non-idempotent, deadline |
| U2.9 | Deadline budget: reads 45 s, writes 60 s, checked before every retry or sleep (including 401 refresh and network retries); transfers exempt; `DeadlineExceeded` says "try again in N s" | 2026-09-26 | `9323a61` | `tests/test_graph_deadline.py` (fake clock) |
| U2.10 | `services.accounts.resolve_account_id`: optional `account_id`, single account by default, ID or email (case-insensitive), errors list ID and email | 2026-09-26 | `c365559` | `tests/test_account_resolution.py`: 0-, 1- and 2-account tests |
| U2.11 | Personal-only auth: default authority `consumers` (`.env.example` updated); work/school rejected at sign-in completion and removed from the MSAL cache; `account_type.py` and account-type metadata removed (legacy `account_list` still reports `"personal"`); `auth_sessions.py` device-flow store (opaque ID, flow server-side, 15 min TTL, single use). `pyjwt` dropped as unused; `jsonschema` made a runtime dependency | 2026-09-26 | `fde613f`, this commit | `tests/test_personal_only_auth.py`, `tests/test_auth_sessions.py`: rejection, expiry, no device code or flow in output |
| U2.15 | `observability.py`: FastMCP middleware logs one JSON line per call (tool, resource, hashed account, duration, outcome, error class, Graph retries via a context variable, result bytes, mutation flag), never argument values; §12.4 server instructions; registry maps handler exceptions through `errors.to_tool_error` | 2026-09-26 | `684c6f4` | `tests/test_observability.py`: log shape (success, failed mutation, validation error), secret redaction, instructions text, retry counting |
| U2.12 | `resource_cache.py`: keys (account, resource, normalised params, cursor) hashed; per-resource TTL policies in `cache_config.py`; `get_or_fetch` with `refresh` bypass and no metadata in results; account-scoped `invalidate`, typed `invalidate_scope`; `MUTATION_INVALIDATES` table for all 20 mutating tools. Stale unified entries are not queued for background refresh (the worker only knows legacy tool names) | 2026-09-26 | `7b7e442` | `tests/test_resource_cache.py` (72): key normalisation, TTL lifecycle per resource, refresh bypass, isolation, scope, invalidation matrix per (tool, resource) |
| — | Live mailbox test guarded: `tests/test_email_folders_integration.py` wrote to the real mailbox during the unit gate; now needs `M365_MCP_LIVE_TESTS=1` | 2026-09-26 | `36b0114` | 7 skipped by default |

---

## 2026-09 Unified tool design and specification

| ID | Task | Completed | Commit | Evidence |
|---|---|---|---|---|
| D1 | Audit the codebase against `MCP_BEST_PRACTICES.md`; write `202609_MCP_BEST_PRACTICES_REPORT.md` (scorecard, findings, P0–P2 roadmap) | 2026-09-26 | `9142609` | Live `tools/list` analysis (85 tools, about 27k tokens), live error and result-size probes |
| D2 | Revise `UNIFIED_TOOLS_CONCEPT.md` into the approved design: 29 tools, decisions D1–D8, verified personal-account Graph constraints, 85-row mapping, delivery plan | 2026-09-26 | `2d60c78` | Live probes: Search API unsupported for MSA; `getSchedule` works only for your own address; `$search`/`$filter` work; createLink and invite rules from Graph docs |
| D3 | Build the implementation source of truth `docs/unified-tools/` (29 per-tool JSON Schema 2020-12 specs, index, legacy mapping, `SCHEMA_REFERENCE.md`, README), generated by `scripts/build_unified_tool_specs.py` | 2026-09-26 | `693431c` | `tests/test_unified_tool_specs.py`: 121 passed; builder `--check` clean; ruff and pyright clean |
| D4 | Correct inbox-rule schema to Graph's exact 30 predicates / 11 actions (legacy validator accepts 6 invalid predicates, rejects 16 valid ones) | 2026-09-26 | `693431c` | Compared against Graph `messageRulePredicates` / `messageRuleActions` docs; test asserts coverage |
| D5 | Measure and set definition token budgets: core 9.4k (≤10k), default 13.5k (≤14k), vs legacy about 22k undocumented | 2026-09-26 | `693431c` | `test_definition_token_budget` |

---

## 2026-09 Tool reference documentation

| ID | Task | Completed | Commit | Evidence |
|---|---|---|---|---|
| DOC1 | `MCP_SERVER_TOOLS.md`: authoritative reference for the current 85 tools (connection, conventions, index, per-tool reference, verified delete semantics) | 2026-09-26 | `47f9710` | Generated from live `tools/list`; 85 anchors, headings and index rows verified |
| DOC2 | `scripts/generate_tools_doc.py` regenerates sections 4–5 with `--check` for CI; hand-verified notes kept in `ARG_OVERRIDES` / `IMPLEMENTATION_NOTES` | 2026-09-26 | `47f9710` | Regeneration reproduced the document; ruff and pyright clean |

---

## 2026-09 Reliability and auth review

Scope: reliability of Microsoft Graph calls, the initial auth flow, and
silent token refresh for personal accounts.

### Findings (context for the tasks below)

- **F1. Root cause of the forced re-auth:** the refresh token expired after
  113 days idle (`AADSTS70000`). Personal refresh tokens expire after 90
  days without use. The user re-authenticated on 2026-09-26.
- **F2.** `authenticate.py` reported success without checking tokens.
- **F3.** Token cache written with no lock and no atomic write; concurrent
  processes could lose rotated refresh tokens.
- **F4.** A new MSAL app (with network tenant discovery) was built on every
  Graph request.
- **F5.** MSAL errors were swallowed, so expiry and transient failures
  looked identical.
- **F6.** `account_complete_auth` blocked for up to 15 minutes; its
  "pending" branch was unreachable.
- **F7.** No 401 refresh-and-retry.
- **F8.** Network errors were not retried; the token went stale across
  retries.
- **F9.** `Retry-After` HTTP-date values crashed; `Retry-After` on 503 was
  ignored.
- **F10.** Chunked uploads sent `Authorization` to the pre-authenticated
  upload URL; an empty final 201 crashed.

### Completed tasks

| ID | Task | Completed | Commit | Evidence |
|---|---|---|---|---|
| T1 | `authenticate.py` checks every account (forced refresh), offers re-sign-in for expired accounts, exits 1 unless all usable (F2) | 2026-09-26 | `f3120cb` | 3 new script tests |
| T2 | Token cache via `msal-extensions` `PersistedTokenCache` (cross-process lock, reload on change) (F3) | 2026-09-26 | `f3120cb` | Live: cache persisted after refresh |
| T3 | Reuse one MSAL app per (client_id, tenant) (F4) | 2026-09-26 | `f3120cb` | `test_build_app_reuses_app_per_tenant`; live 1.5 s → 0.5 s per call |
| T4 | `get_token()` surfaces the MSAL reason; `SignInRequiredError` for `invalid_grant` etc.; transient errors distinct (F5) | 2026-09-26 | `f3120cb` | 3 new tests |
| T5 | `account_complete_auth` polls once (non-blocking) (F6) | 2026-09-26 | `f3120cb` | Pending-status test asserts `exit_condition` |
| T6 | 401 → one forced token refresh and retry (F7) | 2026-09-26 | `f3120cb` | 2 tests in `tests/test_graph_client.py` |
| T7 | Retry transport errors: connect errors for all methods, timeouts only for idempotent ones; token fetched per attempt (F8) | 2026-09-26 | `f3120cb` | 3 tests |
| T8 | Robust `Retry-After` (seconds or HTTP date, capped 60 s), honoured on 503 (F9) | 2026-09-26 | `f3120cb` | 2 tests |
| T9 | No `Authorization` on upload-session URLs; empty 201 handled (F10) | 2026-09-26 | `f3120cb` | 1 test |
| T9a | POSTs no longer retried on ambiguous 5xx or read timeouts (no duplicate sends); 429/503 still retried | 2026-09-26 | `f3120cb` | `test_post_is_not_retried_on_ambiguous_5xx`, `test_read_timeout_is_not_retried_for_post` |
| T10 | Unit tests for all new behaviour; suite, ruff and pyright green | 2026-09-26 | `f3120cb`, `0c7f915` | Suite 401 → 423 passed; pyright 0 errors; no new ruff findings (HEAD-vs-current comparison) |
| T11 | Live verification on the personal account | 2026-09-26 | — | Forced refresh OK; 3 × `GET /me` OK; cache persisted; one app reused |
| N1 | Pagination resends the first page's query headers on every nextLink page (fixes HTML bodies on page 2+ and missing `ConsistencyLevel`) | 2026-09-26 | `f3120cb`, `0c7f915` | `test_paginated_next_pages_keep_query_headers`; live: 3 pages all `text` |
| N2 | Device flow records the issuing tenant; completion uses the same authority | 2026-09-26 | `f3120cb`, `0c7f915` | 2 tests |
| N3 | `graph.request()` no longer mutates caller `params` (`_query_headers()` shared with pagination) | 2026-09-26 | `f3120cb`, `8bb8150`, `0c7f915` | `test_request_does_not_mutate_caller_params`; live check |
| N-verify | Final verification of N1–N3 | 2026-09-26 | `8bb8150` | Suite 423 passed; pyright 0; ruff no new findings |
