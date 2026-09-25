from typing import Any

from ..mcp_instance import mcp
from ..services import drive
from ..validators import (
    validate_limit,
    validate_microsoft_graph_id,
    require_confirm,
)


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
    use_cache: bool = True,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """📖 List only folders (not files) in OneDrive (read-only, safe for unsupervised use)

    Returns folders with child counts and hierarchy information.

    Caching: Results are cached for 15 minutes (fresh) / 1 hour (stale).
    Use force_refresh=True to bypass cache and fetch fresh data.

    Args:
        account_id: Microsoft account ID
        path: Path to list folders from (e.g., "/Documents", default: "/")
        folder_id: Direct folder ID (takes precedence over path)
        limit: Maximum folders to return (1-500, default: 50)
        use_cache: Whether to use cached data if available (default: True)
        force_refresh: Force refresh from API, bypassing cache (default: False)

    Returns:
        Dictionary with:
        - folders: List of folder objects with id, name, childCount, path, parentId
        - _cache_status: Cache state (fresh/stale/miss)
        - _cached_at: When data was cached (ISO format)
    """
    limit = validate_limit(limit, 1, 500, "limit")

    return drive.list_folders(
        account_id,
        path=path,
        folder_id=folder_id,
        limit=limit,
        use_cache=use_cache,
        force_refresh=force_refresh,
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

    return drive.get_folder(account_id, folder_id=folder_id, path=path)


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
    use_cache: bool = True,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """📖 Recursively build a tree of OneDrive folders (read-only, safe for unsupervised use)

    Returns a hierarchical tree structure showing all folders and nested subfolders.
    Useful for understanding OneDrive folder organization.

    Caching: Results are cached for 30 minutes (fresh) / 2 hours (stale).
    Use force_refresh=True to bypass cache and fetch fresh data.

    Args:
        account_id: Microsoft account ID
        path: Starting path (default: "/")
        folder_id: Starting folder ID (takes precedence over path)
        max_depth: Maximum recursion depth (1-25, default: 10)
        use_cache: Whether to use cached data if available (default: True)
        force_refresh: Force refresh from API, bypassing cache (default: False)

    Returns:
        Nested tree structure with folders and their children, including:
        - _cache_status: Cache state (fresh/stale/miss)
        - _cached_at: When data was cached (ISO format)
    """
    max_depth = validate_limit(max_depth, 1, 25, "max_depth")

    return drive.get_folder_tree(
        account_id,
        path=path,
        folder_id=folder_id,
        max_depth=max_depth,
        use_cache=use_cache,
        force_refresh=force_refresh,
    )


# folder_create
@mcp.tool(
    name="folder_create",
    annotations={
        "title": "Create OneDrive Folder",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    meta={"category": "folder", "safety_level": "moderate"},
)
def folder_create(
    name: str,
    account_id: str,
    parent_folder_id: str | None = None,
) -> dict[str, Any]:
    """✏️ Create a new OneDrive folder (requires user confirmation recommended)

    Creates a new folder in OneDrive, either at the root level or
    as a child of an existing folder.

    Args:
        name: Name for the new folder
        account_id: Microsoft account ID
        parent_folder_id: Parent folder ID (None = root level)

    Returns:
        Created folder object with id, name, and other metadata

    Raises:
        ValueError: If name is empty or parent_folder_id is invalid
    """
    if not name or not name.strip():
        raise ValueError("name cannot be empty")

    name = name.strip()

    if parent_folder_id:
        parent_folder_id = validate_microsoft_graph_id(
            parent_folder_id, "parent_folder_id"
        )

    return drive.create_folder(account_id, name, parent_folder_id=parent_folder_id)


# folder_delete
@mcp.tool(
    name="folder_delete",
    annotations={
        "title": "Delete OneDrive Folder",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    meta={"category": "folder", "safety_level": "critical"},
)
def folder_delete(
    folder_id: str,
    account_id: str,
    confirm: bool = False,
) -> dict[str, str]:
    """🔴 Delete an OneDrive folder permanently (always require user confirmation)

    WARNING: This action permanently deletes the folder and all its contents
    (files and subfolders) and cannot be undone.

    Args:
        folder_id: The folder ID to delete
        account_id: Microsoft account ID
        confirm: Must be True to confirm deletion (prevents accidents)

    Returns:
        Status confirmation

    Raises:
        ValueError: If folder_id is invalid or confirm is False
    """
    require_confirm(confirm, "delete OneDrive folder")
    folder_id = validate_microsoft_graph_id(folder_id, "folder_id")

    return drive.delete_folder(account_id, folder_id)


# folder_rename
@mcp.tool(
    name="folder_rename",
    annotations={
        "title": "Rename OneDrive Folder",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    meta={"category": "folder", "safety_level": "moderate"},
)
def folder_rename(
    folder_id: str,
    new_name: str,
    account_id: str,
) -> dict[str, Any]:
    """✏️ Rename an OneDrive folder (requires user confirmation recommended)

    Updates the name of an existing OneDrive folder.

    Args:
        folder_id: The folder ID to rename
        new_name: New name for the folder
        account_id: Microsoft account ID

    Returns:
        Updated folder object with new name

    Raises:
        ValueError: If folder_id is invalid or new_name is empty
    """
    folder_id = validate_microsoft_graph_id(folder_id, "folder_id")

    if not new_name or not new_name.strip():
        raise ValueError("new_name cannot be empty")

    new_name = new_name.strip()

    return drive.rename_folder(account_id, folder_id, new_name)


# folder_move
@mcp.tool(
    name="folder_move",
    annotations={
        "title": "Move OneDrive Folder",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    meta={"category": "folder", "safety_level": "moderate"},
)
def folder_move(
    folder_id: str,
    destination_folder_id: str,
    account_id: str,
) -> dict[str, Any]:
    """✏️ Move an OneDrive folder to a different parent (requires user confirmation recommended)

    Moves a folder to become a child of a different parent folder.

    Args:
        folder_id: The folder ID to move
        destination_folder_id: The destination parent folder ID
        account_id: Microsoft account ID

    Returns:
        Updated folder object with new parentReference

    Raises:
        ValueError: If folder_id or destination_folder_id is invalid
    """
    folder_id = validate_microsoft_graph_id(folder_id, "folder_id")
    destination_folder_id = validate_microsoft_graph_id(
        destination_folder_id, "destination_folder_id"
    )

    return drive.move_folder(account_id, folder_id, destination_folder_id)
