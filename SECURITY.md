# Security Policy

## Overview

Safe Workspace MCP intentionally exposes a **minimal capability surface**: structured text-file operations inside one pre-validated workspace, plus a managed local Git history. Its security does not depend on an OS sandbox. It depends on:

```
tiny capability surface
+ one fixed workspace
+ strict path validation
+ no code execution
+ no network
+ Git recoverability
```

## Workspace confinement

- The workspace root is fixed in TOML at startup, canonicalized, and immutable for the process lifetime. No tool, argument, or code path can change it.
- Only workspace-**relative** paths are accepted. Rejected lexically, before any filesystem access:
  - absolute and root-relative paths (`/x`, `\x`)
  - drive-qualified and drive-relative paths (`C:\x`, `C:/x`, `C:x`)
  - UNC (`\\server\share`, `//server/share`) and extended namespace (`\\?\...`)
  - `..` traversal in any form; `.` components; empty components (double separators)
  - any `:` in a component (NTFS alternate data streams; also drive-like forms)
  - Windows reserved device names (`CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9`, with or without extension, any casing)
  - components with trailing dots or trailing/leading whitespace (Win32 silently strips these, which would make the validated name differ from the created name)
  - NUL, control characters, and Unicode format characters (incl. RTL overrides)
- Containment is **filesystem-aware**: candidate paths are walked component-by-component with `lstat`, then compared against the canonical root via resolved paths. String-prefix comparison is never used (`D:\Workspace` vs `D:\WorkspaceOther` cannot be confused).

## Windows special paths

The validator fails closed on every form it cannot guarantee: device names in any casing, ADS colon syntax, trailing dot/space names, short-name (8.3) aliases of internal directories (the **resolved** path is re-checked against internal/excluded names, so `GIT~1` cannot reach `.git`), cross-volume components (st_dev mismatch catches bind mounts/junctions atypically tagged).

## Reparse point policy

Any reparse point in any component of an existing path — symlink, junction, mount point, or unknown tag (including cloud-file placeholders) — is **denied**, whether it points inside or outside the workspace. Non-existent targets of `create` operations are validated to the nearest existing ancestor and re-validated after creation.

## Hardlink policy

Regular files with `st_nlink > 1` are denied to both reads and writes. Directory link counts are never treated as hardlinks. Windows regression tests create real hardlinks (`os.link`); symlink tests require elevated privileges and run in CI as admin, skipping with an explicit reason where privileges are unavailable.

## Atomic writes

All writes go through: temp file in the same directory → write → flush → fsync → size validation → `os.replace` (atomic) → post-write re-validation through the full path guard. A crash mid-write leaves the original file intact and at most one `.mcp-tmp-*.tmp` leftover, which is invisible to tools and never checkpointed.

## Expected hashes (optimistic concurrency)

`read_file` returns the file's SHA-256. Every modification or deletion of an existing file requires `expected_sha256`; a mismatch (`HASH_MISMATCH`) aborts the whole transaction with no changes. A file you edited in your editor between the model's read and write is therefore never silently overwritten.

## Transactions

`apply_changes` validates the entire plan first (paths, hashes, policy, duplicate-path conflicts, byte budget), takes a **pre-change checkpoint**, executes in order, verifies, then takes a **post-change checkpoint**. Any failure triggers rollback: executed operations are undone precisely (in reverse order), and managed files are synced byte-for-byte to the pre-change checkpoint. `ROLLBACK_FAILED` (git store unavailable) is reported with the pre-change checkpoint id for manual recovery.

## Git isolation

- `.git` belongs exclusively to the internal Git store; every file tool rejects it (`INTERNAL_PATH_FORBIDDEN`), including case variants and short-name aliases.
- The repository is **created and owned by the server**; startup refuses if `.git` already exists. No adoption, no worktrees, no submodules.
- **No remotes**: no `fetch/push/pull/clone` code path exists; startup fails if a remote is configured in the managed repo.
- Git access is library-level (Dulwich). `git.exe` is never invoked.
- Line-ending translation is pinned off (`core.autocrlf=false`, `core.eol=lf` locally) so checkpoints and restores are byte-exact regardless of the user's global git config.
- dulwich's hook-execution path (which shells out even for missing hooks) is permanently neutralized at import time; commits additionally pass `no_verify=True`. Verified by a regression test that plants hook files inside `.git` and proves no execution attempt occurs.

## No subprocess / no execution

- Production code contains no `subprocess`, `os.system`, `Popen`, shell invocation, or dynamic import — enforced by AST-based tests that scan every module under `src/`, not just review. This is the primary guarantee: the model-facing tool surface contains no execution capability, so there is no path from tool arguments to a process-creation API.
- No compiler, test runner, package manager, or eval/exec anywhere.
- One evidence-backed runtime hardening is applied: dulwich's git-hook execution is neutralized at import time (see below), because dulwich executes `hooks["post-commit"]` unconditionally on every commit — a real subprocess attempt per checkpoint — which would execute any binary planted at `.git/hooks/post-commit`. `PathGuard`'s `.git` isolation is the first line of defense; the hook neutralization is an independent second layer, regression-tested with planted hook files.
- We deliberately do **not** monkeypatch `subprocess`/`socket` globally at runtime: it guards no real attack path (business code is statically forbidden from those APIs) and would break legitimate infrastructure (asyncio's event loop on Windows needs socket pairs).

## No local network tools

- No HTTP client, no socket usage, no DNS, no downloads, no web search/fetch tools. The MCP server speaks stdio only. (A tunnel client you run to expose this server to a remote host is external infrastructure, not part of this project.)
- AST tests forbid network imports and network calls in production code; the model has no tool that reaches any network primitive.

## Resource limits

`max_file_bytes`, `max_read_bytes`, `max_transaction_bytes`, `max_search_results` are loaded once and never raised at runtime. Hitting a limit fails the operation (fail closed). Search additionally skips binary/large files and never follows links.

## Prompt injection

Web content or repository text may instruct the model to make harmful edits. This project does not attempt to *prevent* prompt injection. It *contains the blast radius*: the misled model still cannot execute anything, leave the workspace, exfiltrate via network tools, or make an un-checkpointed change; every edit is diffable and revertible via `git_restore`.

## Residual risks

- **TOCTOU**: path validation and the subsequent filesystem operation are not one atomic step. Mitigations: writes are atomic replaces, post-write re-validation, hardlink/reparse re-checks; the window is tiny and the attacker requires local code execution, at which point the OS is the relevant boundary.
- **Same-user authority**: the server runs with your user's full filesystem authority; confinement is enforced by this program's logic, not by the OS. Do not run it against workspaces containing data you cannot afford to lose; rely on checkpoints.
- **Excluded directories are not checkpointed**: contents the server cannot see cannot be restored by the server.
- **Filenames that differ only by case** on case-sensitive filesystems are distinct files; on Windows they are the same file. The validator checks the resolved path, but cross-platform case-collision semantics are the OS's.
- **Model-mediated data loss**: `git_restore` and `apply_changes` do what an injected prompt asks, within the workspace. Review `git_diff` before restores; keep pre-checkpoints (they are automatic).

## Reporting

Please use GitHub's private vulnerability reporting. Include the tool call JSON if applicable. Do not open public issues for exploitable behavior.
