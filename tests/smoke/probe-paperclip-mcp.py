#!/usr/bin/env python3
import json
import os
import subprocess

messages = "\n".join(
    [
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "nix-contract", "version": "1"},
                },
            }
        ),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
        "",
    ]
)
env = os.environ | {
    "PAPERCLIP_API_URL": "http://127.0.0.1:9",
    "PAPERCLIP_API_KEY": "pcp_contract_only",
    "PAPERCLIP_COMPANY_ID": "11111111-1111-4111-8111-111111111111",
}
result = subprocess.run(
    ["npx", "-y", "--min-release-age=0", "@paperclipai/mcp-server@2026.916.1"],
    input=messages,
    text=True,
    capture_output=True,
    timeout=90,
    check=True,
    env=env,
)
responses = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
tools_response = next(item for item in responses if item.get("id") == 2)
names = {tool["name"] for tool in tools_response["result"]["tools"]}
required = {
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
missing = sorted(required - names)
if missing:
    raise SystemExit(f"Pinned Paperclip MCP package is missing required tools: {missing}")
print("Pinned Paperclip MCP tool contract passed.")
