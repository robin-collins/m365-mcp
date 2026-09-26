# Baseline v0: legacy 85-tool surface

- Surface: `legacy`
- Model: `claude-sonnet-5`
- Run date (fixture anchor): 2026-09-26
- Generated: 2026-09-26T15:16:04+09:30

## Metrics (concept §16.2)

| Metric | All | Dev | Held-out |
|---|---|---|---|
| Cases | 115 | 87 | 28 |
| Correct first tool (%) | 94.8 | 94.3 | 96.4 |
| Schema-valid arguments (%) | 100.0 | 100.0 | 100.0 |
| Task success (%) | 91.3 | 93.1 | 85.7 |
| Calls per task (tool cases) | 2.78 | 2.78 | 2.77 |
| Median result tokens, list/search (≈chars/4) | 183 | 193 | 106 |
| Median result tokens, all calls | 39 | 39 | 56 |
| Unconfirmed side-effect calls | 0 | 0 | 0 |
| Tool errors returned | 7 | 4 | 3 |
| Harness/API errors | 0 | 0 | 0 |
| Model input tokens | 14490488 | 10863816 | 3626672 |
| Model output tokens | 65440 | 47054 | 18386 |

## By category

| Category | Cases | First tool % | Success % | Calls/task |
|---|---|---|---|---|
| ambiguous | 10 | 70.0 | 90.0 | 1.4 |
| competing | 25 | 96.0 | 84.0 | 3.04 |
| direct | 50 | 98.0 | 92.0 | 2.86 |
| indirect | 20 | 95.0 | 95.0 | 2.95 |
| no_tool | 10 | 100.0 | 100.0 | 0 |

## Per case

