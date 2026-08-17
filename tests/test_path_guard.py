"""PathGuard lexical and filesystem validation tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from safe_workspace_mcp import errors
from safe_workspace_mcp.path_guard import PathGuard


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    real = tmp_path / "root"
    real.mkdir()
    (real / "sub").mkdir()
    (real / "sub" / "file.txt").write_text("hello", encoding="utf-8")
    return real


def test_root_must_exist(tmp_path: Path) -> None:
    with pytest.raises(errors.PathError):
        PathGuard(tmp_path / "missing")


def test_root_rejects_file(tmp_path: Path) -> None:
    f = tmp_path / "f.txt"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(errors.PathError):
        PathGuard(f)


def test_root_rejects_drive_root(tmp_path: Path) -> None:
    with pytest.raises(errors.PathError):
        PathGuard(Path(tmp_path.anchor))


# ---------------------------------------------------------------- lexical


@pytest.mark.parametrize(
    "bad",
    [
        "../escape",
        "..\\escape",
        "sub/../../escape",
        "sub/../..",
        "/abs",
        "\\abs",
        "C:\\abs",
        "C:/abs",
        "C:abs",
        "c:abs",
        "\\\\server\\share",
        "//server/share",
        "\\\\?\\C:\\x",
        "\\??\\x",
        "sub/CON",
        "sub/con.txt",
        "NUL",
        "nul",
        "aux.txt.bak",
        "com1",
        "COM9",
        "LPT1.log",
        "lpt9",
        "sub/file.txt:.stream",
        "sub/file.txt:$DATA",
        "a:b",
        "foo.",
        "foo..",
        "foo ",
        " foo",
        "foo\tbar",
        "foo\nbar",
        "sub//file.txt",
        "sub\\",
        "",
        ".",
        "sub/.",
        "sub/..",
        ".git/config",
        ".git",
        ".GIT/config",
        ".workspace-mcp/x",
        "node_modules/x",
        "BUILD/x",
        "dist",
        ".venv/lib",
        "__pycache__/c.pyc",
        "sub/\x00file",
        "sub/file\x1b[J",
    ],
)
def test_rejects_bad_paths(root: Path, bad: str) -> None:
    guard = PathGuard(root)
    with pytest.raises(errors.PathError):
        guard.validate_relative(bad)


def test_rejects_correct_error_types(root: Path) -> None:
    guard = PathGuard(root)
    with pytest.raises(errors.AbsolutePathError):
        guard.validate_relative("C:/x")
    with pytest.raises(errors.AbsolutePathError):
        guard.validate_relative("/x")
    with pytest.raises(errors.PathTraversalError):
        guard.validate_relative("../x")
    with pytest.raises(errors.WindowsReservedNameError):
        guard.validate_relative("sub/con")
    with pytest.raises(errors.InternalPathError):
        guard.validate_relative(".git/config")
    with pytest.raises(errors.ExcludedPathError):
        guard.validate_relative("node_modules/x")


@pytest.mark.parametrize(
    "ok",
    [
        "file.txt",
        "sub/file.txt",
        "sub\\file.txt",
        "a/b/c/d.txt",
        "sub/version1.2.txt",
        "my project/notes v2.md",
    ],
)
def test_accepts_good_paths(root: Path, ok: str) -> None:
    guard = PathGuard(root)
    p = guard.validate_relative(ok)
    assert p.is_absolute()
    assert str(guard.root).lower() in str(p).lower()


def test_prefix_confusion_denied(tmp_path: Path) -> None:
    root = tmp_path / "Workspace"
    other = tmp_path / "WorkspaceOther"
    root.mkdir()
    other.mkdir()
    guard = PathGuard(root)
    with pytest.raises(errors.PathError):
        guard.validate_relative("../WorkspaceOther/file.txt")
    # The existing file in the sibling dir must not resolve through guard.
    (other / "f.txt").write_text("x", encoding="utf-8")
    with pytest.raises(errors.PathError):
        guard.check_existing("../WorkspaceOther/f.txt")


# ------------------------------------------------------------ filesystem


def test_check_existing_missing(root: Path) -> None:
    guard = PathGuard(root)
    with pytest.raises(errors.FileNotFoundError_):
        guard.check_existing("sub/nope.txt")


def test_check_for_creation_nested_missing(root: Path) -> None:
    guard = PathGuard(root)
    p = guard.check_for_creation("a/b/new.txt")
    assert not p.exists()


def test_check_for_creation_parent_is_file(root: Path) -> None:
    guard = PathGuard(root)
    with pytest.raises(errors.DirectoryExpectedError):
        guard.check_for_creation("sub/file.txt/deeper.txt")


def test_case_variant_of_internal_name(root: Path) -> None:
    guard = PathGuard(root)
    for variant in (".Git", ".GIT", ".gIt"):
        with pytest.raises(errors.PathError):
            guard.validate_relative(f"{variant}/config")
