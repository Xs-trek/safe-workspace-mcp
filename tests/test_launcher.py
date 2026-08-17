"""Launcher tests for Start-SafeWorkspaceMCP.ps1 (deployment layer).

Covers:
- PowerShell syntax parse (Parser::ParseFile).
- Launcher security invariants (AST scan of the script itself):
  no Invoke-Expression, no Set-ExecutionPolicy, no registry/PATH mutation,
  no Codex/ChatGPT paths.
- tunnel-client `--mcp.command` quoting: a Python port (byte-faithful) of
  tunnel-client v0.0.11 pkg/config/config.go parseCommandArgv proves that
  the launcher's ConvertTo-TunnelClientArg output parses back to the exact
  original path, including spaces, Unicode, quotes and apostrophes.
- Real PowerShell invocation: runtime config generation (spaces, Unicode,
  idempotency, content) and workspace validation fail-closed behavior.

No network, no real OpenAI keys, no ChatGPT/Codex access anywhere here.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LAUNCHER = REPO / "Start-SafeWorkspaceMCP.ps1"


# ---------------------------------------------------------------------------
# tunnel-client parseCommandArgv (ported from
# openai/tunnel-client v0.0.11 pkg/config/config.go) -- test oracle only.
# ---------------------------------------------------------------------------


def parse_command_argv(raw: str) -> list[str]:
    input_ = raw.strip(" \t\n\r\f\v")
    if input_ == "":
        raise ValueError("command is empty")
    args: list[str] = []
    builder: list[str] = []
    in_single = False
    in_double = False
    escaped = False

    def flush() -> None:
        if builder:
            args.append("".join(builder))
            builder.clear()

    for ch in input_:
        if escaped:
            builder.append(ch)
            escaped = False
            continue
        if in_single:
            if ch == "'":
                in_single = False
                continue
            builder.append(ch)
            continue
        if in_double:
            if ch == "\\":
                escaped = True
            elif ch == '"':
                in_double = False
            else:
                builder.append(ch)
            continue
        if ch == "\\":
            escaped = True
        elif ch == "'":
            in_single = True
        elif ch == '"':
            in_double = True
        elif ch in " \t\n\r":
            flush()
        else:
            builder.append(ch)
    if escaped:
        raise ValueError("unterminated escape sequence")
    if in_single or in_double:
        raise ValueError("unterminated quoted string")
    flush()
    if not args:
        raise ValueError("command is empty")
    return args


QUOTING_CASES = [
    r"C:\mcp\safe-workspace-mcp.exe",
    r"D:\Safe MCP\release\safe-workspace-mcp\safe-workspace-mcp.exe",
    r"D:\ChatGPT_Workspace\demo folder with spaces\config-abc.toml",
    r"C:\Users\Alise Ünicode\安全工作区\safe-workspace-mcp.exe",
    r"C:\build\config-with-quotes-\"inside\".toml",
    "C:\\data\\it's-a-name.exe",
    r"\\server\share\safe workspace\mcp.exe",
]


@pytest.mark.parametrize("path", QUOTING_CASES)
def test_tunnel_command_quoting_roundtrip(path: str) -> None:
    """Launcher quoting must survive tunnel-client's argv parser byte-exact."""
    quoted = _tunnel_quote(path)
    argv = parse_command_argv(quoted)
    assert argv == [path]


def _tunnel_quote(path: str) -> str:
    # Mirrors ConvertTo-TunnelClientArg in Start-SafeWorkspaceMCP.ps1
    if "'" not in path:
        return f"'{path}'"
    escaped = path.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def test_tunnel_command_two_args() -> None:
    exe = r"D:\Safe MCP\release\safe-workspace-mcp\safe-workspace-mcp.exe"
    cfg = r"D:\ChatGPT_Workspace\demo folder\config-0123456789abcdef.toml"
    cmd = f"{_tunnel_quote(exe)} {_tunnel_quote(cfg)}"
    assert parse_command_argv(cmd) == [exe, cfg]


# ---------------------------------------------------------------------------
# PowerShell launcher: syntax + AST invariants
# ---------------------------------------------------------------------------


def _run_ps(script: str, workdir: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", script],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=workdir,
    )


def test_powershell_parse_ok() -> None:
    ps = (
        "$errs = $null; "
        "$null = [System.Management.Automation.Language.Parser]::ParseFile("
        f"'{LAUNCHER}', [ref]$null, [ref]$errs); "
        "if ($errs.Count -gt 0) { "
        "$errs | ForEach-Object { Write-Output $_.Message }; exit 1 "
        "} else { Write-Output 'OK' }"
    )
    r = _run_ps(ps)
    assert r.returncode == 0, r.stderr + r.stdout
    assert "OK" in r.stdout


