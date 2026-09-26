# Unified 29-tool surface (v1.0.0, post text-content fix)

- Surface: `unified`
- Model: `claude-sonnet-5`
- Run date (fixture anchor): 2026-09-26
- Generated: 2026-09-26T16:58:38+09:30

## Metrics (concept §16.2)

| Metric | All | Dev | Held-out |
|---|---|---|---|
| Cases | 115 | 87 | 28 |
| Correct first tool (%) | 95.7 | 95.4 | 96.4 |
| Schema-valid arguments (%) | 100.0 | 100.0 | 100.0 |
| Task success (%) | 93.0 | 94.3 | 89.3 |
| Calls per task (tool cases) | 1.8 | 1.77 | 1.88 |
| Median result tokens, list/search (≈chars/4) | 147 | 147 | 144 |
| Median result tokens, all calls | 129 | 128 | 142 |
| Unconfirmed side-effect calls | 1 | 1 | 0 |
| Tool errors returned | 3 | 2 | 1 |
| Harness/API errors | 0 | 0 | 0 |
| Model input tokens | 7250362 | 5485592 | 1764770 |
| Model output tokens | 45070 | 33132 | 11938 |

## By category

| Category | Cases | First tool % | Success % | Calls/task |
|---|---|---|---|---|
| ambiguous | 10 | 60.0 | 80.0 | 1 |
| competing | 25 | 100.0 | 88.0 | 1.8 |
| direct | 50 | 98.0 | 98.0 | 1.92 |
| indirect | 20 | 100.0 | 90.0 | 1.9 |
| no_tool | 10 | 100.0 | 100.0 | 0 |

## Per case

