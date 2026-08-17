"""Optimistic concurrency: stale hash must fail closed."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from safe_workspace_mcp.config import Config
from safe_workspace_mcp.errors import HashMismatchError
from safe_workspace_mcp.file_service import FileService
from safe_workspace_mcp.path_guard import PathGuard


def test_manual_edit_between_read_and_write(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    files = FileService(Config(root=root), PathGuard(root))
    files.create_file("f.txt", "v1\n")
    _, hash_a, _ = files.read_file("f.txt")

    # user edits in VS Code
    (root / "f.txt").write_text("v2-user\n", encoding="utf-8")
    hash_b = hashlib.sha256((root / "f.txt").read_bytes()).hexdigest()
    assert hash_b != hash_a

    # model writes with stale hash -> must fail, user content preserved
    with pytest.raises(HashMismatchError):
        files.replace_file("f.txt", "v3-model\n", hash_a)
    assert (root / "f.txt").read_text(encoding="utf-8") == "v2-user\n"

    with pytest.raises(HashMismatchError):
        files.replace_text("f.txt", hash_a, "v1", "X")
    assert (root / "f.txt").read_text(encoding="utf-8") == "v2-user\n"

    with pytest.raises(HashMismatchError):
        files.delete_file("f.txt", hash_a)
    assert (root / "f.txt").exists()


def test_fresh_hash_succeeds(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    files = FileService(Config(root=root), PathGuard(root))
    files.create_file("f.txt", "v1\n")
    _, hash_a, _ = files.read_file("f.txt")
    files.replace_file("f.txt", "v2\n", hash_a)
    assert files.read_file("f.txt")[0] == "v2\n"
