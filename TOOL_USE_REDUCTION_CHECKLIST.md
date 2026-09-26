# Tool-Use Reduction Checklist

Implementation task list for `TOOL_USE_REDUCTION_REQUEST.md` (revision 3,
target 1.1.0). Decisions D1 to D6 and Q1 to Q5 are **approved**
(2026-09-27); see the request, sections 2 and 11. Work-item IDs (F1, A1, B7,
D1, and so on) refer to that document.

This file is written to be executed by agents. Read sections 1 to 3 first;
section 4 is the task list; section 5 is the task index used to check
dependencies.

## 1. Approved decisions (do not re-litigate)

| ID | Decision |
|---|---|
| D1 | New list defaults ship in **1.1.0** (owner-approved exception to the versioning rule). ADR, CHANGELOG "Changed" entry, escape hatches `fields="full"` and `preview_chars=255`. |
| D2 | Compress existing tool definitions first. |
| D3 | Light parameters in core/extended; seven heavy tools in a new opt-in `bulk` tier. |
| D4 | One execution model: inline budget, then job UUID; long-poll status; plan/apply with `plan_id`. |
| D5 | Richer responses: `folder_path`, rule `sequence` and resolved names in every read. |
| D6 | Job and plan store are Phase 1 work. |
| Q1 | Version label stays 1.1.0 (ADR plus prominent CHANGELOG entry). |
| Q2 | Caps stay 10,000 (core) and 14,000 (core+extended) after compression; separate `bulk` budget 6,000. |
| Q3 | Cancel a job with `m365_delete(resource="operation")`. |
| Q4 | MCP protocol tasks are skipped in 1.1.0. |
| Q5 | Defaults: inline budget 20 s, max wait 30 s, plan expiry 30 min, result retention 24 h, 100 IDs per `ids` call, `max_items` up to 1,000; all configurable by environment variable. |

## 2. Execution protocol for agents

### 2.1 Branches and merging

- One **integration branch**: `tool-use-reduction`, created from the current
  branch (`embrace-extend-extinguish`) by the orchestrator (task **P0.0**).
- One **task branch per agent assignment**: `tur/<task-id>` (for chained
  tasks, one branch for the chain: `tur/W1-A`), each in its own git worktree
  (`isolation: "worktree"`).
- Merge into the integration branch **only when the task's "Done when" is
  met and the standard gates pass**. Merge in the order listed in the wave
  table. Rebase a task branch on the integration branch before merging.
- Agents do **not** push, open pull requests, or touch `master`. The owner
  does the final PR after Phase 1 exit review, Phase 2 exit and Phase 3 exit.
- Commit messages are imperative and end with the required attribution
  line. One logical commit per task or sub-step; the generated files
  (below) are committed together with the change that caused them.

### 2.2 Generated files and the builder hotspot

`scripts/build_unified_tool_specs.py` is one 4,000-line file and the source
for `docs/unified-tools/`, `src/m365_mcp/tool_specs/` and
`MCP_SERVER_TOOLS.md`. Rules:

1. Never edit generated files by hand.
2. On a merge conflict in a generated file, **take either side and
   re-run** `uv run python scripts/build_unified_tool_specs.py` and
   `uv run python scripts/generate_tools_doc.py`, then commit the regenerated
   output. Only conflicts in the builder itself are resolved by hand.
3. Agents in the same wave edit **different tool blocks** of the builder
   (the wave table lists which); never reformat or reorder unrelated blocks.
4. Compression (T1.x) must be merged **before** any task that adds
   parameters to the same tools (`email_rule_manage`, `m365_list`,
   `m365_search`, `m365_update`); the dependency lists enforce this.
5. Token cost is measured with the estimator in
   `tests/test_unified_tool_specs.py` (`chars / 4`). A task that pushes a
   budget over its cap fails its gate; it must compress or negotiate with the
   orchestrator, not raise a cap.

### 2.3 Standard gates

Run in the task's worktree before requesting a merge:

```bash
uv run pytest tests/ -q
uv run pyright
uvx ruff check .
uvx ruff format --check .
uv run python scripts/build_unified_tool_specs.py --check
uv run python scripts/generate_tools_doc.py --check
```

### 2.4 Rules that apply to every task

- Read `CLAUDE.md` and `.projects/steering/*.md` first; follow them.
- **Spec first**: edit the builder, regenerate, then implement.
- **Test first** (TDD): write the failing test, then the minimum code.
- Every new `validation_rules` entry gets a test with its **exact** error
  text; spec examples are fixtures.
- Services never import FastMCP (`tests/test_services_boundaries.py`).
- Errors carry no URLs, Graph codes or request IDs (`errors.py`).
- Never log or return tokens; audit lines never contain argument values.
- Do not set `M365_MCP_LIVE_TESTS` for write-capable checks. **No live
  writes against a real mailbox**; live writes are done only by the owner on a
  disposable folder, draft, event and contact.
