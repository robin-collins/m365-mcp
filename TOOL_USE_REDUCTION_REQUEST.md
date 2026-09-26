# Tool-Use Reduction Request

| | |
|---|---|
| **Status** | Approved: decisions D1 to D6 (section 2) and Q1 to Q5 (section 11) recorded; ready for Phase 0 |
| **Date** | 2026-09-27 (revision 3) |
| **Target release** | 1.1.0. Mostly additive, with one owner-approved exception to the versioning rule (D1, section 2) |
| **Source evidence** | `CLAUDE_CHAT_WITH_TOOL_RECOMMENDATIONS.md` (chat "Optimizing M365 email rules", 9 turns) |
| **Companion** | `TOOL_USE_REDUCTION_CHECKLIST.md` (ordered implementation tasks) |

## 1. Summary

An agent used the M365 MCP server to catalogue and rebuild an Inbox ruleset.
It made about 165 server calls and still did not finish: the turn hit the
host's per-turn tool limit several times, four calls timed out after 4 minutes,
and one returned an internal error. About 140 of the calls were single-item
mutations that a batched or declarative interface would have folded into a
handful of calls.

The agent's recommendations focus on mail rules, but every pattern behind them
is generic: **one call per item, no server-side paging, no way to ask for
counts, opaque IDs that need a lookup, and no way to preview or verify a bulk
change**. This document assesses the recommendations, generalises them across
all services, and sets out how to deliver them.

The design rests on five decisions (section 2):

1. **Compress the existing tool definitions** to free token budget (D2).
2. **Split the surface.** Small optional parameters go on existing core and
   extended tools; the heavy tools go in a new opt-in **`bulk` tier** (D3).
3. **One execution model for every bulk write: hybrid inline-then-job, with
   a long-poll status call and plan/apply** (D4). Small work returns results
   at once; anything slower returns a job ID that the agent checks once.
4. **Better defaults**: compact lists and more items per page (D1).
5. **Richer responses**: paths, resolved names and rule sequence in every read
   so no lookup calls are needed (D5).

**Estimated effort:** 54 to 72 working days across four phases (section 8).
Phases 0 to 2 (about 44 to 59 days) deliver most of the call savings seen in
the chat. Phase 1 is large because the job and plan store, the `bulk` tier
plumbing, definition compression and the new list defaults all land in it.

## 2. Decisions recorded

| ID | Decision | Alternatives rejected | Consequence |
|---|---|---|---|
| D1 | **New list defaults ship in 1.1.0**: compact default fields and a larger default page. | Additive-only until 2.0 (recommended by the assistant); an env switch. | This is a **breaking change** under the project's own rule (`CLAUDE.md`, `mcp-server.md`: changing a default or removing a default result field is major-version only). The owner has accepted it for 1.1.0. It must be recorded as an explicit exception: a `CHANGELOG.md` "Changed" entry with migration notes, an ADR, escape hatches to restore the old shape (D1 detail below), and the version label stays 1.1.0 (Q1, approved). |
| D2 | **Compress existing definitions** first (option B). | Raising the caps; deferred tool loading only. | Editing work on `email_rule_manage` (2,059 tokens) and on the repeated condition lists; must be checked with the `evals/` harness so tool selection does not degrade. |
| D3 | **Split: light parameters in core/extended, heavy tools in a new opt-in `bulk` tier.** | Everything in `bulk`; everything in existing tiers. | Basic batching (`ids`, `max_items`, `fields`, paths, job status) works on a default install. Heavy tools cost nothing unless enabled. Needs a fourth toolset value, its own token budget, and a way to tell the agent the tier is missing. |
| D4 | **Hybrid execution plus long-poll plus plan/apply** (options 3, 4 and 5 combined). | Sync-only batches; always-async. | One result shape everywhere; a job and plan store is a Phase 1 foundation, not a Phase 3 retrofit. |
| D5 | **Richer responses** (`folder_path`, sequence and resolved names in every read). | None. | Additive. Removes a whole class of lookup calls and the ID-mapping error seen in the chat. |
| D6 | **Job store and status long-poll move to Phase 1.** | Keep in Phase 3. | Phase 1 grows about 4 days; no batch tool is retrofitted later. |

