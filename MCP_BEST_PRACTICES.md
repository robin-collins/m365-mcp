# Current Best Practices for MCP Servers — September 2026

I’m approaching this as a protocol and production-systems research analyst, grounding the audit in the current MCP specification and primary OpenAI, Anthropic, and Google documentation rather than claiming first-hand deployment credentials.

## Executive findings and source freshness

The most important conclusion is that **a good MCP server is no longer just a clean JSON-RPC wrapper around an API**. The server surface is part API contract, part prompt: tool names, descriptions, schemas, inventory size, ordering, and returned context all directly affect whether a model discovers the right tool, chooses it, supplies valid arguments, and completes the task economically. Anthropic explicitly frames tools as a contract between deterministic software and nondeterministic agents and reports material gains from evaluation-driven refinement of tool definitions. OpenAI similarly recommends intent-oriented descriptions, explicit inputs, stable names, and golden-prompt evaluation; Google recommends clear descriptions, strong typing, validation, and an active tool set of roughly 10–20 tools. citeturn16view0turn12view2turn12view4turn21view0

For an existing server that already works, the highest-return improvements are therefore usually:

**First**, reduce ambiguity in the exposed tool surface: distinct names, explicit selection boundaries, strongly constrained parameters, and fewer simultaneously visible tools. **Second**, make results smaller and more structured, with filtering/pagination and useful identifiers only where downstream calls need them. **Third**, stabilize tool definitions and ordering so provider prompt caches and MCP tool-list caches work. **Fourth**, harden execution with server-side validation, authorization on every call, actionable model-visible errors, retry-safe mutation semantics, deadlines, and audit logging. **Fifth**, test separately against OpenAI, Anthropic, and Google because their remote-MCP transports, discovery controls, caching, approval facilities, and feature coverage differ materially. citeturn22view0turn17view1turn10view1turn16view2turn21view1

The primary-source baseline used here is:

| Source | Freshness/status as of Sep. 25, 2026 | Significance |
|---|---|---|
| **MCP Specification 2026-07-28** | Published July 28, 2026; current stable revision exposed by the official documentation | Normative protocol baseline. The 2026 revision uses stateless, self-contained requests and per-request protocol/capability metadata rather than relying on legacy connection initialization. citeturn2view0turn3view0 |
| **Anthropic engineering guidance** | “Writing effective tools for agents” published Sep. 11, 2025; current Claude Platform MCP docs retrieved Sep. 25, 2026 | Best primary source here for empirical tool ergonomics, granularity, responses, and evaluation. Anthropic's MCP connector remains explicitly **Beta**. citeturn16view0turn16view1 |
| **Anthropic Sep. 2026 APIs** | `mcp-client-2026-09-15` and `inline-tools-2026-09-15` are current beta surfaces; release notes document recent MCP tool-list pinning and in-conversation tool changes | Important but **experimental/Beta**, not portable MCP behavior. citeturn16view2turn16view3 |
| **OpenAI MCP/tool docs** | Current documentation retrieved Sep. 25, 2026 | Current Responses API behavior for remote MCP, approvals, `allowed_tools`, list reuse, and deferred loading. citeturn8view0turn10view1turn10view2 |
| **OpenAI prompt-caching guidance** | Published Sep. 22, 2026 | Extremely current, but its specific cache numbers and recommendations are **OpenAI/GPT-6-specific**, not MCP requirements. citeturn10view0 |
| **Google Gemini API docs** | Live documentation retrieved Sep. 25, 2026; the retrieved page did not expose a publication/update date, so no date is inferred | Current Remote MCP constraints, function declaration guidance, tool-count recommendation, and Gemini caching behavior. citeturn20view0turn20view2 |

A particularly important 2026 migration issue is that **the newest MCP specification and real client implementations are not perfectly synchronized**. The 2026-07-28 protocol revision moved to self-contained requests with protocol version/client capability metadata on every request, while some official SDK documentation still describes or defaults to the legacy initialization-era behavior unless modern support is explicitly selected. Treat “supports MCP” and “supports MCP 2026-07-28 semantics” as separate compatibility assertions and test both when legacy clients matter. citeturn2view0turn2view1turn0search0turn0search6turn0search10

## Protocol baseline

The following items are **MCP requirements or recommendations**, not vendor advice.

The 2026-07-28 Tools specification requires a server advertising the `tools` capability to answer `tools/list`; tools have unique names, a human-readable description, and a valid JSON Schema `inputSchema`. Unless `$schema` says otherwise, MCP interprets tool schemas as JSON Schema 2020-12. `outputSchema` is optional but, when supplied, server-produced `structuredContent` **MUST** conform and clients **SHOULD** validate it. For backward compatibility, the specification says structured results should also have a serialized representation in a text content block. citeturn22view0

MCP's own naming rules are intentionally broad: tool names **SHOULD** be 1–128 characters, case-sensitive, unique within a server, and limited to ASCII letters, digits, `_`, `-`, and `.`. Because uniqueness is only server-local, an aggregator may need to disambiguate identically named tools from several servers. These are protocol constraints, not a claim that every permitted naming pattern is equally model-friendly. citeturn22view0

The current specification also contains an unusually useful caching recommendation: a server's tool list **SHOULD be returned in deterministic order**, because stable ordering enables reliable client caching and improves LLM prompt-cache hit rates. `tools/list` supports pagination and cache metadata such as `ttlMs` and `cacheScope`. The available tool set may legitimately vary with the authorization presented on the request, but should not drift because of arbitrary per-connection state. citeturn22view0