- Do not remove or rename any tool, parameter or result field. The only
  approved behaviour change is D1.
- Surgical changes: touch only what the task needs; mention unrelated
  problems in the report instead of fixing them.
- If something in the task is ambiguous, blocked, or would need a decision
  the request does not record, **stop and report**; do not guess.

### 2.5 Agent brief template

Each agent is started with:

> You are implementing task(s) `<IDs>` of `TOOL_USE_REDUCTION_CHECKLIST.md`
> in worktree `<branch>`. First read `CLAUDE.md`, `.projects/steering/*.md`,
> `TOOL_USE_REDUCTION_REQUEST.md` (sections `<list>`) and the task text in
> the checklist. Follow checklist section 2 exactly (branching, generated
> files, gates, rules). Work test-first. When the "Done when" for every task
> in your assignment is met and all standard gates pass, report: files
> changed, tests added, gate output summary (pass or fail, with output for any
> failure), token cost change for tools you touched, and anything you
> deferred or found. Do not merge, push or open a pull request.

### 2.6 Human gates

| Gate | When | Owner action |
|---|---|---|
| G0 | After Wave 0 | Review the ADR (P0.4) and the baseline counts |
| G1 | After Wave 4 (Phase 1 exit) | Review token budgets, the D1 default numbers, and run the opt-in live read-only tests |
| G2 | After the Phase 2 exit | Run the opt-in live write check on a disposable folder for `bulk_apply` and `email_rules_apply` |
| G3 | After B8.1 | Run the opt-in live comparison of evaluator vs real rules on a disposable folder |
| G4 | Final | Review the CHANGELOG "Changed" entry; merge and release |

## 3. Wave plan

A **wave** is a set of assignments that can run in parallel once every
earlier wave they depend on is merged. **Assignment** IDs (`W1-A`) name one
agent working a chain of tasks in order. Merge order inside a wave is the
order listed.

Critical path (elapsed, with parallel agents and no review delay): about 32
working days versus about 64 nominal effort days done serially. Review time at
the gates is extra.

| Wave | Assignment | Tasks (in order) | Needs merged | Builder blocks / files touched (likely) |
|---|---|---|---|---|
| **W0** | W0-A | P0.0, P0.2 | none | git; `tests/fixtures/graph/`, `evals/` |
| | W0-B | P0.3, P0.4 | none | docs, measuring script, `CHANGELOG.md` |
| | W0-C | F2.0 | none | new `src/m365_mcp/batch_types.py` |
| **W1** | W1-A | T1.1, T1.2, T1.3, T1.4 | W0 | builder: `email_rule_manage`, `m365_update`, `m365_list`, `m365_search` |
| | W1-B | T2.1 | W0 | builder tier table (about lines 3626, 4056, and admin `toolsets_enabled` enum about 3481); `tools/registry.py`; `server.py`; `.env.example` |
| | W1-C | F1.1 | W0 | `services/mail_folders.py` |
| | W1-D | F3.1 | W0 (F2.0) | new `services/batch_ops.py`; uses `graph.batch` |
| | W1-E | J1 | W0 (F2.0) | `operations.py`, `encryption.py`, new store module |
| **W2** | W2-A | T2.2, T2.3 | W1-A, W1-B | `tests/test_unified_tool_specs.py`; `admin_server_info`; server instructions |
| | W2-B | F1.2, F1.3 | W1-A, W1-C | builder: folder inputs on many tools; handlers |
| | W2-C | F2.1, F3.3 | W1-A, W1-D | builder `$defs`; `resource_cache.py` |
| | W2-D | F3.2, J5 | W1-D, W1-E | `rate_limit.py`; store module |
| | W2-E | A3.1 | W1-A, W1-C | `projections.py`; builder output schemas |
| | W2-F | B6.1, B9.1 | W1-A, W1-C | builder: `email_rule_manage`, `m365_create`; rule and folder handlers |
| **W3** | W3-A | J2, J3, J4 | W2-C, W2-D | executor module; builder: `m365_get`, `m365_delete` (operation) |
| | W3-B | A1.1, A2.1, A4.1 | W1-D, W2-A, W2-E | builder: `m365_list`, `m365_search`, `m365_get`; `cursors.py`; projections |
| **W4** | W4-A | B1.1, B2.1, B3.1 | W3-A, W2-B | builder: `m365_move`, `m365_update`, `m365_delete`; handlers |
| | W4-B | D1.1, D1.2 | W3-B | builder list defaults; projections; `CHANGELOG.md`, ADR |
| **W5** | W5-A | P1.X1, P1.X2, P1.X3 | W3, W4 | tests, docs |
| **W6** | W6-A | A5.1, A5.2 | W5 | new `services/aggregate.py`; builder new tool |
| | W6-B | B4.1, B4.2 | W5 | builder new tools; plan/apply handlers |
| | W6-C | B7.1, B7.2, B7.3, C2.1 | W5 | builder new tools; rules service |
| | W6-D | B8.1 | W5 (A4.1) | new pure evaluator module |
| **W7** | W7-A | P2.X1 | W6-A, W6-B, W6-C | tests, docs |
| **W8** | W8-A | C3.1 | W7 | `errors.py` |
| | W8-B | B8.2, B8.3 | W7, W6-D | builder new tools |
| | W8-C | X1 (calendar), X1 (contacts), X1 (OneDrive) | W7 | builder; one sub-assignment per service if capacity allows |
| **W9** | W9-A | P3.X1 | W8 | tests, docs, measurement |

