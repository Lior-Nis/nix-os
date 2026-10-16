#!/usr/bin/env python3
"""Deliver durable Paperclip question interactions through Hermes' webhook.

This module has one fixed network target: the pinned Hermes gateway's loopback
``deliver_only`` route.  It is not a general HTTP or messaging client.  The
Paperclip interaction is already authoritative before this notification runs.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
from typing import Any
from urllib.parse import quote


WEBHOOK_HOST = "127.0.0.1"
WEBHOOK_PORT = 8644
WEBHOOK_PATH = "/webhooks/paperclip-decision"
WEBHOOK_EVENT = "paperclip.decision_required"
OUTBOX_PATH = Path("/opt/data/state/paperclip-question-delivery.db")
SECRET_ENV = "HERMES_DECISION_WEBHOOK_SECRET"
HTTP_TIMEOUT_SECONDS = 3.0
MAX_MESSAGE_CHARACTERS = 3800
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
SECRET_PATTERN = re.compile(r"^[0-9a-f]{64}$")
PAPERCLIP_ARGUMENT_KEYS = {
    "issueId",
    "idempotencyKey",
    "sourceCommentId",
    "sourceRunId",
    "title",
    "summary",
    "continuationPolicy",
    "payload",
}


class DeliveryConfigurationError(RuntimeError):
    """The fixed local delivery boundary is not configured safely."""


def _bounded_optional_string(value: Any, maximum: int) -> bool:
    return value is None or (isinstance(value, str) and len(value.strip()) <= maximum)


def _validate_question_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    if set(arguments) - PAPERCLIP_ARGUMENT_KEYS:
        raise ValueError("question arguments contain unsupported fields")
    issue_id = arguments.get("issueId")
    if not isinstance(issue_id, str) or UUID_PATTERN.fullmatch(issue_id) is None:
        raise ValueError("issueId must be a canonical UUID")
    idempotency_key = arguments.get("idempotencyKey")
    if (
        not isinstance(idempotency_key, str)
        or not idempotency_key.strip()
        or len(idempotency_key.strip()) > 255
    ):
        raise ValueError("a stable idempotencyKey is required")
    for key in ("sourceCommentId", "sourceRunId"):
        value = arguments.get(key)
        if value is not None and (
            not isinstance(value, str) or UUID_PATTERN.fullmatch(value) is None
        ):
            raise ValueError(f"{key} must be a canonical UUID when present")
    if not _bounded_optional_string(arguments.get("title"), 240):
        raise ValueError("title is invalid")
    if not _bounded_optional_string(arguments.get("summary"), 1000):
        raise ValueError("summary is invalid")
    continuation = arguments.get("continuationPolicy", "wake_assignee")
    if continuation != "wake_assignee":
        raise ValueError("continuationPolicy is invalid")
    payload = arguments.get("payload")
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("question payload version is invalid")
    questions = payload.get("questions")
    if not isinstance(questions, list) or not 1 <= len(questions) <= 64:
        raise ValueError("question payload must contain 1 to 64 questions")
    question_ids: set[str] = set()
    for question in questions:
        if not isinstance(question, dict):
            raise ValueError("question is invalid")
        question_id = question.get("id")
        prompt = question.get("prompt")
        selection_mode = question.get("selectionMode")
        required = question.get("required")
        options = question.get("options")
        if (
            not isinstance(question_id, str)
            or not question_id.strip()
            or len(question_id.strip()) > 160
            or question_id in question_ids
        ):
            raise ValueError("question id is invalid or duplicated")
        question_ids.add(question_id)
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt.strip()) > 4000:
            raise ValueError("question prompt is invalid")
        if selection_mode not in {"single", "multi"}:
            raise ValueError("question selectionMode is invalid")
        if not isinstance(required, bool):
            raise ValueError("question required must be explicit")
        if not isinstance(options, list) or not 1 <= len(options) <= 129:
            raise ValueError("question options are invalid")
        option_ids: set[str] = set()
        free_text_count = 0
        for option in options:
            if not isinstance(option, dict):
                raise ValueError("question option is invalid")
            option_id = option.get("id")
            label = option.get("label")
            if (
                not isinstance(option_id, str)
                or not option_id.strip()
                or len(option_id.strip()) > 160
                or option_id in option_ids
            ):
                raise ValueError("question option id is invalid or duplicated")
            option_ids.add(option_id)
            if not isinstance(label, str) or not label.strip() or len(label.strip()) > 1000:
                raise ValueError("question option label is invalid")
            if "freeText" in option and not isinstance(option["freeText"], bool):
                raise ValueError("question option freeText is invalid")
            if option.get("freeText") is True:
                free_text_count += 1
        if free_text_count > 1:
            raise ValueError("question permits more than one free-text option")
    body = {key: value for key, value in arguments.items() if key != "issueId"}
    body["kind"] = "ask_user_questions"
    body["resolverPolicy"] = "human_only"
    body["continuationPolicy"] = continuation
    return body


def human_only_question_api_arguments(
    arguments: dict[str, Any], trusted_run_id: str
) -> dict[str, str]:
    """Map the exposed Ask schema to one fixed official API-request tool call."""
    if UUID_PATTERN.fullmatch(trusted_run_id) is None:
        raise DeliveryConfigurationError("the trusted Paperclip run ID is invalid")
    body = _validate_question_arguments(arguments)
    lior_user_id = os.environ.get("PAPERCLIP_LIOR_USER_ID", "")
    if re.fullmatch(r"[A-Za-z0-9._:-]{3,200}", lior_user_id) is None:
        raise DeliveryConfigurationError("the founder Paperclip user ID is invalid")
    body["addresseeUserId"] = lior_user_id
    body["sourceRunId"] = trusted_run_id
    return {
        "method": "POST",
        "path": f"/issues/{quote(arguments['issueId'], safe='')}/interactions",
        "jsonBody": _canonical_json(body).decode("utf-8"),
    }


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _text_content(response: dict[str, Any]) -> dict[str, Any] | None:
    if "error" in response:
        return None
    result = response.get("result")
    if not isinstance(result, dict) or result.get("isError") is True:
        return None
    content = result.get("content")
    if not isinstance(content, list):
        return None
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "text":
            continue
        text = item.get("text")
        if not isinstance(text, str):
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _interaction_from_success(
    response: dict[str, Any], request: dict[str, Any]
) -> dict[str, Any] | None:
    """Return an authoritative newly-created interaction or fail closed."""
    params = request.get("params")
    arguments = params.get("arguments") if isinstance(params, dict) else None
    expected_issue = arguments.get("issueId") if isinstance(arguments, dict) else None
    interaction = _text_content(response)
    if interaction is None or interaction.get("error") is not None:
        return None
    interaction_id = interaction.get("id")
    if not isinstance(interaction_id, str) or UUID_PATTERN.fullmatch(interaction_id) is None:
        return None
    if interaction.get("kind") != "ask_user_questions":
        return None
    if not isinstance(expected_issue, str) or interaction.get("issueId") != expected_issue:
        return None
    if interaction.get("status") != "pending":
        return None
    if (
        interaction.get("requestedResolverPolicy") != "human_only"
        or interaction.get("effectiveResolverPolicy") != "human_only"
        or interaction.get("addresseeUserId") != os.environ.get("PAPERCLIP_LIOR_USER_ID")
    ):
        return None
    payload = interaction.get("payload")
    if not isinstance(payload, dict) or payload.get("version") != 1:
        return None
    questions = payload.get("questions")
    if not isinstance(questions, list) or not questions:
        return None
    return interaction


def _one_line(value: Any, maximum: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:maximum]


def _render_message(interaction: dict[str, Any]) -> str | None:
    payload = interaction["payload"]
    questions = payload["questions"]
    lines = [
        "Paperclip needs your decision.",
        f"Issue: {interaction['issueId']}",
        f"Decision: {interaction['id']}",
    ]
    title = _one_line(payload.get("title"), 240)
    if title:
        lines.extend(("", title))
    for index, question in enumerate(questions, start=1):
        if not isinstance(question, dict):
            return None
        prompt = _one_line(question.get("prompt"), 1000)
        options = question.get("options")
        if (
            not prompt
            or question.get("selectionMode") not in {"single", "multi"}
            or not isinstance(question.get("required"), bool)
            or not isinstance(options, list)
            or not options
        ):
            return None
        lines.extend(("", f"{index}. {prompt}"))
        for option in options:
            if not isinstance(option, dict):
                return None
            label = _one_line(option.get("label"), 300)
            if not label:
                return None
            lines.append(f"- {label}")
        if question.get("allowOther") is True:
            lines.append("- Another answer")
    lines.extend(("", "Reply to Chief in this Telegram chat."))
    message = "\n".join(lines)
    if len(message) > MAX_MESSAGE_CHARACTERS:
        message = message[: MAX_MESSAGE_CHARACTERS - 1].rstrip() + "…"
    return message


def _validate_secret() -> str:
    secret = os.environ.get(SECRET_ENV, "")
    if SECRET_PATTERN.fullmatch(secret) is None:
        raise DeliveryConfigurationError(
            "the Hermes decision webhook secret is missing or invalid"
        )
    return secret


def _open_outbox(path: Path) -> sqlite3.Connection:
    os.umask(0o077)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent = path.parent.lstat()
    if (
        not stat.S_ISDIR(parent.st_mode)
        or stat.S_ISLNK(parent.st_mode)
        or parent.st_uid != os.geteuid()
        or parent.st_gid != os.getegid()
        or stat.S_IMODE(parent.st_mode) & 0o022
    ):
        raise DeliveryConfigurationError("the question outbox parent is unsafe")
    if not os.path.lexists(path):
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        os.close(descriptor)
    metadata = path.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
    ):
        raise DeliveryConfigurationError("the question outbox is unsafe")
    if (
        metadata.st_uid != os.geteuid()
        or metadata.st_gid != os.getegid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise DeliveryConfigurationError("the question outbox ownership or mode is unsafe")
    connection = sqlite3.connect(path, timeout=5.0)
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA journal_mode = DELETE")
    connection.execute("PRAGMA synchronous = FULL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS deliveries (
          interaction_id TEXT PRIMARY KEY,
          payload_digest TEXT NOT NULL,
          state TEXT NOT NULL CHECK (
            state IN ('pending','failed_not_sent','delivered','duplicate','failed','unknown','conflict')
          ),
          attempt_count INTEGER NOT NULL,
          http_status INTEGER,
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL
        )
        """
    )
    connection.commit()
    os.chmod(path, 0o600)
    return connection


