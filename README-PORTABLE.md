# Safe Workspace MCP — Portable Windows Release

Run a security-focused local MCP workspace server on Windows **without
installing Python, Git, or Node.js**. One folder, one script.

## What you need

- Windows 10/11 (amd64 or arm64), PowerShell, a normal user account (no admin)
- A workspace folder (the single folder Safe Workspace MCP may touch)
- An OpenAI **Secure MCP Tunnel ID** — create at
  <https://platform.openai.com/settings/organization/tunnels>
- An OpenAI **Runtime API Key** — create at
  <https://platform.openai.com/settings/organization/api-keys>
- Internet access on first launch (downloads the official OpenAI tunnel client,
  SHA-256 verified; later launches reuse the cached copy)

## Quick start

1. Extract this ZIP anywhere (a path without spaces is easiest, but spaces work).
2. Open PowerShell in the extracted folder.
3. Run:

   ```powershell
   .\Start-SafeWorkspaceMCP.ps1 -Workspace "D:\My Workspace\demo" -TunnelId "tunnel_..."
   ```

   If PowerShell blocks the script, use the one-shot, process-only form:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\Start-SafeWorkspaceMCP.ps1 ...
   ```

4. Enter your Runtime API Key when prompted (input hidden; never written to disk).
5. Keep the terminal open. `Ctrl+C` stops the tunnel and the MCP server.

The launcher then prints:

```text
Safe Workspace MCP is running through tunnel: <tunnel_id>
Connect this existing tunnel from ChatGPT Developer Mode.
No ChatGPT or Codex settings were modified.
```

Finish by connecting the tunnel as an app/connector in ChatGPT (Developer Mode).
That last step is done by you, in your OpenAI/ChatGPT account — this package
never touches ChatGPT or Codex configuration.

## What the launcher does

- Generates a runtime config for your workspace (in
  `%LOCALAPPDATA%\SafeWorkspaceMCP\runtime\`; contains no secrets).
- On first run, downloads `tunnel-client` from the official OpenAI GitHub
  release, verifies its SHA-256 against the pinned value, and caches it in
  `%LOCALAPPDATA%\SafeWorkspaceMCP\tools\`. Tampered or corrupted downloads
  abort immediately.
- Starts the packaged MCP server as a stdio child of `tunnel-client`, in the
  foreground. All tunnel traffic is outbound; no inbound ports are opened.

## Options

| Flag | Meaning |
|---|---|
| `-Workspace <path>` | Workspace folder (must exist; created only with `-CreateWorkspace`) |
| `-TunnelId <id>` | `tunnel_` + 32 hex chars; falls back to `CONTROL_PLANE_TUNNEL_ID` |
| `-CreateWorkspace` | Create the workspace folder if missing |
| `-TunnelClientPath <exe>` | Use an already-downloaded official tunnel-client instead of the cache |
| `-DryRun` | Show what would run, without starting anything |

The Runtime API Key is read from `CONTROL_PLANE_API_KEY` if set, otherwise
prompted securely. It is never written to any file, log, or command line.

## Cleaning up

Delete `%LOCALAPPDATA%\SafeWorkspaceMCP\` and the extracted folder. Nothing
else is left behind (no registry, PATH, or system changes were made).

## What this server can do

Exactly nine tools over one fixed workspace: `workspace_info`,
`list_directory`, `read_file`, `search_text`, `apply_changes` (atomic
transactions), `git_status`, `git_diff`, `git_history`, `git_restore` — with
local Git checkpoints and rollback for every change. No shell, no code
execution, no network access from the server itself. See `THIRD_PARTY_NOTICES.md`
for bundled components and the SECURITY/THREAT_MODEL docs in the source
repository: <https://github.com/Xs-trek/safe-workspace-mcp>
