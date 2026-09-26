"""Local file safety for tools that read or write the local disk.

Concept §8.13 and §12.5. Paths are allowed only inside:

- the current working directory,
- the system temp directory,
- each entry of ``MCP_FILE_ALLOWED_ROOTS`` (``os.pathsep``-separated).

Symlinks are resolved before the check, so a link that escapes a root is
refused. The deny-list applies to reads and writes alike: any path
component below the root that starts with ``.`` (which covers ``.env``),
``*.pem``, ``*.key`` and ``*token_cache*`` (case-insensitive). The name
the caller typed is checked too, so a link called ``server.pem`` is
refused even if its target is harmless.

Error texts follow the spec validation rules and never echo the full path.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from .validators import WINDOWS_RESERVED_NAMES, ValidationError

ALLOWED_ROOTS_ENV = "MCP_FILE_ALLOWED_ROOTS"
DEFAULT_FILE_NAME = "download"

_INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*]')
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def allowed_roots() -> list[Path]:
    """Return the resolved folders local paths must stay inside.

    Returns:
        The working directory, the temp directory, then each
        ``MCP_FILE_ALLOWED_ROOTS`` entry.
    """
    roots = [Path.cwd().resolve(), Path(tempfile.gettempdir()).resolve()]
    for entry in os.getenv(ALLOWED_ROOTS_ENV, "").split(os.pathsep):
        if entry.strip():
            roots.append(Path(entry.strip()).expanduser().resolve())
    return roots


def _resolve(path: Path) -> Path:
    """Resolve symlinks and ``..`` (a seam for tests)."""
    return path.resolve(strict=False)


def _is_protected(name: str) -> bool:
    """Return True for hidden or secret-like path components."""
    lower = name.lower()
    return (
        lower.startswith(".")
        or lower.endswith((".pem", ".key"))
        or "token_cache" in lower
    )


def _root_of(path: Path, roots: list[Path]) -> Path | None:
    """Return the allowed root containing ``path``, if any."""
    target = os.path.normcase(str(path))
    for root in roots:
        base = os.path.normcase(str(root))
        try:
            if os.path.commonpath([base, target]) == base:
                return root
        except ValueError:  # different drives on Windows
            continue
    return None


def _check(path: str | os.PathLike[str], param: str) -> Path:
    """Apply the root and deny-list checks and return the resolved path."""
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    resolved = _resolve(candidate)

    root = _root_of(resolved, allowed_roots())
    if root is None:
        raise ValidationError(
            f"Invalid {param}: outside allowed folders. Expected: a path "
            "under the working directory, temp directory or "
            f"{ALLOWED_ROOTS_ENV}"
        )

    names = list(resolved.relative_to(root).parts) if resolved != root else []
    if candidate.name not in ("", ".", ".."):
        names.append(candidate.name)
    for name in names:
        if _is_protected(name):
            raise ValidationError(f"Invalid {param}: '{name}' is a protected file")
    return resolved


def check_read_path(path: str | os.PathLike[str], param: str = "local_path") -> Path:
    """Validate a local file the server is about to read.

    Args:
        path: Path supplied by the caller (relative paths use the working
            directory).
        param: Parameter name used in error messages.

    Returns:
        The resolved path of an existing regular file.

    Raises:
        ValidationError: If the path is outside the allowed roots,
            deny-listed, missing or not a regular file.
    """
    resolved = _check(path, param)
    if not resolved.exists():
        raise ValidationError(
            f"Invalid {param}: file not found. Expected: an existing file"
        )
    if not resolved.is_file():
        raise ValidationError(
            f"Invalid {param}: not a regular file. Expected: an existing file"
        )
    return resolved


def check_write_path(
    path: str | os.PathLike[str],
    param: str = "save_path",
    overwrite: bool = False,
) -> Path:
    """Validate a local file the server is about to write.

    Args:
        path: Path supplied by the caller (relative paths use the working
            directory).
        param: Parameter name used in error messages.
        overwrite: Allow replacing an existing file.

    Returns:
        The resolved destination path.

    Raises:
        ValidationError: If the path is outside the allowed roots,
            deny-listed, a folder, or an existing file while
            ``overwrite`` is false.
    """
    resolved = _check(path, param)
    if resolved.is_dir():
        raise ValidationError(f"Invalid {param}: is a folder. Expected: a file path")
    if resolved.exists() and not overwrite:
        raise ValidationError(
            f"Invalid {param}: file exists. Expected: overwrite=true or another path"
        )
    return resolved


def sanitize_file_name(name: str, fallback: str = DEFAULT_FILE_NAME) -> str:
    """Make a file name from Graph safe to use as a local file name.

    Removes control characters, replaces path separators and characters
    Windows forbids with ``_``, strips trailing dots and spaces, and
    prefixes reserved Windows device names (``CON``, ``LPT1.txt``) with
    ``_``.

    Args:
        name: Untrusted name (an attachment or drive item name).
        fallback: Name used when nothing usable remains.

    Returns:
        A single path component.
    """
    cleaned = _CONTROL_CHARS.sub("", name)
    cleaned = _INVALID_NAME_CHARS.sub("_", cleaned)
    cleaned = cleaned.strip(" ").rstrip(". ")
    if not cleaned:
        return fallback
    if cleaned.split(".")[0].upper() in WINDOWS_RESERVED_NAMES:
        cleaned = "_" + cleaned
    return cleaned