This matters because the 2026 protocol is explicitly **stateless/self-contained at the base-protocol level**. Do not make correct tool behavior depend on “the previous call happened on this socket.” The Tools specification's non-normative guidance says stateful workflows should return an explicit opaque handle, such as `basket_id`, and require it on later calls. Authorization should then be checked against that handle on every subsequent request. citeturn2view0turn22view0

For tool failures, MCP distinguishes two categories. Malformed JSON-RPC requests, nonexistent tools, and protocol/server failures are JSON-RPC errors. Errors the model can potentially correct—invalid dates, out-of-range values, upstream API failures, business-rule failures—should normally be **tool execution errors**, with `isError: true` and actionable content that can be shown to the model. Clients are explicitly encouraged to provide those execution errors to models so they can self-correct. citeturn22view0

Security requirements are stronger than many early MCP implementations assumed. The current Tools specification says servers **MUST validate all tool inputs, implement proper access controls, rate-limit invocations, and sanitize tool outputs**. Clients should validate results, impose timeouts, log tool usage, show sensitive inputs before sending them, and ask for confirmation on sensitive operations. Tool annotations are explicitly untrusted unless the server itself is trusted. citeturn22view0turn2view0

The standard 2026 transports are **stdio** and **Streamable HTTP**. Stdio remains appropriate for a host-launched local process. Streamable HTTP uses an MCP HTTP endpoint with POST and, where relevant, request-scoped SSE streaming. Custom transports are permitted. The contemporary protocol carries required MCP metadata—including protocol version and client capabilities—with each request; this is a major distinction from the older initialization/connection-state model. citeturn2view1turn2view0

Long-running work needs special care. The 2026 specification family includes **Tasks** for asynchronous operations, polling, durable handles, and further interaction, but Tasks are an optional extension rather than something you can assume every MCP client supports. For clients without Tasks support, a portable fallback is an application-level `start_*` → explicit `operation_id` → `get_*_status`/`cancel_*` workflow rather than holding an HTTP request open indefinitely. That fallback also fits MCP's statelessness guidance. citeturn2view0turn0search8turn22view0

One piece of older MCP advice should now be treated cautiously: official SDK material marks **legacy Sampling as deprecated from the 2026-07-28 era**. New cross-provider servers should not make core workflows depend on server-initiated sampling behavior, especially because the managed OpenAI, Anthropic, and Google remote-MCP products discussed below are primarily tool surfaces rather than full implementations of every MCP feature. citeturn0search12

## Tool design and model usability

The strongest cross-provider rule is: **design tools around user intents, not around your underlying REST endpoints**.

Anthropic reports that blindly exposing every API operation gives agents too many overlapping affordances and consumes context. It recommends a smaller set of high-impact tools and gives examples such as replacing `list_users` + `list_events` + `create_event` with a workflow-oriented `schedule_event`, or replacing `read_logs` with `search_logs` that performs filtering before returning data. citeturn17view0

OpenAI's current connector/tool-design guidance adds the balancing principle: combine operations that represent one coherent user action, but **split operations when permissions, safety risks, or confirmation requirements differ**. It also recommends separating reads and writes where those boundaries matter. citeturn12view2

Those positions are complementary rather than contradictory. A good rule for an existing MCP server is:

> **One tool should usually represent one recognizable user intent and one risk/permission boundary.**

Thus “find mutually available time and schedule this meeting” may be a useful workflow tool, while “search calendar” and “delete calendar” should not be merged merely to reduce tool count. citeturn17view0turn12view2

**Names should encode domain and action clearly.** Anthropic found namespacing valuable where agents can see hundreds of tools, with examples such as `asana_projects_search` and `jira_search`; it also found that prefix versus suffix choices can measurably affect evaluations and says the best arrangement is model-dependent. OpenAI recommends stable, action-oriented names, while Google's generic function-calling guidance recommends descriptive names without spaces or special characters and documents underscore/camel-case names. citeturn17view0turn12view2turn21view0turn21view2

For **maximum OpenAI/Anthropic/Google portability**, I would therefore favor lower-case snake case such as:

`calendar_search_events`  
`calendar_create_event`  
`crm_get_customer_context`

rather than relying on every valid MCP character. MCP itself allows `calendar.search-events`, but Google's guidance is stricter and Google's Remote MCP server naming explicitly disallows `-`. Snake case is the least-surprising shared subset. citeturn22view0turn21view1

Descriptions deserve more engineering effort than most servers give them. Anthropic says tool descriptions and specifications are loaded into the agent's context and can collectively steer calling behavior; its practical heuristic is to write them as if onboarding a new employee, making implicit terminology, query syntax, and resource relationships explicit. OpenAI recommends descriptions that explain the user's goal, when the tool should be used, how it differs from neighboring tools, and important prerequisites or limits—not implementation details or a restatement of the name. Google likewise recommends clear, specific function and parameter descriptions. citeturn17view2turn12view2turn21view0

A particularly effective pattern is:

> **“Use this when … Do not use this when … Returns …”**

OpenAI's metadata optimization guidance explicitly recommends “use when” and disallowed-use guidance, while Anthropic's findings show that small wording changes in descriptions can materially change tool-use behavior. citeturn12view4turn17view2

Parameter names should remove inference burden. Anthropic's concrete example is `user_id` instead of ambiguous `user`. OpenAI likewise says not to force the model to guess identifiers, account scope, or other information required for correctness. Google recommends strongly typed parameters and enums. citeturn17view2turn12view2turn21view0

