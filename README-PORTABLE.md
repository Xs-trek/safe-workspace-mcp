# Safe Workspace MCP — Windows Portable Guide

Safe Workspace MCP gives ChatGPT controlled access to one fixed local workspace, with managed local Git checkpoints and rollback.

This portable Windows release is intended for end users. You do not need to install Python, Git, Node.js, npm, the MCP SDK, Dulwich, or OpenAI tunnel-client manually.

## What Safe Workspace MCP provides

The MCP exposes exactly these tools:

- `workspace_info`
- `list_directory`
- `read_file`
- `search_text`
- `apply_changes`
- `git_status`
- `git_diff`
- `git_history`
- `git_restore`

It does **not** expose:

- a shell or terminal
- arbitrary command execution
- model-accessible subprocess execution
- model-accessible network access
- Git remotes, push, pull, or fetch
- access to the internal `.git` directory

The local Git repository is managed internally for checkpoints and rollback.

---

# 1. Requirements

You need:

- Windows 10 or Windows 11 x64
- PowerShell
- Internet access
- a local workspace directory
- an OpenAI Secure MCP Tunnel ID
- an OpenAI Runtime API Key authorized for the tunnel
- a ChatGPT account/workspace with custom MCP / Developer Mode access

You do **not** need to install:

- Python
- Git
- Node.js
- npm / npx
- Docker
- WSL
- Dulwich
- MCP SDK
- `tunnel-client`

The launcher downloads and verifies the tested OpenAI `tunnel-client` automatically.

---

# 2. Download

Download the Windows x64 ZIP from this project's GitHub Releases page:

```text
safe-workspace-mcp-0.1.1-windows-x64.zip
```

Also download:

```text
SHA256SUMS.txt
```

when it is provided with the release.

Do not download individual files from the source tree for normal portable use.

---

# 3. Optional: verify the release ZIP

Before extracting the ZIP, you can verify its SHA-256 checksum:

```powershell
Get-FileHash ".\safe-workspace-mcp-0.1.1-windows-x64.zip" -Algorithm SHA256
```

Compare the result with the matching entry in:

```text
SHA256SUMS.txt
```

If the checksum does not match, do not use the archive.

---

# 4. Extract the complete ZIP

Extract the whole archive to a normal user-writable directory, for example:

```text
D:\SafeWorkspaceMCP\
```

The extracted directory should contain files similar to:

```text
Start-SafeWorkspaceMCP.ps1
safe-workspace-mcp\
README-PORTABLE.md
README-PORTABLE.zh-CN.md
LICENSE
THIRD_PARTY_NOTICES.md
```

Keep the complete extracted directory.

Do not copy only `safe-workspace-mcp.exe`.

---

# 5. Prepare a workspace

Safe Workspace MCP v0.1.1 uses one fixed workspace per running MCP instance.

For first use, an empty directory is recommended:

```powershell
New-Item -ItemType Directory -Force "D:\ChatGPT_Workspace\my-project"
```

The workspace must not already contain a **foreign** `.git` repository (one not created by Safe Workspace MCP). On first start the server creates its own managed `.git` and writes a `safe-workspace-mcp.managed-repository-format` marker; on later starts it reopens that managed repo automatically. A plain `git init`, a clone, or any repo without the marker is rejected with `EXISTING_GIT_REPOSITORY_NOT_SUPPORTED`.

If you are unsure whether a directory already has `.git`:

```powershell
Test-Path "D:\ChatGPT_Workspace\my-project\.git"
```

- `False` -> safe for first use; the server will create the managed repo.
- `True` -> if Safe Workspace MCP already ran there before, it is the managed repo and will be reopened. If it is your own `git init`/clone, the server refuses it; use an empty directory instead.

Safe Workspace MCP never adopts existing Git repositories, worktrees, submodules, or remotes.

For important projects, use a disposable copy until you are comfortable with the workflow.

Do not use your entire home directory, system drive, or a directory containing unrelated credentials or secrets as the workspace.

---

# 6. Create an OpenAI Secure MCP Tunnel

Open the OpenAI Platform Tunnels page:

```text
https://platform.openai.com/settings/organization/tunnels
```

Create a tunnel.

Example:

```text
Name:
Safe Workspace MCP

Description:
Secure tunnel for local Safe Workspace MCP
```

When the page asks for organization or ChatGPT workspace scopes, select the organization and ChatGPT workspace in which you intend to use this MCP.

After creation, save the Tunnel ID.

It looks similar to:

```text
tunnel_0123456789abcdef0123456789abcdef
```

The Tunnel ID identifies the same tunnel that will be used by both ChatGPT and the local `tunnel-client`.

---

# 7. Create a Runtime API Key

Open the OpenAI Platform Runtime API Keys page:

```text
https://platform.openai.com/settings/organization/api-keys
```

