from __future__ import annotations

from typing import Any

from .. import graph
from ..mcp_instance import mcp
from ..services import drive
from ..validators import (
    ValidationError,
    ensure_safe_path,
    format_validation_error,
    require_confirm,
    validate_account_id,
    validate_limit,
    validate_microsoft_graph_id,
    validate_onedrive_path,
)


# file_list
@mcp.tool(
    name="file_list",
    annotations={
        "title": "List Files",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "file", "safety_level": "safe"},
)
def file_list(
    account_id: str,
    path: str = "/",
    folder_id: str | None = None,
    limit: int = 50,
    type_filter: str = "all",
    use_cache: bool = True,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """📖 List files and/or folders in OneDrive (read-only, safe for unsupervised use)

    Returns items from OneDrive with names, sizes, and modification dates.

    Caching: Results are cached for 10 minutes (fresh) / 1 hour (stale).
    Use force_refresh=True to bypass cache and fetch fresh data.

    Args:
        account_id: Microsoft account ID
        path: Path to list from (default: "/")
        folder_id: Direct folder ID (takes precedence over path)
        limit: Maximum items to return (1-500, default: 50)
        type_filter: Filter by type - "all", "files", or "folders" (default: "all")
        use_cache: Whether to use cached data if available (default: True)
        force_refresh: Force refresh from API, bypassing cache (default: False)

    Returns:
        List of items matching the filter criteria.
        Each item includes _cache_status and _cached_at fields.
    """
    validate_account_id(account_id)
    limit = validate_limit(limit, 1, 500)
    if type_filter not in ["all", "files", "folders"]:
        raise ValidationError(
            format_validation_error(
                "type_filter",
                type_filter,
                "unsupported value",
                "'all', 'files', or 'folders'",
            )
        )

    return drive.list_items(
        account_id,
        path=path,
        folder_id=folder_id,
        limit=limit,
        type_filter=type_filter,
        use_cache=use_cache,
        force_refresh=force_refresh,
    )


def _file_get_impl(file_id: str, account_id: str, download_path: str) -> dict[str, Any]:
    account = validate_account_id(account_id)
    graph_file_id = validate_microsoft_graph_id(file_id, "file_id")
    destination = ensure_safe_path(download_path, allow_overwrite=False)
    destination.parent.mkdir(parents=True, exist_ok=True)

    return drive.download_file(account, graph_file_id, destination)


@mcp.tool(
    name="file_get",
    annotations={
        "title": "Get File",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "file", "safety_level": "moderate"},
)
def file_get(file_id: str, account_id: str, download_path: str) -> dict[str, Any]:
    """✏️ Download a OneDrive file to a local path (requires user confirmation recommended)

    The download URL is supplied by Microsoft Graph (never user input) and is
    validated against an allow-list of Microsoft domains before use. The file
    is streamed to disk in configurable chunks with retry behaviour to protect
    against transient failures. Download size and timeouts respect the
    environment variables `MCP_FILE_DOWNLOAD_MAX_MB` and
    `MCP_FILE_DOWNLOAD_TIMEOUT`.

    Args:
        file_id: The Microsoft Graph file identifier to download.
        account_id: Microsoft account identifier associated with the file.
        download_path: Absolute path where the file will be stored locally.
            Must reside within an allowed root directory.

    Returns:
        Dictionary containing download metadata (name, size_mb, mime_type).

    Raises:
        ValidationError: If input parameters are invalid.
        RuntimeError: If all download attempts fail.
    """

    return _file_get_impl(file_id, account_id, download_path)


# file_create
@mcp.tool(
    name="file_create",
    annotations={
        "title": "Create File",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    meta={"category": "file", "safety_level": "moderate"},
)
def file_create(
    onedrive_path: str, local_file_path: str, account_id: str
) -> dict[str, Any]:
    """✏️ Upload a local file to OneDrive (requires user confirmation recommended)

    Args:
        onedrive_path: Destination path within OneDrive (must start with '/').
        local_file_path: Absolute path to the local file to upload. Paths are
            validated via `ensure_safe_path` to prevent traversal and
            restrict uploads to trusted directories.
        account_id: Microsoft account identifier.

    Returns:
        Metadata for the created OneDrive file.
    """
    account = validate_account_id(account_id)
    target = validate_onedrive_path(onedrive_path)
    source_path = ensure_safe_path(
        local_file_path, must_exist=True, allow_overwrite=True
    )

    data = source_path.read_bytes()
    return drive.upload_file(account, target, data)


# file_update
@mcp.tool(
    name="file_update",
    annotations={
        "title": "Update File",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "file", "safety_level": "moderate"},
)
def file_update(file_id: str, local_file_path: str, account_id: str) -> dict[str, Any]:
    """✏️ Replace OneDrive file content with local file (requires user confirmation recommended)

    Args:
        file_id: Target OneDrive file identifier to replace.
        local_file_path: Absolute path to the replacement file. Validated via
            `ensure_safe_path` to block traversal and enforce workspace roots.
        account_id: Microsoft account identifier.

    Returns:
        Updated file metadata returned by Microsoft Graph.
    """
    account = validate_account_id(account_id)
    graph_file_id = validate_microsoft_graph_id(file_id, "file_id")
    source_path = ensure_safe_path(
        local_file_path, must_exist=True, allow_overwrite=True
    )
    data = source_path.read_bytes()
    return drive.replace_file(account, graph_file_id, data)


# file_delete
@mcp.tool(
    name="file_delete",
    annotations={
        "title": "Delete File",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={
        "category": "file",
        "safety_level": "critical",
        "requires_confirmation": True,
    },
)
def file_delete(file_id: str, account_id: str, confirm: bool = False) -> dict[str, str]:
    """🔴 Delete a OneDrive file or folder permanently (always require user confirmation)

    WARNING: This action permanently deletes the file or folder and cannot be undone.
    """

    require_confirm(confirm, "delete OneDrive item")
    account = validate_account_id(account_id)
    graph_file_id = validate_microsoft_graph_id(file_id, "file_id")
    return drive.delete_item(account, graph_file_id)


# file_copy
@mcp.tool(
    name="file_copy",
    annotations={
        "title": "Copy File",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    meta={"category": "file", "safety_level": "moderate"},
)
def file_copy(
    file_id: str,
    destination_folder_id: str,
    account_id: str,
    new_name: str | None = None,
) -> dict[str, Any]:
    """✏️ Copy a file within OneDrive (requires user confirmation recommended)

    Creates a copy of a file in a specified destination folder. The copy
    operation is asynchronous and may take time for large files.

    Args:
        file_id: The file ID to copy
        destination_folder_id: The destination folder ID
        account_id: Microsoft account ID
        new_name: Optional new name for the copied file

    Returns:
        Copy operation status with location URL to monitor progress

    Raises:
        ValueError: If file_id or destination_folder_id is invalid
    """
    account = validate_account_id(account_id)
    graph_file_id = validate_microsoft_graph_id(file_id, "file_id")
    dest_folder_id = validate_microsoft_graph_id(
        destination_folder_id, "destination_folder_id"
    )

    if new_name is not None:
        if not new_name.strip():
            raise ValueError("new_name cannot be empty")
        new_name = new_name.strip()

    return drive.copy_item(account, graph_file_id, dest_folder_id, new_name=new_name)


# file_move
@mcp.tool(
    name="file_move",
    annotations={
        "title": "Move File",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    meta={"category": "file", "safety_level": "moderate"},
)
def file_move(
    file_id: str,
    destination_folder_id: str,
    account_id: str,
) -> dict[str, Any]:
    """✏️ Move a file to a different folder (requires user confirmation recommended)

    Moves a file to a different parent folder within OneDrive.

    Args:
        file_id: The file ID to move
        destination_folder_id: The destination folder ID
        account_id: Microsoft account ID

    Returns:
        Updated file object with new parentReference

    Raises:
        ValueError: If file_id or destination_folder_id is invalid
    """
    account = validate_account_id(account_id)
    graph_file_id = validate_microsoft_graph_id(file_id, "file_id")
    dest_folder_id = validate_microsoft_graph_id(
        destination_folder_id, "destination_folder_id"
    )

    return drive.move_file(account, graph_file_id, dest_folder_id)


# file_rename
@mcp.tool(
    name="file_rename",
    annotations={
        "title": "Rename File",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    meta={"category": "file", "safety_level": "moderate"},
)
def file_rename(
    file_id: str,
    new_name: str,
    account_id: str,
) -> dict[str, Any]:
    """✏️ Rename a file (requires user confirmation recommended)

    Updates the name of an existing OneDrive file.

    Args:
        file_id: The file ID to rename
        new_name: New name for the file
        account_id: Microsoft account ID

    Returns:
        Updated file object with new name

    Raises:
        ValueError: If file_id is invalid or new_name is empty
    """
    account = validate_account_id(account_id)
    graph_file_id = validate_microsoft_graph_id(file_id, "file_id")

    if not new_name or not new_name.strip():
        raise ValueError("new_name cannot be empty")

    new_name = new_name.strip()

    return drive.rename_file(account, graph_file_id, new_name)


def _list_folders_impl(
    account_id: str,
    path: str | None = "/",
    folder_id: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Internal implementation for listing OneDrive folders"""
    if folder_id:
        endpoint = f"/me/drive/items/{folder_id}/children"
    elif path in (None, "/"):
        endpoint = "/me/drive/root/children"
    else:
        endpoint = f"/me/drive/root:/{path}:/children"

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


# file_share
@mcp.tool(
    name="file_share",
    annotations={
        "title": "Share File",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    meta={"category": "file", "safety_level": "moderate"},
)
def file_share(
    file_id: str,
    account_id: str,
    permission_type: str = "view",
    scope: str = "anonymous",
) -> dict[str, Any]:
    """✏️ Create a sharing link for a OneDrive file (requires user confirmation recommended)

    Creates a sharing link that allows others to access the file. Permission types
    control what recipients can do with the file.

    Args:
        file_id: The file ID to share
        account_id: Microsoft account ID
        permission_type: Type of permission - "view" or "edit" (default: "view")
        scope: Link scope - "anonymous" or "organization" (default: "anonymous")

    Returns:
        Sharing link details including the web URL

    Raises:
        ValueError: If file_id is invalid or permission_type/scope is unsupported
    """
    account = validate_account_id(account_id)
    graph_file_id = validate_microsoft_graph_id(file_id, "file_id")

    # Validate permission_type
    if permission_type not in ["view", "edit"]:
        raise ValidationError(
            format_validation_error(
                "permission_type",
                permission_type,
                "unsupported value",
                "'view' or 'edit'",
            )
        )

    # Validate scope
    if scope not in ["anonymous", "organization"]:
        raise ValidationError(
            format_validation_error(
                "scope",
                scope,
                "unsupported value",
                "'anonymous' or 'organization'",
            )
        )

    return drive.create_sharing_link(
        account, graph_file_id, permission_type=permission_type, scope=scope
    )


# file_download_url
@mcp.tool(
    name="file_download_url",
    annotations={
        "title": "Get File Download URL",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    meta={"category": "file", "safety_level": "safe"},
)
def file_download_url(
    file_id: str,
    account_id: str,
) -> dict[str, Any]:
    """📖 Get direct download URL for a OneDrive file (read-only, safe for unsupervised use)

    Returns a temporary download URL that can be used to download the file directly
    without authentication. The URL expires after a short period.

    Args:
        file_id: The file ID to get download URL for
        account_id: Microsoft account ID

    Returns:
        Dictionary containing the download URL and file metadata

    Raises:
        ValueError: If file_id is invalid or file not found
    """
    account = validate_account_id(account_id)
    graph_file_id = validate_microsoft_graph_id(file_id, "file_id")

    return drive.get_download_url(account, graph_file_id)