That means an existing schema like this is expensive for the model:

```json
{
  "user": "abc",
  "type": "x",
  "data": {}
}
```

Prefer fields whose semantics are recoverable from the definition itself:

```json
{
  "customer_id": "cus_123",
  "include_recent_orders": true,
  "status": "active"
}
```

and constrain known sets with `enum`, numeric ranges, array item schemas, formats where interoperable, and `additionalProperties: false` where your target clients accept it. OpenAI specifically recommends using enums/object structure to prevent invalid states; Google recommends specific types and enums; MCP requires a valid JSON Schema. citeturn12view9turn21view0turn22view0

**Required fields need one provider caveat.** MCP uses ordinary JSON Schema semantics: only genuinely mandatory fields need appear in `required`. OpenAI's native function-calling **strict mode**, by contrast, recommends that every property be required and that optional values be represented as nullable; this is an OpenAI function-calling constraint/recommendation, not an MCP protocol requirement and should not be blindly copied into a cross-provider MCP schema. Google examples use ordinary `required` subsets. citeturn22view0turn12view10turn21view2

For tool output, prefer **high-signal semantic fields plus the identifiers actually required for follow-up calls**. Anthropic found agents more successful with human-readable names than with opaque UUID-heavy responses, while acknowledging that technical IDs still need to be returned when subsequent tools require them. It suggests selectable concise/detailed result formats in cases where both needs exist. citeturn17view1

For modern MCP, the strongest generic contract is therefore:

1. Declare an `outputSchema`.
2. Return the actual machine-readable value in `structuredContent`.
3. Return a short text representation as a compatibility/model-readable fallback.
4. Do not duplicate a huge structured result into a huge prose rendering. citeturn22view0

Models also need **negative examples** in evaluation, not necessarily in every description. OpenAI recommends golden prompt sets containing direct requests, indirect requests, and prompts where the tool should *not* be used. Anthropic recommends evaluation suites plus held-out cases to prevent optimization against a narrow training set. citeturn12view4turn16view0

For each tool, measure at minimum:

**selection precision**, **selection recall**, **no-tool precision on negative prompts**, **first-attempt schema-valid argument rate**, **task success**, **mean tool calls per successful task**, **error-recovery rate**, **tool-result tokens**, and **end-to-end p50/p95 latency**. Those metrics turn “this description sounds clearer” into a measurable engineering change; the evaluation-driven approach is strongly supported by both Anthropic and OpenAI guidance. citeturn16view0turn12view4

## Token and latency efficiency

There are three separate costs to optimize: **definitions presented to the model, tool-list/discovery round trips, and result context**.

For definitions, the first optimization is not indiscriminate shortening. A tiny but ambiguous description can cost more than a somewhat longer one because it triggers wrong calls, retries, or additional exploration. The right goal is **minimal discriminating information**: enough text to distinguish the tool from competitors, specify important argument semantics, and identify prerequisites—no API-history prose, marketing text, internal architecture, duplicate examples, or fields the model cannot act on. Anthropic explicitly warns that tool definitions consume model context; OpenAI likewise treats imported MCP tool definitions as billable input and recommends reducing the active set where possible. citeturn17view2turn10view1

For large catalogs, all three providers now point toward **smaller active tool sets**, although the mechanisms differ.

Google gives the most explicit generic number: keep the active set to approximately **10–20 tools maximum** for function calling. That is a Google recommendation, not an MCP limit. citeturn21view0

OpenAI's Responses API provides `allowed_tools` for reducing the imported MCP surface and supports `defer_loading: true` with tool search, so individual definitions are brought into model context only when the model decides the server/tool family is relevant. OpenAI explicitly positions deferred loading as a token-saving technique for servers with many functions. citeturn10view1turn10view2

Anthropic's current MCP toolset likewise supports `enabled` controls and `defer_loading`; deferred definitions are used with Anthropic's tool-search machinery. It supports allowlist/denylist patterns and per-tool overrides. citeturn17view3turn17view4

For an existing server, this means **do not delete useful niche tools just to reduce prompt size** if your principal clients can defer or search them. Keep a clean catalog, but expose only the likely subset eagerly.

Tool-list discovery itself should also be cached. The MCP specification recommends deterministic `tools/list` ordering and supports cache metadata. OpenAI says that when the `mcp_list_tools` item remains in Responses API context, the API can reuse it instead of fetching the list again on each turn. Anthropic's new `mcp-client-2026-09-15` beta goes further: when the API fetches a server's list it can return an `mcp_tool_listing` block; if that assistant message is sent back unchanged, subsequent requests use the pinned list instead of contacting the MCP server again. citeturn22view0turn10view1turn16view2

Those optimizations make **schema stability** operationally valuable. Avoid rebuilding semantically identical schemas in nondeterministic property order, changing descriptions on every deployment timestamp, randomly ordering tools, or conditionally deleting definitions when an ordinary permissions/filter mechanism would work. MCP itself calls for deterministic tool ordering. citeturn22view0

Provider prompt caches make the same point more strongly:

**OpenAI:** its Sep. 22, 2026 GPT-6 caching guidance says tool definitions are part of reusable prompt prefixes and recommends keeping tool definitions, schemas, and ordering stable; when possible, control availability via `allowed_tools` or tool choice rather than physically changing the definitions. The same guidance describes GPT-6 shared-prefix caching with a 30-minute eligibility window and potentially large cached-input savings. These timings/economics are **GPT-6/OpenAI-specific**, not MCP properties. citeturn10view0