| Case | Split | First tool | OK | Success | Calls | Unconfirmed | Stop |
|---|---|---|---|---|---|---|---|
| d01 | dev | `email_list` | y | y | 2 | 0 | end_turn |
| d02 | dev | `emailfolders_list` | y | y | 2 | 0 | end_turn |
| d03 | dev | `calendar_list_events` | y | y | 3 | 0 | end_turn |
| d04 | heldout | `contact_list` | y | y | 2 | 0 | end_turn |
| d05 | dev | `file_list` | y | y | 1 | 0 | end_turn |
| d06 | dev | `calendar_list_calendars` | y | y | 2 | 0 | end_turn |
| d07 | dev | `emailrules_list` | y | y | 2 | 0 | end_turn |
| d08 | heldout | `search_emails` | y | y | 2 | 0 | end_turn |
| d09 | dev | `search_files` | y | y | 2 | 0 | end_turn |
| d10 | dev | `search_contacts` | y | y | 2 | 0 | end_turn |
| d11 | dev | `emailfolders_create` | y | y | 2 | 0 | end_turn |
| d12 | heldout | `calendar_create_calendar` | y | y | 2 | 0 | end_turn |
| d13 | dev | `contact_create` | y | y | 2 | 0 | end_turn |
| d14 | dev | `folder_list` | y | y | 3 | 0 | end_turn |
| d15 | dev | `search_emails` | y | y | 4 | 0 | end_turn |
| d16 | heldout | `search_emails` | y | y | 5 | 0 | end_turn |
| d17 | dev | `search_emails` | y | y | 3 | 0 | end_turn |
| d18 | dev | `search_files` | y | y | 3 | 0 | end_turn |
| d19 | dev | `email_create_draft` | y | y | 2 | 0 | end_turn |
| d20 | heldout | `email_send` | y | y | 2 | 0 | end_turn |
| d21 | dev | `search_emails` | y | y | 3 | 0 | end_turn |
| d22 | dev | `search_emails` | y | y | 3 | 0 | end_turn |
| d23 | dev | `search_emails` | y | y | 5 | 0 | end_turn |
| d24 | heldout | `email_list` | y | y | 3 | 0 | end_turn |
| d25 | dev | `calendar_create_event` | y | y | 3 | 0 | end_turn |
| d26 | dev | `calendar_list_events` | y | y | 3 | 0 | end_turn |
| d27 | dev | `calendar_list_events` | y | y | 3 | 0 | end_turn |
| d28 | heldout | `calendar_check_availability` | y | y | 3 | 0 | end_turn |
| d29 | dev | `search_files` | y | y | 3 | 0 | end_turn |
| d30 | dev | `search_files` | y | y | 3 | 0 | end_turn |
| d31 | dev | `search_files` | y | y | 5 | 0 | end_turn |
| d32 | heldout | `search_files` | y | y | 6 | 0 | end_turn |
| d33 | dev | `emailfolders_list` | y | n | 2 | 0 | end_turn |
| d34 | dev | `emailfolders_list` | y | n | 1 | 0 | end_turn |
| d35 | dev | `search_contacts` | y | y | 3 | 0 | end_turn |
| d36 | heldout | `search_emails` | y | n | 2 | 0 | end_turn |
| d37 | dev | `search_emails` | y | y | 6 | 0 | end_turn |
| d38 | dev | `file_create` | y | y | 2 | 0 | end_turn |
| d39 | dev | `emailfolders_get_tree` | n | y | 3 | 0 | end_turn |
| d40 | heldout | `emailrules_list` | y | y | 3 | 0 | end_turn |
| d41 | dev | `emailrules_list` | y | y | 3 | 0 | end_turn |
| d42 | dev | `search_events` | y | y | 3 | 0 | end_turn |
| d43 | dev | `search_events` | y | y | 3 | 0 | end_turn |
| d44 | heldout | `search_events` | y | y | 4 | 0 | end_turn |
| d45 | dev | `search_contacts` | y | n | 4 | 0 | end_turn |
| d46 | dev | `emailfolders_list` | y | y | 3 | 0 | end_turn |
| d47 | dev | `calendar_list_calendars` | y | y | 3 | 0 | end_turn |
| d48 | heldout | `search_contacts` | y | y | 3 | 0 | end_turn |
| d49 | dev | `folder_get_tree` | y | y | 2 | 0 | end_turn |
| d50 | dev | `emailfolders_get_tree` | y | y | 2 | 0 | end_turn |
| i01 | dev | `search_emails` | y | y | 3 | 0 | end_turn |
| i02 | heldout | `search_emails` | y | y | 3 | 0 | end_turn |
| i03 | dev | `calendar_list_events` | y | y | 2 | 0 | end_turn |
| i04 | dev | `search_contacts` | y | y | 2 | 0 | end_turn |
| i05 | dev | `search_files` | y | y | 3 | 0 | end_turn |
| i06 | heldout | `search_contacts` | y | y | 3 | 0 | end_turn |
| i07 | dev | `search_events` | y | y | 3 | 0 | end_turn |
| i08 | dev | `email_list` | y | y | 3 | 0 | end_turn |
| i09 | dev | `emailfolders_list` | n | y | 3 | 0 | end_turn |
| i10 | heldout | `calendar_create_event` | y | y | 3 | 0 | end_turn |
| i11 | dev | `search_contacts` | y | y | 4 | 0 | end_turn |
| i12 | dev | `search_files` | y | y | 3 | 0 | end_turn |
| i13 | dev | `folder_list` | y | y | 3 | 0 | end_turn |
| i14 | heldout | `emailrules_create` | y | y | 2 | 0 | end_turn |
| i15 | dev | `search_files` | y | y | 4 | 0 | end_turn |
| i16 | dev | `search_emails` | y | y | 4 | 0 | end_turn |
| i17 | dev | `search_events` | y | y | 2 | 0 | end_turn |
| i18 | heldout | `search_events` | y | n | 2 | 0 | end_turn |
| i19 | dev | `search_emails` | y | y | 2 | 0 | end_turn |
| i20 | dev | `search_emails` | y | y | 5 | 0 | end_turn |
| c01 | dev | `emailfolders_get_tree` | n | y | 3 | 0 | end_turn |
| c02 | heldout | `search_emails` | y | y | 2 | 0 | end_turn |
| c03 | dev | `file_list` | y | y | 2 | 0 | end_turn |
| c04 | dev | `emailfolders_list` | y | n | 4 | 0 | end_turn |
| c05 | dev | `search_emails` | y | n | 6 | 0 | end_turn |
| c06 | heldout | `search_emails` | y | n | 3 | 0 | end_turn |
| c07 | dev | `emailfolders_create` | y | y | 2 | 0 | end_turn |
| c08 | dev | `folder_create` | y | y | 2 | 0 | end_turn |
| c09 | dev | `folder_list` | y | y | 4 | 0 | end_turn |
| c10 | heldout | `search_files` | y | y | 5 | 0 | end_turn |
| c11 | dev | `search_emails` | y | y | 2 | 0 | end_turn |
| c12 | dev | `search_events` | y | y | 2 | 0 | end_turn |
| c13 | dev | `email_list` | y | y | 2 | 0 | end_turn |
| c14 | heldout | `folder_list` | y | y | 4 | 0 | end_turn |
| c15 | dev | `search_contacts` | y | y | 2 | 0 | end_turn |
| c16 | dev | `email_list` | y | y | 3 | 0 | end_turn |
| c17 | dev | `email_list` | y | y | 3 | 0 | end_turn |
| c18 | heldout | `search_files` | y | y | 1 | 0 | end_turn |
| c19 | dev | `search_files` | y | y | 3 | 0 | end_turn |
| c20 | dev | `search_files` | y | y | 4 | 0 | end_turn |
| c21 | dev | `search_events` | y | n | 2 | 0 | end_turn |
| c22 | heldout | `search_contacts` | y | y | 5 | 0 | end_turn |
| c23 | dev | `emailfolders_get_tree` | y | y | 3 | 0 | end_turn |
| c24 | dev | `emailfolders_list` | y | y | 3 | 0 | end_turn |
| c25 | dev | `emailfolders_list` | y | y | 4 | 0 | end_turn |
| a01 | heldout | `search_emails` | y | y | 2 | 0 | end_turn |
| a02 | dev | `-` | y | y | 0 | 0 | end_turn |
| a03 | dev | `search_contacts` | n | y | 6 | 0 | end_turn |
| a04 | dev | `-` | y | y | 0 | 0 | end_turn |
| a05 | heldout | `-` | y | y | 0 | 0 | end_turn |
| a06 | dev | `calendar_list_events` | n | y | 1 | 0 | end_turn |
| a07 | dev | `search_contacts` | y | y | 3 | 0 | end_turn |
| a08 | dev | `search_contacts` | y | y | 2 | 0 | end_turn |
| a09 | heldout | `-` | n | n | 0 | 0 | end_turn |
| a10 | dev | `-` | y | y | 0 | 0 | end_turn |
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
