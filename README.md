# safe-workspace-mcp

A minimal, security-focused [MCP](https://modelcontextprotocol.io) server that provides structured read/write access to **exactly one local workspace**, with built-in local Git checkpoints and rollback.

Designed to let a chat model (e.g. ChatGPT with MCP support) safely edit files in one project folder - and nothing else.

## Windows portable quick start (no Python, no Git, no Node)

1. Download the Windows release ZIP from [Releases](https://github.com/Xs-trek/safe-workspace-mcp/releases) and extract it.
2. Prepare a workspace directory (the one folder the server may touch).
3. Get an OpenAI **Secure MCP Tunnel ID** ([create here](https://platform.openai.com/settings/organization/tunnels)) and a **Runtime API Key** ([create here](https://platform.openai.com/settings/organization/api-keys)).
4. In the extracted folder run:

   ```powershell
   .\Start-SafeWorkspaceMCP.ps1 -Workspace "D:\ChatGPT_Workspace\demo" -TunnelId "tunnel_..."
   ```

5. Enter the Runtime API Key when prompted (hidden input, never stored).
6. Keep the terminal open; `Ctrl+C` stops everything.
7. Connect the existing tunnel from ChatGPT Developer Mode - the account-side step you do yourself.

The launcher downloads the official OpenAI tunnel client (pinned `v0.0.11`, SHA-256 verified) on first run and caches it under `%LOCALAPPDATA%\SafeWorkspaceMCP\. No admin rights, no PATH/registry changes. See `README-PORTABLE.md` (or the Chinese edition `README-PORTABLE.zh-CN.md`) inside the ZIP for full details.

> Accurate claim: *portable local deployment with no Python/Git/Node installation required; the launcher bootstraps the tested OpenAI tunnel client automatically.* It is not "zero configuration" - you bring the workspace, tunnel ID, runtime key, and ChatGPT account-side setup.

## What it is

- One process = one configuration = **one fixed workspace** (chosen at startup, immutable at runtime)
- Structured text-file CRUD with atomic multi-file transactions
- Optimistic concurrency: every modification of an existing file requires its current `sha256`
- Managed local Git history (via [Dulwich](https://www.dulwich.io), never `git.exe`): pre/post-change checkpoints, diff, history, restore
- stdio MCP server, 9 tools total

## Non-goals (hard absent)

No shell, no terminal, no subprocess, no code execution, no compiler/test-runner/package-manager, no arbitrary HTTP or network tools, no remote Git, no workspace switching, no binary/image editing, no OS sandbox claims.

If a capability is not listed below, this server does not have it.

## Architecture

```
ChatGPT / any MCP client
        │
OpenAI Secure MCP Tunnel (account-side, outbound-only)
        │
tunnel-client.exe            <- external deployment layer (official OpenAI binary,
        │                       pinned + SHA-256 verified by the launcher)
        │ MCP over stdio (child process)
        ▼
Safe Workspace MCP           <- this project (9 tools, no network, no exec)
        │
   fixed single workspace
        │
   ┌────┴─────────────┐
   │                   │
structured file CRUD   managed local Git checkpoints
```

- Web search / URL fetching is done by the chat host itself; this server has no network capability by design.
- The tunnel client is an external deployment component, not part of this server: the server process itself never opens sockets, and the launcher's only network activity is downloading the pinned, checksum-verified official tunnel client.

## The nine tools

| Tool | Read-only | Purpose |
|---|---|---|
| `workspace_info` | ✓ | Workspace name, limits, version |
| `list_directory` | ✓ | List one directory (internal/excluded entries hidden) |
| `read_file` | ✓ | Read UTF-8 text file → content, sha256, size |
| `search_text` | ✓ | Literal text search, capped results |
| `apply_changes` | ✗ | Atomic transaction: create/replace file, replace text, create dir, move, delete file, delete empty dir |
| `git_status` | ✓ | Working-tree changes since last checkpoint |
| `git_diff` | ✓ | Unified diff vs a checkpoint (default: last) |
| `git_history` | ✓ | Checkpoint list (newest first) |
| `git_restore` | ✗ | Restore workspace to a checkpoint (auto-checkpoints current state first, so restores are undoable) |

`apply_changes` operations all validate first (paths, hashes, policy, plan conflicts); if anything fails, **nothing** is applied. On mid-execution failure everything is rolled back.

## Installation

Two supported paths:

- **End user (Windows)**: download the portable release ZIP - no Python/Git/Node required (see quick start above).
- **Developer / Linux**: source checkout with Python 3.12+:

```
git clone https://github.com/Xs-trek/safe-workspace-mcp.git
cd safe-workspace-mcp
py -3.12 -m venv .venv
.venv\Scripts\pip install -e .
```

Runtime dependencies: `mcp==2.0.0` (official SDK), `dulwich==1.2.6`, Python stdlib. Nothing else. End-user prerequisites for the portable release are only: Windows 10/11, PowerShell, internet for the tunnel, a workspace folder, tunnel ID + Runtime API Key, and your own ChatGPT account setup.

## Configuration

TOML file, loaded once at startup, immutable afterwards. There is no tool (and no code path) that can change the configuration, the workspace root, or any limit at runtime.

```toml
[workspace]
root = "D:/ChatGPT_Workspace/demo"
max_file_bytes = 2097152        # largest file the server will write/track
max_read_bytes = 1048576        # largest read returned / searched per file
max_transaction_bytes = 10485760
max_search_results = 200
excluded = ["node_modules", "build", "dist", ".venv"]  # plus built-ins

[paths]
reject_reparse_points = true    # symlinks/junctions/mounts: always recommended
reject_hardlinks = true
require_same_filesystem = true

[write]
allow_create_file = true
allow_modify_file = true
allow_delete_file = true
allow_move = true
allow_create_directory = true
allow_delete_empty_directory = true
require_expected_hash = true

[git]
mode = "managed"                # only mode in v0.1.0
author_name = "Safe Workspace MCP"
author_email = "safe-workspace-mcp@local"

[search]
include_hidden = false

[server]
transport = "stdio"             # only transport in v0.1.0
```

See `examples/` for minimal / existing-source / large-source variants.

### Managed workspace

On first start with an **empty or plain source directory** (no `.git`), the server:

1. scans the directory (only regular text files are tracked),
2. initializes a managed repository at `<root>/.git`,
3. writes a `safe-workspace-mcp.managed-repository-format` marker into `.git/config` (so the repo is provably ours on later restarts),
4. creates the `initial snapshot` checkpoint.

On subsequent starts, the server **reopens its own managed repo** (identified by the marker). A workspace containing a foreign `.git` (plain `git init`, a clone, or a repo without the managed marker) is rejected with `EXISTING_GIT_REPOSITORY_NOT_SUPPORTED`. Adopting existing repositories, worktrees, submodules, and remotes remains out of scope.

**Editable ⇒ Recoverable**: every regular file the MCP can modify or delete is tracked in the managed repository, so it can always be restored from a checkpoint. Excluded directories (node_modules, build artifacts, virtualenvs, …) are invisible to every tool — not readable, not writable, not searched, not checkpointed.

## Running

```
.venv\Scripts\safe-workspace-mcp path\to\config.toml
```

The server speaks MCP on stdio and logs to stderr. It refuses to start if the workspace root does not exist or is unsafe.

### Multiple projects

One process serves exactly one workspace. Run several processes with several configs:

```
safe-workspace-mcp project-a.toml
safe-workspace-mcp project-b.toml
```

### Importing existing source

Point `workspace.root` at an existing source directory **without** `.git`. The initial snapshot commits the current state as the baseline; from then on the directory is managed. Large generated directories should be added to `excluded`.

## Portable usage scenarios (Windows)

- **First run on a new PC**: extract the ZIP, create/select a workspace, run the launcher, provide tunnel credentials. The launcher downloads and verifies the pinned tunnel client automatically.
- **Second run**: same launcher; the cached tunnel client is reused - no re-download, no reinstall.
- **Switching projects**: same release, different `-Workspace` path. Each MCP process still serves exactly one fixed workspace (no runtime switching).
- **Offline install (advanced)**: pre-download the official `tunnel-client-<version>-windows-<arch>.zip` yourself, verify it against the official `SHA256SUMS.txt`, and point `-TunnelClientPath` at the extracted official `tunnel-client.exe`. This is an advanced operator override: it skips the launcher's pinned SHA-256 guarantee (existence and `--version` are still checked). Not needed for normal use.

## Testing with MCP Inspector

```
npx @modelcontextprotocol/inspector .venv\Scripts\safe-workspace-mcp -- args/config.toml
```

(Or `mcp dev` from the MCP SDK CLI.) Verify `tools/list` shows exactly nine tools, the read-only annotations are correct, and exercise read → search → apply_changes → git_diff/git_history/git_restore against a disposable workspace first.

## Connecting ChatGPT Desktop / ChatGPT Web

ChatGPT reaches a local MCP server through OpenAI's Secure MCP Tunnel (Developer Mode / connectors). **This project is only the stdio server plus an operator-run launcher** - it contains no tunnel transport, no OAuth, no credentials storage, and it never reads or writes ChatGPT/Codex configuration.

Recommended flow:

1. Pass the full local test suite with a disposable workspace (see above).
2. Create a Secure MCP Tunnel in the OpenAI Platform and run the portable launcher (or `tunnel-client run` yourself) with that tunnel ID.
3. In ChatGPT, connect the existing tunnel as a developer/app connector while the launcher terminal is running.
4. Use a dedicated test workspace first, then switch the config to your real project.

Always configure ChatGPT manually in its UI.

## Security overview

- **Workspace confinement** — workspace-relative paths only; traversal, absolute/drive/UNC paths, reserved device names, ADS colons, trailing dot/space names all rejected; containment is filesystem-aware (realpath-based), never string-prefix.
- **Links** — any reparse point (symlink, junction, mount, unknown tag) in any component of an existing path ⇒ deny. Hard-linked regular files (st_nlink > 1) ⇒ deny.
- **Internal isolation** — `.git` is inaccessible through every file tool; it is only touched by the managed Git store.
- **Atomic writes** — temp sibling → fsync → validate → `os.replace`; a failed write never truncates the original.
- **Optimistic concurrency** — stale `expected_sha256` ⇒ `HASH_MISMATCH`, the user's newer file is never overwritten.
- **No execution / no network** — production code contains no subprocess/socket usage (AST-enforced by tests, scanning every module for imports and calls); dulwich's unconditional hook-execution path is neutralized at import time and regression-tested with planted hook files; the managed repo never gets hooks, filters, or remotes.
- **Resource limits** — max file/read/transaction bytes and search results; reaching a limit fails closed.
- **Prompt injection** — not solved, contained: a misled model can only perform structured, checkpointed file edits inside one folder, which you can always roll back.

See `SECURITY.md` and `THREAT_MODEL.md` for the full analysis and residual risks.

## Known limitations (v0.1.0)

- Text (UTF-8) files only; binary files are refused.
- Windows is the primary security target; Linux is supported and CI-tested.
- No concurrent multi-client coordination beyond hash checks (run one writer).
- Checkpoint history grows unboundedly (no gc in v0.1.0).
- Restores are file-level; excluded directories are untouched by restore.

## Security reporting

Please open a private security advisory (GitHub "Report a vulnerability") rather than a public issue.

## License

Apache-2.0 — see `LICENSE`.