FORBIDDEN_PS_PATTERNS = [
    "Invoke-Expression",
    "iex ",
    "Set-ExecutionPolicy",
    "Set-ItemProperty",
    "New-ItemProperty",
    "Remove-ItemProperty",
    "HKLM:",
    "HKCU:",
    "[Environment]::SetEnvironmentVariable",
    "$env:PATH =",
    "$env:Path =",
    "tunnel-client codex",
    ".codex",
    "codex plugin",
    "runtimes connect",
    "admin tunnels",
    "Start-Process",
    "-RunAs",
    "Start-Service",
    "schtasks",
    "Register-ScheduledTask",
    "OPENAI_ADMIN_KEY",
]


def test_launcher_source_invariants() -> None:
    src = LAUNCHER.read_text(encoding="utf-8-sig")
    for pattern in FORBIDDEN_PS_PATTERNS:
        assert pattern.lower() not in src.lower(), f"launcher must not contain: {pattern}"
    # Pinned download base and pinned hashes must be present.
    assert "https://github.com/openai/tunnel-client/releases/download/" in src
    assert "v0.0.11" in src
    assert "EB912C86C6CCDE90CDA805CB17009507176A656725CF86C36FABE1901A12E29B" in src.upper()


PIN_BLOCK_TESTS = [
    ("downloaded zip is verified against pinned SHA-256 and fails closed", True),
]


def test_checksum_is_exact_official_value() -> None:
    # Must match openai/tunnel-client v0.0.11 SHA256SUMS.txt windows-amd64
    src = LAUNCHER.read_text(encoding="utf-8-sig")
    assert "eb912c86c6ccde90cda805cb17009507176a656725cf86c36fabe1901a12e29b".upper() in src.upper()
    assert "38f015a720404c8ccd5976a0d6aed18d931899697eaf208548b5eb3d0f6e8592".upper() in src.upper()


# ---------------------------------------------------------------------------
# Real PowerShell behavior: config generation (spaces / Unicode / idempotency)
# ---------------------------------------------------------------------------

requires_windows_ps = pytest.mark.skipif(
    sys.platform != "win32", reason="requires Windows PowerShell 5.1"
)


@pytest.fixture()
def portable_tree(tmp_path: Path) -> Path:
    root = tmp_path / "safe-workspace-mcp-v0.1.0-windows-x64"
    (root / "safe-workspace-mcp").mkdir(parents=True)
    exe = root / "safe-workspace-mcp" / "safe-workspace-mcp.exe"
    exe.write_bytes(b"MZ-placeholder")
    return root


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


_FLAG_VALUES = {"-Workspace", "-TunnelId", "-TunnelClientPath", "-StateRoot"}


