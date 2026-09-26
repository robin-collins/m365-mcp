# Smoke run, legacy surface, local model

> **INVALID RUN:** 2 of 10 cases hit an API or harness error and scored as failures (d21, d28). Do not use these numbers.

- Surface: `legacy`
- Model: `qwen3.8-27b-uncensored-cyber-agentic-imatrix`
- Run date (fixture anchor): 2026-09-26
- Generated: 2026-09-26T15:02:46+09:30

## Metrics (concept §16.2)

| Metric | All | Dev | Held-out |
|---|---|---|---|
| Cases | 10 | 8 | 2 |
| Correct first tool (%) | 60.0 | 62.5 | 50.0 |
| Schema-valid arguments (%) | 100.0 | 100.0 | 100.0 |
| Task success (%) | 70.0 | 75.0 | 50.0 |
| Calls per task (tool cases) | 2.33 | 2.71 | 1 |
| Median result tokens, list/search (≈chars/4) | 271 | 249 | 276 |
| Median result tokens, all calls | 39 | 39 | 157 |
| Unconfirmed side-effect calls | 0 | 0 | 0 |
| Tool errors returned | 1 | 1 | 0 |
| Harness/API errors | 2 | 1 | 1 |
| Model input tokens | 630249 | 568531 | 61718 |
| Model output tokens | 2879 | 2482 | 397 |

## By category

| Category | Cases | First tool % | Success % | Calls/task |
|---|---|---|---|---|
| ambiguous | 1 | 0.0 | 0.0 | 3 |
| competing | 3 | 66.7 | 100.0 | 2 |
| direct | 4 | 50.0 | 50.0 | 2 |
| indirect | 1 | 100.0 | 100.0 | 4 |
| no_tool | 1 | 100.0 | 100.0 | 0 |

## Per case

| Case | Split | First tool | OK | Success | Calls | Unconfirmed | Stop |
|---|---|---|---|---|---|---|---|
| d01 | dev | `email_list` | y | y | 2 | 0 | end_turn |
| d08 | heldout | `search_emails` | y | y | 2 | 0 | end_turn |
| d21 | dev | `search_emails` | n | n | 4 | 0 | error |
| d28 | heldout | `-` | n | n | 0 | 0 | error |
| i01 | dev | `search_emails` | y | y | 4 | 0 | end_turn |
| c01 | dev | `emailfolders_get_tree` | n | y | 2 | 0 | end_turn |
| c07 | dev | `emailfolders_create` | y | y | 2 | 0 | end_turn |
| c08 | dev | `folder_create` | y | y | 2 | 0 | end_turn |
| a02 | dev | `email_list` | n | n | 3 | 0 | end_turn |
| n01 | dev | `-` | y | y | 0 | 0 | answered |
