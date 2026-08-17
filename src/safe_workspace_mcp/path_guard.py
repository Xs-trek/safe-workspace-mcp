"""Filesystem-aware path validation for exactly one fixed workspace root.

This is the single shared path-security authority for every tool.
All other services must construct paths through PathGuard.

Guarantees (fail-closed on anything uncertain):

* Input must be a workspace-relative path using ``/`` or ``\\`` separators.
* Rejected lexically: absolute/root-relative paths, drive-qualified and
  drive-relative paths, UNC, ``..`` traversal, empty or ``.`` components,
  any ``:`` in a component (NTFS alternate data streams), Windows reserved
  device names, trailing dots/spaces, NUL and control/format characters,
  overly long components, internal names (``.git``, ``.workspace-mcp``)
  and configured excluded names, in any casing.
* Rejected on the filesystem: any reparse point (symlink, junction,
  mount point, unsupported tag) in any existing component, cross-volume
  components (st_dev mismatch, catches bind mounts), hard-linked regular
  files (st_nlink > 1), and 8.3-short-name aliases of internal/excluded
  names (re-checked against the resolved path).
* Containment is computed filesystem-aware (realpath + is_relative_to),
  never with string prefix comparison.

TOCTOU between validation and use is inherent to path-based APIs; write
operations re-validate after creation (see FileService).
"""

from __future__ import annotations

import errno
import os
import stat
import unicodedata
from pathlib import Path
from typing import Final

from . import errors

_RESERVED_DEVICES: Final[frozenset[str]] = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)
_INTERNAL_NAMES: Final[frozenset[str]] = frozenset({".git", ".workspace-mcp"})
DEFAULT_EXCLUDED_NAMES: Final[frozenset[str]] = frozenset(
    {"node_modules", "build", "dist", ".venv", "__pycache__"}
)
_MAX_COMPONENT_CHARS: Final[int] = 255
_MAX_TOTAL_CHARS: Final[int] = 1024
_FILE_ATTRIBUTE_REPARSE_POINT: Final[int] = 0x400