**Anthropic:** prompt caching hashes the prefix in the order `tools`, then `system`, then `messages`; current Anthropic documentation says a hit requires exact byte-for-byte prefix identity up to the breakpoint. Reordering a tool or changing top-level system content can therefore destroy reuse. Anthropic's new mid-conversation tool-change APIs were specifically designed to alter tool availability without rewriting the early cached prefix, but these APIs are Sep. 2026 **Beta**, not portable MCP features. citeturn16view2turn16view4

**Google:** Gemini's Interactions API has implicit caching enabled for Gemini 2.5-and-newer models, while explicit cache objects are not available through Interactions and require `generateContent`. The current caching page does not make the same explicit tool-order guarantee that OpenAI and Anthropic document, so stable definitions remain a sensible cross-provider practice, but Google's exact caching mechanics should not be inferred from the other providers. citeturn20view2turn21view3

Result size is usually the next major opportunity. Anthropic recommends pagination, range selection, filtering and/or truncation with sensible defaults for tools capable of producing large responses. It reports that Claude Code itself applies a 25,000-token default tool-output limit, but that number is a **Claude Code product behavior**, not a recommended target for an MCP response. Most task-oriented results should be dramatically smaller. citeturn17view1turn17view2

A strong pattern for search/list tools is:

```json
{
  "query": "...",
  "limit": 20,
  "cursor": "...",
  "fields": ["id", "title", "status"]
}
```

returning:

```json
{
  "items": [...],
  "next_cursor": "...",
  "has_more": true
}
```

For an MCP server, note the distinction: protocol-level pagination applies to MCP list operations such as `tools/list`; pagination through your business data is part of **your tool's own schema**. Anthropic's advice on pagination/filtering concerns the latter. citeturn22view0turn17view1

If a result is truncated, say exactly what happened and how the model can retrieve the next or narrower slice. Anthropic specifically recommends that truncation and error messages steer the agent toward narrower searches, filters, or pagination rather than silently cutting output. citeturn17view2

## Reliability and safety

The production server should assume that **model-generated arguments are untrusted input** even when a provider offers constrained function calling. Schema validation is the first layer, not the last. The current MCP specification requires server-side input validation and access control. Google tells applications to validate calls before execution; OpenAI and Anthropic similarly treat model tool use as something the host must mediate rather than as trusted application code. citeturn22view0turn21view0turn10view1

Validation should happen in two phases. First validate the JSON against `inputSchema`; then validate business semantics—for example resource existence, caller ownership, state transitions, monetary limits, supported time ranges, and permission scopes. When business validation fails, return a model-correctable tool execution error instead of an opaque 500 or stack trace. MCP explicitly distinguishes those errors from malformed protocol requests. citeturn22view0

An effective error looks like:

```json
{
  "isError": true,
  "content": [
    {
      "type": "text",
      "text": "end_time must be after start_time. Supply both as RFC 3339 timestamps."
    }
  ]
}
```

rather than:

```text
ValidationException: code=E422 field=3
```

That pattern aligns both with MCP's error semantics and Anthropic's recommendation that validation errors tell the agent specifically how to correct the next call. citeturn22view0turn17view2

**Authorization must be checked at execution time, not inferred from discovery.** MCP allows the visible tool list to vary according to per-request credentials, which is useful for least-privilege discovery, but state-handle guidance still requires checking authorization against the referenced resource on each later call. A tool being visible is not proof that a particular object is accessible. citeturn22view0

For mutations, separate **model retryability** from **transport retryability**. MCP does not provide a generic tool-level idempotency primitive in the current Tools contract. As an application-level production practice, make retry-prone mutations naturally idempotent where possible, or let the caller/harness carry an idempotency token that your backend persists. Do not require the language model to invent a fresh random idempotency value and expect it to remain stable across recovery. This recommendation follows from MCP's stateless request model and explicit-state guidance rather than from a standardized MCP field. citeturn2view0turn22view0

Automatic retries should consequently be conservative: repeat clearly safe reads after transient transport/upstream failures; do not blindly replay a non-idempotent “charge card”, “send message”, “create order”, or “delete resource” after an ambiguous timeout. For ambiguous mutation outcomes, return or expose an operation/resource identifier so the agent can check state before attempting another write. This is an engineering consequence of MCP's statelessness and lack of a generic idempotency contract. citeturn22view0

Use **bounded deadlines** throughout the stack. MCP says clients should impose tool-call timeouts; the server should likewise apply downstream API/database deadlines so an abandoned dependency does not consume workers indefinitely. Long work should move to an asynchronous operation/Tasks-style design rather than simply raising the timeout to several minutes. citeturn22view0turn2view0

For safety-sensitive tools, put boundaries in both metadata and enforcement. Accurate read-only/destructive/open-world annotations can help compatible clients present the right experience, but MCP says annotations must be considered untrusted when the server is untrusted; they are never a substitute for authorization or confirmation. OpenAI's connector guidance specifically recommends `require_approval` and `allowed_tools` for sensitive MCP actions. citeturn22view0turn12view0turn10view2

Treat **tool results as untrusted too**. This is especially important for search, web, email, documents, issue trackers, databases containing user-authored text, or any other tool that can return instructions embedded by someone else. OpenAI explicitly warns that MCP content can contain prompt injections and that URLs surfaced by tool output can be unsafe; its guidance recommends approvals, allowlisting and review/trust boundaries for sensitive integrations. MCP itself tells clients to validate results and servers to sanitize outputs. citeturn10view2turn22view0

