#!/usr/bin/env python3
"""Hermetic tests for human-only question creation and Telegram delivery."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import socket
import sqlite3
import stat
import tempfile
import threading
import time


REPO = Path(__file__).resolve().parents[2]
MODULE = REPO / "deploy/hermes/paperclip_question_delivery.py"
ISSUE = "11111111-1111-4111-8111-111111111111"
INTERACTION = "22222222-2222-4222-8222-222222222222"
RUN_ID = "33333333-3333-4333-8333-333333333333"
SECRET = "a" * 64

spec = importlib.util.spec_from_file_location("paperclip_question_delivery_contract", MODULE)
assert spec is not None and spec.loader is not None
delivery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(delivery)


def question_payload(prompt: str = "Choose a direction") -> dict:
    return {
        "version": 1,
        "title": "Founder decision",
        "questions": [
            {
                "id": "direction",
                "prompt": prompt,
                "selectionMode": "single",
                "required": True,
                "options": [
                    {"id": "alpha", "label": "Alpha"},
                    {"id": "beta", "label": "Beta"},
                ],
            }
        ],
    }


def request(payload: dict | None = None, *, key: str = "decision-one") -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "paperclipAskUserQuestions",
            "arguments": {
                "issueId": ISSUE,
                "idempotencyKey": key,
                "payload": payload or question_payload(),
            },
        },
    }


def response(payload: dict | None = None, *, interaction_id: str = INTERACTION) -> dict:
    interaction = {
        "id": interaction_id,
        "issueId": ISSUE,
        "kind": "ask_user_questions",
        "status": "pending",
        "requestedResolverPolicy": "human_only",
        "effectiveResolverPolicy": "human_only",
        "addresseeUserId": "lior-user",
        "payload": payload or question_payload(),
    }
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(interaction, separators=(",", ":")),
                }
            ]
        },
    }


class Server(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, address, mode: str):
        super().__init__(address, Handler)
        self.mode = mode
        self.received: list[dict] = []


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers["Content-Length"])
        body = self.rfile.read(length)
        timestamp = self.headers["X-Webhook-Timestamp"]
        expected = hmac.new(
            SECRET.encode(), timestamp.encode() + b"." + body, hashlib.sha256
        ).hexdigest()
        assert self.path == "/webhooks/paperclip-decision"
        assert hmac.compare_digest(self.headers["X-Webhook-Signature-V2"], expected)
        delivery_id = self.headers["X-Request-ID"]
        self.server.received.append(  # type: ignore[attr-defined]
            {"body": json.loads(body), "delivery_id": delivery_id}
        )
        mode = self.server.mode  # type: ignore[attr-defined]
        if mode == "timeout":
            time.sleep(0.3)
        status = 401 if mode == "reject" else (502 if mode == "server-error" else 200)
        payload = {
            "status": "duplicate" if mode == "duplicate" else "delivered",
            "delivery_id": delivery_id,
        }
        encoded = json.dumps(payload).encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *_args):
        return


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@contextmanager
def server(mode: str, port: int | None = None):
    instance = Server(("127.0.0.1", port or 0), mode)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        yield instance
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join(timeout=2)


def state(path: Path) -> tuple[str, int, int | None]:
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT state, attempt_count, http_status FROM deliveries WHERE interaction_id = ?",
            (INTERACTION,),
        ).fetchone()
    assert row is not None
    return row


def main() -> None:
    os.environ["HERMES_DECISION_WEBHOOK_SECRET"] = SECRET
    os.environ["PAPERCLIP_LIOR_USER_ID"] = "lior-user"
    assert delivery.WEBHOOK_HOST == "127.0.0.1"
    assert delivery.WEBHOOK_PORT == 8644
    assert delivery.WEBHOOK_PATH == "/webhooks/paperclip-decision"

    transformed = delivery.human_only_question_api_arguments(
        request()["params"]["arguments"], RUN_ID
    )
    assert transformed["method"] == "POST"
    assert transformed["path"] == f"/issues/{ISSUE}/interactions"
    api_body = json.loads(transformed["jsonBody"])
    assert api_body["kind"] == "ask_user_questions"
    assert api_body["resolverPolicy"] == "human_only"
    assert api_body["addresseeUserId"] == "lior-user"
    assert api_body["idempotencyKey"] == "decision-one"
    assert api_body["sourceRunId"] == RUN_ID
    assert api_body["continuationPolicy"] == "wake_assignee"
    assert "issueId" not in api_body
    for invalid in (
        {**request()["params"]["arguments"], "idempotencyKey": ""},
        {**request()["params"]["arguments"], "issueId": "../escape"},
        {**request()["params"]["arguments"], "continuationPolicy": "none"},
        {
            **request()["params"]["arguments"],
            "payload": {
                "version": 1,
                "questions": [{
                    "id": "q", "prompt": "Choose", "required": True,
                    "options": [{"id": "a", "label": "A"}],
                }],
            },
        },
        {
            **request()["params"]["arguments"],
            "payload": {
                "version": 1,
                "questions": [{
                    "id": "q", "prompt": "Choose", "selectionMode": "single",
                    "options": [{"id": "a", "label": "A"}],
                }],
            },
        },
    ):
        try:
            delivery.human_only_question_api_arguments(invalid, RUN_ID)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid question arguments passed")

    original_port = delivery.WEBHOOK_PORT
    original_timeout = delivery.HTTP_TIMEOUT_SECONDS
    try:
        with tempfile.TemporaryDirectory(prefix="nix-question-delivery-") as directory:
            root = Path(directory)

            unsafe_parent = root / "unsafe"
            unsafe_parent.mkdir(mode=0o777)
            unsafe_parent.chmod(0o777)
            try:
                delivery._open_outbox(unsafe_parent / "outbox.db")
            except delivery.DeliveryConfigurationError as exc:
                assert "outbox parent is unsafe" in str(exc)
            else:
                raise AssertionError("group/world-writable outbox parent unexpectedly passed")

            hardlink_db = root / "hardlink.db"
            connection = delivery._open_outbox(hardlink_db)
            connection.close()
            hardlink_alias = root / "hardlink-alias.db"
            os.link(hardlink_db, hardlink_alias)
            try:
                delivery._open_outbox(hardlink_alias)
            except delivery.DeliveryConfigurationError as exc:
                assert "outbox is unsafe" in str(exc)
            else:
                raise AssertionError("hardlinked question outbox unexpectedly passed")

            # Confirmed delivery is durable and replay does not re-send.
            delivered_db = root / "delivered.db"
            with server("delivered") as endpoint:
                delivery.WEBHOOK_PORT = endpoint.server_port
                assert delivery.notify_question_created(
                    response(), request(), outbox_path=delivered_db
                ) == "delivered"
                assert delivery.notify_question_created(
                    response(), request(), outbox_path=delivered_db
                ) == "delivered"
                assert len(endpoint.received) == 1
                event = endpoint.received[0]
                assert event["delivery_id"] == INTERACTION
                assert set(event["body"]) == {
                    "event_type", "interaction_id", "issue_id", "message"
                }
                assert event["body"]["event_type"] == "paperclip.decision_required"
                assert event["body"]["interaction_id"] == INTERACTION
                assert event["body"]["issue_id"] == ISSUE
                assert "Choose a direction" in event["body"]["message"]
                assert "Alpha" in event["body"]["message"]
            metadata = delivered_db.stat()
            assert stat.S_IMODE(metadata.st_mode) == 0o600
            assert state(delivered_db) == ("delivered", 1, 200)

            # Hermes' duplicate response is recorded and never replayed.
            duplicate_db = root / "duplicate.db"
            with server("duplicate") as endpoint:
                delivery.WEBHOOK_PORT = endpoint.server_port
                assert delivery.notify_question_created(
                    response(), request(), outbox_path=duplicate_db
                ) == "duplicate"
                assert delivery.notify_question_created(
                    response(), request(), outbox_path=duplicate_db
                ) == "duplicate"
                assert len(endpoint.received) == 1

            # A refused loopback connect is conclusively not sent and may be
            # retried only when the same durable interaction is presented.
            retry_port = free_port()
            delivery.WEBHOOK_PORT = retry_port
            retry_db = root / "retry.db"
            assert delivery.notify_question_created(
                response(), request(), outbox_path=retry_db
            ) == "failed_not_sent"
            with server("delivered", retry_port) as endpoint:
                assert delivery.notify_question_created(
                    response(), request(), outbox_path=retry_db
                ) == "delivered"
                assert len(endpoint.received) == 1
            assert state(retry_db) == ("delivered", 2, 200)

            # Concurrent admission cannot produce two webhook sends for one
            # interaction, even while the first HTTP attempt is in flight.
            concurrent_db = root / "concurrent.db"
            delivery.HTTP_TIMEOUT_SECONDS = 1.0
            with server("delivered") as endpoint:
                delivery.WEBHOOK_PORT = endpoint.server_port
                original_post = delivery._post
                send_entered = threading.Event()
                release_send = threading.Event()

                def held_post(*args, **kwargs):
                    send_entered.set()
                    assert release_send.wait(timeout=2)
                    return original_post(*args, **kwargs)

                delivery._post = held_post
                results: list[str | None] = []
                first = threading.Thread(
                    target=lambda: results.append(delivery.notify_question_created(
                        response(), request(), outbox_path=concurrent_db
                    ))
                )
                first.start()
                assert send_entered.wait(timeout=2)
                second = threading.Thread(
                    target=lambda: results.append(delivery.notify_question_created(
                        response(), request(), outbox_path=concurrent_db
                    ))
                )
                second.start()
                second.join(timeout=2)
                release_send.set()
                first.join(timeout=2)
                delivery._post = original_post
                assert not first.is_alive() and not second.is_alive()
                assert sorted(results) == ["delivered", "unknown"]
                assert len(endpoint.received) == 1
                assert state(concurrent_db) == ("delivered", 1, 200)

            # Timeout after connect is outcome-unknown and never blindly sent
            # again, even when the same interaction is replayed.
            unknown_db = root / "unknown.db"
            delivery.HTTP_TIMEOUT_SECONDS = 0.05
            with server("timeout") as endpoint:
                delivery.WEBHOOK_PORT = endpoint.server_port
                assert delivery.notify_question_created(
                    response(), request(), outbox_path=unknown_db
                ) == "unknown"
                assert delivery.notify_question_created(
                    response(), request(), outbox_path=unknown_db
                ) == "unknown"
                assert len(endpoint.received) == 1

            # A signed request rejected before delivery is terminal and is not
            # retried without creating a new interaction.
            rejected_db = root / "rejected.db"
            delivery.HTTP_TIMEOUT_SECONDS = original_timeout
            with server("reject") as endpoint:
                delivery.WEBHOOK_PORT = endpoint.server_port
                assert delivery.notify_question_created(
                    response(), request(), outbox_path=rejected_db
                ) == "failed"
                assert delivery.notify_question_created(
                    response(), request(), outbox_path=rejected_db
                ) == "failed"
                assert len(endpoint.received) == 1

            # A receiver-side 5xx may follow a Telegram attempt. Its outcome
            # is unknown and therefore cannot be replayed automatically.
            server_error_db = root / "server-error.db"
            with server("server-error") as endpoint:
                delivery.WEBHOOK_PORT = endpoint.server_port
                assert delivery.notify_question_created(
                    response(), request(), outbox_path=server_error_db
                ) == "unknown"
                assert delivery.notify_question_created(
                    response(), request(), outbox_path=server_error_db
                ) == "unknown"
                assert len(endpoint.received) == 1

            # Same interaction ID with different content is a durable conflict,
            # and unsuccessful/non-human-only responses never enter the outbox.
            assert delivery.notify_question_created(
                response(question_payload("Different")),
                request(question_payload("Different")),
                outbox_path=delivered_db,
            ) == "conflict"
            invalid_db = root / "invalid.db"
            unsafe = response()
            record = json.loads(unsafe["result"]["content"][0]["text"])
            record["effectiveResolverPolicy"] = "anyone"
            unsafe["result"]["content"][0]["text"] = json.dumps(record)
            assert delivery.notify_question_created(
                unsafe, request(), outbox_path=invalid_db
            ) is None
            assert not invalid_db.exists()

            # Path.exists() is false for a dangling symlink. The fixed outbox
            # boundary must still refuse it rather than creating state through
            # or over an attacker/corruption-controlled path.
            dangling_db = root / "dangling.db"
            dangling_db.symlink_to(root / "missing-target.db")
            try:
                delivery.notify_question_created(
                    response(), request(), outbox_path=dangling_db
                )
            except (FileExistsError, delivery.DeliveryConfigurationError):
                pass
            else:
                raise AssertionError("dangling outbox symlink was accepted")
            assert dangling_db.is_symlink()
    finally:
        delivery.WEBHOOK_PORT = original_port
        delivery.HTTP_TIMEOUT_SECONDS = original_timeout


if __name__ == "__main__":
    main()