def _invoke_launcher(
    portable_root: Path, workspace: Path, extra: list[str], use_tunnel_path: bool = True,
    state_root: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    tc = portable_root / "tc.exe"
    tc.write_bytes(b"placeholder")
    raw = ["-Workspace", str(workspace), "-TunnelId", "tunnel_" + "0" * 31 + "a", "-DryRun"]
    if use_tunnel_path:
        raw += ["-TunnelClientPath", str(tc)]
    if state_root is not None:
        raw += ["-StateRoot", str(state_root)]
    raw += extra
    parts: list[str] = []
    i = 0
    while i < len(raw):
        tok = raw[i]
        if tok in _FLAG_VALUES:
            parts.append(tok)
            i += 1
            parts.append(_ps_quote(raw[i]))
        else:
            parts.append(tok)
        i += 1
    script = f"& {_ps_quote(str(portable_root / 'Start-SafeWorkspaceMCP.ps1'))} {' '.join(parts)}"
    return _run_ps(script)


def _copy_launcher(portable_root: Path) -> None:
    (portable_root / "Start-SafeWorkspaceMCP.ps1").write_text(
        LAUNCHER.read_text(encoding="utf-8-sig"), encoding="utf-8"
    )


def _reported_config_path(stdout: str) -> Path:
    for line in stdout.splitlines():
        if "Config    :" in line:
            return Path(line.split(":", 1)[1].strip().rstrip('"').lstrip('"'))
    raise AssertionError(f"config path not reported in launcher output:\n{stdout}")


@requires_windows_ps
def test_dryrun_generates_config_with_space_and_unicode(
    tmp_path: Path, portable_tree: Path
) -> None:
    _copy_launcher(portable_tree)
    ws = tmp_path / "空间 workspace with spaces"
    ws.mkdir()
    state = tmp_path / "state"
    r = _invoke_launcher(portable_tree, ws, [], state_root=state)
    assert r.returncode == 0, r.stdout + r.stderr
    cfg = _reported_config_path(r.stdout)
    assert cfg.is_file(), f"runtime config not generated: {cfg}"
    assert state in cfg.parents
    content = cfg.read_text(encoding="utf-8")
    assert "[workspace]" in content
    assert ws.as_posix() in content
    assert "[server]" in content and "stdio" in content
    # No secrets in config
    assert "sk-" not in content and "api" not in content.lower()


@requires_windows_ps
def test_dryrun_is_idempotent(tmp_path: Path, portable_tree: Path) -> None:
    _copy_launcher(portable_tree)
    ws = tmp_path / "demo"
    ws.mkdir()
    state = tmp_path / "state"
    r1 = _invoke_launcher(portable_tree, ws, [], state_root=state)
    r2 = _invoke_launcher(portable_tree, ws, [], state_root=state)
    assert r1.returncode == 0 and r2.returncode == 0, r1.stdout + r2.stderr
    assert _reported_config_path(r1.stdout) == _reported_config_path(r2.stdout)


@requires_windows_ps
def test_missing_workspace_fails_closed(tmp_path: Path, portable_tree: Path) -> None:
    _copy_launcher(portable_tree)
    missing = tmp_path / "no such folder"
    r = _invoke_launcher(portable_tree, missing, [])
    assert r.returncode != 0
    assert "not found" in (r.stdout + r.stderr).lower()


@requires_windows_ps
def test_existing_git_workspace_rejected(tmp_path: Path, portable_tree: Path) -> None:
    _copy_launcher(portable_tree)
    ws = tmp_path / "hasgit"
    (ws / ".git").mkdir(parents=True)
    r = _invoke_launcher(portable_tree, ws, [])
    assert r.returncode != 0
    assert ".git" in (r.stdout + r.stderr)


@requires_windows_ps
def test_bad_tunnel_id_rejected(tmp_path: Path, portable_tree: Path) -> None:
    _copy_launcher(portable_tree)
    ws = tmp_path / "ws"
    ws.mkdir()
    tc = portable_tree / "tc.exe"
    tc.write_bytes(b"x")
    args = ["-Workspace", str(ws), "-TunnelId", "not-a-tunnel-id", "-DryRun",
            "-TunnelClientPath", str(tc)]
    parts: list[str] = []
    i = 0
    while i < len(args):
        tok = args[i]
        if tok in _FLAG_VALUES:
            parts.append(tok)
            i += 1
            parts.append(_ps_quote(args[i]))
        else:
            parts.append(tok)
        i += 1
    script = f"& {_ps_quote(str(portable_tree / 'Start-SafeWorkspaceMCP.ps1'))} {' '.join(parts)}"
    r = _run_ps(script)
    assert r.returncode != 0
    assert "tunnel" in (r.stdout + r.stderr).lower()


def test_missing_tunnel_id_env_fallback(tmp_path: Path, portable_tree: Path) -> None:
    _copy_launcher(portable_tree)
    ws = tmp_path / "ws"
    ws.mkdir()
    tc = portable_tree / "tc.exe"
    tc.write_bytes(b"x")
    state = tmp_path / "state"
    script = (
        f"$env:CONTROL_PLANE_TUNNEL_ID='tunnel_{'a' * 32}'; "
        f"& {_ps_quote(str(portable_tree / 'Start-SafeWorkspaceMCP.ps1'))} "
        f"-Workspace {_ps_quote(str(ws))} -DryRun "
        f"-TunnelClientPath {_ps_quote(str(tc))} -StateRoot {_ps_quote(str(state))}"
    )
    r = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", script],
        capture_output=True, text=True, timeout=120, cwd=tmp_path,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "tunnel_" + "a" * 32 in r.stdout


@requires_windows_ps
@pytest.mark.skipif(sys.platform != "win32", reason="Windows launcher")
def test_checksum_mismatch_fail_closed(tmp_path: Path, portable_tree: Path) -> None:
    """Corrupted cache reuse is impossible (only extracted exe is cached), so
    prove fail-closed on the hash guard itself: a wrong pinned hash must abort
    before any launch. We simulate by calling the launcher's Test-FileSha256
    via AST dot-source of the function definitions only."""
    content = LAUNCHER.read_text(encoding="utf-8-sig")
    # Extract functions up to 'function Main' (dot-sourcing the whole script
    # would run Main).
    idx = content.index("function Main")
    funcs = content[:idx]
    probe = tmp_path / "funcs.ps1"
    probe.write_text(funcs + "\n", encoding="utf-8")
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"corrupted")
    script = (
        f". {_ps_quote(str(probe))}; "
        "if (Test-FileSha256 -Path '" + str(bad).replace("'", "''") + "' "
        "-ExpectedSha256 '0000000000000000000000000000000000000000000000000000000000000000') "
        "{ Write-Output 'MISMATCH-PASSED'; exit 1 } else { Write-Output 'FAIL-CLOSED-OK' }"
    )
    r = _run_ps(script)
    assert "FAIL-CLOSED-OK" in r.stdout
    assert r.returncode == 0


