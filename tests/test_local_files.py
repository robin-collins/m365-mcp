"""Tests for local file safety (task U2.13)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from src.m365_mcp import local_files
from src.m365_mcp.local_files import (
    allowed_roots,
    check_read_path,
    check_write_path,
    sanitize_file_name,
)
from src.m365_mcp.validators import ValidationError

OUTSIDE = (
    "Invalid {param}: outside allowed folders. Expected: a path under the "
    "working directory, temp directory or MCP_FILE_ALLOWED_ROOTS"
)
EXISTS = "Invalid save_path: file exists. Expected: overwrite=true or another path"


@pytest.fixture
def roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Create cwd, temp, extra and outside folders and point roots at them."""
    folders = {name: tmp_path / name for name in ("cwd", "temp", "extra", "outside")}
    for folder in folders.values():
        folder.mkdir()
    monkeypatch.chdir(folders["cwd"])
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(folders["temp"]))
    monkeypatch.delenv("MCP_FILE_ALLOWED_ROOTS", raising=False)
    return folders


def test_default_roots_are_cwd_and_temp(roots: dict[str, Path]) -> None:
    assert allowed_roots() == [
        roots["cwd"].resolve(),
        roots["temp"].resolve(),
    ]


def test_env_roots_are_added(
    roots: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "MCP_FILE_ALLOWED_ROOTS",
        os.pathsep.join([str(roots["extra"]), ""]),
    )
    target = roots["extra"] / "report.pdf"
    target.write_bytes(b"x")

    assert roots["extra"].resolve() in allowed_roots()
    assert check_read_path(str(target)) == target.resolve()


def test_read_inside_cwd_by_relative_path(roots: dict[str, Path]) -> None:
    (roots["cwd"] / "notes.txt").write_text("hi")

    assert check_read_path("notes.txt") == (roots["cwd"] / "notes.txt").resolve()


def test_write_inside_temp(roots: dict[str, Path]) -> None:
    target = roots["temp"] / "sub" / "out.pdf"

    assert check_write_path(str(target)) == target.resolve()


@pytest.mark.parametrize("check", ["read", "write"])
def test_outside_roots_is_refused(roots: dict[str, Path], check: str) -> None:
    target = roots["outside"] / "file.txt"
    target.write_text("x")

    if check == "read":
        with pytest.raises(ValidationError) as exc:
            check_read_path(str(target))
        assert str(exc.value) == OUTSIDE.format(param="local_path")
    else:
        with pytest.raises(ValidationError) as exc:
            check_write_path(str(target))
        assert str(exc.value) == OUTSIDE.format(param="save_path")


@pytest.mark.parametrize(
    "relative",
    [
        "../outside/file.txt",
        "sub/../../outside/file.txt",
        "../../../../../../../../etc/passwd",
    ],
)
def test_traversal_is_refused(roots: dict[str, Path], relative: str) -> None:
    (roots["outside"] / "file.txt").write_text("x")

    with pytest.raises(ValidationError, match="outside allowed folders"):
        check_write_path(relative)


def test_traversal_that_stays_inside_is_allowed(
    roots: dict[str, Path],
) -> None:
    (roots["cwd"] / "sub").mkdir()

    assert check_write_path("sub/../ok.txt") == (roots["cwd"] / "ok.txt").resolve()


def test_error_does_not_echo_path(roots: dict[str, Path]) -> None:
    with pytest.raises(ValidationError) as exc:
        check_write_path(str(roots["outside"] / "secret-name.txt"))
    assert "secret-name" not in str(exc.value)


@pytest.mark.parametrize(
    ("relative", "component"),
    [
        (".env", ".env"),
        ("config/.env", ".env"),
        (".ssh/id_rsa", ".ssh"),
        (".hidden", ".hidden"),
        ("certs/server.pem", "server.pem"),
        ("certs/SERVER.PEM", "SERVER.PEM"),
        ("private.key", "private.key"),
        ("Private.Key", "Private.Key"),
        ("m365_mcp_token_cache.json", "m365_mcp_token_cache.json"),
        ("backup/MY_TOKEN_CACHE.bin", "MY_TOKEN_CACHE.bin"),
        ("token_cache_dir/file.txt", "token_cache_dir"),
    ],
)
@pytest.mark.parametrize("check", ["read", "write"])
def test_deny_list(
    roots: dict[str, Path], relative: str, component: str, check: str
) -> None:
    target = roots["cwd"] / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("secret")

    if check == "read":
        with pytest.raises(ValidationError) as exc:
            check_read_path(relative)
        param = "local_path"
    else:
        with pytest.raises(ValidationError) as exc:
            check_write_path(relative, overwrite=True)
        param = "save_path"
    assert str(exc.value) == (f"Invalid {param}: '{component}' is a protected file")


def test_dot_folder_above_root_is_not_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / ".config" / "work"
    root.mkdir(parents=True)
    monkeypatch.chdir(root)
    (root / "a.txt").write_text("x")

    assert check_read_path("a.txt") == (root / "a.txt").resolve()


def test_overwrite_protection(roots: dict[str, Path]) -> None:
    target = roots["cwd"] / "exists.txt"
    target.write_text("old")

    with pytest.raises(ValidationError) as exc:
        check_write_path(str(target))
    assert str(exc.value) == EXISTS

    assert check_write_path(str(target), overwrite=True) == target.resolve()


def test_write_to_directory_is_refused(roots: dict[str, Path]) -> None:
    with pytest.raises(ValidationError, match="Invalid save_path"):
        check_write_path(str(roots["cwd"]), overwrite=True)


