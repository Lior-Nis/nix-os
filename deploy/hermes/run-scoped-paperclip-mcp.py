#!/usr/bin/env python3
"""Add trusted per-call heartbeat attribution to two Paperclip MCP mutations.

All ordinary traffic is proxied to one warmed instance of the exact official
package. When Hermes supplies a valid request-local Paperclip run ID, only an
existing-issue update/comment is routed through a short-lived, offline official
MCP process carrying that ID. The official schemas remain unchanged.
"""

from __future__ import annotations

import copy
import json
import os
import re
import select
import signal
import subprocess
import sys
import time
from typing import Any


PACKAGE = "@paperclipai/mcp-server@2026.916.1"
PERSISTENT_UPSTREAM_COMMAND = ("npx", "-y", PACKAGE)
SCOPED_UPSTREAM_COMMAND = ("npx", "-y", "--offline", PACKAGE)
RUN_SCOPED_TOOLS = {"paperclipUpdateIssue", "paperclipAddComment"}
MUTATION_TOOLS = {
    "paperclipCreateIssue",
    "paperclipUpdateIssue",
    "paperclipAddComment",
}
RUN_ID_META_KEY = "com.paperclip/run-id"
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)

# Hermes' outer MCP call timeout remains the final guard. These shorter bounds
# ensure a wedged compatibility child reports a useful result first.
PERSISTENT_RPC_TIMEOUT_SECONDS = 60.0
PERSISTENT_STARTUP_TIMEOUT_SECONDS = 15.0
SCOPED_STARTUP_TIMEOUT_SECONDS = 15.0
SCOPED_RPC_TIMEOUT_SECONDS = 30.0
WRITE_TIMEOUT_SECONDS = 5.0
GRACEFUL_SHUTDOWN_SECONDS = 2.0
KILL_WAIT_SECONDS = 2.0


class UpstreamFailure(RuntimeError):
    """The pinned upstream failed, optionally after mutation dispatch."""

    def __init__(self, *, dispatched: bool = False) -> None:
        super().__init__("pinned upstream failure")
        self.dispatched = dispatched