### D1 detail: what changes

| Item | Today | New in 1.1.0 |
|---|---|---|
| `m365_list` `limit` | default 20, maximum 50 | default and maximum raised (target default 200, maximum 200), always bounded by a response byte cap (below) |
| Response size | none | byte cap (initial target 64 KB, tunable); when reached the result is truncated with `next_cursor` and `has_more` |
| Email preview | `PREVIEW_MAX_CHARS` 255 in every list record | default lowered (initial target 80, to be set from measurement) |
| Default fields in list records | full summary (about 800 characters per email in the chat) | compact default set per resource, chosen from measured projections (goal: at most about 250 characters per email record) |
| Restoring the old shape | n/a | `fields="full"` and `preview_chars=255` (explicit, per call) |
| `m365_get` | full record | unchanged |
| `outputSchema` | all fields required | fields outside the compact set become optional in **list** results only |

The exact numbers are set in checklist task D1.1 from measurements of the
recorded scenarios, not guessed here.

## 3. Evidence from the chat log

### 3.1 Where the calls went

| Task | Calls | Cause |
|---|---|---|
| Catalogue rules (repeated 3 times) | ~8 | Rules paged at 50; rules carry opaque folder IDs, so the agent fetched the folder tree and mapped IDs by hand. One mapping error mislabelled a rule. |
| Analyse July to September inbox | 5 pages, sampled only | ~1,000 messages at 50 per page, ~800 characters each (mostly preview and ID). The agent sampled three windows instead of covering all. |
| Rebuild rules | ~80 updates, ~30 reorders, 9 creates, 2 deletes | One rule per call. `update` replaced `actions` wholesale, so adding `stop_processing_rules` meant resending `move_to_folder`. Ordering took one move per rule. |
| Folder preparation | 7 | Separate create and rename calls before rules could reference folders. |
| Refile Client_Work | 2 lists + 87 moves (11 done) | One message per move. |
| Error recovery | 4 timeouts, 1 internal error | After a timed-out move, no cheap way to know whether it applied; the verifying read also timed out. |

### 3.2 Failure modes observed

1. **Turn budget exhaustion.** The dominant failure. Work stopped mid-refile
   (11 of 87 moved) and the backlog of ~1,000 messages was never attempted.
2. **Timeouts and a hung connector.** A folder rename timed out, likely on a
   host approval prompt, and a later move and read both timed out after
   4 minutes. The agent stopped. `m365_move` already says an ambiguous
   failure is not retried and to check the destination, but the agent has no
   cheap way to make that check.
3. **Opaque error.** "An unexpected internal error occurred. Retrying is
   unlikely to help" gave no cause.
4. **Silent-ignore trap.** `sequence` on rule create or update is ignored;
   the agent found this from the response.
5. **Manual mapping errors.** Hand-mapping folder IDs to names produced a
   mislabelled rule.

## 4. Root-cause patterns (generalised)

| # | Pattern | Seen in the chat | Same pattern elsewhere in this server |
|---|---|---|---|
| P1 | One call per item for writes | 87 moves, ~80 rule updates | Contacts, events, OneDrive moves and deletes, email flags, categories, read state |
| P2 | No server-side paging; page cap 50 | Rules, inbox listing | Every `m365_list` and `m365_search` resource |
| P3 | Heavy default projection | 800 characters per message | Emails, drive items, contacts |
| P4 | Counts need a full scan | Quarter inbox analysis | Sender stats, largest OneDrive files, events per organiser |
| P5 | Opaque IDs need a lookup | Folder ID mapping | `container_id`, `destination_id`, `parent`; OneDrive already has `path`, mail and contact folders do not |
| P6 | Imperative writes for a declarative goal | Rule rebuild | Folder trees, categories, any "make X look like Y" job |
| P7 | No preview or verify for bulk change | Ordering bugs found by inference | Any filtered bulk move or delete |
| P8 | Long jobs cannot outlive the request | 4-minute timeouts | Bulk moves, large copies, large deletes |
| P9 | Ambiguous outcome after failure | Timed-out move and reorder | Every non-idempotent write |

