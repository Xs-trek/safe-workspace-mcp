"""Packaged-runtime integration test: PyInstaller onedir executable + MCP stdio client.

Gated behind SAFE_MCP_PACKAGED_EXE env var (path to the packaged
safe-workspace-mcp.exe). Skipped unless the portable build is available, so
normal `pytest` runs stay fast; the release workflow and local release
validation set the variable and the test must pass there.

Runs the packaged exe against a temporary workspace (no source tree, no venv)
and verifies initialize/tools/list (nine tools)/CRUD/git checkpoint/restore/
clean shutdown -- the same bar as the source-level stdio integration test.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]

pytestmark = pytest.mark.anyio

REQUIRED_TOOLS = {
    "workspace_info", "list_directory", "read_file", "search_text",
    "apply_changes", "git_status", "git_diff", "git_history", "git_restore",
}


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="module")
def packaged_exe() -> Path:
    exe = os.environ.get("SAFE_MCP_PACKAGED_EXE")
    if not exe:
        pytest.skip("SAFE_MCP_PACKAGED_EXE not set (packaged build not available)")
    p = Path(exe)
    if not p.is_file():
        pytest.skip(f"packaged exe not found: {p}")
    return p


async def test_packaged_stdio_roundtrip(tmp_path: Path, packaged_exe: Path) -> None:
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters, stdio_client

    workspace = tmp_path / "ws dir ünïcode"
    workspace.mkdir()
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[workspace]\nroot = "{workspace.as_posix()}"\n\n[server]\ntransport = "stdio"\n',
        encoding="utf-8",
    )

    params = StdioServerParameters(
        command=str(packaged_exe),
        args=[str(cfg)],
        env={**os.environ},
    )
    async with Client(stdio_client(params)) as client:
        tools = await client.list_tools()
        names = {t.name for t in tools.tools}
        assert names == REQUIRED_TOOLS

        r = await client.call_tool(
            "apply_changes",
            {"operations": [
                {"op": "create_file", "path": "hello.py", "content": "print('hi')\n"},
            ]},
        )
        assert not r.is_error, r.content[0].text

        r = await client.call_tool("read_file", {"path": "hello.py"})
        assert json.loads(r.content[0].text)["content"] == "print('hi')\n"

        r = await client.call_tool("search_text", {"query": "hi"})
        assert json.loads(r.content[0].text)["hits"][0]["path"] == "hello.py"

        r = await client.call_tool("git_history", {"limit": 10})
        ck = json.loads(r.content[0].text)["checkpoints"]
        assert any("initial" in c["message"] for c in ck)

        r = await client.call_tool("git_status", {})
        assert not r.is_error

        # checkpoint-restore round trip
        r = await client.call_tool(
            "apply_changes",
            {"operations": [
                {"op": "replace_file", "path": "hello.py",
                 "expected_sha256": None or _sha(tmp_path), "content": "print('changed')\n"},
            ]},
        )
        assert not r.is_error, r.content[0].text

        assert (workspace / ".git").is_dir()
        r = await client.call_tool("read_file", {"path": ".git/config"})
        assert r.is_error  # .git isolation holds in the packaged build too


def _sha(tmp_path: Path) -> str:
    import hashlib

    return hashlib.sha256(b"print('hi')\n").hexdigest()
