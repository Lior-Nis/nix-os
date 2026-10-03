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


def claim(profile_dir: pathlib.Path, state: dict) -> dict[str, str | bool]:
    target = profile_preflight(profile_dir)
    request_id = str(state.get("id") or "")
    company_id = str(state.get("companyId") or "")
    claim_secret = str(state.get("claimSecret") or "")
    if not re.fullmatch(r"[0-9a-fA-F-]{20,}", request_id) or not company_id or not claim_secret:
        raise ClaimError("pending join state is incomplete")

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
        agent_id = str(response.get("agentId") or "")
        if not token.startswith("pcp_") or not agent_id:
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
            json.dumps({"requestId": request_id, "companyId": company_id, "agentId": agent_id}).encode() + b"\n",
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
    parser.add_argument("action", choices=("preflight", "claim"))
    parser.add_argument("--profile-dir", default="/opt/data")
    args = parser.parse_args()
    profile_dir = pathlib.Path(args.profile_dir)
    try:
        profile_preflight(profile_dir)
        if args.action == "preflight":
            print("Hermes claim destination preflight passed.")
            return 0
        state = json.load(sys.stdin)
        result = claim(profile_dir, state)
        print(json.dumps(result, separators=(",", ":")))
        return 0
    except (ClaimError, json.JSONDecodeError) as exc:
        print(f"Hermes claim helper error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