## 5. The agent's recommendations, assessed

| # | Recommendation | Verdict | Assessment |
|---|---|---|---|
| R1 | Declarative rule sync (`email_rules_apply`, `email_rules_export`) | Adopt, in `bulk` tier | Biggest single saving (about 120 calls to 2). Uses the shared plan/apply model (D4): plan returns a `plan_id`; apply executes exactly that plan. `delete_unlisted` off by default. |
| R2 | Folder paths wherever a folder ID is accepted, plus `folder_path` in results | Adopt (D5), generalise | Prerequisite for R1 and cheap. Extend to contact folders. |
| R3 | Batch mutations (`ids`, batch rule ops) | Adopt in core/extended (`ids`); rule batch stays internal | `graph.batch()` exists (20 per `$batch`, non-idempotent writes never retried). The imperative rule-batch action is dropped as a public surface because `email_rules_apply` supersedes it and it would cost tokens. |
| R4 | `fetch_all` and `fields` projection | Adopt as `max_items` plus `fields` plus D1 defaults | An unbounded `fetch_all` conflicts with output size and deadlines. Use a bounded `max_items` (cap 1,000) with a cursor when truncated. |
| R5 | `email_stats` aggregation | Adopt in `bulk` tier | Graph has no group-by for mail, so the server pages and aggregates. One model call, several Graph calls, bounded by `max_scan`. |
| R6 | `email_rules_test`, `email_rules_run` | Adopt, staged, `bulk` tier | Highest risk: Graph has no "run rules now", so the server re-implements Exchange predicate evaluation. Ship `test` first, restricted to predicates we can evaluate exactly. `run` produces a `plan_id`, applied through the shared plan/apply path. |
| R7 | Patch semantics for rule updates; honour or reject `sequence` | Adopt, small | A bug-class fix: reject `sequence` on create and update with a message that points to `reorder`; add `actions_merge`. |
| R8 | Idempotency, async bulk, error detail | Adopt (D4, D6) | Async is now the shared job model. Errors carry a coarse `reason` and `retryable` flag, not Graph codes (project rule: no URLs, codes or request IDs). |

## 6. Proposed design

Principle: **extend existing tools with small optional parameters first**; add
a tool only where intent, safety, confirm rule, retry semantics or result
shape differ (`tool-names.md`). Everything stays spec-first: edit
`scripts/build_unified_tool_specs.py`, regenerate, then implement.

### 6.1 Token budget and the `bulk` tier (D2, D3)

**Why a budget exists.** Every tool definition (name, description, schema)
is sent to the model each session, used or not. The caps of 10,000 (core) and
14,000 (core plus extended) are this project's own limits in
`tests/test_unified_tool_specs.py`, not MCP limits. Measured today with the
test's own estimator (JSON characters divided by 4):

| Set | Now | Cap | Headroom |
|---|---|---|---|
| core | 9,448 | 10,000 | 552 |
| core + extended | 13,536 | 14,000 | 464 |
| `email_rule_manage` alone | 2,059 | | (largest tool) |
| `m365_list` | 940 | | |

**Step 1: compress (D2).** Reuse `$defs` for the repeated condition and action
lists in `email_rule_manage`, tighten descriptions without losing the
"use when / do not use" guidance, and drop redundant text. Target: reclaim at
least 800 tokens in core plus extended before any new parameter is added.
Gate: run the golden prompts in `evals/` before and after; tool-selection
accuracy must not fall.

