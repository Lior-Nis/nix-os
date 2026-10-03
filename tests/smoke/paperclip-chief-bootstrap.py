#!/usr/bin/env python3
from __future__ import annotations

import copy
import contextlib
import http.server
import importlib.machinery
import importlib.util
import io
import json
import os
import pathlib
import tempfile
import threading
import urllib.parse
from types import SimpleNamespace


REPO = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_loader(
    "nix_paperclip_chief_bootstrap",
    importlib.machinery.SourceFileLoader(
        "nix_paperclip_chief_bootstrap", str(REPO / "scripts/bootstrap-paperclip-chief")
    ),
)
assert spec and spec.loader
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class State:
    def __init__(self) -> None:
        self.agents: list[dict] = []
        self.goals: list[dict] = []
        self.projects: list[dict] = []
        self.keys: dict[str, list[dict]] = {}
        self.requests: list[tuple[str, str, dict | None]] = []
        self.revoked: list[str] = []
        self.challenge_count = 0
        self.board_tokens: set[str] = set()
        self.fail_temp_patch_once = False
        self.invites: list[dict] = []
        self.joins: list[dict] = []
        self.secret_values: set[str] = set()
        self.auth_user_id = "lior-user"
        self.fail_revoke_detail: str | None = None
        self.fail_accept_detail: str | None = None
        self.malformed_recovery_key = False
        self.fail_key_delete_once = False
        self.accept_override: dict | None = None

    def reset_paperclip(self) -> None:
        self.agents = []
        self.goals = []
        self.projects = []
        self.keys = {}
        self.requests = []
        self.revoked = []
        self.challenge_count = 0
        self.board_tokens = set()
        self.fail_temp_patch_once = False
        self.invites = []
        self.joins = []
        self.secret_values = set()
        self.auth_user_id = "lior-user"
        self.fail_revoke_detail = None
        self.fail_accept_detail = None
        self.malformed_recovery_key = False
        self.fail_key_delete_once = False
        self.accept_override = None


state = State()


