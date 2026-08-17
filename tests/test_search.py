"""SearchService tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from safe_workspace_mcp.config import Config, SearchPolicy
from safe_workspace_mcp.file_service import FileService
from safe_workspace_mcp.path_guard import PathGuard
from safe_workspace_mcp.search_service import SearchService


@pytest.fixture()
def env(tmp_path: Path):
    root = tmp_path / "ws"
    root.mkdir()
    cfg = Config(root=root)
    guard = PathGuard(root)
    files = FileService(cfg, guard)
    files.create_directory("sub")
    files.create_file("a.txt", "alpha\nbravo\ncharlie\n")
    files.create_file("sub/b.txt", "bravo again\n")
    return root, SearchService(cfg, guard)


def test_basic_hit(env) -> None:
    _, s = env
    hits, truncated = s.search("bravo")
    assert truncated is False
    assert [(h.path, h.line) for h in hits] == [("a.txt", 2), ("sub/b.txt", 1)]


def test_no_hit(env) -> None:
    _, s = env
    hits, truncated = s.search("zulu")
    assert hits == []


def test_case_sensitive_literal(env) -> None:
    _, s = env
    hits, _ = s.search("Alpha")
    assert hits == []


def test_scope_limit(env) -> None:
    _, s = env
    hits, _ = s.search("bravo", scope_rel="sub")
    assert [h.path for h in hits] == ["sub/b.txt"]


def test_include_filter(env) -> None:
    _, s = env
    hits, _ = s.search("bravo", include="A.TXT")
    assert [h.path for h in hits] == ["a.txt"]


def test_hidden_files_skipped_by_default(env) -> None:
    root, s = env
    (root / ".hidden.txt").write_text("bravo\n", encoding="utf-8")
    hits, _ = s.search("bravo")
    assert ".hidden.txt" not in [h.path for h in hits]


def test_hidden_files_included_when_configured(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    cfg = Config(root=root, search=SearchPolicy(include_hidden=True))
    guard = PathGuard(root)
    files = FileService(cfg, guard)
    files.create_file("a.txt", "x bravo\n")
    (root / ".hidden.txt").write_text("bravo\n", encoding="utf-8")
    s = SearchService(cfg, guard)
    hits, _ = s.search("bravo")
    assert {h.path for h in hits} == {".hidden.txt", "a.txt"}


def test_git_dir_never_searched(env) -> None:
    root, s = env
    # simulate internal file (real .git exists after server start; here fake it)
    (root / ".git").mkdir(exist_ok=True)
    (root / ".git" / "config").write_text("bravo-secret\n", encoding="utf-8")
    (root / "node_modules").mkdir(exist_ok=True)
    (root / "node_modules" / "dep.js").write_text("bravo-dep\n", encoding="utf-8")
    hits, _ = s.search("bravo")
    assert all(not h.path.startswith(".git") for h in hits)
    assert all(not h.path.startswith("node_modules") for h in hits)


def test_max_results_cap(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    cfg = Config(root=root, search=SearchPolicy(max_results=2))
    guard = PathGuard(root)
    files = FileService(cfg, guard)
    files.create_file("a.txt", "x\nneedle\n")
    files.create_file("b.txt", "needle\n")
    files.create_file("c.txt", "needle\n")
    s = SearchService(cfg, guard)
    hits, truncated = s.search("needle")
    assert len(hits) == 2
    assert truncated is True


def test_binary_files_skipped(env) -> None:
    root, s = env
    (root / "blob.bin").write_bytes(b"bravo\x00\x01")
    hits, _ = s.search("bravo")
    assert "blob.bin" not in [h.path for h in hits]
