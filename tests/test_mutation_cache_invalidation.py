from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.m365_mcp.cache import CacheManager
from src.m365_mcp.tools import email as email_tools
from src.m365_mcp.tools import file as file_tools


@pytest.fixture
def cache_manager(tmp_path: Path) -> CacheManager:
    return CacheManager(
        db_path=str(tmp_path / "mutation_cache.db"),
        encryption_enabled=False,
    )


def test_email_delete_invalidates_email_lists_for_only_target_account(
    monkeypatch: pytest.MonkeyPatch,
    cache_manager: CacheManager,
) -> None:
    target_account = "target@example.com"
    other_account = "other@example.com"
    params = {"folder": "inbox", "limit": 10}

    cache_manager.set_cached(target_account, "email_list", params, {"messages": []})
    cache_manager.set_cached(other_account, "email_list", params, {"messages": []})

    def fake_request(
        method: str,
        path: str,
        account_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, str]:
        assert method == "DELETE"
        assert path == "/me/messages/message-1"
        assert account_id == target_account
        return {}

    monkeypatch.setattr(email_tools.graph, "request", fake_request)
    monkeypatch.setattr(email_tools, "get_cache_manager", lambda: cache_manager)

    result = email_tools.email_delete.fn(
        email_id="message-1",
        account_id=target_account,
        confirm=True,
    )

    assert result == {"status": "deleted"}
    assert cache_manager.get_cached(target_account, "email_list", params) is None
    assert cache_manager.get_cached(other_account, "email_list", params) is not None


def test_email_update_invalidates_email_get_entries_for_only_target_account(
    monkeypatch: pytest.MonkeyPatch,
    cache_manager: CacheManager,
) -> None:
    target_account = "target@example.com"
    other_account = "other@example.com"
    params = {"email_id": "message-1", "include_body": True}

    cache_manager.set_cached(target_account, "email_get", params, {"id": "message-1"})
    cache_manager.set_cached(other_account, "email_get", params, {"id": "message-1"})

    def fake_request(
        method: str,
        path: str,
        account_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, str]:
        assert method == "PATCH"
        assert path == "/me/messages/message-1"
        assert account_id == target_account
        assert kwargs["json"] == {"isRead": True}
        return {"id": "message-1"}

    monkeypatch.setattr(email_tools.graph, "request", fake_request)
    monkeypatch.setattr(email_tools, "get_cache_manager", lambda: cache_manager)

    result = email_tools.email_update.fn(
        email_id="message-1",
        updates={"isRead": True},
        account_id=target_account,
    )

    assert result == {"id": "message-1"}
    assert cache_manager.get_cached(target_account, "email_get", params) is None
    assert cache_manager.get_cached(other_account, "email_get", params) is not None


def test_file_delete_invalidates_file_and_folder_lists_for_only_target_account(
    monkeypatch: pytest.MonkeyPatch,
    cache_manager: CacheManager,
) -> None:
    target_account = "target@example.com"
    other_account = "other@example.com"
    file_params = {"path": "/", "limit": 50}
    folder_params = {"path": "/", "max_depth": 10}

    cache_manager.set_cached(target_account, "file_list", file_params, {"files": []})
    cache_manager.set_cached(other_account, "file_list", file_params, {"files": []})
    cache_manager.set_cached(
        target_account,
        "folder_get_tree",
        folder_params,
        {"folders": []},
    )
    cache_manager.set_cached(
        other_account,
        "folder_get_tree",
        folder_params,
        {"folders": []},
    )

    def fake_request(
        method: str,
        path: str,
        account_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, str]:
        assert method == "DELETE"
        assert path == "/me/drive/items/file-1"
        assert account_id == target_account
        return {}

    monkeypatch.setattr(file_tools.graph, "request", fake_request)
    monkeypatch.setattr(file_tools, "get_cache_manager", lambda: cache_manager)

    result = file_tools.file_delete.fn(
        file_id="file-1",
        account_id=target_account,
        confirm=True,
    )

    assert result == {"status": "deleted"}
    assert cache_manager.get_cached(target_account, "file_list", file_params) is None
    assert cache_manager.get_cached(target_account, "folder_get_tree", folder_params) is None
    assert cache_manager.get_cached(other_account, "file_list", file_params) is not None
    assert (
        cache_manager.get_cached(other_account, "folder_get_tree", folder_params)
        is not None
    )


def test_file_rename_invalidates_file_lists_for_only_target_account(
    monkeypatch: pytest.MonkeyPatch,
    cache_manager: CacheManager,
) -> None:
    target_account = "target@example.com"
    other_account = "other@example.com"
    params = {"path": "/", "limit": 50}

    cache_manager.set_cached(target_account, "file_list", params, {"files": []})
    cache_manager.set_cached(other_account, "file_list", params, {"files": []})

    def fake_request(
        method: str,
        path: str,
        account_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        assert method == "PATCH"
        assert path == "/me/drive/items/file-1"
        assert account_id == target_account
        assert kwargs["json"] == {"name": "renamed.txt"}
        return {
            "id": "file-1",
            "name": "renamed.txt",
            "parentReference": {"id": "folder-1"},
        }

    monkeypatch.setattr(file_tools.graph, "request", fake_request)
    monkeypatch.setattr(file_tools, "get_cache_manager", lambda: cache_manager)

    result = file_tools.file_rename.fn(
        file_id="file-1",
        new_name=" renamed.txt ",
        account_id=target_account,
    )

    assert result["name"] == "renamed.txt"
    assert cache_manager.get_cached(target_account, "file_list", params) is None
    assert cache_manager.get_cached(other_account, "file_list", params) is not None