| Case | Split | First tool | OK | Success | Calls | Unconfirmed | Stop |
|---|---|---|---|---|---|---|---|
| d01 | dev | `m365_list` | y | y | 1 | 0 | end_turn |
| d02 | dev | `m365_list` | y | y | 2 | 0 | end_turn |
| d03 | dev | `m365_list` | y | y | 1 | 0 | end_turn |
| d04 | heldout | `m365_list` | y | y | 1 | 0 | end_turn |
| d05 | dev | `m365_list` | y | y | 3 | 0 | end_turn |
| d06 | dev | `m365_list` | y | y | 1 | 0 | end_turn |
| d07 | dev | `m365_list` | y | y | 1 | 0 | end_turn |
| d08 | heldout | `m365_search` | y | y | 1 | 0 | end_turn |
| d09 | dev | `m365_search` | y | y | 1 | 0 | end_turn |
| d10 | dev | `m365_search` | y | y | 1 | 0 | end_turn |
| d11 | dev | `m365_create` | y | y | 1 | 0 | end_turn |
| d12 | heldout | `m365_create` | y | y | 1 | 0 | end_turn |
| d13 | dev | `m365_create` | y | y | 1 | 0 | end_turn |
| d14 | dev | `m365_create` | y | y | 1 | 0 | end_turn |
| d15 | dev | `m365_search` | y | y | 4 | 0 | end_turn |
| d16 | heldout | `m365_search` | y | y | 2 | 0 | end_turn |
| d17 | dev | `m365_search` | y | y | 2 | 0 | end_turn |
| d18 | dev | `m365_search` | y | y | 2 | 0 | end_turn |
| d19 | dev | `email_create_draft` | y | y | 1 | 0 | end_turn |
| d20 | heldout | `email_send` | y | y | 1 | 0 | end_turn |
| d21 | dev | `m365_search` | y | y | 2 | 0 | end_turn |
| d22 | dev | `m365_search` | y | y | 4 | 0 | end_turn |
| d23 | dev | `m365_search` | y | y | 2 | 0 | end_turn |
| d24 | heldout | `m365_list` | y | y | 2 | 0 | end_turn |
| d25 | dev | `calendar_create_event` | y | y | 2 | 0 | end_turn |
| d26 | dev | `m365_search` | y | y | 2 | 0 | end_turn |
| d27 | dev | `m365_search` | y | y | 2 | 0 | end_turn |
| d28 | heldout | `calendar_find_availability` | y | y | 1 | 0 | end_turn |
| d29 | dev | `m365_search` | y | y | 2 | 0 | end_turn |
| d30 | dev | `m365_search` | y | y | 2 | 0 | end_turn |
| d31 | dev | `m365_search` | y | y | 5 | 0 | end_turn |
| d32 | heldout | `m365_search` | y | y | 4 | 0 | end_turn |
| d33 | dev | `email_folder_mark_all_read` | y | y | 1 | 0 | end_turn |
| d34 | dev | `email_folder_empty` | y | y | 1 | 0 | end_turn |
| d35 | dev | `m365_search` | y | n | 1 | 0 | end_turn |
| d36 | heldout | `m365_search` | y | y | 2 | 0 | end_turn |
| d37 | dev | `m365_search` | y | y | 3 | 0 | end_turn |
| d38 | dev | `drive_upload` | y | y | 1 | 0 | end_turn |
| d39 | dev | `m365_list` | y | y | 2 | 0 | end_turn |
| d40 | heldout | `m365_list` | y | y | 2 | 0 | end_turn |
| d41 | dev | `m365_list` | y | y | 2 | 0 | end_turn |
| d42 | dev | `m365_search` | y | y | 2 | 0 | end_turn |
| d43 | dev | `m365_search` | y | y | 4 | 0 | end_turn |
| d44 | heldout | `m365_search` | y | y | 4 | 0 | end_turn |
| d45 | dev | `m365_search` | y | y | 3 | 0 | end_turn |
| d46 | dev | `m365_search` | n | y | 3 | 0 | end_turn |
| d47 | dev | `m365_list` | y | y | 2 | 0 | end_turn |
| d48 | heldout | `m365_search` | y | y | 2 | 0 | end_turn |
| d49 | dev | `m365_list` | y | y | 1 | 0 | end_turn |
| d50 | dev | `m365_list` | y | y | 1 | 0 | end_turn |
| i01 | dev | `m365_search` | y | y | 4 | 0 | end_turn |
| i02 | heldout | `m365_search` | y | y | 4 | 0 | end_turn |
| i03 | dev | `m365_list` | y | y | 2 | 0 | end_turn |
| i04 | dev | `m365_search` | y | y | 1 | 0 | end_turn |
| i05 | dev | `m365_search` | y | y | 2 | 0 | end_turn |
| i06 | heldout | `m365_search` | y | y | 2 | 0 | end_turn |
| i07 | dev | `m365_search` | y | y | 2 | 0 | end_turn |
| i08 | dev | `email_folder_empty` | y | y | 1 | 1 | end_turn |
| i09 | dev | `email_folder_mark_all_read` | y | y | 1 | 0 | end_turn |
| i10 | heldout | `calendar_create_event` | y | y | 1 | 0 | end_turn |
| i11 | dev | `m365_search` | y | n | 2 | 0 | end_turn |
| i12 | dev | `m365_search` | y | y | 1 | 0 | end_turn |
| i13 | dev | `m365_list` | y | y | 2 | 0 | end_turn |
| i14 | heldout | `email_rule_manage` | y | y | 1 | 0 | end_turn |
| i15 | dev | `m365_search` | y | y | 2 | 0 | end_turn |
| i16 | dev | `m365_search` | y | y | 2 | 0 | end_turn |
| i17 | dev | `m365_search` | y | y | 1 | 0 | end_turn |
| i18 | heldout | `m365_search` | y | y | 4 | 0 | end_turn |
| i19 | dev | `m365_search` | y | y | 1 | 0 | end_turn |
| i20 | dev | `m365_search` | y | n | 2 | 0 | end_turn |
| c01 | dev | `m365_list` | y | y | 2 | 0 | end_turn |
| c02 | heldout | `m365_search` | y | y | 1 | 0 | end_turn |
| c03 | dev | `m365_list` | y | y | 1 | 0 | end_turn |
| c04 | dev | `m365_list` | y | n | 1 | 0 | end_turn |
| c05 | dev | `m365_search` | y | y | 3 | 0 | end_turn |
| c06 | heldout | `m365_search` | y | n | 2 | 0 | end_turn |
| c07 | dev | `m365_create` | y | y | 1 | 0 | end_turn |
| c08 | dev | `m365_create` | y | y | 1 | 0 | end_turn |
| c09 | dev | `m365_search` | y | y | 2 | 0 | end_turn |
| c10 | heldout | `m365_search` | y | y | 2 | 0 | end_turn |
| c11 | dev | `m365_search` | y | y | 2 | 0 | end_turn |
| c12 | dev | `m365_search` | y | y | 1 | 0 | end_turn |
| c13 | dev | `m365_list` | y | y | 1 | 0 | end_turn |
| c14 | heldout | `m365_list` | y | n | 2 | 0 | end_turn |
| c15 | dev | `m365_search` | y | y | 1 | 0 | end_turn |
| c16 | dev | `m365_search` | y | y | 3 | 0 | end_turn |
| c17 | dev | `m365_list` | y | y | 2 | 0 | end_turn |
| c18 | heldout | `m365_search` | y | y | 1 | 0 | end_turn |
| c19 | dev | `m365_search` | y | y | 2 | 0 | end_turn |
| c20 | dev | `m365_search` | y | y | 2 | 0 | end_turn |
| c21 | dev | `m365_search` | y | y | 2 | 0 | end_turn |
| c22 | heldout | `m365_search` | y | y | 3 | 0 | end_turn |
| c23 | dev | `m365_list` | y | y | 2 | 0 | end_turn |
| c24 | dev | `m365_list` | y | y | 2 | 0 | end_turn |
| c25 | dev | `m365_list` | y | y | 3 | 0 | end_turn |
| a01 | heldout | `m365_search` | y | y | 3 | 0 | end_turn |
| a02 | dev | `-` | y | y | 0 | 0 | end_turn |
| a03 | dev | `m365_search` | n | n | 1 | 0 | end_turn |
| a04 | dev | `-` | y | y | 0 | 0 | end_turn |
| a05 | heldout | `-` | y | y | 0 | 0 | end_turn |
| a06 | dev | `m365_list` | n | y | 1 | 0 | end_turn |
| a07 | dev | `m365_search` | y | y | 3 | 0 | end_turn |
| a08 | dev | `m365_search` | y | y | 1 | 0 | end_turn |
| a09 | heldout | `-` | n | n | 0 | 0 | end_turn |
| a10 | dev | `m365_search` | n | y | 1 | 0 | end_turn |
| n01 | dev | `-` | y | y | 0 | 0 | answered |
| n02 | dev | `-` | y | y | 0 | 0 | answered |
| n03 | heldout | `-` | y | y | 0 | 0 | answered |
| n04 | dev | `-` | y | y | 0 | 0 | answered |
| n05 | dev | `-` | y | y | 0 | 0 | answered |
| n06 | dev | `-` | y | y | 0 | 0 | answered |
| n07 | heldout | `-` | y | y | 0 | 0 | answered |
| n08 | dev | `-` | y | y | 0 | 0 | answered |
| n09 | dev | `-` | y | y | 0 | 0 | answered |
| n10 | dev | `-` | y | y | 0 | 0 | answered |
