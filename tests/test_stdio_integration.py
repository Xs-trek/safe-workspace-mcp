"""Integration test: real server process over stdio.

Spawns `python -m safe_workspace_mcp <config>` as a subprocess (test-only
usage of subprocess; production code never spawns anything) and drives it
with the official MCP stdio client.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

if sys.platform == "win32":
    # anyio's stdio subprocess transport requires the selector loop on Windows
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]

pytestmark = pytest.mark.anyio


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"


def _spawn(workspace: Path, tmp: Path) -> list[str]:
    cfg = tmp / "config.toml"
    cfg.write_text(
        f'[workspace]\nroot = "{workspace.as_posix()}"\n\n[server]\ntransport = "stdio"\n',
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_ROOT)
    return [
        sys.executable,
        "-m",
        "safe_workspace_mcp",
        str(cfg),
    ]


async def test_stdio_roundtrip(tmp_path: Path) -> None:
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters, stdio_client

    workspace = tmp_path / "ws"
    workspace.mkdir()
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "safe_workspace_mcp", str(tmp_path / "config.toml")],
        env={"PYTHONPATH": str(SRC_ROOT), **os.environ},
    )
    (tmp_path / "config.toml").write_text(
        f'[workspace]\nroot = "{workspace.as_posix()}"\n', encoding="utf-8"
    )
    async with Client(stdio_client(params)) as client:
            tools = await client.list_tools()
            names = {t.name for t in tools.tools}
            assert names == {
                "workspace_info", "list_directory", "read_file", "search_text",
                "apply_changes", "git_status", "git_diff", "git_history",
                "git_restore",
            }

            r = await client.call_tool(
                "apply_changes",
                {"operations": [
                    {"op": "create_file", "path": "hello.py",
                     "content": "print('hi')\n"},
                ]},
            )
            assert not r.is_error, r.content[0].text

            r = await client.call_tool("read_file", {"path": "hello.py"})
            rf = json.loads(r.content[0].text)
            assert rf["content"] == "print('hi')\n"

            r = await client.call_tool("search_text", {"query": "hi"})
            hits = json.loads(r.content[0].text)["hits"]
            assert hits[0]["path"] == "hello.py"

            r = await client.call_tool("git_history", {"limit": 10})
            ck = json.loads(r.content[0].text)["checkpoints"]
            assert any("initial" in c["message"] for c in ck)

            # server process must actually have created the managed repo
            assert (workspace / ".git").is_dir()
            # ... while refusing access to it via tools:
            r = await client.call_tool("read_file", {"path": ".git/config"})
            assert r.is_error
