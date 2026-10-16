#!/usr/bin/env python3
"""Hermetic contract tests for the run-scoped Paperclip MCP wrapper."""

from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import runpy
import select
import subprocess
import sys
import tempfile
import time


REPO = Path(__file__).resolve().parents[2]
WRAPPER = REPO / "deploy/hermes/run-scoped-paperclip-mcp.py"
PACKAGE = "@paperclipai/mcp-server@2026.916.1"
SECRET = "pcp_wrapper_secret_must_not_leak"
RUN_ONE = "11111111-1111-4111-8111-111111111111"
RUN_TWO = "22222222-2222-4222-8222-222222222222"


FAKE_UPSTREAM = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import sys
import time

TOOLS = [
    {"name":"paperclipMe","inputSchema":{"type":"object","properties":{}}},
    {"name":"paperclipCreateIssue","inputSchema":{"type":"object","properties":{"title":{"type":"string"}},"required":["title"]}},
    {"name":"paperclipUpdateIssue","inputSchema":{"type":"object","properties":{"issueId":{"type":"string"}},"required":["issueId"]}},
    {"name":"paperclipAddComment","inputSchema":{"type":"object","properties":{"issueId":{"type":"string"},"body":{"type":"string"}},"required":["issueId","body"]}},
]
for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    method = request.get("method")
    if method == "initialize":
        if "scoped" in sys.argv and Path(os.environ["NIX_TEST_FAIL_SCOPED_INIT"]).exists():
            os._exit(6)
        if "persistent" in sys.argv and Path(os.environ["NIX_TEST_FAIL_PERSISTENT_INIT"]).exists():
            Path(os.environ["NIX_TEST_PERSISTENT_RESTART_STARTED"]).write_text("started")
            release = Path(os.environ["NIX_TEST_PERSISTENT_RESTART_RELEASE"])
            deadline = time.monotonic() + 5
            while not release.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            os._exit(8)
        result = {"protocolVersion":"2025-03-26","capabilities":{"tools":{}},"serverInfo":{"name":"fake","version":"1"}}
    elif method == "tools/list":
        result = {"tools":TOOLS}
    elif method == "tools/call":
        params = request["params"]
        args = params.get("arguments", {})
        if args.get("forceCrash"):
            os._exit(7)
        if args.get("forceHang"):
            mode = "SCOPED" if "scoped" in sys.argv else "PERSISTENT"
            ready = os.environ[f"NIX_TEST_{mode}_DESCENDANT_READY"]
            terminated = os.environ[f"NIX_TEST_{mode}_DESCENDANT_TERMINATED"]
            child_code = (
                "import pathlib,signal,sys,time; "
                "ready=pathlib.Path(sys.argv[1]); done=pathlib.Path(sys.argv[2]); "
                "signal.signal(signal.SIGTERM, lambda *_: (done.write_text('terminated'), sys.exit(0))); "
                "ready.write_text('ready'); time.sleep(60)"
            )
            subprocess.Popen([sys.executable, "-c", child_code, ready, terminated])
            for _ in range(100):
                if Path(ready).exists():
                    break
                time.sleep(0.01)
            Path(os.environ[f"NIX_TEST_{mode}_PGID"]).write_text(str(os.getpgrp()))
            time.sleep(60)
        if args.get("forceUpstreamError"):
            result = {"content":[{"type":"text","text":"upstream rejected mutation"}],"isError":True}
        else:
            result = {"content":[{"type":"text","text":json.dumps({
                "name":params["name"],
                "arguments":args,
                "argv":sys.argv[1:],
                "meta":params.get("_meta"),
                "runId":os.environ.get("PAPERCLIP_RUN_ID"),
            }, separators=(",", ":"))}]}
    else:
        result = {"echo":method,"runId":os.environ.get("PAPERCLIP_RUN_ID")}
    print(json.dumps({"jsonrpc":"2.0","id":request["id"],"result":result}, separators=(",", ":")), flush=True)
