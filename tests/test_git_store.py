"""GitStore checkpoint/history/diff/restore tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from safe_workspace_mcp import errors
from safe_workspace_mcp.config import Config
from safe_workspace_mcp.git_store import GitStore
from safe_workspace_mcp.path_guard import PathGuard


@pytest.fixture()
def env(tmp_path: Path):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "f.txt").write_bytes(b"v1\n")
    cfg = Config(root=root)
    guard = PathGuard(root)
    git = GitStore(cfg, guard)
    first = git.open_or_init()
    return root, git, first


def test_initial_snapshot(env) -> None:
    root, git, first = env
    hist = git.history(10)
    assert hist[0].id == first
    assert hist[0].message == "initial snapshot"
    st = git.status()
    assert st == {"added": [], "modified": [], "removed": []}


def test_existing_git_rejected(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (root / ".git").mkdir()
    cfg = Config(root=root)
    guard = PathGuard(root)
    git = GitStore(cfg, guard)
    with pytest.raises(errors.ExistingGitRepoError):
        git.open_or_init()


def test_checkpoint_tracks_user_edits(env) -> None:
    root, git, _ = env
    (root / "f.txt").write_bytes(b"user edited\n")
    cid = git.checkpoint("pre-change checkpoint")
    st = git.status()
    assert st["modified"] == []  # now committed
    hist = git.history(1)
    assert hist[0].id == cid


def test_history_order(env) -> None:
    root, git, _ = env
    (root / "f.txt").write_bytes(b"v2\n")
    git.checkpoint("c2")
    (root / "f.txt").write_bytes(b"v3\n")
    git.checkpoint("c3")
    msgs = [c.message for c in git.history(5)]
    assert msgs[0] == "c3"
    assert msgs[1] == "c2"
    assert msgs[2] == "initial snapshot"


def test_diff_detects_change(env) -> None:
    root, git, first = env
    (root / "f.txt").write_bytes(b"changed\n")
    d = git.diff(None)
    assert "+changed" in d
    assert "-v1" in d


def test_restore_and_undo(env) -> None:
    root, git, first = env
    (root / "f.txt").write_bytes(b"v2\n")
    v2 = git.checkpoint("v2 state")
    (root / "f.txt").write_bytes(b"v3\n")
    git.checkpoint("v3 state")
    # restore to v2
    pre = git.checkpoint("pre-restore checkpoint")
    git.restore(v2, pre_restore_checkpoint=pre)
    assert (root / "f.txt").read_bytes() == b"v2\n"
    hist = [c.id for c in git.history(10)]
    assert v2 in hist  # target still reachable
    assert pre in hist  # pre-restore still reachable
    # undo restore: restore pre-restore checkpoint
    pre2 = git.checkpoint("pre-restore 2")
    git.restore(pre, pre_restore_checkpoint=pre2)
    assert (root / "f.txt").read_bytes() == b"v3\n"


def test_line_endings_preserved(env) -> None:
    root, git, first = env
    (root / "f.txt").write_bytes(b"a\r\nb\r\n")  # explicit CRLF content
    v2 = git.checkpoint("crlf state")
    (root / "f.txt").write_bytes(b"plain\n")
    git.checkpoint("plain state")
    pre = git.checkpoint("pre-restore")
    git.restore(v2, pre_restore_checkpoint=pre)
    assert (root / "f.txt").read_bytes() == b"a\r\nb\r\n"


def test_unknown_checkpoint(env) -> None:
    root, git, _ = env
    with pytest.raises(errors.CheckpointNotFoundError):
        git.restore("deadbeef", pre_restore_checkpoint="0" * 40)


def test_prefix_lookup(env) -> None:
    root, git, first = env
    (root / "f.txt").write_bytes(b"v2\n")
    git.checkpoint("second")
    hist = git.history(2)
    full = hist[1].id  # initial
    pre = git.checkpoint("pre")
    git.restore(full[:8], pre_restore_checkpoint=pre)
    assert (root / "f.txt").read_bytes() == b"v1\n"


def test_new_files_tracked_and_restorable(env) -> None:
    root, git, _ = env
    (root / "new.txt").write_bytes(b"n\n")
    n1 = git.checkpoint("with new")
    (root / "new.txt").unlink()
    pre = git.checkpoint("pre-restore")
    git.restore(n1, pre_restore_checkpoint=pre)
    assert (root / "new.txt").read_bytes() == b"n\n"


def test_git_dir_hidden_from_guard(env) -> None:
    root, git, _ = env
    with pytest.raises(errors.SafeWorkspaceError):
        git._guard.check_existing(".git/config")
