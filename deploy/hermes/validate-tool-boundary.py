#!/usr/bin/env python3
"""Validate the Chief's exact resolved Hermes capability boundary."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
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
    "paperclipCheckoutIssue",
    "paperclipUpdateIssue",
    "paperclipAddComment",
    "paperclipAskUserQuestions",
    "nixResolveFounderDecision",
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
    "API_SERVER_KEY", "HERMES_DECISION_WEBHOOK_SECRET", "TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USERS",
    "TELEGRAM_HOME_CHANNEL",
    "PAPERCLIP_LIOR_USER_ID", "WEBHOOK_SECRET", "NIX_FOUNDER_RELAY_SECRET",
    "PAPERCLIP_API_KEY", "PAPERCLIP_AGENT_ID", "PAPERCLIP_COMPANY_ID", "PAPERCLIP_API_URL",
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "GOOGLE_API_KEY",
    "OPENCODE_GO_API_KEY", "OPENCODE_GO_BASE_URL", "OPENCODE_ZEN_API_KEY",
    "GEMINI_API_KEY", "XAI_API_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY",
    "TOGETHER_API_KEY", "HF_TOKEN", "HUGGINGFACE_TOKEN",
}
GRILL_GUIDANCE = Path("/opt/hermes/optional-skills/software-development/grill-me/SKILL.md")
BRAIN_ROOT = Path("/workspace/nix-brain")
HERMES_STATE_DB = Path("/opt/data/state.db")
HERMES_CONFIG = Path("/opt/data/config.yaml")
HERMES_LEGACY_SESSIONS = Path("/opt/data/sessions/sessions.json")
WEBHOOK_SUBSCRIPTIONS = Path("/opt/data/webhook_subscriptions.json")
RUNS_IDEMPOTENCY_DB = Path("/opt/data/runs_idempotency.db")
QUESTION_OUTBOX = Path("/opt/data/state/paperclip-question-delivery.db")
EXPECTED_MODEL_ROUTE = {
    "provider": "opencode-go",
    "model": "gpt-5.6-luna",
    "base_url": "https://opencode.ai/zen/go/v1",
}


def validate_optional_state_database(path: Path, label: str) -> None:
    """Reject every non-regular representation, including dangling symlinks."""
    if not os.path.lexists(path):
        return
    metadata = path.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_uid != 10000
        or metadata.st_gid != 10000
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        fail(f"the {label} ownership or mode is unsafe")


def validate_optional_private_directory(path: Path, label: str) -> None:
    if not os.path.lexists(path):
        return
    metadata = path.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != 10000
        or metadata.st_gid != 10000
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        fail(f"the {label} ownership or mode is unsafe")


def validate_no_dynamic_webhook_subscriptions(path: Path) -> None:
    """Chief has one immutable route; even an empty mutable route file is unsafe."""
    if os.path.lexists(path):
        fail("dynamic Hermes webhook subscriptions are forbidden for Chief")


def webhook_config_check(
    *, subscriptions_path: Path = WEBHOOK_SUBSCRIPTIONS,
    runs_idempotency_path: Path = RUNS_IDEMPOTENCY_DB,
    outbox_path: Path = QUESTION_OUTBOX,
    quiet: bool = False,
) -> None:
    """Validate the fixed, non-model-visible Paperclip decision delivery lane."""
    from gateway.config import Platform, load_gateway_config

    config = load_gateway_config()
    telegram = config.platforms.get(Platform.TELEGRAM)
    webhook = config.platforms.get(Platform.WEBHOOK)
    if telegram is None or telegram.home_channel is None:
        fail("Telegram has no statically configured home channel")
    allowed_user = os.getenv("TELEGRAM_ALLOWED_USERS", "")
    configured_home = os.getenv("TELEGRAM_HOME_CHANNEL", "")
    if re.fullmatch(r"[1-9][0-9]*", allowed_user) is None:
        fail("Telegram home channel is not backed by one positive allowlisted user")
    if not hmac.compare_digest(configured_home, allowed_user):
        fail("external Telegram home channel differs from the sole allowlisted user")
    if str(telegram.home_channel.chat_id) != allowed_user:
        fail("Telegram home channel differs from the sole allowlisted user")
    if telegram.gateway_restart_notification is not False:
        fail("Telegram restart notifications must remain disabled")
    if webhook is None or webhook.enabled is not True:
        fail("the fixed Hermes webhook receiver is not enabled")
    secret = os.getenv("HERMES_DECISION_WEBHOOK_SECRET", "")
    if re.fullmatch(r"[0-9a-f]{64}", secret) is None:
        fail("the decision webhook secret is missing or invalid")
    if hmac.compare_digest(secret, os.getenv("API_SERVER_KEY", "")):
        fail("the decision webhook and Runs API secrets are not distinct")
    if os.getenv("WEBHOOK_ENABLED") != "true" or not hmac.compare_digest(
        secret, os.getenv("WEBHOOK_SECRET", "")
    ):
        fail("the upstream webhook receiver secret differs from the decision sender secret")
    expected_route = {
        "events": ["paperclip.decision_required"],
        "prompt": "{message}",
        "deliver": "telegram",
        "deliver_only": True,
    }
    expected_extra = {
        "host": "127.0.0.1",
        "port": 8644,
        "rate_limit": 10,
        "max_body_bytes": 16384,
        "secret": secret,
        "routes": {"paperclip-decision": expected_route},
    }
    if webhook.extra != expected_extra:
        fail("the Hermes webhook boundary differs from the fixed delivery policy")
    validate_no_dynamic_webhook_subscriptions(subscriptions_path)
    validate_optional_state_database(runs_idempotency_path, "Hermes Runs idempotency database")
    validate_optional_private_directory(outbox_path.parent, "Paperclip question outbox directory")
    validate_optional_state_database(outbox_path, "Paperclip question outbox")
    if not quiet:
        print("Hermes Paperclip decision-delivery boundary verified.")


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

    webhook_config_check(quiet=True)
    config = load_config()
    paperclip_server = config.get("mcp_servers", {}).get("paperclip", {})
    paperclip_environment = paperclip_server.get("env", {})
    if paperclip_environment.get("PAPERCLIP_LIOR_USER_ID") != os.getenv(
        "PAPERCLIP_LIOR_USER_ID"
    ):
        fail("Paperclip question addressee differs from the validated founder user")
    discovered = set(discover_mcp_tools(allowed_mcp_names=["paperclip"]))
    expected_mcp = {mcp_prefixed_tool_name("paperclip", name) for name in APPROVED_PAPERCLIP_TOOLS}
    if discovered != expected_mcp:
        fail(f"Paperclip MCP discovery differs from the eleven-tool policy: {sorted(discovered)}")
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
            "denied", "permission denied", "read-only file system",
            "outside hermes_write_safe_root", "cannot read", "device file",
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


def _tracked_brain_markdown() -> tuple[Path, str, str]:
    """Select a small tracked Markdown file without emitting its name or contents."""
    from agent.redact import redact_sensitive_text

    listing = subprocess.run(
        [
            "git", "-c", f"safe.directory={BRAIN_ROOT}", "-C", str(BRAIN_ROOT),
            "ls-files", "-z", "--", "*.md",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if listing.returncode != 0:
        fail("read-only brain checkout is not a readable Git worktree")
    for encoded_relative in listing.stdout.split(b"\0"):
        if not encoded_relative:
            continue
        try:
            relative = encoded_relative.decode("utf-8")
            candidate = (BRAIN_ROOT / relative).resolve(strict=True)
            candidate.relative_to(BRAIN_ROOT.resolve(strict=True))
            if candidate.name.casefold() in {"agents.md", "claude.md", "soul.md"}:
                continue
            size = candidate.stat().st_size
            if not candidate.is_file() or size <= 0 or size > 64 * 1024:
                continue
            content = candidate.read_text(encoding="utf-8")
            lines = content.splitlines()
            if not lines or len(lines) > 1000 or any(len(line) > 512 for line in lines):
                continue
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        numbered_source = content[:-1] if content.endswith("\n") else content
        numbered = "\n".join(
            f"{line_number}|{line}"
            for line_number, line in enumerate(numbered_source.split("\n"), start=1)
        )
        return candidate, content, redact_sensitive_text(numbered, file_read=True)
    fail("read-only brain checkout has no usable tracked Markdown file")


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

        brain_file, brain_before, expected_brain_tool_content = _tracked_brain_markdown()
        brain_digest = hashlib.sha256(brain_before.encode("utf-8")).digest()
        brain_result = require_success(
            read_file_tool(str(brain_file), task_id="nix-boundary-brain-read"),
            "read tracked brain Markdown",
        )
        if str(brain_result.get("content", "")) != expected_brain_tool_content:
            fail("tracked brain Markdown read did not return its exact contents")
        require_denied(
            write_file_tool(
                str(brain_file), brain_before + "\n<!-- nix-boundary-write-probe -->\n",
                task_id="nix-boundary-brain-write",
            ),
            "write tracked brain Markdown",
        )
        if hashlib.sha256(brain_file.read_bytes()).digest() != brain_digest:
            fail("tracked brain Markdown changed during validation")

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


def _process_environment(proc_dir: Path) -> dict[str, list[bytes]]:
    try:
        raw_items = (proc_dir / "environ").read_bytes().split(b"\0")
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        fail("could not inspect the live gateway environment")
    values: dict[str, list[bytes]] = {}
    for item in raw_items:
        if b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        try:
            decoded_key = key.decode("ascii")
        except UnicodeDecodeError:
            continue
        values.setdefault(decoded_key, []).append(value)
    return values


def _one_process_value(environment: dict[str, list[bytes]], key: str) -> bytes:
    values = environment.get(key, [])
    if len(values) != 1:
        fail(f"live gateway must contain exactly one {key} entry")
    return values[0]


def telegram_model_route_check(
    *, state_db: Path = HERMES_STATE_DB, config_path: Path = HERMES_CONFIG,
    legacy_sessions: Path = HERMES_LEGACY_SESSIONS,
) -> None:
    """Reject Telegram session overrides that bypass the reviewed model route.

    ``gateway_routing`` in state.db is the pinned runtime's primary routing
    index. The adjacent sessions.json file is also inspected because the
    pinned runtime imports legacy-only keys that SQLite lacks. Diagnostics
    intentionally disclose neither session identifiers nor stored state.
    """
    try:
        import yaml
    except ImportError as exc:
        fail(f"could not inspect the reviewed Hermes model configuration ({type(exc).__name__})")
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        fail(f"could not inspect the reviewed Hermes model configuration ({type(exc).__name__})")
    model = config.get("model") if isinstance(config, dict) else None
    if not isinstance(model, dict) or {
        "provider": model.get("provider"),
        "model": model.get("default"),
    } != {
        "provider": EXPECTED_MODEL_ROUTE["provider"],
        "model": EXPECTED_MODEL_ROUTE["model"],
    }:
        fail("reviewed Hermes model configuration differs from the pinned route")
    configured_base_url = model.get("base_url")
    if configured_base_url not in (None, "", EXPECTED_MODEL_ROUTE["base_url"]):
        fail("reviewed Hermes model configuration overrides the pinned endpoint")
    platforms = config.get("platforms") if isinstance(config, dict) else None
    telegram = platforms.get("telegram") if isinstance(platforms, dict) else None
    channel_overrides = telegram.get("channel_overrides") if isinstance(telegram, dict) else None
    if channel_overrides not in (None, {}):
        fail("reviewed Hermes Telegram configuration contains forbidden channel overrides")

    try:
        connection = sqlite3.connect(f"file:{state_db}?mode=ro", uri=True, timeout=5)
        try:
            rows = connection.execute(
                "SELECT session_key, entry_json FROM gateway_routing WHERE scope = ?",
                (str(legacy_sessions.parent.resolve()),),
            ).fetchall()
        finally:
            connection.close()
    except (OSError, sqlite3.Error) as exc:
        fail(f"could not inspect authoritative Hermes routing state ({type(exc).__name__})")

    try:
        if legacy_sessions.exists():
            legacy = json.loads(legacy_sessions.read_text(encoding="utf-8"))
            if not isinstance(legacy, dict):
                fail("legacy Hermes routing state has an unexpected shape")
        else:
            legacy = {}
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail(f"could not inspect legacy Hermes routing state ({type(exc).__name__})")

    encoded_routes = list(rows)
    encoded_routes.extend(
        (session_key, entry)
        for session_key, entry in legacy.items()
        if isinstance(session_key, str) and not session_key.startswith("_")
    )
    mismatched_routes = 0
    malformed_routes = 0
    for session_key, encoded_entry in encoded_routes:
        try:
            entry = json.loads(encoded_entry) if isinstance(encoded_entry, (str, bytes)) else encoded_entry
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
            # Only classify a malformed entry as Telegram when its non-secret
            # routing key says so. Never include the key in diagnostics.
            if isinstance(session_key, str) and ":telegram:" in session_key:
                malformed_routes += 1
            continue
        if not isinstance(entry, dict):
            if isinstance(session_key, str) and ":telegram:" in session_key:
                malformed_routes += 1
            continue
        if entry.get("platform") != "telegram" and not (
            isinstance(session_key, str) and ":telegram:" in session_key
        ):
            continue
        override = entry.get("model_override")
        if override is None:
            continue
        if not isinstance(override, dict) or override != EXPECTED_MODEL_ROUTE:
            mismatched_routes += 1
    if malformed_routes:
        fail("authoritative Hermes routing state contains malformed Telegram entries")
    if mismatched_routes:
        fail("Telegram session model override differs from the reviewed model route")
    print("Hermes Telegram model routing verified.")


def process_check(
    *, proc_root: Path = Path("/proc"), profile_env: Path = HERMES_ENV,
    state_db: Path = HERMES_STATE_DB, config_path: Path = HERMES_CONFIG,
    legacy_sessions: Path = HERMES_LEGACY_SESSIONS,
) -> dict[str, list[dict[str, int]]]:
    """Prove the model-facing gateway, MCP child, and logger run as Hermes."""
    expected = {
        "gateway": lambda command: "hermes gateway run --replace" in command,
        "mcp_wrapper": lambda command: "python3 /opt/nix/run-scoped-paperclip-mcp.py" in command,
        "mcp_upstream": lambda command: "npm exec @paperclipai/mcp-server@2026.916.1" in command,
        "logger": lambda command: "s6-log" in command and "/opt/data/logs/gateways/default" in command,
    }
    found: dict[str, list[tuple[int, int, int, int, tuple[int, ...]]]] = {
        label: [] for label in expected
    }
    for proc_dir in proc_root.iterdir():
        if not proc_dir.name.isdigit():
            continue
        try:
            command = (proc_dir / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            status_lines = (proc_dir / "status").read_text().splitlines()
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        fields = {line.split(":", 1)[0]: line.split(":", 1)[1].split() for line in status_lines if ":" in line}
        ppid = int(fields["PPid"][0])
        uid = int(fields["Uid"][0])
        gid = int(fields["Gid"][0])
        groups = tuple(int(value) for value in fields.get("Groups", []))
        for label, matches in expected.items():
            if matches(command):
                found[label].append((int(proc_dir.name), ppid, uid, gid, groups))
    missing = sorted(label for label, values in found.items() if not values)
    if missing:
        fail("required Hermes processes were not found: " + ", ".join(missing))
    if len(found["gateway"]) != 1:
        fail(f"expected exactly one Hermes gateway process; found {len(found['gateway'])}")
    unsafe = {
        label: values
        for label, values in found.items()
        if any(value[2:4] != (10000, 10000) for value in values)
    }
    if unsafe:
        fail("Hermes process ownership is unsafe: " + ", ".join(sorted(unsafe)))
    wrapper_pids = {pid for pid, _, _, _, _ in found["mcp_wrapper"]}
    for pid, _, _, _, _ in found["mcp_wrapper"]:
        if "PAPERCLIP_RUN_ID" in _process_environment(proc_root / str(pid)):
            fail("MCP wrapper retained a static Paperclip run ID")
    persistent_upstreams = 0
    for pid, ppid, _, _, _ in found["mcp_upstream"]:
        run_values = _process_environment(proc_root / str(pid)).get("PAPERCLIP_RUN_ID", [])
        if not run_values:
            if ppid not in wrapper_pids:
                fail("persistent MCP upstream is not owned by a discovered wrapper")
            persistent_upstreams += 1
            continue
        if len(run_values) != 1:
            fail("run-scoped MCP child has malformed Paperclip run attribution")
        try:
            supplied = run_values[0].decode("ascii")
            canonical = str(uuid.UUID(supplied))
        except (UnicodeDecodeError, ValueError):
            fail("run-scoped MCP child has malformed Paperclip run attribution")
        if supplied != canonical:
            fail("run-scoped MCP child has malformed Paperclip run attribution")
        if ppid not in wrapper_pids:
            fail("run-scoped MCP child is not owned by a discovered wrapper")
    if persistent_upstreams < 1:
        fail("no unattributed persistent Paperclip MCP upstream was found")
    expected_brain_gid = os.getenv("NIX_EXPECT_BRAIN_GID", "")
    if expected_brain_gid:
        if re.fullmatch(r"[1-9][0-9]*", expected_brain_gid) is None:
            fail("validated nix-brain group is not a positive numeric group ID")
        brain_gid = int(expected_brain_gid)
        if brain_gid not in found["gateway"][0][4]:
            fail("live gateway lacks the validated nix-brain supplemental group")
    if profile_env.exists():
        forbidden_profile_keys = {
            "HERMES_DECISION_WEBHOOK_SECRET",
            "OPENCODE_GO_BASE_URL",
            "PAPERCLIP_LIOR_USER_ID",
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_HOME_CHANNEL",
            "TELEGRAM_ALLOWED_USERS",
            "TELEGRAM_ALLOW_ALL_USERS",
            "WEBHOOK_SECRET",
            "GATEWAY_ALLOW_ALL_USERS",
        }
        with profile_env.open("r", encoding="utf-8-sig", newline="") as stream:
            bindings = list(parse_stream(stream))
        if any(binding.error for binding in bindings):
            fail("persistent profile environment contains invalid dotenv syntax")
        for binding in bindings:
            if binding.key in forbidden_profile_keys:
                fail("persistent profile retained a forbidden external runtime override")
    telegram_model_route_check(
        state_db=state_db, config_path=config_path, legacy_sessions=legacy_sessions
    )
    expected_telegram_mode = os.getenv("NIX_EXPECT_TELEGRAM_MODE", "")
    if expected_telegram_mode:
        if expected_telegram_mode not in ("disabled", "live"):
            fail("unsupported expected Telegram mode")
        expected_token_digest = os.getenv("NIX_EXPECT_TELEGRAM_TOKEN_SHA256", "").encode()
        expected_user = os.getenv("NIX_EXPECT_TELEGRAM_ALLOWED_USERS", "").encode()
        expected_home = os.getenv("NIX_EXPECT_TELEGRAM_HOME_CHANNEL", "").encode()
        expected_telegram_allow_all = os.getenv(
            "NIX_EXPECT_TELEGRAM_ALLOW_ALL_USERS", ""
        ).encode()
        expected_gateway_allow_all = os.getenv("NIX_EXPECT_GATEWAY_ALLOW_ALL_USERS", "").encode()
        if re.fullmatch(rb"[0-9a-f]{64}", expected_token_digest) is None:
            fail("validated external Telegram token digest is missing or invalid")
        if re.fullmatch(rb"[1-9][0-9]*", expected_user) is None:
            fail("validated external Telegram allowlist is not exactly one positive numeric user ID")
        if not hmac.compare_digest(expected_home, expected_user):
            fail("validated external Telegram home channel differs from the sole allowlisted user")
        if expected_telegram_allow_all != b"false" or expected_gateway_allow_all != b"false":
            fail("validated external Telegram allow-all controls are not false")

        gateway_pid = found["gateway"][0][0]
        environment = _process_environment(proc_root / str(gateway_pid))
        expected_lior_user = os.getenv("NIX_EXPECT_PAPERCLIP_LIOR_USER_ID", "").encode()
        if not expected_lior_user:
            fail("validated founder Paperclip user ID is missing")
        live_lior_user = _one_process_value(environment, "PAPERCLIP_LIOR_USER_ID")
        if not hmac.compare_digest(live_lior_user, expected_lior_user):
            fail("live gateway founder Paperclip user differs from deployment configuration")
        opencode_go_base_urls = environment.get("OPENCODE_GO_BASE_URL", [])
        if len(opencode_go_base_urls) > 1 or any(opencode_go_base_urls):
            fail("live gateway overrides the reviewed OpenCode Go endpoint")
        live_token = _one_process_value(environment, "TELEGRAM_BOT_TOKEN")
        live_user = _one_process_value(environment, "TELEGRAM_ALLOWED_USERS")
        live_home = _one_process_value(environment, "TELEGRAM_HOME_CHANNEL")
        live_telegram_allow_all = _one_process_value(environment, "TELEGRAM_ALLOW_ALL_USERS")
        live_gateway_allow_all = _one_process_value(environment, "GATEWAY_ALLOW_ALL_USERS")
        if expected_telegram_mode == "disabled" and live_token:
            fail("live gateway retained a Telegram token while disabled")
        if expected_telegram_mode == "live" and (
            not live_token
            or not hmac.compare_digest(hashlib.sha256(live_token).hexdigest().encode(), expected_token_digest)
        ):
            fail("live gateway Telegram token differs from the validated external configuration")
        for label, live, expected_value in (
            ("TELEGRAM_ALLOWED_USERS", live_user, expected_user),
            ("TELEGRAM_HOME_CHANNEL", live_home, expected_home),
            ("TELEGRAM_ALLOW_ALL_USERS", live_telegram_allow_all, expected_telegram_allow_all),
            ("GATEWAY_ALLOW_ALL_USERS", live_gateway_allow_all, expected_gateway_allow_all),
        ):
            if not hmac.compare_digest(live, expected_value):
                fail(f"live gateway {label} differs from the validated external configuration")

    summary = {
        label: [
            {"pid": pid, "ppid": ppid, "uid": uid, "gid": gid}
            for pid, ppid, uid, gid, _ in sorted(values)
        ]
        for label, values in sorted(found.items())
    }
    print(json.dumps(summary, separators=(",", ":"), sort_keys=True))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=("runtime", "api", "files-preflight", "files", "processes", "webhook-config"),
    )
    args = parser.parse_args()
    if args.mode == "runtime":
        runtime_check()
    elif args.mode == "api":
        api_check()
    elif args.mode == "files-preflight":
        files_check(preflight=True)
    elif args.mode == "processes":
        process_check()
    elif args.mode == "webhook-config":
        webhook_config_check()
    else:
        files_check()


if __name__ == "__main__":
    main()
