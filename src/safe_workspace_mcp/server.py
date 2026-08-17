"""Safe Workspace MCP stdio server.

Exactly nine tools, no more:
  workspace_info, list_directory, read_file, search_text   (read-only)
  apply_changes                                            (write)
  git_status, git_diff, git_history                        (read-only)
  git_restore                                              (write)

No shell, no subprocess, no network, no dynamic capabilities.
"""

from __future__ import annotations

import logging
from typing import Annotated

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from . import __version__, errors
from .config import Config
from .file_service import FileService
from .git_store import GitStore
from .models import (
    ApplyChanges,
    ApplyResult,
    Checkpoint,
    EntryInfo,
    GitDiffResult,
    GitHistoryResult,
    GitRestoreResult,
    GitStatusResult,
    ListResult,
    Operation,
    ReadResult,
    SearchResult,
    WorkspaceInfo,
)
from .path_guard import PathGuard
from .search_service import SearchService
from .transaction import TransactionManager

logger = logging.getLogger("safe_workspace_mcp")

_RO = ToolAnnotations(read_only_hint=True, open_world_hint=False)
_WRITE = ToolAnnotations(read_only_hint=False, open_world_hint=False)


def build_server(config: Config) -> MCPServer:
    guard = PathGuard(
        config.root,
        reject_reparse_points=config.paths.reject_reparse_points,
        reject_hardlinks=config.paths.reject_hardlinks,
        require_same_filesystem=config.paths.require_same_filesystem,
        excluded_names=config.excluded_names,
    )
    files = FileService(config, guard)
    search = SearchService(config, guard)
    git = GitStore(config, guard)
    tx = TransactionManager(config, files, git)

    # Managed-git lifecycle: attach to managed repo or init a fresh one.
    if (guard.root / ".git").exists():
        git.open_existing()
    else:
        git.open_or_init()

    server = MCPServer(
        "safe-workspace-mcp",
        instructions=(
            "Structured file access to ONE fixed local workspace with local Git "
            "checkpoints. Paths are workspace-relative. Writes require "
            "expected_sha256 for existing files. No shell, no network."
        ),
    )

    def _err(exc: errors.SafeWorkspaceError) -> str:
        return f"ERROR [{exc.code}]: {exc.message}"

    # ------------------------------------------------------------ tools

    @server.tool(name="workspace_info", annotations=_RO)
    def workspace_info() -> WorkspaceInfo:
        """Describe the fixed workspace (name, limits version, git mode)."""
        return WorkspaceInfo(
            name=guard.root.name,
            git_enabled=config.git.enabled,
            version=__version__,
        )

    @server.tool(name="list_directory", annotations=_RO)
    def list_directory(
        path: Annotated[
            str, Field(description="Directory relative to workspace root; '' lists root")
        ] = "",
    ) -> ListResult:
        """List one directory (internal and excluded entries are hidden)."""
        try:
            entries = [
                EntryInfo(name=n, type=t, size=s)
                for n, t, s in files.list_directory(path)
            ]
            return ListResult(path=path or ".", entries=entries)
        except errors.SafeWorkspaceError as exc:
            raise ValueError(_err(exc)) from exc

    @server.tool(name="read_file", annotations=_RO)
    def read_file(
        path: Annotated[str, Field(description="Workspace-relative file path")],
    ) -> ReadResult:
        """Read a UTF-8 text file: returns content, sha256, size."""
        try:
            text, digest, size = files.read_file(path)
            return ReadResult(path=path, content=text, sha256=digest, size=size)
        except errors.SafeWorkspaceError as exc:
            raise ValueError(_err(exc)) from exc

    @server.tool(name="search_text", annotations=_RO)
    def search_text(
        query: Annotated[str, Field(min_length=1, description="Literal text to find")],
        path_limit: Annotated[
            str | None, Field(description="Optional directory scope")
        ] = None,
        include: Annotated[
            str | None,
            Field(description="Optional case-insensitive filename substring filter"),
        ] = None,
    ) -> SearchResult:
        """Literal text search across workspace files (capped results)."""
        try:
            hits, truncated = search.search(query, path_limit, include)
            return SearchResult(query=query, hits=hits, truncated=truncated)
        except errors.SafeWorkspaceError as exc:
            raise ValueError(_err(exc)) from exc

    @server.tool(name="apply_changes", annotations=_WRITE)
    def apply_changes(
        operations: Annotated[
            list[Annotated[Operation, Field(discriminator="op")]],
            Field(min_length=1, max_length=200,
                  description="Operations applied atomically in order"),
        ],
    ) -> ApplyResult:
        """Apply file operations atomically (create/replace/move/delete).

        All operations are validated first; if anything fails nothing is
        applied. Existing-file changes require expected_sha256.
        """
        try:
            request = ApplyChanges(operations=operations)
            applied, pre, post = tx.apply(request)
            return ApplyResult(
                applied=applied,
                checkpoint=post,
                pre_checkpoint=pre,
            )
        except errors.SafeWorkspaceError as exc:
            raise ValueError(_err(exc)) from exc

    @server.tool(name="git_status", annotations=_RO)
    def git_status() -> GitStatusResult:
        """Show working-tree changes since the last checkpoint."""
        try:
            st = git.status()
            hist = git.history(1)
            return GitStatusResult(
                modified=st["modified"],
                added=st["added"],
                removed=st["removed"],
                clean=not (st["modified"] or st["added"] or st["removed"]),
                checkpoint=hist[0].id if hist else None,
            )
        except errors.SafeWorkspaceError as exc:
            raise ValueError(_err(exc)) from exc

    @server.tool(name="git_diff", annotations=_RO)
    def git_diff(
        checkpoint: Annotated[
            str | None,
            Field(description="Checkpoint id; omit for HEAD (last checkpoint)"),
        ] = None,
    ) -> GitDiffResult:
        """Unified diff of the working tree against a checkpoint (or HEAD)."""
        try:
            return GitDiffResult(checkpoint=checkpoint, diff=git.diff(checkpoint))
        except errors.SafeWorkspaceError as exc:
            raise ValueError(_err(exc)) from exc

    @server.tool(name="git_history", annotations=_RO)
    def git_history(
        limit: Annotated[int, Field(ge=1, le=100, description="Max entries")] = 20,
    ) -> GitHistoryResult:
        """List checkpoints (most recent first)."""
        try:
            return GitHistoryResult(
                checkpoints=[
                    Checkpoint(id=c.id, message=c.message, timestamp=c.timestamp)
                    for c in git.history(limit)
                ]
            )
        except errors.SafeWorkspaceError as exc:
            raise ValueError(_err(exc)) from exc

    @server.tool(name="git_restore", annotations=_WRITE)
    def git_restore(
        checkpoint: Annotated[
            str, Field(description="Checkpoint id to restore (prefix ok)")
        ],
    ) -> GitRestoreResult:
        """Restore the workspace to a checkpoint (state is checkpointed first)."""
        try:
            pre = git.checkpoint("pre-restore checkpoint")
            git.restore(checkpoint, pre_restore_checkpoint=pre)
            return GitRestoreResult(restored_to=checkpoint, pre_restore_checkpoint=pre)
        except errors.SafeWorkspaceError as exc:
            raise ValueError(_err(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"ERROR [GIT_ERROR]: restore failed: {exc}") from exc
    return server


def main(config_path: str | None = None) -> None:
    import sys

    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    if config_path is None:
        if len(sys.argv) != 2:
            print("usage: safe-workspace-mcp <config.toml>", file=sys.stderr)
            raise SystemExit(2)
        config_path = sys.argv[1]
    from .config import load_config

    config = load_config(config_path)
    server = build_server(config)
    server.run()  # stdio
