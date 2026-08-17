# PyInstaller onedir spec for the Safe Workspace MCP portable Windows release.
# Built from a clean checkout; dependency pins (mcp==2.0.0, dulwich==1.2.6) are
# installed into the build venv before running pyinstaller so the bundled
# runtime matches the audited versions exactly.

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# NOTE: deliberately NOT collect_submodules("mcp"): importing mcp.cli at build
# time executes its CLI guard (sys.exit). Static analysis + dependency walking
# covers everything the server actually imports at runtime.
# safe_workspace_mcp must be pip-installed (non-editable) into the build venv;
# this spec is invoked from packaging/ with the repo root one level up.
import os
import sys

_repo_src = os.path.abspath(os.path.join(os.path.dirname(SPEC), "..", "src"))
sys.path.insert(0, _repo_src)

hiddenimports = collect_submodules("safe_workspace_mcp")

a = Analysis(
    ["entry.py"],
    pathex=[_repo_src],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="safe-workspace-mcp",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="safe-workspace-mcp",
)
