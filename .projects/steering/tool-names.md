# Tool Naming Conventions

## Core Naming Pattern

`[category]_[verb]_[entity]`

## Categories and Prefixes

| Category | Prefix | Operations |
|----------|--------|------------|
| Email | `email_` | list, get, send, delete, move, update, reply |
| Email Folders | `emailfolders_` | list, get, tree navigation |
| Email Rules | `emailrules_` | list, get, create, update, delete, move |
| Calendar | `calendar_` | calendar_list_events, calendar_get_event, calendar_create_event, calendar_update_event, calendar_delete_event |
| Contacts | `contact_` | list, get, create, update, delete |
| Files | `file_` | list, get, create, update, delete |
| Folders | `folder_` | list, get, tree navigation |
| Search | `search_` | emails, events, contacts, files, unified |
| Account | `account_` | list, authenticate, complete_auth |

## Safety Annotations

Use FastMCP annotations for safety indication:

```python
@mcp.tool(
    name="email_delete",
    annotations={
        "title": "Delete Email",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True
    },
    meta={
        "category": "email",
        "safety_level": "critical",
        "requires_confirmation": True
    }
)
```

## Safety Levels

| Level | readOnlyHint | destructiveHint | Emoji | Description |
|-------|--------------|-----------------|-------|-------------|
| Safe | `True` | `False` | 📖 | Read-only operations |
| Moderate | `False` | `False` | ✏️ | Write/modify operations |
| Dangerous | `False` | `False` | 📧 | Send operations |
| Critical | `False` | `True` | 🔴 | Delete operations |

**Meta safety_level values:** `"safe"`, `"moderate"`, `"dangerous"`, `"critical"`

## Description Guidelines

Use emoji indicators at the start of descriptions for immediate visual safety recognition:

| Emoji | Safety Level | Description Format |
|-------|--------------|-------------------|
| 📖 | Safe | `[Action] (read-only, safe for unsupervised use)` |
| ✏️ | Moderate | `[Action] (requires user confirmation recommended)` |
| 📧 | Dangerous | `[Action] (always require user confirmation)` |
| 🔴 | Critical | `[Action] (always require user confirmation)` |

**Critical operations must include confirm=True parameter to prevent accidental execution.**

## Tool Naming Compliance

**All tools must follow the category prefix system and include appropriate safety annotations with confirmation parameters for critical operations.**
