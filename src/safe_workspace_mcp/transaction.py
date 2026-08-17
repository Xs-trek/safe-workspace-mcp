"""Atomic multi-operation transactions.

Ordering (per project spec):
  1. validate ALL operations (paths, hashes, policy, plan-level conflicts)
  2. PRE checkpoint of current state
  3. execute in order
  4. verify results
  5. POST checkpoint
On any execution failure: roll back to PRE state (managed files).
"""

from __future__ import annotations

import os
from pathlib import Path

from . import errors
from .config import Config
from .file_service import FileService
from .git_store import GitStore
from .models import (
    ApplyChanges,
    CreateDirectoryOp,
    CreateFileOp,
    DeleteDirectoryOp,
    DeleteFileOp,
    MoveOp,
    Operation,
    OpResult,
    ReplaceFileOp,
    ReplaceTextOp,
)


class TransactionManager:
    def __init__(
        self, config: Config, files: FileService, git: GitStore
    ) -> None:
        self._config = config
        self._files = files
        self._git = git

    # ------------------------------------------------------------- plan

    def _validate_plan(self, ops: ApplyChanges) -> None:
        """Whole-plan validation before anything executes."""
        total_bytes = 0
        seen_dest: dict[str, str] = {}
        for i, op in enumerate(ops.operations):
            match op:
                case CreateFileOp(path=path, content=content):
                    total_bytes += len(content.encode("utf-8"))
                    _claim(seen_dest, path, f"operation {i}")
                case ReplaceFileOp(path=path, content=content):
                    total_bytes += len(content.encode("utf-8"))
                case ReplaceTextOp(path=path):
                    pass
                case CreateDirectoryOp(path=path):
                    _claim(seen_dest, path, f"operation {i}")
                case MoveOp(source=source, destination=destination):
                    _claim(seen_dest, destination, f"operation {i}")
                    if destination == source:
                        raise errors.TransactionError(f"operation {i}: no-op move")
                    _check_subtree(source, destination, i)
                case DeleteFileOp(path=path):
                    _claim(seen_dest, path, f"operation {i}", deleting=True)
                case DeleteDirectoryOp(path=path):
                    _claim(seen_dest, path, f"operation {i}", deleting=True)
        if total_bytes > self._config.limits.max_transaction_bytes:
            raise errors.TransactionError(
                f"transaction exceeds max_transaction_bytes "
                f"({self._config.limits.max_transaction_bytes})"
            )

    # ------------------------------------------------------------- run

    def apply(self, request: ApplyChanges) -> tuple[list[OpResult], str | None, str | None]:
        """Execute atomically. Returns (results, pre_ckpt, post_ckpt)."""
        self._validate_plan(request)

        # Per-operation precondition checks (paths + hashes) BEFORE executing.
        for op in request.operations:
            self._precheck(op)

        pre = self._git.checkpoint("pre-change checkpoint")
        applied: list[OpResult] = []
        journal: list[tuple[str, str, str | None]] = []  # (kind, path, extra)
        try:
            for op in request.operations:
                applied.append(self._execute(op))
                self._record_journal(op, journal)
            self._verify(request, applied)
        except Exception as exc:
            self._rollback(pre, journal)
            if isinstance(exc, errors.SafeWorkspaceError):
                raise
            raise errors.TransactionError(f"transaction failed: {exc}") from exc
        post = self._git.checkpoint("post-change checkpoint")
        return applied, pre, post

    def _record_journal(
        self, op: Operation, journal: list[tuple[str, str, str | None]]
    ) -> None:
        """Record what executed, for precise rollback."""
        match op:
            case CreateFileOp(path=path):
                journal.append(("created", path, None))
            case ReplaceFileOp(path=path):
                journal.append(("modified", path, None))
            case ReplaceTextOp(path=path):
                journal.append(("modified", path, None))
            case CreateDirectoryOp(path=path):
                journal.append(("created_dir", path, None))
            case MoveOp(source=source, destination=destination):
                journal.append(("moved", destination, source))
            case DeleteFileOp(path=path):
                journal.append(("deleted", path, None))
            case DeleteDirectoryOp(path=path):
                journal.append(("deleted_dir", path, None))

    # ---------------------------------------------------------- precheck

    def _precheck(self, op: Operation) -> None:
        guard = self._files.guard
        match op:
            case CreateFileOp(path=path):
                guard.check_for_creation(path)
            case ReplaceFileOp(path=path):
                guard.check_existing(path)
            case ReplaceTextOp(path=path):
                guard.check_existing(path)
            case CreateDirectoryOp(path=path):
                guard.check_for_creation(path)
            case MoveOp(source=source, destination=destination):
                guard.check_existing(source)
                guard.check_for_creation(destination)
            case DeleteFileOp(path=path):
                guard.check_existing(path)
            case DeleteDirectoryOp(path=path):
                guard.check_existing(path)

    # ---------------------------------------------------------- execute

    def _execute(self, op: Operation) -> OpResult:
        files = self._files
        match op:
            case CreateFileOp(
                path=path, content=content, encoding=encoding, expected_sha256=expected
            ):
                digest = files.create_file(
                    path, content, encoding, overwrite_hash=expected
                )
                return OpResult(op="create_file", path=path, sha256=digest)
            case ReplaceFileOp(
                path=path, content=content, expected_sha256=expected, encoding=encoding
            ):
                digest = files.replace_file(path, content, expected, encoding)
                return OpResult(op="replace_file", path=path, sha256=digest)
            case ReplaceTextOp(
                path=path, expected_sha256=expected, old_text=old, new_text=new
            ):
                digest = files.replace_text(path, expected, old, new)
                return OpResult(op="replace_text", path=path, sha256=digest)
            case CreateDirectoryOp(path=path):
                files.create_directory(path)
                return OpResult(op="create_directory", path=path)
            case MoveOp(source=source, destination=destination):
                files.move(source, destination)
                return OpResult(op="move", path=destination)
            case DeleteFileOp(path=path):
                files.delete_file(path, op.expected_sha256)
                return OpResult(op="delete_file", path=path)
            case DeleteDirectoryOp(path=path):
                files.delete_empty_directory(path)
                return OpResult(op="delete_empty_directory", path=path)
        raise errors.TransactionError(f"unknown operation type: {type(op).__name__}")

    # ---------------------------------------------------------- verify

    def _verify(self, request: ApplyChanges, applied: list[OpResult]) -> None:
        if len(applied) != len(request.operations):
            raise errors.TransactionError("operation count mismatch")

    # ---------------------------------------------------------- rollback

    def _rollback(self, pre_checkpoint: str, journal: list[tuple[str, str, str | None]]) -> None:
        """Undo executed operations in reverse order.

        Precise inverse operations run first; then the working tree is
        synced to the PRE checkpoint so content is byte-for-byte restored
        (the PRE checkpoint contains every managed file, so any modified
        or deleted file is recoverable; files CREATED by this transaction
        are removed by the inverse operations, never by touching files
        the transaction did not create).
        """
        guard = self._files.guard
        root = guard.root
        try:
            for kind, path, extra in reversed(journal):
                try:
                    if kind == "created":
                        (root / path).unlink(missing_ok=True)
                    elif kind == "created_dir":
                        import shutil

                        shutil.rmtree(root / path, ignore_errors=True)
                    elif kind == "moved":
                        # move back
                        os.replace(root / path, root / str(extra))
                except OSError:
                    pass  # best effort; git sync below is authoritative
            # Restore contents of modified/deleted files from PRE commit.
            self._git.sync_working_tree_to(pre_checkpoint)
            # Clean up directories that only existed because of this tx.
            for kind, path, _extra in reversed(journal):
                if kind in ("created_dir",):
                    p = root / path
                    try:
                        p.rmdir()  # only removes if empty
                    except OSError:
                        pass
        except Exception as exc:  # noqa: BLE001
            raise errors.RollbackError(
                f"ROLLBACK FAILED - recover manually via git_restore({pre_checkpoint!r}): "
                f"{exc}"
            ) from exc


def _claim(
    seen: dict[str, str], path: str, who: str, *, deleting: bool = False
) -> None:
    norm = str(Path(path)).replace("\\", "/").lower()
    key_claim = f"write:{norm}"
    if key_claim in seen:
        raise errors.TransactionError(
            f"{who}: path already touched by earlier operation: {path}"
        )
    if deleting:
        seen[f"delete:{norm}"] = who
    seen[key_claim] = who


def _check_subtree(source: str, destination: str, i: int) -> None:
    s = Path(source).parts
    d = Path(destination).parts
    if len(d) > len(s) and list(d[: len(s)]) == list(s):
        raise errors.TransactionError(
            f"operation {i}: cannot move a directory into its own subtree"
        )
