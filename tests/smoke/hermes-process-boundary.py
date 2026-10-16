#!/usr/bin/env python3
"""Exercise live Hermes process and Telegram-environment validation without secrets."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types


REPO = Path(__file__).resolve().parents[2]
VALIDATOR = REPO / "deploy/hermes/validate-tool-boundary.py"

# The process fixture never parses a profile .env. Stub the pinned-only import
# so this narrow test remains runnable in the secret-free foundation job.
dotenv = types.ModuleType("dotenv")
dotenv_parser = types.ModuleType("dotenv.parser")
dotenv_parser.parse_stream = lambda stream: ()
dotenv.parser = dotenv_parser
sys.modules.setdefault("dotenv", dotenv)
sys.modules.setdefault("dotenv.parser", dotenv_parser)
spec = importlib.util.spec_from_file_location("nix_hermes_boundary", VALIDATOR)
assert spec is not None and spec.loader is not None
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


CONFIG = {
    "TELEGRAM_BOT_TOKEN": "configured-token-canary",
    "TELEGRAM_ALLOWED_USERS": "123456789",
    "TELEGRAM_ALLOW_ALL_USERS": "false",
    "GATEWAY_ALLOW_ALL_USERS": "false",
}
EXPECTATIONS = {
    "NIX_EXPECT_TELEGRAM_TOKEN_SHA256": hashlib.sha256(
        CONFIG["TELEGRAM_BOT_TOKEN"].encode()
    ).hexdigest(),
    "NIX_EXPECT_TELEGRAM_ALLOWED_USERS": CONFIG["TELEGRAM_ALLOWED_USERS"],
    "NIX_EXPECT_TELEGRAM_ALLOW_ALL_USERS": CONFIG["TELEGRAM_ALLOW_ALL_USERS"],
    "NIX_EXPECT_GATEWAY_ALLOW_ALL_USERS": CONFIG["GATEWAY_ALLOW_ALL_USERS"],
}


def add_process(
    root: Path,
    pid: int,
    command: str,
    environment: dict[str, str] | list[tuple[str, str]],
    *,
    parent_pid: int = 1,
) -> None:
    process = root / str(pid)
    process.mkdir()
    (process / "cmdline").write_bytes(command.replace(" ", "\0").encode() + b"\0")
    (process / "status").write_text(
        f"Name:\tfixture\nPPid:\t{parent_pid}\n"
        "Uid:\t10000\t10000\t10000\t10000\nGid:\t10000\t10000\t10000\t10000\n",
        encoding="utf-8",
    )
    items = environment.items() if isinstance(environment, dict) else environment
    payload = b"\0".join(f"{key}={value}".encode() for key, value in items) + b"\0"
    (process / "environ").write_bytes(payload)


def fixture(
    root: Path,
    gateway_environment: dict[str, str] | list[tuple[str, str]],
    *,
    duplicate_gateway: bool = False,
    wrapper_environment: dict[str, str] | None = None,
    upstream_environment: dict[str, str] | None = None,
    transient_run_id: str | None = None,
    transient_parent_pid: int = 201,
    orphan_persistent: bool = False,
) -> None:
    add_process(root, 101, "hermes gateway run --replace", gateway_environment)
    if duplicate_gateway:
        add_process(root, 102, "hermes gateway run --replace", gateway_environment)
    wrapper_env = wrapper_environment or {}
    upstream_env = upstream_environment or {}
    add_process(root, 201, "python3 /opt/nix/run-scoped-paperclip-mcp.py", wrapper_env)
    add_process(root, 202, "python3 /opt/nix/run-scoped-paperclip-mcp.py", wrapper_env)
    add_process(root, 211, "npm exec @paperclipai/mcp-server@2026.916.1", upstream_env, parent_pid=201)
    add_process(root, 212, "npm exec @paperclipai/mcp-server@2026.916.1", upstream_env, parent_pid=202)
    if transient_run_id is not None:
        add_process(
            root,
            213,
            "npm exec @paperclipai/mcp-server@2026.916.1",
            {"PAPERCLIP_RUN_ID": transient_run_id},
            parent_pid=transient_parent_pid,
        )
    if orphan_persistent:
        add_process(
            root,
            214,
            "npm exec @paperclipai/mcp-server@2026.916.1",
            {},
            parent_pid=999,
        )
    add_process(root, 301, "s6-log /opt/data/logs/gateways/default", {})


@contextlib.contextmanager
def configured_environment(**overrides: str):
    # TELEGRAM_* simulates Docker's potentially stale container-creation
    # environment. NIX_EXPECT_* is the independent, host-file-derived truth.
    values = CONFIG | EXPECTATIONS | overrides
    before = {key: os.environ.get(key) for key in values}
    try:
        os.environ.update(values)
        yield
    finally:
        for key, value in before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def check(root: Path, mode: str) -> dict[str, list[dict[str, int]]]:
    os.environ["NIX_EXPECT_TELEGRAM_MODE"] = mode
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        result = validator.process_check(proc_root=root, profile_env=root / "profile.env")
    assert json.loads(output.getvalue()) == result
    return result


def rejected(root: Path, mode: str, expected: str) -> None:
    try:
        check(root, mode)
    except SystemExit as exc:
        message = str(exc)
        assert expected in message, message
        assert CONFIG["TELEGRAM_BOT_TOKEN"] not in message
    else:
        raise AssertionError(f"unsafe process fixture unexpectedly passed: {expected}")


def main() -> None:
    with configured_environment():
        with tempfile.TemporaryDirectory(prefix="nix-hermes-process-disabled-") as directory:
            root = Path(directory)
            fixture(root, CONFIG | {"TELEGRAM_BOT_TOKEN": ""})
            summary = check(root, "disabled")
            assert len(summary["gateway"]) == 1
            assert len(summary["mcp_wrapper"]) == 2
            assert len(summary["mcp_upstream"]) == 2

        with tempfile.TemporaryDirectory(prefix="nix-hermes-process-live-") as directory:
            root = Path(directory)
            fixture(root, CONFIG)
            check(root, "live")

        with tempfile.TemporaryDirectory(prefix="nix-hermes-process-disabled-token-") as directory:
            root = Path(directory)
            fixture(root, CONFIG)
            rejected(root, "disabled", "retained a Telegram token while disabled")

        for token_environment, expected in (
            (CONFIG | {"TELEGRAM_BOT_TOKEN": ""}, "token differs"),
            ({key: value for key, value in CONFIG.items() if key != "TELEGRAM_BOT_TOKEN"},
             "exactly one TELEGRAM_BOT_TOKEN entry"),
            ([*CONFIG.items(), ("TELEGRAM_BOT_TOKEN", "duplicate-token")],
             "exactly one TELEGRAM_BOT_TOKEN entry"),
        ):
            with tempfile.TemporaryDirectory(prefix="nix-hermes-process-live-token-") as directory:
                root = Path(directory)
                fixture(root, token_environment)
                rejected(root, "live", expected)

        for changed, expected in (
            ({"TELEGRAM_BOT_TOKEN": "stale-token"}, "token differs"),
            ({"TELEGRAM_ALLOWED_USERS": "987654321"}, "TELEGRAM_ALLOWED_USERS differs"),
            ({"TELEGRAM_ALLOW_ALL_USERS": "true"}, "TELEGRAM_ALLOW_ALL_USERS differs"),
            ({"GATEWAY_ALLOW_ALL_USERS": "true"}, "GATEWAY_ALLOW_ALL_USERS differs"),
        ):
            with tempfile.TemporaryDirectory(prefix="nix-hermes-process-stale-") as directory:
                root = Path(directory)
                fixture(root, CONFIG | changed)
                rejected(root, "live", expected)

        with tempfile.TemporaryDirectory(prefix="nix-hermes-process-duplicate-") as directory:
            root = Path(directory)
            fixture(root, CONFIG, duplicate_gateway=True)
            rejected(root, "live", "exactly one Hermes gateway process")

        with tempfile.TemporaryDirectory(prefix="nix-hermes-process-static-run-") as directory:
            root = Path(directory)
            fixture(
                root,
                CONFIG,
                upstream_environment={"PAPERCLIP_RUN_ID": "11111111-1111-4111-8111-111111111111"},
            )
            rejected(root, "live", "no unattributed persistent Paperclip MCP upstream")

        with tempfile.TemporaryDirectory(prefix="nix-hermes-process-wrapper-run-") as directory:
            root = Path(directory)
            fixture(
                root,
                CONFIG,
                wrapper_environment={"PAPERCLIP_RUN_ID": "11111111-1111-4111-8111-111111111111"},
            )
            rejected(root, "live", "MCP wrapper retained a static Paperclip run ID")

        with tempfile.TemporaryDirectory(prefix="nix-hermes-process-transient-run-") as directory:
            root = Path(directory)
            fixture(
                root,
                CONFIG,
                transient_run_id="11111111-1111-4111-8111-111111111111",
            )
            summary = check(root, "live")
            assert len(summary["mcp_upstream"]) == 3

        with tempfile.TemporaryDirectory(prefix="nix-hermes-process-malformed-run-") as directory:
            root = Path(directory)
            fixture(root, CONFIG, transient_run_id="not-a-uuid")
            rejected(root, "live", "malformed Paperclip run attribution")

        with tempfile.TemporaryDirectory(prefix="nix-hermes-process-orphan-run-") as directory:
            root = Path(directory)
            fixture(
                root,
                CONFIG,
                transient_run_id="11111111-1111-4111-8111-111111111111",
                transient_parent_pid=999,
            )
            rejected(root, "live", "not owned by a discovered wrapper")

        with tempfile.TemporaryDirectory(prefix="nix-hermes-process-orphan-persistent-") as directory:
            root = Path(directory)
            fixture(root, CONFIG, orphan_persistent=True)
            rejected(root, "live", "persistent MCP upstream is not owned by a discovered wrapper")

        with tempfile.TemporaryDirectory(prefix="nix-hermes-process-missing-") as directory:
            root = Path(directory)
            missing_control = dict(CONFIG)
            del missing_control["TELEGRAM_ALLOWED_USERS"]
            fixture(root, missing_control)
            rejected(root, "live", "exactly one TELEGRAM_ALLOWED_USERS entry")

    with configured_environment(NIX_EXPECT_TELEGRAM_ALLOW_ALL_USERS="true"):
        with tempfile.TemporaryDirectory(prefix="nix-hermes-process-config-") as directory:
            root = Path(directory)
            fixture(root, CONFIG)
            rejected(root, "live", "validated external Telegram allow-all controls are not false")

    with configured_environment(NIX_EXPECT_TELEGRAM_ALLOWED_USERS="123456789,987654321"):
        with tempfile.TemporaryDirectory(prefix="nix-hermes-process-config-user-") as directory:
            root = Path(directory)
            fixture(root, CONFIG)
            rejected(root, "live", "exactly one positive numeric user ID")

    # The gateway and Docker creation environment agree, but the separately
    # validated external host file has rotated. This must fail until recreate.
    with configured_environment(
        NIX_EXPECT_TELEGRAM_TOKEN_SHA256=hashlib.sha256(b"rotated-external-token").hexdigest()
    ):
        with tempfile.TemporaryDirectory(prefix="nix-hermes-process-host-drift-") as directory:
            root = Path(directory)
            fixture(root, CONFIG)
            rejected(root, "live", "token differs")

    print("Hermes live process and Telegram boundary fixtures passed.")


if __name__ == "__main__":
    main()
