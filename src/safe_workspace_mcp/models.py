"""Pydantic models for tool arguments and structured results.

These models are the MCP-facing input contract. They carry no filesystem
semantics; PathGuard remains the single validation authority.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

_REL_PATH_RE = re.compile(r"^[^\\/:*?\"<>|\r\n\t]+(?:[/\\][^\\/:*?\"<>|\r\n\t]+)*$")

RelPath = Annotated[
    str,
    Field(
        description="Workspace-relative path using '/' separators.",
        pattern=r"^[^\\/:*?\"<>|\r\n\t]+(?:[/\\][^\\/:*?\"<>|\r\n\t]+)*$",
    ),
]


class FileContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: RelPath = Field(description="Workspace-relative file path.")
    content: str = Field(description="Full text content (UTF-8).", max_length=10_000_000)
    encoding: Literal["utf-8", "utf-8-sig"] = Field(
        default="utf-8", description="Text encoding for writing."
    )


class CreateFileOp(FileContent):
    op: Literal["create_file"] = "create_file"
    expected_sha256: str | None = Field(
        default=None,
        description="Optional: if given, must match when the file already exists "
        "(overwrite); otherwise create-only.",
    )


class ReplaceFileOp(FileContent):
    op: Literal["replace_file"] = "replace_file"
    expected_sha256: str = Field(
        description="SHA-256 of the current on-disk content (optimistic concurrency)."
    )


class ReplaceTextOp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["replace_text"] = "replace_text"
    path: RelPath
    expected_sha256: str
    old_text: str = Field(min_length=1, description="Exact text to replace.")
    new_text: str = Field(description="Replacement text.")
    occurrence: Literal["unique"] = "unique"


class CreateDirectoryOp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["create_directory"] = "create_directory"
    path: RelPath


class MoveOp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["move"] = "move"
    source: RelPath
    destination: RelPath


class DeleteFileOp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["delete_file"] = "delete_file"
    path: RelPath
    expected_sha256: str = Field(description="SHA-256 of the file being deleted.")


class DeleteDirectoryOp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["delete_empty_directory"] = "delete_empty_directory"
    path: RelPath


Operation = (
    CreateFileOp
    | ReplaceFileOp
    | ReplaceTextOp
    | CreateDirectoryOp
    | MoveOp
    | DeleteFileOp
    | DeleteDirectoryOp
)


class ApplyChanges(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operations: list[Annotated[Operation, Field(discriminator="op")]] = Field(
        min_length=1, max_length=200, description="Operations applied atomically."
    )


class ReadFileArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: RelPath


class ListDirectoryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: RelPath = Field(default="", description="Directory relative to workspace root.")


class SearchTextArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=1000, description="Literal text to find.")
    path_limit: RelPath | None = Field(
        default=None, description="Optional directory scope for the search."
    )
    include: str | None = Field(
        default=None, description="Optional case-insensitive filename substring filter."
    )


class GitStatusArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GitDiffArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checkpoint: str | None = Field(
        default=None, description="Optional checkpoint id to diff against working tree."
    )


class GitHistoryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=20, ge=1, le=100)


class GitRestoreArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checkpoint: str = Field(description="Checkpoint id to restore.")


# ------------------------------------------------------------- results


class EntryInfo(BaseModel):
    name: str
    type: Literal["file", "directory"]
    size: int | None = None
    sha256: str | None = None


class ReadResult(BaseModel):
    path: str
    content: str
    sha256: str
    size: int
    encoding: str = "utf-8"


class ListResult(BaseModel):
    path: str
    entries: list[EntryInfo]


class SearchHit(BaseModel):
    path: str
    line: int
    column: int
    line_text: str


class SearchResult(BaseModel):
    query: str
    hits: list[SearchHit]
    truncated: bool


class OpResult(BaseModel):
    op: str
    path: str
    status: Literal["ok"] = "ok"
    sha256: str | None = None


class ApplyResult(BaseModel):
    applied: list[OpResult]
    checkpoint: str | None = None
    pre_checkpoint: str | None = None
    rolled_back: bool = False


class WorkspaceInfo(BaseModel):
    name: str
    root_exists: bool = True
    git_enabled: bool
    version: str


class Checkpoint(BaseModel):
    id: str
    message: str
    timestamp: int


class GitStatusResult(BaseModel):
    modified: list[str]
    added: list[str]
    removed: list[str]
    clean: bool
    checkpoint: str | None = None


class GitDiffResult(BaseModel):
    checkpoint: str | None
    diff: str


class GitHistoryResult(BaseModel):
    checkpoints: list[Checkpoint]


class GitRestoreResult(BaseModel):
    restored_to: str
    pre_restore_checkpoint: str
