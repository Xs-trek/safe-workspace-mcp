"""CRUD operations tests through FileService + apply_changes."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from safe_workspace_mcp.config import Config, Limits
from safe_workspace_mcp.file_service import FileService
from safe_workspace_mcp.path_guard import PathGuard


@pytest.fixture()
def env(tmp_path: Path):
    root = tmp_path / "ws"
    root.mkdir()
    cfg = Config(root=root)
    guard = PathGuard(root)
    files = FileService(cfg, guard)
    return root, files


def test_create_and_read(env) -> None:
    root, files = env
    digest = files.create_file("a.txt", "hello\n")
    text, sha, size = files.read_file("a.txt")
    assert text == "hello\n"
    assert sha == hashlib.sha256(b"hello\n").hexdigest() == digest
    assert size == 6


def test_create_existing_fails(env) -> None:
    root, files = env
    files.create_file("a.txt", "x")
    with pytest.raises(Exception):
        files.create_file("a.txt", "y")


def test_create_overwrite_with_hash(env) -> None:
    root, files = env
    d1 = files.create_file("a.txt", "x")
    d2 = files.create_file("a.txt", "y", overwrite_hash=d1)
    assert d2 != d1
    assert files.read_file("a.txt")[0] == "y"


def test_replace_file_requires_hash(env) -> None:
    root, files = env
    files.create_file("a.txt", "v1")
    d = files.current_hash("a.txt")
    with pytest.raises(Exception):
        files.replace_file("a.txt", "v2", "0" * 64)
    files.replace_file("a.txt", "v2", d)
    assert files.read_file("a.txt")[0] == "v2"


def test_replace_text_unique(env) -> None:
    root, files = env
    files.create_file("a.txt", "foo bar foo")
    d = files.current_hash("a.txt")
    with pytest.raises(Exception):
        files.replace_text("a.txt", d, "foo", "X")  # not unique
    with pytest.raises(Exception):
        files.replace_text("a.txt", d, "nope", "X")  # not found
    files.replace_text("a.txt", d, "bar", "BAR")
    assert files.read_file("a.txt")[0] == "foo BAR foo"


def test_create_directory_and_delete(env) -> None:
    root, files = env
    files.create_directory("x/y")
    assert (root / "x" / "y").is_dir()
    files.delete_empty_directory("x/y")
    assert not (root / "x" / "y").exists()
    files.delete_empty_directory("x")


def test_delete_directory_not_empty(env) -> None:
    root, files = env
    files.create_file("d/a.txt", "x")
    with pytest.raises(Exception):
        files.delete_empty_directory("d")


def test_move_file(env) -> None:
    root, files = env
    files.create_file("a.txt", "data")
    files.move("a.txt", "sub/b.txt")
    assert (root / "sub" / "b.txt").read_text(encoding="utf-8") == "data"
    assert not (root / "a.txt").exists()


def test_move_dir(env) -> None:
    root, files = env
    files.create_file("d/a.txt", "x")
    files.move("d", "e")
    assert (root / "e" / "a.txt").exists()


def test_move_into_own_subtree(env) -> None:
    root, files = env
    files.create_directory("d")
    with pytest.raises(Exception):
        files.move("d", "d/sub")


def test_delete_file_requires_hash(env) -> None:
    root, files = env
    files.create_file("a.txt", "x")
    with pytest.raises(Exception):
        files.delete_file("a.txt", "0" * 64)
    d = files.current_hash("a.txt")
    files.delete_file("a.txt", d)
    assert not (root / "a.txt").exists()


def test_binary_rejected(env) -> None:
    root, files = env
    (root / "bin.dat").write_bytes(b"\x00\x01\x02")
    with pytest.raises(Exception):
        files.read_file("bin.dat")


def test_read_size_limit(env, tmp_path: Path) -> None:
    root = tmp_path / "ws2"
    root.mkdir()
    cfg = Config(root=root, limits=Limits(max_read_bytes=10, max_file_bytes=100))
    files = FileService(cfg, PathGuard(root))
    files.create_file("small.txt", "12345")
    (root / "big.txt").write_bytes(b"x" * 50)
    with pytest.raises(Exception):
        files.read_file("big.txt")


def test_write_size_limit(env) -> None:
    root, files = env
    with pytest.raises(Exception):
        files.create_file("big.txt", "x" * (files and 3 * 1024 * 1024))


def test_atomic_write_no_tmp_leftover(env) -> None:
    root, files = env
    files.create_file("a.txt", "v1")
    d = files.current_hash("a.txt")
    files.replace_file("a.txt", "v2", d)
    leftovers = [p.name for p in root.iterdir() if ".mcp-tmp-" in p.name]
    assert leftovers == []


def test_utf8_sig_encoding(env) -> None:
    root, files = env
    files.create_file("bom.txt", "hello", encoding="utf-8-sig")
    raw = (root / "bom.txt").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