'''


def request(process: subprocess.Popen[str], request_id: int, method: str, params: dict) -> dict:
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(
        json.dumps(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
            separators=(",", ":"),
        )
        + "\n"
    )
    process.stdin.flush()
    while True:
        line = process.stdout.readline()
        assert line, "wrapper exited before responding"
        response = json.loads(line)
        if response.get("id") == request_id:
            return response


def tool_payload(response: dict) -> dict:
    content = response["result"]["content"]
    return json.loads("".join(item.get("text", "") for item in content))


def group_gone(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return True
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return True
        raise
    return False


def main() -> None:
    production = runpy.run_path(str(WRAPPER), run_name="nix_wrapper_contract")
    persistent_command = production["PERSISTENT_UPSTREAM_COMMAND"]
    scoped_command = production["SCOPED_UPSTREAM_COMMAND"]
    assert persistent_command[-1] == PACKAGE
    assert "--offline" not in persistent_command
    assert "--min-release-age=0" not in persistent_command
    assert scoped_command[-1] == PACKAGE
    assert scoped_command.count("--offline") == 1
    assert "--min-release-age=0" not in scoped_command

    with tempfile.TemporaryDirectory(prefix="nix-run-scoped-mcp-") as directory:
        root = Path(directory)
        fake = root / "fake-upstream.py"
        fake.write_text(FAKE_UPSTREAM, encoding="utf-8")
        fake.chmod(0o700)
        launcher = root / "launcher.py"
        launcher.write_text(
            "import runpy\n"
            f"ns=runpy.run_path({str(WRAPPER)!r}, run_name='nix_wrapper')\n"
            "g=ns['serve'].__globals__\n"
            f"g['PERSISTENT_UPSTREAM_COMMAND']=({sys.executable!r},{str(fake)!r},'persistent')\n"
            f"g['SCOPED_UPSTREAM_COMMAND']=({sys.executable!r},{str(fake)!r},'scoped','--offline',{PACKAGE!r})\n"
            "g['SCOPED_STARTUP_TIMEOUT_SECONDS']=1.0\n"
            "g['SCOPED_RPC_TIMEOUT_SECONDS']=0.5\n"
            "g['PERSISTENT_STARTUP_TIMEOUT_SECONDS']=3.0\n"
            "g['PERSISTENT_RPC_TIMEOUT_SECONDS']=0.5\n"
            "g['GRACEFUL_SHUTDOWN_SECONDS']=0.25\n"
            "g['KILL_WAIT_SECONDS']=0.25\n"
            "raise SystemExit(ns['serve']())\n",
            encoding="utf-8",
        )
        environment = os.environ | {
            "PAPERCLIP_API_KEY": SECRET,
            "PAPERCLIP_RUN_ID": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "NIX_TEST_SCOPED_DESCENDANT_READY": str(root / "scoped-descendant-ready"),
            "NIX_TEST_SCOPED_DESCENDANT_TERMINATED": str(root / "scoped-descendant-terminated"),
            "NIX_TEST_SCOPED_PGID": str(root / "scoped-pgid"),
            "NIX_TEST_PERSISTENT_DESCENDANT_READY": str(root / "persistent-descendant-ready"),
            "NIX_TEST_PERSISTENT_DESCENDANT_TERMINATED": str(root / "persistent-descendant-terminated"),
            "NIX_TEST_PERSISTENT_PGID": str(root / "persistent-pgid"),
            "NIX_TEST_FAIL_SCOPED_INIT": str(root / "fail-scoped-init"),
            "NIX_TEST_FAIL_PERSISTENT_INIT": str(root / "fail-persistent-init"),
            "NIX_TEST_PERSISTENT_RESTART_STARTED": str(root / "persistent-restart-started"),
            "NIX_TEST_PERSISTENT_RESTART_RELEASE": str(root / "persistent-restart-release"),
        }
        process = subprocess.Popen(
            [sys.executable, str(launcher)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
        )
        try:
            initialized = request(
                process, 1, "initialize",
                {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "wrapper-contract", "version": "1"},
                },
            )
            assert initialized["result"]["serverInfo"]["name"] == "fake"
            listing = request(process, 2, "tools/list", {})
            tools = {item["name"]: item for item in listing["result"]["tools"]}
            assert tools["paperclipUpdateIssue"]["inputSchema"]["required"] == ["issueId"]
            assert tools["paperclipAddComment"]["inputSchema"]["required"] == ["issueId", "body"]

            # Missing reserved metadata keeps the official no-run behavior.
            missing = tool_payload(request(
                process, 3, "tools/call",
                {
                    "name": "paperclipUpdateIssue",
                    "arguments": {"issueId": "one"},
                    "_meta": {"unrelated": "kept"},
                },
            ))
            assert missing["runId"] is None
            assert missing["argv"] == ["persistent"]
            assert missing["meta"] == {"unrelated": "kept"}

            # Explicit malformed reserved metadata fails before upstream dispatch.
            for invalid in ("", "not-a-uuid", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"):
                response = request(
                    process, 4, "tools/call",
                    {
                        "name": "paperclipUpdateIssue",
                        "arguments": {"issueId": "one"},
                        "_meta": {"com.paperclip/run-id": invalid},
                    },
                )
                assert response["error"]["code"] == -32602
                assert SECRET not in json.dumps(response)

            first = tool_payload(request(
                process, 5, "tools/call",
                {
                    "name": "paperclipUpdateIssue",
                    "arguments": {"issueId": "one", "description": "updated"},
                    "_meta": {"com.paperclip/run-id": RUN_ONE, "unrelated": "preserved"},
                },
            ))
            assert first["runId"] == RUN_ONE
            assert first["meta"] == {"unrelated": "preserved"}
            assert first["argv"] == ["scoped", "--offline", PACKAGE]

            second = tool_payload(request(
                process, 6, "tools/call",
                {
                    "name": "paperclipAddComment",
                    "arguments": {"issueId": "two", "body": "done"},
                    "_meta": {"com.paperclip/run-id": RUN_TWO},
                },
            ))
            assert second["runId"] == RUN_TWO
            assert second["meta"] is None

            # Reserved run context is stripped from every other tool.
            ordinary = tool_payload(request(
                process, 7, "tools/call",
                {
                    "name": "paperclipMe",
                    "arguments": {},
                    "_meta": {"com.paperclip/run-id": RUN_ONE, "unrelated": "kept"},
                },
            ))
            assert ordinary["runId"] is None
            assert ordinary["meta"] == {"unrelated": "kept"}

            (root / "fail-scoped-init").write_text("fail", encoding="utf-8")
            pre_dispatch = tool_payload(request(
                process, 8, "tools/call",
                {
                    "name": "paperclipUpdateIssue",
                    "arguments": {"issueId": "two"},
                    "_meta": {"com.paperclip/run-id": RUN_TWO},
                },
            ))
            assert pre_dispatch["error"] == "mutation_not_dispatched"
            (root / "fail-scoped-init").unlink()

            upstream_error = request(
                process, 9, "tools/call",
                {
                    "name": "paperclipAddComment",
                    "arguments": {"issueId": "two", "body": "fail", "forceUpstreamError": True},
                    "_meta": {"com.paperclip/run-id": RUN_TWO},
                },
            )
            assert upstream_error["result"]["isError"] is True
            assert "upstream rejected mutation" in json.dumps(upstream_error)

            crashed = tool_payload(request(
                process, 10, "tools/call",
                {
                    "name": "paperclipUpdateIssue",
                    "arguments": {"issueId": "two", "forceCrash": True},
                    "_meta": {"com.paperclip/run-id": RUN_TWO},
                },
            ))
            assert crashed["error"] == "outcome_uncertain"
            assert "Read back the issue and comments before retrying" in crashed["message"]

            hanging = tool_payload(request(
                process, 11, "tools/call",
                {
                    "name": "paperclipUpdateIssue",
                    "arguments": {"issueId": "two", "forceHang": True},
                    "_meta": {"com.paperclip/run-id": RUN_TWO},
                },
            ))
            assert hanging["error"] == "outcome_uncertain"
            assert (root / "scoped-descendant-terminated").read_text() == "terminated"
            process_group = int((root / "scoped-pgid").read_text())
            for _ in range(100):
                if group_gone(process_group):
                    break
                time.sleep(0.02)
            assert group_gone(process_group), "scoped process group survived timeout cleanup"

            after_scoped_failure = tool_payload(request(
                process, 12, "tools/call", {"name": "paperclipMe", "arguments": {}},
            ))
            assert after_scoped_failure["runId"] is None

            # Every persistent mutation is ambiguity-safe after full dispatch.
            create_crash = tool_payload(request(
                process, 13, "tools/call",
                {
                    "name": "paperclipCreateIssue",
                    "arguments": {"title": "create", "forceCrash": True},
                },
            ))
            assert create_crash["error"] == "outcome_uncertain"
            assert "Read back the issue and comments before retrying" in create_crash["message"]
            after_create_crash = tool_payload(request(
                process, 14, "tools/call", {"name": "paperclipMe", "arguments": {}},
            ))
            assert after_create_crash["runId"] is None

            update_hang = tool_payload(request(
                process, 15, "tools/call",
                {
                    "name": "paperclipUpdateIssue",
                    "arguments": {"issueId": "persistent", "forceHang": True},
                },
            ))
            assert update_hang["error"] == "outcome_uncertain"
            assert "Read back the issue and comments before retrying" in update_hang["message"]
            assert (root / "persistent-descendant-terminated").read_text() == "terminated"
            persistent_group = int((root / "persistent-pgid").read_text())
            for _ in range(100):
                if group_gone(persistent_group):
                    break
                time.sleep(0.02)
            assert group_gone(persistent_group), "persistent process group survived timeout cleanup"

            comment_crash = tool_payload(request(
                process, 16, "tools/call",
                {
                    "name": "paperclipAddComment",
                    "arguments": {
                        "issueId": "persistent",
                        "body": "comment",
                        "forceCrash": True,
                    },
                },
            ))
            assert comment_crash["error"] == "outcome_uncertain"

            recovered = tool_payload(request(
                process, 17, "tools/call",
                {
                    "name": "paperclipAddComment",
                    "arguments": {"issueId": "persistent", "body": "recovered"},
                },
            ))
            assert recovered["name"] == "paperclipAddComment"
            assert recovered["runId"] is None
            assert recovered["argv"] == ["persistent"]
        finally:
            if process.stdin is not None:
                process.stdin.close()
            process.wait(timeout=10)
            stderr = process.stderr.read() if process.stderr is not None else ""
            assert process.returncode == 0, stderr
            assert SECRET not in stderr

        # A slow replacement must not consume the current mutation's response
        # budget. The wrapper flushes uncertainty, then blocks later stdin while
        # replacement initialization fails and exits fail-closed.
        failure_process = subprocess.Popen(
            [sys.executable, str(launcher)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
        )
        try:
            initialized = request(
                failure_process, 18, "initialize",
                {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "wrapper-contract", "version": "1"},
                },
            )
            assert initialized["result"]["serverInfo"]["name"] == "fake"
            (root / "fail-persistent-init").write_text("fail", encoding="utf-8")
            assert failure_process.stdin is not None
            assert failure_process.stdout is not None
            failure_process.stdin.write(json.dumps({
                "jsonrpc": "2.0",
                "id": 19,
                "method": "tools/call",
                "params": {
                    "name": "paperclipCreateIssue",
                    "arguments": {"title": "timing", "forceCrash": True},
                },
            }, separators=(",", ":")) + "\n")
            failure_process.stdin.flush()
            readable, _, _ = select.select([failure_process.stdout], [], [], 0.75)
            assert readable, "mutation response consumed replacement-startup budget"
            uncertain = tool_payload(json.loads(failure_process.stdout.readline()))
            assert uncertain["error"] == "outcome_uncertain"
            assert failure_process.poll() is None, "wrapper waited for replacement failure before responding"
            for _ in range(100):
                if (root / "persistent-restart-started").exists():
                    break
                time.sleep(0.01)
            assert (root / "persistent-restart-started").exists()
            (root / "persistent-restart-release").write_text("release", encoding="utf-8")
            failure_process.wait(timeout=5)
            assert failure_process.returncode == 1
        finally:
            if failure_process.poll() is None:
                failure_process.terminate()
                failure_process.wait(timeout=5)
            stderr = (
                failure_process.stderr.read()
                if failure_process.stderr is not None
                else ""
            )
            assert SECRET not in stderr

    print("Run-scoped Paperclip MCP wrapper contract passed.")


if __name__ == "__main__":
    main()
