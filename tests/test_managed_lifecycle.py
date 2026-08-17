"""Managed-repository lifecycle tests through the real production entry.

Covers the three ownership states that build_server()/open_or_init_managed()
must distinguish:
  A. no .git                -> first start creates managed repo + identity
  B. managed .git (ours)    -> restart succeeds
  C. foreign .git           -> EXISTING_GIT_REPOSITORY_NOT_SUPPORTED, always

Plus fail-closed on marker corruption/unsupported format version, and
rollback of a half-created .git when initialization fails midway.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from dulwich.repo import Repo

from safe_workspace_mcp import errors
from safe_workspace_mcp.config import Config
from safe_workspace_mcp.git_store import _MANAGED_KEY, _MANAGED_SECTION
from safe_workspace_mcp.path_guard import PathGuard
from safe_workspace_mcp.server import build_server

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def _cfg(root: Path) -> Config:
    return Config(root=root)


def _marker_value(root: Path) -> bytes | None:
    with Repo(str(root)) as repo:
        try:
            return repo.get_config().get(_MANAGED_SECTION, _MANAGED_KEY)
        except Exception:  # noqa: BLE001
            return None


def _make_foreign(root: Path, *, remote: bool = False) -> None:
    with Repo.init(str(root), mkdir=False) as repo:
        if remote:
            config = repo.get_config()
            config.set(b"remote", b"origin", b"https://example.com/x.git")
            config.write_to_path()


# ---------------------------------------------------------------- case A + B

def test_first_start_creates_managed_repo_then_restart_succeeds(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "hello.txt").write_text("hi\n", encoding="utf-8")

    # First real production start: managed repo + marker + initial snapshot.
    server1 = build_server(_cfg(root))
    assert server1 is not None
    git_dir = root / ".git"
    assert git_dir.is_dir()
    assert _marker_value(root) == b"1"
    with Repo(str(root)) as repo:
        walker = list(repo.get_walker(max_entries=1))
        assert walker[0].commit.message.decode().strip() == "initial snapshot"

    # Second real production start on the SAME workspace must succeed.
    server2 = build_server(_cfg(root))
    assert server2 is not None
    assert _marker_value(root) == b"1"


# ---------------------------------------------------------------- case C

def test_foreign_plain_git_init_rejected(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    _make_foreign(root, remote=False)
    with pytest.raises(errors.ExistingGitRepoError) as ei:
        build_server(_cfg(root))
    assert ei.value.code == "EXISTING_GIT_REPOSITORY_NOT_SUPPORTED"


def test_foreign_repo_with_remote_rejected(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    _make_foreign(root, remote=True)
    with pytest.raises(errors.ExistingGitRepoError) as ei:
        build_server(_cfg(root))
    assert ei.value.code == "EXISTING_GIT_REPOSITORY_NOT_SUPPORTED"


def test_managed_repo_tampered_with_remote_rejected(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    build_server(_cfg(root))
    with Repo(str(root)) as repo:
        config = repo.get_config()
        config.set(b"remote", b"origin", b"https://example.com/x.git")
        config.write_to_path()
    with pytest.raises(errors.ExistingGitRepoError) as ei:
        build_server(_cfg(root))
    assert ei.value.code == "EXISTING_GIT_REPOSITORY_NOT_SUPPORTED"


def test_git_dir_without_marker_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    # A real git layout (init + autocrlf pin) but WITHOUT the managed marker.
    with Repo.init(str(root), mkdir=False) as repo:
        config = repo.get_config()
        config.set(b"core", b"autocrlf", b"false")
        config.write_to_path()
    with pytest.raises(errors.ExistingGitRepoError) as ei:
        build_server(_cfg(root))
    assert ei.value.code == "EXISTING_GIT_REPOSITORY_NOT_SUPPORTED"


# ---------------------------------------------------------------- fail closed

def test_marker_unsupported_version_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    build_server(_cfg(root))
    with Repo(str(root)) as repo:
        config = repo.get_config()
        config.set(_MANAGED_SECTION, _MANAGED_KEY, b"99")
        config.write_to_path()
    with pytest.raises(errors.ExistingGitRepoError) as ei:
        build_server(_cfg(root))
    assert ei.value.code == "EXISTING_GIT_REPOSITORY_NOT_SUPPORTED"


def test_corrupt_git_config_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    build_server(_cfg(root))
    (root / ".git" / "config").write_text("not [ a valid config\n", encoding="utf-8")
    with pytest.raises(errors.ExistingGitRepoError) as ei:
        build_server(_cfg(root))
    assert ei.value.code == "EXISTING_GIT_REPOSITORY_NOT_SUPPORTED"


# ---------------------------------------------------------------- init rollback

def test_failed_init_leaves_no_zombie_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If initialization fails after Repo.init, the half-created .git must be
    rolled back so the workspace is not wedged forever; the next start can
    initialize cleanly. Fail-closed is preserved (no foreign adoption)."""
    from safe_workspace_mcp.git_store import GitStore

    root = tmp_path / "ws"
    root.mkdir()

    def _boom(self: GitStore, message: str) -> str:
        raise errors.GitError_("simulated checkpoint failure")

    monkeypatch.setattr(GitStore, "checkpoint", _boom)
    cfg = _cfg(root)
    guard = PathGuard(root)
    git = GitStore(cfg, guard)
    with pytest.raises(errors.GitError_):
        git.open_or_init_managed()
    assert not (root / ".git").exists(), "half-initialized .git must be removed"

    # After the transient failure, a clean start initializes successfully.
    monkeypatch.undo()
    git2 = GitStore(cfg, guard)
    first = git2.open_or_init_managed()
    assert first
    assert _marker_value(root) == b"1"