Create a Restricted runtime key.

The runtime principal should have:

```text
Tunnels: Read
Tunnels: Use
```

A Runtime API Key is used by the local `tunnel-client`.

It is different from an Admin API Key.

You do not need an Admin API Key merely to run an already-created tunnel.

Copy the complete Runtime API Key when it is created.

OpenAI does not normally show the full secret again later.

Do not:

- commit it to Git
- save it in the workspace
- put it in TOML
- put it in documentation
- paste it into ChatGPT
- pass it as a normal command-line argument

If the complete key is lost, create a new one.

---

# 8. Start Safe Workspace MCP

Open PowerShell in the extracted release directory:

```powershell
cd "D:\SafeWorkspaceMCP"
```

For the simplest interactive setup, run:

```powershell
.\Start-SafeWorkspaceMCP.ps1
```

The launcher will ask for:

```text
Workspace directory
OpenAI Secure MCP Tunnel ID
OpenAI Runtime API Key
```

Example:

```text
Workspace directory (fixed single workspace for this run):
D:\ChatGPT_Workspace\my-project

OpenAI Secure MCP Tunnel ID (tunnel_...):
tunnel_0123456789abcdef0123456789abcdef

OpenAI Runtime API Key (input hidden):
********************************
```

The Runtime API Key input is hidden.

You may also provide the non-secret values directly:

```powershell
.\Start-SafeWorkspaceMCP.ps1 `
  -Workspace "D:\ChatGPT_Workspace\my-project" `
  -TunnelId "tunnel_0123456789abcdef0123456789abcdef"
```

Then enter the Runtime API Key when prompted.

Do not pass the Runtime API Key as a normal command-line argument.

---

# 9. What happens on first launch

On the normal supported path, the launcher:

1. validates the workspace
2. checks the local tunnel-client cache
3. downloads the project-pinned official OpenAI `tunnel-client` if necessary
4. verifies its pinned SHA-256 checksum
5. stops immediately if checksum verification fails
6. creates non-secret runtime configuration
7. starts `tunnel-client`
8. starts the packaged Safe Workspace MCP as the local stdio MCP process

