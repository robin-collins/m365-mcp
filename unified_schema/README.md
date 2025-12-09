# Unified Tool Schema Proposal

This folder introduces a consolidated JSON Schema layer that wraps the existing
operation-specific schemas into a smaller, predictable tool surface. Each
unified schema uses a common envelope with two fields:

- `resource`: discriminator that selects the target entity or operation flavor.
- `parameters`: the exact payload validated by the current individual schema for
  that operation.

Using this pattern keeps the detailed validation logic from
`individual_schema/` intact while exposing a compact tool catalogue for MCP
clients.

## Unified tool list

| Unified tool | Resources (via `resource` discriminator) | Underlying individual schema(s) |
| --- | --- | --- |
| `list` | `emails`, `events`, `contacts`, `files` | `email_list`, `calendar_list_events`, `contact_list`, `file_list` |
| `get` | `email`, `attachment`, `event`, `availability`, `contact`, `file` | `email_get`, `email_get_attachment`, `calendar_get_event`, `calendar_check_availability`, `contact_get`, `file_get` |
| `create` | `email_draft`, `event`, `contact`, `file` | `email_create_draft`, `calendar_create_event`, `contact_create`, `file_create` |
| `send` | `email` | `email_send` |
| `reply` | `email`, `email_all`, `event` | `email_reply`, `email_reply_all`, `calendar_respond_event` |
| `update` | `email`, `event`, `contact`, `file` | `email_update`, `calendar_update_event`, `contact_update`, `file_update` |
| `move` | `email` | `email_move` (file/folder moves can be added when schemas exist) |
| `delete` | `email`, `event`, `contact`, `file`, `calendar` | `email_delete`, `calendar_delete_event`, `contact_delete`, `file_delete`, `calendar_delete_calendar` |
| `search` | `emails`, `events`, `files`, `unified` | `search_unified` (with constrained `entity_types` for emails/events) and `search_files` |
| `auth` | `list`, `authenticate`, `complete` | `account_list`, `account_authenticate`, `account_complete_auth` |
| `cache` | `get_stats`, `invalidate`, `task_enqueue`, `task_status`, `task_list`, `warming_status` | `cache_get_stats`, `cache_invalidate`, `cache_task_enqueue`, `cache_task_get_status`, `cache_task_list`, `cache_warming_status` |

## Design notes

- **Compatibility-first**: the unified schemas wrap (not replace) the existing
  per-tool schemas through `$ref` or `allOf`, so any updates to the underlying
  validators automatically flow into the unified surface.
- **Discriminated unions**: every unified schema declares a `discriminator`
  pointing at `resource`, making it clear which parameter schema applies for a
  given call.
- **Safety preservation**: destructive and send operations still depend on the
  underlying schema requirements (for example `confirm: true` on send/delete),
  so the unified layer inherits those safeguards.
- **Extensibility**: placeholders like `move` can accept additional resources
  (e.g., OneDrive moves) simply by adding a new branch that references the
  future schema without changing the envelope shape.
- **Consistency**: cache/auth/search entries keep their specialized controls
  (task status, entity type selection, etc.) but remain discoverable as one
  verb with resource variants.

## Usage example

To list files:

```json
{
  "resource": "files",
  "parameters": {
    "account_id": "...",
    "path": "/",
    "limit": 25
  }
}
```

To search only emails using the unified search schema:

```json
{
  "resource": "emails",
  "parameters": {
    "query": "quarterly report",
    "account_id": "...",
    "entity_types": "message"
  }
}
```

Existing tooling can keep emitting the individual payloads; the unified layer
just standardizes the wrapper and routing logic needed to register a smaller
set of MCP tools.
