"""Windows-specific path edge cases (skipped transparently on non-Windows)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from safe_workspace_mcp import errors
from safe_workspace_mcp.path_guard import PathGuard

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only paths")

IS_ADMIN = False
try:
    import ctypes

    IS_ADMIN = bool(ctypes.windll.shell32.IsUserAnAdmin())
except Exception:
    pass


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    real = tmp_path / "root"
    real.mkdir()
    (real / "sub").mkdir()
    return real


def test_drive_qualified_forms(root: Path) -> None:
    guard = PathGuard(root)
    drive = os.path.splitdrive(str(root))[0]
    with pytest.raises(errors.AbsolutePathError):
        guard.validate_relative(f"{drive}\\x")
    with pytest.raises(errors.AbsolutePathError):
        guard.validate_relative(f"{drive}/x")
    with pytest.raises(errors.AbsolutePathError):
        guard.validate_relative(f"{drive.lower()}x")


def test_unc_forms(root: Path) -> None:
    guard = PathGuard(root)
    with pytest.raises(errors.AbsolutePathError):
        guard.validate_relative("\\\\server\\share\\f")
    with pytest.raises(errors.AbsolutePathError):
        guard.validate_relative("//server/share/f")


def test_extended_namespace(root: Path) -> None:
    guard = PathGuard(root)
    with pytest.raises(errors.PathError):
        guard.validate_relative("\\\\?\\C:\\temp\\x")


def test_trailing_dot_space_even_if_os_strips(root: Path) -> None:
    guard = PathGuard(root)
    for name in ("foo.", "foo ", "foo. ", "foo.."):
        with pytest.raises(errors.PathError):
            guard.validate_relative(name)
        with pytest.raises(errors.PathError):
            guard.validate_relative(f"sub/{name}")


def test_windows_reserved_case_variants(root: Path) -> None:
    guard = PathGuard(root)
    for name in ("con", "Con", "CON", "PrN", "nUl", "com3", "LPT7", "aux.ini"):
        with pytest.raises(errors.WindowsReservedNameError):
            guard.validate_relative(name)


def test_short_name_alias_of_internal(root: Path) -> None:
    """8.3 alias like GIT~1 must not reach .git internals via check_existing."""
    guard = PathGuard(root)
    git_dir = root / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("[core]", encoding="utf-8")
    # find the short name if the volume supports 8.3 aliases
    short = None
    for name in os.listdir(root):
        if name.upper().startswith("GIT~") and (root / name).is_dir():
            short = name
            break
    if short is None:
        pytest.skip("8.3 short names not generated on this volume")
    with pytest.raises(errors.PathError):
        guard.check_existing(f"{short}/config")