(The MCP core, not the launcher, decides at startup whether an existing `.git` is the server's own managed repo - reopened - or a foreign repo - rejected. The launcher does not pre-check `.git`.)

Safe Workspace MCP v0.1.1 pins a tested stable `tunnel-client` version.

The launcher output shows the pinned version at startup.

Subsequent launches reuse the verified cached tunnel-client instead of downloading it again.

---

# 10. Check tunnel status

Keep the PowerShell window open.

A successful startup should produce tunnel-client messages similar to:

```text
stdio MCP command started
control-plane poller started
tunnel metadata fetched
tunnel-client started
```

The local tunnel-client administration page is normally available at:

```text
http://127.0.0.1:8080/ui
```

A working setup should report:

```text
Health: live
Ready: ready
Logs: connected
```

`Ready: ready` is the important readiness state.

The local health/admin endpoint is bound to loopback and does not require exposing Safe Workspace MCP directly to the public Internet.

The PowerShell window must stay open while you want ChatGPT to use the local MCP.

Pressing `Ctrl+C` later stops the local tunnel runtime.

---

# 11. Add Safe Workspace MCP to ChatGPT

Current custom MCP setup is most reliably performed from ChatGPT Web.

Open:

```text
https://chatgpt.com/#settings/Connectors
```

Depending on the current ChatGPT UI, the feature may appear under Apps, Connectors, Developer Mode, or custom tools.

Create a new custom MCP app/tool.

Example:

```text
Name:
Safe Workspace MCP

Description:
Controlled single-workspace file editing with local Git checkpoints and rollback.
```

For the connection type, choose:

```text
Tunnel
```

or:

```text
Tunnel ID
```

Enter the same Tunnel ID used by the launcher:

```text
tunnel_0123456789abcdef0123456789abcdef
```

Do not enter:

```text
localhost
127.0.0.1
https://api.openai.com
the Runtime API Key
```

Safe Workspace MCP itself does not require OAuth.

If the generic form still shows OAuth-related fields, do not configure OAuth unless your own MCP implementation has been changed to require OAuth.

Accept ChatGPT's custom MCP security warning and complete the creation/tool-discovery flow.

---

# 12. Verify discovered tools

Safe Workspace MCP v0.1.1 should expose exactly nine tools:

```text
workspace_info
list_directory
read_file
search_text
apply_changes
git_status
git_diff
git_history
git_restore
```

Unexpected additional tools should be investigated before normal use.

There should be no shell, command execution, or network tool.

---

# 13. Use Safe Workspace MCP in ChatGPT

Start a normal ChatGPT Web conversation.

The most explicit first prompt is:

```text
@Safe Workspace MCP show the current workspace information and list the directory without modifying anything.
```

You may also select Safe Workspace MCP through ChatGPT's tools/apps menu.

You do not necessarily need to write:

```text
@Safe Workspace MCP
```

at the beginning of every later message once the app is already selected in the current conversation.

For a new conversation, explicitly selecting or mentioning the app is the most predictable approach.

---

# 14. Recommended first validation

## Read-only test

```text
Use Safe Workspace MCP to show the current workspace information and list the directory. Do not modify any files.
```

## Internal Git isolation test

```text
Use Safe Workspace MCP to try to read .git/config.
```

Expected behavior:

```text
ERROR [INTERNAL_PATH_FORBIDDEN]
```

The managed `.git` directory is intentionally inaccessible through normal MCP file operations.

## Write test

```text
Use Safe Workspace MCP to create hello.txt containing:

Safe Workspace MCP test

Then show the diff against the pre-change checkpoint and list the recent checkpoints.
```

A successful write transaction normally creates:

```text
pre-change checkpoint
post-change checkpoint
```

Because successful changes are checkpointed, the working tree may already be clean after the post-change checkpoint.

To inspect what changed, compare against the pre-change checkpoint.

## Restore test

```text
List the recent checkpoints and restore the workspace to the checkpoint immediately before hello.txt was created.
```

Before performing a restore, Safe Workspace MCP creates an additional protection checkpoint.

After restoring to the pre-change checkpoint:

```text
hello.txt should no longer exist
Git status should be clean
```

The pre-restore protection checkpoint allows the restore itself to be undone.

---

# 15. Checkpoints and Git behavior

Safe Workspace MCP uses managed local Git as recovery infrastructure.

For a normal successful modification:

```text
current state
    |
    +-- pre-change checkpoint
    |
    +-- apply transaction
    |
    +-- post-change checkpoint
```

For a restore:

```text
current state
    |
    +-- pre-restore protection checkpoint
    |
    +-- restore selected checkpoint
```

This design makes normal MCP changes and restores recoverable.

The `.git` directory is internal and cannot be manipulated through normal file tools.

---

# 16. Write confirmations

ChatGPT may display a confirmation before write, modify, delete, or restore operations.

Review:

- the target path
- the requested operation
- the proposed content or changes

before approving it.

Do not blindly approve unexpected actions.

---

# 17. Stop Safe Workspace MCP

When finished, return to the PowerShell window running:

```text
Start-SafeWorkspaceMCP.ps1
```

and press:

```text
Ctrl+C
```

This should stop:

```text
tunnel-client
Safe Workspace MCP child process
```

After the local tunnel runtime is stopped, ChatGPT can no longer access that local workspace through this tunnel until you start the launcher again.

---

# 18. Subsequent launches

Run the same launcher again:

```powershell
.\Start-SafeWorkspaceMCP.ps1 `
  -Workspace "D:\ChatGPT_Workspace\my-project" `
  -TunnelId "tunnel_0123456789abcdef0123456789abcdef"
```

The previously verified tunnel-client should normally be reused from the local cache.

You still provide the Runtime API Key at runtime unless you deliberately provide it through a temporary process environment variable.

The launcher does not permanently configure your system PATH, registry, ChatGPT, or Codex.

---

# 19. If PowerShell blocks the downloaded script

Do not permanently weaken the system PowerShell execution policy.

First verify that you downloaded the archive from the official project Release and, preferably, verify its SHA-256 checksum.

If Windows marks the downloaded script as blocked, you may unblock only this launcher file:

```powershell
Unblock-File ".\Start-SafeWorkspaceMCP.ps1"
```

Then run it again:

```powershell
.\Start-SafeWorkspaceMCP.ps1
```

Do not use a permanent machine-wide `Set-ExecutionPolicy` change just to run Safe Workspace MCP.

---

# 20. Advanced option: -TunnelClientPath

Normal users should not use `-TunnelClientPath`.

The default launcher path provides the project's tested supply-chain guarantee:

```text
pinned tunnel-client version
fixed official download source
pinned SHA-256
```

Advanced operators may explicitly provide another executable:

```powershell
.\Start-SafeWorkspaceMCP.ps1 `
  -Workspace "D:\ChatGPT_Workspace\my-project" `
  -TunnelId "tunnel_0123456789abcdef0123456789abcdef" `
  -TunnelClientPath "D:\ApprovedTools\tunnel-client.exe"
```

Typical advanced use cases include:

- offline deployment
- enterprise-approved tunnel-client binaries
- manual compatibility testing

When `-TunnelClientPath` is used:

```text
the project's pinned SHA-256 guarantee is skipped
```

The launcher only verifies that:

- the specified file exists
- `--version` executes successfully

This is a compatibility check, not a security authenticity check.

The operator is responsible for verifying the supplied executable against the official OpenAI release and checksum.

---

# 21. Other launcher options

`-CreateWorkspace`

May be used when you intentionally want the launcher to create the selected workspace rather than requiring an existing directory.

Use it only when you are certain the path is correct.

`-DryRun`

Shows the planned launcher behavior without downloading, probing, or starting the tunnel runtime.

It is intended for inspection and troubleshooting.

---

# 22. Security notes

Safe Workspace MCP is a capability-restricted MCP server, not an operating-system sandbox.

Its model-facing surface intentionally excludes arbitrary command execution and network access.

The launcher itself is an operator-controlled deployment component and is separate from the MCP model-facing capability surface.

The launcher may:

- download the fixed OpenAI tunnel-client release
- verify its checksum
- create local runtime configuration
- start tunnel-client
- start Safe Workspace MCP

The model cannot choose the tunnel-client download URL, version, checksum, or executable path through MCP workspace content.

Do not store unrelated secrets inside a model-readable workspace.

---

# 23. v0.1.1 limitations

Safe Workspace MCP v0.1.1 intentionally has the following limitations:

- one process manages one fixed workspace
- foreign existing `.git` repositories are not adopted; previously managed repositories are reopened
- `.git` is inaccessible through MCP file tools
- no shell
- no terminal
- no arbitrary model-triggerable command execution
- no model-accessible local network or web-fetch tool
- no Git remotes
- no clone / fetch / pull / push
- no dynamic workspace switching

These restrictions are part of the v0.1.1 security design.

---

# 24. ChatGPT Desktop

The unified ChatGPT desktop application may expose local STDIO MCP configuration for Codex separately from ChatGPT custom MCP apps.

That local STDIO configuration is not required for the Secure MCP Tunnel workflow documented here.

For Safe Workspace MCP used from normal ChatGPT conversations, use the ChatGPT custom MCP app connected to the Tunnel ID.

If the desktop application does not expose the same custom Tunnel app interface as ChatGPT Web, configure and use the custom MCP through ChatGPT Web.

Do not modify ChatGPT or Codex configuration files manually to work around missing UI.

---

# 25. Troubleshooting

## Tunnel starts but ChatGPT cannot see it

Check:

- the Tunnel ID is correct
- the tunnel is associated with the intended ChatGPT workspace
- the runtime-key principal has `Tunnels: Read` and `Tunnels: Use`
- tunnel-client reports `Ready: ready`
- tunnel-client remains running

## tunnel-client returns 401 or 403

Check that the Runtime API Key belongs to a principal with:

```text
Tunnels: Read
Tunnels: Use
```

for the selected tunnel.

## Workspace is rejected with EXISTING_GIT_REPOSITORY_NOT_SUPPORTED

Safe Workspace MCP reopens its own managed `.git` (created on a previous run) automatically. It rejects a **foreign** repository - a plain `git init`, a clone, or a repo without the `safe-workspace-mcp.managed-repository-format` marker.

If the directory is one you previously used with Safe Workspace MCP, the rejection should not happen; if it does, the marker may have been removed or the repo tampered with. Otherwise use:

- an empty workspace
- or a copy of the source tree without its existing `.git`

## ChatGPT refuses a write operation

ChatGPT may independently apply account, workspace, confirmation, or safety restrictions to MCP write operations.

Do not weaken Safe Workspace MCP's security model to bypass a ChatGPT product-level restriction.

## Tunnel-client cache already exists

Normal later launches reuse the verified cached version.

This is expected.

---

# 26. Official OpenAI references

OpenAI Tunnel management:

```text
https://platform.openai.com/settings/organization/tunnels
```

OpenAI Runtime API Keys:

```text
https://platform.openai.com/settings/organization/api-keys
```

ChatGPT connector settings:

```text
https://chatgpt.com/#settings/Connectors
```

OpenAI tunnel-client repository:

```text
https://github.com/openai/tunnel-client
```

---

# 27. Summary

For normal Windows users, the complete workflow is:

```text
Download GitHub Release ZIP
        |
        v
Extract the complete ZIP
        |
        v
Prepare a workspace without .git
        |
        v
Create/reuse an OpenAI Secure MCP Tunnel
        |
        v
Create a Restricted Runtime API Key
(Tunnels Read + Use)
        |
        v
Run Start-SafeWorkspaceMCP.ps1
        |
        v
Enter workspace + tunnel ID + runtime key
        |
        v
Wait for Health live / Ready ready / Logs connected
        |
        v
Create a ChatGPT custom MCP app using Tunnel ID
        |
        v
Select or @mention Safe Workspace MCP in ChatGPT
        |
        v
Use controlled local file editing + Git checkpoints
        |
        v
Press Ctrl+C when finished
```

No Python, Git, Node.js, npm, or manual tunnel-client installation is required for the portable Windows release.