Notes:

- W6-D (`B8.1`, the evaluator) is a pure module, so it can also start
  earlier, as soon as `A4.1` is merged, if capacity is free.
- Same-wave assignments that both edit the builder are safe only if they
  edit different tool blocks (see the table); if two need the same block, the
  orchestrator serialises them.
- **P0.0 runs first**; nothing else in Wave 0 starts until the integration
  branch exists.
- Cross-cutting tasks (section 4.8) attach to each wave's exit task.

## 4. Tasks

Format: **ID.** Title. **Wave / assignment**, **Needs**, **Effort** (days).
Then description and **Done when**.

### 4.0 Phase 0: groundwork (1.5 days, Wave 0)

- [x] **P0.1 Confirm Q1 to Q5.** Approved 2026-09-27 (section 1).
- [ ] **P0.0 Integration branch.** Wave W0-A. Needs: owner OK to commit the
  three untracked documents. Effort 0.1.
  Create `tool-use-reduction` from the current branch after the owner has
  committed `TOOL_USE_REDUCTION_REQUEST.md` and
  `TOOL_USE_REDUCTION_CHECKLIST.md` (and decided whether to keep
  `CLAUDE_CHAT_WITH_TOOL_RECOMMENDATIONS.md`, 767 KB, in the repository).
  Done when: the branch exists, `git status` is clean, and standard gates pass
  on it before any change.
- [ ] **P0.2 Baseline fixtures.** W0-A. Needs: P0.0. Effort 0.5.
  Add the scenarios of request section 8.1 (catalogue, analyse, rebuild,
  refile 87, backlog about 1,000) as fixtures under `tests/fixtures/graph/`
  and as golden prompts in `evals/`, with today's per-item call counts.
  Done when: a test replays each scenario with today's tools and the counts
  are recorded in the request.
- [ ] **P0.3 Token measurement.** W0-B. Needs: none. Effort 0.25.
  Script the test's estimator per tool and per set; record core 9,448 and
  core plus extended 13,536 as the starting point.
  Done when: a per-tool token table is in the request.
- [ ] **P0.4 ADR and changelog skeleton for D1.** W0-B. Needs: none.
  Effort 0.5.
  Write the decision record for shipping changed list defaults in 1.1.0 (the
  versioning-rule exception), with migration text and the escape hatches.
  Add an unreleased 1.1.0 section to `CHANGELOG.md` with a "Changed" entry.
  Done when: the ADR and entry exist (final numbers are filled by D1.1);
  **G0** review done.
- [ ] **F2.0 Batch result types.** W0-C. Needs: none. Effort 0.25.
  New module `src/m365_mcp/batch_types.py`: the `reason` enum
  (`not_found`, `access_denied`, `throttled`, `conflict`,
  `outcome_unknown`, `invalid`, `too_large`, `skipped`), item result,
  progress and status types (`completed`, `running`, `failed`, `cancelled`,
  `interrupted`), and a `to_dict()` matching request section 6.2. No spec
  change and no FastMCP import.
  Done when: unit tests cover construction and serialisation and the services
  boundary test passes.

### 4.1 Phase 1A: compress and add the `bulk` tier (6.25 days)

- [ ] **T1.1 Selection baseline.** W1-A. Needs: P0.2. Effort 0.5.
  Run the `evals/` golden prompts on the current definitions and save the
  results.
  Done when: baseline tool-selection accuracy is recorded.
- [ ] **T1.2 Compress `email_rule_manage`.** W1-A. Needs: T1.1, P0.3.
  Effort 1.5.
  Share the repeated condition and action lists through `$defs`; tighten
  descriptions but keep "use when / do not use" guidance.
  Done when: schema-validity and `tests/test_unified_tool_specs.py` pass and
  every existing `validation_rules` error text is unchanged.
- [ ] **T1.3 Compress the remaining core and extended definitions**
  (largest first: `m365_update`, `m365_list`, `m365_search`). W1-A.
  Needs: T1.1. Effort 1. Target: T1.2 plus T1.3 reclaim at least 800 tokens
  across core plus extended.
  Done when: reclaimed tokens are recorded per tool.
