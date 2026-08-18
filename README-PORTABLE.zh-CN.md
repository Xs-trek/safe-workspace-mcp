# Safe Workspace MCP — Windows 便携版使用指南

Safe Workspace MCP 允许 ChatGPT 在**一个固定的本地工作区**中进行受控文件操作，并使用受管理的本地 Git checkpoint 提供修改历史与恢复能力。

本指南面向直接从 GitHub Releases 下载 Windows 便携版的普通用户。

正常使用不需要手动安装 Python、Git、Node.js、npm、MCP SDK、Dulwich 或 OpenAI tunnel-client。

## Safe Workspace MCP 提供什么

MCP 恰好暴露以下工具：

- `workspace_info`
- `list_directory`
- `read_file`
- `search_text`
- `apply_changes`
- `git_status`
- `git_diff`
- `git_history`
- `git_restore`

它**不提供**：

- Shell
- 终端
- 任意命令执行
- 模型可调用的 subprocess
- 模型可调用的网络访问
- Git remote / push / pull / fetch
- 对内部 `.git` 目录的访问

本地 Git 仓库仅作为 checkpoint 和 rollback 的内部恢复设施。

---

# 1. 使用要求

你需要：

- Windows 10 或 Windows 11 x64
- PowerShell
- 可访问互联网
- 一个本地 workspace 目录
- 一个 OpenAI Secure MCP Tunnel ID
- 一个具有对应 Tunnel 权限的 OpenAI Runtime API Key
- 已获得自定义 MCP / Developer Mode 能力的 ChatGPT 账号或工作区

你**不需要手动安装**：

- Python
- Git
- Node.js
- npm / npx
- Docker
- WSL
- Dulwich
- MCP SDK
- `tunnel-client`

启动脚本会自动下载并校验项目测试过的 OpenAI 官方 `tunnel-client`。

---

# 2. 下载

普通 Windows 用户只需要从本项目的 **GitHub Releases** 页面下载：

```text
safe-workspace-mcp-0.1.1-windows-x64.zip
```

建议同时下载：

```text
SHA256SUMS.txt
```

正常便携版使用不要从源码仓库中单独下载某几个文件。

---

# 3. 可选：验证 Release ZIP

解压前可以验证 ZIP 的 SHA-256：

```powershell
Get-FileHash ".\safe-workspace-mcp-0.1.1-windows-x64.zip" -Algorithm SHA256
```

将结果与同一 GitHub Release 中：

```text
SHA256SUMS.txt
```

对应条目比较。

如果 SHA-256 不一致，不要继续使用该压缩包。

---

# 4. 完整解压

将整个 ZIP 解压到普通用户有写权限的位置，例如：

```text
D:\SafeWorkspaceMCP\
```

解压目录应类似：

```text
Start-SafeWorkspaceMCP.ps1
safe-workspace-mcp\
README-PORTABLE.md
README-PORTABLE.zh-CN.md
LICENSE
THIRD_PARTY_NOTICES.md
```

请保留整个目录。

不要只复制 `safe-workspace-mcp.exe`。

---

# 5. 准备 workspace

Safe Workspace MCP v0.1.1 每个运行中的 MCP 实例只管理一个固定 workspace。

首次使用建议创建一个空目录：

```powershell
New-Item -ItemType Directory -Force "D:\ChatGPT_Workspace\my-project"
```

v0.1.1 使用自己管理的本地 Git。workspace 不能已经包含**外部的** `.git` 仓库（即非 Safe Workspace MCP 创建的仓库）。首次启动时，服务会创建自己的 managed `.git` 并写入 `safe-workspace-mcp.managed-repository-format` 标记；之后再次启动会自动重新打开该 managed 仓库。普通的 `git init`、clone 或没有该标记的仓库会被拒绝（`EXISTING_GIT_REPOSITORY_NOT_SUPPORTED`）。

如果你不确定目录是否已有 `.git`：

```powershell
Test-Path "D:\ChatGPT_Workspace\my-project\.git"
```

- 返回 `False`：可以首次使用，服务会创建 managed 仓库。
- 返回 `True`：如果该目录之前已被 Safe Workspace MCP 使用过，则是 managed 仓库，会被自动重新打开；如果是你自己 `git init` 或 clone 的仓库，服务会拒绝，请改用空目录。

