"""Transaction tests: validation-first, rollback on failure."""

from __future__ import annotations

from pathlib import Path

import pytest

from safe_workspace_mcp.config import Config
from safe_workspace_mcp.errors import HashMismatchError, TransactionError
from safe_workspace_mcp.file_service import FileService
from safe_workspace_mcp.git_store import GitStore
from safe_workspace_mcp.models import (
    ApplyChanges,
    CreateDirectoryOp,
    CreateFileOp,
    DeleteFileOp,
    MoveOp,
    ReplaceFileOp,
    ReplaceTextOp,
)
from safe_workspace_mcp.path_guard import PathGuard
from safe_workspace_mcp.transaction import TransactionManager


@pytest.fixture()
def env(tmp_path: Path):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "B.txt").write_text("bbb\n", encoding="utf-8")
    (root / "C.txt").write_text("ccc\n", encoding="utf-8")
    (root / "D.txt").write_text("ddd\n", encoding="utf-8")
    cfg = Config(root=root)
    guard = PathGuard(root)
    files = FileService(cfg, guard)
    git = GitStore(cfg, guard)
    git.open_or_init()
    tx = TransactionManager(cfg, files, git)
    return root, files, git, tx


def _hash(root: Path, name: str) -> str:
    import hashlib

    return hashlib.sha256((root / name).read_bytes()).hexdigest()


def test_all_success(env) -> None:
    root, files, git, tx = env
    results, pre, post = tx.apply(
        ApplyChanges(
            operations=[
                CreateFileOp(path="A.txt", content="aaa\n"),
                ReplaceFileOp(
                    path="B.txt", content="B2\n", expected_sha256=_hash(root, "B.txt")
                ),
                MoveOp(source="C.txt", destination="C2.txt"),
                DeleteFileOp(path="D.txt", expected_sha256=_hash(root, "D.txt")),
            ]
        )
    )
    assert all(r.status == "ok" for r in results)
    assert (root / "A.txt").exists()
    assert (root / "B.txt").read_text(encoding="utf-8") == "B2\n"
    assert (root / "C2.txt").exists() and not (root / "C.txt").exists()
    assert not (root / "D.txt").exists()
    assert pre and post


def test_invalid_plan_executes_nothing(env) -> None:
    root, files, git, tx = env
    before = (root / "B.txt").read_bytes()
    with pytest.raises(TransactionError):
        tx.apply(
            ApplyChanges(
                operations=[
                    CreateFileOp(path="A.txt", content="x"),
                    # conflict: same path touched twice
                    CreateFileOp(path="A.txt", content="y"),
                ]
            )
        )
    assert not (root / "A.txt").exists()
    assert (root / "B.txt").read_bytes() == before


def test_hash_mismatch_blocks_everything(env) -> None:
    root, files, git, tx = env
    with pytest.raises(HashMismatchError):
        tx.apply(
            ApplyChanges(
                operations=[
                    CreateFileOp(path="A.txt", content="x"),
                    ReplaceFileOp(path="B.txt", content="B2\n", expected_sha256="0" * 64),
                ]
            )
        )
    assert not (root / "A.txt").exists()


def test_execution_failure_rolls_back(env) -> None:
    root, files, git, tx = env
    # op 2 fails at execution time (old_text not unique); op 1 (create A.txt)
    # already ran, so rollback must remove it and leave B.txt untouched.
    (root / "B.txt").write_text("bbb\nbbb\n", encoding="utf-8")
    import hashlib

    new_hash = hashlib.sha256((root / "B.txt").read_bytes()).hexdigest()
    with pytest.raises(Exception):
        tx.apply(
            ApplyChanges(
                operations=[
                    CreateFileOp(path="A.txt", content="aaa\n"),
                    ReplaceTextOp(
                        path="B.txt",
                        expected_sha256=new_hash,
                        old_text="bbb",
                        new_text="BBB",
                    ),
                ]
            )
        )
    # A.txt must be rolled back (deleted), B.txt unchanged
    assert not (root / "A.txt").exists()
    assert (root / "B.txt").read_text(encoding="utf-8") == "bbb\nbbb\n"


def test_transaction_bytes_cap(tmp_path: Path) -> None:
    from safe_workspace_mcp.config import Limits

    root = tmp_path / "ws"
    root.mkdir()
    cfg = Config(root=root, limits=Limits(max_transaction_bytes=10, max_file_bytes=1000))
    guard = PathGuard(root)
    files = FileService(cfg, guard)
    git = GitStore(cfg, guard)
    git.open_or_init()
    tx = TransactionManager(cfg, files, git)
    with pytest.raises(TransactionError):
        tx.apply(
            ApplyChanges(
                operations=[CreateFileOp(path="big.txt", content="x" * 50)]
            )
        )
    assert not (root / "big.txt").exists()


def test_create_directory_op(env) -> None:
    root, files, git, tx = env
    tx.apply(
        ApplyChanges(
            operations=[CreateDirectoryOp(path="x/y/z")]
        )
    )
    assert (root / "x" / "y" / "z").is_dir()