def _reserve(
    connection: sqlite3.Connection, interaction_id: str, digest: str
) -> tuple[bool, str]:
    """Reserve one attempt; stale pending rows become unknown, never replayed."""
    now = int(time.time())
    connection.execute("BEGIN IMMEDIATE")
    row = connection.execute(
        "SELECT payload_digest, state, attempt_count FROM deliveries WHERE interaction_id = ?",
        (interaction_id,),
    ).fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO deliveries VALUES (?, ?, 'pending', 1, NULL, ?, ?)",
            (interaction_id, digest, now, now),
        )
        connection.commit()
        return True, "pending"
    stored_digest, state, attempts = row
    if stored_digest != digest:
        connection.execute(
            "UPDATE deliveries SET state = 'conflict', updated_at = ? WHERE interaction_id = ?",
            (now, interaction_id),
        )
        connection.commit()
        return False, "conflict"
    if state == "pending":
        connection.execute(
            "UPDATE deliveries SET state = 'unknown', updated_at = ? WHERE interaction_id = ?",
            (now, interaction_id),
        )
        connection.commit()
        return False, "unknown"
    if state == "failed_not_sent":
        connection.execute(
            "UPDATE deliveries SET state = 'pending', attempt_count = ?, http_status = NULL, updated_at = ? "
            "WHERE interaction_id = ?",
            (int(attempts) + 1, now, interaction_id),
        )
        connection.commit()
        return True, "pending"
    connection.commit()
    return False, str(state)


