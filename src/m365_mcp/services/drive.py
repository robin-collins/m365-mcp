"""OneDrive file and folder service.

Holds the Microsoft Graph logic behind the ``file_*`` and ``folder_*``
tools: endpoints, query parameters, pagination, uploads, streamed
downloads, cache reads/writes and cache invalidation. Inputs are expected
to have been validated by the MCP tool layer.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

import httpx

from .. import graph
from ..validators import (
    ValidationError,
    format_validation_error,
    validate_graph_url,
    validate_onedrive_path,
    validate_request_size,
)

if TYPE_CHECKING:
    from ..cache import CacheManager

LOGGER = logging.getLogger("microsoft_mcp.services.drive")

DEFAULT_DOWNLOAD_TIMEOUT = float(os.getenv("MCP_FILE_DOWNLOAD_TIMEOUT", "60.0"))
DEFAULT_CHUNK_SIZE = int(os.getenv("MCP_FILE_DOWNLOAD_CHUNK_SIZE", "1048576"))
MAX_DOWNLOAD_MIB = int(os.getenv("MCP_FILE_DOWNLOAD_MAX_MB", "512"))
MAX_REDIRECTS = 3

_FILE_LIST_SELECT = (
    "id,name,size,lastModifiedDateTime,folder,file,@microsoft.graph.downloadUrl"
)
_FOLDER_SELECT = "id,name,folder,parentReference,size,lastModifiedDateTime"


def get_cache_manager() -> CacheManager:
    """Return the shared cache manager.

    The import is deferred so this service module does not depend on the
    tools package at import time.

    Returns:
        The process-wide cache manager instance.
    """
    from ..cache import get_cache_manager as _get_cache_manager

    return _get_cache_manager()


def _invalidate(account_id: str, *resources: str) -> None:
    """Invalidate cached entries for resources, ignoring cache failures."""
    try:
        cache_manager = get_cache_manager()
        for resource in resources:
            cache_manager.invalidate_pattern(f"{resource}:*", account_id=account_id)
    except Exception:
        # Don't fail the operation if cache invalidation fails
        pass


def _children_endpoint(path: str, folder_id: str | None) -> str:
    """Build the children endpoint for a folder ID or OneDrive path."""
    if folder_id:
        return f"/me/drive/items/{folder_id}/children"
    normalised_path = validate_onedrive_path(path, "path")
    if normalised_path == "/":
        return "/me/drive/root/children"
    return f"/me/drive/root:{normalised_path}:/children"


def list_items(
    account_id: str,
    *,
    path: str = "/",
    folder_id: str | None = None,
    limit: int = 50,
    type_filter: str = "all",
    use_cache: bool = True,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """List files and/or folders in a OneDrive folder.

    Args:
        account_id: Microsoft account identifier.
        path: OneDrive path to list (ignored when folder_id is given).
        folder_id: Folder ID to list; takes precedence over path.
        limit: Maximum number of items to fetch.
        type_filter: "all", "files" or "folders".
        use_cache: Whether to read and write the cache.
        force_refresh: Skip the cache read and fetch from Graph.

    Returns:
        Item summaries with ``_cache_status`` (and ``_cached_at`` when
        fetched from Graph).

    Raises:
        ValidationError: If path is not a valid OneDrive path.
    """
    cache_params = {
        "path": path,
        "folder_id": folder_id,
        "limit": limit,
        "type_filter": type_filter,
    }

    if use_cache and not force_refresh:
        try:
            cache_manager = get_cache_manager()
            cached_result = cache_manager.get_cached(
                account_id, "file_list", cache_params
            )

            if cached_result:
                data, state = cached_result
                for item in data:
                    item["_cache_status"] = state.value
                return data
        except Exception:
            # If cache fails, continue to API call
            pass

    endpoint = _children_endpoint(path, folder_id)
    params = {"$top": limit, "$select": _FILE_LIST_SELECT}

    items = list(
        graph.request_paginated(endpoint, account_id, params=params, limit=limit)
    )

    result = []
    cached_at = datetime.now(timezone.utc).isoformat()

    for item in items:
        is_folder = "folder" in item
        is_file = "file" in item

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
                "_cache_status": "miss",  # Fresh from API
                "_cached_at": cached_at,
            }
        )

    if use_cache:
        try:
            cache_manager = get_cache_manager()
            cache_manager.set_cached(account_id, "file_list", cache_params, result)
        except Exception:
            # If cache storage fails, still return the result
            pass

    return result


def _stream_download(
    url: str,
    destination: Path,
    *,
    timeout: float,
    chunk_size: int,
) -> None:
    """Stream file contents from a validated URL to destination path."""
    target_url = url
    for _redirect in range(MAX_REDIRECTS + 1):
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            with client.stream("GET", target_url) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("Location")
                    if not location:
                        raise RuntimeError("Redirect response missing Location header")
                    next_url = urljoin(target_url, location)
                    target_url = validate_graph_url(next_url, "redirect_url")
                    continue

                response.raise_for_status()
                with destination.open("wb") as output:
                    for chunk in response.iter_bytes(chunk_size):
                        if chunk:
                            output.write(chunk)
                return
    raise RuntimeError("Exceeded redirect limit during download")


def _download_with_retries(
    url: str,
    destination: Path,
    *,
    timeout: float,
    chunk_size: int,
    retries: int,
) -> None:
    """Download with exponential backoff retry strategy."""
    attempt = 0
    backoff = 1.0
    last_error: Exception | None = None
    while attempt <= retries:
        try:
            _stream_download(
                url,
                destination,
                timeout=timeout,
                chunk_size=chunk_size,
            )
            return
        except (httpx.HTTPError, OSError, RuntimeError) as exc:
            last_error = exc
            LOGGER.warning(
                "file_get download attempt failed",
                extra={
                    "attempt": attempt + 1,
                    "retries": retries,
                    "reason": str(exc),
                },
            )
            if destination.exists():
                destination.unlink(missing_ok=True)
            if attempt >= retries:
                break
            time.sleep(backoff)
            backoff *= 2
            attempt += 1
    assert last_error is not None
    raise RuntimeError(f"Failed to download file after retries: {last_error}") from (
        last_error
    )


def download_file(account_id: str, file_id: str, destination: Path) -> dict[str, Any]:
    """Download a OneDrive file to a local destination.

    Fetches the item metadata, enforces the download size limit, validates
    the Graph-supplied download URL and streams it to disk with retries.
    A partially written destination is removed on failure.

    Args:
        account_id: Microsoft account identifier.
        file_id: Validated OneDrive item ID.
        destination: Validated local path to write to.

    Returns:
        Dictionary with ``path``, ``name``, ``size_mb`` and ``mime_type``.

    Raises:
        ValidationError: If the file is missing, too large or its download
            URL is not an allowed Microsoft host.
        RuntimeError: If no download URL exists or the download fails.
    """
    metadata = graph.request("GET", f"/me/drive/items/{file_id}", account_id)
    if not metadata:
        raise ValidationError(
            format_validation_error(
                "file_id",
                file_id,
                "not found in OneDrive",
                "Existing file identifier",
            )
        )

    size_bytes = metadata.get("size", 0) or 0
    size_limit = MAX_DOWNLOAD_MIB * 1024 * 1024
    validate_request_size(size_bytes, size_limit, "download_size")

    download_url = metadata.get("@microsoft.graph.downloadUrl")
    if not download_url:
        raise RuntimeError("No download URL available for this file")
    safe_url = validate_graph_url(download_url, "download_url")

    LOGGER.info(
        "Initiating file download",
        extra={
            "file_id": file_id,
            "account_id": account_id,
            "destination": str(destination),
            "expected_size": size_bytes,
        },
    )

    try:
        _download_with_retries(
            safe_url,
            destination,
            timeout=max(DEFAULT_DOWNLOAD_TIMEOUT, 1.0),
            chunk_size=max(DEFAULT_CHUNK_SIZE, 65536),
            retries=3,
        )
    except Exception as exc:
        LOGGER.error(
            "file_get download failed",
            extra={
                "file_id": file_id,
                "account_id": account_id,
                "destination": str(destination),
            },
        )
        if destination.exists():
            destination.unlink(missing_ok=True)
        if isinstance(exc, ValidationError):
            raise
        raise RuntimeError(f"Failed to download file: {exc}") from exc

    actual_size = destination.stat().st_size
    return {
        "path": str(destination),
        "name": metadata.get("name", "unknown"),
        "size_mb": round(actual_size / (1024 * 1024), 2),
        "mime_type": metadata.get("file", {}).get("mimeType") if metadata else None,
    }


def upload_file(account_id: str, onedrive_path: str, data: bytes) -> dict[str, Any]:
    """Upload content to a OneDrive path, using a session for large files.

    Args:
        account_id: Microsoft account identifier.
        onedrive_path: Validated destination path starting with '/'.
        data: File content to upload.

    Returns:
        Metadata for the created OneDrive file.

    Raises:
        RuntimeError: If Graph returns no metadata.
    """
    result = graph.upload_large_file(
        f"/me/drive/root:{onedrive_path}:", data, account_id
    )
    if not result:
        raise RuntimeError(f"Failed to create file at path: {onedrive_path}")

    _invalidate(account_id, "file_list", "folder_get_tree")
    return result


def replace_file(account_id: str, file_id: str, data: bytes) -> dict[str, Any]:
    """Replace the content of an existing OneDrive file.

    Args:
        account_id: Microsoft account identifier.
        file_id: Validated OneDrive item ID.
        data: Replacement content.

    Returns:
        Updated file metadata returned by Microsoft Graph.

    Raises:
        RuntimeError: If Graph returns no metadata.
    """
    result = graph.upload_large_file(f"/me/drive/items/{file_id}", data, account_id)
    if not result:
        raise RuntimeError(f"Failed to update file with ID: {file_id}")

    _invalidate(account_id, "file_list")
    return result


def delete_item(account_id: str, item_id: str) -> dict[str, str]:
    """Permanently delete a OneDrive file or folder.

    Args:
        account_id: Microsoft account identifier.
        item_id: Validated OneDrive item ID.

    Returns:
        ``{"status": "deleted"}``.
    """
    graph.request("DELETE", f"/me/drive/items/{item_id}", account_id)
    _invalidate(account_id, "file_list", "folder_get_tree")
    return {"status": "deleted"}


def copy_item(
    account_id: str,
    item_id: str,
    destination_folder_id: str,
    *,
    new_name: str | None = None,
) -> dict[str, Any]:
    """Start an asynchronous copy of a OneDrive item.

    Args:
        account_id: Microsoft account identifier.
        item_id: Validated OneDrive item ID to copy.
        destination_folder_id: Validated destination folder ID.
        new_name: Optional (already stripped) name for the copy.

    Returns:
        Graph response, or ``{"status": "copy initiated"}`` when empty.
    """
    payload: dict[str, Any] = {"parentReference": {"id": destination_folder_id}}
    if new_name is not None:
        payload["name"] = new_name

    # Copy is an async operation, returns 202 Accepted with location header
    result = graph.request(
        "POST", f"/me/drive/items/{item_id}/copy", account_id, json=payload
    )

    _invalidate(account_id, "file_list", "folder_get_tree")
    return result if result else {"status": "copy initiated"}


def move_file(
    account_id: str, file_id: str, destination_folder_id: str
) -> dict[str, Any]:
    """Move a OneDrive file to a different parent folder.

    Args:
        account_id: Microsoft account identifier.
        file_id: Validated OneDrive item ID.
        destination_folder_id: Validated destination folder ID.

    Returns:
        Updated file object with the new parentReference.

    Raises:
        ValueError: If Graph returns no result.
    """
    payload = {"parentReference": {"id": destination_folder_id}}
    result = graph.request(
        "PATCH", f"/me/drive/items/{file_id}", account_id, json=payload
    )
    if not result:
        raise ValueError("Failed to move file")

    _invalidate(account_id, "file_list", "folder_get_tree")
    return result


def rename_file(account_id: str, file_id: str, new_name: str) -> dict[str, Any]:
    """Rename a OneDrive file.

    Args:
        account_id: Microsoft account identifier.
        file_id: Validated OneDrive item ID.
        new_name: New (already stripped) file name.

    Returns:
        Updated file object with the new name.

    Raises:
        ValueError: If Graph returns no result.
    """
    result = graph.request(
        "PATCH", f"/me/drive/items/{file_id}", account_id, json={"name": new_name}
    )
    if not result:
        raise ValueError("Failed to rename file")

    _invalidate(account_id, "file_list")
    return result


def create_sharing_link(
    account_id: str,
    file_id: str,
    *,
    permission_type: str,
    scope: str,
) -> dict[str, Any]:
    """Create a sharing link for a OneDrive item.

    Args:
        account_id: Microsoft account identifier.
        file_id: Validated OneDrive item ID.
        permission_type: Link type, "view" or "edit".
        scope: Link scope, "anonymous" or "organization".

    Returns:
        Sharing link details returned by Microsoft Graph.

    Raises:
        ValueError: If Graph returns no result.
    """
    payload = {"type": permission_type, "scope": scope}
    result = graph.request(
        "POST", f"/me/drive/items/{file_id}/createLink", account_id, json=payload
    )
    if not result:
        raise ValueError(f"Failed to create sharing link for file {file_id}")

    return result


def get_download_url(account_id: str, file_id: str) -> dict[str, Any]:
    """Get the pre-authenticated download URL for a OneDrive file.

    Args:
        account_id: Microsoft account identifier.
        file_id: Validated OneDrive item ID.

    Returns:
        Dictionary with ``id``, ``name``, ``size`` and ``download_url``.

    Raises:
        ValueError: If the file is not found or has no download URL.
    """
    params = {"$select": "id,name,size,@microsoft.graph.downloadUrl"}
    result = graph.request(
        "GET", f"/me/drive/items/{file_id}", account_id, params=params
    )
    if not result:
        raise ValueError(f"File with ID {file_id} not found")

    download_url = result.get("@microsoft.graph.downloadUrl")
    if not download_url:
        raise ValueError(f"No download URL available for file {file_id}")

    return {
        "id": result.get("id"),
        "name": result.get("name"),
        "size": result.get("size"),
        "download_url": download_url,
    }


def _list_child_folders(
    account_id: str,
    path: str | None = "/",
    folder_id: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch the child folders of a OneDrive folder from Graph."""
    endpoint = _children_endpoint(path or "/", folder_id)
    page_size = limit if limit is not None else 500
    params = {"$top": page_size, "$select": _FOLDER_SELECT}

    items = list(
        graph.request_paginated(endpoint, account_id, params=params, limit=limit)
    )

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


