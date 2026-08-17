"""Stable error codes for Safe Workspace MCP.

Tool responses never include tracebacks or paths outside the workspace.
Each error carries a stable machine-readable code plus a human message.
"""

from __future__ import annotations


class SafeWorkspaceError(Exception):
    """Base class for all expected Safe Workspace MCP errors."""

    code = "INTERNAL_ERROR"

    def __init__(self, message: str = "") -> None:
        super().__init__(message or self.code)
        self.message = message or self.code


class PathError(SafeWorkspaceError):
    code = "PATH_OUTSIDE_WORKSPACE"


class AbsolutePathError(PathError):
    code = "ABSOLUTE_PATH_FORBIDDEN"


class PathTraversalError(PathError):
    code = "PATH_TRAVERSAL_FORBIDDEN"


class InternalPathError(PathError):
    code = "INTERNAL_PATH_FORBIDDEN"


class ExcludedPathError(PathError):
    code = "EXCLUDED_PATH"


class InvalidPathError(PathError):
    """Generic reject: bad component, reserved name, ambiguous form..."""

    code = "INVALID_PATH"


class WindowsReservedNameError(InvalidPathError):
    code = "WINDOWS_RESERVED_NAME"


class ReparsePointError(PathError):
    code = "REPARSE_POINT_FORBIDDEN"


class HardlinkError(PathError):
    code = "HARDLINK_FORBIDDEN"


class FileTooLargeError(SafeWorkspaceError):
    code = "FILE_TOO_LARGE"


class ReadTooLargeError(SafeWorkspaceError):
    code = "READ_TOO_LARGE"


class BinaryFileUnsupportedError(SafeWorkspaceError):
    code = "BINARY_FILE_UNSUPPORTED"


class HashMismatchError(SafeWorkspaceError):
    code = "HASH_MISMATCH"


class TextNotFoundError(SafeWorkspaceError):
    code = "TEXT_NOT_FOUND"


class TextNotUniqueError(SafeWorkspaceError):
    code = "TEXT_NOT_UNIQUE"


class TransactionError(SafeWorkspaceError):
    code = "TRANSACTION_FAILED"


class RollbackError(SafeWorkspaceError):
    code = "ROLLBACK_FAILED"


class ExistingGitRepoError(SafeWorkspaceError):
    code = "EXISTING_GIT_REPOSITORY_NOT_SUPPORTED"


class CheckpointNotFoundError(SafeWorkspaceError):
    code = "CHECKPOINT_NOT_FOUND"


class OperationNotAllowedError(SafeWorkspaceError):
    code = "OPERATION_NOT_ALLOWED"


class FileNotFoundError_(SafeWorkspaceError):
    code = "FILE_NOT_FOUND"


class FileExistsError_(SafeWorkspaceError):
    code = "FILE_ALREADY_EXISTS"


class DirectoryExpectedError(SafeWorkspaceError):
    code = "DIRECTORY_EXPECTED"


class NotEmptyDirectoryError(SafeWorkspaceError):
    code = "DIRECTORY_NOT_EMPTY"


class NotUnderSameRootError(SafeWorkspaceError):
    code = "NOT_UNDER_SAME_ROOT"


class GitError_(SafeWorkspaceError):
    code = "GIT_ERROR"


class ConfigError(SafeWorkspaceError):
    code = "CONFIG_ERROR"
