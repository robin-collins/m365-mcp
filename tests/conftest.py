from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest
from dotenv import load_dotenv

from tests.unified_harness import harness  # noqa: F401  (shared fixture)

# Load environment variables from .env file for all tests
test_env_file = os.getenv("TEST_ENV_FILE", ".env")
if Path(test_env_file).exists():
    load_dotenv(dotenv_path=test_env_file)
else:
    load_dotenv()


@pytest.fixture(autouse=True, scope="session")
def ensure_port_8000_free():
    """Kill any process on port 8000 before and after test session.

    This prevents orphaned HTTP server processes from blocking the port
    and causing test failures. Runs automatically for every test session.
    """

    def cleanup():
        """Find and kill all processes using port 8000 using netstat approach."""
        try:
            # Use the proven netstat approach to kill processes on port 8000
            # Loop while port 8000 is in use (max 3 iterations to avoid infinite loop)
            max_attempts = 3
            attempt = 0

            while attempt < max_attempts:
                # Check if port 8000 is in use
                check_result = subprocess.run(
                    ["sudo", "netstat", "-tunlp"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )

                if "8000" not in check_result.stdout:
                    # Port is free
                    break

                # Extract PID and kill it
                # Parse: "tcp 0 0 :::8000 :::* LISTEN 12345/python"
                # Extract: "12345/python" then remove last 8 chars to get PID
                for line in check_result.stdout.split("\n"):
                    if "8000" in line:
                        # Use awk to get column 7, sed to remove last 8 chars
                        pid_result = subprocess.run(
                            [
                                "bash",
                                "-c",
                                f"echo '{line}' | awk '{{print $7}}' | sed 's/.{{8}}$//'",
                            ],
                            capture_output=True,
                            text=True,
                            timeout=2,
                            check=False,
                        )
                        pid = pid_result.stdout.strip()

                        if pid:
                            # Kill the process
                            subprocess.run(
                                ["sudo", "kill", "-9", pid],
                                stderr=subprocess.DEVNULL,
                                timeout=2,
                                check=False,
                            )

                # Wait before next iteration
                time.sleep(1)
                attempt += 1

        except subprocess.TimeoutExpired:
            print("Warning: Port 8000 cleanup timed out")
        except (OSError, subprocess.SubprocessError) as e:
            # Don't fail tests if cleanup fails, just warn
            print(f"Warning: Port 8000 cleanup encountered error: {e}")

    # Clean before test session starts
    cleanup()

    yield

    # Clean after test session ends
    cleanup()
