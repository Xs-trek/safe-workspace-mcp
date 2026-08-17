"""MCP protocol-level tests via in-memory Client (SDK v2 pattern)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from safe_workspace_mcp.config import Config
from safe_workspace_mcp.server import build_server

pytestmark = pytest.mark.anyio


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


async def test_tools_list_exact_nine(tmp_path: Path) -> None:
    from mcp import Client

    server = build_server(Config(root=_mk_ws(tmp_path)))
    async with Client(server) as client:
        tools = await client.list_tools()
        names = {t.name for t in tools.tools}
        assert names == {
            "workspace_info",
            "list_directory",
            "read_file",
            "search_text",
            "apply_changes",
            "git_status",
            "git_diff",
            "git_history",
            "git_restore",
        }


async def test_read_only_annotations(tmp_path: Path) -> None:
    from mcp import Client

    server = build_server(Config(root=_mk_ws(tmp_path)))
    async with Client(server) as client:
        tools = await client.list_tools()
        by_name = {t.name: t.annotations for t in tools.tools}
        for name in (
            "workspace_info",
            "list_directory",
            "read_file",
            "search_text",
            "git_status",
            "git_diff",
            "git_history",
        ):
            assert by_name[name] is not None
            assert by_name[name].read_only_hint is True, name
        for name in ("apply_changes", "git_restore"):
            assert by_name[name].read_only_hint is False, name


async def test_full_workflow(tmp_path: Path) -> None:
    from mcp import Client

    server = build_server(Config(root=_mk_ws(tmp_path)))
    async with Client(server) as client:
        r = await client.call_tool(
            "apply_changes",
            {
                "operations": [
                    {"op": "create_file", "path": "src/main.c",
                     "content": "int main(){return 0;}\n"},
                    {"op": "create_file", "path": "README.md", "content": "# t\n"},
                ]
            },
        )
        assert not r.is_error, r.content[0].text
        out = json.loads(r.content[0].text)
        assert len(out["applied"]) == 2
        assert out["checkpoint"]

        r = await client.call_tool("read_file", {"path": "src/main.c"})
        assert not r.is_error, r.content[0].text
        rf = json.loads(r.content[0].text)
        assert rf["sha256"]

        r = await client.call_tool(
            "apply_changes",
            {
                "operations": [
                    {
                        "op": "replace_file",
                        "path": "src/main.c",
                        "expected_sha256": "0" * 64,
                        "content": "x",
                    }
                ]
            },
        )
        assert r.is_error
        assert "HASH_MISMATCH" in r.content[0].text

        r = await client.call_tool(
            "apply_changes",
            {
                "operations": [
                    {
                        "op": "replace_text",
                        "path": "src/main.c",
                        "expected_sha256": rf["sha256"],
                        "old_text": "return 0;",
                        "new_text": "return 1;",
                    }
                ]
            },
        )
        assert not r.is_error, r.content[0].text

        r = await client.call_tool("search_text", {"query": "return"})
        hits = json.loads(r.content[0].text)["hits"]
        assert hits and hits[0]["path"] == "src/main.c"

        r = await client.call_tool("git_diff", {})
        assert not r.is_error, r.content[0].text
        # Working tree is clean right after a checkpoint; diff against the
        # pre-change checkpoint shows the edit.
        r = await client.call_tool("git_history", {"limit": 10})
        hist = json.loads(r.content[0].text)["checkpoints"]
        pre_change = next(c["id"] for c in hist if c["message"] == "pre-change checkpoint")
        r = await client.call_tool("git_diff", {"checkpoint": pre_change})
        assert not r.is_error, r.content[0].text
        assert "return 1" in json.loads(r.content[0].text)["diff"]

        r = await client.call_tool("git_history", {"limit": 50})
        ckpts = json.loads(r.content[0].text)["checkpoints"]
        assert any("initial" in c["message"] for c in ckpts)

        r = await client.call_tool("read_file", {"path": "../outside.txt"})
        assert r.is_error
        assert "PATH_TRAVERSAL_FORBIDDEN" in r.content[0].text

        r = await client.call_tool("read_file", {"path": "C:/Windows/system.ini"})
        assert r.is_error
        assert "ABSOLUTE_PATH_FORBIDDEN" in r.content[0].text

        r = await client.call_tool("read_file", {"path": ".git/config"})
        assert r.is_error
        assert "INTERNAL_PATH_FORBIDDEN" in r.content[0].text


async def test_error_messages_hide_external_paths(tmp_path: Path) -> None:
    from mcp import Client

    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    server = build_server(Config(root=_mk_ws(tmp_path)))
    async with Client(server) as client:
        r = await client.call_tool("read_file", {"path": "../outside.txt"})
        assert r.is_error
        text = r.content[0].text
        assert str(tmp_path) not in text


async def test_git_restore_via_mcp(tmp_path: Path) -> None:
    from mcp import Client

    server = build_server(Config(root=_mk_ws(tmp_path)))
    async with Client(server) as client:
        await client.call_tool(
            "apply_changes",
            {"operations": [{"op": "create_file", "path": "f.txt", "content": "v1\n"}]},
        )
        r = await client.call_tool("read_file", {"path": "f.txt"})
        rf = json.loads(r.content[0].text)
        await client.call_tool(
            "apply_changes",
            {
                "operations": [
                    {
                        "op": "replace_file",
                        "path": "f.txt",
                        "expected_sha256": rf["sha256"],
                        "content": "v2\n",
                    }
                ]
            },
        )
        r = await client.call_tool("git_history", {"limit": 10})
        hist = json.loads(r.content[0].text)["checkpoints"]
        v1 = hist[2]["id"]  # post-change of first apply
        r = await client.call_tool("git_restore", {"checkpoint": v1})
        assert not r.is_error, r.content[0].text
        r = await client.call_tool("read_file", {"path": "f.txt"})
        assert json.loads(r.content[0].text)["content"] == "v1\n"
        # undo
        r = await client.call_tool("git_history", {"limit": 2})
        pre_restore = json.loads(r.content[0].text)["checkpoints"][1]["id"]
        r = await client.call_tool("git_restore", {"checkpoint": pre_restore})
        assert not r.is_error, r.content[0].text
        r = await client.call_tool("read_file", {"path": "f.txt"})
        assert json.loads(r.content[0].text)["content"] == "v2\n"


def _mk_ws(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir(exist_ok=False)
    return root
