import pathlib as pl
from typing import Any
from ..mcp_instance import mcp
from .. import graph


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
) -> list[dict[str, Any]]:
    """📖 List files and/or folders in OneDrive (read-only, safe for unsupervised use)

    Returns items from OneDrive with names, sizes, and modification dates.

    Args:
        account_id: Microsoft account ID
        path: Path to list from (default: "/")
        folder_id: Direct folder ID (takes precedence over path)
        limit: Maximum items to return (default: 50)
        type_filter: Filter by type - "all", "files", or "folders" (default: "all")

    Returns:
        List of items matching the filter criteria
    """
    # Validate type_filter
    if type_filter not in ["all", "files", "folders"]:
        raise ValueError("type_filter must be one of: 'all', 'files', 'folders'")

    # Determine endpoint
    if folder_id:
        endpoint = f"/me/drive/items/{folder_id}/children"
    elif path == "/":
        endpoint = "/me/drive/root/children"
    else:
        endpoint = f"/me/drive/root:/{path}:/children"

    params = {
        "$top": min(limit, 100),
        "$select": "id,name,size,lastModifiedDateTime,folder,file,@microsoft.graph.downloadUrl",
    }

    items = list(
        graph.request_paginated(endpoint, account_id, params=params, limit=limit)
    )

    # Apply type filtering
    result = []
    for item in items:
        is_folder = "folder" in item
        is_file = "file" in item

        # Filter based on type_filter
        if type_filter == "folders" and not is_folder:
            continue
        if type_filter == "files" and not is_file:
            continue

        result.append(
            {
                "id": item["id"],
                "name": item["name"],
                "type": "folder" if is_folder else "file",
                "size": item.get("size", 0),
                "modified": item.get("lastModifiedDateTime"),
                "download_url": item.get("@microsoft.graph.downloadUrl"),
            }
        )

    return result


# file_get
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
    """⚠️ Download a file from OneDrive to local path (requires user confirmation recommended)

    IMPORTANT: Large files may take significant time to download.
    Ensure sufficient local disk space is available.

    Files are downloaded in chunks for reliability.

    Args:
        file_id: The file ID to download
        account_id: Microsoft account ID
        download_path: Local path to save the file

    Returns:
        File metadata including path, size, and MIME type
    """
    import subprocess

    metadata = graph.request("GET", f"/me/drive/items/{file_id}", account_id)
    if not metadata:
        raise ValueError(f"File with ID {file_id} not found")

    download_url = metadata.get("@microsoft.graph.downloadUrl")
    if not download_url:
        raise ValueError("No download URL available for this file")

    try:
        subprocess.run(
            ["curl", "-L", "-o", download_path, download_url],
            check=True,
            capture_output=True,
        )

        return {
            "path": download_path,
            "name": metadata.get("name", "unknown"),
            "size_mb": round(metadata.get("size", 0) / (1024 * 1024), 2),
            "mime_type": metadata.get("file", {}).get("mimeType") if metadata else None,
        }
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to download file: {e.stderr.decode()}")


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

    Files >4.8MB automatically use chunked upload for reliability.

    Args:
        onedrive_path: Destination path in OneDrive (e.g., "/Documents/file.pdf")
        local_file_path: Local file path to upload
        account_id: Microsoft account ID

    Returns:
        Created file object with ID and metadata
    """
    path = pl.Path(local_file_path).expanduser().resolve()
    data = path.read_bytes()
    result = graph.upload_large_file(
        f"/me/drive/root:/{onedrive_path}:", data, account_id
    )
    if not result:
        raise ValueError(f"Failed to create file at path: {onedrive_path}")
    return result


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
    """✏️ Update OneDrive file content from local file (requires user confirmation recommended)

    Replaces the file content with new content from local file.
    Files >4.8MB automatically use chunked upload.

    Args:
        file_id: The OneDrive file ID to update
        local_file_path: Local file path with new content
        account_id: Microsoft account ID

    Returns:
        Updated file object
    """
    path = pl.Path(local_file_path).expanduser().resolve()
    data = path.read_bytes()
    result = graph.upload_large_file(f"/me/drive/items/{file_id}", data, account_id)
    if not result:
        raise ValueError(f"Failed to update file with ID: {file_id}")
    return result


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
    """🔴 Delete a file or folder from OneDrive (always require user confirmation)

    WARNING: Deleting a folder will permanently remove ALL files and
    subfolders within it. This action cannot be undone.

    For safety, consider moving items to a "trash" folder first.

    Args:
        file_id: The file or folder ID to delete
        account_id: The account ID
        confirm: Must be True to confirm deletion (prevents accidents)

    Returns:
        Status confirmation
    """
    if not confirm:
        raise ValueError(
            "Deletion requires explicit confirmation. "
            "Set confirm=True to proceed. "
            "This action cannot be undone."
        )
    graph.request("DELETE", f"/me/drive/items/{file_id}", account_id)
    return {"status": "deleted"}


def _list_folders_impl(
    account_id: str,
    path: str = "/",
    folder_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Internal implementation for listing OneDrive folders"""
    if folder_id:
        endpoint = f"/me/drive/items/{folder_id}/children"
    elif path == "/":
        endpoint = "/me/drive/root/children"
    else:
        endpoint = f"/me/drive/root:/{path}:/children"

    params = {
        "$top": min(limit, 100),
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
