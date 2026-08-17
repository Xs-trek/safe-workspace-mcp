# Threat Model — safe-workspace-mcp v0.1.0

## Assets

1. **Workspace contents** — the only data this server can touch. Confidentiality (read), integrity (write/delete), availability (restore).
2. **Files outside the workspace** — must remain unreachable (confidentiality + integrity).
3. **The managed `.git` history** — integrity of the recovery mechanism.
4. **Host machine** — must not gain code execution, process spawning, or outbound network capability via this server.
5. **The user's other configurations** (ChatGPT, Codex, credentials) — explicitly out of reach; this project never reads or writes them.

## Trust boundaries

```
UNTRUSTED                         TRUSTED
─────────                         ───────
MCP tool arguments          │
Model-generated paths       │
Model-generated edits       │   OS + local user authority
Workspace file contents     │   Python 3.12 runtime
Text brought in via the     │   mcp SDK, dulwich (pinned deps)
model from web search       │   this server's own code
(prompt injection vector)   │   the startup TOML config (user-authored)
```

The single hard boundary is the MCP tool-call interface. Everything arriving through it — arguments, paths, file contents, search results shown back to the model — is untrusted input.

## Trusted components

| Component | Why trusted |
|---|---|
| OS, filesystem metadata (`lstat`, realpath, `st_dev`, `st_nlink`) | the mechanism confinement is built on; if it lies, the OS is compromised |
| Local user running the server | already holds full authority over the workspace |
| Python runtime + pinned `mcp`, `dulwich` | reviewed, pinned versions; AST tests constrain our usage |
| `safe_workspace_mcp` code | small, static, boring by design; test-enforced invariants |
| Startup TOML | written by the user, not reachable from any tool |

### Portable release (deployment layer, separate from the MCP server)

| Component | Why trusted / how verified |
|---|---|
| PyInstaller-bundled Python runtime | built in the release workflow from the exact pinned dependencies; closure + licenses documented in `THIRD_PARTY_NOTICES.md` |
| `Start-SafeWorkspaceMCP.ps1` launcher | operator-run; reviewed script, AST-tested invariants (no Invoke-Expression, no registry/PATH mutation, no Codex/ChatGPT access) |
| OpenAI `tunnel-client` binary | downloaded from the official GitHub release at a pinned version (`v0.0.11`), verified against the pinned official SHA-256 before first use; fail-closed on mismatch |

The launcher's download URL, version, and hash are constants in the script.
Workspace content, MCP tool arguments, and config files cannot influence them -
so workspace prompt injection cannot redirect deployment-time downloads.

## Untrusted inputs

- Tool arguments (paths, text, hashes, checkpoint ids) — fully validated, fail-closed.
- Model-produced edits — constrained to the operation grammar; hashes prevent blind overwrites.
- **Workspace file contents** — treated as hostile text (prompt-injection carrier); they can influence the model but confer no new capability.
- Web-search-derived content entering model context — same: injection carrier, no capability.

## Capabilities deliberately absent

`shell` / `terminal` / `PTY`, `subprocess`/`Popen`/`os.system`, `eval`/`exec`/dynamic import, compilers, test runners, package managers, arbitrary HTTP or any network client, DNS, downloads, `git.exe` invocation, remote Git (fetch/push/clone), OAuth/credential handling, dynamic workspace switching, configuration mutation tools, symlink creation, recursive delete, binary file editing, images/PDFs/archives.

