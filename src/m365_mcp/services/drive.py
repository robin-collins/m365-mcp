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
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

import httpx

from .. import graph
from ..validators import (
    validate_graph_url,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_DOWNLOAD_TIMEOUT = float(os.getenv("MCP_FILE_DOWNLOAD_TIMEOUT", "60.0"))
DEFAULT_CHUNK_SIZE = int(os.getenv("MCP_FILE_DOWNLOAD_CHUNK_SIZE", "1048576"))
MAX_REDIRECTS = 3


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
        with (
            httpx.Client(timeout=timeout, follow_redirects=False) as client,
            client.stream("GET", target_url) as response,
        ):
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