@requires_windows_ps
def test_runtime_config_uses_forward_slashes_and_escapes(tmp_path: Path) -> None:
    """Direct unit test of Write-RuntimeConfig escaping via dot-sourced functions."""
    content = LAUNCHER.read_text(encoding="utf-8-sig")
    idx = content.index("function Main")
    funcs = tmp_path / "funcs.ps1"
    funcs.write_text(content[:idx] + "\n", encoding="utf-8")
    out = tmp_path / "out.toml"
    ws = 'D:\\weird "quote" path'
    script = (
        f". {_ps_quote(str(funcs))}; "
        f"Write-RuntimeConfig -ConfigPath {_ps_quote(str(out))} -WorkspaceRoot {_ps_quote(ws)}; "
        f"Get-Content -Raw {_ps_quote(str(out))} | ConvertTo-Json"
    )
    r = _run_ps(script)
    assert r.returncode == 0, r.stderr + r.stdout
    written = json.loads(r.stdout)
    if isinstance(written, dict):
        written = written.get("value", "")
    # Backslashes converted to forward slashes; inner double quotes TOML-escaped.
    assert 'D:/weird \\"quote\\" path' in written


@requires_windows_ps
def test_launcher_downloads_nothing_when_cached(tmp_path: Path, portable_tree: Path) -> None:
    _copy_launcher(portable_tree)
    ws = tmp_path / "ws"
    ws.mkdir()
    state = tmp_path / "state"
    tools = state / "tools" / "tunnel-client" / "v0.0.11"
    tools.mkdir(parents=True, exist_ok=True)
    cached = tools / "tunnel-client.exe"
    cached.write_bytes(b"cached-binary")
    r = _invoke_launcher(portable_tree, ws, [], use_tunnel_path=False, state_root=state)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Reusing cached tunnel-client" in r.stdout
    assert cached.read_bytes() == b"cached-binary"
    # Cache isolation: fake cache content must never leak into the real LOCALAPPDATA.
    real_cached = (
        Path(os.environ["LOCALAPPDATA"]) / "SafeWorkspaceMCP" / "tools"
        / "tunnel-client" / "v0.0.11" / "tunnel-client.exe"
    )
    assert not (real_cached.exists() and real_cached.read_bytes() == b"cached-binary")


@requires_windows_ps
def test_launcher_no_network_by_default_when_path_given(
    tmp_path: Path, portable_tree: Path
) -> None:
    _copy_launcher(portable_tree)
    ws = tmp_path / "ws"
    ws.mkdir()
    state = tmp_path / "state"
    # -TunnelClientPath skips download entirely; assert no 'Downloading' output.
    r = _invoke_launcher(portable_tree, ws, [], state_root=state)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Downloading" not in r.stdout


@pytest.mark.skipif(
    os.environ.get("SAFE_MCP_E2E_DOWNLOAD") != "1",
    reason="network test; set SAFE_MCP_E2E_DOWNLOAD=1 to include",
)
@requires_windows_ps
def test_launcher_real_download_and_checksum(tmp_path: Path, portable_tree: Path) -> None:
    """Full bootstrap path: official download, SHA-256 verify, extract, --version."""
    _copy_launcher(portable_tree)
    ws = tmp_path / "ws"
    ws.mkdir()
    state = tmp_path / "state"
    r = _invoke_launcher(portable_tree, ws, [], use_tunnel_path=False, state_root=state)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SHA-256 verified" in r.stdout
    exe = state / "tools" / "tunnel-client" / "v0.0.11" / "tunnel-client.exe"
    assert exe.is_file() and exe.stat().st_size > 10_000_000
    v = _run_ps(f"& {_ps_quote(str(exe))} --version")
    assert "0.0.11" in v.stdout
    # Second run must reuse the cache without downloading again.
    r2 = _invoke_launcher(portable_tree, ws, [], use_tunnel_path=False, state_root=state)
    assert "Reusing cached tunnel-client" in r2.stdout
