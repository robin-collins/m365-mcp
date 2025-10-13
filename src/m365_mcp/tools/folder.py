from typing import Any
from ..mcp_instance import mcp
from .. import graph
from ..validators import validate_limit, validate_onedrive_path


def _list_folders_impl(
    account_id: str,
    path: str | None = "/",
    folder_id: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Internal implementation for listing OneDrive folders"""
    if folder_id:
        endpoint = f"/me/drive/items/{folder_id}/children"
    else:
        normalised_path = validate_onedrive_path(path or "/", "path")
        if normalised_path == "/":
            endpoint = "/me/drive/root/children"
        else:
            endpoint = f"/me/drive/root:{normalised_path}:/children"

    page_size = limit if limit is not None else 500
    params = {
        "$top": page_size,
        "$select": "id,name,folder,parentReference,size,lastModifiedDateTime",
    }

    items = list(
        graph.request_paginated(endpoint, account_id, params=params, limit=limit)
    )

    # Filter to only return folders
    folders = []
    for item in items:
        if "folder" in item:
            folders.append(
                {
                    "id": item["id"],
                    "name": item["name"],
                    "childCount": item.get("folder", {}).get("childCount", 0),
                    "path": item.get("parentReference", {}).get("path", ""),
                    "parentId": item.get("parentReference", {}).get("id"),
                    "modified": item.get("lastModifiedDateTime"),
                }
            )

    return folders


# folder_list
@mcp.tool(
    name="folder_list",
    annotations={
        "title": "List Folders",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "folder", "safety_level": "safe"},
)
def folder_list(
    account_id: str,
    path: str = "/",
    folder_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """📖 List only folders (not files) in OneDrive (read-only, safe for unsupervised use)

    Returns folders with child counts and hierarchy information.

    Args:
        account_id: Microsoft account ID
        path: Path to list folders from (e.g., "/Documents", default: "/")
        folder_id: Direct folder ID (takes precedence over path)
        limit: Maximum folders to return (1-500, default: 50)

    Returns:
        List of folder objects with: id, name, childCount, path, parentId
    """
    limit = validate_limit(limit, 1, 500, "limit")
    return _list_folders_impl(
        account_id=account_id,
        path=path,
        folder_id=folder_id,
        limit=limit,
    )


# folder_get
@mcp.tool(
    name="folder_get",
    annotations={
        "title": "Get Folder",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "folder", "safety_level": "safe"},
)
def folder_get(
    account_id: str,
    folder_id: str | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    """📖 Get metadata for a specific OneDrive folder (read-only, safe for unsupervised use)

    Returns folder details including child count and web URL.

    Args:
        account_id: Microsoft account ID
        folder_id: Folder ID (takes precedence if provided)
        path: Folder path (e.g., "/Documents/Projects")

    Returns:
        Folder metadata including childCount, webUrl, and parent info
    """
    if not folder_id and not path:
        raise ValueError("Either folder_id or path must be provided")

    if folder_id:
        endpoint = f"/me/drive/items/{folder_id}"
    else:
        normalised_path = validate_onedrive_path(path or "/", "path")
        if normalised_path == "/":
            endpoint = "/me/drive/root"
        else:
            endpoint = f"/me/drive/root:{normalised_path}"

    result = graph.request("GET", endpoint, account_id)
    if not result:
        raise ValueError("Folder not found")

    # Validate it's actually a folder
    if "folder" not in result:
        raise ValueError("Item at specified location is not a folder")

    return {
        "id": result["id"],
        "name": result["name"],
        "childCount": result.get("folder", {}).get("childCount", 0),
        "path": result.get("parentReference", {}).get("path", ""),
        "parentId": result.get("parentReference", {}).get("id"),
        "modified": result.get("lastModifiedDateTime"),
        "webUrl": result.get("webUrl"),
    }


# folder_get_tree
@mcp.tool(
    name="folder_get_tree",
    annotations={
        "title": "Get Folder Tree",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "folder", "safety_level": "safe"},
)
def folder_get_tree(
    account_id: str,
    path: str = "/",
    folder_id: str | None = None,
    max_depth: int = 10,
) -> dict[str, Any]:
    """📖 Recursively build a tree of OneDrive folders (read-only, safe for unsupervised use)

    Returns a hierarchical tree structure showing all folders and nested subfolders.
    Useful for understanding OneDrive folder organization.

    Args:
        account_id: Microsoft account ID
        path: Starting path (default: "/")
        folder_id: Starting folder ID (takes precedence over path)
        max_depth: Maximum recursion depth (1-25, default: 10)

    Returns:
        Nested tree structure with folders and their children
    """
    max_depth = validate_limit(max_depth, 1, 25, "max_depth")

    def _build_drive_folder_tree(
        item_id: str | None, item_path: str | None, current_depth: int
    ) -> list[dict[str, Any]]:
        """Internal recursive helper to build OneDrive folder tree"""
        if current_depth >= max_depth:
            return []

        # Get folders at this level
        try:
            folders = _list_folders_impl(
                account_id=account_id,
                path=item_path if not item_id else None,
                folder_id=item_id,
                limit=None,
            )
        except Exception as e:
            # Log error but don't fail entire tree operation
            # Return empty list to stop recursion on this branch
            return []

        result = []
        for folder in folders:
            folder_node = {
                "id": folder["id"],
                "name": folder["name"],
                "childCount": folder.get("childCount", 0),
                "path": folder.get("path", ""),
                "parentId": folder.get("parentId"),
                "modified": folder.get("modified"),
                "children": [],
            }

            # Always recurse to check for subfolders
            # The API call will return empty list if no subfolders exist
            # This is more efficient than checking childCount which includes files
            folder_node["children"] = _build_drive_folder_tree(
                folder["id"], None, current_depth + 1
            )

            result.append(folder_node)

        return result

    # Build tree starting from specified location
    if folder_id:
        start_id = folder_id
        start_path: str | None = None
    else:
        start_id = None
        start_path = validate_onedrive_path(path or "/", "path")

    tree_data = _build_drive_folder_tree(start_id, start_path, 0)

    return {
        "root_folder_id": folder_id,
        "root_path": start_path if start_path is not None else None,
        "max_depth": max_depth,
        "folders": tree_data,
    }
