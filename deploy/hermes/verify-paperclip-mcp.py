#!/usr/bin/env python3
"""Verify the profile's Paperclip identity and optional bounded MCP operations."""

from __future__ import annotations

import argparse
import json
import os
import subprocess

from dotenv import load_dotenv


class McpProbe:
    def __init__(self, environment: dict[str, str]) -> None:
        self.next_id = 1
        self.process = subprocess.Popen(
            ["npx", "-y", "--min-release-age=0", "@paperclipai/mcp-server@2026.916.1"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env=environment,
        )
        self.request(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "nix-bounded-mcp-check", "version": "1"},
            },
        )
        self.notify("notifications/initialized", {})

    def write(self, payload: dict) -> None:
        if not self.process.stdin:
            raise RuntimeError("MCP stdin is unavailable")
        self.process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def notify(self, method: str, params: dict) -> None:
        self.write({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method: str, params: dict) -> dict:
        request_id = self.next_id
        self.next_id += 1
        self.write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        if not self.process.stdout:
            raise RuntimeError("MCP stdout is unavailable")
        while True:
            line = self.process.stdout.readline()
            if not line:
                raise RuntimeError("MCP server exited before responding")
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                continue
            if response.get("id") != request_id:
                continue
            if "error" in response:
                raise RuntimeError("MCP request failed")
            return response.get("result", {})

    def call(self, name: str, arguments: dict) -> object:
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError") is True:
            raise RuntimeError(f"approved MCP tool failed: {name}")
        text = "".join(
            str(item.get("text", ""))
            for item in result.get("content", [])
            if item.get("type") == "text"
        )
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"approved MCP tool returned invalid JSON: {name}") from exc
        if (
            isinstance(parsed, dict)
            and isinstance(parsed.get("status"), int)
            and parsed["status"] >= 400
        ):
            detail = str(parsed.get("error") or "unreported Paperclip error")
            raise RuntimeError(
                f"approved MCP tool returned HTTP {parsed['status']}: {name}: {detail}"
            )
        return parsed

    def close(self) -> None:
        if self.process.stdin:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=10)
        if self.process.returncode not in (0, -15):
            raise RuntimeError("pinned Paperclip MCP exited unsuccessfully")


def require_mapping(value: object, operation: str) -> dict:
    if not isinstance(value, dict):
        raise RuntimeError(f"approved MCP tool returned an unexpected shape: {operation}")
    return value


def contains_id(value: object, expected: str) -> bool:
    return expected in json.dumps(value, separators=(",", ":"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exercise-project", help="existing project UUID used for safe bounded write checks")
    parser.add_argument("--exercise-run", help="existing issue UUID used for run-scoped update/comment checks")
    args = parser.parse_args()
    if args.exercise_project and args.exercise_run:
        parser.error("choose only one exercise mode")

    load_dotenv("/opt/data/.env", override=True)
    company_id = os.environ.get("PAPERCLIP_COMPANY_ID", "")
    agent_id = os.environ.get("PAPERCLIP_AGENT_ID", "")
    api_key = os.environ.get("PAPERCLIP_API_KEY", "")
    if not company_id or not agent_id or not api_key.startswith("pcp_"):
        raise SystemExit("Paperclip profile identity is incomplete")

    probe = McpProbe(os.environ.copy())
    try:
        identity = probe.call("paperclipMe", {})
        if not contains_id(identity, company_id) or not contains_id(identity, agent_id):
            raise RuntimeError("bounded Paperclip MCP returned an unexpected identity")

        if args.exercise_run:
            if not os.environ.get("PAPERCLIP_RUN_ID"):
                raise RuntimeError("run-scoped mutation check requires PAPERCLIP_RUN_ID")
            issue_id = args.exercise_run
            updated = probe.call(
                "paperclipUpdateIssue",
                {"issueId": issue_id, "description": "Updated through the approved Chief tool boundary."},
            )
            if not contains_id(updated, issue_id):
                raise RuntimeError("bounded Paperclip MCP returned an unexpected updated issue")
            marker = "Slice 1 bounded MCP comment fixture."
            comment = require_mapping(
                probe.call(
                    "paperclipAddComment",
                    {"issueId": issue_id, "body": marker},
                ),
                "paperclipAddComment",
            )
            comment_id = str(comment.get("id") or "")
            comments = probe.call("paperclipListComments", {"issueId": issue_id})
            if (
                not comment_id
                or not contains_id(comments, comment_id)
                or marker not in json.dumps(comments, separators=(",", ":"))
            ):
                raise RuntimeError("bounded Paperclip MCP comment round trip failed")
            print(json.dumps({"issueId": issue_id, "commentId": comment_id}, separators=(",", ":")))
            return

        if not args.exercise_project:
            print("Bounded Paperclip MCP identity verified.")
            return

        project_id = args.exercise_project
        projects = probe.call("paperclipListProjects", {})
        if not contains_id(projects, project_id):
            raise RuntimeError("bounded Paperclip MCP project list omitted the fixture project")
        project = probe.call("paperclipGetProject", {"projectId": project_id})
        if not contains_id(project, project_id):
            raise RuntimeError("bounded Paperclip MCP returned an unexpected project")

        issue = require_mapping(
            probe.call(
                "paperclipCreateIssue",
                {
                    "title": "Slice 1 bounded MCP recovery issue",
                    "description": "Created through the approved Chief tool boundary.",
                    "priority": "low",
                    "projectId": project_id,
                    "assigneeAgentId": agent_id,
                },
            ),
            "paperclipCreateIssue",
        )
        issue_id = str(issue.get("id") or "")
        if not issue_id or str(issue.get("projectId") or "") != project_id:
            raise RuntimeError("bounded Paperclip MCP created an issue outside the fixture project")

        issues = probe.call("paperclipListIssues", {"projectId": project_id})
        if not contains_id(issues, issue_id):
            raise RuntimeError("bounded Paperclip MCP issue list omitted the created issue")
        fetched = probe.call("paperclipGetIssue", {"issueId": issue_id})
        if not contains_id(fetched, issue_id):
            raise RuntimeError("bounded Paperclip MCP could not read the created issue")

        comments = probe.call("paperclipListComments", {"issueId": issue_id})
        if not isinstance(comments, list):
            raise RuntimeError("bounded Paperclip MCP returned an unexpected comment-list shape")

        print(json.dumps({"issueId": issue_id}, separators=(",", ":")))
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"Bounded Paperclip MCP verification failed: {exc}") from None
    finally:
        probe.close()


if __name__ == "__main__":
    main()
