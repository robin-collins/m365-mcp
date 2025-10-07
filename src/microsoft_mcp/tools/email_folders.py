from typing import Any
from ..mcp_instance import mcp
from .. import graph
from ..validators import validate_limit


def _list_mail_folders_impl(
    account_id: str,
    parent_folder_id: str | None = None,
    include_hidden: bool = False,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Internal implementation for listing mail folders"""
    if parent_folder_id:
        endpoint = f"/me/mailFolders/{parent_folder_id}/childFolders"
    else:
        endpoint = "/me/mailFolders"

    page_size = limit if limit is not None else 250
    params = {
        "$select": "id,displayName,childFolderCount,unreadItemCount,totalItemCount,parentFolderId,isHidden",
        "$top": page_size,
    }

    if include_hidden:
        params["includeHiddenFolders"] = "true"

    folders = list(
        graph.request_paginated(endpoint, account_id, params=params, limit=limit)
    )

    return folders


# emailfolders_list
@mcp.tool(
    name="emailfolders_list",
    annotations={
        "title": "List Email Folders",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "emailfolders", "safety_level": "safe"},
)
def emailfolders_list(
    account_id: str,
    parent_folder_id: str | None = None,
    include_hidden: bool = False,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """📖 List mail folders from mailbox (read-only, safe for unsupervised use)

    Returns root folders or child folders of a specific parent with metadata
    including unread counts and child folder information.

    Args:
        account_id: Microsoft account ID
        parent_folder_id: If None, lists root folders. If provided, lists child folders.
        include_hidden: Whether to include hidden folders (default: False)
        limit: Maximum number of folders to return (1-250, default: 100)

    Returns:
        List of folder objects with: id, displayName, childFolderCount,
        unreadItemCount, totalItemCount, parentFolderId, isHidden
    """
    limit = validate_limit(limit, 1, 250, "limit")
    return _list_mail_folders_impl(account_id, parent_folder_id, include_hidden, limit)


# emailfolders_get
@mcp.tool(
    name="emailfolders_get",
    annotations={
        "title": "Get Email Folder",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "emailfolders", "safety_level": "safe"},
)
def emailfolders_get(
    folder_id: str,
    account_id: str,
) -> dict[str, Any]:
    """📖 Get detailed information about a specific mail folder (read-only, safe for unsupervised use)

    Returns complete folder metadata including counts and hierarchy information.

    Args:
        folder_id: The folder ID to retrieve
        account_id: Microsoft account ID

    Returns:
        Folder object with full metadata including id, displayName,
        childFolderCount, unreadItemCount, totalItemCount
    """
    result = graph.request("GET", f"/me/mailFolders/{folder_id}", account_id)
    if not result:
        raise ValueError(f"Mail folder with ID {folder_id} not found")
    return result


# emailfolders_get_tree
@mcp.tool(
    name="emailfolders_get_tree",
    annotations={
        "title": "Get Email Folder Tree",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "emailfolders", "safety_level": "safe"},
)
def emailfolders_get_tree(
    account_id: str,
    parent_folder_id: str | None = None,
    max_depth: int = 10,
    include_hidden: bool = False,
) -> dict[str, Any]:
    """📖 Recursively build a tree of mail folders (read-only, safe for unsupervised use)

    Returns a hierarchical tree structure showing all folders and their nested children.
    Useful for understanding mailbox folder organization.

    Args:
        account_id: Microsoft account ID
        parent_folder_id: Root folder to start from (None = root)
        max_depth: Maximum recursion depth to prevent infinite loops (1-25, default: 10)
        include_hidden: Whether to include hidden folders (default: False)

    Returns:
        Nested tree structure with folders and their children
    """
    max_depth = validate_limit(max_depth, 1, 25, "max_depth")

    def _build_folder_tree(
        folder_id: str | None, current_depth: int
    ) -> list[dict[str, Any]]:
        """Internal recursive helper to build folder tree"""
        if current_depth >= max_depth:
            return []

        # Get folders at this level
        folders = _list_mail_folders_impl(
            account_id=account_id,
            parent_folder_id=folder_id,
            include_hidden=include_hidden,
            limit=None,
        )

        result = []
        for folder in folders:
            folder_node = {
                "id": folder["id"],
                "displayName": folder.get("displayName", ""),
                "childFolderCount": folder.get("childFolderCount", 0),
                "unreadItemCount": folder.get("unreadItemCount", 0),
                "totalItemCount": folder.get("totalItemCount", 0),
                "parentFolderId": folder.get("parentFolderId"),
                "isHidden": folder.get("isHidden", False),
                "children": [],
            }

            # Recursively get children if this folder has child folders
            if folder.get("childFolderCount", 0) > 0:
                folder_node["children"] = _build_folder_tree(
                    folder["id"], current_depth + 1
                )

            result.append(folder_node)

        return result

    # Build tree starting from specified parent or root
    tree_data = _build_folder_tree(parent_folder_id, 0)

    return {
        "root_folder_id": parent_folder_id,
        "max_depth": max_depth,
        "folders": tree_data,
    }