- [ ] **T1.4 Re-run selection evals.** W1-A. Needs: T1.2, T1.3. Effort 0.5.
  Done when: accuracy is not lower than the T1.1 baseline (restore wording
  until it is).
- [ ] **T2.1 `bulk` toolset plumbing.** W1-B. Needs: P0.1. Effort 1.5.
  Add `bulk` to the builder tier table (`TIER_ORDER`, `tiers`, the
  `admin_server_info` `toolsets_enabled` enum), the registry's toolset
  parsing (unknown values must still fail at startup), `server.py` messages
  and `.env.example`. The tier is empty for now. Default stays `core,extended`.
  Done when: `tests/test_tool_registry.py` proves `tools/list` equals the spec
  for every toolset combination including `bulk`.
- [ ] **T2.2 Budget tests.** W2-A. Needs: T2.1, T1.4. Effort 0.5.
  Add `BULK_TOKEN_BUDGET` (6,000) and combined-set checks to
  `tests/test_unified_tool_specs.py`.
  Done when: core, default and `bulk` budgets each have a passing test.
- [ ] **T2.3 Discovery hints.** W2-A. Needs: T2.1. Effort 0.75.
  One sentence in the server `instructions` about enabling `bulk`;
  `admin_server_info` reports enabled and available toolsets; truncated or
  capped results say so in `summary` only when the tier is off.
  Done when: tests assert each message and that the hint is absent when
  `bulk` is enabled.

### 4.2 Phase 1B: foundations (16 days)

- [ ] **F1.1 Mail folder path resolver.** W1-C. Needs: P0.1. Effort 1.
  `resolve_path()` in `services/mail_folders.py`: split on `/`, walk the
  cached tree, aliases (`inbox`, `sent`, `drafts`, `deleted`, `junk`,
  `archive`, `root`) win, ambiguity raises an error listing candidates. Tests
  first: exact, alias, missing, ambiguous, case, trailing slash, spaces.
  Done when: gates pass and at most one folder-tree read per call is
  asserted.
- [ ] **F1.2 Paths at every mail-folder input.** W2-B. Needs: F1.1, T1.4.
  Effort 1.5.
  `container_id`, `destination_id`, `email_changes.parent`, rule
  `move_to_folder` and `copy_to_folder`. Existing "unknown alias" and
  "folder not found" texts stay exact; add rows for path errors.
  Done when: each input accepts a path in a test and all existing
  validation-rule tests pass unchanged.
- [ ] **F1.3 Contact folder paths.** W2-B. Needs: F1.1. Effort 0.5.
  Done when: tests cover `default` and nested folders.
- [ ] **F2.1 Shared result contract in the spec.** W2-C. Needs: F2.0, T1.4.
  Effort 1.
  `$defs` for the batch result (`status`, `operation_id`, `progress`,
  `retry_after_seconds`, per-item `results`, `next_cursor`, `summary`, the
  `reason` enum) from `batch_types.py`.
  Done when: the schema validates, a hostile Graph error fixture cannot leak
  URLs, codes or request IDs, and the token cost is recorded.
- [ ] **F3.1 Batch engine.** W1-D. Needs: F2.0. Effort 2.
  `services/batch_ops.py` over `graph.batch()`: chunks of 20, per-item
  mapping to the F2.0 types, `dependsOn`, ambiguous outcome for
  non-idempotent writes (never retried), deadline guard.
  Done when: tests cover success, partial failure, 429 on a subset, deadline
  mid-batch and duplicate IDs; the services boundary test passes.
- [ ] **F3.2 Per-item rate accounting.** W2-D. Needs: F3.1. Effort 1.
  `rate_limit.py` `charge(account, kind, n)`: sensitive verbs charge per
  item, the overall bucket per call plus per mutating item; a refused call
  consumes nothing.
  Done when: a 100-item delete against a 20-token bucket is paced (job) or
  refused with a clear size limit, and single-item behaviour is unchanged.
- [ ] **F3.3 Cache invalidation once per batch and at job end**, including
  partial success. W2-C. Needs: F3.1. Effort 0.5.
  Done when: stale entries are gone after a partial failure and other
  accounts are untouched.
- [ ] **J1 Durable operation and plan store.** W1-E. Needs: F2.0.
  Effort 2.5.
  Extend `operations.py` into the generic store (keep `drive_copy` monitors
  working): jobs, plans, a per-item journal, retention (24 h results, 30 min
  plans), a SQLite file encrypted through `encryption.py`.
  Done when: records survive a process restart, expired records are purged,
  and the existing `drive_copy` tests pass unchanged.