**Step 2: light additions in core and extended.** Only small optional
parameters, budgeted per parameter (target under 350 tokens in total):

| Where | Parameters |
|---|---|
| `m365_list`, `m365_search` | `max_items`, `fields`, `preview_chars` |
| `m365_move`, `m365_update`, `m365_delete` | `ids` (1 to 100) alongside `id` |
| Every mail-folder input | paths accepted as values (no new parameter) |
| `m365_get(resource="operation")` | `wait_seconds` (cap 30), result paging |
| `m365_delete(resource="operation")` | cancel a running job (Q3, approved) |
| `email_rule_manage` | `actions_merge`, `sequence` rejected |

**Step 3: heavy tools in a new opt-in `bulk` tier.** Selected with
`M365_MCP_TOOLSETS=core,extended,bulk`; not in the default set. Tools:

| Tool | Purpose |
|---|---|
| `bulk_plan` | Dry run of a filter-driven move, update or delete; returns a `plan_id`, matched count and sample |
| `bulk_apply` | Execute a stored `plan_id` (requires `confirm`) |
| `m365_aggregate` | Counts and groupings over a large set (mail first) |
| `email_rules_export` | Current ruleset in declarative form |
| `email_rules_apply` | Plan or apply a whole ruleset (returns or takes a `plan_id`) |
| `email_rules_test` | Which rule fires for given messages |
| `email_rules_run` | Evaluate rules over a folder and produce a `plan_id` for `bulk_apply` |

A new `BULK_TOKEN_BUDGET` test (initial target 6,000 tokens) and combined-set
budget checks are added; the existing core and default caps stay unless a
measured case justifies a change (Q2).

**Telling the agent when the tier is missing.** The failure mode of an opt-in
tier is silence. Mitigations, all cheap: (a) one sentence in the server
`instructions` ("for large or repeated changes enable the `bulk` toolset");
(b) `admin_server_info` reports enabled and available toolsets; (c) the
result of a request that had to be truncated or capped says so in its
`summary` ("500 more; enable the bulk toolset for batch tools" only if the
tier is off).

Alternatives considered: raising caps (every user pays forever and the cap
loses meaning), everything in `bulk` (the default install cannot batch and the
original problem remains), on-demand schema discovery (adds a call, weakens
validation), relying only on the host's deferred tool loading (helps one
host).

### 6.2 Execution model: hybrid inline-then-job, long-poll, plan/apply (D4)

One model for every bulk write (`ids` batches, `bulk_apply`, `email_rules_apply`).

**Instant when small, a UUID when not.** The server starts the work and waits
for an **inline budget** (default 20 s). If it finishes, the result is returned
directly. If not, the call returns at once with an `operation_id` (UUID v4)
and the work continues in the background. The decision is by elapsed time, not
item count, because item count predicts duration badly under throttling.

**One result shape in both cases:**

```jsonc
{
  "status": "completed" | "running" | "failed" | "cancelled" | "interrupted",
  "operation_id": null | "3f9c…",        // set only while a job exists
  "progress": { "total": 87, "done": 87, "failed": 3 },
  "retry_after_seconds": null | 20,      // when running
  "results": [ { "index": 0, "id": "…", "ok": true, "new_id": "…" },
               { "index": 1, "id": "…", "ok": false,
                 "reason": "not_found", "retryable": false } ],
  "next_cursor": null,                   // pages `results` when large
  "summary": "84 of 87 moved, 3 failed"
}
```

`reason` is a small enum (`not_found`, `access_denied`, `throttled`,
`conflict`, `outcome_unknown`, `invalid`, `too_large`, `skipped`); no Graph
URLs, codes or request IDs. Partial failure is normal: the call succeeds if
the batch ran.

