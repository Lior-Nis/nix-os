#!/usr/bin/env python3
"""Add trusted per-call heartbeat attribution to Paperclip MCP mutations.

All ordinary traffic is proxied to one warmed instance of the exact official
package. When Hermes supplies a valid request-local Paperclip run ID, lifecycle
mutations are routed through a short-lived, offline official MCP process
carrying that ID. Checkout and user-question interactions require that trusted
context; issue creation intentionally retains official no-run behavior for
Telegram commitments. The official schemas remain unchanged.
One additional fixed founder-decision tool is appended locally; it has no
generic API, credential, or caller-selected routing surface.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import re
import select
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paperclip_question_delivery import (
    human_only_question_api_arguments,
    notify_question_created,
)


PACKAGE = "@paperclipai/mcp-server@2026.916.1"
PERSISTENT_UPSTREAM_COMMAND = ("npx", "-y", PACKAGE)
SCOPED_UPSTREAM_COMMAND = ("npx", "-y", "--offline", PACKAGE)
RUN_SCOPED_TOOLS = {
    "paperclipCreateIssue",
    "paperclipCheckoutIssue",
    "paperclipUpdateIssue",
    "paperclipAddComment",
    "paperclipAskUserQuestions",
}
REQUIRED_RUN_SCOPED_TOOLS = {
    "paperclipCheckoutIssue",
    "paperclipAskUserQuestions",
}
MUTATION_TOOLS = {
    "paperclipCreateIssue",
    "paperclipCheckoutIssue",
    "paperclipUpdateIssue",
    "paperclipAddComment",
    "paperclipAskUserQuestions",
}
RUN_ID_META_KEY = "com.paperclip/run-id"
INTERNAL_API_TOOL = "paperclipApiRequest"
FOUNDER_DECISION_TOOL = "nixResolveFounderDecision"
FOUNDER_CONTEXT_META_KEYS = {
    "platform": "com.nix/hermes-platform",
    "chat_type": "com.nix/hermes-chat-type",
    "chat_id": "com.nix/hermes-chat-id",
    "user_id": "com.nix/hermes-user-id",
    "message_id": "com.nix/hermes-message-id",
}
RESERVED_META_KEYS = {RUN_ID_META_KEY, *FOUNDER_CONTEXT_META_KEYS.values()}
FOUNDER_DECISION_SCHEMA = {
    "name": FOUNDER_DECISION_TOOL,
    "description": (
        "Record Lior's explicit answer to one pending founder decision and resume "
        "only its server-verified originating employee. Available only in Lior's "
        "configured Telegram direct-message turn."
    ),
    "inputSchema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "issueId": {"type": "string", "format": "uuid"},
            "interactionId": {"type": "string", "format": "uuid"},
            "idempotencyKey": {
                "type": "string",
                "minLength": 8,
                "maxLength": 200,
                "pattern": "^[A-Za-z0-9._:-]+$",
            },
            "answers": {
                "type": "array",
                "minItems": 1,
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "questionId": {"type": "string", "minLength": 1, "maxLength": 160},
                        "optionIds": {
                            "type": "array",
                            "maxItems": 129,
                            "items": {"type": "string", "minLength": 1, "maxLength": 160},
                        },
                        "otherText": {"type": ["string", "null"], "maxLength": 100000},
                    },
                    "required": ["questionId", "optionIds"],
                },
            },
        },
        "required": ["issueId", "interactionId", "idempotencyKey", "answers"],
    },
}
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,200}$")
POSITIVE_INTEGER = re.compile(r"^[1-9][0-9]*$")

# Hermes' outer MCP call timeout remains the final guard. These shorter bounds
# ensure a wedged compatibility child reports a useful result first.
PERSISTENT_RPC_TIMEOUT_SECONDS = 60.0
PERSISTENT_STARTUP_TIMEOUT_SECONDS = 15.0
SCOPED_STARTUP_TIMEOUT_SECONDS = 15.0
SCOPED_RPC_TIMEOUT_SECONDS = 30.0
FOUNDER_RELAY_TIMEOUT_SECONDS = 20.0
FOUNDER_RELAY_MAX_RESPONSE_BYTES = 262_144
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
        # The official MCP child never participates in founder attestation.
        # Keep the relay secret in this fixed wrapper process only.
        environment.pop("NIX_FOUNDER_RELAY_SECRET", None)
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


def _invalid_params(request_id: Any, *, missing: bool = False) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": -32602,
            "message": (
                "Trusted Paperclip run metadata is required"
                if missing
                else "Trusted Paperclip run metadata is invalid"
            ),
        },
    }


def _tool_failure(request_id: Any, *, uncertain: bool) -> dict[str, Any]:
    if uncertain:
        payload = {
            "error": "outcome_uncertain",
            "message": (
                "The mutation was dispatched but no conclusive response was received. "
                "Read back the issue, child issues, comments, checkout, and pending "
                "interactions before retrying."
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


def _founder_denied(request_id: Any, *, invalid_arguments: bool = False) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": -32602,
            "message": (
                "Founder decision arguments are invalid"
                if invalid_arguments
                else "Trusted Lior Telegram DM context is required"
            ),
        },
    }


def _strip_reserved_metadata(request: dict[str, Any]) -> dict[str, Any]:
    params = request.get("params")
    metadata = params.get("_meta") if isinstance(params, dict) else None
    if not isinstance(metadata, dict) or not RESERVED_META_KEYS.intersection(metadata):
        return request
    forwarded = copy.deepcopy(request)
    forwarded_metadata = forwarded["params"]["_meta"]
    for key in RESERVED_META_KEYS:
        forwarded_metadata.pop(key, None)
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


def _valid_scoped_child_issue(request: dict[str, Any]) -> bool:
    params = request.get("params")
    arguments = params.get("arguments") if isinstance(params, dict) else None
    if not isinstance(arguments, dict):
        return False
    for key in ("parentId", "projectId"):
        value = arguments.get(key)
        if not isinstance(value, str) or UUID_PATTERN.fullmatch(value) is None:
            return False
    idempotency_key = arguments.get("idempotencyKey")
    return (
        isinstance(idempotency_key, str)
        and bool(idempotency_key.strip())
        and len(idempotency_key.strip()) <= 255
    )


def _founder_context(request: dict[str, Any]) -> dict[str, str] | None:
    params = request.get("params")
    metadata = params.get("_meta") if isinstance(params, dict) else None
    if not isinstance(metadata, dict) or RUN_ID_META_KEY in metadata:
        return None
    context = {
        name: metadata.get(key) for name, key in FOUNDER_CONTEXT_META_KEYS.items()
    }
    configured_user = os.environ.get("TELEGRAM_ALLOWED_USERS", "")
    configured_chat = os.environ.get("TELEGRAM_HOME_CHANNEL", "")
    if (
        context["platform"] != "telegram"
        or context["chat_type"] != "dm"
        or context["user_id"] != configured_user
        or context["chat_id"] != configured_chat
        or configured_user != configured_chat
        or POSITIVE_INTEGER.fullmatch(configured_user) is None
        or not isinstance(context["message_id"], str)
        or POSITIVE_INTEGER.fullmatch(context["message_id"]) is None
    ):
        return None
    return {name: str(value) for name, value in context.items()}


def _founder_arguments(request: dict[str, Any]) -> dict[str, Any] | None:
    params = request.get("params")
    arguments = params.get("arguments") if isinstance(params, dict) else None
    if not isinstance(arguments, dict) or set(arguments) != {
        "issueId", "interactionId", "idempotencyKey", "answers"
    }:
        return None
    issue_id = arguments.get("issueId")
    interaction_id = arguments.get("interactionId")
    idempotency_key = arguments.get("idempotencyKey")
    answers = arguments.get("answers")
    if (
        not isinstance(issue_id, str)
        or UUID_PATTERN.fullmatch(issue_id) is None
        or not isinstance(interaction_id, str)
        or UUID_PATTERN.fullmatch(interaction_id) is None
        or not isinstance(idempotency_key, str)
        or IDEMPOTENCY_PATTERN.fullmatch(idempotency_key) is None
        or not isinstance(answers, list)
        or not 1 <= len(answers) <= 20
    ):
        return None
    normalized: list[dict[str, Any]] = []
    question_ids: set[str] = set()
    for answer in answers:
        if not isinstance(answer, dict) or not {"questionId", "optionIds"} <= set(answer):
            return None
        if not set(answer) <= {"questionId", "optionIds", "otherText"}:
            return None
        question_id = answer.get("questionId")
        option_ids = answer.get("optionIds")
        other_text = answer.get("otherText")
        if (
            not isinstance(question_id, str)
            or question_id != question_id.strip()
            or not 1 <= len(question_id) <= 160
            or question_id in question_ids
            or not isinstance(option_ids, list)
            or len(option_ids) > 129
            or any(
                not isinstance(option_id, str)
                or option_id != option_id.strip()
                or not 1 <= len(option_id) <= 160
                for option_id in option_ids
            )
            or len(set(option_ids)) != len(option_ids)
            or (
                "otherText" in answer
                and other_text is not None
                and (
                    not isinstance(other_text, str)
                    or other_text != other_text.strip()
                    or len(other_text) > 100000
                )
            )
        ):
            return None
        question_ids.add(question_id)
        normalized_answer: dict[str, Any] = {
            "questionId": question_id,
            "optionIds": list(option_ids),
        }
        if "otherText" in answer:
            normalized_answer["otherText"] = other_text
        normalized.append(normalized_answer)
    return {
        "issueId": issue_id,
        "interactionId": interaction_id,
        "idempotencyKey": idempotency_key,
        "answers": normalized,
    }


def _founder_result(
    request_id: Any, payload: dict[str, Any], *, error: bool = False
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "content": [{
                "type": "text",
                "text": json.dumps(payload, separators=(",", ":")),
            }],
            **({"isError": True} if error else {}),
        },
    }


class _NoFounderRelayRedirects(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def _open_founder_relay(request: Request, timeout: float):
    # The target is an internal fixed Paperclip origin. Ignore ambient proxy
    # configuration and refuse redirects so credentials/attestation cannot be
    # forwarded to another host.
    return build_opener(ProxyHandler({}), _NoFounderRelayRedirects()).open(
        request, timeout=timeout
    )


def _founder_relay_call(
    request_id: Any, arguments: dict[str, Any], context: dict[str, str]
) -> dict[str, Any]:
    secret = os.environ.get("NIX_FOUNDER_RELAY_SECRET", "")
    api_key = os.environ.get("PAPERCLIP_API_KEY", "")
    api_url = os.environ.get("PAPERCLIP_API_URL", "")
    lior_user_id = os.environ.get("PAPERCLIP_LIOR_USER_ID", "")
    specialist_values = os.environ.get("NIX_PAPERCLIP_SPECIALIST_AGENT_IDS", "").split(",")
    specialist_ids = {value.strip() for value in specialist_values if value.strip()}
    chief_agent_id = os.environ.get("PAPERCLIP_AGENT_ID", "").strip()
    parsed = urlsplit(api_url)
    if (
        len(secret) < 32
        or not api_key
        or not lior_user_id
        or not specialist_ids
        or any(UUID_PATTERN.fullmatch(value) is None for value in specialist_ids)
        or len(specialist_ids) != len([value for value in specialist_values if value.strip()])
        or UUID_PATTERN.fullmatch(chief_agent_id) is None
        or parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        return _founder_result(
            request_id,
            {"error": "founder_relay_unavailable", "message": "The founder decision relay is not safely configured."},
            error=True,
        )

    issue_id = arguments["issueId"]
    interaction_id = arguments["interactionId"]
    idempotency_key = arguments["idempotencyKey"]
    path = f"/api/issues/{issue_id}/interactions/{interaction_id}/respond"
    body = json.dumps(
        {"answers": arguments["answers"]},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    timestamp = str(int(time.time()))
    canonical = "\n".join((
        "v1",
        timestamp,
        "POST",
        path,
        hashlib.sha256(body).hexdigest(),
        "telegram",
        "dm",
        context["user_id"],
        context["chat_id"],
        context["message_id"],
        idempotency_key,
    )).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Nix-Founder-Relay-Version": "1",
        "X-Nix-Founder-Relay-Timestamp": timestamp,
        "X-Nix-Founder-Relay-Idempotency-Key": idempotency_key,
        "X-Nix-Founder-Relay-Platform": "telegram",
        "X-Nix-Founder-Relay-Chat-Type": "dm",
        "X-Nix-Founder-Relay-User-Id": context["user_id"],
        "X-Nix-Founder-Relay-Chat-Id": context["chat_id"],
        "X-Nix-Founder-Relay-Message-Id": context["message_id"],
        "X-Nix-Founder-Relay-Signature": f"v1={signature}",
    }
    try:
        with _open_founder_relay(
            Request(api_url.rstrip("/") + path, data=body, headers=headers, method="POST"),
            FOUNDER_RELAY_TIMEOUT_SECONDS,
        ) as response:
            response_bytes = response.read(FOUNDER_RELAY_MAX_RESPONSE_BYTES + 1)
            if len(response_bytes) > FOUNDER_RELAY_MAX_RESPONSE_BYTES:
                raise ValueError("oversized relay response")
            response_payload = json.loads(response_bytes)
    except HTTPError as exc:
        # A gateway/server failure can happen after commit. Preserve the same
        # read-before-replay rule as a transport timeout. Other 4xx responses
        # are conclusive policy/input rejection. Never echo the response body.
        if exc.code >= 500 or exc.code == 408:
            return _founder_result(
                request_id,
                {
                    "error": "outcome_uncertain",
                    "message": (
                        "The relay may have recorded the decision. Read the interaction, then retry "
                        "only with the exact same interactionId, answers, and idempotencyKey."
                    ),
                },
                error=True,
            )
        return _founder_result(
            request_id,
            {"error": "founder_relay_rejected", "httpStatus": exc.code},
            error=True,
        )
    except (OSError, TimeoutError, URLError):
        return _founder_result(
            request_id,
            {
                "error": "outcome_uncertain",
                "message": (
                    "The relay may have recorded the decision. Read the interaction, then retry "
                    "only with the exact same interactionId, answers, and idempotencyKey."
                ),
            },
            error=True,
        )
    except (UnicodeError, ValueError, json.JSONDecodeError):
        return _founder_result(
            request_id,
            {"error": "invalid_founder_relay_response"},
            error=True,
        )

    relay = response_payload.get("nixFounderRelay") if isinstance(response_payload, dict) else None
    expected_relay = {
        "version": 1,
        "verified": True,
        "interactionId": interaction_id,
        "issueId": issue_id,
        "resolverUserId": lior_user_id,
        "sourceMessageId": context["message_id"],
        "idempotencyKey": idempotency_key,
    }
    if (
        not isinstance(response_payload, dict)
        or response_payload.get("id") != interaction_id
        or response_payload.get("issueId") != issue_id
        or response_payload.get("kind") != "ask_user_questions"
        or response_payload.get("status") != "answered"
        or response_payload.get("requestedResolverPolicy") != "human_only"
        or response_payload.get("effectiveResolverPolicy") != "human_only"
        or response_payload.get("addresseeUserId") != lior_user_id
        or not isinstance(relay, dict)
        or set(relay) != {*expected_relay, "originAgentId", "resumedAgentId", "replayed"}
        or any(relay.get(key) != value for key, value in expected_relay.items())
        or not isinstance(relay.get("replayed"), bool)
        or not isinstance(relay.get("originAgentId"), str)
        or UUID_PATTERN.fullmatch(relay["originAgentId"]) is None
        or relay.get("originAgentId") not in {*specialist_ids, chief_agent_id}
        or relay.get("resumedAgentId") != relay.get("originAgentId")
    ):
        return _founder_result(
            request_id,
            {"error": "invalid_founder_relay_response"},
            error=True,
        )
    return _founder_result(
        request_id,
        {
            "recorded": True,
            "issueId": issue_id,
            "interactionId": interaction_id,
            "status": "answered",
            "idempotencyKey": idempotency_key,
        },
    )


def _add_founder_tool(response: dict[str, Any]) -> None:
    result = response.get("result")
    tools = result.get("tools") if isinstance(result, dict) else None
    if not isinstance(tools, list):
        return
    if any(isinstance(tool, dict) and tool.get("name") == FOUNDER_DECISION_TOOL for tool in tools):
        raise UpstreamFailure
    tools.append(copy.deepcopy(FOUNDER_DECISION_SCHEMA))


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


def _deliver_question_notification(
    request: dict[str, Any], response: dict[str, Any]
) -> str | None:
    """Run the fixed Hermes delivery side effect and return a safe disposition."""
    try:
        state = notify_question_created(response, request)
    except Exception as exc:
        print(
            f"Paperclip question notification failed safely ({type(exc).__name__})",
            file=sys.stderr,
            flush=True,
        )
        return "failed"
    if state is not None:
        print(
            f"Paperclip question notification state={state}",
            file=sys.stderr,
            flush=True,
        )
    return state


def _surface_delivery_disposition(response: dict[str, Any], state: str | None) -> None:
    """Tell Chief how to recover without changing Paperclip interaction truth."""
    if state in (None, "delivered", "duplicate"):
        return
    result = response.get("result")
    content = result.get("content") if isinstance(result, dict) else None
    if not isinstance(content, list):
        return
    if state == "failed_not_sent":
        instruction = (
            "Nix notification status: Telegram was definitely not sent. After the "
            "delivery service is healthy, retry paperclipAskUserQuestions with the exact "
            "same issueId, payload, and idempotencyKey; do not create another interaction."
        )
    else:
        instruction = (
            "Nix notification status: Telegram delivery is not confirmed. Do not retry "
            "or create another interaction because delivery may have occurred; keep the "
            "Paperclip interaction pending and request operator recovery."
        )
    content.append({"type": "text", "text": instruction})


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
                if name == INTERNAL_API_TOOL:
                    _emit(_invalid_params(request.get("id")))
                    continue
                if name == FOUNDER_DECISION_TOOL:
                    founder_context = _founder_context(request)
                    if founder_context is None:
                        _emit(_founder_denied(request.get("id")))
                        continue
                    founder_arguments = _founder_arguments(request)
                    if founder_arguments is None:
                        _emit(_founder_denied(request.get("id"), invalid_arguments=True))
                        continue
                    _emit(
                        _founder_relay_call(
                            request.get("id"), founder_arguments, founder_context
                        )
                    )
                    continue
                persistent_mutation = name in MUTATION_TOOLS
                has_reserved, run_id = _explicit_run_metadata(request)
                if name in RUN_SCOPED_TOOLS:
                    if has_reserved:
                        if run_id is None:
                            _emit(_invalid_params(request.get("id")))
                            continue
                        if initialize_params is None:
                            _emit(_tool_failure(request.get("id"), uncertain=False))
                            continue
                        if name == "paperclipCreateIssue" and not _valid_scoped_child_issue(
                            request
                        ):
                            _emit(_invalid_params(request.get("id")))
                            continue
                        scoped_request = request
                        if name == "paperclipAskUserQuestions":
                            arguments = params.get("arguments")
                            if not isinstance(arguments, dict):
                                _emit(_invalid_params(request.get("id")))
                                continue
                            try:
                                internal_arguments = human_only_question_api_arguments(
                                    arguments, run_id
                                )
                            except (ValueError, RuntimeError):
                                _emit(_invalid_params(request.get("id")))
                                continue
                            scoped_request = copy.deepcopy(request)
                            scoped_request["params"]["name"] = INTERNAL_API_TOOL
                            scoped_request["params"]["arguments"] = internal_arguments
                        try:
                            response, preceding = _mutation_call(
                                scoped_request, initialize_params, run_id
                            )
                        except (BrokenPipeError, OSError, UpstreamFailure, ValueError) as exc:
                            uncertain = not isinstance(exc, UpstreamFailure) or exc.dispatched
                            response = _tool_failure(
                                request.get("id"), uncertain=uncertain
                            )
                            preceding = []
                        if name == "paperclipAskUserQuestions":
                            delivery_state = _deliver_question_notification(request, response)
                            _surface_delivery_disposition(response, delivery_state)
                        for message in preceding:
                            _emit(message)
                        _emit(response)
                        continue
                    if name in REQUIRED_RUN_SCOPED_TOOLS:
                        _emit(_invalid_params(request.get("id"), missing=True))
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
            if method == "tools/list":
                try:
                    _add_founder_tool(response)
                except UpstreamFailure:
                    return 1
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