Each absence is enforced by AST-based static tests over the production package (no imports, no attribute calls), plus runtime regression tests: a full local-stack run (CRUD, search, transactions, checkpoints, restore) must make **zero** subprocess attempts even with executable hook files deliberately planted in the managed `.git` (covering dulwich's unconditional post-commit execution path). We intentionally do not globally monkeypatch the Python stdlib: the model-facing surface has no path to those APIs, and stdlib stubbing adds no evidence-backed protection.

## Attack surfaces & mitigations

| Attack | Mitigation |
|---|---|
| Path traversal (`../`, absolute, UNC, drive-relative) | lexical rejection before fs access; traversal-specific error codes |
| Windows reserved names / ADS / trailing dot-space | component-level rejection, all casings |
| 8.3 short-name alias to `.git` | resolved-path re-check against internal names |
| Symlink/junction escape | every existing component `lstat`-checked for reparse attribute; cross-volume `st_dev` check |
| Hardlink aliasing (modify-outside-via-inside) | `st_nlink > 1` files denied for read and write |
| Prefix confusion (`Workspace` vs `WorkspaceOther`) | filesystem-aware containment, never string prefix |
| Overwrite race (user edits between model read/write) | mandatory `expected_sha256`; whole transaction aborts on mismatch |
| Partial multi-file edit on failure | validate-all-first, journal, precise rollback + checkpoint sync |
| Unrecoverable deletion | every writable file is tracked ⇒ Editable⇒Recoverable; pre-checkpoints before every change and every restore |
| `.git` tampering via file tools | internal-path rejection + GitStore sole owner |
| Foreign-repo adoption (user runs MCP in a directory that already has a `.git`) | the server reopens a repo only if `.git/config` carries the `safe-workspace-mcp.managed-repository-format` marker at a supported version; a plain `git init` / clone / marker-less repo is rejected with `EXISTING_GIT_REPOSITORY_NOT_SUPPORTED` (fail closed); a managed repo tampered to add a remote is also rejected |
| Hook/filter execution inside dulwich | hooks neutralized at import (post-commit runs unconditionally otherwise); `no_verify=True`; no filters, no signing, no remotes ever configured; `.git` unreachable via tools (first line of defense) |
| Resource exhaustion (huge files, huge transactions, search floods) | startup-fixed limits, fail closed |
| Prompt injection -> destructive edits | capability containment + diff-before-restore + automatic pre-restore checkpoints; **not prevention** |
| Info leak via error messages | stable error codes only; no tracebacks, no absolute host paths in tool responses |
| Supply-chain: tampered tunnel-client download | pinned official URL + pinned SHA-256 from official `SHA256SUMS.txt`; mismatch deletes the file and aborts (fail closed); cached copy per version under `%LOCALAPPDATA%` |
| Supply-chain: workspace influencing the launcher | launcher reads only the workspace *path* (as data); never reads workspace files, never executes workspace content; download constants are script constants |
| Credential theft via launcher | Runtime API Key only in memory/child env via SecureString prompt or `CONTROL_PLANE_API_KEY`; never in argv/config/logs; env cleared on exit |
| Tunnel transport abusing the MCP child slot | the MCP command is built solely from the launcher's own packaged exe + generated config path; the model/workspace cannot alter `--mcp.command` |

## Residual risks (accepted for v0.1.0)

1. **TOCTOU** between validation and use (inherent to path APIs; narrowed by atomic replace + re-validation).
2. **Same-user trust**: the process could technically touch anything the user can; confinement is this program's logic, not an OS boundary. Corollary: a compromised dependency could abuse that authority — mitigated by pinning + tiny dependency set, not eliminated.
3. **Excluded dirs are invisible AND unprotected** — the server neither reads nor restores them; treat them as outside the safety envelope.
4. **Prompt injection succeeds at its actual goal** (getting the model to edit files); we only bound what "edit files" can mean and make it reversible.
5. **History growth** unbounded (no gc in v0.1.0; disk exhaustion is a availability risk inside the workspace).

## Why no Docker/VM/WSL sandbox in v0.1.0

> Because the MCP server exposes no shell, subprocess, code execution, package execution, or arbitrary local-network capability. Its model-facing authority is intentionally limited to structured filesystem operations inside one validated workspace.

An OS-level sandbox guards against a process with broad authority. This process is built to have almost no authority worth sandboxing: there is no command the model can ask for that reaches an exec API (they are stubbed out), no network primitive it can route through, and no path that leaves the workspace. The remaining risk — "the program's own logic is wrong" — is what the path tests, AST tests, and rollback machinery address, and what a sandbox would *not* fix.

**If a future version adds command execution, build, or test-running capabilities, this rationale collapses.** Such features require a redesigned threat model and an OS/container sandbox (or equivalent privilege reduction) as a hard prerequisite, plus explicit user opt-in. That decision is deliberately out of scope for v0.1.0.

## Out-of-scope threats

- Compromise of the host OS or of the user account (game over by definition).
- Malice or bugs in the MCP client/host application itself.
- Supply-chain compromise of Python or the two pinned dependencies (mitigated by pinning + review, not solved).
- Supply-chain compromise of the OpenAI tunnel-client release itself (we verify integrity against the official checksum; a malicious-but-authentic official release is beyond our detection).
- Compromise of the user's OpenAI account / tunnel credentials (account-side threat).
- Physical/local access attacks.
- Availability of the machine (crash, power loss) — durability is best-effort (fsync on writes), not transactional across the whole repo.
