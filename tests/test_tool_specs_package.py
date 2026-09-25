"""Tests for the packaged copy of the unified-tool specs (task U2.1)."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest

from m365_mcp import tool_specs

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs" / "unified-tools"
PKG_DIR = ROOT / "src" / "m365_mcp" / "tool_specs"
BUILDER = ROOT / "scripts" / "build_unified_tool_specs.py"


def _load_builder() -> Any:
    spec = importlib.util.spec_from_file_location("build_specs_pkg", BUILDER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _spec_files(base: Path) -> dict[str, bytes]:
    files = {"index.json": (base / "index.json").read_bytes()}
    for path in sorted((base / "tools").glob("*.json")):
        files[f"tools/{path.name}"] = path.read_bytes()
    return files


def test_package_copy_equals_docs_copy() -> None:
    docs = _spec_files(DOCS_DIR)
    package = _spec_files(PKG_DIR)
    assert len(docs) == 30
    assert package == docs


def test_loader_reads_packaged_specs() -> None:
    index = tool_specs.load_index()
    assert index == json.loads((DOCS_DIR / "index.json").read_text("utf-8"))
    for name in index["tool_order"]:
        expected = json.loads(
            (DOCS_DIR / "tools" / f"{name}.json").read_text("utf-8")
        )
        assert tool_specs.load_tool_spec(name) == expected


def test_loader_rejects_unknown_tool() -> None:
    with pytest.raises(KeyError, match="no_such_tool"):
        tool_specs.load_tool_spec("no_such_tool")


def test_builder_writes_and_checks_package_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    builder = _load_builder()
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    monkeypatch.setattr(builder, "OUT_DIR", tmp_path / "docs")
    monkeypatch.setattr(builder, "PKG_DIR", tmp_path / "pkg")

    def run(*args: str) -> int:
        monkeypatch.setattr(sys, "argv", ["build", *args])
        return builder.main()

    assert run("--check") == 1
    assert run() == 0
    assert _spec_files(tmp_path / "pkg") == _spec_files(tmp_path / "docs")
    assert run("--check") == 0

    extra = tmp_path / "pkg" / "tools" / "stray.json"
    extra.write_text("{}", encoding="utf-8")
    assert run("--check") == 1
    assert run() == 0
    assert not extra.exists()

    (tmp_path / "pkg" / "index.json").write_text("{}", encoding="utf-8")
    assert run("--check") == 1


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed")
def test_wheel_contains_specs(tmp_path: Path) -> None:
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        timeout=300,
    )
    (wheel,) = tmp_path.glob("*.whl")
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        packaged = {
            name.removeprefix("m365_mcp/tool_specs/"): archive.read(name)
            for name in names
            if name.startswith("m365_mcp/tool_specs/")
            and name.endswith(".json")
        }
    assert "m365_mcp/tool_specs/__init__.py" in names
    assert packaged == _spec_files(DOCS_DIR)
