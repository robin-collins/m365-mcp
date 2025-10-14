from __future__ import annotations

import pytest

from src.m365_mcp.tools import email_folders as email_folder_tools
from src.m365_mcp.tools import file as file_tools
from src.m365_mcp.tools import folder as folder_tools
from src.m365_mcp.validators import ValidationError


def test_folder_list_rejects_invalid_limit(mock_account_id: str) -> None:
    with pytest.raises(ValidationError):
        folder_tools.folder_list.fn(account_id=mock_account_id, limit=0)


def test_folder_get_tree_rejects_invalid_depth(mock_account_id: str) -> None:
    with pytest.raises(ValidationError):
        folder_tools.folder_get_tree.fn(
            account_id=mock_account_id,
            max_depth=0,
        )


def test_emailfolders_list_rejects_invalid_limit(mock_account_id: str) -> None:
    with pytest.raises(ValidationError):
        email_folder_tools.emailfolders_list.fn(account_id=mock_account_id, limit=0)


def test_emailfolders_get_tree_rejects_invalid_depth(mock_account_id: str) -> None:
    with pytest.raises(ValidationError):
        email_folder_tools.emailfolders_get_tree.fn(
            account_id=mock_account_id,
            max_depth=0,
        )


def test_file_list_rejects_relative_path(mock_account_id: str) -> None:
    with pytest.raises(ValidationError):
        file_tools.file_list.fn(
            account_id=mock_account_id,
            path="Documents",
        )


def test_folder_list_rejects_relative_path(mock_account_id: str) -> None:
    with pytest.raises(ValidationError):
        folder_tools.folder_list.fn(
            account_id=mock_account_id,
            path="Documents/Work",
        )


def test_folder_get_rejects_relative_path(mock_account_id: str) -> None:
    with pytest.raises(ValidationError):
        folder_tools.folder_get.fn(
            account_id=mock_account_id,
            path="Projects/2024",
        )
