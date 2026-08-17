"""Immutable startup configuration, loaded once from TOML.

Nothing in this module is reachable from MCP tool arguments. There is no
set_config / set_root / change_workspace capability anywhere in the server.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import errors
from .path_guard import DEFAULT_EXCLUDED_NAMES


@dataclass(frozen=True)
class PathPolicy:
    reject_reparse_points: bool = True
    reject_hardlinks: bool = True
    require_same_filesystem: bool = True


@dataclass(frozen=True)
class WritePolicy:
    allow_create_file: bool = True
    allow_modify_file: bool = True
    allow_delete_file: bool = True
    allow_move: bool = True
    allow_create_directory: bool = True
    allow_delete_empty_directory: bool = True
    # Recursive delete is not implemented at all; flag exists to document it.
    allow_recursive_delete: bool = False
    require_expected_hash: bool = True


@dataclass(frozen=True)
class GitPolicy:
    enabled: bool = True
    mode: str = "managed"
    auto_checkpoint: bool = True
    allow_existing_repository: bool = False
    allow_remotes: bool = False
    author_name: str = "Safe Workspace MCP"
    author_email: str = "safe-workspace-mcp@local"


@dataclass(frozen=True)
class SearchPolicy:
    include_hidden: bool = False
    max_results: int = 200


@dataclass(frozen=True)
class Limits:
    max_file_bytes: int = 2 * 1024 * 1024
    max_read_bytes: int = 1024 * 1024
    max_transaction_bytes: int = 10 * 1024 * 1024
    max_search_results: int = 200


@dataclass(frozen=True)
class Config:
    root: Path
    limits: Limits = field(default_factory=Limits)
    paths: PathPolicy = field(default_factory=PathPolicy)
    write: WritePolicy = field(default_factory=WritePolicy)
    git: GitPolicy = field(default_factory=GitPolicy)
    search: SearchPolicy = field(default_factory=SearchPolicy)
    excluded_names: frozenset[str] = DEFAULT_EXCLUDED_NAMES


_KNOWN_SECTIONS = {"workspace", "paths", "write", "git", "search", "server"}
_KNOWN_WORKSPACE = {"root", "max_file_bytes", "max_read_bytes", "max_transaction_bytes",
                    "max_search_results", "excluded"}


def _unexpected_keys(data: dict[str, Any]) -> None:
    for section in data:
        if section not in _KNOWN_SECTIONS:
            raise errors.ConfigError(f"unknown config section: [{section}]")
    for key in data.get("workspace", {}):
        if key not in _KNOWN_WORKSPACE:
            raise errors.ConfigError(f"unknown config key: workspace.{key}")


def load_config(path: os.PathLike[str] | str) -> Config:
    """Load and freeze the configuration. Fails closed on unknown keys."""
    cfg_path = Path(path)
    if not cfg_path.is_file():
        raise errors.ConfigError(f"config file not found: {cfg_path}")
    with cfg_path.open("rb") as fh:
        data = tomllib.load(fh)
    _unexpected_keys(data)

    ws = data.get("workspace", {})
    root_raw = ws.get("root")
    if not isinstance(root_raw, str) or not root_raw:
        raise errors.ConfigError("workspace.root is required")
    root = Path(root_raw).expanduser()

    limits = Limits(
        max_file_bytes=_positive_int(ws, "max_file_bytes", Limits.max_file_bytes),
        max_read_bytes=_positive_int(ws, "max_read_bytes", Limits.max_read_bytes),
        max_transaction_bytes=_positive_int(
            ws, "max_transaction_bytes", Limits.max_transaction_bytes
        ),
        max_search_results=_positive_int(ws, "max_search_results", Limits.max_search_results),
    )
    if limits.max_read_bytes > limits.max_file_bytes:
        raise errors.ConfigError("max_read_bytes must not exceed max_file_bytes")

    paths_raw = data.get("paths", {})
    paths = PathPolicy(
        reject_reparse_points=_bool(paths_raw, "reject_reparse_points", True),
        reject_hardlinks=_bool(paths_raw, "reject_hardlinks", True),
        require_same_filesystem=_bool(paths_raw, "require_same_filesystem", True),
    )

    write_raw = data.get("write", {})
    write = WritePolicy(
        allow_create_file=_bool(write_raw, "allow_create_file", True),
        allow_modify_file=_bool(write_raw, "allow_modify_file", True),
        allow_delete_file=_bool(write_raw, "allow_delete_file", True),
        allow_move=_bool(write_raw, "allow_move", True),
        allow_create_directory=_bool(write_raw, "allow_create_directory", True),
        allow_delete_empty_directory=_bool(write_raw, "allow_delete_empty_directory", True),
        allow_recursive_delete=_bool(write_raw, "allow_recursive_delete", False),
        require_expected_hash=_bool(write_raw, "require_expected_hash", True),
    )
    if write.allow_recursive_delete:
        raise errors.ConfigError("allow_recursive_delete is not supported in v0.1.0")

    git_raw = data.get("git", {})
    git = GitPolicy(
        enabled=_bool(git_raw, "enabled", True),
        mode=_word(git_raw, "mode", "managed"),
        auto_checkpoint=_bool(git_raw, "auto_checkpoint", True),
        allow_existing_repository=_bool(git_raw, "allow_existing_repository", False),
        allow_remotes=_bool(git_raw, "allow_remotes", False),
        author_name=_str(git_raw, "author_name", GitPolicy.author_name),
        author_email=_str(git_raw, "author_email", GitPolicy.author_email),
    )
    if git.mode != "managed":
        raise errors.ConfigError("git.mode must be 'managed' in v0.1.0")
    if git.allow_existing_repository:
        raise errors.ConfigError("adopting existing repositories is not supported in v0.1.0")
    if git.allow_remotes:
        raise errors.ConfigError("git remotes are not supported in v0.1.0")
    if not git.enabled:
        raise errors.ConfigError("git.enabled = false is not supported in v0.1.0")

    search_raw = data.get("search", {})
    search = SearchPolicy(
        include_hidden=_bool(search_raw, "include_hidden", False),
        max_results=_positive_int(search_raw, "max_results", limits.max_search_results),
    )

    excluded_raw = ws.get("excluded", [])
    if not isinstance(excluded_raw, list) or not all(isinstance(x, str) for x in excluded_raw):
        raise errors.ConfigError("workspace.excluded must be a list of names")
    excluded = frozenset(x.lower() for x in excluded_raw) | DEFAULT_EXCLUDED_NAMES

    transport = data.get("server", {}).get("transport", "stdio")
    if transport != "stdio":
        raise errors.ConfigError("only stdio transport is supported in v0.1.0")

    return Config(
        root=root,
        limits=limits,
        paths=paths,
        write=write,
        git=git,
        search=search,
        excluded_names=excluded,
    )


def _positive_int(section: dict[str, Any], key: str, default: int) -> int:
    v = section.get(key, default)
    if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
        raise errors.ConfigError(f"{key} must be a positive integer")
    return v


def _bool(section: dict[str, Any], key: str, default: bool) -> bool:
    v = section.get(key, default)
    if not isinstance(v, bool):
        raise errors.ConfigError(f"{key} must be a boolean")
    return v


def _str(section: dict[str, Any], key: str, default: str) -> str:
    v = section.get(key, default)
    if not isinstance(v, str) or not v:
        raise errors.ConfigError(f"{key} must be a non-empty string")
    return v


def _word(section: dict[str, Any], key: str, default: str) -> str:
    v = _str(section, key, default)
    if not v.replace("-", "").replace("_", "").isalnum():
        raise errors.ConfigError(f"{key} must be a simple word")
    return v
