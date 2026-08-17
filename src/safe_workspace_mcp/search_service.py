"""Literal text search over workspace text files.

Pure Python, no external tools, no regex in v0.1.0, no symlink following,
never enters internal (.git) or excluded directories, results capped by
max_search_results (truncation is reported, never silently extended).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from . import errors
from .config import Config
from .models import SearchHit
from .path_guard import PathGuard


class SearchService:
    def __init__(self, config: Config, guard: PathGuard) -> None:
        self._config = config
        self._guard = guard

    def search(
        self,
        query: str,
        scope_rel: str | None = None,
        include: str | None = None,
    ) -> tuple[list[SearchHit], bool]:
        """Return (hits, truncated)."""
        limit = self._config.search.max_results
        if scope_rel:
            scope = self._guard.check_existing(scope_rel)
            if not scope.is_dir():
                raise errors.DirectoryExpectedError(f"not a directory: {scope_rel}")
        else:
            scope = self._guard.root
        include_lower = include.lower() if include else None
        hits: list[SearchHit] = []
        truncated = False
        for path in self._iter_files(scope):
            rel = path.relative_to(self._guard.root).as_posix()
            if include_lower is not None and include_lower not in path.name.lower():
                continue
            file_hits, file_truncated = self._search_file(path, rel, query, limit - len(hits))
            hits.extend(file_hits)
            if file_truncated or len(hits) >= limit:
                truncated = True
                break
        return hits[:limit], truncated

    def _iter_files(self, scope: Path) -> Iterator[Path]:
        """Iterate regular files; prune internal/excluded dirs; no symlink follow."""
        stack: list[Path] = [scope]
        while stack:
            current = stack.pop()
            with os.scandir(current) as it:
                for entry in sorted(it, key=lambda e: e.name, reverse=True):
                    if self._guard.is_internal_or_excluded_dir(entry.name):
                        continue
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            st = entry.stat(follow_symlinks=False)
                            if st.st_nlink > 1 and self._config.paths.reject_hardlinks:
                                continue
                            if not self._config.search.include_hidden and entry.name.startswith(
                                "."
                            ):
                                continue
                            yield Path(entry.path)
                    except OSError:
                        continue

    def _search_file(
        self, path: Path, rel: str, query: str, budget: int
    ) -> tuple[list[SearchHit], bool]:
        if budget <= 0:
            return [], True
        try:
            st = os.stat(path)
            if st.st_size > self._config.limits.max_read_bytes:
                return [], False
            with open(path, "rb") as fh:  # noqa: S108
                data = fh.read()
        except OSError:
            return [], False
        if b"\x00" in data[:8192]:
            return [], False
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return [], False
        hits: list[SearchHit] = []
        lines = text.splitlines(keepends=True)
        pos = 0
        for lineno, line in enumerate(lines, start=1):
            col = line.find(query)
            if col >= 0:
                hits.append(
                    SearchHit(
                        path=rel,
                        line=lineno,
                        column=col + 1,
                        line_text=line.rstrip("\r\n")[:500],
                    )
                )
                if len(hits) >= budget:
                    return hits, True
            pos += len(line)
        return hits, False
