"""Reparse point (symlink/junction) and hardlink rejection tests.

Real links are created where the platform/privileges allow; otherwise the
test is skipped with an explicit reason (never silently passed).
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from safe_workspace_mcp import errors
from safe_workspace_mcp.path_guard import PathGuard


@pytest.fixture()
def env(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "sub").mkdir()
    (outside / "secret.txt").write_text("outside", encoding="utf-8")
    return root, outside, tmp_path


def _mk_symlink(link: Path, target: os.PathLike[str] | str, is_dir: bool) -> bool:
    try:
        os.symlink(target, link, target_is_directory=is_dir)
    except (OSError, NotImplementedError, PermissionError):
        return False
    return True


def _mk_junction(link: Path, target: Path) -> bool:
    if sys.platform != "win32":
        return False
    try:
        import subprocess  # noqa: S404 - test-only, never shipped

        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=True,
            capture_output=True,
        )
    except Exception:
        return False
    return link.exists() or link.is_dir()


def test_symlink_file_inside_to_outside(env: tuple[Path, Path, Path]) -> None:
    root, outside, _ = env
    if not _mk_symlink(root / "leak.txt", outside / "secret.txt", is_dir=False):
        pytest.skip("symlink creation requires privileges unavailable here")
    guard = PathGuard(root)
    with pytest.raises(errors.ReparsePointError):
        guard.check_existing("leak.txt")


def test_symlink_file_inside_to_inside(env: tuple[Path, Path, Path]) -> None:
    root, _, _ = env
    (root / "real.txt").write_text("in", encoding="utf-8")
    if not _mk_symlink(root / "alias.txt", root / "real.txt", is_dir=False):
        pytest.skip("symlink creation requires privileges unavailable here")
    guard = PathGuard(root)
    with pytest.raises(errors.ReparsePointError):
        guard.check_existing("alias.txt")


def test_symlink_dir_inside_to_outside(env: tuple[Path, Path, Path]) -> None:
    root, outside, _ = env
    if not _mk_symlink(root / "outdir", outside, is_dir=True):
        pytest.skip("symlink creation requires privileges unavailable here")
    guard = PathGuard(root)
    with pytest.raises(errors.ReparsePointError):
        guard.check_existing("outdir/secret.txt")


def test_symlink_intermediate_component(env: tuple[Path, Path, Path]) -> None:
    root, outside, _ = env
    if not _mk_symlink(root / "hop", outside, is_dir=True):
        pytest.skip("symlink creation requires privileges unavailable here")
    guard = PathGuard(root)
    with pytest.raises(errors.ReparsePointError):
        guard.check_existing("hop/secret.txt")
    with pytest.raises(errors.ReparsePointError):
        guard.check_for_creation("hop/newfile.txt")


def test_junction_inside_to_outside(env: tuple[Path, Path, Path]) -> None:
    root, outside, _ = env
    if not _mk_junction(root / "jm", outside):
        pytest.skip("junction creation unavailable (Windows only)")
    guard = PathGuard(root)
    with pytest.raises(errors.ReparsePointError):
        guard.check_existing("jm/secret.txt")
    with pytest.raises(errors.ReparsePointError):
        guard.check_for_creation("jm/new.txt")


def test_junction_inside_to_inside(env: tuple[Path, Path, Path]) -> None:
    root, _, _ = env
    if not _mk_junction(root / "jin", root / "sub"):
        pytest.skip("junction creation unavailable (Windows only)")
    guard = PathGuard(root)
    with pytest.raises(errors.ReparsePointError):
        guard.check_existing("jin")


def test_hardlink_rejected(env: tuple[Path, Path, Path]) -> None:
    root, _, _ = env
    target = root / "real.txt"
    target.write_text("data", encoding="utf-8")
    try:
        os.link(target, root / "hard.txt")
    except (OSError, NotImplementedError):
        pytest.skip("hardlink creation unavailable on this platform")
    guard = PathGuard(root)
    with pytest.raises(errors.HardlinkError):
        guard.check_existing("real.txt")
    with pytest.raises(errors.HardlinkError):
        guard.check_existing("hard.txt")


def test_directory_link_count_not_treated_as_hardlink(env: tuple[Path, Path, Path]) -> None:
    root, _, _ = env
    # Directories legitimately have st_nlink > 1; they must pass.
    (root / "sub" / "nested").mkdir()
    guard = PathGuard(root)
    guard.check_existing("sub")
    guard.check_existing("sub/nested")
    assert stat.S_ISDIR(os.stat(root / "sub").st_mode)
