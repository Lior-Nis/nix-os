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
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "paperclipUpdateIssue",
                    "arguments": {
                        "issueId": "22222222-2222-4222-8222-222222222222",
                        "description": "offline resolution probe",
                    },
                    "_meta": {
                        "com.paperclip/run-id": "33333333-3333-4333-8333-333333333333"
                    },
                },
            }
        ),
        "",
    ]
)
env = os.environ | {
    "PAPERCLIP_API_URL": "http://127.0.0.1:9",
    "PAPERCLIP_API_KEY": "pcp_contract_only",
    "PAPERCLIP_COMPANY_ID": "11111111-1111-4111-8111-111111111111",
}
result = subprocess.run(
    ["python3", "/opt/nix/run-scoped-paperclip-mcp.py"],
    input=messages,
    text=True,
    capture_output=True,
    timeout=90,
    check=True,
    env=env,
)
responses = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
tools_response = next(item for item in responses if item.get("id") == 2)
mutation_response = next(item for item in responses if item.get("id") == 3)
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
schemas = {tool["name"]: tool["inputSchema"] for tool in tools_response["result"]["tools"]}
for name in ("paperclipUpdateIssue", "paperclipAddComment"):
    if "runId" in schemas[name].get("properties", {}) or "runId" in schemas[name].get("required", []):
        raise SystemExit(f"Run attribution became model-visible in the official schema: {name}")
mutation_result = mutation_response.get("result", {})
mutation_text = "".join(
    str(item.get("text", ""))
    for item in mutation_result.get("content", [])
    if item.get("type") == "text"
)
try:
    mutation_payload = json.loads(mutation_text)
except json.JSONDecodeError:
    mutation_payload = {}
if (
    mutation_response.get("error")
    or not mutation_text
    or mutation_payload.get("error") in ("outcome_uncertain", "mutation_not_dispatched")
    or (
        mutation_payload.get("error") is None
        and mutation_payload.get("status", 0) < 400
    )
):
    raise SystemExit("Run-scoped offline MCP probe did not reach the official upstream tool")
print("Pinned Paperclip MCP tool contract passed.")
