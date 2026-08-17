# Changelog

All notable changes to this project are documented here.
The format follows Keep a Changelog; versioning is SemVer.

## [0.1.0] — 2026-08-17

### Added (portable deployment layer)
- Portable Windows release: PyInstaller onedir bundle (no Python/Git/Node required on the target machine), built from the exact pinned dependencies in the tag-triggered release workflow.
- `Start-SafeWorkspaceMCP.ps1`: single idempotent launcher - first-run bootstrap plus foreground launcher. Generates the per-workspace runtime config (secret-free) under `%LOCALAPPDATA%\SafeWorkspaceMCP\runtime\`, downloads the pinned official OpenAI tunnel-client (`v0.0.11`, re-verified against the GitHub releases API/`SHA256SUMS.txt`) with fail-closed SHA-256 verification, caches it per version, and runs `tunnel-client run --mcp.command ...` with the packaged server as a stdio child. `-DryRun` prints the intended command without downloading or probing. `-TunnelClientPath` is an advanced operator override: it intentionally skips the pinned SHA-256 guarantee and only checks that the target exists and `--version` executes (existence + probe failures abort).
- Runtime API Key handling: read from `CONTROL_PLANE_API_KEY` or prompted via `Read-Host -AsSecureString`; never written to disk, argv, config, or logs; environment cleaned on exit. Tunnel ID treated as non-secret.
- `packaging/`: PyInstaller spec (tracked), entry wrapper, and `build-portable.ps1` release builder producing the ZIP plus `SHA256SUMS.txt`.
- `THIRD_PARTY_NOTICES.md`: bundled runtime dependency closure with versions and licenses, generated from the real build environment.
- Release workflow (`.github/workflows/release.yml`): tag-triggered; runs the full gates, builds the portable ZIP, runs the packaged-runtime + launcher test suites, and publishes the ZIP with checksums.
- Launcher test suite: PowerShell parse check, AST/source invariants (no `Invoke-Expression`, no registry/PATH mutation, no Codex/ChatGPT access, pinned URL/version/hash present), tunnel-client argv-quoting round-trip oracle (ported from the official parser; spaces, Unicode, quotes, apostrophes), config generation/idempotency, workspace and tunnel-ID validation fail-closed, checksum-mismatch fail-closed, cache reuse, and an opt-in real-download E2E test.
- Packaged-runtime integration test: extracted release exe + official MCP stdio client over a space+Unicode workspace (nine tools, CRUD, checkpoints, `.git` isolation, clean shutdown).
- Portable guide shipped inside the release ZIP in English (`README-PORTABLE.md`) and Chinese (`README-PORTABLE.zh-CN.md`).

### Verified (v0.1.0 acceptance)
- Real end-to-end acceptance completed against ChatGPT Web via an OpenAI Secure MCP Tunnel: launcher bootstrap (pinned download, SHA-256 verify, cache), `tunnel-client` foreground run with the packaged server as a stdio child, tunnel readiness, connector discovery with exactly nine tools, workspace_info/read-only checks, `.git` internal-path denial, write flow with pre/post checkpoints, and restore with a pre-restore protection checkpoint. Ctrl+C shut down tunnel-client and the MCP child cleanly; no ChatGPT/Codex configuration was modified.

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
