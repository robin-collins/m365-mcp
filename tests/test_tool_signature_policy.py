from __future__ import annotations

import ast
from pathlib import Path


EXPECTED_NON_FIRST_ACCOUNT_ID_TOOLS = {
    ("cache_tools.py", "cache_invalidate", 1),
    ("calendar.py", "calendar_get_event", 1),
    ("calendar.py", "calendar_update_event", 2),
    ("contact.py", "contact_delete", 1),
    ("contact.py", "contact_get", 1),
    ("contact.py", "contact_update", 2),
    ("email.py", "email_add_category", 1),
    ("email.py", "email_archive", 1),
    ("email.py", "email_delete", 1),
    ("email.py", "email_flag", 1),
    ("email.py", "email_get", 1),
    ("email.py", "email_get_attachment", 3),
    ("email.py", "email_mark_read", 1),
    ("email.py", "email_move", 2),
    ("email.py", "email_update", 2),
    ("email_folders.py", "emailfolders_create", 1),
    ("email_folders.py", "emailfolders_delete", 1),
    ("email_folders.py", "emailfolders_empty", 1),
    ("email_folders.py", "emailfolders_get", 1),
    ("email_folders.py", "emailfolders_mark_all_as_read", 1),
    ("email_folders.py", "emailfolders_move", 2),
    ("email_folders.py", "emailfolders_rename", 2),
    ("email_rules.py", "emailrules_delete", 1),
    ("email_rules.py", "emailrules_get", 1),
    ("email_rules.py", "emailrules_move_bottom", 1),
    ("email_rules.py", "emailrules_move_down", 1),
    ("email_rules.py", "emailrules_move_top", 1),
    ("email_rules.py", "emailrules_move_up", 1),
    ("email_rules.py", "emailrules_update", 1),
    ("file.py", "file_copy", 2),
    ("file.py", "file_create", 2),
    ("file.py", "file_delete", 1),
    ("file.py", "file_download_url", 1),
    ("file.py", "file_get", 1),
    ("file.py", "file_move", 2),
    ("file.py", "file_rename", 2),
    ("file.py", "file_share", 1),
    ("file.py", "file_update", 2),
    ("folder.py", "folder_create", 1),
    ("folder.py", "folder_delete", 1),
    ("folder.py", "folder_move", 2),
    ("folder.py", "folder_rename", 2),
    ("search.py", "search_contacts", 1),
    ("search.py", "search_emails", 1),
    ("search.py", "search_events", 1),
    ("search.py", "search_files", 1),
    ("search.py", "search_unified", 1),
}


def _is_mcp_tool(function: ast.FunctionDef) -> bool:
    for decorator in function.decorator_list:
        call = decorator if isinstance(decorator, ast.Call) else None
        target = call.func if call else decorator
        if isinstance(target, ast.Attribute) and target.attr == "tool":
            return True
    return False


def test_account_id_signature_policy_has_no_unexpected_drift() -> None:
    """Existing account-scoped public signatures are intentionally preserved."""
    tools_dir = Path("src/m365_mcp/tools")
    actual: set[tuple[str, str, int]] = set()

    for path in tools_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or not _is_mcp_tool(node):
                continue
            parameters = [arg.arg for arg in node.args.args]
            if "account_id" in parameters and parameters[0] != "account_id":
                actual.add((path.name, node.name, parameters.index("account_id")))

    assert actual == EXPECTED_NON_FIRST_ACCOUNT_ID_TOOLS
