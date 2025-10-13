from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

from .. import graph
from ..mcp_instance import mcp
from ..validators import (
    ValidationError,
    ensure_safe_path,
    format_validation_error,
    require_confirm,
    validate_account_id,
    validate_graph_url,
    validate_limit,
    validate_microsoft_graph_id,
    validate_onedrive_path,
    validate_request_size,
)

LOGGER = logging.getLogger("microsoft_mcp.tools.file")

DEFAULT_DOWNLOAD_TIMEOUT = float(os.getenv("MCP_FILE_DOWNLOAD_TIMEOUT", "60.0"))
DEFAULT_CHUNK_SIZE = int(os.getenv("MCP_FILE_DOWNLOAD_CHUNK_SIZE", "1048576"))
MAX_DOWNLOAD_MIB = int(os.getenv("MCP_FILE_DOWNLOAD_MAX_MB", "512"))
MAX_REDIRECTS = 3


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
        limit: Maximum items to return (1-500, default: 50)
        type_filter: Filter by type - "all", "files", or "folders" (default: "all")

    Returns:
        List of items matching the filter criteria
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

    # Determine endpoint
    if folder_id:
        endpoint = f"/me/drive/items/{folder_id}/children"
    else:
        validated_path = validate_onedrive_path(path, "path")
        if validated_path == "/":
            endpoint = "/me/drive/root/children"
        else:
            endpoint = f"/me/drive/root:{validated_path}:/children"

    params = {
        "$top": limit,
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


def _stream_download(
    url: str,
    destination: Path,
    *,
    timeout: float,
    chunk_size: int,
) -> None:
    """Stream file contents from a validated URL to destination path."""
    target_url = url
    for redirect in range(MAX_REDIRECTS + 1):
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


def _file_get_impl(file_id: str, account_id: str, download_path: str) -> dict[str, Any]:
    account = validate_account_id(account_id)
    graph_file_id = validate_microsoft_graph_id(file_id, "file_id")
    destination = ensure_safe_path(download_path, allow_overwrite=False)
    destination.parent.mkdir(parents=True, exist_ok=True)

    metadata = graph.request("GET", f"/me/drive/items/{graph_file_id}", account)
    if not metadata:
        raise ValidationError(
            format_validation_error(
                "file_id",
                graph_file_id,
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
            "file_id": graph_file_id,
            "account_id": account,
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
    except Exception as exc:  # noqa: BLE001
        LOGGER.error(
            "file_get download failed",
            extra={
                "file_id": graph_file_id,
                "account_id": account,
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
    """Download a OneDrive file to a validated local path.

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
    """Upload a validated local file to OneDrive.

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
    result = graph.upload_large_file(f"/me/drive/root:{target}:", data, account)
    if not result:
        raise RuntimeError(f"Failed to create file at path: {target}")
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
    """Replace OneDrive file content from a validated local source.

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
    result = graph.upload_large_file(
        f"/me/drive/items/{graph_file_id}",
        data,
        account,
    )
    if not result:
        raise RuntimeError(f"Failed to update file with ID: {graph_file_id}")
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
    """Delete a OneDrive file or folder after explicit confirmation."""

    require_confirm(confirm, "delete OneDrive item")
    account = validate_account_id(account_id)
    graph_file_id = validate_microsoft_graph_id(file_id, "file_id")
    graph.request("DELETE", f"/me/drive/items/{graph_file_id}", account)
    return {"status": "deleted"}


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