v0.1.1 不接管已有 Git 仓库、worktree、submodule 或 remote。

首次测试重要项目时，建议先使用项目副本。

不要把整个用户目录、系统盘根目录或包含大量无关凭据/秘密信息的目录作为 workspace。

---

# 6. 创建 OpenAI Secure MCP Tunnel

打开 OpenAI Platform 的 Tunnel 管理页面：

```text
https://platform.openai.com/settings/organization/tunnels
```

创建一个 Tunnel。

例如：

```text
名称：
Safe Workspace MCP

描述：
Secure tunnel for local Safe Workspace MCP
```

如果页面要求选择：

```text
Organizations
ChatGPT workspaces
```

请选择实际使用该 MCP 的 Organization 和 ChatGPT workspace。

创建完成后保存 Tunnel ID。

格式类似：

```text
tunnel_0123456789abcdef0123456789abcdef
```

ChatGPT 与本机 `tunnel-client` 必须使用同一个 Tunnel ID。

---

# 7. 创建 Runtime API Key

打开 OpenAI Platform Runtime API Keys：

```text
https://platform.openai.com/settings/organization/api-keys
```

创建一个：

```text
Restricted
```

类型的 Runtime API Key。

Runtime principal 应具有：

```text
Tunnels: Read
Tunnels: Use
```

Runtime API Key 用于本机 `tunnel-client` 连接 OpenAI Tunnel control plane。

它与 Admin API Key 不同。

如果只是运行已经创建好的 Tunnel，不需要 Admin API Key。

Key 创建时立即保存完整 secret。

之后 OpenAI 通常只显示掩码，无法再次查看完整 key。

不要：

- 提交到 Git
- 写入 workspace
- 写入 TOML
- 写入 README
- 发给 ChatGPT
- 作为普通命令行参数传递

如果完整 key 已丢失，请创建新的 Runtime API Key。

---

# 8. 启动 Safe Workspace MCP

在解压目录打开 PowerShell：

```powershell
cd "D:\SafeWorkspaceMCP"
```

最简单的交互式启动方式：

```powershell
.\Start-SafeWorkspaceMCP.ps1
```

Launcher 会依次询问：

```text
Workspace directory
OpenAI Secure MCP Tunnel ID
OpenAI Runtime API Key
```

示例：

```text
Workspace directory (fixed single workspace for this run):
D:\ChatGPT_Workspace\my-project

OpenAI Secure MCP Tunnel ID (tunnel_...):
tunnel_0123456789abcdef0123456789abcdef

OpenAI Runtime API Key (input hidden):
********************************
```

Runtime API Key 输入是隐藏的。

也可以直接传递非秘密参数：

```powershell
.\Start-SafeWorkspaceMCP.ps1 `
  -Workspace "D:\ChatGPT_Workspace\my-project" `
  -TunnelId "tunnel_0123456789abcdef0123456789abcdef"
```

随后在隐藏输入框中输入 Runtime API Key。

不要把 Runtime API Key 作为普通命令行参数。

---

# 9. 第一次启动会执行什么

默认支持路径下，Launcher 会：

1. 验证 workspace
2. 检查本地 tunnel-client 缓存
3. 缺失时下载项目固定的 OpenAI 官方 `tunnel-client`
4. 验证项目固定的 SHA-256
5. SHA-256 不匹配时立即停止
6. 创建不包含 Runtime API Key 的运行配置
7. 启动 `tunnel-client`
8. 由 tunnel-client 拉起 packaged Safe Workspace MCP stdio 进程

（`.git` 是 managed 还是外部仓库，由 MCP 核心在启动时判断，而非 launcher 预检查；launcher 不检查 `.git`。）

Safe Workspace MCP v0.1.1 固定使用经过项目实际验证的稳定 tunnel-client 版本。

Launcher 启动时会显示当前 pin。

之后再次运行时，会直接复用已校验的 tunnel-client 缓存。

---

# 10. 检查 Tunnel 是否正常

保持 PowerShell 窗口开启。

正常启动日志通常包括：

```text
stdio MCP command started
control-plane poller started
tunnel metadata fetched
tunnel-client started
```

本地 tunnel-client 管理页面通常位于：

```text
http://127.0.0.1:8080/ui
```

正常状态应为：

```text
Health: live
Ready: ready
Logs: connected
```

其中最关键的是：

