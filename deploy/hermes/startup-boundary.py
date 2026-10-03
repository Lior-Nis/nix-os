#!/usr/bin/env python3
"""Enforce the root-owned Telegram mode and canonical profile-env boundary."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat
import tempfile

from dotenv.parser import Binding, parse_stream


PROFILE_ENV = Path("/opt/data/.env")
MODE_FILE = Path("/run/nix/hermes-telegram-mode.env")
HERMES_UID = 10000
HERMES_GID = 10000
EXTERNAL_ONLY_KEYS = {
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ALLOWED_USERS",
    "TELEGRAM_ALLOW_ALL_USERS",
    "GATEWAY_ALLOW_ALL_USERS",
}
MODE_BYTES = {
    b"HERMES_TELEGRAM_MODE=disabled\n": "disabled",
    b"HERMES_TELEGRAM_MODE=live\n": "live",
}


def fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def validate_mode_marker(path: Path = MODE_FILE) -> str:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        raise RuntimeError("Telegram mode marker is missing or unsafe") from None
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError("Telegram mode marker is missing or unsafe")
    if metadata.st_uid != 0 or metadata.st_gid != 0:
        raise RuntimeError("Telegram mode marker has unexpected ownership")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise RuntimeError("Telegram mode marker must have mode 0600")
    try:
        return MODE_BYTES[path.read_bytes()]
    except KeyError:
        raise RuntimeError("Telegram mode marker has invalid content") from None


def profile_bindings(path: Path) -> tuple[bytes, list[Binding]]:
    original = path.read_bytes()
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        bindings = list(parse_stream(stream))
    if any(binding.error for binding in bindings):
        raise RuntimeError("Hermes profile environment contains syntax the pinned dotenv parser rejected")
    return original, bindings


def sanitize_profile_env(path: Path = PROFILE_ENV, *, check_only: bool = False) -> bool:
    if not path.exists():
        return False
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Hermes profile environment is missing or unsafe")
    metadata = path.stat()
    if metadata.st_uid != HERMES_UID or metadata.st_gid != HERMES_GID:
        raise RuntimeError("Hermes profile environment has unexpected ownership")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise RuntimeError("Hermes profile environment must have mode 0600")

    original, bindings = profile_bindings(path)
    forbidden = [binding for binding in bindings if binding.key in EXTERNAL_ONLY_KEYS]
    if check_only:
        if forbidden:
            raise RuntimeError("Hermes profile environment contains external-only Telegram controls")
        return False

    # Reading as utf-8-sig gives the same BOM semantics as the pinned Hermes
    # dotenv loader. Rewriting also removes a BOM even when no key was removed.
    payload = "".join(
        binding.original.string for binding in bindings if binding.key not in EXTERNAL_ONLY_KEYS
    ).encode("utf-8")
    if payload == original:
        return False

    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        os.fchmod(fd, 0o600)
        os.fchown(fd, HERMES_UID, HERMES_GID)
        with os.fdopen(fd, "wb", closefd=True) as stream:
            stream.write(payload)
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
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-profile-only", action="store_true")
    args = parser.parse_args()
    if args.check_profile_only:
        sanitize_profile_env(check_only=True)
        return
    mode = validate_mode_marker()
    sanitize_profile_env()
    print(mode)


if __name__ == "__main__":
    main()
