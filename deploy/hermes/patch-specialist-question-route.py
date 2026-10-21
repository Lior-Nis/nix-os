#!/usr/bin/env python3
"""Install the one pinned Hermes per-route secret compatibility fix."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import tempfile


TARGET = Path("/opt/hermes/gateway/platforms/webhook.py")
ORIGINAL_SHA256 = "1651b461e6c594107390bfab5f31f6c3fdad48b9269482ccdf547d78cfa30fe3"
PATCHED_SHA256 = "c5fd3f413e5add5efff0f0d940a1fb57505014e442dec5a6db795d5f39507c1c"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def transform(source: str) -> str:
    anchor = '_GH_TOKEN_VARS = ("GH_TOKEN", "GITHUB_TOKEN")\n\n\n'
    helper = '''_GH_TOKEN_VARS = ("GH_TOKEN", "GITHUB_TOKEN")
_NIX_SPECIALIST_SECRET_PLACEHOLDER = "${NIX_SPECIALIST_QUESTION_DELIVERY_SECRET}"


def _nix_effective_route_secret(route: dict, global_secret: str) -> str:
    """Resolve only Nix's reviewed static specialist-route placeholder."""
    secret = route.get("secret", global_secret)
    if secret == _NIX_SPECIALIST_SECRET_PLACEHOLDER:
        return os.environ.get("NIX_SPECIALIST_QUESTION_DELIVERY_SECRET", "")
    return secret


'''
    if source.count(anchor) != 1:
        raise RuntimeError("Hermes specialist route patch refused: helper anchor drifted")
    source = source.replace(anchor, helper, 1)
    old = 'route.get("secret", self._global_secret)'
    if source.count(old) != 2:
        raise RuntimeError("Hermes specialist route patch refused: secret anchors drifted")
    source = source.replace(old, '_nix_effective_route_secret(route, self._global_secret)')
    handler_old = 'route_config.get("secret", self._global_secret)'
    if source.count(handler_old) != 1:
        raise RuntimeError("Hermes specialist route patch refused: handler secret anchor drifted")
    return source.replace(
        handler_old,
        '_nix_effective_route_secret(route_config, self._global_secret)',
        1,
    )


def atomic_write(path: Path, data: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    original = TARGET.read_bytes()
    current = digest(original)
    if args.verify:
        if current != PATCHED_SHA256:
            raise SystemExit("Hermes specialist route patch verification failed")
        return
    if current == PATCHED_SHA256:
        return
    if current != ORIGINAL_SHA256:
        raise SystemExit("Hermes specialist route patch refused: unsupported source")
    patched = transform(original.decode("utf-8")).encode("utf-8")
    if digest(patched) != PATCHED_SHA256:
        raise SystemExit("Hermes specialist route patch refused: output mismatch")
    atomic_write(TARGET, patched)


if __name__ == "__main__":
    main()
