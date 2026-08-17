"""No-execution / no-network guarantees.

Two layers, both test-enforced:

1. STATIC: AST scan of every module under src/. Production code must not
   import or call process-execution or network APIs. This is the primary
   guarantee - the model-facing surface contains no such capability, so
   no runtime patching of the Python stdlib is needed or performed.

2. RUNTIME REGRESSIONS:
   - a full local-stack run (CRUD, search, transaction, checkpoint,
     diff, restore) must make ZERO subprocess attempts, even with hook
     files deliberately planted inside the managed .git (blocks the
     dulwich post-commit execution path);
   - hook neutralization is verified against real executable hooks on
     POSIX (where a shell script is trivially executable) and against
     the subprocess-attempt counter on Windows.

Note: the runtime layer intentionally does NOT monkeypatch the stdlib in
production. Global stubbing of subprocess/socket added no evidence-backed
protection (the model has no path to those APIs) and broke asyncio's
event loop on Windows. See THREAT_MODEL.md.
"""

from __future__ import annotations

import ast
import subprocess  # noqa: S404 - test harness records/block calls
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "safe_workspace_mcp"

FORBIDDEN_MODULES = {
    "subprocess",
    "socket",
    "asyncio.subprocess",
    "multiprocessing",
    "ctypes",
    "winreg",
    "signal",
}
FORBIDDEN_IMPORT_NAMES = {
    "subprocess",
    "Popen",
    "system",
    "popen",
    "exec",
    "eval",
    "__import__",
    "urlopen",
    "create_connection",
    "getaddrinfo",
}
FORBIDDEN_CALL_ATTRS = {
    "system",
    "popen",
    "Popen",
    "exec",
    "eval",
    "urlopen",
    "create_connection",
    "getaddrinfo",
}
NETWORK_MODULES = {"urllib.request", "http", "http.client", "ftplib", "smtplib", "telnetlib"}


def test_no_forbidden_imports() -> None:
    for f in sorted(SRC.glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root not in FORBIDDEN_MODULES, f"{f.name}: import {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                assert root not in FORBIDDEN_MODULES, f"{f.name}: from {node.module}"
                for alias in node.names:
                    assert alias.name not in FORBIDDEN_IMPORT_NAMES or root in (
                        "models", "errors", "config"
                    ), f"{f.name}: from {node.module} import {alias.name}"


def test_no_network_imports() -> None:
    for f in sorted(SRC.glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in NETWORK_MODULES, (
                        f"{f.name}: network import {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "") not in NETWORK_MODULES, (
                    f"{f.name}: network import from {node.module}"
                )


def test_no_forbidden_calls() -> None:
    for f in sorted(SRC.glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    assert func.id not in FORBIDDEN_CALL_ATTRS, (
                        f"{f.name}: call to {func.id}()"
                    )
                elif isinstance(func, ast.Attribute):
                    assert func.attr not in FORBIDDEN_CALL_ATTRS, (
                        f"{f.name}: call to .{func.attr}()"
                    )


# ------------------------------------------------------------------
# Runtime regression: zero subprocess attempts across the full stack,
# with planted hook files (the dulwich post-commit attack path).
# ------------------------------------------------------------------


class _AttemptRecorder:
    def __init__(self) -> None:
        self.attempts: list[str] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # IMPORTANT: import safe_workspace_mcp modules (and thereby dulwich)
        # BEFORE patching: dulwich evaluates `subprocess.Popen[bytes]` type
        # annotations at import time.
        import safe_workspace_mcp.git_store  # noqa: F401

        for attr in ("run", "Popen", "call", "check_call", "check_output"):
            monkeypatch.setattr(
                subprocess,
                attr,
                self._blocked(attr),
                raising=True,
            )

    def _blocked(self, attr: str):
        def raiser(*args: object, **kwargs: object) -> None:
            self.attempts.append(f"subprocess.{attr}: {args!r}")
            raise AssertionError(
                f"subprocess.{attr} attempted: {args!r} - the no-execution "
                "invariant was violated"
            )

        return raiser


def _drive_full_stack(root: Path) -> None:
    from safe_workspace_mcp.config import Config
    from safe_workspace_mcp.file_service import FileService
    from safe_workspace_mcp.git_store import GitStore
    from safe_workspace_mcp.models import ApplyChanges, CreateFileOp, ReplaceFileOp
    from safe_workspace_mcp.path_guard import PathGuard
    from safe_workspace_mcp.search_service import SearchService
    from safe_workspace_mcp.transaction import TransactionManager

    cfg = Config(root=root)
    guard = PathGuard(root)
    files = FileService(cfg, guard)
    git = GitStore(cfg, guard)
    git.open_or_init()
    search = SearchService(cfg, guard)
    tx = TransactionManager(cfg, files, git)

    files.create_file("hello.txt", "world\n")
    text, digest, _ = files.read_file("hello.txt")
    assert text == "world\n"
    files.list_directory("")
    hits, _ = search.search("world")
    assert hits
    assert "world" in git.diff(None)
    git.history(5)

    applied, _pre, post = tx.apply(
        ApplyChanges(
            operations=[
                CreateFileOp(path="a.txt", content="aaa\n"),
                ReplaceFileOp(path="hello.txt", content="bye\n", expected_sha256=digest),
            ]
        )
    )
    assert all(r.status == "ok" for r in applied)
    git.restore(post, pre_restore_checkpoint=post)


def test_full_stack_makes_zero_subprocess_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sys.path.insert(0, str(SRC.parent))
    recorder = _AttemptRecorder()
    recorder.install(monkeypatch)

    root = tmp_path / "ws"
    root.mkdir()
    _drive_full_stack(root)
    assert recorder.attempts == []


def test_hooks_never_execute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Planted .git/hooks files must never run during checkpoint/restore.

    Regression for the dulwich attack path: worktree.commit() executes
    hooks["post-commit"] unconditionally (no_verify only covers
    pre-commit/commit-msg). git_store neutralizes Hook.execute at import
    time; this test plants real hook files and proves no execution
    attempt happens.
    """
    sys.path.insert(0, str(SRC.parent))
    recorder = _AttemptRecorder()
    recorder.install(monkeypatch)

    from safe_workspace_mcp.config import Config
    from safe_workspace_mcp.git_store import GitStore
    from safe_workspace_mcp.path_guard import PathGuard

    root = tmp_path / "ws"
    root.mkdir()
    cfg = Config(root=root)
    guard = PathGuard(root)
    git = GitStore(cfg, guard)
    git.open_or_init()

    hooks_dir = root / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    marker = root / "hook-ran"
    for hook_name in ("pre-commit", "post-commit", "commit-msg"):
        hook_file = hooks_dir / hook_name
        if sys.platform == "win32":
            # Content is irrelevant on Windows: execution would still be a
            # subprocess attempt (what we assert on). A PE renamed to the
            # hook name is the real-world scenario; any bytes suffice here.
            hook_file.write_bytes(b"MZ")
        else:
            hook_file.write_text(
                f"#!/bin/sh\ntouch '{marker}'\n", encoding="utf-8"
            )
            hook_file.chmod(0o755)

    (root / "f.txt").write_text("v2\n", encoding="utf-8")
    cid = git.checkpoint("with hooks planted")
    git.restore(cid, pre_restore_checkpoint=cid)

    assert recorder.attempts == []
    if sys.platform != "win32":
        assert not marker.exists(), "hook script executed - neutralization failed"
    # Sanity: history still works with hooks present (restore appended its
    # own post-restore checkpoint on top)
    ids = [c.id for c in git.history(10)]
    assert cid in ids
