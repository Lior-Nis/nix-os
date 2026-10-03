#!/usr/bin/env python3
"""Validate the Chief's exact resolved Hermes capability boundary."""

from __future__ import annotations

import argparse
import json
import sys


EXPECTED_TOOLSETS = {"file", "skills", "memory", "session_search", "paperclip"}
EXPECTED_NATIVE_TOOLS = {
    "memory",
    "patch",
    "read_file",
    "search_files",
    "session_search",
    "skill_manage",
    "skill_view",
    "skills_list",
    "write_file",
}
APPROVED_PAPERCLIP_TOOLS = {
    "paperclipMe",
    "paperclipListIssues",
    "paperclipGetIssue",
    "paperclipListComments",
    "paperclipListProjects",
    "paperclipGetProject",
    "paperclipCreateIssue",
    "paperclipUpdateIssue",
    "paperclipAddComment",
}
FORBIDDEN_EXACT = {
    "terminal",
    "process_manage",
    "execute_code",
    "computer_use",
    "web_search",
    "web_extract",
    "manage_connections",
    "delegate_task",
    "cronjob_manage",
    "setup_mcp",
    "read_terminal",
}
FORBIDDEN_PREFIXES = ("browser_", "desktop_", "mcp__paperclip__paperclipCreateProject", "mcp__paperclip__paperclipCreateGoal")
TOOL_SEARCH_BRIDGE = {"tool_search", "tool_describe", "tool_call"}


def fail(message: str) -> None:
    raise SystemExit(f"Chief tool-boundary error: {message}")


def assert_concrete(tools: set[str], expected: set[str], lane: str) -> None:
    forbidden = sorted(
        tool
        for tool in tools
        if tool in FORBIDDEN_EXACT or any(tool.startswith(prefix) for prefix in FORBIDDEN_PREFIXES)
    )
    if forbidden:
        fail(f"{lane} exposes forbidden concrete tools: {', '.join(forbidden)}")
    missing = sorted(expected - tools)
    unexpected = sorted(tools - expected)
    if missing or unexpected:
        fail(f"{lane} concrete tools differ from policy; missing={missing}, unexpected={unexpected}")


def runtime_check() -> None:
    from hermes_cli.config import load_config
    from hermes_cli.tools_config import _get_platform_tools
    from model_tools import get_tool_definitions
    from tools.mcp_tool_discovery import discover_mcp_tools
    from tools.mcp_tool_schema import mcp_prefixed_tool_name

    config = load_config()
    discovered = set(discover_mcp_tools(allowed_mcp_names=["paperclip"]))
    expected_mcp = {mcp_prefixed_tool_name("paperclip", name) for name in APPROVED_PAPERCLIP_TOOLS}
    if discovered != expected_mcp:
        fail(f"Paperclip MCP discovery differs from the nine-tool policy: {sorted(discovered)}")
    expected_concrete = EXPECTED_NATIVE_TOOLS | expected_mcp

    summary: dict[str, dict[str, list[str]]] = {}
    for lane in ("cli", "telegram", "api_server"):
        toolsets = set(_get_platform_tools(config, lane))
        if toolsets != EXPECTED_TOOLSETS:
            fail(f"{lane} toolsets differ from policy: {sorted(toolsets)}")
        raw_definitions = get_tool_definitions(
            enabled_toolsets=sorted(toolsets), quiet_mode=True, skip_tool_search_assembly=True
        )
        concrete = {item["function"]["name"] for item in raw_definitions}
        assert_concrete(concrete, expected_concrete, lane)
        presented_definitions = get_tool_definitions(enabled_toolsets=sorted(toolsets), quiet_mode=True)
        presented = {item["function"]["name"] for item in presented_definitions}
        forbidden_presented = {
            tool
            for tool in presented
            if tool in FORBIDDEN_EXACT or any(tool.startswith(prefix) for prefix in FORBIDDEN_PREFIXES)
        }
        if forbidden_presented or presented - expected_concrete - TOOL_SEARCH_BRIDGE:
            fail(f"{lane} model-visible tools contain an unexpected escape hatch: {sorted(presented)}")
        summary[lane] = {
            "toolsets": sorted(toolsets),
            "tools": sorted(concrete),
            "model_tools": sorted(presented),
        }
    print(json.dumps(summary, separators=(",", ":"), sort_keys=True))


def api_check() -> None:
    payload = json.load(sys.stdin)
    if payload.get("platform") != "api_server" or not isinstance(payload.get("data"), list):
        fail("API-server toolset response has an unexpected shape")
    enabled = {row.get("name") for row in payload["data"] if row.get("enabled") is True}
    # v2026.9.14 exposes configurable built-ins here; native MCP aliases are
    # validated by runtime_check after discovery because this endpoint omits them.
    expected_api_rows = EXPECTED_TOOLSETS - {"paperclip"}
    if enabled != expected_api_rows:
        fail(f"API-server enabled toolsets differ from policy: {sorted(enabled)}")
    tools: set[str] = set()
    for row in payload["data"]:
        if row.get("enabled") is True:
            tools.update(str(name) for name in row.get("tools", []))
    assert_concrete(tools, EXPECTED_NATIVE_TOOLS, "api_server endpoint")
    print("Hermes API-server tool boundary verified.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("runtime", "api"))
    args = parser.parse_args()
    runtime_check() if args.mode == "runtime" else api_check()


if __name__ == "__main__":
    main()
