#!/usr/bin/env python3
"""Validate the Chief's exact resolved Hermes capability boundary."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import uuid

from dotenv.parser import parse_stream


EXPECTED_TOOLSETS = {"file", "memory", "session_search", "paperclip"}
EXPECTED_NATIVE_TOOLS = {
    "memory",
    "patch",
    "read_file",
    "search_files",
    "session_search",
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
SAFE_WRITE_ROOT = Path("/opt/data/memories")
HERMES_ENV = Path("/opt/data/.env")
HERMES_AUTH = Path("/opt/data/auth.json")
HERMES_PROTECTED_TOKENS = Path("/opt/data/mcp-tokens")
PREFLIGHT_CREDENTIAL_ENV = {
    "API_SERVER_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USERS",
    "PAPERCLIP_API_KEY", "PAPERCLIP_AGENT_ID", "PAPERCLIP_COMPANY_ID", "PAPERCLIP_API_URL",
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "GOOGLE_API_KEY",
    "GEMINI_API_KEY", "XAI_API_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY",
    "TOGETHER_API_KEY", "HF_TOKEN", "HUGGINGFACE_TOKEN",
}
GRILL_GUIDANCE = Path("/opt/hermes/optional-skills/software-development/grill-me/SKILL.md")


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


def parse_tool_result(raw: str, label: str) -> dict:
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        fail(f"{label} returned a non-JSON result")
    if not isinstance(payload, dict):
        fail(f"{label} returned an unexpected result shape")
    return payload


def require_success(raw: str, label: str) -> dict:
    payload = parse_tool_result(raw, label)
    if payload.get("error") or payload.get("success") is False:
        fail(f"{label} failed")
    return payload


def require_denied(raw: str, label: str) -> None:
    payload = parse_tool_result(raw, label)
    error = payload.get("error")
    if not isinstance(error, str) or not any(
        marker in error.lower() for marker in (
            "denied", "access denied", "outside hermes_write_safe_root", "cannot read", "device file",
        )
    ):
        fail(f"{label} did not fail closed")


def _write_preflight_fixture(path: Path, content: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, content.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


def files_check(*, preflight: bool = False) -> None:
    """Exercise the pinned file-tool chokepoints without retaining probe state."""
    from agent.file_safety import get_safe_write_roots
    from tools.file_tools import patch_tool, read_file_tool, search_tool, write_file_tool

    created_credentials: list[Path] = []
    canaries: list[str] = []
    try:
        fixture_id = uuid.uuid4().hex
        protected_filename = f"nix-os-paperclip-stage-boundary-{fixture_id}.json"
        protected_canary = f"nix-paperclip-stage-canary-{fixture_id}"
        HERMES_PROTECTED_TOKENS.mkdir(mode=0o700, parents=False, exist_ok=True)
        protected_dir_stat = HERMES_PROTECTED_TOKENS.stat()
        if (
            HERMES_PROTECTED_TOKENS.is_symlink()
            or not HERMES_PROTECTED_TOKENS.is_dir()
            or protected_dir_stat.st_uid != os.geteuid()
            or protected_dir_stat.st_gid != os.getegid()
            or stat.S_IMODE(protected_dir_stat.st_mode) & 0o077
        ):
            fail("protected mcp-tokens staging directory is unsafe")
        protected_stage = HERMES_PROTECTED_TOKENS / protected_filename
        _write_preflight_fixture(protected_stage, json.dumps({"claimSecret": protected_canary}) + "\n")
        protected_stat = protected_stage.stat()
        if (
            protected_stat.st_uid != os.geteuid()
            or protected_stat.st_gid != os.getegid()
            or stat.S_IMODE(protected_stat.st_mode) != 0o600
        ):
            fail("protected staged-claim fixture ownership or mode is unsafe")
        created_credentials.append(protected_stage)
        canaries.append(protected_canary)
        if preflight:
            populated = sorted(name for name in PREFLIGHT_CREDENTIAL_ENV if os.environ.get(name))
            if populated:
                fail("credential-bearing environment reached preflight: " + ", ".join(populated))
            SAFE_WRITE_ROOT.mkdir(parents=True, exist_ok=True)
        safe_root = str(SAFE_WRITE_ROOT.resolve())
        if get_safe_write_roots() != {safe_root}:
            fail("HERMES_WRITE_SAFE_ROOT must resolve exactly to /opt/data/memories")
        if not SAFE_WRITE_ROOT.is_dir():
            fail("safe write root does not exist")
        if preflight:
            if any(os.path.lexists(path) for path in (HERMES_ENV, HERMES_AUTH)):
                fail("preflight refuses to replace an existing .env or auth.json")
            canaries.extend([f"nix-env-canary-{fixture_id}", f"nix-auth-canary-{fixture_id}"])
            _write_preflight_fixture(HERMES_ENV, f"NIX_PREFLIGHT_CANARY={canaries[0]}\n")
            created_credentials.append(HERMES_ENV)
            _write_preflight_fixture(HERMES_AUTH, json.dumps({"fixture": canaries[1]}) + "\n")
            created_credentials.append(HERMES_AUTH)
        for protected in (HERMES_ENV, HERMES_AUTH):
            if not protected.is_file():
                fail(f"required protected credential fixture is missing: {protected}")
            require_denied(read_file_tool(str(protected), task_id="nix-boundary"), f"read {protected.name}")
        require_denied(
            read_file_tool(str(protected_stage), task_id="nix-boundary-stage-read"),
            "read protected staged claim secret",
        )

        credential_link = SAFE_WRITE_ROOT / f".nix-boundary-credential-link-{uuid.uuid4().hex}"
        credential_link.symlink_to(HERMES_ENV)
        linked_read = read_file_tool(str(credential_link), task_id="nix-boundary-linked-read")
        require_denied(linked_read, "read credential through symlink")
        protected_link = SAFE_WRITE_ROOT / f".nix-boundary-stage-link-{uuid.uuid4().hex}"
        protected_link.symlink_to(protected_stage)
        require_denied(
            read_file_tool(str(protected_link), task_id="nix-boundary-stage-linked-read"),
            "read protected staged claim through symlink",
        )

        proc_canary = os.getenv("NIX_HERMES_PROC_CANARY", "")
        proc_read = read_file_tool("/proc/self/environ", task_id="nix-boundary-proc-read")
        require_denied(proc_read, "read /proc/self/environ")
        if proc_canary and proc_canary in proc_read:
            fail("proc environ read leaked its canary")
        if proc_canary:
            proc_search = parse_tool_result(search_tool(
                pattern=proc_canary, target="content", path="/proc/self", limit=1000,
                task_id="nix-boundary-proc-search",
            ), "search /proc/self")
            if proc_canary in json.dumps(proc_search.get("matches", []), sort_keys=True):
                fail("proc search leaked its environment canary")

        guidance_before = GRILL_GUIDANCE.read_bytes() if GRILL_GUIDANCE.is_file() else b""
        if not guidance_before:
            fail("pinned grill-me guidance is missing")
        guidance_result = require_success(
            read_file_tool(str(GRILL_GUIDANCE), task_id="nix-boundary"), "read grill-me guidance"
        )
        if "name: grill-me" not in str(guidance_result.get("content", "")):
            fail("pinned grill-me guidance has an unexpected identity")
        require_denied(
            write_file_tool(str(GRILL_GUIDANCE), guidance_before.decode("utf-8"), task_id="nix-boundary"),
            "write grill-me guidance",
        )
        require_denied(
            patch_tool(
                path=str(GRILL_GUIDANCE), old_string="name: grill-me", new_string="name: forbidden",
                task_id="nix-boundary",
            ),
            "patch grill-me guidance",
        )
        if hashlib.sha256(GRILL_GUIDANCE.read_bytes()).digest() != hashlib.sha256(guidance_before).digest():
            fail("pinned grill-me guidance changed during validation")

        probe_id = uuid.uuid4().hex
        safe_file = SAFE_WRITE_ROOT / f".nix-boundary-{probe_id}.txt"
        outside_file = Path("/opt/data") / f".nix-boundary-outside-{probe_id}.txt"
        outside_target = Path("/tmp") / f"nix-boundary-target-{probe_id}.txt"
        escape_link = SAFE_WRITE_ROOT / f".nix-boundary-link-{probe_id}.txt"
        require_success(
            write_file_tool(str(safe_file), "boundary-before\n", task_id="nix-boundary"),
            "write inside memories",
        )
        require_success(
            patch_tool(
                path=str(safe_file), old_string="boundary-before", new_string="boundary-after",
                task_id="nix-boundary",
            ),
            "patch inside memories",
        )
        if safe_file.read_text() != "boundary-after\n":
            fail("safe-root write/patch did not persist the expected probe")

        require_denied(
            write_file_tool(str(outside_file), "forbidden\n", task_id="nix-boundary"),
            "write outside memories",
        )
        if outside_file.exists():
            fail("outside-root write created a file")

        outside_target.write_text("escape-before\n")
        escape_link.symlink_to(outside_target)
        require_denied(
            write_file_tool(str(escape_link), "escape-write\n", task_id="nix-boundary"),
            "write through symlink escape",
        )
        require_denied(
            patch_tool(
                path=str(escape_link), old_string="escape-before", new_string="escape-after",
                task_id="nix-boundary",
            ),
            "patch through symlink escape",
        )
        if outside_target.read_text() != "escape-before\n":
            fail("symlink escape modified its outside target")

        filename_search = parse_tool_result(search_tool(
            pattern="*", target="files", path="/opt/data", limit=1000, task_id="nix-boundary-search-files"
        ), "broad file search")
        visible_file_matches = json.dumps(filename_search.get("matches", []), sort_keys=True)
        for protected_name in (".env", "auth.json"):
            if protected_name in visible_file_matches:
                fail("broad file search returned a protected credential file")
        if protected_filename in visible_file_matches:
            fail("broad file search returned the protected staged-claim filename")
        for index, canary in enumerate(canaries):
            search_payload = parse_tool_result(search_tool(
                pattern=canary, target="content", path="/opt/data", limit=1000,
                task_id=f"nix-boundary-canary-{index}",
            ), "broad content search")
            visible_content_matches = json.dumps(search_payload.get("matches", []), sort_keys=True)
            if canary in visible_content_matches:
                fail("broad content search leaked a credential canary")
    finally:
        for path in (
            locals().get("credential_link"), locals().get("protected_link"),
            locals().get("escape_link"), locals().get("safe_file"),
            locals().get("outside_file"), locals().get("outside_target"),
        ):
            if path is None:
                continue
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        for path in reversed(created_credentials):
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    print("Hermes file read/write boundary verified.")


def process_check() -> None:
    """Prove the model-facing gateway, MCP child, and logger run as Hermes."""
    expected = {
        "gateway": lambda command: "hermes gateway run --replace" in command,
        "mcp": lambda command: "npm exec @paperclipai/mcp-server@2026.916.1" in command,
        "logger": lambda command: "s6-log" in command and "/opt/data/logs/gateways/default" in command,
    }
    found: dict[str, tuple[int, int, int]] = {}
    for proc_dir in Path("/proc").iterdir():
        if not proc_dir.name.isdigit():
            continue
        try:
            command = (proc_dir / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            status_lines = (proc_dir / "status").read_text().splitlines()
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        fields = {line.split(":", 1)[0]: line.split(":", 1)[1].split() for line in status_lines if ":" in line}
        uid = int(fields["Uid"][0])
        gid = int(fields["Gid"][0])
        for label, matches in expected.items():
            if matches(command):
                found[label] = (int(proc_dir.name), uid, gid)
    missing = sorted(set(expected) - set(found))
    if missing:
        fail("required Hermes processes were not found: " + ", ".join(missing))
    unsafe = {label: values for label, values in found.items() if values[1:] != (10000, 10000)}
    if unsafe:
        fail("Hermes process ownership is unsafe: " + ", ".join(sorted(unsafe)))
    profile_env = Path("/opt/data/.env")
    if profile_env.exists():
        forbidden_profile_keys = {
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_ALLOWED_USERS",
            "TELEGRAM_ALLOW_ALL_USERS",
            "GATEWAY_ALLOW_ALL_USERS",
        }
        with profile_env.open("r", encoding="utf-8-sig", newline="") as stream:
            bindings = list(parse_stream(stream))
        if any(binding.error for binding in bindings):
            fail("persistent profile environment contains invalid dotenv syntax")
        for binding in bindings:
            if binding.key in forbidden_profile_keys:
                fail("persistent profile retained an external-only Telegram control")
    expected_telegram_mode = os.getenv("NIX_EXPECT_TELEGRAM_MODE", "")
    if expected_telegram_mode:
        if expected_telegram_mode != "disabled":
            fail("unsupported expected Telegram mode")
        gateway_pid = found["gateway"][0]
        try:
            environment = (Path("/proc") / str(gateway_pid) / "environ").read_bytes().split(b"\0")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            fail("could not inspect the live gateway environment")
        token_values = [item.split(b"=", 1)[1] for item in environment if item.startswith(b"TELEGRAM_BOT_TOKEN=")]
        if any(token_values):
            fail("live gateway retained a Telegram token while disabled")
    print(json.dumps({label: {"pid": values[0], "uid": values[1], "gid": values[2]} for label, values in sorted(found.items())}))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("runtime", "api", "files-preflight", "files", "processes"))
    args = parser.parse_args()
    if args.mode == "runtime":
        runtime_check()
    elif args.mode == "api":
        api_check()
    elif args.mode == "files-preflight":
        files_check(preflight=True)
    elif args.mode == "processes":
        process_check()
    else:
        files_check()


if __name__ == "__main__":
    main()