class McpProcess:
    def __init__(self, command: tuple[str, ...], *, run_id: str | None = None) -> None:
        environment = os.environ.copy()
        environment.pop("PAPERCLIP_RUN_ID", None)
        if run_id is not None:
            environment["PAPERCLIP_RUN_ID"] = run_id
        try:
            self.process = subprocess.Popen(
                list(command),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
                env=environment,
                start_new_session=True,
            )
        except OSError as exc:
            raise UpstreamFailure from exc
        if self.process.stdin is None or self.process.stdout is None:
            raise UpstreamFailure
        os.set_blocking(self.process.stdin.fileno(), False)
        os.set_blocking(self.process.stdout.fileno(), False)
        self._buffer = bytearray()

    @staticmethod
    def _remaining(deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise UpstreamFailure
        return remaining

    def write(self, payload: dict[str, Any], *, timeout: float) -> None:
        data = memoryview(
            (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        )
        deadline = time.monotonic() + timeout
        descriptor = self.process.stdin.fileno()
        while data:
            try:
                _, writable, _ = select.select(
                    [], [descriptor], [], self._remaining(deadline)
                )
                if not writable:
                    raise UpstreamFailure
                written = os.write(descriptor, data)
            except (BrokenPipeError, OSError, ValueError) as exc:
                raise UpstreamFailure from exc
            if written <= 0:
                raise UpstreamFailure
            data = data[written:]

    def read_json(self, *, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        descriptor = self.process.stdout.fileno()
        while True:
            while b"\n" in self._buffer:
                line, _, remainder = self._buffer.partition(b"\n")
                self._buffer = bytearray(remainder)
                try:
                    payload = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if isinstance(payload, dict):
                    return payload
            if self.process.poll() is not None:
                raise UpstreamFailure
            try:
                readable, _, _ = select.select(
                    [descriptor], [], [], self._remaining(deadline)
                )
                if not readable:
                    raise UpstreamFailure
                chunk = os.read(descriptor, 65536)
            except (OSError, ValueError) as exc:
                raise UpstreamFailure from exc
            if not chunk:
                raise UpstreamFailure
            self._buffer.extend(chunk)

    def request(
        self,
        payload: dict[str, Any],
        *,
        timeout: float,
        mutation: bool = False,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if "id" not in payload:
            raise UpstreamFailure
        self.write(payload, timeout=WRITE_TIMEOUT_SECONDS)
        request_id = payload["id"]
        preceding: list[dict[str, Any]] = []
        deadline = time.monotonic() + timeout
        try:
            while True:
                response = self.read_json(timeout=self._remaining(deadline))
                if response.get("id") == request_id:
                    return response, preceding
                preceding.append(response)
        except UpstreamFailure as exc:
            raise UpstreamFailure(dispatched=mutation) from exc

    def _terminate_group(self) -> None:
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except PermissionError:
            # macOS can report EPERM for an already-reaped, now-empty session.
            # A live leader returning EPERM is not safe to ignore.
            if self.process.poll() is not None:
                return
            raise
        try:
            self.process.wait(timeout=GRACEFUL_SHUTDOWN_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        deadline = time.monotonic() + GRACEFUL_SHUTDOWN_SECONDS
        while time.monotonic() < deadline:
            try:
                os.killpg(self.process.pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.02)
        try:
            os.killpg(self.process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        try:
            self.process.wait(timeout=KILL_WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            pass

    def close(self, *, failed: bool = False) -> None:
        if failed:
            self._terminate_group()
            return
        try:
            self.process.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        try:
            self.process.wait(timeout=GRACEFUL_SHUTDOWN_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        # Every upstream owns a process group. Clean it even after a graceful
        # leader exit so npm/node descendants cannot survive wrapper shutdown.
        self._terminate_group()


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _invalid_params(request_id: Any) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": -32602,
            "message": "Trusted Paperclip run metadata is invalid",
        },
    }


def _tool_failure(request_id: Any, *, uncertain: bool) -> dict[str, Any]:
    if uncertain:
        payload = {
            "error": "outcome_uncertain",
            "message": (
                "The mutation was dispatched but no conclusive response was received. "
                "Read back the issue and comments before retrying."
            ),
        }
    else:
        payload = {
            "error": "mutation_not_dispatched",
            "message": "The mutation was not dispatched; retry after the MCP path recovers.",
        }
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "content": [{"type": "text", "text": json.dumps(payload, separators=(",", ":"))}],
            "isError": True,
        },
    }


def _rpc_failure(request_id: Any) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": -32603,
            "message": "The pinned Paperclip MCP upstream failed and was restarted",
        },
    }


def _strip_reserved_metadata(request: dict[str, Any]) -> dict[str, Any]:
    params = request.get("params")
    metadata = params.get("_meta") if isinstance(params, dict) else None
    if not isinstance(metadata, dict) or RUN_ID_META_KEY not in metadata:
        return request
    forwarded = copy.deepcopy(request)
    forwarded_metadata = forwarded["params"]["_meta"]
    forwarded_metadata.pop(RUN_ID_META_KEY, None)
    if not forwarded_metadata:
        forwarded["params"].pop("_meta", None)
    return forwarded


def _explicit_run_metadata(request: dict[str, Any]) -> tuple[bool, str | None]:
    params = request.get("params")
    metadata = params.get("_meta") if isinstance(params, dict) else None
    if not isinstance(metadata, dict) or RUN_ID_META_KEY not in metadata:
        return False, None
    value = metadata[RUN_ID_META_KEY]
    if not isinstance(value, str) or UUID_PATTERN.fullmatch(value) is None:
        return True, None
    return True, value


def _mutation_call(
    request: dict[str, Any], initialize_params: dict[str, Any], run_id: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    process = McpProcess(SCOPED_UPSTREAM_COMMAND, run_id=run_id)
    failed = True
    failure: UpstreamFailure | None = None
    try:
        init_request = {
            "jsonrpc": "2.0",
            "id": "nix-run-scoped-initialize",
            "method": "initialize",
            "params": initialize_params,
        }
        init_response, init_preceding = process.request(
            init_request, timeout=SCOPED_STARTUP_TIMEOUT_SECONDS
        )
        if "error" in init_response:
            raise UpstreamFailure
        process.write(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            timeout=WRITE_TIMEOUT_SECONDS,
        )
        response, preceding = process.request(
            _strip_reserved_metadata(request),
            timeout=SCOPED_RPC_TIMEOUT_SECONDS,
            mutation=True,
        )
        failed = False
        return response, [*init_preceding, *preceding]
    except UpstreamFailure as exc:
        failure = exc
        raise
    finally:
        try:
            process.close(failed=failed)
        except (BrokenPipeError, OSError, ValueError):
            if failure is None and failed:
                raise UpstreamFailure from None


def _restart_persistent(
    initialize_params: dict[str, Any],
) -> McpProcess | None:
    try:
        process = McpProcess(PERSISTENT_UPSTREAM_COMMAND)
    except UpstreamFailure:
        return None
    try:
        response, _ = process.request(
            {
                "jsonrpc": "2.0",
                "id": "nix-persistent-reinitialize",
                "method": "initialize",
                "params": initialize_params,
            },
            timeout=PERSISTENT_STARTUP_TIMEOUT_SECONDS,
        )
        if "error" in response:
            raise UpstreamFailure
        process.write(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            timeout=WRITE_TIMEOUT_SECONDS,
        )
        return process
    except (BrokenPipeError, OSError, UpstreamFailure, ValueError):
        process.close(failed=True)
        return None


def serve() -> int:
    try:
        persistent = McpProcess(PERSISTENT_UPSTREAM_COMMAND)
    except UpstreamFailure:
        return 1
    initialize_params: dict[str, Any] | None = None
    persistent_ready = False
    try:
        for raw_line in sys.stdin:
            try:
                request = json.loads(raw_line)
            except json.JSONDecodeError:
                _emit({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
                continue
            if not isinstance(request, dict):
                _emit(_invalid_params(None))
                continue

            method = request.get("method")
            params = request.get("params")
            if method == "initialize" and isinstance(params, dict):
                initialize_params = copy.deepcopy(params)

            persistent_mutation = False
            if method == "tools/call" and isinstance(params, dict):
                name = params.get("name")
                persistent_mutation = name in MUTATION_TOOLS
                has_reserved, run_id = _explicit_run_metadata(request)
                if name in RUN_SCOPED_TOOLS and has_reserved:
                    if run_id is None:
                        _emit(_invalid_params(request.get("id")))
                        continue
                    if initialize_params is None:
                        _emit(_tool_failure(request.get("id"), uncertain=False))
                        continue
                    try:
                        response, preceding = _mutation_call(
                            request, initialize_params, run_id
                        )
                    except (BrokenPipeError, OSError, UpstreamFailure, ValueError) as exc:
                        uncertain = not isinstance(exc, UpstreamFailure) or exc.dispatched
                        response = _tool_failure(
                            request.get("id"), uncertain=uncertain
                        )
                        preceding = []
                    for message in preceding:
                        _emit(message)
                    _emit(response)
                    continue
                request = _strip_reserved_metadata(request)

            if "id" not in request:
                persistent.write(request, timeout=WRITE_TIMEOUT_SECONDS)
                continue
            try:
                response, preceding = persistent.request(
                    request,
                    timeout=PERSISTENT_RPC_TIMEOUT_SECONDS,
                    mutation=persistent_mutation,
                )
            except UpstreamFailure as exc:
                persistent.close(failed=True)
                if persistent_mutation:
                    _emit(
                        _tool_failure(
                            request.get("id"), uncertain=exc.dispatched
                        )
                    )
                else:
                    _emit(_rpc_failure(request.get("id")))
                # Flush the current call's conclusive failure classification
                # before replacement startup consumes any of the outer Hermes
                # timeout. The serial stdin loop still accepts no later call
                # until a clean official upstream is initialized.
                replacement = (
                    _restart_persistent(initialize_params)
                    if persistent_ready and initialize_params is not None
                    else None
                )
                if replacement is None:
                    return 1
                persistent = replacement
                continue
            for message in preceding:
                _emit(message)
            _emit(response)
            if method == "initialize" and "error" not in response:
                persistent_ready = True
    except (BrokenPipeError, OSError, UpstreamFailure, ValueError):
        return 1
    finally:
        persistent.close(failed=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(serve())