Do not “sanitize” by destroying useful user data, however. The practical server-side job is to prevent protocol/content-type confusion, secret leakage, unintended executable markup, forged internal metadata, and oversized pathological responses. Whether natural-language content is trustworthy is a separate model/host security decision.

Finally, instrument the server by **tool and outcome**, not merely HTTP status. At minimum record a correlation/request ID, authenticated principal or tenant identifier in privacy-safe form, tool name, schema/version hash, start/end times, downstream latency, success/error class, retry count, result byte/token estimate, and whether a state-changing action occurred. MCP explicitly recommends client-side tool-use audit logging; equivalent server observability is necessary to run the model-use evaluations discussed above. citeturn22view0

## Provider compatibility

The largest practical trap is treating “MCP-compatible” as a single identical runtime environment.

| Concern | MCP 2026-07-28 | OpenAI | Anthropic | Google |
|---|---|---|---|---|
| **Remote transport** | Standard transports are stdio and Streamable HTTP. citeturn2view1 | Responses API documents remote MCP over **Streamable HTTP or HTTP/SSE**. The SSE compatibility path is provider support, not the current core transport recommendation. citeturn10view1 | MCP connector accepts publicly reachable HTTPS servers using **Streamable HTTP or SSE**; local stdio is not directly connectable. citeturn17view3 | Gemini Remote MCP currently supports **Streamable HTTP only; SSE is not supported**. citeturn21view1 |
| **Local stdio** | Standard transport. citeturn2view1 | Not the remote Responses MCP path. citeturn10view1 | Not supported by direct Messages API MCP connector. citeturn17view3 | Not supported by documented Remote MCP path. citeturn21view1 |
| **Remote feature coverage** | Protocol supports tools plus other capabilities/extensions. citeturn2view0 | Current remote MCP integration is centered on imported tools/list/calls. citeturn10view1 | Connector explicitly says **only MCP tool calls are currently supported** from the wider MCP feature set. citeturn17view3 | Remote MCP is documented as a way of exposing external tools/services through Interactions. citeturn21view1 |
| **Tool subset** | Server may vary inventory by authorization; clients can consume list. citeturn22view0 | `allowed_tools`. citeturn10view1 | `enabled`, allowlist/denylist and per-tool configuration. citeturn17view4 | `allowed_tools` on the remote MCP declaration. citeturn21view1 |
| **Deferred discovery** | Not a base MCP model-context mechanism. | `defer_loading` with OpenAI tool search. citeturn10view2 | `defer_loading` with Anthropic tool search. citeturn17view3 | Current cited guidance instead says keep the active function set around 10–20; no equivalent remote-MCP deferred-loading mechanism is documented in the cited page. citeturn21view0 |
| **Tool-list reuse** | Deterministic ordering + caching metadata. citeturn22view0 | Keep the `mcp_list_tools` item in context to avoid repeated listing. citeturn10view1 | Sep. 2026 **Beta** `mcp_tool_listing` can pin the fetched list across turns. citeturn16view2 | No equivalent behavior is asserted by the cited current Remote MCP page. |
| **Prompt caching** | Not an LLM-provider cache specification; deterministic list order explicitly helps downstream prompt caches. citeturn22view0 | Stable tool schema/order strongly recommended in current GPT-6 caching guidance. citeturn10view0 | Exact byte-for-byte prefix matching; tools precede system/messages in the cached prefix. citeturn16view2turn16view4 | Interactions uses implicit caching on Gemini 2.5+; explicit cache objects require another API. citeturn21view3 |
| **Human approval** | Applications SHOULD keep humans able to deny sensitive calls. citeturn22view0 | Responses MCP defaults toward approval controls and exposes `require_approval`; trusted workflows can selectively skip approvals to reduce latency. citeturn10view2turn9view2 | Connector supports filtering; Managed Agents additionally have permission-policy machinery, but that is an Anthropic product layer rather than MCP core. citeturn17view4turn16view3 | Do not assume an OpenAI-style approval control from Remote MCP itself; Google documents tool choice/`allowed_tools` and says applications should validate calls before execution. citeturn21view0turn21view1 |
| **Naming caveat** | Tool names may contain `_`, `-`, `.` and alphanumerics. citeturn22view0 | Clear/action-oriented names recommended. citeturn12view2 | Namespacing recommended and empirically model-sensitive. citeturn17view0 | Generic functions: descriptive names without special characters; Remote MCP **server names should not contain `-`**, and snake case is recommended. citeturn21view0turn21view1 |

The practical deployment target is therefore **Streamable HTTP first**. It is the current MCP standard remote transport and the only common remote denominator across the three managed provider integrations. Keep legacy SSE only if you have measured clients that still require it. citeturn2view1turn10view1turn17view3turn21view1

Also test protocol-generation compatibility explicitly. A modern 2026-07-28 server must handle the current per-request metadata/capability model; if your client population includes older MCP applications, a compatibility layer for the legacy initialization era may still be necessary because official SDK adoption is not uniform. Do not silently mix connection-scoped assumptions from pre-2026 MCP with the new stateless model. citeturn2view0turn2view1turn0search0turn0search10

Anthropic deserves an additional version warning. Its normal MCP connector documentation is still explicitly **Beta** and notes that `mcp-client-2025-04-04` is deprecated; newer Sep. 2026 capabilities use `mcp-client-2026-09-15`. Tool-list pinning and inline/mid-conversation changes from that newer header should therefore be treated as Anthropic-specific optimizations with fallback behavior, not server requirements. citeturn16view1turn16view2

