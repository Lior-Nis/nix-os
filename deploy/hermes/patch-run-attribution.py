#!/usr/bin/env python3
"""Apply Nix's version-locked Paperclip run-attribution patch to Hermes.

The pinned Hermes release has no request-local bridge between ``/v1/runs`` and
MCP calls.  This installer makes the smallest source change needed to carry an
authenticated, UUID-shaped idempotency key through the executor thread and add
it as MCP request metadata only for the server named ``paperclip``.

Every input and output file is hash locked.  A pristine pinned image is patched,
an already-patched image is accepted, and every other state fails closed.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import tempfile
from typing import Callable


API_SERVER_RUNS_SHA256 = "dd7303663f8062ece1a08b03b2010a7737500162c9b1e7a7f5e802b4b80504c0"
MCP_HANDLERS_SHA256 = "c4713aa289c7ca17b53c0ae53ceb6a276321f6d36e259084974e8b5738b6a4dd"

# Filled with the deterministic results of the transformations below.  These
# are deliberately independent of the source-image manifest check performed by
# Compose: both controls must agree before the gateway starts.
PATCHED_API_SERVER_RUNS_SHA256 = "d5dd305a29441134b5b2531541ea23901da1d23d058990cb38226f867ca2ed7f"
PATCHED_MCP_HANDLERS_SHA256 = "90b68aa75d4dc166d5bb827b99e6bb57cd5842d20a195846aa242513026b533a"

CONTEXT_MODULE = '''"""Request-local Paperclip heartbeat attribution for the Nix Hermes pin."""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Optional
import uuid


_paperclip_run_id: ContextVar[Optional[str]] = ContextVar(
    "nix_paperclip_run_id", default=None
)


def validated_paperclip_run_id(value: object) -> Optional[str]:
    """Return a canonical UUID or ``None`` without reflecting invalid input."""
    if not isinstance(value, str):
        return None
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, ValueError):
        return None
    canonical = str(parsed)
    return canonical if value == canonical else None


def bind_paperclip_run_id(value: object) -> Token:
    """Bind only a validated run id in the current execution context."""
    return _paperclip_run_id.set(validated_paperclip_run_id(value))


def reset_paperclip_run_id(token: Token) -> None:
    _paperclip_run_id.reset(token)


def paperclip_request_metadata(server_name: str) -> Optional[dict[str, str]]:
    """Metadata for the one trusted MCP server; all other lanes emit none."""
    run_id = _paperclip_run_id.get()
    if server_name != "paperclip" or run_id is None:
        return None
    return {"com.paperclip/run-id": run_id}
'''
CONTEXT_MODULE_SHA256 = hashlib.sha256(CONTEXT_MODULE.encode()).hexdigest()


def _replace_once(source: str, old: str, new: str, *, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"Hermes patch refused: expected one {label} anchor, found {count}")
    return source.replace(old, new, 1)


def patch_api_server_runs(source: str) -> str:
    source = _replace_once(
        source,
        "from gateway.platforms.api_server_run_idempotency import TERMINAL_STATUSES\n",
        "from gateway.platforms.api_server_run_idempotency import TERMINAL_STATUSES\n"
        "from gateway.paperclip_run_context import (\n"
        "    bind_paperclip_run_id, reset_paperclip_run_id, validated_paperclip_run_id)\n",
        label="api import",
    )
    source = _replace_once(
        source,
        "    browser_control_transport_family: Any\n"
        "    turn_author: Optional[Dict[str, Any]] = None  # memory-attribution label only; grants nothing\n",
        "    browser_control_transport_family: Any\n"
        "    paperclip_run_id: Optional[str]\n"
        "    turn_author: Optional[Dict[str, Any]] = None  # memory-attribution label only; grants nothing\n",
        label="run launch field",
    )
    source = _replace_once(
        source,
        "    idempotency_scope = idempotency_fingerprint = \"\"\n"
        "    if idempotency_key:\n",
        "    # Paperclip uses its heartbeat UUID as the idempotency key.  Generic\n"
        "    # Hermes idempotency keys retain their existing behavior but receive no\n"
        "    # Paperclip authority when they are absent or non-canonical UUIDs.\n"
        "    paperclip_run_id = validated_paperclip_run_id(idempotency_key)\n"
        "    idempotency_scope = idempotency_fingerprint = \"\"\n"
        "    if idempotency_key:\n",
        label="idempotency capture",
    )
    source = _replace_once(
        source,
        "        browser_control_transport_family=_api_server._api_request_browser_control_transport_family.get(),\n"
        "        turn_author=turn_author)\n",
        "        browser_control_transport_family=_api_server._api_request_browser_control_transport_family.get(),\n"
        "        paperclip_run_id=paperclip_run_id,\n"
        "        turn_author=turn_author)\n",
        label="run launch value",
    )
    source = _replace_once(
        source,
        "            # Contextvars, not process env: concurrent runs must not share identity.\n"
        "            resets.append((set_current_session_key(run.approval_session_key), reset_current_session_key))\n",
        "            # Contextvars, not process env: concurrent runs must not share identity.\n"
        "            resets.append((set_current_session_key(run.approval_session_key), reset_current_session_key))\n"
        "            resets.append((bind_paperclip_run_id(run.paperclip_run_id), reset_paperclip_run_id))\n",
        label="executor binding",
    )
    return source


def patch_mcp_handlers(source: str) -> str:
    source = _replace_once(
        source,
        "from tools.mcp_tool_errors import _is_auth_error, _is_session_expired_error\n",
        "from tools.mcp_tool_errors import _is_auth_error, _is_session_expired_error\n"
        "from gateway.paperclip_run_context import paperclip_request_metadata\n",
        label="mcp import",
    )
    source = _replace_once(
        source,
        "async def _call_tool_racing_stdio_death(server, server_name: str, tool_name: str, args: dict):\n",
        "async def _call_tool_racing_stdio_death(\n"
        "        server, server_name: str, tool_name: str, args: dict, *, request_meta=None):\n",
        label="mcp call signature",
    )
    source = _replace_once(
        source,
        "    _call_coro = server.session.call_tool(tool_name, arguments=args)\n",
        "    _call_kwargs = {\"arguments\": args}\n"
        "    if request_meta is not None:\n"
        "        _call_kwargs[\"meta\"] = request_meta\n"
        "    _call_coro = server.session.call_tool(tool_name, **_call_kwargs)\n",
        label="mcp metadata call",
    )
    source = _replace_once(
        source,
        "        server, error = _acquire_call_server(server_name, tool_timeout)\n"
        "        if server is None:\n"
        "            return error\n\n"
        "        async def _call():\n",
        "        server, error = _acquire_call_server(server_name, tool_timeout)\n"
        "        if server is None:\n"
        "            return error\n"
        "        # Read in the agent executor thread before scheduling onto Hermes'\n"
        "        # dedicated MCP loop, whose task context is intentionally separate.\n"
        "        request_meta = paperclip_request_metadata(server_name)\n\n"
        "        async def _call():\n",
        label="mcp metadata capture",
    )
    source = _replace_once(
        source,
        "                    result = await _call_tool_racing_stdio_death(server, server_name, tool_name, args)\n",
        "                    result = await _call_tool_racing_stdio_death(\n"
        "                        server, server_name, tool_name, args, request_meta=request_meta)\n",
        label="mcp metadata routing",
    )
    return source


@dataclass(frozen=True)
class PatchSpec:
    relative_path: str
    original_sha256: str
    patched_sha256: str
    transform: Callable[[str], str]


PATCH_SPECS = (
    PatchSpec(
        "gateway/platforms/api_server_runs.py",
        API_SERVER_RUNS_SHA256,
        PATCHED_API_SERVER_RUNS_SHA256,
        patch_api_server_runs,
    ),
    PatchSpec(
        "tools/mcp_tool_handlers.py",
        MCP_HANDLERS_SHA256,
        PATCHED_MCP_HANDLERS_SHA256,
        patch_mcp_handlers,
    ),
)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write(path: Path, data: bytes, mode: int) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def verify_patch(root: Path, specs: tuple[PatchSpec, ...] = PATCH_SPECS) -> None:
    """Verify that only the exact patched runtime is installed; never write."""
    module_path = root / "gateway/paperclip_run_context.py"
    if not module_path.is_file() or _digest(module_path.read_bytes()) != CONTEXT_MODULE_SHA256:
        raise RuntimeError("Hermes patch verification failed: run-context module mismatch")
    for spec in specs:
        path = root / spec.relative_path
        if not path.is_file() or _digest(path.read_bytes()) != spec.patched_sha256:
            raise RuntimeError(
                f"Hermes patch verification failed at {spec.relative_path}"
            )


def apply_patch(root: Path, specs: tuple[PatchSpec, ...] = PATCH_SPECS) -> None:
    """Validate all files, then atomically install each deterministic output."""
    pending: list[tuple[Path, bytes, int]] = []
    for spec in specs:
        path = root / spec.relative_path
        original = path.read_bytes()
        current_digest = _digest(original)
        if current_digest == spec.patched_sha256:
            continue
        if current_digest != spec.original_sha256:
            raise RuntimeError(
                f"Hermes patch refused: unsupported source at {spec.relative_path}"
            )
        patched = spec.transform(original.decode("utf-8")).encode("utf-8")
        if _digest(patched) != spec.patched_sha256:
            raise RuntimeError(
                f"Hermes patch refused: output mismatch at {spec.relative_path}"
            )
        pending.append((path, patched, path.stat().st_mode & 0o777))

    module_path = root / "gateway/paperclip_run_context.py"
    module_data = CONTEXT_MODULE.encode("utf-8")
    if module_path.exists() and _digest(module_path.read_bytes()) != CONTEXT_MODULE_SHA256:
        raise RuntimeError("Hermes patch refused: unexpected run-context module")

    if not module_path.exists():
        _atomic_write(module_path, module_data, 0o644)
    for path, data, mode in pending:
        _atomic_write(path, data, mode)

    # Verify the installed state after every invocation, including idempotent runs.
    verify_patch(root, specs)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/opt/hermes"))
    parser.add_argument(
        "--verify",
        action="store_true",
        help="verify exact installed hashes without modifying the runtime",
    )
    args = parser.parse_args()
    try:
        if args.verify:
            verify_patch(args.root)
        else:
            apply_patch(args.root)
    except (OSError, RuntimeError, UnicodeError) as exc:
        # Paths and stable reasons only: never source, request metadata, or env.
        print(str(exc), file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
