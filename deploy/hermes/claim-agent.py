#!/usr/bin/env python3
"""Claim and durably persist one Paperclip agent credential without logging it."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import stat
import sys
import tempfile
import urllib.error
import urllib.request
from types import SimpleNamespace
from typing import Any

try:
    from dotenv.parser import parse_stream as dotenv_parse_stream
except ModuleNotFoundError:  # Dependency-free hosted unit tests only.
    if os.environ.get("NIX_ALLOW_DEPENDENCY_FREE_DOTENV_TEST") != "1":
        raise
    dotenv_parse_stream = None


MIN_FREE_BYTES = 1024 * 1024
MANAGED_KEYS = {
    "PAPERCLIP_API_URL",
    "PAPERCLIP_API_KEY",
    "PAPERCLIP_COMPANY_ID",
    "PAPERCLIP_AGENT_ID",
}
EXTERNAL_ONLY_KEYS = {
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ALLOWED_USERS",
    "TELEGRAM_ALLOW_ALL_USERS",
    "GATEWAY_ALLOW_ALL_USERS",
}
CLAIM_STAGE_DIRECTORY = "mcp-tokens"
CLAIM_STAGE_NAME = "nix-os-paperclip-claim-stage.json"
REPLACEMENT_MARKER_KIND = "replacement-key-install"


class ClaimError(RuntimeError):
    pass


class ConsumedClaimError(ClaimError):
    pass


def fsync_directory(path: pathlib.Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path: pathlib.Path, data: bytes, mode: int = 0o600) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = pathlib.Path(temporary)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb", closefd=True) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        fsync_directory(path.parent)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        temporary_path.unlink(missing_ok=True)
        raise


def require_runtime_secret(path: pathlib.Path, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise ClaimError(f"{label} is missing or unsafe")
    metadata = path.stat()
    if metadata.st_uid != os.geteuid() or metadata.st_gid != os.getegid():
        raise ClaimError(f"{label} has unexpected ownership")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise ClaimError(f"{label} must have mode 0600")


def claim_stage_path(profile_dir: pathlib.Path, *, create_parent: bool = False) -> pathlib.Path:
    directory = profile_dir / CLAIM_STAGE_DIRECTORY
    if not directory.exists() and create_parent:
        try:
            directory.mkdir(mode=0o700)
            fsync_directory(profile_dir)
        except FileExistsError:
            pass
    if directory.exists():
        if directory.is_symlink() or not directory.is_dir():
            raise ClaimError("Paperclip claim staging directory is unsafe")
        metadata = directory.stat()
        if metadata.st_uid != os.geteuid() or metadata.st_gid != os.getegid():
            raise ClaimError("Paperclip claim staging directory has unexpected ownership")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise ClaimError("Paperclip claim staging directory must be private")
    elif create_parent:
        raise ClaimError("Paperclip claim staging directory could not be created")
    return directory / CLAIM_STAGE_NAME


def parse_env(path: pathlib.Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for binding in parse_env_bindings(path):
        if binding.key is not None and binding.value is not None:
            values[binding.key] = binding.value
    return values


def parse_env_bindings(path: pathlib.Path) -> list[Any]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        if dotenv_parse_stream is not None:
            bindings = list(dotenv_parse_stream(stream))
        else:
            bindings = []
            assignment = re.compile(
                r"^\s*(?:export\s+)?(?:'([^']+)'|([A-Za-z_][A-Za-z0-9_]*))\s*=\s*(.*?)(?:\r?\n)?$"
            )
            for line in stream:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    bindings.append(
                        SimpleNamespace(key=None, value=None, original=SimpleNamespace(string=line), error=False)
                    )
                    continue
                match = assignment.match(line)
                bindings.append(
                    SimpleNamespace(
                        key=(match.group(1) or match.group(2)) if match else None,
                        value=match.group(3) if match else None,
                        original=SimpleNamespace(string=line),
                        error=match is None,
                    )
                )
    if any(binding.error for binding in bindings):
        raise ClaimError("Hermes profile environment contains invalid dotenv syntax")
    return bindings


def profile_preflight(profile_dir: pathlib.Path) -> pathlib.Path:
    if not profile_dir.is_dir() or profile_dir.is_symlink():
        raise ClaimError("Hermes profile directory is missing or unsafe")
    profile_stat = profile_dir.stat()
    if profile_stat.st_uid != os.geteuid():
        raise ClaimError("Hermes profile directory has unexpected ownership")
    if not os.access(profile_dir, os.W_OK | os.X_OK):
        raise ClaimError("Hermes profile directory is not writable")
    for required in ("config.yaml", "SOUL.md"):
        if not (profile_dir / required).is_file():
            raise ClaimError(f"Hermes profile is incomplete: {required} is missing")
    if shutil.disk_usage(profile_dir).free < MIN_FREE_BYTES:
        raise ClaimError("Hermes profile storage has less than 1 MiB free")

    target = profile_dir / ".env"
    if target.exists():
        if target.is_symlink() or not target.is_file():
            raise ClaimError("Hermes profile credential destination is unsafe")
        target_stat = target.stat()
        if target_stat.st_uid != os.geteuid():
            raise ClaimError("Hermes profile credential file has unexpected ownership")
        if stat.S_IMODE(target_stat.st_mode) != 0o600:
            raise ClaimError("Hermes profile credential file must have mode 0600")
    return target


def request_json(url: str, payload: dict, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status < 200 or response.status >= 300:
                raise ClaimError(f"Paperclip returned HTTP {response.status}")
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise ClaimError(f"Paperclip returned HTTP {exc.code}") from None
    except urllib.error.URLError:
        raise ClaimError("Paperclip could not be reached") from None


def get_self(api_url: str, token: str) -> dict:
    request = urllib.request.Request(
        f"{api_url}/api/agents/me",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status != 200:
                raise ClaimError(f"Paperclip identity verification returned HTTP {response.status}")
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise ClaimError(f"Paperclip identity verification returned HTTP {exc.code}") from None
    except urllib.error.URLError:
        raise ClaimError("Paperclip identity verification could not connect") from None


def render_env(existing_path: pathlib.Path, api_url: str, token: str, company_id: str, agent_id: str) -> bytes:
    preserved: list[str] = []
    if existing_path.exists():
        for binding in parse_env_bindings(existing_path):
            if binding.key not in MANAGED_KEYS and binding.key not in EXTERNAL_ONLY_KEYS:
                preserved.append(binding.original.string.rstrip("\r\n"))
    preserved.extend(
        [
            f"PAPERCLIP_API_URL={api_url}",
            f"PAPERCLIP_API_KEY={token}",
            f"PAPERCLIP_COMPANY_ID={company_id}",
            f"PAPERCLIP_AGENT_ID={agent_id}",
        ]
    )
    return ("\n".join(preserved) + "\n").encode()


def verify_identity(api_url: str, token: str, company_id: str, agent_id: str) -> None:
    identity = get_self(api_url, token)
    if identity.get("id") != agent_id or identity.get("companyId") != company_id:
        raise ClaimError("persisted Paperclip credential resolved to an unexpected identity")


def recovery_status(profile_dir: pathlib.Path) -> dict[str, Any]:
    target = profile_preflight(profile_dir)
    receipt_path = profile_dir / ".paperclip-claim-receipt.json"
    markers = sorted(profile_dir.glob(".paperclip-claim-*.pending"))
    if len(markers) > 1:
        raise ClaimError("multiple Paperclip claim recovery markers exist")

    existing = parse_env(target)
    token = existing.get("PAPERCLIP_API_KEY", "")
    company_id = existing.get("PAPERCLIP_COMPANY_ID", "")
    agent_id = existing.get("PAPERCLIP_AGENT_ID", "")
    if token:
        if not company_id or not agent_id:
            raise ClaimError("persisted Paperclip credential identity is incomplete")
        require_runtime_secret(target, "persisted Paperclip credential file")
        verify_identity(os.environ.get("PAPERCLIP_API_URL", "http://paperclip:3100").rstrip("/"), token, company_id, agent_id)
    elif company_id or agent_id:
        raise ClaimError("persisted Paperclip identity exists without its credential")

    receipt: dict[str, Any] | None = None
    if receipt_path.exists():
        require_runtime_secret(receipt_path, "Paperclip claim receipt")
        try:
            loaded = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise ClaimError("Paperclip claim receipt is invalid") from None
        if not isinstance(loaded, dict):
            raise ClaimError("Paperclip claim receipt is invalid")
        receipt = loaded
        if not token or loaded.get("companyId") != company_id or loaded.get("agentId") != agent_id:
            raise ClaimError("Paperclip claim receipt does not match the persisted identity")

    marker: dict[str, Any] | None = None
    if markers:
        require_runtime_secret(markers[0], "Paperclip claim recovery marker")
        try:
            loaded = json.loads(markers[0].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise ClaimError("Paperclip claim recovery marker is invalid") from None
        if not isinstance(loaded, dict) or not loaded.get("requestId") or not loaded.get("companyId"):
            raise ClaimError("Paperclip claim recovery marker is invalid")
        marker = {
            "requestId": str(loaded["requestId"]),
            "companyId": str(loaded["companyId"]),
        }
        if loaded.get("kind") == REPLACEMENT_MARKER_KIND:
            if not loaded.get("agentId") or not loaded.get("keyId"):
                raise ClaimError("Paperclip replacement-key recovery marker is invalid")
            marker.update(
                {
                    "kind": REPLACEMENT_MARKER_KIND,
                    "agentId": str(loaded["agentId"]),
                    "keyId": str(loaded["keyId"]),
                }
            )
        if loaded.get("companyId") != company_id and token:
            raise ClaimError("Paperclip claim recovery marker does not match the persisted identity")
        if token and marker.get("agentId") and marker.get("agentId") != agent_id:
            raise ClaimError("Paperclip replacement-key marker does not match the persisted identity")
        if receipt is not None and marker.get("keyId") and receipt.get("keyId") != marker.get("keyId"):
            raise ClaimError("Paperclip replacement-key marker does not match the claim receipt")

    stage: dict[str, Any] | None = None
    stage_path = claim_stage_path(profile_dir)
    if stage_path.exists():
        staged = load_claim_stage(profile_dir)
        stage = {"requestId": staged["id"], "companyId": staged["companyId"]}
        if token and staged["companyId"] != company_id:
            raise ClaimError("staged Paperclip claim does not match the persisted identity")

    return {
        "credentialPresent": bool(token),
        "companyId": company_id or None,
        "agentId": agent_id or None,
        "receipt": receipt,
        "marker": marker,
        "stage": stage,
    }


def validate_claim_state(state: dict, *, require_secret: bool) -> tuple[str, str, str]:
    request_id = str(state.get("id") or "")
    company_id = str(state.get("companyId") or "")
    claim_secret = str(state.get("claimSecret") or "")
    if not re.fullmatch(r"[0-9a-fA-F-]{20,}", request_id) or not company_id:
        raise ClaimError("pending join state is incomplete")
    if require_secret and len(claim_secret) < 16:
        raise ClaimError("pending join state is missing its claim secret")
    return request_id, company_id, claim_secret


def load_claim_stage(profile_dir: pathlib.Path) -> dict[str, str]:
    stage_path = claim_stage_path(profile_dir)
    require_runtime_secret(stage_path, "staged Paperclip claim")
    try:
        loaded = json.loads(stage_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ClaimError("staged Paperclip claim is invalid") from None
    if not isinstance(loaded, dict):
        raise ClaimError("staged Paperclip claim is invalid")
    request_id, company_id, claim_secret = validate_claim_state(loaded, require_secret=True)
    return {"id": request_id, "companyId": company_id, "claimSecret": claim_secret}


def stage_claim(profile_dir: pathlib.Path, state: dict) -> dict[str, str]:
    target = profile_preflight(profile_dir)
    request_id, company_id, claim_secret = validate_claim_state(state, require_secret=True)
    if parse_env(target).get("PAPERCLIP_API_KEY"):
        raise ClaimError("a Paperclip credential already exists; refusing to stage another claim")
    stage_path = claim_stage_path(profile_dir, create_parent=True)
    if stage_path.exists():
        existing = load_claim_stage(profile_dir)
        if existing != {"id": request_id, "companyId": company_id, "claimSecret": claim_secret}:
            raise ClaimError("a different Paperclip claim is already staged")
    else:
        atomic_write(
            stage_path,
            json.dumps(
                {"id": request_id, "companyId": company_id, "claimSecret": claim_secret},
                separators=(",", ":"),
            ).encode()
            + b"\n",
        )
    require_runtime_secret(stage_path, "staged Paperclip claim")
    return {"requestId": request_id, "companyId": company_id}


def resume_claim(profile_dir: pathlib.Path) -> dict[str, str | bool]:
    staged = load_claim_stage(profile_dir)
    request_id = staged["id"]
    company_id = staged["companyId"]
    status = recovery_status(profile_dir)
    receipt = status.get("receipt")
    if isinstance(receipt, dict):
        if receipt.get("requestId") != request_id or receipt.get("companyId") != company_id:
            raise ClaimError("staged Paperclip claim does not match the existing receipt")
        result: dict[str, str | bool] = {
            "companyId": company_id,
            "agentId": str(receipt.get("agentId") or ""),
            "recovered": True,
        }
    else:
        result = claim(profile_dir, staged)
    stage_path = claim_stage_path(profile_dir)
    stage_path.unlink(missing_ok=True)
    fsync_directory(stage_path.parent)
    return result


def install_replacement_key(profile_dir: pathlib.Path, state: dict) -> dict[str, str | bool]:
    target = profile_preflight(profile_dir)
    request_id = str(state.get("requestId") or "")
    company_id = str(state.get("companyId") or "")
    agent_id = str(state.get("agentId") or "")
    key_id = str(state.get("keyId") or "")
    token = str(state.get("token") or "")
    if (
        not re.fullmatch(r"[0-9a-fA-F-]{20,}", request_id)
        or not company_id
        or not agent_id
        or not key_id
        or not token.startswith("pcp_")
    ):
        raise ClaimError("replacement Paperclip credential state is incomplete")
    if parse_env(target).get("PAPERCLIP_API_KEY"):
        raise ClaimError("a Paperclip credential already exists; refusing to overwrite it")

    markers = sorted(profile_dir.glob(".paperclip-claim-*.pending"))
    if len(markers) > 1:
        raise ClaimError("multiple Paperclip claim recovery markers exist")
    marker_path = profile_dir / f".paperclip-claim-{request_id}.pending"
    if markers:
        if markers[0] != marker_path:
            raise ClaimError("Paperclip claim recovery marker has an unexpected request identifier")
        require_runtime_secret(markers[0], "Paperclip claim recovery marker")
        try:
            marker = json.loads(markers[0].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise ClaimError("Paperclip claim recovery marker is invalid") from None
        if not isinstance(marker, dict) or marker.get("requestId") != request_id or marker.get("companyId") != company_id:
            raise ClaimError("Paperclip claim recovery marker does not match replacement state")
        if marker.get("agentId") not in (None, agent_id):
            raise ClaimError("Paperclip claim recovery marker does not match replacement agent")

    stage_path = claim_stage_path(profile_dir)
    if stage_path.exists():
        staged = load_claim_stage(profile_dir)
        if staged["id"] != request_id or staged["companyId"] != company_id:
            raise ClaimError("staged Paperclip claim does not match replacement state")

    api_url = os.environ.get("PAPERCLIP_API_URL", "http://paperclip:3100").rstrip("/")
    atomic_write(
        marker_path,
        json.dumps(
            {
                "kind": REPLACEMENT_MARKER_KIND,
                "requestId": request_id,
                "companyId": company_id,
                "agentId": agent_id,
                "keyId": key_id,
            },
            separators=(",", ":"),
        ).encode()
        + b"\n",
    )
    require_runtime_secret(marker_path, "Paperclip replacement-key recovery marker")
    previous = target.read_bytes() if target.exists() else None
    payload = render_env(target, api_url, token, company_id, agent_id)
    atomic_write(target, payload)
    try:
        require_runtime_secret(target, "persisted Paperclip credential file")
        verify_identity(api_url, token, company_id, agent_id)
    except Exception:
        if previous is None:
            target.unlink(missing_ok=True)
            fsync_directory(profile_dir)
        else:
            atomic_write(target, previous)
        raise
    receipt = profile_dir / ".paperclip-claim-receipt.json"
    atomic_write(
        receipt,
        json.dumps(
            {
                "requestId": request_id,
                "companyId": company_id,
                "agentId": agent_id,
                "keyId": key_id,
            },
            separators=(",", ":"),
        ).encode()
        + b"\n",
    )
    require_runtime_secret(receipt, "Paperclip claim receipt")
    marker_path.unlink(missing_ok=True)
    stage_path.unlink(missing_ok=True)
    fsync_directory(stage_path.parent)
    fsync_directory(profile_dir)
    return {"companyId": company_id, "agentId": agent_id, "recovered": True}


def recover_claim(profile_dir: pathlib.Path, state: dict) -> dict[str, str | bool]:
    request_id = str(state.get("id") or "")
    company_id = str(state.get("companyId") or "")
    if not re.fullmatch(r"[0-9a-fA-F-]{20,}", request_id) or not company_id:
        raise ClaimError("claim recovery state is incomplete")
    status = recovery_status(profile_dir)
    marker = status.get("marker")
    if not status.get("credentialPresent") or not isinstance(marker, dict):
        raise ClaimError("claim recovery requires a verified persisted credential and matching marker")
    if marker.get("requestId") != request_id or marker.get("companyId") != company_id:
        raise ClaimError("claim recovery state does not match the retained marker")
    agent_id = str(status.get("agentId") or "")
    if marker.get("agentId") and marker.get("agentId") != agent_id:
        raise ClaimError("claim recovery marker does not match the verified agent")
    key_id = str(marker.get("keyId") or "")
    existing_receipt = status.get("receipt")
    if isinstance(existing_receipt, dict):
        if (
            existing_receipt.get("requestId") != request_id
            or existing_receipt.get("companyId") != company_id
            or existing_receipt.get("agentId") != agent_id
            or (key_id and existing_receipt.get("keyId") != key_id)
        ):
            raise ClaimError("claim recovery marker does not match the existing receipt")
    stage_path = claim_stage_path(profile_dir)
    if stage_path.exists():
        staged = load_claim_stage(profile_dir)
        if staged["id"] != request_id or staged["companyId"] != company_id:
            raise ClaimError("staged Paperclip claim does not match the recovered credential")
    receipt = profile_dir / ".paperclip-claim-receipt.json"
    atomic_write(
        receipt,
        json.dumps(
            {
                "requestId": request_id,
                "companyId": company_id,
                "agentId": agent_id,
                **({"keyId": key_id} if key_id else {}),
            },
            separators=(",", ":"),
        ).encode()
        + b"\n",
    )
    require_runtime_secret(receipt, "Paperclip claim receipt")
    marker_path = profile_dir / f".paperclip-claim-{request_id}.pending"
    marker_path.unlink(missing_ok=True)
    if stage_path.exists():
        stage_path.unlink(missing_ok=True)
        fsync_directory(stage_path.parent)
    fsync_directory(profile_dir)
    return {"companyId": company_id, "agentId": agent_id, "recovered": True}


def discard_replacement_marker(profile_dir: pathlib.Path, state: dict) -> dict[str, str | bool]:
    target = profile_preflight(profile_dir)
    request_id = str(state.get("requestId") or "")
    company_id = str(state.get("companyId") or "")
    agent_id = str(state.get("agentId") or "")
    key_id = str(state.get("keyId") or "")
    if not request_id or not company_id or not agent_id or not key_id:
        raise ClaimError("replacement marker cleanup state is incomplete")
    if parse_env(target).get("PAPERCLIP_API_KEY"):
        raise ClaimError("refusing to discard replacement marker while a credential is persisted")
    marker_path = profile_dir / f".paperclip-claim-{request_id}.pending"
    require_runtime_secret(marker_path, "Paperclip replacement-key recovery marker")
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ClaimError("Paperclip replacement-key recovery marker is invalid") from None
    expected = {
        "kind": REPLACEMENT_MARKER_KIND,
        "requestId": request_id,
        "companyId": company_id,
        "agentId": agent_id,
        "keyId": key_id,
    }
    if marker != expected:
        raise ClaimError("Paperclip replacement-key recovery marker does not exactly match cleanup state")
    marker_path.unlink()
    fsync_directory(profile_dir)
    return {"requestId": request_id, "keyId": key_id, "discarded": True}


def claim(profile_dir: pathlib.Path, state: dict) -> dict[str, str | bool]:
    target = profile_preflight(profile_dir)
    request_id, company_id, claim_secret = validate_claim_state(state, require_secret=True)

    api_url = os.environ.get("PAPERCLIP_API_URL", "http://paperclip:3100").rstrip("/")
    marker = profile_dir / f".paperclip-claim-{request_id}.pending"
    receipt = profile_dir / ".paperclip-claim-receipt.json"
    existing = parse_env(target)
    existing_token = existing.get("PAPERCLIP_API_KEY", "")

    if existing_token:
        if not marker.exists():
            raise ClaimError("a Paperclip credential already exists; refusing to overwrite it")
        require_runtime_secret(marker, "Paperclip claim recovery marker")
        existing_company = existing.get("PAPERCLIP_COMPANY_ID", "")
        existing_agent = existing.get("PAPERCLIP_AGENT_ID", "")
        if existing_company != company_id or not existing_agent:
            raise ClaimError("an interrupted claim left an unexpected persisted identity")
        verify_identity(api_url, existing_token, existing_company, existing_agent)
        atomic_write(
            receipt,
            json.dumps({"requestId": request_id, "companyId": existing_company, "agentId": existing_agent}).encode()
            + b"\n",
        )
        require_runtime_secret(receipt, "Paperclip claim receipt")
        marker.unlink(missing_ok=True)
        fsync_directory(profile_dir)
        return {"companyId": existing_company, "agentId": existing_agent, "recovered": True}

    atomic_write(marker, json.dumps({"requestId": request_id, "companyId": company_id}).encode() + b"\n")
    require_runtime_secret(marker, "Paperclip claim recovery marker")
    temp_fd, temp_name = tempfile.mkstemp(prefix=".env.claim-", suffix=".tmp", dir=profile_dir)
    temp_path = pathlib.Path(temp_name)
    os.fchmod(temp_fd, 0o600)

    consumed = False
    try:
        response = request_json(
            f"{api_url}/api/join-requests/{request_id}/claim-api-key",
            {"claimSecret": claim_secret},
        )
        consumed = True
        token = str(response.get("token") or "")
        key_id = str(response.get("keyId") or "")
        agent_id = str(response.get("agentId") or "")
        if not token.startswith("pcp_") or not key_id or not agent_id:
            raise ConsumedClaimError("Paperclip returned an invalid claimed credential")

        payload = render_env(target, api_url, token, company_id, agent_id)
        with os.fdopen(temp_fd, "wb", closefd=True) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temp_fd = -1
        os.replace(temp_path, target)
        fsync_directory(profile_dir)
        if stat.S_IMODE(target.stat().st_mode) != 0o600:
            raise ConsumedClaimError("persisted Paperclip credential file permissions are unsafe")
        require_runtime_secret(target, "persisted Paperclip credential file")
        verify_identity(api_url, token, company_id, agent_id)
        atomic_write(
            receipt,
            json.dumps(
                {"requestId": request_id, "companyId": company_id, "agentId": agent_id, "keyId": key_id},
                separators=(",", ":"),
            ).encode()
            + b"\n",
        )
        require_runtime_secret(receipt, "Paperclip claim receipt")
        marker.unlink(missing_ok=True)
        fsync_directory(profile_dir)
        return {"companyId": company_id, "agentId": agent_id, "recovered": False}
    except ClaimError:
        if consumed:
            raise ConsumedClaimError(
                "the one-time claim may have been consumed; inspect the persisted profile before revoking and re-inviting"
            ) from None
        raise
    except Exception:
        if consumed:
            raise ConsumedClaimError(
                "the one-time claim may have been consumed; inspect the persisted profile before revoking and re-inviting"
            ) from None
        raise ClaimError("claim failed before Paperclip confirmed credential creation") from None
    finally:
        if temp_fd >= 0:
            os.close(temp_fd)
        temp_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=("preflight", "status", "stage", "resume", "install", "claim", "recover", "discard-install"),
    )
    parser.add_argument("--profile-dir", default="/opt/data")
    args = parser.parse_args()
    profile_dir = pathlib.Path(args.profile_dir)
    try:
        profile_preflight(profile_dir)
        if args.action == "preflight":
            print("Hermes claim destination preflight passed.")
            return 0
        if args.action == "status":
            print(json.dumps(recovery_status(profile_dir), separators=(",", ":")))
            return 0
        if args.action == "resume":
            result = resume_claim(profile_dir)
        else:
            state = json.load(sys.stdin)
            if args.action == "stage":
                result = stage_claim(profile_dir, state)
            elif args.action == "install":
                result = install_replacement_key(profile_dir, state)
            elif args.action == "claim":
                result = claim(profile_dir, state)
            elif args.action == "discard-install":
                result = discard_replacement_marker(profile_dir, state)
            else:
                result = recover_claim(profile_dir, state)
        print(json.dumps(result, separators=(",", ":")))
        return 0
    except (ClaimError, json.JSONDecodeError) as exc:
        print(f"Hermes claim helper error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