Google's Remote MCP documentation is stricter on transport than either OpenAI or Anthropic: an SSE-only remote server will work with neither the current MCP common denominator nor Google's Remote MCP integration. Migrating an old SSE server to Streamable HTTP is consequently a high-priority compatibility fix. citeturn21view1turn2view1

## Prioritized audit checklist

The priority order below assumes the server is functionally correct today and the objective is better model use, reliability, cost and latency.

| Priority | Audit recommendation | Expected benefit | Trade-off / scope | How to prove it |
|---|---|---|---|---|
| **P0** | ☐ **Create a real tool-use evaluation suite before refactoring metadata.** Include positive, indirect, ambiguous, competing-tool and “no tool expected” prompts from production logs, with a held-out set. | Prevents subjective metadata tuning; gives selection/argument/task-success baselines. | Universal. Requires test harness and labeled cases. Anthropic and OpenAI both explicitly advocate evaluation-driven tool optimization. citeturn16view0turn12view4 | Track selection precision/recall, no-call accuracy, valid-arguments-first-try, task success, calls/task, tokens and latency before/after. |
| **P0** | ☐ **Remove or redesign overlapping tools. Give every tool a distinct user intent.** | Fewer wrong selections and exploratory calls; smaller tool context. | Universal. Combining too aggressively can create giant “god tools”; preserve separate permission/risk boundaries. citeturn17view0turn12view2 | Run pairs of prompts that previously confused neighboring tools; measure wrong-tool rate and total calls. |
| **P0** | ☐ **Rename vague tools and parameters. Standardize on stable snake_case for cross-provider exposure.** | Better discovery and argument generation; fewer cross-provider naming surprises. | MCP itself permits more characters; snake_case is a portability recommendation, especially because Google is stricter. citeturn22view0turn17view0turn21view1 | A/B definitions while holding implementation fixed; compare correct-tool and valid-argument rates. |
| **P0** | ☐ **Rewrite descriptions around selection boundaries: what it does, when to use it, when not to, important prerequisites, and what comes back.** | Directly improves model routing. | Universal; avoid bloating descriptions with implementation detail or dozens of examples. citeturn17view2turn12view2 | Use direct/indirect/negative golden prompts and inspect false positives/negatives. |
| **P0** | ☐ **Tighten every `inputSchema`: specific field names/types, enums/ranges where meaningful, no catch-all `data` bags, and only genuinely needed model-supplied inputs.** | Higher first-call validity and less guessing. | Universal MCP JSON Schema. Native OpenAI strict function calling has additional all-required/nullable conventions that are not MCP requirements. citeturn22view0turn12view9turn12view10turn21view0 | Schema-fuzz and model tests; measure validation failures per 1,000 calls and correction turns. |
| **P0** | ☐ **Validate authorization and business constraints server-side on every call and every explicit state handle.** | Prevents cross-user/tenant access and unsafe model-generated mutations. | Universal/non-negotiable. Discovery filtering alone is not authorization. citeturn22view0 | Permission-matrix tests, object-level authorization tests, stale/forged handle tests, tenant-isolation tests. |
| **P0** | ☐ **Classify read/write/destructive behavior accurately and make sensitive mutations approval-friendly.** | Better host UX and lower accidental-change risk. | MCP annotations are hints, not security controls. OpenAI adds `require_approval`; other hosts differ. citeturn22view0turn10view2 | Attempt sensitive tasks under read-only/approval-required configurations and verify no mutation occurs before authorization. |
| **P0** | ☐ **Migrate the remote endpoint to Streamable HTTP if it is SSE-only.** | Gives the broadest current compatibility and aligns with MCP 2026. | Universal remote recommendation. Keep SSE only for measured legacy OpenAI/Anthropic clients. Google Remote MCP does not support SSE. citeturn2view1turn10view1turn17view3turn21view1 | Automated handshake/list/call matrix against OpenAI, Anthropic, Google, and any legacy clients you support. |
| **P0** | ☐ **Make the 2026 request model genuinely stateless. Remove correctness dependencies on connection-local session state.** | Correctness behind load balancers/retries and with current MCP clients. | Modern MCP universal; legacy clients may require a compatibility adapter. citeturn2view0turn22view0 | Route sequential workflow calls to different server instances and verify they still work using explicit handles. |
| **P1** | ☐ **Add `outputSchema` + compact `structuredContent` for important tools, with a concise TextContent fallback.** | More reliable downstream model reasoning and programmatic validation. | MCP universal feature; exact provider surfacing can differ, so retain text fallback. citeturn22view0 | Validate every production result against output schema; compare follow-up-call success and parsing errors. |
| **P1** | ☐ **Put pagination/filtering/range selection on every potentially large-result tool; make narrow output the default.** | Often the largest reduction in token consumption and context pollution. | Universal design recommendation; pagination fields themselves are application-level. citeturn17view1turn17view2 | Log result tokens/bytes and task success; target lower p50/p95 result size without reducing completion rate. |
| **P1** | ☐ **Return semantic labels plus only the opaque IDs needed for follow-up calls.** | Better comprehension without breaking tool chaining. | Universal; purely human-friendly results can make later calls impossible. citeturn17view1 | Test multi-step workflows such as search → inspect → update and measure identifier hallucinations. |
| **P1** | ☐ **Make `tools/list` deterministic and cacheable; do not reorder tools or properties nondeterministically.** | MCP cacheability plus better LLM prompt-cache reuse. | Universal, with especially large gains on OpenAI/Anthropic cached conversations. citeturn22view0turn10view0turn16view4 | Hash serialized tool lists across identical deployments/requests; monitor provider cache-hit metrics. |
| **P1** | ☐ **Reduce the eagerly visible inventory.** Use provider `allowed_tools`/enabled lists; use deferred loading where supported. | Fewer selection collisions, lower input tokens and often lower latency. | Google recommends ~10–20 active functions; OpenAI and Anthropic can defer large catalogs. Provider-specific mechanism, universal objective. citeturn21view0turn10view2turn17view3 | Sweep active-set size and record tool-selection accuracy, input tokens, time-to-first-tool-call and task completion. |
| **P1** | ☐ **Keep definition/schema/order changes out of hot request paths.** | Higher prompt-cache reuse. | OpenAI/Anthropic especially; Google's exact cache-key behavior differs. citeturn10view0turn16view2turn21view3 | Compare cache reads/hits before and after stabilizing serialization; use Anthropic cache diagnostics where relevant. |
| **P1** | ☐ **Turn model-correctable failures into actionable `isError` results. Reserve JSON-RPC errors for protocol failures.** | Lets the model repair arguments rather than terminate/restart the workflow. | MCP universal. citeturn22view0turn17view2 | Deliberately submit invalid dates/enums/IDs and measure successful self-correction within the next call. |
| **P1** | ☐ **Set downstream deadlines and define retry policy per tool. Make mutations retry-safe where feasible.** | Prevents worker exhaustion and duplicate side effects. | Timeouts are MCP-recommended client behavior; idempotency strategy is application-level because MCP has no generic tool idempotency primitive. citeturn22view0 | Fault-inject timeouts, connection resets and duplicate requests; verify reads recover and writes do not duplicate effects. |
| **P1** | ☐ **For long operations, use Tasks only when the client supports it; otherwise return explicit operation handles and status/cancel tools.** | Avoids multi-minute request occupation and ambiguous disconnects. | Tasks are an optional MCP extension; fallback must remain portable. citeturn2view0turn0search8 | Run through supported/unsupported clients; disconnect/reconnect midway and confirm operation state is recoverable. |
| **P1** | ☐ **Sanitize and bound external/untrusted result content and treat returned instructions/URLs as data.** | Reduces prompt-injection, exfiltration and context-abuse risk. | Universal security principle; OpenAI provides particularly explicit MCP warnings. citeturn22view0turn10view2 | Seed retrieved documents with adversarial instructions and unsafe URLs; verify the system does not silently expand permissions or perform unrelated writes. |
| **P2** | ☐ **Exploit OpenAI `mcp_list_tools` reuse and deferred loading when OpenAI is a major client.** | Lower tool-list latency and definition-token cost. | OpenAI-only optimization. citeturn10view1turn10view2 | Compare repeated-turn server-list requests, input tokens and total latency with/without retained list context. |
| **P2** | ☐ **Use Anthropic's Sep. 2026 pinned `mcp_tool_listing`/inline tool-change features only behind an Anthropic-specific adapter.** | Avoids refetching lists and preserves cached prefixes during tool changes. | **Beta**, Anthropic-only. Do not make server correctness depend on it. citeturn16view2turn16view3 | Compare server discovery traffic/cache hits and verify fallback works with the beta disabled. |
| **P2** | ☐ **Continuously test 2026-07-28 and any legacy protocol generation you claim to support.** | Prevents “MCP-compatible” regressions caused by the 2026 architecture change and uneven SDK adoption. | Relevant whenever older clients matter. citeturn2view0turn0search0turn0search10 | CI interoperability matrix that executes discovery, list, call, errors, authorization and stateful workflows under each version/client. |