```text
Ready: ready
```

本地 health/admin 服务默认只监听 loopback。

Safe Workspace MCP 本身不需要直接暴露公网入站端口。

**只要希望 ChatGPT 能继续访问本地 workspace，就必须保持这个 PowerShell 窗口和 tunnel-client 运行。**

---

# 11. 在 ChatGPT Web 中添加 Safe Workspace MCP

当前推荐使用 ChatGPT Web 配置自定义 MCP。

打开：

```text
https://chatgpt.com/#settings/Connectors
```

根据当前 ChatGPT UI，入口可能显示为：

```text
Apps
Connectors
Developer Mode
自定义工具
创建新插件
```

创建一个新的自定义 MCP。

建议填写：

```text
名称：
Safe Workspace MCP

描述：
Controlled single-workspace file editing with local Git checkpoints and rollback.
```

连接类型选择：

```text
Tunnel
```

或：

```text
隧道 ID
```

填写与 Launcher 相同的：

```text
tunnel_0123456789abcdef0123456789abcdef
```

不要填写：

```text
localhost
127.0.0.1
https://api.openai.com
Runtime API Key
```

Safe Workspace MCP 本身不需要 OAuth。

如果通用表单仍然显示 OAuth 相关字段，只要 Safe Workspace MCP 本身没有改造成 OAuth MCP，就不要额外配置 OAuth。

阅读并确认 ChatGPT 对自定义 MCP 的安全警告，然后完成工具发现/创建。

---

# 12. 检查工具发现

Safe Workspace MCP v0.1.1 应恰好暴露 9 个工具：

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

如果出现其它额外工具，应先调查原因再使用。

正常情况下不应出现：

```text
shell
exec
terminal
network
fetch
```

等工具。

---

# 13. 在 ChatGPT 中使用

新开一个普通 ChatGPT Web 对话。

首次最明确的提示词：

```text
@Safe Workspace MCP 查看当前 workspace 信息并列出目录，不要修改任何文件。
```

也可以先在 ChatGPT 输入框附近的工具 / Apps 菜单中选择：

```text
Safe Workspace MCP
```

当前对话已经选中该 App 后，后续通常**不需要每句话都以**：

```text
@Safe Workspace MCP
```

开头。

对于新对话，为避免调用错误工具，建议首次显式 `@Safe Workspace MCP`，或者先从工具菜单选择它。

---

# 14. 推荐首次验证

## 只读测试

```text
使用 Safe Workspace MCP 查看当前 workspace 信息并列出目录，不要修改任何文件。
```

## `.git` 内部目录隔离测试

```text
使用 Safe Workspace MCP 尝试读取 .git/config。
```

正常结果：

```text
ERROR [INTERNAL_PATH_FORBIDDEN]
```

即使 `.git/config` 位于 workspace 内部，也不能通过普通 MCP 文件工具读取。

这是设计行为。

## 写入测试

```text
使用 Safe Workspace MCP 创建 hello.txt，内容为：

Safe Workspace MCP test

然后显示相对修改前 checkpoint 的 git diff 和最近的 checkpoint。
```

一次正常的成功修改会形成：

```text
pre-change checkpoint
post-change checkpoint
```

因为成功修改后已经生成 POST checkpoint，所以当前 HEAD 相对 working tree 的 diff 可以为空。

如果要查看本次具体变化，应与 PRE checkpoint 比较。

## Restore 测试

```text
列出最近 checkpoint，并恢复到创建 hello.txt 之前的状态。
```

执行 restore 前，Safe Workspace MCP 会先自动创建一个保护 checkpoint。

恢复成功后：

```text
hello.txt 不应存在
Git status 应为 clean
```

因为 restore 前存在保护 checkpoint，所以 restore 本身也可以被撤销。

---

# 15. Checkpoint 工作方式

普通修改：

```text
当前状态
    |
    +-- pre-change checkpoint
    |
    +-- 执行 apply_changes
    |
    +-- post-change checkpoint
```

恢复：

```text
当前状态
    |
    +-- pre-restore protection checkpoint
    |
    +-- restore 指定 checkpoint
```

因此正常 MCP 修改和恢复操作都具有本地恢复链。

`.git` 仅作为内部恢复设施，不能通过正常 MCP 文件工具操作。

---

# 16. ChatGPT 写操作确认

ChatGPT 可能在：