def list_folders(
    account_id: str,
    *,
    path: str = "/",
    folder_id: str | None = None,
    limit: int = 50,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """List only the folders inside a OneDrive folder.

    Args:
        account_id: Microsoft account identifier.
        path: OneDrive path to list (ignored when folder_id is given).
        folder_id: Folder ID to list; takes precedence over path.
        limit: Maximum number of items to fetch.
        use_cache: Whether to read and write the cache.
        force_refresh: Skip the cache read and fetch from Graph.

    Returns:
        Dictionary with ``folders``, ``_cache_status`` and ``_cached_at``.

    Raises:
        ValidationError: If path is not a valid OneDrive path.
    """
    cache_params = {
        "path": path,
        "folder_id": folder_id,
        "limit": limit,
    }

    if use_cache and not force_refresh:
        try:
            cache_manager = get_cache_manager()
            cached_result = cache_manager.get_cached(
                account_id, "folder_list", cache_params
            )

            if cached_result:
                data, state = cached_result
                return {
                    "folders": data["folders"],
                    "_cache_status": state.value,
                    "_cached_at": data.get("_cached_at"),
                }
        except Exception:
            # If cache fails, continue to API call
            pass

    folders = _list_child_folders(
        account_id=account_id,
        path=path,
        folder_id=folder_id,
        limit=limit,
    )

    result = {
        "folders": folders,
        "_cache_status": "miss",  # Fresh from API
        "_cached_at": datetime.now(timezone.utc).isoformat(),
    }

    if use_cache:
        try:
            cache_manager = get_cache_manager()
            cache_manager.set_cached(account_id, "folder_list", cache_params, result)
        except Exception:
            # If cache storage fails, still return the result
            pass

    return result


def get_folder(
    account_id: str,
    *,
    folder_id: str | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    """Get metadata for a OneDrive folder by ID or path.

    Args:
        account_id: Microsoft account identifier.
        folder_id: Folder ID; takes precedence over path.
        path: OneDrive folder path.

    Returns:
        Folder summary including childCount, parent info and webUrl.

    Raises:
        ValueError: If the folder is not found or the item is not a folder.
        ValidationError: If path is not a valid OneDrive path.
    """
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


def get_folder_tree(
    account_id: str,
    *,
    path: str = "/",
    folder_id: str | None = None,
    max_depth: int = 10,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Recursively build a tree of OneDrive folders.

    Branches whose listing fails are returned as empty rather than
    failing the whole tree.

    Args:
        account_id: Microsoft account identifier.
        path: Starting path (ignored when folder_id is given).
        folder_id: Starting folder ID; takes precedence over path.
        max_depth: Maximum recursion depth.
        use_cache: Whether to read and write the cache.
        force_refresh: Skip the cache read and fetch from Graph.

    Returns:
        Dictionary with ``root_folder_id``, ``root_path``, ``max_depth``,
        nested ``folders``, ``_cache_status`` and ``_cached_at``.

    Raises:
        ValidationError: If path is not a valid OneDrive path.
    """
    cache_params = {
        "path": path,
        "folder_id": folder_id,
        "max_depth": max_depth,
    }

    if use_cache and not force_refresh:
        try:
            cache_manager = get_cache_manager()
            cached_result = cache_manager.get_cached(
                account_id, "folder_get_tree", cache_params
            )

            if cached_result:
                data, state = cached_result
                data["_cache_status"] = state.value
                return data
        except Exception:
            # If cache fails, continue to API call
            pass

    def _build_drive_folder_tree(
        item_id: str | None, item_path: str | None, current_depth: int
    ) -> list[dict[str, Any]]:
        """Internal recursive helper to build OneDrive folder tree"""
        if current_depth >= max_depth:
            return []

        try:
            folders = _list_child_folders(
                account_id=account_id,
                path=item_path if not item_id else None,
                folder_id=item_id,
                limit=None,
            )
        except Exception:
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

            # Always recurse; childCount includes files so it cannot
            # tell whether subfolders exist.
            folder_node["children"] = _build_drive_folder_tree(
                folder["id"], None, current_depth + 1
            )

            result.append(folder_node)

        return result

    if folder_id:
        start_id = folder_id
        start_path: str | None = None
    else:
        start_id = None
        start_path = validate_onedrive_path(path or "/", "path")

    tree_data = _build_drive_folder_tree(start_id, start_path, 0)

    result = {
        "root_folder_id": folder_id,
        "root_path": start_path if start_path is not None else None,
        "max_depth": max_depth,
        "folders": tree_data,
        "_cache_status": "miss",  # Fresh from API
        "_cached_at": datetime.now(timezone.utc).isoformat(),
    }

    if use_cache:
        try:
            cache_manager = get_cache_manager()
            cache_manager.set_cached(
                account_id, "folder_get_tree", cache_params, result
            )
        except Exception:
            # If cache storage fails, still return the result
            pass

    return result


def create_folder(
    account_id: str,
    name: str,
    *,
    parent_folder_id: str | None = None,
) -> dict[str, Any]:
    """Create a OneDrive folder, renaming on conflict.

    Args:
        account_id: Microsoft account identifier.
        name: Folder name (already stripped).
        parent_folder_id: Validated parent folder ID, or None for root.

    Returns:
        Created folder object returned by Microsoft Graph.

    Raises:
        ValueError: If Graph returns no result.
    """
    if parent_folder_id:
        endpoint = f"/me/drive/items/{parent_folder_id}/children"
    else:
        endpoint = "/me/drive/root/children"

    payload = {
        "name": name,
        "folder": {},  # This tells Graph API to create a folder
        "@microsoft.graph.conflictBehavior": "rename",
    }

    result = graph.request("POST", endpoint, account_id, json=payload)
    if not result:
        raise ValueError("Failed to create folder")
    return result


def delete_folder(account_id: str, folder_id: str) -> dict[str, str]:
    """Permanently delete a OneDrive folder and its contents.

    Args:
        account_id: Microsoft account identifier.
        folder_id: Validated folder ID.

    Returns:
        ``{"status": "deleted", "folder_id": folder_id}``.
    """
    graph.request("DELETE", f"/me/drive/items/{folder_id}", account_id)
    return {"status": "deleted", "folder_id": folder_id}


def rename_folder(account_id: str, folder_id: str, new_name: str) -> dict[str, Any]:
    """Rename a OneDrive folder.

    Args:
        account_id: Microsoft account identifier.
        folder_id: Validated folder ID.
        new_name: New (already stripped) folder name.

    Returns:
        Updated folder object with the new name.

    Raises:
        ValueError: If Graph returns no result.
    """
    result = graph.request(
        "PATCH", f"/me/drive/items/{folder_id}", account_id, json={"name": new_name}
    )
    if not result:
        raise ValueError("Failed to rename folder")

    return result


def move_folder(
    account_id: str, folder_id: str, destination_folder_id: str
) -> dict[str, Any]:
    """Move a OneDrive folder under a different parent.

    Args:
        account_id: Microsoft account identifier.
        folder_id: Validated folder ID.
        destination_folder_id: Validated destination parent folder ID.

    Returns:
        Updated folder object with the new parentReference.

    Raises:
        ValueError: If Graph returns no result.
    """
    payload = {"parentReference": {"id": destination_folder_id}}
    result = graph.request(
        "PATCH", f"/me/drive/items/{folder_id}", account_id, json=payload
    )
    if not result:
        raise ValueError("Failed to move folder")

    return result
