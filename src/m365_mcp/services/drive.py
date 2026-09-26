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
from urllib.parse import quote, urljoin

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


# ----------------------------------------------------------------------
# Unified tool surface (drive_item resource and drive_* tools)
# ----------------------------------------------------------------------

ROOT_ALIAS = "root"
# drive_upload: simple PUT up to 4 MB, upload session above (concept §8.13).
SIMPLE_UPLOAD_MAX_BYTES = 4 * 1024 * 1024
_CHILDREN_PAGE_SIZE = 200
_DOWNLOAD_URL_SELECT = "id,name,size,folder,file,@microsoft.graph.downloadUrl"


def max_download_mib() -> int:
    """Return the download size limit in MiB (``MCP_FILE_DOWNLOAD_MAX_MB``)."""
    return int(os.getenv("MCP_FILE_DOWNLOAD_MAX_MB", "512"))


def _item_base(item_id: str | None = None, path: str | None = None) -> str:
    """Return the Graph path of an item given by ID, ``root`` or path.

    Args:
        item_id: Item ID or the ``root`` alias.
        path: Normalised OneDrive path (``/`` or ``/A/B``) instead of an ID.

    Returns:
        ``/me/drive/root``, ``/me/drive/root:{path}`` or
        ``/me/drive/items/{id}``.
    """
    if path is not None:
        return "/me/drive/root" if path == "/" else f"/me/drive/root:{quote(path)}"
    if item_id is None or item_id == ROOT_ALIAS:
        return "/me/drive/root"
    return f"/me/drive/items/{item_id}"


def _children_path(item_id: str | None = None, path: str | None = None) -> str:
    base = _item_base(item_id, path)
    if base.startswith("/me/drive/root:"):
        return f"{base}:/children"
    return f"{base}/children"


def _send_json(
    method: str, path: str, account_id: str, body: dict[str, Any]
) -> httpx.Response:
    """Send a JSON request and return the response (status and headers)."""
    return graph._send(
        method,
        f"{graph.BASE_URL}{path}",
        account_id,
        headers={"Content-Type": "application/json"},
        json=body,
    )


def get_drive_item(
    account_id: str, *, item_id: str | None = None, path: str | None = None
) -> dict[str, Any]:
    """Read one OneDrive item by ID, ``root`` alias or path.

    Args:
        account_id: Microsoft account identifier.
        item_id: Item ID or ``root``.
        path: Normalised OneDrive path instead of ``item_id``.

    Returns:
        The Graph driveItem.
    """
    return graph.request("GET", _item_base(item_id, path), account_id) or {}