def _is_reparse_point(st: os.stat_result) -> bool:
    """True if the lstat result marks a Windows reparse point."""
    return bool(getattr(st, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


class PathGuard:
    """Validates and resolves paths inside one immutable workspace root."""

    def __init__(
        self,
        root: os.PathLike[str] | str,
        *,
        reject_reparse_points: bool = True,
        reject_hardlinks: bool = True,
        require_same_filesystem: bool = True,
        excluded_names: frozenset[str] = DEFAULT_EXCLUDED_NAMES,
    ) -> None:
        raw = Path(root)
        if not raw.exists():
            raise errors.PathError(f"workspace root does not exist: {raw}")
        resolved = raw.resolve(strict=True)
        if not resolved.is_dir():
            raise errors.PathError("workspace root must be a directory")
        if resolved.parent == resolved:
            raise errors.PathError("workspace root must not be a filesystem root")
        st = os.lstat(resolved)
        if stat.S_ISLNK(st.st_mode) or _is_reparse_point(st):
            raise errors.ReparsePointError("workspace root must not be a link")
        self._root = resolved
        self._root_str = str(resolved)
        self._reject_reparse_points = reject_reparse_points
        self._reject_hardlinks = reject_hardlinks
        self._require_same_filesystem = require_same_filesystem
        self._excluded = frozenset(n.lower() for n in excluded_names)
        self._root_st = os.stat(resolved)

    @property
    def root(self) -> Path:
        return self._root

    # ------------------------------------------------------------------
    # Lexical validation
    # ------------------------------------------------------------------

    def _check_chars(self, rel: str) -> None:
        if len(rel) > _MAX_TOTAL_CHARS:
            raise errors.InvalidPathError("path too long")
        for ch in rel:
            if unicodedata.category(ch) in ("Cc", "Cf", "Cs"):
                raise errors.InvalidPathError("control or format character in path")

    def _lexical_parts(self, rel: str) -> list[str]:
        if not isinstance(rel, str):
            raise errors.InvalidPathError("path must be a string")
        if rel == "":
            raise errors.InvalidPathError("path must not be empty")
        if rel != rel.strip():
            raise errors.InvalidPathError("path must not have leading/trailing whitespace")
        self._check_chars(rel)
        if rel[0] in ("/", "\\"):
            raise errors.AbsolutePathError("absolute and root-relative paths are forbidden")
        if len(rel) >= 2 and rel[1] == ":" and rel[0].isascii() and rel[0].isalpha():
            raise errors.AbsolutePathError("drive-qualified paths are forbidden")
        parts = [p for p in rel.replace("\\", "/").split("/")]
        for part in parts:
            self._check_component(part)
        self._reject_special_names(parts)
        return parts

    def _check_component(self, part: str) -> None:
        if part == "":
            raise errors.InvalidPathError("empty path component")
        if part == "..":
            raise errors.PathTraversalError(".. is forbidden")
        if part == ".":
            raise errors.InvalidPathError("'.': components must be explicit")
        if ":" in part:
            raise errors.InvalidPathError("':' is forbidden in path components")
        if part != part.strip() or part.endswith("."):
            raise errors.InvalidPathError(
                "component must not have leading/trailing whitespace or trailing dots"
            )
        if len(part) > _MAX_COMPONENT_CHARS:
            raise errors.InvalidPathError("path component too long")
        stem = part.split(".")[0].upper()
        if stem in _RESERVED_DEVICES:
            raise errors.WindowsReservedNameError(f"reserved device name: {stem}")

    def _reject_special_names(self, parts: list[str]) -> None:
        for part in parts:
            low = part.lower()
            if low in _INTERNAL_NAMES:
                raise errors.InternalPathError(f"internal path is forbidden: {part}")
            if low in self._excluded:
                raise errors.ExcludedPathError(f"excluded path: {part}")

    # ------------------------------------------------------------------
    # Filesystem validation
    # ------------------------------------------------------------------

    def _walk_existing(self, parts: list[str]) -> tuple[Path, int]:
        """Walk components from the root; return (deepest existing path, index).

        Raises on reparse points and cross-volume components among existing
        components. Stops at the first missing component.
        """
        cur = self._root
        for i, part in enumerate(parts):
            nxt = cur / part
            try:
                st = os.lstat(nxt)
            except FileNotFoundError:
                return cur, i
            except OSError as exc:
                if exc.errno == errno.ENOTDIR:
                    raise errors.DirectoryExpectedError(
                        f"a parent component is not a directory: {part}"
                    ) from exc
                raise errors.PathError(f"cannot inspect path component: {exc}") from exc
            if self._reject_reparse_points and (
                stat.S_ISLNK(st.st_mode) or _is_reparse_point(st)
            ):
                raise errors.ReparsePointError(f"reparse point in path: {part}")
            if self._require_same_filesystem and st.st_dev != self._root_st.st_dev:
                raise errors.ReparsePointError(f"cross-filesystem component in path: {part}")
            cur = nxt
        return cur, len(parts)

    def _check_resolved(self, candidate: Path) -> Path:
        """Containment plus resolved-name re-check (8.3 short-name defense)."""
        resolved = Path(os.path.realpath(candidate))
        if not resolved.is_relative_to(self._root):
            raise errors.PathError("resolved path escapes the workspace")
        rel_parts = resolved.relative_to(self._root).parts
        self._reject_special_names(list(rel_parts))
        return resolved

    def _check_hardlink(self, candidate: Path) -> None:
        if not self._reject_hardlinks:
            return
        st = os.stat(candidate)
        if stat.S_ISREG(st.st_mode) and st.st_nlink > 1:
            raise errors.HardlinkError("file has multiple hard links")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_relative(self, rel: str) -> Path:
        """Lexically validate a workspace-relative path; return the absolute path."""
        parts = self._lexical_parts(rel)
        return self._root.joinpath(*parts)

    def check_existing(self, rel: str) -> Path:
        """Validate a path that must already exist; return its absolute path."""
        parts = self._lexical_parts(rel)
        candidate = self._root.joinpath(*parts)
        deepest, reached = self._walk_existing(parts)
        if reached < len(parts):
            raise errors.FileNotFoundError_(f"not found: {rel}")
        self._check_resolved(candidate)
        self._check_hardlink(candidate)
        return candidate

    def check_for_creation(self, rel: str) -> Path:
        """Validate a path that may not exist yet.

        The nearest existing ancestor must be a safe directory; the missing
        tail must be lexically valid (already checked). The caller must
        re-validate with check_existing() after creation.
        """
        parts = self._lexical_parts(rel)
        candidate = self._root.joinpath(*parts)
        deepest, reached = self._walk_existing(parts)
        if reached == len(parts):
            # Already exists: full validation (reparse/hardlink) applies.
            self._check_resolved(candidate)
            self._check_hardlink(candidate)
            return candidate
        if reached > 0 and not deepest.is_dir():
            raise errors.DirectoryExpectedError(
                f"a parent component is not a directory: {parts[reached - 1]}"
            )
        return candidate

    def is_internal_or_excluded_dir(self, name: str) -> bool:
        """True if a directory entry name must be hidden from listings/search."""
        low = name.lower()
        return (
            low in _INTERNAL_NAMES
            or low in self._excluded
            or (low.startswith(".mcp-tmp-") and low.endswith(".tmp"))
        )