**Long-poll status.** `m365_get(resource="operation", id, wait_seconds=N)`
holds until the job finishes or `N` seconds pass (cap 30, so it stays well
under host call timeouts of a few minutes). Usually one status call is
enough, so the whole flow costs about two calls instead of a polling loop.
`retry_after_seconds` tells the agent when checking again is worthwhile.

**Plan/apply.** A dry run (for example `bulk_plan`, `email_rules_apply` in plan
mode, `email_rules_run` with dry run) stores the **exact reviewed change**
under a `plan_id` (UUID v4): the matched item IDs and the operation, not the
filter. `bulk_apply(plan_id, confirm)` then executes precisely that. This
gives four properties: the approval matches what runs; new mail arriving
between review and apply cannot widen the scope; the apply request is tiny;
and apply can be repeated safely because already-applied items are skipped.
Plans are single-use, bound to the account, and expire (default 30 minutes).

**State, resumption and safety:**

| Concern | Design |
|---|---|
| Where a job lives | Graph has no async job for mail moves, so our process runs it. Jobs and plans are kept in a durable store (a SQLite file using the existing key management in `encryption.py`) with a per-item journal. |
| Server restart | Running jobs are marked `interrupted`, never re-run automatically (a non-idempotent write could double-apply). The agent resumes explicitly; the journal skips completed items. |
| Approval | `confirm` covers exactly the plan's stored scope and count; the confirm error text names the count. |
| Rate limits | The job paces itself against the per-account buckets and waits rather than fails; charging is per mutating item (20 sensitive per minute means 1,000 deletes take about 50 minutes, which is a job by design). |
| Concurrency | One running job per account and resource family at a time (a second is refused with the existing job's ID); execution uses the worker pool (`M365_MCP_MAX_CONCURRENCY`). |
| Cancellation | Stops between chunks; completed items stay done and are reported (Q3, approved). |
| Access | Job and plan IDs are unguessable and bound to the account; another account gets not found. Results pass through `untrusted.py`. Retention: results kept 24 hours (configurable). |
| Audit | One audit line per job with item counts and outcome; never argument values. |
| Cache | Invalidated once per batch and again when a job finishes, including on partial failure. |
| Extends | `operations.py` (today `drive_copy` monitor URLs) becomes the generic store; `drive_copy` keeps working unchanged. |

**Alternatives considered.** Sync-only batches fail for large jobs (the
exact failure seen). Always-async doubles the call cost of trivial work and
adds state for it. MCP protocol tasks are a candidate later, but client
support is uneven and the tool-level job ID works everywhere; verify what the
`fastmcp` version in use supports before deciding (Q4, approved).

### 6.3 Reads: defaults, richer responses, aggregation (D1, D5)

| ID | Change | Applies to |
|---|---|---|
| A1 | `max_items` (1 to 1,000) with internal paging, byte cap and deadline guard; `next_cursor` and `truncated` when stopped early | `m365_list`, `m365_search` |
| A2 | `fields` and `preview_chars`; unknown fields rejected; `fields="full"` restores today's shape | `m365_list`, `m365_search`, `m365_get` |
| A3 | **Richer responses**: `folder_path` next to every folder ID; rules include `sequence`, `is_enabled` and resolved `folder_path` for `move_to_folder` and `copy_to_folder`; results never require a follow-up lookup to be meaningful | email, email_folder, email_rule, contact, contact_folder |
| A4 | Rule listing returns all rules in order in one call | `m365_list(resource="email_rule")` |
| A5 | `m365_aggregate` (`bulk` tier): `group_by` in `sender`, `sender_domain`, `day`, `week`, `month`, `folder`, `category`; metrics `count`, `first`, `last`, `sample_subjects`, `total_size`; `max_scan` and `truncated` | email first; drive_item and event later |
| D1 | New default limit, byte cap, preview length and compact field set (section 2) | `m365_list`, `m365_search` |

### 6.4 Writes

| ID | Change | Tier |
|---|---|---|
| F1 | Folder **path** accepted wherever a mail folder ID or alias is accepted (aliases win; ambiguity lists candidates); same for contact folders | core, extended |
| B1 to B3 | `ids` on `m365_move`, `m365_update`, `m365_delete`; shared change object for update; delete's `confirm` covers the batch and names the count; results and jobs per 6.2 | core |
| B4 | `bulk_plan` and `bulk_apply`: filter-driven move, update, delete with `plan_id` | `bulk` |
| B6 | `email_rule_manage`: `actions_merge`; reject `sequence` with a pointer to `reorder` | extended |
| B7 | `email_rules_export` and `email_rules_apply` (plan and apply, `plan_id`, array order defines sequence, minimal PATCH computation, `delete_unlisted` off by default, `create_missing_folders`, rules quota check before writing, confirm on any forward, redirect or delete and on `delete_unlisted`) | `bulk` |
| B8 | `email_rules_test`, `email_rules_run` (dry run produces `plan_id`; applied by `bulk_apply`) | `bulk` |
| B9 | `m365_create(resource="email_folder")` accepts a path and `create_parents` | core |

The imperative rule "batch operations" action from the agent's list is not
exposed: `email_rules_apply` covers it and the schema would cost tokens
without adding capability. The batch engine still runs it internally.

### 6.5 Reliability

| ID | Change |
|---|---|
| C2 | Batch, reorder and apply results echo the resulting state (rule order, new IDs) so an ambiguous outcome can be checked without another read |
| C3 | `reason` and `retryable` also on single-item errors, in the `ToolError` text (no codes or URLs; `mask_error_details` stays on) |
| C4 | Deadline budgeting: bulk handlers never run into the host timeout; work beyond the inline budget becomes a job (6.2) |

### 6.6 Cross-service gains

| Service | Change |
|---|---|
| Calendar | `ids` on event update and delete; `max_items` and `fields` on event lists |
| Contacts | `ids` batches; aggregate by company or domain; `folder_path` for contact folders |
| OneDrive | `ids` batches; aggregate by type and size |
| Mail | Category and read-state bulk updates via `ids` or `bulk_plan` |

## 7. Constraints and dependencies

- **Spec-first workflow**: every change starts in
  `scripts/build_unified_tool_specs.py`; regenerate the docs and the packaged
  copy in `src/m365_mcp/tool_specs/`; update `MCP_SERVER_TOOLS.md` via
  `scripts/generate_tools_doc.py`. `tools/list` must equal the spec for every
  toolset combination, including the new `bulk` tier.
- **Tool counts change**: docs currently say 30 tools (16 core, 7 extended,
  7 admin). The `bulk` tier adds seven tools (`bulk_plan`, `bulk_apply`,
  `m365_aggregate`, `email_rules_export`, `email_rules_apply`,
  `email_rules_test`, `email_rules_run`), so counts in `CLAUDE.md`, steering
  files, `index.json` and `README` must be updated together.
- **Toolset validation**: `M365_MCP_TOOLSETS` fails at startup on unknown
  values; `bulk` must become a known value and be documented in
  `.env.example`.
- **Output contract**: results are validated against `outputSchema`.
  Optional list fields (D1) and the shared batch result need schema updates;
  the audit line records result bytes.
- **Cursors** are bound to account, resource and request. `max_items`,
  `fields` and `preview_chars` become part of the bound request.
- **Cache**: new parameters change cache keys (normalised parameters);
  changed defaults change cached shapes, so existing entries expire
  naturally. Batch mutations invalidate once per batch through
  `resource_cache.MUTATION_INVALIDATES`.
- **Services boundary**: batch, job and aggregation logic lives in
  `services/` (or a top-level module like `operations.py`), never importing
  FastMCP (`tests/test_services_boundaries.py`).
- **Rate limit**: `rate_limit.py` counts per call today; it needs a per-item
  `charge(n)` (a refused call still consumes nothing).
- **Hosts**: `dangerous` and `critical` tools still need host approval;
  `bulk_apply` and `email_rules_apply` inherit the highest safety level of
  what they can do and carry `destructiveHint` when they can delete.
- **Untrusted content**: `sample_subjects`, previews and job results are
  third-party text and go through `untrusted.py`.
- **Legacy parity**: `legacy_mapping.json` and `tests/test_parity.py` need
  rows only where a legacy name maps to a new tool.

## 8. Effort, risk and payoff

Estimates are engineering days for one developer working test-first,
including specs, tests, docs, changelog and lint and type gates.

| Phase | Scope | Effort | Risk | Payoff |
|---|---|---|---|---|
| 0 | Integration branch, baseline fixtures, token measurement, ADR for D1, batch result types | 1.5 | Low | Unblocks design |
| 1 | Compress definitions and `bulk` tier plumbing (D2, D3, about 6 days); paths, result contract, batch engine, rate accounting, job and plan store, hybrid executor, long-poll status, cancel (D4, D6, about 16 days); reads (`max_items`, `fields`, richer responses, D1 defaults, about 8 days); `ids` on move, update, delete, rule ergonomics, folder create by path (about 5.5 days); exit (about 1 day) | 32 to 42 | Medium to high (token budget, breaking defaults, job durability, rate accounting) | About 85 percent of chat calls removed; large jobs survive timeouts |
| 2 | `m365_aggregate`, `bulk_plan` and `bulk_apply`, `email_rules_export` and `email_rules_apply` | 11 to 15 | Medium to high (declarative diffing, quota check, confirm semantics) | Rule rebuild from about 130 calls to 2 or 3; analysis from 5 to 1 |
| 3 | Rule test and run (evaluator), error reasons, cross-service extensions | 9 to 13 | High for the evaluator | Backlog refile in 2 calls; parity across services |
| | **Total** | **54 to 72** | | |

The rule evaluator (B8) is 5 to 7 days of Phase 3 and the piece most likely to
be cut or narrowed: the server must mirror Exchange semantics (AND across
conditions, OR within a list, exceptions, stop processing, message-state
conditions). Ship `test` first, reject unsupported predicates explicitly, and
validate on a disposable folder; live write tests are never run against a real
mailbox otherwise. The cut line if time is short is Phases 0 to 2 (about 44 to 59 days).

### 8.1 Estimated call savings

Recomputed against this chat. "Phase 1" assumes the model composes `ids`
batches and uses long-poll; Phases 2 and 3 assume the `bulk` tier is enabled.

| Task | Calls now | After Phase 1 | After Phase 2 | After Phase 3 |
|---|---|---|---|---|
| Catalogue rules | ~8 | 1 | 1 | 1 |
| Inbox analysis (complete) | 5, sampled | 1 to 2 (defaults, `max_items`, `fields`) | 1 | 1 |
| Rule rebuild with folders and verification | ~130 | ~15 | 2 to 3 (plan, apply, status) | 2 to 3 |
| Refile 87 messages | 89 | 1 to 2 (`ids` in one call, or job plus one status) | 2 (plan, apply) | 2 |
| Backlog of ~1,000 messages | not attempted | ~6 to 10 (paged `ids` jobs) | 3 (plan, apply, status) | 2 to 3 |
| **Total** | **~230** | **~25 to 30 (about 88 percent)** | **~10** | **~8** |

These are estimates until measured: task P0.3 records baselines and each
phase exit re-measures.

## 9. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **New defaults break existing clients (D1)** | High | Medium | Record as a versioning exception (ADR, CHANGELOG "Changed" with migration text); `fields="full"` and `preview_chars=255` restore the old shape; Q1 keeps 1.1.0 |
| Token budget blown | Medium | Medium | Compress first, per-parameter budgets in CI, separate `bulk` budget |
| Opt-in tier goes unnoticed and agents still loop | Medium | Medium | Server instructions sentence, `admin_server_info`, truncation hint in `summary` |
| Job store bugs (lost, duplicated or double-applied work) | Medium | High | Per-item journal; `interrupted` never auto-resumes; single job per account and resource family; idempotent skip of done items; crash-injection tests |
| Bulk tool bypasses the sensitive rate limit | Medium | High | Per-item charging; job paces itself; tested |
| Wrong bulk mutation from a bad filter | Medium | High | Plan stores exact IDs, not the filter; dry run first; `confirm` names the count; sample in the plan |
| Long-poll ties up worker threads | Low | Medium | Cap `wait_seconds` at 30; limit concurrent waiters per account |
| Client-side rule engine diverges from Exchange | High | Medium | Exactly-evaluable predicates only, explicit reject, `test` before `run`, live check on a disposable folder |
| Ambiguous outcome after a timeout | Medium | Medium | `outcome_unknown` reason; state echo (C2); no automatic retry of writes |
| Path ambiguity or folder rename race | Medium | Low | Error lists candidates; resolve and write in one call |
| Result too large | Medium | Medium | Byte cap plus cursor |
| Rules quota exceeded during apply | Low | Medium | Pre-check and report before writing |
| Scope creep into a workflow engine | Medium | Medium | Only add what section 4 patterns justify |

## 10. Success criteria

- Every scenario in 8.1 is a replayable fixture (`tests/fixtures/graph/`) and
  a golden prompt (`evals/`), and meets its call count at the phase exit.
- No new call bypasses `confirm`, the rate limit or audit logging (audit line
  still records tool, outcome, mutation flag; no argument values).
- `tools/list` equals the spec for every toolset combination; token budgets
  pass, including `bulk`.
- Every new `validation_rules` entry has a test with its exact error text.
- The D1 exception is documented (ADR, CHANGELOG, migration note) and the
  escape hatches are tested.
- Job durability tests pass: restart mid-job, cancel, duplicate apply of a
  plan, expired plan, foreign account.
- Live read-only tests pass; bulk writes verified once on a disposable
  folder, draft, event and contact.

## 11. Approved decisions (Q1 to Q5)

Approved by the owner on 2026-09-27. The checklist treats these as fixed.

| ID | Decision |
|---|---|
| Q1 | Version label for D1 stays **1.1.0**, with an ADR and a prominent CHANGELOG "Changed" entry. Revisit only if a known client depends on the old shape. |
| Q2 | Caps stay at 10,000 (core) and 14,000 (core plus extended) after compression, with a separate 6,000-token `bulk` budget. |
| Q3 | Cancel a job with `m365_delete(resource="operation")` (adds one enum value to a core tool). |
| Q4 | MCP protocol tasks are skipped in 1.1.0; revisit after checking the `fastmcp` version's support. |
| Q5 | 20 s inline budget, 30 s maximum wait, 30-minute plan expiry, 24-hour result retention, 100 IDs per `ids` call, 1,000 for `max_items`; all configurable through environment variables. |

## 12. Out of scope

- Changing the host's per-turn tool limit or approval prompts.
- Work and school accounts (still unsupported).
- Removing or renaming any existing tool, parameter or result field
  (D1 changes defaults and default shape only).
- A scripting or workflow tool inside the server.
- Push notifications or delta sync.

## Appendix A. Mapping from the chat's recommendations to work items

| Chat recommendation | Work items |
|---|---|
| 1. Declarative rule sync | B7, F1, B9, C2, plan/apply (6.2) |
| 2. Folder paths everywhere | F1, A3, B9 |
| 3. Batch mutations | B1 to B3, batch engine, job model (6.2) |
| 4. Server-side paging and projection | A1, A2, A4, D1 |
| 5. Aggregation | A5 |
| 6. Rule simulation and run | B8, B4 |
| 7. Patch semantics for rule updates | B6 |
| 8. Reliability | 6.2, C2 to C4 |
| Safety points | 6.2 (plan/confirm/rate/audit), section 9 |