- 创建文件
- 修改文件
- 删除文件
- 移动文件
- restore

等操作前要求确认。

确认前请检查：

- 目标路径
- 操作类型
- 要写入或修改的内容

不要盲目批准不符合预期的写操作。

---

# 17. 停止 Safe Workspace MCP

使用完成后，回到运行：

```text
Start-SafeWorkspaceMCP.ps1
```

的 PowerShell 窗口。

按：

```text
Ctrl+C
```

应关闭：

```text
tunnel-client
Safe Workspace MCP child process
```

停止后，ChatGPT 将无法继续通过该 Tunnel 访问本地 workspace。

下次重新运行 Launcher 即可恢复连接。

---

# 18. 第二次及后续启动

再次执行：

```powershell
.\Start-SafeWorkspaceMCP.ps1 `
  -Workspace "D:\ChatGPT_Workspace\my-project" `
  -TunnelId "tunnel_0123456789abcdef0123456789abcdef"
```

正常情况下会复用之前已经验证过的 tunnel-client 缓存，不再重新下载。

仍然需要在运行时提供 Runtime API Key，除非你主动通过当前进程的临时环境变量提供。

Launcher 不会永久修改：

```text
PATH
Registry
ChatGPT 配置
Codex 配置
PowerShell Execution Policy
```

---

# 19. 如果 Windows 阻止运行 PowerShell 脚本

不要为了运行本项目永久降低整个系统的 PowerShell Execution Policy。

首先确认 ZIP 来自本项目官方 GitHub Release，并建议先验证 SHA-256。

如果 Windows 只阻止这个下载得到的脚本，可以只解除该文件的下载阻止标记：

```powershell
Unblock-File ".\Start-SafeWorkspaceMCP.ps1"
```

然后重新：

```powershell
.\Start-SafeWorkspaceMCP.ps1
```

不要为了 Safe Workspace MCP 执行永久性的机器级：

```text
Set-ExecutionPolicy
```

修改。

---

# 20. 高级选项：-TunnelClientPath

普通用户不要使用：

```text
-TunnelClientPath
```

默认路径具有项目验证过的供应链保证：

```text
固定 tunnel-client 版本
固定官方来源
固定 SHA-256
```

高级操作者可以明确指定其它 tunnel-client：

```powershell
.\Start-SafeWorkspaceMCP.ps1 `
  -Workspace "D:\ChatGPT_Workspace\my-project" `
  -TunnelId "tunnel_0123456789abcdef0123456789abcdef" `
  -TunnelClientPath "D:\ApprovedTools\tunnel-client.exe"
