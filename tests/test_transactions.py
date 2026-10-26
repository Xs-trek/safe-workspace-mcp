"""Transaction tests: validation-first, rollback on failure."""

from __future__ import annotations

from pathlib import Path

import pytest

from safe_workspace_mcp import errors
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
    git.open_or_init_managed()
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


def _failing_tx(root: Path) -> ApplyChanges:
    """Creates new.txt, then fails on a replace_text whose old_text is absent."""
    return ApplyChanges(
        operations=[
            CreateFileOp(path="new.txt", content="n\n"),
            ReplaceTextOp(
                path="B.txt",
                expected_sha256=_hash(root, "B.txt"),
                old_text="zzz-not-present",
                new_text="x",
            ),
        ]
    )


def test_transaction_adds_one_commit_with_message(env) -> None:
    root, _, git, tx = env
    before = [c.id for c in git.history(50)]
    _, pre, post = tx.apply(
        ApplyChanges(
            operations=[CreateFileOp(path="new.txt", content="n\n")],
            message="add new.txt for the parser",
        )
    )
    hist = git.history(50)
    assert pre == before[0]  # unchanged state: no empty pre-change commit
    assert [c.id for c in hist] == [post, *before]
    assert hist[0].message == "add new.txt for the parser"


def test_pre_checkpoint_records_outside_edits(env) -> None:
    root, _, git, tx = env
    head = git.history(1)[0].id
    (root / "C.txt").write_text("edited outside MCP\n", encoding="utf-8")
    _, pre, post = tx.apply(ApplyChanges(operations=[CreateFileOp(path="n.txt", content="n\n")]))
    assert pre != head
    hist = git.history(3)
    assert [c.id for c in hist] == [post, pre, head]
    assert hist[0].message == "post-change checkpoint"


@pytest.mark.parametrize("bad", ["", "   ", "two\nlines", "x" * 201])
def test_invalid_message_rejected(bad: str) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ApplyChanges(operations=[CreateFileOp(path="n.txt", content="n\n")], message=bad)


def test_rollback_never_deletes_gitignored_files(env) -> None:
    """Regression: the rollback working-tree sync deleted every walkable
    file absent from the PRE commit, erasing gitignored files."""
    root, _, git, tx = env
    (root / ".gitignore").write_text("ignored/\n.env\n", encoding="utf-8")
    (root / "ignored").mkdir()
    (root / "ignored" / "keep.bin").write_bytes(b"payload")
    (root / ".env").write_bytes(b"TOKEN=local\n")
    git.checkpoint("baseline with ignore")
    with pytest.raises(errors.SafeWorkspaceError):
        tx.apply(_failing_tx(root))
    assert not (root / "new.txt").exists()
    assert (root / "B.txt").read_text(encoding="utf-8") == "bbb\n"
    assert (root / "ignored" / "keep.bin").read_bytes() == b"payload"
    assert (root / ".env").read_bytes() == b"TOKEN=local\n"


def test_rollback_survives_locked_gitignored_file(env) -> None:
    """A gitignored file held open by another process (e.g. a JDK
    lib/modules mapped by a Gradle daemon) must not turn a normal rollback
    into ROLLBACK_FAILED: the sync never touches untracked files."""
    root, _, git, tx = env
    (root / ".gitignore").write_text(".tools/\n", encoding="utf-8")
    modules = root / ".tools" / "jdk-17" / "lib" / "modules"
    modules.parent.mkdir(parents=True)
    modules.write_bytes(b"\0" * 1024)
    git.checkpoint("baseline with .tools")
    with modules.open("rb") as lock:
        with pytest.raises(errors.SafeWorkspaceError) as excinfo:
            tx.apply(_failing_tx(root))
        assert "ROLLBACK" not in str(excinfo.value).upper()
        assert lock.read(4) == b"\0\0\0\0"
    assert not (root / "new.txt").exists()
    assert (root / "B.txt").read_text(encoding="utf-8") == "bbb\n"


def test_transaction_bytes_cap(tmp_path: Path) -> None:
    from safe_workspace_mcp.config import Limits

    root = tmp_path / "ws"
    root.mkdir()
    cfg = Config(root=root, limits=Limits(max_transaction_bytes=10, max_file_bytes=1000))
    guard = PathGuard(root)
    files = FileService(cfg, guard)
    git = GitStore(cfg, guard)
    git.open_or_init_managed()
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
