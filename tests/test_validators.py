from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.microsoft_mcp import validators


def test_ensure_safe_path_allows_workspace(tmp_path: Path) -> None:
    target = tmp_path / "example.txt"
    resolved = validators.ensure_safe_path(target, allow_overwrite=True)
    assert resolved == target.resolve()


def test_ensure_safe_path_rejects_traversal(tmp_path: Path) -> None:
    target = tmp_path / ".." / "evil.txt"
    with pytest.raises(validators.ValidationError):
        validators.ensure_safe_path(target)


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific validation")
def test_ensure_safe_path_rejects_reserved_windows_names(tmp_path: Path) -> None:
    target = tmp_path / "CON.txt"
    with pytest.raises(validators.ValidationError):
        validators.ensure_safe_path(target)


def test_validate_graph_url_accepts_allowed_domain() -> None:
    url = "https://graph.microsoft.com/v1.0/me"
    assert validators.validate_graph_url(url) == url


def test_validate_graph_url_rejects_external_host() -> None:
    with pytest.raises(validators.ValidationError):
        validators.validate_graph_url("https://example.com/resource")


def test_validate_onedrive_path_normalises() -> None:
    path = validators.validate_onedrive_path("/Documents/Sub/File.txt")
    assert path == "/Documents/Sub/File.txt"


def test_validate_onedrive_path_rejects_parent_segments() -> None:
    with pytest.raises(validators.ValidationError):
        validators.validate_onedrive_path("/Documents/../secret.txt")


def test_validate_request_size_enforces_limit() -> None:
    validators.validate_request_size(1024, 4096)
    with pytest.raises(validators.ValidationError):
        validators.validate_request_size(8192, 4096)