- [ ] **J5 Plan store.** W2-D. Needs: J1. Effort 1.
  Create a plan from stored item IDs and the operation (not the filter),
  single use, bound to the account, expires (30 min), records the scope and
  count that `confirm` covers. Apply skips already applied items.
  Done when: tests cover an expired plan, a reused plan, a foreign account and
  a plan applied twice after partial failure.
- [ ] **J2 Hybrid executor.** W3-A. Needs: F3.1, F3.2, J1, F3.3. Effort 2.
  Run for the inline budget (default 20 s, `M365_MCP_INLINE_BUDGET_SECONDS`);
  if unfinished, return `status: running` with an `operation_id` and continue
  on the worker pool (`M365_MCP_MAX_CONCURRENCY`), paced by the rate limiter.
  Same result shape both ways.
  Done when: tests cover a fast call (completed, no ID), a slow call
  (running, ID) and throttling that turns a call into a job.
- [ ] **J3 Status and long-poll.** W3-A. Needs: J2, F2.1. Effort 1.5.
  `m365_get(resource="operation")` accepts `wait_seconds` (cap 30,
  `M365_MCP_WAIT_MAX_SECONDS`), returns progress and `retry_after_seconds`,
  and pages `results` by cursor. Limit concurrent waiters per account.
  Done when: the call returns early on completion, returns at the cap
  otherwise, refuses a foreign account's ID, and its spec token cost fits the
  Q2 caps.
- [ ] **J4 Cancel, restart and single-job rule.** W3-A. Needs: J3.
  Effort 1.5.
  Cancel through `m365_delete(resource="operation")` (Q3): stops between
  chunks, completed items stay done and are reported. On startup, running jobs
  become `interrupted` and are never re-run automatically; resume is explicit
  and skips journalled items. One running job per account and resource
  family; a second call is refused naming the existing job. One audit line per
  job (item counts, outcome, no argument values).
  Done when: crash-injection tests (kill mid-chunk, restart, resume) show no
  item is applied twice.

### 4.3 Phase 1C: reads (8.25 days)

- [ ] **A1.1 `max_items` with internal paging.** W3-B. Needs: F3.1, T2.3.
  Effort 2.
  On `m365_list` and `m365_search`: 1 to 1,000, paging with `$top` and
  `nextLink` (host still verified as in `cursors.py`), stop at the byte cap or
  deadline and return `next_cursor` and `truncated`.
  Done when: tests cover exact, short, size-capped and deadline-capped
  results, and a cursor from one request is rejected on another.
- [ ] **A2.1 `fields` and `preview_chars`.** W3-B. Needs: A1.1. Effort 1.5.
  Allow-list per resource; unknown fields rejected with exact error text;
  `fields="full"` restores the current shape; both are part of cursor binding
  and cache keys.
  Done when: a 1,000-message listing with `fields` fits the byte cap in one
  call (fixture) and validates against `outputSchema`.
- [ ] **A3.1 Richer responses (D5).** W2-E. Needs: F1.1, T1.4. Effort 1.5.
  `folder_path` next to every folder ID on email, email_folder, email_rule,
  contact and contact_folder records using the cached tree (no per-record
  call); rules include `sequence`, `is_enabled` and resolved `folder_path` for
  `move_to_folder` and `copy_to_folder`.
  Done when: a deleted or missing folder gives `folder_path: null` and spec
  examples are updated.
- [ ] **A4.1 Rule listing returns all rules in order in one call.** W3-B.
  Needs: A1.1, A3.1. Effort 0.75.
  Done when: a 120-rule fixture returns in one call in sequence order.
- [ ] **D1.1 Choose the new defaults from measurement.** W4-B. Needs: A2.1,
  P0.4. Effort 0.5.
  Using the P0.2 fixtures, pick the default limit, byte cap, preview length
  and compact field set per resource (goal: at most about 250 characters per
  email record versus about 800). Record the numbers in the ADR.
  Done when: the ADR lists final numbers and measured size per record.
- [ ] **D1.2 Implement the new defaults.** W4-B. Needs: D1.1. Effort 2.
  Raise `limit` default and maximum, add the byte cap, lower the default
  preview, apply the compact default field set; make fields outside it
  optional in **list** `outputSchema` only; `m365_get` unchanged;
  `fields="full"` and `preview_chars=255` restore the old shape. Update
  cache handling and the CHANGELOG "Changed" entry with migration text.
  Done when: tests prove the escape hatches return today's shape, spec
  examples are updated, and the full suite passes with the changed defaults.

### 4.4 Phase 1D: writes (5.5 days)

- [ ] **B6.1 Rule ergonomics.** W2-F. Needs: T1.4. Effort 1.
  `actions_merge` (confirm rule evaluated on the merged result) and a
  validation rule rejecting `sequence` on create and update, pointing to
  `reorder`.
  Done when: a `stop_processing_rules` toggle works without resending
  `move_to_folder` and the `sequence` error text is exact.