def test_read_missing_file_is_refused(roots: dict[str, Path]) -> None:
    with pytest.raises(ValidationError) as exc:
        check_read_path("missing.txt")
    assert str(exc.value) == (
        "Invalid local_path: file not found. Expected: an existing file"
    )


def test_read_directory_is_refused(roots: dict[str, Path]) -> None:
    (roots["cwd"] / "folder").mkdir()

    with pytest.raises(ValidationError) as exc:
        check_read_path("folder")
    assert str(exc.value) == (
        "Invalid local_path: not a regular file. Expected: an existing file"
    )


def test_custom_param_name(roots: dict[str, Path]) -> None:
    with pytest.raises(ValidationError, match=r"^Invalid attachments: "):
        check_read_path(".env", param="attachments")


def test_symlink_escaping_root_is_refused(roots: dict[str, Path]) -> None:
    secret = roots["outside"] / "secret.txt"
    secret.write_text("x")
    link = roots["cwd"] / "innocent.txt"
    try:
        link.symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted on this system")

    with pytest.raises(ValidationError, match="outside allowed folders"):
        check_read_path("innocent.txt")


def test_symlink_to_protected_file_is_refused(roots: dict[str, Path]) -> None:
    secret = roots["cwd"] / ".env"
    secret.write_text("x")
    link = roots["cwd"] / "innocent.txt"
    try:
        link.symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted on this system")

    with pytest.raises(ValidationError, match="'.env' is a protected file"):
        check_read_path("innocent.txt")


def test_resolved_target_is_checked_not_lexical_path(
    roots: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Symlink logic with a patched resolver (works without symlinks)."""
    link = roots["cwd"] / "innocent.txt"
    link.write_text("x")
    escaped = roots["outside"] / "secret.txt"
    escaped.write_text("x")
    real_resolve = local_files._resolve

    def fake_resolve(path: Path) -> Path:
        if path == link:
            return escaped.resolve()
        return real_resolve(path)

    monkeypatch.setattr(local_files, "_resolve", fake_resolve)

    with pytest.raises(ValidationError, match="outside allowed folders"):
        check_read_path("innocent.txt")
    with pytest.raises(ValidationError, match="outside allowed folders"):
        check_write_path("innocent.txt", overwrite=True)


def test_protected_link_name_is_refused_even_if_target_is_safe(
    roots: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    link = roots["cwd"] / "server.pem"
    target = roots["cwd"] / "plain.txt"
    target.write_text("x")
    monkeypatch.setattr(
        local_files,
        "_resolve",
        lambda path: target.resolve() if path == link else path.resolve(),
    )

    with pytest.raises(ValidationError, match="'server.pem' is a protected"):
        check_read_path("server.pem")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("report.pdf", "report.pdf"),
        ("../../etc/passwd", ".._.._etc_passwd"),
        ("a\\b/c.txt", "a_b_c.txt"),
        ('bad<>:"|?*.txt', "bad_______.txt"),
        ("tab\there\x00\x1f\x7f.txt", "tabhere.txt"),
        ("trailing. . ", "trailing"),
        ("CON", "_CON"),
        ("con.txt", "_con.txt"),
        ("LPT1.tar.gz", "_LPT1.tar.gz"),
        ("console.txt", "console.txt"),
        ("", "download"),
        ("...", "download"),
        ("\x00", "download"),
    ],
)
def test_sanitize_file_name(name: str, expected: str) -> None:
    assert sanitize_file_name(name) == expected


def _http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    for name in ("MCP_FILE_ALLOW_CWD", "MCP_FILE_ALLOW_TEMP"):
        monkeypatch.delenv(name, raising=False)


def test_http_transport_defaults_to_explicit_roots_only(
    roots: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _http(monkeypatch)
    assert allowed_roots() == []
    (roots["cwd"] / "a.txt").write_text("x")
    (roots["temp"] / "b.txt").write_text("x")
    for name in ("cwd", "temp"):
        with pytest.raises(ValidationError, match="outside allowed folders"):
            check_read_path(str(roots[name] / ("a.txt" if name == "cwd" else "b.txt")))


def test_http_transport_uses_configured_roots(
    roots: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _http(monkeypatch)
    monkeypatch.setenv("MCP_FILE_ALLOWED_ROOTS", str(roots["extra"]))
    target = roots["extra"] / "report.pdf"
    target.write_bytes(b"x")
    assert allowed_roots() == [roots["extra"].resolve()]
    assert check_read_path(str(target)) == target.resolve()


def test_http_transport_can_opt_back_in(
    roots: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _http(monkeypatch)
    monkeypatch.setenv("MCP_FILE_ALLOW_CWD", "true")
    assert allowed_roots() == [roots["cwd"].resolve()]
    monkeypatch.setenv("MCP_FILE_ALLOW_TEMP", "1")
    assert allowed_roots() == [roots["cwd"].resolve(), roots["temp"].resolve()]


def test_stdio_can_drop_the_temp_directory(
    roots: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MCP_TRANSPORT", raising=False)
    monkeypatch.setenv("MCP_FILE_ALLOW_TEMP", "false")
    assert allowed_roots() == [roots["cwd"].resolve()]
    monkeypatch.setenv("MCP_FILE_ALLOW_CWD", "false")
    assert allowed_roots() == []


def test_unrecognised_flag_falls_back_to_the_transport_default(
    roots: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MCP_TRANSPORT", raising=False)
    monkeypatch.setenv("MCP_FILE_ALLOW_TEMP", "maybe")
    assert roots["temp"].resolve() in allowed_roots()
