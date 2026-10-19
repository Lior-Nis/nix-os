#!/usr/bin/env python3
"""Hermetic tests for Nix's pinned Hermes run-attribution patch."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import threading
import types


REPO = Path(__file__).resolve().parents[2]
PATCHER_PATH = REPO / "deploy/hermes/patch-run-attribution.py"


def load_patcher():
    spec = importlib.util.spec_from_file_location("nix_hermes_run_patch", PATCHER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves the defining module while decorating PatchSpec.
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_context_module(source: str):
    gateway = types.ModuleType("gateway")
    session_context = types.ModuleType("gateway.session_context")
    session_context._UNSET = object()
    for name in (
        "_SESSION_PLATFORM", "_SESSION_CHAT_TYPE", "_SESSION_CHAT_ID",
        "_SESSION_USER_ID", "_SESSION_MESSAGE_ID",
    ):
        setattr(session_context, name, ContextVar(name, default=session_context._UNSET))
    gateway.session_context = session_context
    import sys
    previous_gateway = sys.modules.get("gateway")
    previous_session = sys.modules.get("gateway.session_context")
    sys.modules["gateway"] = gateway
    sys.modules["gateway.session_context"] = session_context
    module = types.ModuleType("gateway.paperclip_run_context")
    try:
        exec(compile(source, "paperclip_run_context.py", "exec"), module.__dict__)
    finally:
        if previous_gateway is None:
            del sys.modules["gateway"]
        else:
            sys.modules["gateway"] = previous_gateway
        if previous_session is None:
            del sys.modules["gateway.session_context"]
        else:
            sys.modules["gateway.session_context"] = previous_session
    return module, session_context


def test_context_contract(patcher) -> None:
    context, session_context = load_context_module(patcher.CONTEXT_MODULE)
    run_one = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    run_two = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

    for invalid in (None, "", "not-a-uuid", run_one.upper(), f" {run_one}"):
        assert context.validated_paperclip_run_id(invalid) is None
        token = context.bind_paperclip_run_id(invalid)
        try:
            assert context.paperclip_request_metadata("paperclip") is None
        finally:
            context.reset_paperclip_run_id(token)

    static_value = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    previous = os.environ.get("PAPERCLIP_RUN_ID")
    os.environ["PAPERCLIP_RUN_ID"] = static_value
    token = context.bind_paperclip_run_id(run_one)
    try:
        assert context.paperclip_request_metadata("paperclip") == {
            "com.paperclip/run-id": run_one
        }
        for other in ("Paperclip", "paperclip-read", "github", ""):
            assert context.paperclip_request_metadata(other) is None
        assert os.environ["PAPERCLIP_RUN_ID"] == static_value
    finally:
        context.reset_paperclip_run_id(token)
        if previous is None:
            del os.environ["PAPERCLIP_RUN_ID"]
        else:
            os.environ["PAPERCLIP_RUN_ID"] = previous
    assert context.paperclip_request_metadata("paperclip") is None

    previous_user = os.environ.get("TELEGRAM_ALLOWED_USERS")
    previous_chat = os.environ.get("TELEGRAM_HOME_CHANNEL")
    os.environ["TELEGRAM_ALLOWED_USERS"] = "123456789"
    os.environ["TELEGRAM_HOME_CHANNEL"] = "123456789"
    telegram_tokens = [
        session_context._SESSION_PLATFORM.set("telegram"),
        session_context._SESSION_CHAT_TYPE.set("dm"),
        session_context._SESSION_CHAT_ID.set("123456789"),
        session_context._SESSION_USER_ID.set("123456789"),
        session_context._SESSION_MESSAGE_ID.set("42"),
    ]
    try:
        assert context.paperclip_request_metadata("paperclip") == {
            "com.nix/hermes-platform": "telegram",
            "com.nix/hermes-chat-type": "dm",
            "com.nix/hermes-chat-id": "123456789",
            "com.nix/hermes-user-id": "123456789",
            "com.nix/hermes-message-id": "42",
        }
        assert context.paperclip_request_metadata("other") is None
        session_context._SESSION_USER_ID.set("987654321")
        assert context.paperclip_request_metadata("paperclip") is None
        session_context._SESSION_USER_ID.set("123456789")
        session_context._SESSION_CHAT_TYPE.set("group")
        assert context.paperclip_request_metadata("paperclip") is None
        session_context._SESSION_CHAT_TYPE.set("dm")
        session_context._SESSION_PLATFORM.set("api_server")
        assert context.paperclip_request_metadata("paperclip") is None
    finally:
        for variable, token in zip(
            (
                session_context._SESSION_PLATFORM,
                session_context._SESSION_CHAT_TYPE,
                session_context._SESSION_CHAT_ID,
                session_context._SESSION_USER_ID,
                session_context._SESSION_MESSAGE_ID,
            ),
            telegram_tokens,
        ):
            variable.reset(token)
        if previous_user is None:
            del os.environ["TELEGRAM_ALLOWED_USERS"]
        else:
            os.environ["TELEGRAM_ALLOWED_USERS"] = previous_user
        if previous_chat is None:
            del os.environ["TELEGRAM_HOME_CHANNEL"]
        else:
            os.environ["TELEGRAM_HOME_CHANNEL"] = previous_chat

    # Simulate _run_agent_sync binding inside executor workers. The barrier
    # keeps both scopes live simultaneously and proves there is no global/env
    # cross-talk between runs.
    barrier = threading.Barrier(2)

    def executor_run(run_id: str):
        bound = context.bind_paperclip_run_id(run_id)
        try:
            barrier.wait(timeout=5)
            return context.paperclip_request_metadata("paperclip")
        finally:
            context.reset_paperclip_run_id(bound)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(executor_run, run_one)
        second = executor.submit(executor_run, run_two)
        assert first.result(timeout=10) == {"com.paperclip/run-id": run_one}
        assert second.result(timeout=10) == {"com.paperclip/run-id": run_two}
    assert context.paperclip_request_metadata("paperclip") is None


def test_source_transforms(patcher) -> None:
    api_fixture = "".join(
        (
            "from gateway.platforms.api_server_run_idempotency import TERMINAL_STATUSES\n",
            "    browser_control_transport_family: Any\n"
            "    turn_author: Optional[Dict[str, Any]] = None  # memory-attribution label only; grants nothing\n",
            "    idempotency_scope = idempotency_fingerprint = \"\"\n"
            "    if idempotency_key:\n",
            "        browser_control_transport_family=_api_server._api_request_browser_control_transport_family.get(),\n"
            "        turn_author=turn_author)\n",
            "            # Contextvars, not process env: concurrent runs must not share identity.\n"
            "            resets.append((set_current_session_key(run.approval_session_key), reset_current_session_key))\n",
        )
    )
    patched_api = patcher.patch_api_server_runs(api_fixture)
    assert "paperclip_run_id = validated_paperclip_run_id(idempotency_key)" in patched_api
    assert "paperclip_run_id=paperclip_run_id" in patched_api
    assert "bind_paperclip_run_id(run.paperclip_run_id)" in patched_api
    assert "os.environ" not in patched_api

    mcp_fixture = "".join(
        (
            "from tools.mcp_tool_errors import _is_auth_error, _is_session_expired_error\n",
            "async def _call_tool_racing_stdio_death(server, server_name: str, tool_name: str, args: dict):\n",
            "    _call_coro = server.session.call_tool(tool_name, arguments=args)\n",
            "        server, error = _acquire_call_server(server_name, tool_timeout)\n"
            "        if server is None:\n"
            "            return error\n\n"
            "        async def _call():\n",
            "                    result = await _call_tool_racing_stdio_death(server, server_name, tool_name, args)\n",
        )
    )
    patched_mcp = patcher.patch_mcp_handlers(mcp_fixture)
    assert "request_meta = paperclip_request_metadata(server_name)" in patched_mcp
    assert '_call_kwargs["meta"] = request_meta' in patched_mcp
    assert "os.environ" not in patched_mcp


def test_installer_contract(patcher) -> None:
    original = b"known upstream\n"
    patched = b"known patched\n"
    secret = "credential-material-must-not-leak"

    def transform(source: str) -> str:
        assert source == original.decode()
        return patched.decode()

    spec = patcher.PatchSpec(
        "tools/example.py",
        hashlib.sha256(original).hexdigest(),
        hashlib.sha256(patched).hexdigest(),
        transform,
    )
    with tempfile.TemporaryDirectory(prefix="nix-hermes-run-patch-") as directory:
        root = Path(directory)
        (root / "tools").mkdir()
        (root / "gateway").mkdir()
        target = root / spec.relative_path
        target.write_bytes(original)
        target.chmod(0o640)

        patcher.apply_patch(root, (spec,))
        assert target.read_bytes() == patched
        assert target.stat().st_mode & 0o777 == 0o640
        assert (root / "gateway/paperclip_run_context.py").read_text() == patcher.CONTEXT_MODULE

        # A second invocation is a no-op success and still verifies all outputs.
        patcher.apply_patch(root, (spec,))
        patcher.verify_patch(root, (spec,))
        assert target.read_bytes() == patched

        target.write_text(secret, encoding="utf-8")
        try:
            patcher.apply_patch(root, (spec,))
        except RuntimeError as exc:
            message = str(exc)
            assert "unsupported source" in message
            assert secret not in message
        else:
            raise AssertionError("unknown Hermes source was not rejected")

        target.write_bytes(patched)
        patcher.verify_patch(root, (spec,))
        target.write_text(secret, encoding="utf-8")
        try:
            patcher.verify_patch(root, (spec,))
        except RuntimeError as exc:
            message = str(exc)
            assert "verification failed" in message
            assert secret not in message
        else:
            raise AssertionError("verification accepted unknown patched source")

        target.write_bytes(original)
        (root / "gateway/paperclip_run_context.py").write_text(secret, encoding="utf-8")
        try:
            patcher.apply_patch(root, (spec,))
        except RuntimeError as exc:
            message = str(exc)
            assert "unexpected run-context module" in message
            assert secret not in message
        else:
            raise AssertionError("unknown context module was not rejected")


def main() -> None:
    patcher = load_patcher()
    test_context_contract(patcher)
    test_source_transforms(patcher)
    test_installer_contract(patcher)
    print("Hermes run-attribution patch contract passed.")


if __name__ == "__main__":
    main()