def list_drive_children_page(
    account_id: str,
    *,
    item_id: str | None = None,
    path: str | None = None,
    limit: int = 20,
    next_link: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Read one page of a folder's children, ordered by name.

    Args:
        account_id: Microsoft account identifier.
        item_id: Folder ID or ``root`` (default: root).
        path: Normalised folder path instead of ``item_id``.
        limit: Page size.
        next_link: Graph ``@odata.nextLink`` from the previous page.

    Returns:
        The Graph driveItems on this page and the next page's link.
    """
    if next_link:
        result = graph.request("GET", next_link.replace(graph.BASE_URL, ""), account_id)
    else:
        params = {"$top": limit, "$orderby": "name"}
        result = graph.request(
            "GET", _children_path(item_id, path), account_id, params=params
        )
    result = result or {}
    return list(result.get("value") or []), result.get("@odata.nextLink")


def list_all_drive_children(
    account_id: str, *, item_id: str | None = None, path: str | None = None
) -> list[dict[str, Any]]:
    """Read every child of a folder, ordered by name, following nextLinks.

    Args:
        account_id: Microsoft account identifier.
        item_id: Folder ID or ``root`` (default: root).
        path: Normalised folder path instead of ``item_id``.

    Returns:
        The Graph driveItems.
    """
    params = {"$top": _CHILDREN_PAGE_SIZE, "$orderby": "name"}
    return list(
        graph.request_paginated(
            _children_path(item_id, path), account_id, params=params
        )
    )


def create_drive_folder(
    account_id: str,
    name: str,
    *,
    parent_id: str | None = None,
    parent_path: str | None = None,
    conflict: str = "fail",
) -> dict[str, Any]:
    """Create a folder (``POST .../children`` with a folder facet).

    Args:
        account_id: Microsoft account identifier.
        name: Folder name.
        parent_id: Parent folder ID or ``root`` (default: root).
        parent_path: Normalised parent path instead of ``parent_id``.
        conflict: ``@microsoft.graph.conflictBehavior`` (``fail`` or
            ``rename``).

    Returns:
        The created Graph driveItem.

    Raises:
        GraphAPIError: 409 when the name exists and ``conflict`` is fail.
    """
    body = {"name": name, "folder": {}, "@microsoft.graph.conflictBehavior": conflict}
    path = _children_path(parent_id, parent_path)
    return graph.request("POST", path, account_id, json=body) or {}


def patch_drive_item(
    account_id: str, item_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    """Patch a OneDrive item (rename and/or ``parentReference`` move).

    Args:
        account_id: Microsoft account identifier.
        item_id: Item ID.
        body: Graph driveItem fields.

    Returns:
        The updated Graph driveItem.
    """
    path = f"/me/drive/items/{item_id}"
    return graph.request("PATCH", path, account_id, json=body) or {}


def delete_drive_item(account_id: str, item_id: str) -> None:
    """Delete a OneDrive item; OneDrive moves it to the recycle bin."""
    graph.request("DELETE", f"/me/drive/items/{item_id}", account_id)


def get_drive_download_url(account_id: str, item_id: str) -> dict[str, Any]:
    """Read a file's size, facets and pre-authenticated download URL.

    Args:
        account_id: Microsoft account identifier.
        item_id: Item ID.

    Returns:
        The Graph driveItem with ``@microsoft.graph.downloadUrl`` (files).
    """
    params = {"$select": _DOWNLOAD_URL_SELECT}
    return graph.request("GET", _item_base(item_id), account_id, params=params) or {}


def download_drive_file(download_url: str, destination: Path) -> int:
    """Stream a file's download URL to ``destination``.

    The content is written to a temporary sibling first and moved into
    place only when complete, so a failed download never leaves a partial
    file or destroys an existing one.

    Args:
        download_url: ``@microsoft.graph.downloadUrl`` of the file.
        destination: Validated local path.

    Returns:
        The number of bytes written.

    Raises:
        ValidationError: If the URL is not on an approved Microsoft host.
        RuntimeError: If the download fails after retries.
    """
    safe_url = validate_graph_url(download_url, "download_url")
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".m365-partial")
    try:
        _download_with_retries(
            safe_url,
            partial,
            timeout=max(DEFAULT_DOWNLOAD_TIMEOUT, 1.0),
            chunk_size=max(DEFAULT_CHUNK_SIZE, 65536),
            retries=3,
        )
        os.replace(partial, destination)
    finally:
        partial.unlink(missing_ok=True)
    return destination.stat().st_size


def _upload_session(upload_url: str, local_path: Path, size: int) -> httpx.Response:
    """Send a file to an upload session in 15 x 320 KiB chunks.

    The upload URL is pre-authenticated, so no Authorization header is
    sent. Chunks are read from disk one at a time.
    """
    with local_path.open("rb") as source:
        for start in range(0, size, graph.UPLOAD_CHUNK_SIZE):
            chunk = source.read(graph.UPLOAD_CHUNK_SIZE)
            end = start + len(chunk) - 1
            response = graph._send(
                "PUT",
                upload_url,
                None,
                headers={
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {start}-{end}/{size}",
                },
                authenticate=False,
                transfer=True,
                content=chunk,
            )
            if response.status_code in (200, 201):
                return response
    raise RuntimeError("Upload finished without a final response")


def upload_drive_file(
    account_id: str,
    local_path: Path,
    *,
    item_id: str | None = None,
    parent_id: str | None = None,
    name: str | None = None,
    conflict: str = "fail",
) -> tuple[int, dict[str, Any]]:
    """Upload a local file as a new file or over an existing one.

    Files up to 4 MB use a single ``PUT .../content``; larger files use an
    upload session (``createUploadSession`` plus chunks).

    Args:
        account_id: Microsoft account identifier.
        local_path: Validated local file.
        item_id: Existing file whose contents are replaced, or
        parent_id: destination folder ID (or ``root``) for a new file named
        name: the new file's name.
        conflict: ``@microsoft.graph.conflictBehavior`` for a new file
            (``fail``, ``replace`` or ``rename``).

    Returns:
        The final HTTP status (201 created, 200 replaced) and the Graph
        driveItem.

    Raises:
        GraphAPIError: 409 when the name exists and ``conflict`` is fail.
    """
    if item_id is not None:
        base = f"/me/drive/items/{item_id}"
        properties: dict[str, Any] = {}
        params: dict[str, str] = {}
    else:
        base = f"/me/drive/items/{parent_id}:/{quote(name or '', safe='')}:"
        properties = {"@microsoft.graph.conflictBehavior": conflict}
        params = {"@microsoft.graph.conflictBehavior": conflict}
    size = local_path.stat().st_size
    if size <= SIMPLE_UPLOAD_MAX_BYTES:
        response = graph._send(
            "PUT",
            f"{graph.BASE_URL}{base}/content",
            account_id,
            headers={"Content-Type": "application/octet-stream"},
            params=params,
            content=local_path.read_bytes(),
        )
    else:
        session = graph.create_upload_session(base, account_id, properties)
        response = _upload_session(session["uploadUrl"], local_path, size)
    return response.status_code, (response.json() if response.content else {})


def start_drive_copy(
    account_id: str,
    item_id: str,
    parent_reference: dict[str, Any],
    new_name: str | None = None,
) -> str:
    """Start a background copy (``POST /me/drive/items/{id}/copy``).

    Args:
        account_id: Microsoft account identifier.
        item_id: Item to copy.
        parent_reference: Graph ``parentReference`` of the destination.
        new_name: Optional name for the copy.

    Returns:
        The monitor URL from the ``Location`` header.

    Raises:
        RuntimeError: If Graph returned no monitor URL.
    """
    body: dict[str, Any] = {"parentReference": parent_reference}
    if new_name is not None:
        body["name"] = new_name
    response = _send_json("POST", f"/me/drive/items/{item_id}/copy", account_id, body)
    location = response.headers.get("Location")
    if not location:
        raise RuntimeError("OneDrive returned no copy monitor URL")
    return location


def create_drive_link(
    account_id: str, item_id: str, body: dict[str, Any]
) -> tuple[bool, dict[str, Any]]:
    """Create (or fetch the existing) sharing link of a type.

    Args:
        account_id: Microsoft account identifier.
        item_id: Item to share.
        body: Graph ``createLink`` body (type, scope, password, expiry).

    Returns:
        Whether a new link was created (201; 200 means an existing link of
        that type was returned) and the Graph permission.
    """
    path = f"/me/drive/items/{item_id}/createLink"
    response = _send_json("POST", path, account_id, body)
    return response.status_code == 201, (response.json() if response.content else {})


def invite_drive_recipients(
    account_id: str, item_id: str, body: dict[str, Any]
) -> list[dict[str, Any]]:
    """Grant named people access (``POST /me/drive/items/{id}/invite``).

    Args:
        account_id: Microsoft account identifier.
        item_id: Item to share.
        body: Graph ``invite`` body.

    Returns:
        One entry per recipient, in request order when Graph returns one
        per recipient: a permission, or ``{"error": ...}`` for a recipient
        that failed (207 partial success).
    """
    path = f"/me/drive/items/{item_id}/invite"
    result = graph.request("POST", path, account_id, json=body) or {}
    return list(result.get("value") or [])
