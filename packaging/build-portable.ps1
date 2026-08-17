<#
Build the Safe Workspace MCP portable Windows release ZIP.
Usage (from repo root):  powershell -File packaging\build-portable.ps1 [-Version 0.1.0]
Creates: dist\safe-workspace-mcp-<version>-windows-x64.zip and dist\SHA256SUMS.txt
#>

[CmdletBinding()]
param(
    [string]$Version = '0.1.0',
    [string]$BuildVenv = (Join-Path -Path $env:TEMP -ChildPath 'opencode\build-venv')
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$repo = Split-Path -Parent $PSScriptRoot
$stage = Join-Path -Path (Join-Path -Path $repo -ChildPath 'dist') -ChildPath "safe-workspace-mcp-$Version-windows-x64"

if (-not (Test-Path -LiteralPath (Join-Path -Path $BuildVenv -ChildPath 'Scripts\python.exe'))) {
    throw "Build venv not found: $BuildVenv. Create it first (see release.yml)."
}

$py = Join-Path -Path $BuildVenv -ChildPath 'Scripts\python.exe'

# Verify exact dependency pins in the build venv before bundling.
& $py -c "from importlib.metadata import version; assert version('mcp') == '2.0.0'; assert version('dulwich') == '1.2.6'" 2>$null
if ($LASTEXITCODE -ne 0) { throw "dependency pin check failed (need mcp==2.0.0, dulwich==1.2.6)" }

& $py -m PyInstaller --clean --noconfirm `
    --distpath (Join-Path -Path $repo -ChildPath 'dist\_pyi_dist') `
    --workpath (Join-Path -Path $repo -ChildPath 'dist\_pyi_build') `
    (Join-Path -Path $PSScriptRoot -ChildPath 'safe-workspace-mcp.spec')
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }

if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
New-Item -ItemType Directory -Path $stage | Out-Null

Copy-Item (Join-Path -Path $repo -ChildPath 'dist\_pyi_dist\safe-workspace-mcp') -Destination (Join-Path -Path $stage -ChildPath 'safe-workspace-mcp') -Recurse
Copy-Item (Join-Path -Path $repo -ChildPath 'Start-SafeWorkspaceMCP.ps1') -Destination $stage
Copy-Item (Join-Path -Path $repo -ChildPath 'LICENSE') -Destination $stage
Copy-Item (Join-Path -Path $repo -ChildPath 'THIRD_PARTY_NOTICES.md') -Destination $stage
Copy-Item (Join-Path -Path $repo -ChildPath 'README-PORTABLE.md') -Destination $stage
Copy-Item (Join-Path -Path $repo -ChildPath 'README-PORTABLE.zh-CN.md') -Destination $stage

$zip = Join-Path -Path $repo -ChildPath "dist\safe-workspace-mcp-$Version-windows-x64.zip"
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
Compress-Archive -Path "$stage\*" -DestinationPath $zip

$hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash  safe-workspace-mcp-$Version-windows-x64.zip" | Set-Content (Join-Path -Path $repo -ChildPath 'dist\SHA256SUMS.txt') -Encoding ascii

Write-Output "Artifact : $zip"
Write-Output "SHA256   : $hash"
