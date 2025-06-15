from typing import Any
from .graph import _request


def create_folder(
    parent_path: str, folder_name: str, account_id: str | None = None
) -> dict[str, Any]:
    data = {
        "name": folder_name,
        "folder": {},
        "@microsoft.graph.conflictBehavior": "rename",
    }

    if parent_path == "/":
        path = "/me/drive/root/children"
    else:
        path = f"/me/drive/root:/{parent_path}:/children"

    result = _request("POST", path, account_id=account_id, data=data)
    return result or {}


def move_item(
    item_id: str,
    new_parent_id: str,
    new_name: str | None = None,
    account_id: str | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {"parentReference": {"id": new_parent_id}}

    if new_name:
        data["name"] = new_name

    result = _request(
        "PATCH", f"/me/drive/items/{item_id}", account_id=account_id, data=data
    )
    return result or {}


def delete_item(item_id: str, account_id: str | None = None) -> None:
    _request("DELETE", f"/me/drive/items/{item_id}", account_id=account_id)


def get_item_by_path(path: str, account_id: str | None = None) -> dict[str, Any]:
    result = _request("GET", f"/me/drive/root:/{path}", account_id=account_id)
    return result or {}


def list_folder_contents(
    folder_id: str | None = None, path: str | None = None, account_id: str | None = None
) -> dict[str, Any]:
    if folder_id:
        endpoint = f"/me/drive/items/{folder_id}/children"
    elif path:
        endpoint = f"/me/drive/root:/{path}:/children"
    else:
        endpoint = "/me/drive/root/children"

    result = _request("GET", endpoint, account_id=account_id)
    return result or {}