A useful acceptance criterion is not “all model calls now succeed.” For a mature server, a successful optimization should usually improve **task success or maintain it while reducing one or more of wrong-tool rate, correction turns, tool calls, definition tokens, result tokens, list round trips, or wall-clock latency**. Anthropic's held-out evaluation methodology is especially important because optimizing descriptions against a few remembered prompts can overfit the tool surface. citeturn16view0

## Before-and-after patterns and what requires code or logs

**Tool name**

Ineffective:

```text
get
```

Better but collision-prone across servers:

```text
search
```

Cross-provider-friendly:

```text
calendar_search_events
```

The last form gives the model both a namespace and an action while staying inside the conservative naming subset accepted by current provider guidance. MCP itself permits a wider character set; Anthropic specifically recommends namespacing and Google recommends descriptive names without special characters. citeturn22view0turn17view0turn21view0

**Tool description**

Before:

```text
Gets calendar data.
```

After:

```text
Search calendar events by time range and optional text query.
Use this when the user wants to find or inspect existing events.
Do not use it to create, update, or delete events.
Returns matching event IDs, titles, start/end times, and a pagination cursor.
```

The improved version answers the model's real selection questions: capability, positive trigger, negative boundary, and useful output. That directly follows current OpenAI and Anthropic metadata guidance. citeturn12view2turn17view2

**Input schema**

Before:

```json
{
  "type": "object",
  "properties": {
    "q": {},
    "data": {
      "type": "object"
    }
  }
}
```

