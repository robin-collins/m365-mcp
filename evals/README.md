# Golden-prompt evaluation harness

Measures how well a Claude model uses a tool surface (concept §16.2): the
legacy 85-tool surface now, and the unified 29-tool surface once it exists.

## How it works

- **Cases** (`cases.py`): 115 prompts in five categories: direct,
  indirect, ambiguous, competing-tool (list vs search, mail folder vs
  OneDrive folder, update vs move) and no-tool. Each case states the
  acceptable first tools and the successful calls for each surface. Every
  fourth case is held out (28 cases, about 25%); do not tune descriptions
  against it. `SMOKE_IDS` is a fixed 10-case smoke set.
- **Fake Graph** (`fake_graph.py`, `fixtures.py`): an in-memory personal
  mailbox, calendar, address book and OneDrive served through
  `httpx.MockTransport`. The real server code runs unchanged; only the HTTP
  transport, the access token, the account list and retry sleeps are
  replaced (`surface.py`). Runs are deterministic and never touch a real
  account. Unknown routes return a Graph-shaped 404 and are listed per case
  in the transcripts (`unhandled_graph_routes`).
- **Runner** (`runner.py`): shows the model the surface's real
  `tools/list`, executes its calls, and plays the user. When the model stops
  to ask, it first gets the case's follow-up text, then (for side-effect
  cases) one approval: "Yes, that's all correct. Please go ahead."

## Metrics

| Metric | Definition |
|---|---|
| Correct first tool | First call, ignoring `account_list` discovery, is in the case's `first` list. No-tool cases: no call at all. Ambiguous cases with no follow-up: asking the user counts. |
| Schema-valid arguments | Share of calls whose arguments validate against the tool's `inputSchema` (JSON Schema 2020-12 with format checks), before the server sees them. |
| Task success | An executed, non-error call matches one of the case's success alternatives (tool plus argument matchers, optionally a string the result must contain). |
| Calls per task | Mean tool calls per case, no-tool cases excluded. |
| Result tokens | Tool result text length / 4 (an approximation); median reported for list/search tools and for all calls. |
| Unconfirmed side-effect calls | Successful send, share, delete or notify calls made before the simulated user approved. Legacy uses a fixed tool list; unified uses the spec's `meta.confirm` plus the conditional rules. |

## Running

```bash
# offline tests (no API calls)
uv run --group evals pytest tests/test_evals_harness.py -q

# live smoke run (needs ANTHROPIC_API_KEY or an `ant auth login` profile)
uv run --group evals python -m evals.runner --surface legacy --split smoke \
    --out evals/results/smoke-legacy --title "Smoke run, legacy surface"

# full baseline (U0.3)
uv run --group evals python -m evals.runner --surface legacy --split all \
    --out evals/results/baseline-v0 --title "Baseline v0: legacy 85-tool surface"
```

The default model is `claude-sonnet-5` (override with `--model` or
`M365_EVAL_MODEL`). The runner checks the model ID against the Models API
before it starts. Each run writes `<out>.md` (metrics table), `<out>.jsonl`
(one scored result per case) and `<out>.transcripts.json` (full
conversations and the Graph calls made).