- [ ] **B9.1 Create folders by path.** W2-F. Needs: F1.1. Effort 1.
  `m365_create(resource="email_folder")` accepts a path and `create_parents`.
  Done when: `A/B/C` creates only missing levels and repeating the call is a
  no-op returning the same IDs.
- [ ] **B1.1 `m365_move` with `ids`.** W4-A. Needs: J2, J3, F1.2, F3.3.
  Effort 1.5.
  1 to 100 as an alternative to `id` (exactly one of the two), through the
  hybrid executor, per-item results with `new_id`. Exact validation texts for
  both forms; the ambiguous-outcome rule applies per item.
  Done when: 87 moves are one call in a fixture (completed, or job plus one
  status call) and folder-cycle checks still apply for `email_folder`.
- [ ] **B2.1 `m365_update` with `ids`.** W4-A. Needs: B1.1. Effort 1.
  One shared `*_changes` object for many IDs.
  Done when: tests per resource and a partial-failure test pass.
- [ ] **B3.1 `m365_delete` with `ids`.** W4-A. Needs: B1.1. Effort 1.
  The `confirm` gate covers the batch and its error text names the count;
  per-item rate charge.
  Done when: refusal without `confirm` states the item count and the audit
  line shows a mutation flag with no argument values.

### 4.5 Phase 1 exit (1.25 days, Wave 5)

- [ ] **P1.X1 Conformance and budgets.** W5-A. Needs: everything in Phase 1.
  Effort 0.5.
  Token budgets, registry test for every toolset combination,
  `tests/test_sdk_client_conformance.py`, services boundary test.
  Done when: all pass under the Q2 decision.
- [ ] **P1.X2 Measure against the baseline.** W5-A. Needs: P1.X1. Effort 0.25.
  Record real numbers in the "After Phase 1" column of request 8.1.
- [ ] **P1.X3 Docs and security review.** W5-A. Needs: P1.X2. Effort 0.5.
  Regenerate `MCP_SERVER_TOOLS.md`; update `README`, `SECURITY.md` and
  `.env.example` for the new variables (inline budget, wait cap, retention,
  bulk toolset); review confirm gates, rate limit, job and plan access,
  path handling, cursor binding.
  Done when: all standard gates pass. **G1** review by the owner.

### 4.6 Phase 2: `bulk` tier (11 to 15 days, Waves 6 and 7)

- [ ] **A5.1 Aggregation service.** W6-A. Needs: A1.1, F3.1. Effort 2.5.
  `services/aggregate.py`: page the source with `$select` only; group by
  `sender`, `sender_domain`, `day`, `week`, `month`, `folder`, `category`;
  metrics `count`, `first`, `last`, `sample_subjects` (through
  `untrusted.py`), `total_size`; `max_scan` and `truncated`.
  Done when: tests cover multi-page scans, ties, missing sender and time
  zones; a 1,000-message fixture aggregates in one call.
- [ ] **A5.2 `m365_aggregate` tool.** W6-A. Needs: A5.1, T2.2. Effort 1.
  Spec, `outputSchema`, examples, token cost within the `bulk` budget.
  Done when: spec, registry and budget tests pass.
- [ ] **B4.1 `bulk_plan`.** W6-B. Needs: J5, A1.1, T2.2. Effort 1.5.
  Filter-driven move, update or delete: resolve the filter to item IDs,
  store a plan with count and sample, perform no writes; `max_items` cap.
  Done when: a dry run performs no writes (asserted on the Graph mock) and
  the plan holds IDs, not the filter.
