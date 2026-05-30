from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.m365_mcp import validators


pytestmark = pytest.mark.skipif(
    os.name != "nt",
    reason="Windows-specific filesystem validation scaffolding",
)


@pytest.mark.xfail(
    reason=(
        "Finding 2: ensure_safe_path currently treats the Windows drive root "
        "as an alternate data stream segment."
    ),
    strict=True,
)
def test_windows_absolute_path_under_allowed_root_is_accepted(
    tmp_path: Path,
) -> None:
    """Document the expected behavior for normal Windows absolute paths."""
    target = tmp_path / "normal-file.txt"

    resolved = validators.ensure_safe_path(
        target,
        allow_overwrite=True,
        allowed_roots=[tmp_path],
    )

    assert resolved == target.resolve(strict=False)


def test_windows_alternate_data_stream_path_is_rejected(tmp_path: Path) -> None:
    """Document that ADS-style filename segments must remain blocked."""
    target = tmp_path / "normal-file.txt:secret"

    with pytest.raises(validators.ValidationError, match="alternate data streams"):
        validators.ensure_safe_path(
            target,
            allow_overwrite=True,
            allowed_roots=[tmp_path],
        )