def response(handler: http.server.BaseHTTPRequestHandler, code: int, value: object) -> None:
    body = json.dumps(value).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:
        pass

    def body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def record(self, payload: dict | None = None) -> None:
        state.requests.append((self.command, urllib.parse.urlparse(self.path).path, payload))

    def do_GET(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        self.record()
        if path == "/api/cli-auth/me":
            token = self.headers.get("Authorization", "").removeprefix("Bearer ")
            if token not in state.board_tokens or token in state.revoked:
                response(self, 401, {"error": "unauthorized"})
                return
            response(
                self,
                200,
                {
                    "source": "board_key",
                    "userId": state.auth_user_id,
                    "keyId": f"key-{token[-4:]}",
                    "companyIds": ["company-1"],
                    "memberships": [
                        {
                            "companyId": "company-1",
                            "status": "active",
                            "membershipRole": "owner",
                        }
                    ],
                },
            )
            return
        if path.startswith("/api/cli-auth/challenges/challenge-"):
            response(
                self,
                200,
                {"status": "approved", "approvedByUser": {"id": state.auth_user_id}},
            )
            return
        if path == "/api/companies/company-1/agents":
            response(self, 200, copy.deepcopy(state.agents))
            return
        if path == "/api/companies/company-1/goals":
            response(self, 200, copy.deepcopy(state.goals))
            return
        if path == "/api/companies/company-1/projects":
            response(self, 200, copy.deepcopy(state.projects))
            return
        if path == "/api/companies/company-1/invites":
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            wanted = query.get("state", [None])[0]
            offset = int(query.get("offset", ["0"])[0])
            limit = int(query.get("limit", ["100"])[0])
            matching = [item for item in state.invites if wanted is None or item.get("state") == wanted]
            page = matching[offset : offset + limit]
            next_offset = offset + limit if offset + limit < len(matching) else None
            response(self, 200, {"invites": copy.deepcopy(page), "nextOffset": next_offset})
            return
        if path == "/api/companies/company-1/join-requests":
            response(
                self,
                200,
                [{key: value for key, value in copy.deepcopy(item).items() if key != "claimSecret"} for item in state.joins],
            )
            return
        if path.startswith("/api/agents/") and path.endswith("/keys"):
            agent_id = path.split("/")[3]
            response(self, 200, copy.deepcopy(state.keys.get(agent_id, [])))
            return
        if path.startswith("/api/agents/"):
            agent_id = path.split("/")[3]
            agent = next((item for item in state.agents if item["id"] == agent_id), None)
            response(self, 200 if agent else 404, copy.deepcopy(agent) if agent else {"error": "not found"})
            return
        response(self, 404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        payload = self.body()
        self.record(payload)
        if path == "/api/cli-auth/challenges":
            state.challenge_count += 1
            suffix = str(state.challenge_count)
            board_token = "pcp_board_" + suffix.rjust(48, "0")
            state.board_tokens.add(board_token)
            response(
                self,
                201,
                {
                    "id": f"challenge-{suffix}",
                    "token": f"challenge-secret-{suffix}",
                    "boardApiToken": board_token,
                    "approvalPath": f"/cli-auth/challenge-{suffix}?token=challenge-secret-{suffix}",
                    "approvalUrl": f"http://127.0.0.1:{self.server.server_address[1]}/cli-auth/challenge-{suffix}?token=challenge-secret-{suffix}",
                    "pollPath": f"/cli-auth/challenges/challenge-{suffix}",
                    "expiresAt": "2099-01-01T00:00:00.000Z",
                    "suggestedPollIntervalMs": 1,
                },
            )
            return
        if path == "/api/cli-auth/revoke-current":
            token = self.headers.get("Authorization", "").removeprefix("Bearer ")
            if token not in state.board_tokens or token in state.revoked:
                response(self, 401, {"error": "unauthorized"})
                return
            if state.fail_revoke_detail is not None:
                response(self, 500, {"error": state.fail_revoke_detail})
                return
            state.revoked.append(token)
            response(self, 200, {"revoked": True})
            return
        if path == "/api/companies/company-1/invites":
            invite_number = len(state.invites) + 1
            token = f"pcp_invite_fixture_secret_{invite_number}"
            state.secret_values.add(token)
            invite = {
                "id": f"invite-{invite_number}",
                "companyId": "company-1",
                "allowedJoinTypes": payload.get("allowedJoinTypes"),
                "inviteMessage": payload.get("agentMessage"),
                "state": "active",
                "token": token,
            }
            state.invites.append(invite)
            response(self, 201, copy.deepcopy(invite))
            return
        if path.startswith("/api/invites/pcp_invite_") and path.endswith("/accept"):
            token = path.removeprefix("/api/invites/").removesuffix("/accept")
            if state.fail_accept_detail is not None:
                response(self, 400, {"error": state.fail_accept_detail})
                return
            invite = next((item for item in state.invites if item.get("token") == token), None)
            if not invite or invite.get("state") != "active":
                response(self, 404, {"error": "not found"})
                return
            invite["state"] = "accepted"
            request_number = len(state.joins) + 1
            claim_secret = f"claim-secret-fixture-{request_number}"
            state.secret_values.add(claim_secret)
            join = {
                "id": f"11111111-1111-4111-8111-{request_number:012d}",
                "inviteId": invite["id"],
                "companyId": "company-1",
                "requestType": "agent",
                "agentName": payload.get("agentName"),
                "adapterType": payload.get("adapterType"),
                "agentDefaultsPayload": payload.get("agentDefaultsPayload"),
                "status": "pending_approval",
                "claimSecret": claim_secret,
                "createdAgentId": None,
            }
            state.joins.append(join)
            invite["relatedJoinRequestId"] = join["id"]
            accepted_response = copy.deepcopy(join)
            if state.accept_override:
                accepted_response.update(copy.deepcopy(state.accept_override))
            response(self, 202, accepted_response)
            return
        if path.startswith("/api/invites/") and path.endswith("/revoke"):
            invite_id = path.split("/")[3]
            invite = next((item for item in state.invites if item["id"] == invite_id), None)
            if not invite:
                response(self, 404, {"error": "not found"})
                return
            invite["state"] = "revoked"
            response(self, 200, copy.deepcopy(invite))
            return
        if path.startswith("/api/companies/company-1/join-requests/") and path.endswith("/reject"):
            request_id = path.split("/")[5]
            join = next((item for item in state.joins if item["id"] == request_id), None)
            if not join or join.get("status") != "pending_approval":
                response(self, 409, {"error": "not pending"})
                return
            join["status"] = "rejected"
            response(self, 200, copy.deepcopy(join))
            return
        if path.startswith("/api/companies/company-1/join-requests/") and path.endswith("/approve"):
            request_id = path.split("/")[5]
            join = next((item for item in state.joins if item["id"] == request_id), None)
            if not join or join.get("status") != "pending_approval":
                response(self, 409, {"error": "not pending"})
                return
            chief = {
                "id": "chief-agent",
                "name": "Chief of Staff",
                "role": "general",
                "reportsTo": "temp-agent",
                "status": "idle",
                "adapterType": "hermes_gateway",
                "adapterConfig": copy.deepcopy(join["agentDefaultsPayload"]),
                "runtimeConfig": {},
                "budgetMonthlyCents": 0,
                "permissions": {"canCreateAgents": False, "canCreateSkills": False},
                "metadata": None,
            }
            state.agents.append(chief)
            state.keys["chief-agent"] = []
            join["status"] = "approved"
            join["createdAgentId"] = "chief-agent"
            response(self, 200, copy.deepcopy(join))
            return
        if path == "/api/agents/chief-agent/keys":
            key_number = len(state.keys.get("chief-agent", [])) + 1
            token = f"pcp_recovery_fixture_secret_{key_number}"
            state.secret_values.add(token)
            key = {
                "id": f"recovery-key-{key_number}",
                "name": payload.get("name"),
                "scope": copy.deepcopy(payload.get("scope")),
                "responsibleUserId": "unexpected-user" if state.malformed_recovery_key else state.auth_user_id,
                "revokedAt": None,
                "token": token,
            }
            state.keys.setdefault("chief-agent", []).append({key: value for key, value in key.items() if key != "token"})
            response(self, 201, key)
            return
        if path == "/api/companies/company-1/goals":
            goal = {"id": "goal-1", **copy.deepcopy(payload)}
            state.goals.append(goal)
            response(self, 201, copy.deepcopy(goal))
            return
        if path == "/api/companies/company-1/projects":
            project = {"id": "project-1", "archivedAt": None, **copy.deepcopy(payload)}
            state.projects.append(project)
            response(self, 201, copy.deepcopy(project))
            return
        if path == "/api/companies/company-1/agent-hires":
            agent = {
                "id": "temp-agent",
                "status": "pending_approval",
                "spentMonthlyCents": 0,
                **copy.deepcopy(payload),
            }
            state.agents.append(agent)
            state.keys["temp-agent"] = []
            response(self, 201, {"agent": copy.deepcopy(agent), "approval": {"id": "approval-1"}})
            return
        if path == "/api/agents/temp-agent/approve":
            temp = next(item for item in state.agents if item["id"] == "temp-agent")
            temp["status"] = "idle"
            response(self, 200, copy.deepcopy(temp))
            return
        if path == "/api/agents/temp-agent/pause":
            temp = next(item for item in state.agents if item["id"] == "temp-agent")
            temp["status"] = "paused"
            response(self, 200, copy.deepcopy(temp))
            return
        response(self, 404, {"error": "not found"})

    def do_DELETE(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        self.record()
        if path.startswith("/api/agents/chief-agent/keys/"):
            key_id = path.rsplit("/", 1)[-1]
            key = next((item for item in state.keys.get("chief-agent", []) if item["id"] == key_id), None)
            if not key:
                response(self, 404, {"error": "not found"})
                return
            if state.fail_key_delete_once:
                state.fail_key_delete_once = False
                response(self, 500, {"error": "injected key delete interruption"})
                return
            key["revokedAt"] = "2026-10-03T00:00:00.000Z"
            response(self, 200, copy.deepcopy(key))
            return
        response(self, 404, {"error": "not found"})

    def do_PATCH(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        payload = self.body()
        self.record(payload)
        if path == "/api/agents/temp-agent" and state.fail_temp_patch_once:
            state.fail_temp_patch_once = False
            response(self, 500, {"error": "injected interrupted finalization"})
            return
        if path == "/api/projects/project-1":
            state.projects[0].update(payload)
            response(self, 200, copy.deepcopy(state.projects[0]))
            return
        if path.startswith("/api/agents/"):
            parts = path.split("/")
            agent_id = parts[3]
            agent = next((item for item in state.agents if item["id"] == agent_id), None)
            if not agent:
                response(self, 404, {"error": "not found"})
                return
            if len(parts) > 4 and parts[4] == "permissions":
                agent["permissions"] = {
                    "canCreateAgents": payload["canCreateAgents"],
                    "canCreateSkills": payload.get("canCreateSkills", True),
                    "canAssignTasks": payload["canAssignTasks"],
                }
            else:
                agent.update(payload)
            response(self, 200, copy.deepcopy(agent))
            return
        response(self, 404, {"error": "not found"})

class InjectedCrash(BaseException):
    pass


class FakeOperator:
    def __init__(self) -> None:
        self.credential_present = False
        self.company_id: str | None = None
        self.agent_id: str | None = None
        self.receipt: dict | None = None
        self.marker: dict | None = None
        self.stage: dict | None = None
        self.inject_after_stage = False
        self.inject_after_approve = False
        self.inject_claim_after_persist = False
        self.inject_consumed_before_key = False
        self.inject_response_loss = False
        self.install_wrong_identity = False
        self.inject_install_after_persist = False
        self.inject_install_after_receipt = False
        self.inject_install_response_loss = False
        self.commands: list[list[str]] = []
        self.verify_count = 0

    def __call__(self, command: list[str], *, input_text: str | None = None, label: str) -> str:
        self.commands.append(command)
        if command[0].endswith("scripts/configure-hermes"):
            self.verify_count += 1
            return "verified\n"
        if "/opt/nix/claim-agent.py" in command:
            action = command[-1]
            if action == "preflight":
                return "preflight passed\n"
            if action == "status":
                return json.dumps(
                    {
                        "credentialPresent": self.credential_present,
                        "companyId": self.company_id,
                        "agentId": self.agent_id,
                        "receipt": self.receipt,
                        "marker": self.marker,
                        "stage": (
                            None
                            if self.stage is None
                            else {
                                "requestId": self.stage["id"],
                                "companyId": self.stage["companyId"],
                            }
                        ),
                    }
                )
            payload = json.loads(input_text or "{}")
            if action == "stage":
                self.stage = copy.deepcopy(payload)
                if self.inject_after_stage:
                    self.inject_after_stage = False
                    raise InjectedCrash("injected after staged claim")
                return json.dumps(
                    {"requestId": payload["id"], "companyId": payload["companyId"]}
                )
            if action == "resume":
                assert self.stage is not None
                if self.inject_after_approve:
                    self.inject_after_approve = False
                    raise InjectedCrash("injected after join approval")
                if self.inject_consumed_before_key:
                    self.inject_consumed_before_key = False
                    raise bootstrap.BootstrapError("injected consumed claim without key")
                payload = self.stage
                self.credential_present = True
                self.company_id = payload["companyId"]
                self.agent_id = "chief-agent"
                active = [item for item in state.keys.get("chief-agent", []) if not item.get("revokedAt")]
                if not active:
                    state.keys.setdefault("chief-agent", []).append(
                        {
                            "id": "chief-key",
                            "name": "initial-join-key",
                            "scope": {"kind": "standard"},
                            "responsibleUserId": state.auth_user_id,
                            "revokedAt": None,
                        }
                    )
                if self.inject_claim_after_persist:
                    self.inject_claim_after_persist = False
                    self.marker = {"requestId": payload["id"], "companyId": payload["companyId"]}
                    raise InjectedCrash("injected after durable credential")
                self.receipt = {
                    "requestId": payload["id"],
                    "companyId": payload["companyId"],
                    "agentId": self.agent_id,
                    "keyId": active[0]["id"] if active else "chief-key",
                }
                self.marker = None
                self.stage = None
                if self.inject_response_loss:
                    self.inject_response_loss = False
                    raise bootstrap.BootstrapError("injected lost successful claim response")
                return json.dumps(
                    {"companyId": self.company_id, "agentId": self.agent_id, "recovered": False}
                )
            if action == "install":
                self.marker = {
                    "kind": "replacement-key-install",
                    "requestId": payload["requestId"],
                    "companyId": payload["companyId"],
                    "agentId": payload["agentId"],
                    "keyId": payload["keyId"],
                }
                if self.install_wrong_identity:
                    raise bootstrap.BootstrapError("persisted Paperclip credential resolved to an unexpected identity")
                self.credential_present = True
                self.company_id = payload["companyId"]
                self.agent_id = payload["agentId"]
                if self.inject_install_after_persist:
                    self.inject_install_after_persist = False
                    raise bootstrap.BootstrapError("injected replacement crash after credential persistence")
                self.receipt = {
                    "requestId": payload["requestId"],
                    "companyId": payload["companyId"],
                    "agentId": payload["agentId"],
                    "keyId": payload["keyId"],
                }
                if self.inject_install_after_receipt:
                    self.inject_install_after_receipt = False
                    raise bootstrap.BootstrapError("injected replacement crash after receipt persistence")
                self.marker = None
                self.stage = None
                if self.inject_install_response_loss:
                    self.inject_install_response_loss = False
                    raise bootstrap.BootstrapError("injected lost replacement install response")
                return json.dumps(
                    {"companyId": self.company_id, "agentId": self.agent_id, "recovered": True}
                )
            if action == "recover":
                assert self.credential_present and self.marker
                assert self.marker["requestId"] == payload["id"]
                assert self.marker["companyId"] == payload["companyId"]
                self.receipt = {
                    "requestId": payload["id"],
                    "companyId": payload["companyId"],
                    "agentId": self.agent_id,
                    **({"keyId": self.marker["keyId"]} if self.marker.get("keyId") else {}),
                }
                self.marker = None
                self.stage = None
                return json.dumps(
                    {"companyId": self.company_id, "agentId": self.agent_id, "recovered": True}
                )
            if action == "discard-install":
                assert not self.credential_present
                assert self.marker == payload
                key_id = self.marker["keyId"]
                request_id = self.marker["requestId"]
                self.marker = None
                return json.dumps({"requestId": request_id, "keyId": key_id, "discarded": True})
        if "restart" in command and "hermes" in command:
            return ""
        raise AssertionError(f"unexpected operator command for {label}: {command}")


def write_config(tmp: pathlib.Path, port: int, lior_user_id: str = "lior-user") -> pathlib.Path:
    hermes_env = tmp / "hermes.env"
    api_key = "api-server-key-" + "x" * 64
    hermes_env.write_text(f"API_SERVER_KEY={api_key}\n", encoding="utf-8")
    hermes_env.chmod(0o600)
    state.secret_values.add(api_key)
    config = tmp / "deployment.env"
    config.write_text(
        f"PAPERCLIP_PUBLIC_URL=http://127.0.0.1:{port}\n"
        f"PAPERCLIP_LIOR_USER_ID={lior_user_id}\n"
        f"HERMES_ENV_FILE={hermes_env}\n",
        encoding="utf-8",
    )
    return config


def run_helper(
    config: pathlib.Path,
    operator: FakeOperator,
    action: str = "converge",
    *,
    expect_ok: bool,
) -> SimpleNamespace:
    bootstrap.run_operator_command = operator
    stdout = io.StringIO()
    stderr = io.StringIO()
    arguments = [action, "company-1"]
    if action == "finalize":
        arguments.append("chief-agent")
    arguments.extend(["--config", str(config)])
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        returncode = bootstrap.main(arguments)
    result = SimpleNamespace(returncode=returncode, stdout=stdout.getvalue(), stderr=stderr.getvalue())
    if (result.returncode == 0) != expect_ok:
        raise AssertionError(f"unexpected helper result: {result.returncode}\n{result.stdout}\n{result.stderr}")
    for secret in [*state.board_tokens, *state.secret_values]:
        if secret in result.stdout or secret in result.stderr:
            raise AssertionError("bootstrap secret leaked to helper output")
        if any(secret in argument for command in operator.commands for argument in command):
            raise AssertionError("bootstrap secret crossed a process argument")
    return result


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="nix-os-chief-bootstrap-") as directory:
        tmp = pathlib.Path(directory)
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]
        try:
            for override in (
                {"inviteId": "different-invite"},
                {"requestType": "user", "agentName": "Not Chief", "adapterType": "process"},
            ):
                state.reset_paperclip()
                state.accept_override = override
                config = write_config(tmp, port)
                operator = FakeOperator()
                malformed_accept = run_helper(config, operator, expect_ok=False)
                assert "invalid pending Chief join" in malformed_accept.stderr
                assert operator.stage is None
                assert state.joins[0]["status"] == "pending_approval"
                assert not any(item.get("id") == "chief-agent" for item in state.agents)

            state.reset_paperclip()
            config = write_config(tmp, port)
            operator = FakeOperator()
            final = run_helper(config, operator, expect_ok=True)
            assert "sole root CEO" in final.stdout
            assert "Approved goal: goal-1" in final.stdout
            assert "Approved project: project-1" in final.stdout
            assert len(state.goals) == 1 and len(state.projects) == 1
            assert state.projects[0]["idempotencyKey"] == "nix-business-os-v0-approved-v1"
            assert len(state.invites) == 1 and len(state.joins) == 1
            temp = next(item for item in state.agents if item["id"] == "temp-agent")
            assert temp["role"] == "general" and temp["reportsTo"] == "chief-agent" and temp["status"] == "paused"
            assert temp["permissions"]["canAssignTasks"] is False
            assert operator.verify_count == 1
            run_helper(config, operator, expect_ok=True)
            assert len(state.invites) == 1 and len(state.joins) == 1
            assert state.challenge_count == 2 and len(state.revoked) == 2
            assert operator.stage is None

            state.reset_paperclip()
            config = write_config(tmp, port)
            operator = FakeOperator()
            operator.inject_after_stage = True
            after_stage = run_helper(config, operator, expect_ok=False)
            assert "injected after staged claim" in after_stage.stderr
            assert operator.stage and state.joins[0]["status"] == "pending_approval"
            assert not state.keys.get("chief-agent")
            run_helper(config, operator, expect_ok=True)
            assert operator.stage is None and operator.receipt is not None

            state.reset_paperclip()
            config = write_config(tmp, port)
            operator = FakeOperator()
            operator.inject_after_approve = True
            after_approve = run_helper(config, operator, expect_ok=False)
            assert "injected after join approval" in after_approve.stderr
            assert operator.stage and state.joins[0]["status"] == "approved"
            assert not [item for item in state.keys["chief-agent"] if not item.get("revokedAt")]
            run_helper(config, operator, expect_ok=True)
            assert operator.stage is None and operator.receipt is not None

            state.reset_paperclip()
            config = write_config(tmp, port)
            operator = FakeOperator()
            operator.inject_after_approve = True
            run_helper(config, operator, expect_ok=False)
            operator.stage = None
            recovered_key = run_helper(config, operator, expect_ok=True)
            assert "sole root CEO" in recovered_key.stdout
            active_keys = [item for item in state.keys["chief-agent"] if not item.get("revokedAt")]
            assert len(active_keys) == 1 and active_keys[0]["name"] == "nix-chief-recovery"

            state.reset_paperclip()
            config = write_config(tmp, port)
            operator = FakeOperator()
            operator.inject_after_approve = True
            run_helper(config, operator, expect_ok=False)
            operator.stage = None
            state.malformed_recovery_key = True
            malformed_key = run_helper(config, operator, expect_ok=False)
            assert "invalid Chief recovery key" in malformed_key.stderr
            assert not [item for item in state.keys["chief-agent"] if not item.get("revokedAt")]

            state.reset_paperclip()
            config = write_config(tmp, port)
            operator = FakeOperator()
            operator.inject_after_approve = True
            run_helper(config, operator, expect_ok=False)
            operator.stage = None
            operator.install_wrong_identity = True
            bad_install = run_helper(config, operator, expect_ok=False)
            assert "unexpected identity" in bad_install.stderr
            assert not [item for item in state.keys["chief-agent"] if not item.get("revokedAt")]
            assert operator.marker is None and not operator.credential_present
            operator.install_wrong_identity = False
            recovered_after_failed_install = run_helper(config, operator, expect_ok=True)
            assert "sole root CEO" in recovered_after_failed_install.stdout
            assert len([item for item in state.keys["chief-agent"] if not item.get("revokedAt")]) == 1

            state.reset_paperclip()
            config = write_config(tmp, port)
            operator = FakeOperator()
            operator.inject_after_approve = True
            run_helper(config, operator, expect_ok=False)
            operator.stage = None
            operator.install_wrong_identity = True
            state.fail_key_delete_once = True
            interrupted_delete = run_helper(config, operator, expect_ok=False)
            assert "could not be revoked" in interrupted_delete.stderr
            assert operator.marker is None and not operator.credential_present
            assert len([item for item in state.keys["chief-agent"] if not item.get("revokedAt")]) == 1
            operator.install_wrong_identity = False
            rerun_after_delete = run_helper(config, operator, expect_ok=True)
            assert "sole root CEO" in rerun_after_delete.stdout
            assert len([item for item in state.keys["chief-agent"] if not item.get("revokedAt")]) == 1

            state.reset_paperclip()
            config = write_config(tmp, port)
            operator = FakeOperator()
            operator.inject_after_approve = True
            run_helper(config, operator, expect_ok=False)
            operator.stage = None
            crashed_key = {
                "id": "crashed-recovery-key",
                "name": "nix-chief-recovery",
                "scope": {"kind": "standard"},
                "responsibleUserId": state.auth_user_id,
                "revokedAt": None,
            }
            state.keys["chief-agent"].append(crashed_key)
            operator.marker = {
                "kind": "replacement-key-install",
                "requestId": state.joins[0]["id"],
                "companyId": "company-1",
                "agentId": "chief-agent",
                "keyId": crashed_key["id"],
            }
            hard_crash_rerun = run_helper(config, operator, expect_ok=True)
            assert "sole root CEO" in hard_crash_rerun.stdout
            assert operator.marker is None and operator.receipt
            assert len([item for item in state.keys["chief-agent"] if not item.get("revokedAt")]) == 1

            for interruption in (
                "inject_install_after_persist",
                "inject_install_after_receipt",
                "inject_install_response_loss",
            ):
                state.reset_paperclip()
                config = write_config(tmp, port)
                operator = FakeOperator()
                operator.inject_after_approve = True
                run_helper(config, operator, expect_ok=False)
                operator.stage = None
                setattr(operator, interruption, True)
                recovered_install = run_helper(config, operator, expect_ok=True)
                assert "sole root CEO" in recovered_install.stdout
                active_keys = [
                    item for item in state.keys["chief-agent"] if not item.get("revokedAt")
                ]
                assert len(active_keys) == 1
                assert operator.credential_present and operator.receipt
                assert operator.receipt["keyId"] == active_keys[0]["id"]
                assert operator.marker is None and operator.stage is None

            state.reset_paperclip()
            config = write_config(tmp, port)
            operator = FakeOperator()
            operator.inject_response_loss = True
            run_helper(config, operator, expect_ok=True)
            assert operator.credential_present and operator.receipt and operator.stage is None
            active_keys = [item for item in state.keys["chief-agent"] if not item.get("revokedAt")]
            assert len(active_keys) == 1 and active_keys[0]["name"] == "initial-join-key"

            state.reset_paperclip()
            config = write_config(tmp, port)
            operator = FakeOperator()
            operator.inject_consumed_before_key = True
            run_helper(config, operator, expect_ok=True)
            active_keys = [item for item in state.keys["chief-agent"] if not item.get("revokedAt")]
            assert len(active_keys) == 1 and active_keys[0]["name"] == "nix-chief-recovery"

            state.reset_paperclip()
            config = write_config(tmp, port)
            operator = FakeOperator()
            operator.inject_claim_after_persist = True
            interrupted_claim = run_helper(config, operator, expect_ok=False)
            assert "injected after durable credential" in interrupted_claim.stderr
            assert operator.marker and operator.stage and operator.credential_present and operator.receipt is None
            state.fail_temp_patch_once = True
            interrupted_finalize = run_helper(config, operator, expect_ok=False)
            assert "PATCH /api/agents/temp-agent returned HTTP 500" in interrupted_finalize.stderr
            assert operator.marker is None and operator.receipt is not None
            chief = next(item for item in state.agents if item["id"] == "chief-agent")
            assert chief["role"] == "ceo" and chief["reportsTo"] is None
            run_helper(config, operator, expect_ok=True)
            temp = next(item for item in state.agents if item["id"] == "temp-agent")
            assert temp["status"] == "paused" and temp["reportsTo"] == "chief-agent"
            assert len(state.invites) == 1 and len(state.joins) == 1
            assert state.challenge_count == 3 and len(state.revoked) == 3

            state.reset_paperclip()
            config = write_config(tmp, port)
            operator = FakeOperator()
            unmarked_request = "22222222-2222-4222-8222-222222222222"
            state.invites = [
                {
                    "id": "unmarked-invite",
                    "allowedJoinTypes": "agent",
                    "inviteMessage": "some-other-flow",
                    "state": "accepted",
                    "relatedJoinRequestId": unmarked_request,
                }
            ]
            state.joins = [
                {
                    "id": unmarked_request,
                    "inviteId": "unmarked-invite",
                    "companyId": "company-1",
                    "requestType": "agent",
                    "agentName": "Chief of Staff",
                    "adapterType": "hermes_gateway",
                    "status": "pending_approval",
                    "createdAgentId": None,
                }
            ]
            uncorrelated = run_helper(config, operator, expect_ok=False)
            assert "not uniquely correlated" in uncorrelated.stderr
            assert state.joins[0]["status"] == "pending_approval"

            state.invites = [
                {
                    "id": f"accepted-{index}",
                    "allowedJoinTypes": "agent",
                    "inviteMessage": "fixture",
                    "state": "accepted",
                    "relatedJoinRequestId": f"request-{index}",
                }
                for index in range(205)
            ]
            paged = bootstrap.list_invites(
                bootstrap.Api(f"http://127.0.0.1:{port}"), "company-1", "accepted"
            )
            assert len(paged) == 205 and paged[-1]["id"] == "accepted-204"

            state.reset_paperclip()
            config = write_config(tmp, port, "placeholder-before-identify")
            operator = FakeOperator()
            identified = run_helper(config, operator, action="identify", expect_ok=True)
            assert "Lior Paperclip user ID: lior-user" in identified.stdout

            state.reset_paperclip()
            config = write_config(tmp, port, "different-user")
            operator = FakeOperator()
            wrong_identity = run_helper(config, operator, expect_ok=False)
            assert "pinned Lior" in wrong_identity.stderr
            assert len(state.revoked) == 1
            token = next(iter(state.board_tokens))
            assert bootstrap.Api(f"http://127.0.0.1:{port}", token).is_unauthorized("/api/cli-auth/me")

            state.reset_paperclip()
            config = write_config(tmp, port, "different-user")
            operator = FakeOperator()
            leaked = "pcp_claim_redact_fixture"
            state.secret_values.add(leaked)
            state.fail_revoke_detail = f"failed around {leaked}"
            revoke_failure = run_helper(config, operator, expect_ok=False)
            assert "key-0001" in revoke_failure.stderr
            assert leaked not in revoke_failure.stderr

            state.reset_paperclip()
            config = write_config(tmp, port)
            operator = FakeOperator()
            leaked = "pcp_invite_redact_fixture"
            state.secret_values.add(leaked)
            state.fail_accept_detail = f"invalid invite with {leaked}"
            redacted = run_helper(config, operator, expect_ok=False)
            assert "/api/invites/<redacted>/accept returned HTTP 400" in redacted.stderr
            assert leaked not in redacted.stderr

            state.reset_paperclip()
            config = write_config(tmp, port)
            operator = FakeOperator()
            state.agents = [{"id": "rogue", "name": "Unmarked existing agent"}]
            state.keys = {"rogue": []}
            failed = run_helper(config, operator, expect_ok=False)
            assert "refusing to invent topology" in failed.stderr
            assert len(state.revoked) == 1
        finally:
            server.shutdown()
            thread.join(timeout=5)

    print("Paperclip first-Chief bootstrap tests passed.")


if __name__ == "__main__":
    main()
