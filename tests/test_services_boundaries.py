"""Architecture rules for the Graph service layer (task U1.9)."""

import ast
from pathlib import Path

import pytest

SERVICES_DIR = Path(__file__).resolve().parents[1] / "src" / "m365_mcp" / "services"
FORBIDDEN = ("fastmcp", "mcp", "m365_mcp.tools", "m365_mcp.mcp_instance")
FORBIDDEN_RELATIVE = ("tools", "mcp_instance")


def _imports(tree: ast.AST) -> list[tuple[str, int]]:
    """Return (module, relative level) for every import, nested ones included."""
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((alias.name, 0) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.append((node.module or "", node.level))
    return found


SERVICE_FILES = sorted(SERVICES_DIR.glob("*.py"))


def test_service_modules_exist():
    names = {p.stem for p in SERVICE_FILES}
    assert {
        "mail",
        "mail_folders",
        "mail_rules",
        "calendar",
        "contacts",
        "drive",
        "search",
        "accounts",
    } <= names


@pytest.mark.parametrize("path", SERVICE_FILES, ids=lambda p: p.stem)
def test_services_never_import_fastmcp_or_tools(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for module, level in _imports(tree):
        if level == 0:
            assert not any(
                module == f or module.startswith(f + ".") for f in FORBIDDEN
            ), f"{path.name} imports {module}"
        else:
            head = module.split(".")[0]
            assert head not in FORBIDDEN_RELATIVE, (
                f"{path.name} imports {'.' * level}{module}"
            )


def test_cache_manager_singleton_lives_outside_tools():
    from src.m365_mcp import cache
    from src.m365_mcp.tools import cache_tools

    cache._cache_manager = None
    sentinel = object()
    cache._cache_manager = sentinel  # type: ignore[assignment]
    try:
        assert cache.get_cache_manager() is sentinel
        assert cache_tools.get_cache_manager() is sentinel
    finally:
        cache._cache_manager = None


def test_importing_services_does_not_load_fastmcp():
    import subprocess
    import sys

    code = (
        "import sys\n"
        "import m365_mcp.services.mail, m365_mcp.services.mail_folders\n"
        "import m365_mcp.services.mail_rules, m365_mcp.services.calendar\n"
        "import m365_mcp.services.contacts, m365_mcp.services.drive\n"
        "import m365_mcp.services.search, m365_mcp.services.accounts\n"
        "import m365_mcp.projections, m365_mcp.cursors, m365_mcp.errors\n"
        "loaded = sorted(m for m in sys.modules if m.split('.')[0] in "
        "('fastmcp', 'mcp') or m.startswith('m365_mcp.tools'))\n"
        "print(','.join(loaded))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == ""
