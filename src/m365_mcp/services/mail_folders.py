"""Mail folder service functions over Microsoft Graph."""

from typing import Any

from .. import graph

_FOLDER_SELECT = (
    "id,displayName,childFolderCount,unreadItemCount,totalItemCount,"
    "parentFolderId,isHidden"
)


def _folders_endpoint(parent_folder_id: str | None) -> str:
    """Return the root or child mail folder collection endpoint."""
    if parent_folder_id:
        return f"/me/mailFolders/{parent_folder_id}/childFolders"
    return "/me/mailFolders"


def list_folders(
    account_id: str,
    *,
    parent_folder_id: str | None = None,
    include_hidden: bool = False,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """List root mail folders or the child folders of a parent.

    Args:
        account_id: Microsoft account ID.
        parent_folder_id: Parent folder ID; None lists root folders.
        include_hidden: Whether to include hidden folders.
        limit: Maximum folders to return; None returns all.

    Returns:
        List of Graph mailFolder objects.
    """
    endpoint = _folders_endpoint(parent_folder_id)

    page_size = limit if limit is not None else 250
    params: dict[str, Any] = {
        "$select": _FOLDER_SELECT,
        "$top": page_size,
    }

    if include_hidden:
        params["includeHiddenFolders"] = "true"

    return list(
        graph.request_paginated(endpoint, account_id, params=params, limit=limit)
    )


def get_folder(account_id: str, *, folder_id: str) -> dict[str, Any]:
    """Get a single mail folder.

    Args:
        account_id: Microsoft account ID.
        folder_id: The folder ID to retrieve.

    Returns:
        Graph mailFolder object.

    Raises:
        ValueError: If Graph returns no folder.
    """
    result = graph.request("GET", f"/me/mailFolders/{folder_id}", account_id)
    if not result:
        raise ValueError(f"Mail folder with ID {folder_id} not found")
    return result


def create_folder(
    account_id: str,
    *,
    display_name: str,
    parent_folder_id: str | None = None,
) -> dict[str, Any]:
    """Create a mail folder at root level or under a parent.

    Args:
        account_id: Microsoft account ID.
        display_name: Name for the new folder.
        parent_folder_id: Parent folder ID; None creates at root level.

    Returns:
        Created Graph mailFolder object.

    Raises:
        ValueError: If Graph returns no folder.
    """
    endpoint = _folders_endpoint(parent_folder_id)
    payload = {"displayName": display_name}

    result = graph.request("POST", endpoint, account_id, json=payload)

    if not result:
        raise ValueError("Failed to create mail folder")

    return result


def rename_folder(
    account_id: str, *, folder_id: str, new_display_name: str
) -> dict[str, Any]:
    """Rename a mail folder.

    Args:
        account_id: Microsoft account ID.
        folder_id: The folder ID to rename.
        new_display_name: New name for the folder.

    Returns:
        Updated Graph mailFolder object.

    Raises:
        ValueError: If Graph returns no folder.
    """
    payload = {"displayName": new_display_name}

    result = graph.request(
        "PATCH", f"/me/mailFolders/{folder_id}", account_id, json=payload
    )

    if not result:
        raise ValueError(f"Failed to rename mail folder {folder_id}")

    return result


def delete_folder(account_id: str, *, folder_id: str) -> dict[str, str]:
    """Delete a mail folder and its contents.

    Args:
        account_id: Microsoft account ID.
        folder_id: The folder ID to delete.

    Returns:
        Status dict with status and folder_id.
    """
    graph.request("DELETE", f"/me/mailFolders/{folder_id}", account_id)

    return {"status": "deleted", "folder_id": folder_id}


# ----------------------------------------------------------------------
# Unified tool surface (m365_* tools)
# ----------------------------------------------------------------------


def list_folders_page(
    account_id: str,
    *,
    parent_folder_id: str | None = None,
    include_hidden: bool = False,
    top: int = 20,
    next_link: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Fetch one page of top-level or child mail folders.

    Args:
        account_id: Microsoft account ID.
        parent_folder_id: Parent folder ID or well-known name; None lists
            the top level.
        include_hidden: Whether to include hidden folders.
        top: Page size.
        next_link: Graph ``@odata.nextLink`` of a previous page; when set,
            the other query arguments are ignored.

    Returns:
        The Graph mailFolder objects of the page and the next page's link.
    """
    if next_link:
        result = graph.request("GET", next_link.replace(graph.BASE_URL, ""), account_id)
    else:
        params: dict[str, Any] = {"$select": _FOLDER_SELECT, "$top": top}
        if include_hidden:
            params["includeHiddenFolders"] = "true"
        result = graph.request(
            "GET", _folders_endpoint(parent_folder_id), account_id, params=params
        )
    result = result or {}
    return list(result.get("value", [])), result.get("@odata.nextLink")


def move_folder_to(
    account_id: str, *, folder_id: str, destination_id: str
) -> dict[str, Any]:
    """Move a mail folder under another folder (``POST .../move``).

    Args:
        account_id: Microsoft account ID.
        folder_id: The folder to move.
        destination_id: Destination parent folder ID or well-known name.

    Returns:
        The moved Graph mailFolder object.

    Raises:
        ValueError: If Graph returns no folder.
    """
    result = graph.request(
        "POST",
        f"/me/mailFolders/{folder_id}/move",
        account_id,
        json={"destinationId": destination_id},
    )
    if not result or "id" not in result:
        raise ValueError(f"Failed to move mail folder {folder_id}")
    return result
