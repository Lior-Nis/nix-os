#!/usr/bin/env python3
"""Exercise Nix run attribution through the real patched Hermes modules."""

from __future__ import annotations

import asyncio
from contextlib import nullcontext
from contextvars import ContextVar
import threading
from types import SimpleNamespace

from gateway.paperclip_run_context import (
    paperclip_request_metadata,
)
from gateway.platforms import api_server_runs as runs
from tools import mcp_tool_handlers as handlers


RUN_ONE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
RUN_TWO = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


class RecordingSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name: str, **kwargs):
        self.calls.append((name, kwargs))
        return SimpleNamespace(
            content=[SimpleNamespace(text="ok")],
            is_error=False,
            structured_content=None,
            meta=None,
        )


class RecordingServer:
    def __init__(self) -> None:
        self.session = RecordingSession()
        self._rpc_lock = asyncio.Lock()
        self._pending_call_context = None


class IdempotencyStore:
    def __init__(self) -> None:
        self.records = {}

    def lookup(self, *_args, **_kwargs):
        return "missing", None

    def reserve(self, _scope, key, _fingerprint, run_id, status, **_kwargs):
        record = {"run_id": run_id, "status": status}
        self.records[key] = record
        return "created", record

    def update_status(self, *_args, **_kwargs) -> None:
        pass


class Listener:
    _set_run_status = runs._set_run_status
    _release_run_owner_if_forgotten = runs._release_run_owner_if_forgotten

    def __init__(self, server_name: str, barrier: threading.Barrier | None) -> None:
        self.server_name = server_name
        self.barrier = barrier
        self.agents: list[Agent] = []
        self._run_idempotency_store = IdempotencyStore()
        self._run_owner_pid = 1
        self._run_owner_started = 1
        self._run_idempotency_ids = set()
        self._run_stream_subscribers = set()
        self._stopping_run_ids = set()
        self._run_owners = {}
        self._run_streams = {}
        self._run_streams_created = {}
        self._active_run_agents = {}
        self._active_run_tasks = {}
        self._run_statuses = {}
        self._run_approval_sessions = {}
        self._background_tasks = set()
        self._response_store = SimpleNamespace(get=lambda _key: None)
        self._model_name = "contract-model"

    _profile_scope = staticmethod(lambda _profile: nullcontext())
    _bind_api_server_session = staticmethod(lambda **_kwargs: None)
    _bind_declared_conversation = staticmethod(lambda *_args: None)
    _room_grant_token = staticmethod(lambda _request: None)
    _expected_api_key = staticmethod(lambda: "authenticated-contract-key")
    _parse_session_key_header = staticmethod(lambda _request: (None, None))
    _resolve_route = staticmethod(lambda _model: None)
    _request_route_conflict_error = staticmethod(lambda **_kwargs: None)
    _concurrency_limited_response = staticmethod(lambda: None)
    _activate_admitted_request = staticmethod(lambda: None)
    _declared_conversation_session = staticmethod(lambda key: key)

    async def _normalize_room_dispatch(self, _request, body):
        return body, None

    def _run_idempotency_scope(self, request):
        return runs._run_idempotency_scope(self, request, _api_server=ApiServer())

    def _make_run_event_callback(self, run_id, loop):
        return runs._make_run_event_callback(
            self, run_id, loop, _api_server=ApiServer()
        )

    async def _conversation_history_for_session(self, _session_id):
        return []

    def _create_agent(self, **_kwargs):
        agent = Agent(self.server_name, self.barrier)
        self.agents.append(agent)
        return agent


class ApiServer:
    _api_request_profile = ContextVar("contract_profile", default=None)
    _api_request_browser_control_principal = ContextVar("contract_principal", default=None)
    _api_request_browser_control_transport_family = ContextVar("contract_transport", default=None)
    _openai_error = RuntimeError
    _ProviderAuthResolutionError = RuntimeError
    _request_turn_author = staticmethod(lambda _body: None)
    _request_agent_overrides = staticmethod(lambda _body, virtual_model: {})
    _publish_turn_process_ownership = staticmethod(lambda *_args: None)
    _clear_turn_process_ownership = staticmethod(lambda *_args: None)
    _redact_api_error_text = staticmethod(lambda value: str(value))
    redact_sensitive_text = staticmethod(lambda value, force=False: str(value))


class Agent:
    session_prompt_tokens = 0
    session_completion_tokens = 0
    session_total_tokens = 0

    def __init__(self, server_name: str, barrier: threading.Barrier | None) -> None:
        self.server_name = server_name
        self.barrier = barrier
        self.server = RecordingServer()

    def run_conversation(self, **_kwargs):
        if self.barrier is not None:
            self.barrier.wait(timeout=10)
        thread_state.server = self.server
        handler = handlers._make_tool_handler(self.server_name, "contractTool", 5)
        result = handler({"value": "fixture"})
        assert '"result": "ok"' in result
        return {"final_response": "ok"}


thread_state = threading.local()


class Request:
    path = "/v1/runs"

    def __init__(self, raw_id: object) -> None:
        self.headers = {}
        if raw_id is not None:
            self.headers["Idempotency-Key"] = raw_id

    async def json(self):
        return {"input": "test"}

    def get(self, _key, default=None):
        return default


async def admit(raw_id: object, server_name: str, barrier: threading.Barrier | None = None):
    listener = Listener(server_name, barrier)
    response = await runs._handle_runs(listener, Request(raw_id), _api_server=ApiServer())
    assert response.status == 202
    tasks = list(listener._background_tasks)
    assert len(tasks) == 1
    await asyncio.gather(*tasks)
    assert len(listener.agents) == 1
    calls = listener.agents[0].server.session.calls
    assert len(calls) == 1
    return calls[0][1]


def main() -> None:
    original_acquire = handlers._acquire_call_server
    original_dispatch = handlers._dispatch
    original_trust = handlers._trust_gate_check
    original_breaker = handlers._check_circuit_breaker

    def acquire(_server_name: str, _timeout: float):
        return thread_state.server, None

    def dispatch(_server_name, _server, _op, call, _timeout, _recoverers,
                 _on_final_failure, record_outcome=False):
        del record_outcome
        return asyncio.run(call())

    handlers._acquire_call_server = acquire
    handlers._dispatch = dispatch
    handlers._trust_gate_check = lambda *_args: None
    handlers._check_circuit_breaker = lambda *_args: None
    try:
        canonical = asyncio.run(admit(RUN_ONE, "paperclip"))
        assert canonical["meta"] == {"com.paperclip/run-id": RUN_ONE}

        for invalid in (None, "", "not-a-uuid", RUN_ONE.upper()):
            invalid_result = asyncio.run(admit(invalid, "paperclip"))
            assert "meta" not in invalid_result, (invalid, invalid_result)
        assert "meta" not in asyncio.run(admit(RUN_ONE, "github"))

        barrier = threading.Barrier(2)
        async def concurrent_runs():
            return await asyncio.gather(
                admit(RUN_ONE, "paperclip", barrier),
                admit(RUN_TWO, "paperclip", barrier),
            )

        first, second = asyncio.run(concurrent_runs())
        assert first["meta"] == {"com.paperclip/run-id": RUN_ONE}
        assert second["meta"] == {"com.paperclip/run-id": RUN_TWO}
    finally:
        handlers._acquire_call_server = original_acquire
        handlers._dispatch = original_dispatch
        handlers._trust_gate_check = original_trust
        handlers._check_circuit_breaker = original_breaker

    print("Pinned Hermes run-attribution integration passed.")


if __name__ == "__main__":
    main()
