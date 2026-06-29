"""Tests for the conduit usage guide tool + tackle prompt (conduit/guide.py).

These exercise the guide content and registration directly; they construct a fresh
FastMCP and never touch Phorge, so they need no live server or credentials.
"""

import asyncio

from fastmcp import FastMCP

from conduit.guide import GUIDE, register_guide, tackle_prompt


def test_guide_has_key_sections():
    for marker in (
        "Tool catalogue",
        "Read vs write",
        "Task ids",
        "Search and pagination",
        "tackle a task",
        "pha_task_get",
        "pha_file_download",
        "{F",
    ):
        assert marker in GUIDE, f"missing section marker: {marker!r}"


def test_tackle_prompt_specializes_task_id():
    out = tackle_prompt("7229")
    assert "7229" in out
    for tool in ("pha_task_get", "pha_task_get_transactions",
                 "pha_task_relationships", "pha_file_download"):
        assert tool in out, f"tackle prompt missing {tool}"


def test_register_guide_adds_tool_and_prompt():
    mcp = FastMCP("test")
    register_guide(mcp)
    tool_names = [t.name for t in asyncio.run(mcp.list_tools())]
    assert "conduit_guide" in tool_names
    prompt_names = [p.name for p in asyncio.run(mcp.list_prompts())]
    assert "tackle" in prompt_names


def test_conduit_guide_tool_returns_guide():
    mcp = FastMCP("test")
    register_guide(mcp)
    tool = asyncio.run(mcp.get_tool("conduit_guide"))
    assert tool.fn() == GUIDE
    assert tool.annotations.readOnlyHint is True
