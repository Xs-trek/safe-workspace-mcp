# Changelog

All notable changes to this project are documented here.
The format follows Keep a Changelog; versioning is SemVer.

## [0.1.0] — 2026-08-17

### Added
- Fixed single-workspace stdio MCP server (workspace root from TOML, immutable at runtime).
- Nine tools: `workspace_info`, `list_directory`, `read_file`, `search_text`, `apply_changes`, `git_status`, `git_diff`, `git_history`, `git_restore`, with correct read-only annotations.
- `apply_changes` atomic transactions: create_file, replace_file, replace_text, create_directory, move, delete_file, delete_empty_directory; whole-plan validation, journal-based rollback, pre/post checkpoints.
- Optimistic concurrency: mandatory `expected_sha256` for modifying/deleting existing files.
- PathGuard: workspace-relative-only paths; rejection of traversal, absolute/drive/UNC forms, Windows reserved names, ADS colons, trailing dot/space names, control/format characters; filesystem-aware containment; reparse-point (symlink/junction/mount) and hardlink denial; 8.3 alias re-check; `.git`/internal-path isolation; excluded directories (node_modules, build, dist, .venv, __pycache__).
- Managed local Git via Dulwich (no git.exe, no hooks, no filters, no remotes; autocrlf pinned off): initial snapshot, pre/post-change checkpoints, pre/post-restore checkpoints, linear checkpoint chain, byte-exact restore, prefix checkpoint ids.
- Atomic file writes (temp sibling → fsync → validate → replace) with post-write re-validation.
- Literal text search with result cap, hidden-file and excluded-path pruning, no link following.
- Runtime capability guarantees: AST-based no-exec/no-network scans plus runtime regressions (zero subprocess attempts across the full stack; planted `.git/hooks` files never execute, covering dulwich's unconditional post-commit path, which is neutralized at dulwich import time).
- Resource limits (file/read/transaction/search) loaded once, fail closed.
- Test suite: path security (incl. Windows special paths, real junction/hardlink/symlink where privileges allow), CRUD, transactions, concurrency, git checkpoint/restore/undo, AST-based no-exec/no-network scans, MCP protocol tests (exactly nine tools, annotations, error codes).
- CI: Windows + Ubuntu.
- Documentation: README, SECURITY.md, THREAT_MODEL.md, examples.

### Security
- See SECURITY.md for the full model. No sandbox is claimed; safety comes from the minimal capability surface, confinement, and Git recoverability.
