"""Restore semantics via GitStore (A -> B -> restore A -> restore pre -> B)."""

from __future__ import annotations

from pathlib import Path

import pytest

from safe_workspace_mcp.config import Config
from safe_workspace_mcp.git_store import GitStore
from safe_workspace_mcp.path_guard import PathGuard


@pytest.fixture()
def env(tmp_path: Path):
    root = tmp_path / "ws"
    root.mkdir()
    cfg = Config(root=root)
    guard = PathGuard(root)
    git = GitStore(cfg, guard)
    git.open_or_init_managed()
    return root, git


def test_a_b_restore_a_undo(env) -> None:
    root, git = env
    (root / "f").write_bytes(b"A\n")
    a_ckpt = git.checkpoint("A")
    (root / "f").write_bytes(b"B\n")
    git.checkpoint("B")
    # restore A
    pre1 = git.checkpoint("pre-restore 1")
    git.restore(a_ckpt, pre_restore_checkpoint=pre1)
    assert (root / "f").read_bytes() == b"A\n"
    # restore pre-restore (B state)
    pre2 = git.checkpoint("pre-restore 2")
    git.restore(pre1, pre_restore_checkpoint=pre2)
    assert (root / "f").read_bytes() == b"B\n"


def test_restore_deletes_new_files(env) -> None:
    root, git = env
    base = git.checkpoint("empty-ish")
    (root / "extra.txt").write_bytes(b"x\n")
    git.checkpoint("with extra")
    pre = git.checkpoint("pre")
    git.restore(base, pre_restore_checkpoint=pre)
    assert not (root / "extra.txt").exists()


def test_restore_is_recoverable_chain(env) -> None:
    """Every checkpoint made before a restore stays in history."""
    root, git = env
    (root / "f").write_bytes(b"1\n")
    c1 = git.checkpoint("one")
    (root / "f").write_bytes(b"2\n")
    c2 = git.checkpoint("two")
    pre = git.checkpoint("pre")
    git.restore(c1, pre_restore_checkpoint=pre)
    ids = [c.id for c in git.history(50)]
    assert c1 in ids and c2 in ids and pre in ids