```

适用场景包括：

- 离线部署
- 企业已批准的 tunnel-client
- 手工兼容性测试

使用 `-TunnelClientPath` 后：

```text
项目 pinned SHA-256 guarantee 被明确跳过
```

Launcher 只检查：

- 文件存在
- `--version` 可以成功执行

这只是兼容性检查，不是 binary 真实性或安全性验证。

操作者必须自行根据 OpenAI 官方 Release 和 SHA256SUMS 验证指定 binary。

---

# 21. 其它 Launcher 选项

## -CreateWorkspace

当你明确希望 Launcher 创建指定 workspace 时使用。

只有在确定路径正确时才使用。

## -DryRun

仅显示将执行的操作和命令。

`-DryRun` 不下载 tunnel-client、不探测 tunnel-client，也不真正启动 Tunnel。

适合检查启动计划或排查参数。

---

# 22. 安全说明

Safe Workspace MCP 是一个**能力受限的 MCP server**，不是操作系统级 sandbox。

模型可见的 MCP 能力有意排除了：

```text
任意命令执行
Shell
终端
模型可调用网络
```

Launcher 属于操作者控制的部署层，与 MCP 模型能力是不同的信任边界。

Launcher 可以：

- 下载固定的 OpenAI tunnel-client
- 校验固定 SHA-256
- 生成本地 runtime 配置
- 启动 tunnel-client
- 启动 Safe Workspace MCP

模型不能通过 workspace 内容或 MCP tool 参数决定：

```text
tunnel-client 下载地址
tunnel-client 版本
SHA-256
默认 executable
```

不要把与当前项目无关的秘密信息放进模型可读取的 workspace。

---

# 23. v0.1.1 的设计限制

v0.1.1 有意限制为：

- 一个进程 = 一个固定 workspace
- 不接管外部已有 `.git` 仓库；Safe Workspace MCP 自己创建的 managed `.git` 可在后续启动时重新打开
- `.git` 不可通过 MCP 文件工具访问
- 无 Shell
- 无终端
- 无模型触发的任意命令执行
- 无模型可调用的本地网络/Web Fetch
- 无 Git remote
- 无 clone / fetch / pull / push
- 无运行时动态切换 workspace

这些限制属于 v0.1.1 的安全设计，不是缺失的安装步骤。

---

# 24. ChatGPT Desktop

新版 ChatGPT Desktop 可能另外提供 Codex 的本地 STDIO MCP 配置。

该配置与本文档的：

```text
ChatGPT
→ Secure MCP Tunnel
→ Safe Workspace MCP
```

路径不是同一件事。

普通 ChatGPT 对话使用 Safe Workspace MCP 时，应通过 ChatGPT 自定义 MCP App 和 Tunnel ID。

如果当前桌面版没有显示与 ChatGPT Web 相同的自定义 Tunnel App 创建/调用入口，请优先使用 ChatGPT Web。

不要手工修改 ChatGPT 或 Codex 配置文件来绕过 UI。

---

# 25. 常见问题

## Tunnel 正常运行，但 ChatGPT 看不到 Tunnel

检查：

- Tunnel ID 是否正确
- Tunnel 是否关联了当前 ChatGPT workspace
- Runtime/API principal 是否具有 `Tunnels: Read + Use`
- tunnel-client 是否显示 `Ready: ready`
- tunnel-client 是否仍在运行

## tunnel-client 返回 401 / 403

检查 Runtime API Key 对应 principal 是否具有：

```text
Tunnels: Read
Tunnels: Use
```

并确认 key 与 Tunnel 属于正确的 Organization/workspace scope。

## workspace 被拒绝（EXISTING_GIT_REPOSITORY_NOT_SUPPORTED）

Safe Workspace MCP 会自动重新打开自己之前创建的 managed `.git`。它只拒绝**外部**仓库——普通的 `git init`、clone 或没有 `safe-workspace-mcp.managed-repository-format` 标记的仓库。

如果该目录之前被 Safe Workspace MCP 使用过，不应被拒绝；若仍被拒绝，可能是标记被移除或仓库被篡改。否则请使用：

- 空目录
- 或去除原 `.git` 的项目副本

不要尝试让 Safe Workspace MCP 接管重要的已有 Git repository。

## ChatGPT 阻止写入

ChatGPT 自身仍可能根据：

- 账号
- workspace
- 产品 rollout
- 安全检查
- 用户确认策略

限制 MCP write/modify。

不要为了绕过 ChatGPT 产品层限制而削弱 Safe Workspace MCP 的安全设计。

## tunnel-client 已经存在

第二次以后 Launcher 正常会复用已经校验的缓存。

这是预期行为。

---

# 26. OpenAI 官方入口

Tunnel 管理：

```text
https://platform.openai.com/settings/organization/tunnels
```

Runtime API Keys：

```text
https://platform.openai.com/settings/organization/api-keys
```

ChatGPT Connector 设置：

```text
https://chatgpt.com/#settings/Connectors
```

OpenAI tunnel-client：

```text
https://github.com/openai/tunnel-client
```

---

# 27. 完整普通用户流程

```text
从 GitHub Release 下载 Windows ZIP
        |
        v
完整解压 ZIP
        |
        v
准备一个没有外部 .git 的 workspace（MCP 自己创建的可复用）
        |
        v
创建或复用 OpenAI Secure MCP Tunnel
        |
        v
创建 Restricted Runtime API Key
Tunnels Read + Use
        |
        v
运行 Start-SafeWorkspaceMCP.ps1
        |
        v
输入 workspace + tunnel ID + runtime key
        |
        v
等待
Health: live
Ready: ready
Logs: connected
        |
        v
在 ChatGPT Web 创建自定义 MCP
Connection = Tunnel / Tunnel ID
        |
        v
选择或 @Safe Workspace MCP
        |
        v
使用受控本地文件操作 + Git checkpoint/rollback
        |
        v
结束后 Ctrl+C
```

Windows 便携版普通用户不需要安装 Python、Git、Node.js、npm 或手工安装 tunnel-client。
