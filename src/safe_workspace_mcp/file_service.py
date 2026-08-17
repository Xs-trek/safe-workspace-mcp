"""File operations: safe CRUD on regular text files inside the workspace.

Guarantees:
* Every path goes through the single PathGuard.
* Writes are atomic: temp sibling -> fsync -> validate -> os.replace.
* Overwrites/deletes require expected_sha256 (optimistic concurrency).
* Only text files are readable/writable (NUL-byte and decode checks).
* Resource limits fail closed.
* Move never crosses the workspace; destination re-validated.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Literal

from . import errors
from .config import Config
from .path_guard import PathGuard


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def looks_binary(data: bytes) -> bool:
    """Heuristic: any NUL byte in the first 8 KiB means binary."""
    return b"\x00" in data[:8192]


class FileService:
    def __init__(self, config: Config, guard: PathGuard) -> None:
        self._config = config
        self._guard = guard

    @property
    def guard(self) -> PathGuard:
        return self._guard

    # ------------------------------------------------------------- read

    def read_file(self, rel: str) -> tuple[str, str, int]:
        """Return (text, sha256, size)."""
        p = self._guard.check_existing(rel)
        size = p.stat().st_size
        if size > self._config.limits.max_read_bytes:
            raise errors.ReadTooLargeError(
                f"file exceeds max_read_bytes ({self._config.limits.max_read_bytes})"
            )
        data = p.read_bytes()
        if looks_binary(data):
            raise errors.BinaryFileUnsupportedError("binary files are not supported")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise errors.BinaryFileUnsupportedError(
                "file is not valid UTF-8 text"
            ) from exc
        return text, sha256_bytes(data), len(data)

    def list_directory(
        self, rel: str = ""
    ) -> list[tuple[str, Literal["file", "directory"], int | None]]:
        """Return [(name, 'file'|'directory', size)] with internal/excluded hidden."""
        if rel == "":
            directory = self._guard.root
        else:
            directory = self._guard.check_existing(rel)
            if not directory.is_dir():
                raise errors.DirectoryExpectedError(f"not a directory: {rel}")
        out: list[tuple[str, Literal["file", "directory"], int | None]] = []
        for entry in sorted(os.scandir(directory), key=lambda e: e.name):
            if self._guard.is_internal_or_excluded_dir(entry.name):
                continue
            if entry.is_dir(follow_symlinks=False):
                out.append((entry.name, "directory", None))
            else:
                try:
                    st = entry.stat(follow_symlinks=False)
                    out.append((entry.name, "file", st.st_size))
                except OSError:
                    continue
        return out

    # ------------------------------------------------------------- write

    def _validate_content_size(self, text: str, encoding: str) -> bytes:
        data = text.encode(encoding)
        if len(data) > self._config.limits.max_file_bytes:
            raise errors.FileTooLargeError(
                f"content exceeds max_file_bytes ({self._config.limits.max_file_bytes})"
            )
        return data

    def _atomic_write(self, target: Path, data: bytes) -> None:
        """Temp sibling -> write -> fsync -> validate -> atomic replace."""
        fd, tmp_name = tempfile.mkstemp(
            prefix=".mcp-tmp-", dir=str(target.parent), suffix=".tmp"
        )
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            if os.path.getsize(tmp) != len(data):
                raise errors.SafeWorkspaceError("temporary file size mismatch")
            os.replace(tmp, target)
        except BaseException:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        # fsync the directory so the rename is durable (best effort)
        try:
            dfd = os.open(str(target.parent), os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass

    def _post_write_revalidate(self, rel: str, target: Path) -> None:
        """Fail closed if the created/replaced file fails safety re-check."""
        try:
            self._guard.check_existing(rel)
        except errors.SafeWorkspaceError:
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def create_file(
        self,
        rel: str,
        content: str,
        encoding: str = "utf-8",
        *,
        overwrite_hash: str | None = None,
    ) -> str:
        data = self._validate_content_size(content, encoding)
        p = self._guard.check_for_creation(rel)
        if p.exists():
            if overwrite_hash is None:
                if not self._config.write.allow_modify_file:
                    raise errors.OperationNotAllowedError("file overwrite is disabled")
                raise errors.FileExistsError_(f"already exists: {rel}")
            if not self._config.write.allow_modify_file:
                raise errors.OperationNotAllowedError("file overwrite is disabled")
            self._require_hash(rel, p, overwrite_hash, allow_missing=False)
        # Parent directories are created on demand (each new component is
        # still covered by PathGuard's lexical checks and re-validation).
        p.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(p, data)
        self._post_write_revalidate(rel, p)
        return sha256_bytes(data)

    def replace_file(
        self, rel: str, content: str, expected_sha256: str, encoding: str = "utf-8"
    ) -> str:
        if not self._config.write.allow_modify_file:
            raise errors.OperationNotAllowedError("file modification is disabled")
        data = self._validate_content_size(content, encoding)
        p = self._guard.check_existing(rel)
        if not p.is_file():
            raise errors.DirectoryExpectedError(f"not a file: {rel}")
        self._require_hash(rel, p, expected_sha256, allow_missing=False)
        self._atomic_write(p, data)
        self._post_write_revalidate(rel, p)
        return sha256_bytes(data)

    def replace_text(
        self,
        rel: str,
        expected_sha256: str,
        old_text: str,
        new_text: str,
    ) -> str:
        if not self._config.write.allow_modify_file:
            raise errors.OperationNotAllowedError("file modification is disabled")
        p = self._guard.check_existing(rel)
        if not p.is_file():
            raise errors.DirectoryExpectedError(f"not a file: {rel}")
        data = p.read_bytes()
        if len(data) > self._config.limits.max_read_bytes:
            raise errors.ReadTooLargeError("file exceeds max_read_bytes")
        if looks_binary(data):
            raise errors.BinaryFileUnsupportedError("binary files are not supported")
        if sha256_bytes(data) != expected_sha256.lower():
            raise errors.HashMismatchError(
                "file changed since it was read (expected_sha256 mismatch)"
            )
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise errors.BinaryFileUnsupportedError("file is not valid UTF-8 text") from exc
        count = text.count(old_text)
        if count == 0:
            raise errors.TextNotFoundError("old_text not found in file")
        if count > 1:
            raise errors.TextNotUniqueError(f"old_text occurs {count} times; must be unique")
        updated = text.replace(old_text, new_text, 1)
        out_data = self._validate_content_size(updated, "utf-8")
        self._atomic_write(p, out_data)
        self._post_write_revalidate(rel, p)
        return sha256_bytes(out_data)

    def create_directory(self, rel: str) -> None:
        if not self._config.write.allow_create_directory:
            raise errors.OperationNotAllowedError("directory creation is disabled")
        p = self._guard.check_for_creation(rel)
        if p.exists():
            raise errors.FileExistsError_(f"already exists: {rel}")
        p.mkdir(parents=True, exist_ok=False)
        # Re-validate: every new component must pass filesystem checks.
        try:
            self._guard.check_existing(rel)
        except errors.SafeWorkspaceError:
            import shutil

            shutil.rmtree(p, ignore_errors=True)
            raise

    def move(self, source_rel: str, dest_rel: str) -> None:
        if not self._config.write.allow_move:
            raise errors.OperationNotAllowedError("move is disabled")
        src = self._guard.check_existing(source_rel)
        dst = self._guard.check_for_creation(dest_rel)
        if dst.exists():
            raise errors.FileExistsError_(f"destination already exists: {dest_rel}")
        if src == self._guard.root:
            raise errors.PathError("cannot move the workspace root")
        # Directory containment: cannot move a dir into itself.
        if src.is_dir() and dst.parent == src:
            raise errors.PathError("cannot move a directory into itself")
        if src.is_dir() and src in dst.parents:
            raise errors.PathError("cannot move a directory into its own subtree")
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dst)
        try:
            self._guard.check_existing(dest_rel)
        except errors.SafeWorkspaceError:
            os.replace(dst, src)
            raise

    def delete_file(self, rel: str, expected_sha256: str) -> None:
        if not self._config.write.allow_delete_file:
            raise errors.OperationNotAllowedError("file deletion is disabled")
        p = self._guard.check_existing(rel)
        if not p.is_file():
            raise errors.DirectoryExpectedError(f"not a file: {rel}")
        self._require_hash(rel, p, expected_sha256, allow_missing=False)
        p.unlink()
        if p.exists():
            raise errors.SafeWorkspaceError(f"delete failed: {rel}")  # pragma: no cover

    def delete_empty_directory(self, rel: str) -> None:
        if not self._config.write.allow_delete_empty_directory:
            raise errors.OperationNotAllowedError("directory deletion is disabled")
        if rel == "":
            raise errors.PathError("cannot delete the workspace root")
        p = self._guard.check_existing(rel)
        if not p.is_dir():
            raise errors.DirectoryExpectedError(f"not a directory: {rel}")
        if any(os.scandir(p)):
            raise errors.NotEmptyDirectoryError(f"directory not empty: {rel}")
        p.rmdir()

    # ------------------------------------------------------------- hash

    def current_hash(self, rel: str) -> str:
        p = self._guard.check_existing(rel)
        return sha256_bytes(p.read_bytes())

    def _require_hash(
        self, rel: str, p: Path, expected: str | None, *, allow_missing: bool
    ) -> None:
        if expected is None:
            if self._config.write.require_expected_hash and not allow_missing:
                raise errors.HashMismatchError("expected_sha256 is required")
            return
        actual = sha256_bytes(p.read_bytes())
        if actual != expected.lower():
            raise errors.HashMismatchError(
                "file changed since it was read (expected_sha256 mismatch)"
            )