After:

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "query": {
      "type": "string",
      "description": "Text to match against event title and description."
    },
    "start_time": {
      "type": "string",
      "description": "Inclusive start of the search window as an RFC 3339 timestamp."
    },
    "end_time": {
      "type": "string",
      "description": "Exclusive end of the search window as an RFC 3339 timestamp."
    },
    "limit": {
      "type": "integer",
      "minimum": 1,
      "maximum": 50,
      "description": "Maximum number of events to return."
    },
    "cursor": {
      "type": "string",
      "description": "Opaque cursor returned by the previous page."
    }
  },
  "required": ["start_time", "end_time"]
}
```

This moves ambiguity from the model into deterministic schema validation, follows Anthropic's advice to use unambiguous parameter names, Google's strong-typing advice, and MCP's JSON Schema contract. For a native OpenAI strict-function wrapper, additional schema transformation may be needed because OpenAI strict mode has different optional-field conventions; do not mutate the canonical MCP contract purely to satisfy that provider-specific mode. citeturn17view2turn21view0turn22view0turn12view10

**Response**

Before:

```text
Here are all 417 records from the calendar database:
[large prose/JSON dump including organizer UUIDs, sync metadata,
raw provider payloads, attachment URLs, internal etags, ...]
```

After, with an MCP `outputSchema` matching the object:

```json
{
  "content": [
    {
      "type": "text",
      "text": "Returned 2 events; more results are available."
    }
  ],
  "structuredContent": {
    "events": [
      {
        "event_id": "evt_123",
        "title": "Launch review",
        "start_time": "2026-09-28T14:00:00-04:00",
        "end_time": "2026-09-28T14:30:00-04:00"
      },
      {
        "event_id": "evt_456",
        "title": "Design sync",
        "start_time": "2026-09-28T16:00:00-04:00",
        "end_time": "2026-09-28T17:00:00-04:00"
      }
    ],
    "next_cursor": "pg_abc",
    "has_more": true
  },
  "isError": false
}
```

This follows MCP's native structured-output model while keeping the backward-compatible text block, and it follows Anthropic's recommendation to return only high-signal context with filtering/pagination rather than dumping an entire underlying data set. citeturn22view0turn17view1

**Tool granularity**

Before:

```text
users_list
availability_list
events_list
events_create
```

For a repeated scheduling workflow, a useful addition may be:

```text
calendar_schedule_event
```

which resolves participants/availability and creates the event internally. Anthropic specifically recommends collapsing repeatedly chained low-level operations into higher-value workflows where that reduces intermediate context. citeturn17view0

But do **not** turn that lesson into:

```text
calendar_do_everything
```

with a `mode` argument covering search, create, edit, share and delete. Separate actions again when authorization, reversibility, destructive behavior or user confirmation differs; OpenAI explicitly recommends those as split boundaries. citeturn12view2

**Actionable error**

Before:

```text
Error 422
```

After:

```json
{
  "content": [
    {
      "type": "text",
      "text": "The requested end_time is before start_time. Supply end_time later than 2026-09-28T14:00:00-04:00 and retry."
    }
  ],
  "isError": true
}
```

That is exactly the class of recoverable problem MCP intends to expose as a tool execution error rather than a protocol exception, and Anthropic recommends specific corrective guidance instead of opaque codes or stack traces. citeturn22view0turn17view2

The following **cannot be responsibly assessed without inspecting your server's code, generated tool definitions, provider traces, or usage logs**:

- Whether your current tool names actually collide or confuse models in realistic multi-server environments.
- Whether individual descriptions are too vague, too long, overlapping, or missing important “do not use” boundaries.
- Whether your exposed JSON Schemas contain ambiguous fields, unsupported schema constructs, unnecessary required arguments, excessively deep objects, or provider-specific incompatibilities.
- Whether tool serialization/order is deterministic between processes, deployments, users and permission sets.
- How many definition tokens your complete inventory consumes and how much OpenAI/Anthropic/Google prompt-cache reuse you are currently losing.
- Whether your server is repeatedly serving `tools/list` when provider-side list caching could eliminate those round trips.
- Which tools should be combined into workflows and which must remain separate because of your actual authorization, confirmation and side-effect boundaries.
- Whether result payloads contain unnecessary fields, duplicated prose/JSON, excessive rows, secrets, internal diagnostics, raw upstream payloads, or prompt-injection-prone content.
- Whether pagination/filter defaults are appropriate for the observed query/result-size distribution.
- Whether model failures are dominated by wrong-tool selection, invalid arguments, authorization errors, upstream failures, timeouts, malformed responses, excessive context, or poor recovery messages.
- Whether write operations are currently safe under duplicate delivery, transient retries, client disconnects and ambiguous upstream timeouts.
- Whether connection-local state makes the server incompatible with the current stateless 2026 MCP model or horizontally scaled deployments.
- Whether the implementation genuinely supports MCP 2026-07-28, only the legacy initialization era, or an incomplete mixture of the two.
- Whether Streamable HTTP, SSE and/or stdio are implemented correctly for the actual OpenAI, Anthropic, Google and local clients you use.
- Whether authentication is enforced at both tool-discovery and resource-execution layers, including object/tenant authorization for opaque handles.
- Whether destructive/read-only/open-world annotations match real behavior and whether sensitive actions are exposed to provider approval mechanisms correctly.
- Whether your timeouts, rate limits, concurrency limits, retry policy and long-running-operation design match actual downstream latency and failure distributions.
- Whether adding `outputSchema` and `structuredContent` would improve your clients or expose latent mismatches in existing responses.
- Which provider-specific optimizations—OpenAI deferred loading/list retention, Anthropic tool search/pinned `mcp_tool_listing`, or Google's smaller active set—would yield the largest measurable gain for your traffic mix.