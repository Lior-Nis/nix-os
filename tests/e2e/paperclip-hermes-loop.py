#!/usr/bin/env python3
"""In-memory model of the Slice 2 Paperclip -> Hermes execution contract.

This is a fast, secret-free state-machine regression. It does not execute
either pinned upstream runtime and therefore is not Slice 2 acceptance
evidence; image-level and live acceptance checks cover those boundaries.
"""

from __future__ import annotations

import hashlib
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tarfile
import tempfile
import threading
import uuid


API_KEY = "fixture-hermes-api-key-" + ("a" * 48)
SECRET_CANARY = "must-not-appear-in-diagnostics"
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


def canonical_uuid() -> str:
    return str(uuid.uuid4())


def digest_json(value: object) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


class GatewayState:
    """Durable subset of the pinned Hermes Runs API behavior."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.behaviors: dict[str, str] = {}
        self.db = sqlite3.connect(path, check_same_thread=False)
        os.chmod(path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS runs (
                idempotency_key TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                hermes_run_id TEXT UNIQUE NOT NULL,
                issue_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                status TEXT NOT NULL,
                output TEXT,
                failure TEXT
            )"""
        )
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                history TEXT NOT NULL
            )"""
        )
        # A process restart must not leave an executing run looking healthy.
        self.db.execute(
            "UPDATE runs SET status='interrupted', "
            "failure='The gateway restarted before this run settled.' "
            "WHERE status NOT IN ('completed','failed','cancelled','interrupted')"
        )
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def create(self, key: str, session_header: str,
               body: dict[str, object]) -> tuple[int, dict[str, object], bool]:
        fingerprint = digest_json(body)
        with self.lock:
            prior = self.db.execute(
                "SELECT * FROM runs WHERE idempotency_key=?", (key,)
            ).fetchone()
            if prior is not None:
                if prior["fingerprint"] != fingerprint:
                    return 409, {"error": "idempotency_key_conflict"}, False
                return 202, self.admission(prior, replayed=True), True

            session_id = body.get("session_id")
            input_text = body.get("input")
            if set(body) != {"input", "session_id"}:
                return 400, {"error": "invalid_run"}, False
            if not all(isinstance(v, str) and v for v in (session_id, input_text)):
                return 400, {"error": "invalid_run"}, False
            if session_header != session_id:
                return 400, {"error": "session_scope_mismatch"}, False
            parts = session_id.split(":")
            if len(parts) != 7 or parts[0] != "paperclip" or parts[1::2] != ["company", "agent", "issue"]:
                return 400, {"error": "session_scope_mismatch"}, False
            issue_id = parts[-1]

            prior_session = self.db.execute(
                "SELECT history FROM sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            history = json.loads(prior_session["history"]) if prior_session else []
            history.append(input_text)
            self.db.execute(
                "INSERT OR REPLACE INTO sessions(session_id,history) VALUES (?,?)",
                (session_id, json.dumps(history, separators=(",", ":"))),
            )
            hermes_run_id = canonical_uuid()
            interrupt = self.behaviors.pop(key, "complete") == "interrupt"
            status = "started" if interrupt else "completed"
            output = None if interrupt else json.dumps(
                {"issueId": issue_id, "sessionId": session_id, "history": history},
                separators=(",", ":"),
                sort_keys=True,
            )
            self.db.execute(
                "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?)",
                (key, fingerprint, hermes_run_id, issue_id, session_id, status, output, None),
            )
            self.db.commit()
            row = self.db.execute(
                "SELECT * FROM runs WHERE idempotency_key=?", (key,)
            ).fetchone()
            assert row is not None
            return 202, self.admission(row, replayed=False), False

    def get(self, hermes_run_id: str) -> dict[str, object] | None:
        with self.lock:
            row = self.db.execute(
                "SELECT * FROM runs WHERE hermes_run_id=?", (hermes_run_id,)
            ).fetchone()
            return None if row is None else self.public_run(row)

    @staticmethod
    def admission(row: sqlite3.Row, *, replayed: bool) -> dict[str, object]:
        return {"run_id": row["hermes_run_id"], "status": "started", "replayed": replayed}

    @staticmethod
    def public_run(row: sqlite3.Row) -> dict[str, object]:
        result: dict[str, object] = {
            "object": "hermes.run",
            "run_id": row["hermes_run_id"],
            "status": row["status"],
            "session_id": row["session_id"],
            "created_at": "fixture",
            "updated_at": "fixture",
            "model": "fixture",
        }
        if row["output"] is not None:
            result["output"] = row["output"]
        if row["failure"] is not None:
            result["error"] = row["failure"]
        return result


class GatewayServer:
    def __init__(self, database: Path) -> None:
        self.state = GatewayState(database)
        state = self.state

        class Handler(BaseHTTPRequestHandler):
            server_version = "HermesContractFixture/1"

            def log_message(self, _format: str, *_args: object) -> None:
                return

            def json_response(self, status: int, value: object, replayed: bool = False) -> None:
                encoded = json.dumps(value, separators=(",", ":")).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                if replayed:
                    self.send_header("Idempotent-Replayed", "true")
                self.end_headers()
                self.wfile.write(encoded)

            def authorized(self) -> bool:
                if self.headers.get("Authorization") != f"Bearer {API_KEY}":
                    self.json_response(401, {"error": "unauthorized"})
                    return False
                return True

            def do_POST(self) -> None:  # noqa: N802 - stdlib hook
                if self.path != "/v1/runs":
                    self.json_response(404, {"error": "not_found"})
                    return
                if not self.authorized():
                    return
                key = self.headers.get("Idempotency-Key", "")
                try:
                    if str(uuid.UUID(key)) != key:
                        raise ValueError
                    length = int(self.headers.get("Content-Length", "0"))
                    body = json.loads(self.rfile.read(length))
                    if not isinstance(body, dict):
                        raise ValueError
                except (ValueError, json.JSONDecodeError):
                    self.json_response(400, {"error": "invalid_request"})
                    return
                session_header = self.headers.get("X-Hermes-Session-Key", "")
                status, value, replayed = state.create(key, session_header, body)
                self.json_response(status, value, replayed)

            def do_GET(self) -> None:  # noqa: N802 - stdlib hook
                if not self.authorized():
                    return
                path = self.path.split("?", 1)[0]
                if not path.startswith("/v1/runs/"):
                    self.json_response(404, {"error": "not_found"})
                    return
                suffix = path.removeprefix("/v1/runs/")
                is_events = suffix.endswith("/events")
                run_id = suffix.removesuffix("/events")
                run = state.get(run_id)
                if run is None:
                    self.json_response(404, {"error": "not_found"})
                    return
                if is_events:
                    # Emit a non-terminal event and close. The adapter contract
                    # must recover by polling GET /v1/runs/:id.
                    encoded = b'event: status\ndata: {"status":"running"}\n\n'
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Content-Length", str(len(encoded)))
                    self.end_headers()
                    self.wfile.write(encoded)
                    return
                self.json_response(200, run)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        return int(self.httpd.server_address[1])

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        self.state.close()


def request(
    port: int,
    method: str,
    path: str,
    *,
    body: dict[str, object] | None = None,
    token: str | None = API_KEY,
    idempotency_key: str | None = None,
    session_key: str | None = None,
) -> tuple[int, dict[str, object], dict[str, str]]:
    conn = HTTPConnection("127.0.0.1", port, timeout=3)
    headers: dict[str, str] = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    if session_key is not None:
        headers["X-Hermes-Session-Key"] = session_key
    payload = None
    if body is not None:
        payload = json.dumps(body, separators=(",", ":"))
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body=payload, headers=headers)
    response = conn.getresponse()
    response_headers = {key.lower(): value for key, value in response.getheaders()}
    raw = response.read()
    if response_headers.get("content-type") == "text/event-stream":
        result = {"eventStream": raw.decode()}
    else:
        result = json.loads(raw) if raw else {}
    conn.close()
    return response.status, result, response_headers


class PaperclipFixture:
    """Authoritative work graph and the narrow hermes_gateway adapter behavior."""

    def __init__(self, gateway: GatewayServer) -> None:
        self.gateway = gateway
        self.gateway_port = gateway.port
        self.company_id = canonical_uuid()
        self.agent_id = canonical_uuid()
        self.project_id = canonical_uuid()
        self.issues: dict[str, dict[str, object]] = {}
        self.runs: dict[str, dict[str, object]] = {}
        self.processed_hermes_runs: set[str] = set()
        self.diagnostics: list[str] = []

    def issue(self, title: str, *, parent_id: str | None = None) -> str:
        issue_id = canonical_uuid()
        self.issues[issue_id] = {
            "id": issue_id,
            "title": title,
            "projectId": self.project_id,
            "parentId": parent_id,
            "status": "backlog",
            "checkedOutByRun": None,
            "comments": [],
            "terminalResults": 0,
        }
        return issue_id

    def session_key(self, issue_id: str) -> str:
        return (
            f"paperclip:company:{self.company_id}:agent:{self.agent_id}:issue:{issue_id}"
        )

    def body(self, issue_id: str, input_text: str) -> dict[str, object]:
        return {
            "input": input_text,
            "session_id": self.session_key(issue_id),
        }

    def dispatch(self, issue_id: str, input_text: str, *, behavior: str = "complete",
                 run_id: str | None = None) -> tuple[str, dict[str, object], dict[str, str]]:
        paperclip_run_id = run_id or canonical_uuid()
        body = self.body(issue_id, input_text)
        self.gateway.state.behaviors[paperclip_run_id] = behavior
        status, result, headers = request(
            self.gateway_port, "POST", "/v1/runs", body=body,
            idempotency_key=paperclip_run_id, session_key=self.session_key(issue_id),
        )
        assert status == 202, (status, result)
        hermes_run_id = str(result["run_id"])
        self.runs.setdefault(paperclip_run_id, {
            "id": paperclip_run_id,
            "issueId": issue_id,
            "hermesRunId": hermes_run_id,
            "status": "running",
        })
        self.diagnostics.append(
            f"issue={issue_id} paperclip_run={paperclip_run_id} hermes_run={hermes_run_id}"
        )
        return paperclip_run_id, result, headers

    def observe_with_sse_fallback(self, paperclip_run_id: str) -> dict[str, object]:
        record = self.runs[paperclip_run_id]
        hermes_run_id = str(record["hermesRunId"])
        sse_status, _event, _headers = request(
            self.gateway_port, "GET", f"/v1/runs/{hermes_run_id}/events"
        )
        assert sse_status == 200
        poll_status, result, _headers = request(
            self.gateway_port, "GET", f"/v1/runs/{hermes_run_id}"
        )
        assert poll_status == 200
        status = str(result["status"])
        record["status"] = status
        if status in TERMINAL and status != "completed":
            issue = self.issues[str(record["issueId"])]
            issue["checkedOutByRun"] = None
        return result

    def apply_success(self, paperclip_run_id: str, *, create_child: bool = False) -> str | None:
        run = self.runs[paperclip_run_id]
        hermes_run_id = str(run["hermesRunId"])
        if hermes_run_id in self.processed_hermes_runs:
            return None
        assert run["status"] == "completed"
        issue = self.issues[str(run["issueId"])]
        current_lock = issue["checkedOutByRun"]
        assert current_lock in (None, paperclip_run_id), "checkout conflict"
        issue["checkedOutByRun"] = paperclip_run_id
        issue["status"] = "in_progress"
        comments = issue["comments"]
        assert isinstance(comments, list)
        comments.append({"runId": paperclip_run_id, "kind": "progress"})
        child_id = None
        if create_child:
            child_id = self.issue("Bounded child", parent_id=str(issue["id"]))
            self.issues[child_id]["createdByRun"] = paperclip_run_id
        comments.append({"runId": paperclip_run_id, "kind": "evidence"})
        issue["status"] = "done"
        issue["checkedOutByRun"] = None
        issue["terminalResults"] = int(issue["terminalResults"]) + 1
        self.processed_hermes_runs.add(hermes_run_id)
        return child_id


def assert_runs_api_and_lifecycle(tmp: Path) -> None:
    gateway = GatewayServer(tmp / "runs_idempotency.db")
    try:
        unauth, _, _ = request(gateway.port, "POST", "/v1/runs", body={}, token=None)
        wrong, _, _ = request(gateway.port, "POST", "/v1/runs", body={}, token="wrong")
        assert (unauth, wrong) == (401, 401)

        graph = PaperclipFixture(gateway)
        issue_a = graph.issue("Issue A")
        run_a, first, _ = graph.dispatch(issue_a, "issue-a-canary")
        observed_a = graph.observe_with_sse_fallback(run_a)
        assert observed_a["status"] == "completed"
        child_id = graph.apply_success(run_a, create_child=True)
        assert child_id is not None
        child = graph.issues[child_id]
        assert child["parentId"] == issue_a
        assert child["projectId"] == graph.project_id
        assert child["createdByRun"] == run_a

        # Exact duplicate is a replay of one Hermes run and cannot repeat work.
        replay_run, replay, replay_headers = graph.dispatch(
            issue_a, "issue-a-canary", run_id=run_a
        )
        assert replay_run == run_a
        assert replay["run_id"] == first["run_id"]
        assert replay["replayed"] is True
        assert replay_headers.get("idempotent-replayed") == "true"
        graph.observe_with_sse_fallback(run_a)
        graph.apply_success(run_a)
        assert graph.issues[issue_a]["terminalResults"] == 1

        changed = graph.body(issue_a, "changed-body")
        conflict, conflict_body, _ = request(
            gateway.port, "POST", "/v1/runs", body=changed,
            idempotency_key=run_a, session_key=graph.session_key(issue_a),
        )
        assert conflict == 409
        assert conflict_body == {"error": "idempotency_key_conflict"}

        # The issue key is the session boundary: neither unique canary crosses.
        issue_b = graph.issue("Issue B")
        run_b, _, _ = graph.dispatch(issue_b, "issue-b-canary")
        observed_b = graph.observe_with_sse_fallback(run_b)
        assert "issue-b-canary" in str(observed_b["output"])
        assert "issue-a-canary" not in str(observed_b["output"])
        assert issue_a not in str(observed_b["output"])
        assert graph.runs[run_b]["issueId"] == issue_b
        assert graph.runs[run_b]["hermesRunId"] == observed_b["run_id"]
        graph.apply_success(run_b)

        issue = graph.issues[issue_a]
        assert issue["status"] == "done"
        assert issue["checkedOutByRun"] is None
        assert [entry["kind"] for entry in issue["comments"]] == ["progress", "evidence"]
        assert all(entry["runId"] == run_a for entry in issue["comments"])
        assert all(API_KEY not in line and SECRET_CANARY not in line for line in graph.diagnostics)

        conflict_issue = graph.issue("Checkout conflict")
        conflict_run, _, _ = graph.dispatch(conflict_issue, "checkout-conflict-canary")
        assert graph.observe_with_sse_fallback(conflict_run)["status"] == "completed"
        graph.issues[conflict_issue]["checkedOutByRun"] = canonical_uuid()
        try:
            graph.apply_success(conflict_run)
        except AssertionError as exc:
            assert str(exc) == "checkout conflict"
        else:
            raise AssertionError("a competing live checkout unexpectedly succeeded")
        graph.issues[conflict_issue]["checkedOutByRun"] = None
        graph.apply_success(conflict_run)
        assert graph.issues[conflict_issue]["status"] == "done"
    finally:
        gateway.stop()


def assert_restart_and_retry(tmp: Path) -> None:
    database = tmp / "restart-runs.db"
    gateway = GatewayServer(database)
    graph = PaperclipFixture(gateway)
    issue_id = graph.issue("Restart fixture")
    failed_run, started, _ = graph.dispatch(
        issue_id, "interrupted-attempt", behavior="interrupt"
    )
    assert started == {"run_id": started["run_id"], "status": "started", "replayed": False}
    gateway.stop()

    # A new process opens the same artifact and reconciles the abandoned run.
    gateway = GatewayServer(database)
    try:
        graph.gateway = gateway
        graph.gateway_port = gateway.port
        failed = graph.observe_with_sse_fallback(failed_run)
        assert failed["status"] == "interrupted"
        assert failed["error"] == "The gateway restarted before this run settled."
        assert graph.runs[failed_run]["status"] == "interrupted"
        assert graph.issues[issue_id]["status"] == "backlog"

        retry_run, _, _ = graph.dispatch(issue_id, "retry-attempt")
        assert retry_run != failed_run
        completed = graph.observe_with_sse_fallback(retry_run)
        assert completed["status"] == "completed"
        graph.apply_success(retry_run)
        assert graph.issues[issue_id]["status"] == "done"
        assert graph.issues[issue_id]["terminalResults"] == 1
        assert graph.runs[failed_run]["status"] == "interrupted"
        assert graph.runs[retry_run]["status"] == "completed"
    finally:
        gateway.stop()


def assert_state_artifact_roundtrip(tmp: Path) -> None:
    """Prove both Slice 2 SQLite artifacts survive a full-volume archive."""
    source = tmp / "source"
    restored = tmp / "restored"
    (source / "state").mkdir(parents=True)
    artifacts = (
        source / "runs_idempotency.db",
        source / "state" / "paperclip-question-delivery.db",
    )
    for index, artifact in enumerate(artifacts):
        db = sqlite3.connect(artifact)
        db.execute("CREATE TABLE proof (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("INSERT INTO proof(value) VALUES (?)", (f"slice-2-{index}",))
        db.commit()
        db.close()
        os.chmod(artifact, 0o600)
    expected = {str(path.relative_to(source)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in artifacts}

    archive = tmp / "hermes-data.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        output.add(source, arcname=".")
    restored.mkdir()
    with tarfile.open(archive, "r:gz") as incoming:
        # Member names are produced locally above; no untrusted extraction.
        incoming.extractall(restored, filter="data")

    for relative, expected_digest in expected.items():
        artifact = restored / relative
        assert artifact.is_file()
        assert (artifact.stat().st_mode & 0o777) == 0o600
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == expected_digest
        db = sqlite3.connect(f"file:{artifact}?mode=ro", uri=True)
        assert db.execute("SELECT value FROM proof").fetchone()[0].startswith("slice-2-")
        db.close()


def assert_repository_recovery_guards(repo: Path) -> None:
    backup = (repo / "scripts" / "backup").read_text()
    restore = (repo / "scripts" / "restore-smoke").read_text()
    for relative in ("runs_idempotency.db", "state/paperclip-question-delivery.db"):
        assert relative in backup, f"backup lacks an explicit safety guard for {relative}"
        assert relative in restore, f"restore lacks an explicit safety guard for {relative}"


def main() -> None:
    repo = Path(__file__).resolve().parents[2]
    tmp = Path(tempfile.mkdtemp(prefix="nix-slice2-e2e."))
    try:
        assert_runs_api_and_lifecycle(tmp)
        assert_restart_and_retry(tmp)
        assert_state_artifact_roundtrip(tmp)
        assert_repository_recovery_guards(repo)
    finally:
        shutil.rmtree(tmp)
    print("In-memory Paperclip-to-Hermes Slice 2 contract-model checks passed.")


if __name__ == "__main__":
    main()