def _finish(
    connection: sqlite3.Connection,
    interaction_id: str,
    state: str,
    http_status: int | None = None,
) -> None:
    connection.execute(
        "UPDATE deliveries SET state = ?, http_status = ?, updated_at = ? WHERE interaction_id = ?",
        (state, http_status, int(time.time()), interaction_id),
    )
    connection.commit()


def _post(body: bytes, interaction_id: str, secret: str) -> tuple[str, int | None]:
    timestamp = str(int(time.time()))
    signature = hmac.new(
        secret.encode("ascii"), timestamp.encode("ascii") + b"." + body, hashlib.sha256
    ).hexdigest()
    connection = http.client.HTTPConnection(
        WEBHOOK_HOST, WEBHOOK_PORT, timeout=HTTP_TIMEOUT_SECONDS
    )
    try:
        try:
            connection.connect()
        except OSError:
            return "failed_not_sent", None
        try:
            connection.request(
                "POST",
                WEBHOOK_PATH,
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                    "X-Webhook-Timestamp": timestamp,
                    "X-Webhook-Signature-V2": signature,
                    "X-Request-ID": interaction_id,
                },
            )
            response = connection.getresponse()
            response_body = response.read(16384)
        except (OSError, TimeoutError, http.client.HTTPException):
            return "unknown", None
    finally:
        connection.close()
    try:
        parsed = json.loads(response_body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        parsed = None
    if response.status == 200 and isinstance(parsed, dict):
        if parsed.get("delivery_id") != interaction_id:
            return "unknown", response.status
        if parsed.get("status") == "delivered":
            return "delivered", response.status
        if parsed.get("status") == "duplicate":
            return "duplicate", response.status
        return "unknown", response.status
    if 400 <= response.status < 500:
        return "failed", response.status
    # Hermes records the request ID before direct delivery. A 5xx can therefore
    # be returned after the target was attempted; retrying would be unsafe.
    return "unknown", response.status


def notify_question_created(
    response: dict[str, Any],
    request: dict[str, Any],
    *,
    outbox_path: Path = OUTBOX_PATH,
) -> str | None:
    """Notify once after a conclusive Paperclip question-creation response.

    ``None`` means the upstream response was not an authoritative successful
    question creation, so no outbox row and no network attempt were made.
    """
    interaction = _interaction_from_success(response, request)
    if interaction is None:
        return None
    message = _render_message(interaction)
    if message is None:
        return None
    body = _canonical_json(
        {
            "event_type": WEBHOOK_EVENT,
            "interaction_id": interaction["id"],
            "issue_id": interaction["issueId"],
            "message": message,
        }
    )
    digest = hashlib.sha256(body).hexdigest()
    secret = _validate_secret()
    with _open_outbox(outbox_path) as outbox:
        should_send, state = _reserve(outbox, interaction["id"], digest)
        if not should_send:
            return state
        state, http_status = _post(body, interaction["id"], secret)
        _finish(outbox, interaction["id"], state, http_status)
        return state
