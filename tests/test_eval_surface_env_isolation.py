"""Regression: importing ``evals.surface`` must not mutate the environment.

``evals/surface.py`` used to call ``os.environ.setdefault(...)`` at module
import time, to give a bare Graph client ID and cache key to eval runs that
never set their own. But ``tests/conftest.py`` imports the eval harness
(which imports this module, for the ``harness`` fixture) *before* it calls
``load_dotenv()``, and ``load_dotenv()`` never overrides an already-set
variable. So this import-time default silently replaced a real
``M365_MCP_CLIENT_ID`` (loaded from ``.env`` by a human running
``authenticate.py`` and the live tests by hand) for the whole pytest
session — breaking ``tests/test_integration_unified.py`` with a misleading
``SignInRequiredError`` on every call, even immediately after a fresh,
successful sign-in.

The fix scopes the fallback to ``evals.surface.open_surface()`` itself
(restored on exit, like its other patches), so importing the module has no
side effect and a real environment value is never shadowed.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_importing_surface_does_not_set_client_id_env_var() -> None:
    """Merely importing ``evals.surface`` must not set these variables."""
    clean_env = {
        key: value
        for key, value in os.environ.items()
        if key not in ("M365_MCP_CLIENT_ID", "M365_MCP_CACHE_KEY")
    }
    script = (
        "import evals.surface\n"
        "import os\n"
        "assert 'M365_MCP_CLIENT_ID' not in os.environ, os.environ.get('M365_MCP_CLIENT_ID')\n"
        "assert 'M365_MCP_CACHE_KEY' not in os.environ, os.environ.get('M365_MCP_CACHE_KEY')\n"
        "print('OK')"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=clean_env,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_real_client_id_survives_the_conftest_import_order(tmp_path: Path) -> None:
    """A real ``M365_MCP_CLIENT_ID`` from ``.env`` must not be lost.

    Reproduces the exact failure: a real client ID lives only in a ``.env``
    file (as ``authenticate.py`` and a human's shell leave it — not already
    exported in the process environment), and ``tests/conftest.py`` must
    still see it after import, not the eval harness's placeholder.
    """
    env_file = tmp_path / ".env"
    env_file.write_text("M365_MCP_CLIENT_ID=a-real-azure-app-client-id\n")
    clean_env = {
        key: value
        for key, value in os.environ.items()
        if key not in ("M365_MCP_CLIENT_ID", "M365_MCP_CACHE_KEY")
    }
    clean_env["TEST_ENV_FILE"] = str(env_file)
    script = (
        "import tests.conftest\n"
        "import os\n"
        "assert os.environ['M365_MCP_CLIENT_ID'] == 'a-real-azure-app-client-id', (\n"
        "    os.environ.get('M365_MCP_CLIENT_ID')\n"
        ")\n"
        "print('OK')"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=clean_env,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
