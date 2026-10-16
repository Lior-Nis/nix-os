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
            ["python3", "/opt/nix/run-scoped-paperclip-mcp.py"],
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

    def call(self, name: str, arguments: dict, *, metadata: dict | None = None) -> object:
        params = {"name": name, "arguments": arguments}
        if metadata is not None:
            params["_meta"] = metadata
        result = self.request("tools/call", params)
        if result.get("isError") is True:
            raise RuntimeError(f"approved MCP tool failed: {name}")
        parsed = None
        for item in result.get("content", []):
            if item.get("type") != "text":
                continue
            try:
                parsed = json.loads(str(item.get("text", "")))
            except json.JSONDecodeError:
                continue
            break
        if parsed is None:
            raise RuntimeError(f"approved MCP tool returned invalid JSON: {name}")
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

    def call_expect_http_error(
        self,
        name: str,
        arguments: dict,
        *,
        metadata: dict,
        expected_status: int,
    ) -> None:
        params = {"name": name, "arguments": arguments, "_meta": metadata}
        result = self.request("tools/call", params)
        for item in result.get("content", []):
            if item.get("type") != "text":
                continue
            try:
                parsed = json.loads(str(item.get("text", "")))
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and parsed.get("status") == expected_status:
                return
        raise RuntimeError(
            f"approved MCP tool did not return HTTP {expected_status}: {name}"
        )

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
    parser.add_argument("--exercise-project-id", help="project UUID for run-scoped child creation")
    parser.add_argument("--expect-checkout-conflict", help="issue UUID already checked out by another run")
    parser.add_argument("--mark-in-review", help="issue UUID to leave waiting on its pending interaction")
    args = parser.parse_args()
    selected = sum(bool(value) for value in (
        args.exercise_project, args.exercise_run, args.expect_checkout_conflict,
        args.mark_in_review,
    ))
    if selected > 1:
        parser.error("choose only one exercise mode")
    if bool(args.exercise_project_id) != bool(args.exercise_run):
        parser.error("--exercise-project-id is required exactly with --exercise-run")

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

        if args.expect_checkout_conflict:
            if not os.environ.get("PAPERCLIP_RUN_ID"):
                raise RuntimeError("checkout-conflict check requires PAPERCLIP_RUN_ID")
            probe.call_expect_http_error(
                "paperclipCheckoutIssue",
                {"issueId": args.expect_checkout_conflict},
                metadata={"com.paperclip/run-id": os.environ["PAPERCLIP_RUN_ID"]},
                expected_status=409,
            )
            print(json.dumps({"conflict": True}, separators=(",", ":")))
            return

        if args.mark_in_review:
            if not os.environ.get("PAPERCLIP_RUN_ID"):
                raise RuntimeError("waiting-state check requires PAPERCLIP_RUN_ID")
            waiting_issue = probe.call(
                "paperclipUpdateIssue",
                {"issueId": args.mark_in_review, "status": "in_review"},
                metadata={"com.paperclip/run-id": os.environ["PAPERCLIP_RUN_ID"]},
            )
            if not contains_id(waiting_issue, args.mark_in_review):
                raise RuntimeError("bounded Paperclip waiting-state update failed")
            print(json.dumps({"inReview": True}, separators=(",", ":")))
            return

        if args.exercise_run:
            if not os.environ.get("PAPERCLIP_RUN_ID"):
                raise RuntimeError("run-scoped mutation check requires PAPERCLIP_RUN_ID")
            issue_id = args.exercise_run
            run_id = os.environ["PAPERCLIP_RUN_ID"]
            metadata = {"com.paperclip/run-id": run_id}
            checked_out = probe.call(
                "paperclipCheckoutIssue", {"issueId": issue_id}, metadata=metadata
            )
            if not contains_id(checked_out, issue_id):
                raise RuntimeError("bounded Paperclip MCP checkout returned an unexpected issue")
            updated = probe.call(
                "paperclipUpdateIssue",
                {"issueId": issue_id, "description": "Updated through the approved Chief tool boundary."},
                metadata=metadata,
            )
            if not contains_id(updated, issue_id):
                raise RuntimeError("bounded Paperclip MCP returned an unexpected updated issue")
            marker = "Slice 1 bounded MCP comment fixture."
            comment = require_mapping(
                probe.call(
                    "paperclipAddComment",
                    {"issueId": issue_id, "body": marker},
                    metadata=metadata,
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
            child = require_mapping(
                probe.call(
                    "paperclipCreateIssue",
                    {
                        "title": "Slice 2 run-scoped child fixture",
                        "description": "Child created by the attributed Chief run.",
                        "priority": "low",
                        "projectId": args.exercise_project_id,
                        "parentId": issue_id,
                        "idempotencyKey": f"slice-2-child:{issue_id}",
                    },
                    metadata=metadata,
                ),
                "paperclipCreateIssue",
            )
            child_id = str(child.get("id") or "")
            if not child_id or child.get("parentId") != issue_id:
                raise RuntimeError("bounded Paperclip MCP child relationship is wrong")
            question_arguments = {
                "issueId": issue_id,
                "idempotencyKey": f"slice-2-question:{issue_id}",
                "continuationPolicy": "wake_assignee",
                "payload": {
                    "version": 1,
                    "title": "Recovery decision fixture",
                    "questions": [{
                        "id": "direction",
                        "prompt": "Choose the recovery fixture direction",
                        "selectionMode": "single",
                        "required": True,
                        "options": [{"id": "continue", "label": "Continue"}],
                    }],
                },
            }
            interaction = require_mapping(
                probe.call(
                    "paperclipAskUserQuestions", question_arguments, metadata=metadata
                ),
                "paperclipAskUserQuestions",
            )
            interaction_id = str(interaction.get("id") or "")
            if (
                not interaction_id
                or interaction.get("issueId") != issue_id
                or interaction.get("kind") != "ask_user_questions"
                or interaction.get("status") != "pending"
                or interaction.get("requestedResolverPolicy") != "human_only"
                or interaction.get("effectiveResolverPolicy") != "human_only"
                or interaction.get("addresseeUserId") != os.environ.get("PAPERCLIP_LIOR_USER_ID")
                or interaction.get("sourceRunId") != run_id
            ):
                raise RuntimeError("bounded Paperclip question policy or attribution is wrong")
            replayed_interaction = require_mapping(
                probe.call(
                    "paperclipAskUserQuestions", question_arguments, metadata=metadata
                ),
                "paperclipAskUserQuestions replay",
            )
            if replayed_interaction.get("id") != interaction_id:
                raise RuntimeError("bounded Paperclip question replay was not idempotent")
            print(json.dumps({
                "issueId": issue_id,
                "commentId": comment_id,
                "childId": child_id,
                "interactionId": interaction_id,
            }, separators=(",", ":")))
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