- [ ] **B4.2 `bulk_apply`.** W6-B. Needs: B4.1, J2, J3. Effort 1.5.
  Execute a stored plan through the hybrid executor; requires `confirm`
  (error names the plan's count); highest safety level of the operation;
  `destructiveHint` when it deletes.
  Done when: applying a plan moves exactly the planned IDs even when new
  matching mail arrived, a second apply is a no-op, and refusal without
  `confirm` is tested.
- [ ] **B7.1 `email_rules_export`.** W6-C. Needs: A4.1, A3.1, T2.2.
  Effort 1.5.
  Declarative format (stable key, name, conditions, actions with folder
  paths, enabled), ordered.
  Done when: export then apply on an unchanged mailbox yields an empty plan.
- [ ] **B7.2 Rule diff engine.** W6-C. Needs: B7.1. Effort 2.
  Pure function: desired list plus current list to creates, updates, deletes,
  folder creates and the minimal PATCH sequence renumbering.
  `delete_unlisted` off by default.
  Done when: property tests show applying a plan reaches the desired order
  and applying twice is a no-op.
- [ ] **B7.3 `email_rules_apply`.** W6-C. Needs: B7.2, B9.1, J2, J5.
  Effort 3.
  Plan mode returns a `plan_id`; apply mode takes it; `create_missing_folders`
  (uses B9.1); rules quota check reported before writing; confirm on any
  resulting forward, redirect or delete and on `delete_unlisted`; verified
  final state and rule order echoed. Runs through the hybrid executor.
  Done when: plan performs no writes, apply verifies by re-reading, a partial
  failure returns per-item results with the current order, and a forward rule
  is never changed without `confirm`.
- [ ] **C2.1 State echo.** W6-C. Needs: B7.3, B1.1. Effort 0.5.
  Batch, reorder and apply results include the resulting state (rule order,
  new IDs).
  Done when: the schema and tests cover it.
- [ ] **B8.1 Rule predicate evaluator.** W6-D. Needs: A4.1. Effort 3.
  Pure client-side evaluation of predicates that can be matched exactly
  (sender, recipient, subject, body, body-or-subject, header, categories,
  importance, attachments); anything else raises `unsupported predicate`
  naming it. AND across conditions, OR within a list, exceptions,
  stop-processing.
  Done when: table-driven tests cover each predicate and exception. **G3**:
  the owner runs the opt-in live comparison on a disposable folder.
- [ ] **P2.X1 Conformance, budget and baseline.** W7-A. Needs: A5.2, B4.2,
  C2.1. Effort 1.
  Full gates, `bulk` budget, "After Phase 2" column of request 8.1 measured,
  security review as P1.X3.
  Done when: all standard gates pass. **G2**: the owner runs the opt-in live
  write check on a disposable folder.

### 4.7 Phase 3 (9 to 13 days, Waves 8 and 9)

- [ ] **C3.1 Error `reason` and `retryable`** on single-item errors, in the
  `ToolError` text, with `mask_error_details` unchanged. W8-A. Needs: P2.X1.
  Effort 1.
  Done when: each mapped error class has an exact-text test and a regression
  test proves no code or URL leaks.
- [ ] **B8.2 `email_rules_test`.** W8-B. Needs: B8.1, T2.2. Effort 1.
  For message IDs or a folder, return the first firing rule and later rules
  that matched but were stopped; read-only.
  Done when: fixtures reproduce the accidental-AND and last-match-wins
  problems from the chat.
- [ ] **B8.3 `email_rules_run`.** W8-B. Needs: B8.2, B4.2. Effort 1.5.
  Dry run (default) evaluates and stores a plan of the resulting moves;
  `bulk_apply` executes it.
  Done when: the plan lists exactly what the evaluator decided and the apply
  moves exactly that.
- [ ] **X1 Cross-service extensions.** W8-C. Needs: P2.X1 (F3.1, A5.1, J2).
  Effort 3 (about 1 each). Three independent sub-tasks:
  - **X1.cal** `ids` on event update and delete; `max_items` and `fields` on
    event lists.
  - **X1.con** aggregate by company or domain for contacts.
  - **X1.drv** `ids` batches and aggregate by type and size for OneDrive.
  Done when: each has spec, tests and fixture parity.
- [ ] **P3.X1 Final conformance and measurement.** W9-A. Needs: all of
  Phase 3. Effort 1.
  Full gates, live read-only tests (`M365_MCP_LIVE_TESTS=1`), evals harness,
  the "After Phase 3" column of request 8.1 measured.
  Done when: measured totals are within 25 percent of the estimate or the
  request is updated with real numbers. **G4** final review.

### 4.8 Cross-cutting tasks (attach to each wave's exit task)

- [ ] **X.docs** Only through the builder; regenerate `MCP_SERVER_TOOLS.md`;
  update tool counts everywhere (`CLAUDE.md`, `.projects/steering/*.md`,
  `index.json`, `README`): the `bulk` tier adds seven tools.
- [ ] **X.audit** Confirm `observability.py` records bulk calls and jobs with
  item counts, never argument values, tokens or URLs.
- [ ] **X.parity** Add `legacy_mapping.json` rows and `test_parity.py`
  coverage only where a legacy name maps to a new tool.
- [ ] **X.steering** Keep `.projects/steering/tool-names.md` in step: new
  tool names follow `[category]_[verb]`, safety metadata and the description
  template. Amend `mcp-server.md` only by referencing the D1 ADR.
- [ ] **X.security** Security review at the end of each phase: confirm gates,
  rate limit, job and plan access, folder path handling, untrusted text in
  aggregates and results, cursor binding.

## 5. Task index (dependency check)

Every task, its wave, what it needs, and effort. A task may start only when
every task in **Needs** is merged into the integration branch.

| Task | Wave | Needs | Days |
|---|---|---|---|
| P0.0 | W0 | owner | 0.1 |
| P0.2 | W0 | P0.0 | 0.5 |
| P0.3 | W0 | | 0.25 |
| P0.4 | W0 | | 0.5 |
| F2.0 | W0 | | 0.25 |
| T1.1 | W1 | P0.2 | 0.5 |
| T1.2 | W1 | T1.1, P0.3 | 1.5 |
| T1.3 | W1 | T1.1 | 1 |
| T1.4 | W1 | T1.2, T1.3 | 0.5 |
| T2.1 | W1 | | 1.5 |
| F1.1 | W1 | | 1 |
| F3.1 | W1 | F2.0 | 2 |
| J1 | W1 | F2.0 | 2.5 |
| T2.2 | W2 | T2.1, T1.4 | 0.5 |
| T2.3 | W2 | T2.1 | 0.75 |
| F1.2 | W2 | F1.1, T1.4 | 1.5 |
| F1.3 | W2 | F1.1 | 0.5 |
| F2.1 | W2 | F2.0, T1.4 | 1 |
| F3.3 | W2 | F3.1 | 0.5 |
| F3.2 | W2 | F3.1 | 1 |
| J5 | W2 | J1 | 1 |
| A3.1 | W2 | F1.1, T1.4 | 1.5 |
| B6.1 | W2 | T1.4 | 1 |
| B9.1 | W2 | F1.1 | 1 |
| J2 | W3 | F3.1, F3.2, J1, F3.3 | 2 |
| J3 | W3 | J2, F2.1 | 1.5 |
| J4 | W3 | J3 | 1.5 |
| A1.1 | W3 | F3.1, T2.3 | 2 |
| A2.1 | W3 | A1.1 | 1.5 |
| A4.1 | W3 | A1.1, A3.1 | 0.75 |
| B1.1 | W4 | J2, J3, F1.2, F3.3 | 1.5 |
| B2.1 | W4 | B1.1 | 1 |
| B3.1 | W4 | B1.1 | 1 |
| D1.1 | W4 | A2.1, P0.4 | 0.5 |
| D1.2 | W4 | D1.1 | 2 |
| P1.X1 to P1.X3 | W5 | all Phase 1 | 1.25 |
| A5.1 | W6 | A1.1, F3.1 | 2.5 |
| A5.2 | W6 | A5.1, T2.2 | 1 |
| B4.1 | W6 | J5, A1.1, T2.2 | 1.5 |
| B4.2 | W6 | B4.1, J2, J3 | 1.5 |
| B7.1 | W6 | A4.1, A3.1, T2.2 | 1.5 |
| B7.2 | W6 | B7.1 | 2 |
| B7.3 | W6 | B7.2, B9.1, J2, J5 | 3 |
| C2.1 | W6 | B7.3, B1.1 | 0.5 |
| B8.1 | W6 | A4.1 | 3 |
| P2.X1 | W7 | A5.2, B4.2, C2.1 | 1 |
| C3.1 | W8 | P2.X1 | 1 |
| B8.2 | W8 | B8.1, T2.2 | 1 |
| B8.3 | W8 | B8.2, B4.2 | 1.5 |
| X1 | W8 | P2.X1 | 3 |
| P3.X1 | W9 | all Phase 3 | 1 |

## 6. Definition of done (release 1.1.0)

- [ ] All phase exits above are ticked and gates G0 to G4 are passed.
- [ ] Every standard gate passes.
- [ ] Token budgets pass for core, default and `bulk` under Q2.
- [ ] `tools/list` equals the spec for every toolset combination.
- [ ] Every new `validation_rules` entry has a test with its exact error
  text; spec examples are fixtures.
- [ ] Job durability tests pass: restart mid-job, cancel, duplicate apply of a
  plan, expired plan, foreign account.
- [ ] The D1 exception is recorded (ADR, CHANGELOG "Changed" entry with
  migration text) and both escape hatches are tested.
- [ ] Apart from D1, no tool, parameter or result field was removed or
  renamed.
- [ ] Bulk write paths verified once by the owner on a disposable folder,
  draft, event and contact; no live write test ran against a real mailbox.
- [ ] Measured call counts are recorded in the request and compared with the
  estimate.

## 7. Effort roll-up

| Phase | Waves | Effort (days) |
|---|---|---|
| 0 Groundwork | W0 | 1.5 |
| 1 Budget, foundations, jobs, reads, batches | W1 to W5 | 32 to 42 (about 37 nominal) |
| 2 `bulk` tier | W6, W7 | 11 to 15 |
| 3 Rule test and run, errors, cross-service | W8, W9 | 9 to 13 |
| **Total effort** | | **54 to 72** |
| **Elapsed with parallel agents** (about 6 in flight) | | **about 32 working days plus review time at G0 to G4** |

The cut line if time is short is Phases 0 to 2 (about 44 to 59 days of
effort); Phase 3 can then ship in 1.2.0.
