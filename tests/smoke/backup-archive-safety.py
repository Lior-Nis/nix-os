#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import io
from pathlib import Path
import subprocess
import tarfile
import tempfile


REPO = Path(__file__).resolve().parents[2]
SAFE_EXTRACT = REPO / "scripts/safe-extract-tar"
VERIFY_PAYLOAD = REPO / "scripts/verify-backup-checksums"
VERIFY_SIDECAR = REPO / "scripts/verify-artifact-sidecar"


def member(name: str, content: bytes | None = None, kind: bytes | None = None) -> tuple[tarfile.TarInfo, bytes | None]:
    info = tarfile.TarInfo(name)
    if kind is not None:
        info.type = kind
    elif content is None:
        info.type = tarfile.DIRTYPE
    else:
        info.type = tarfile.REGTYPE
        info.size = len(content)
    return info, content


def make_tar(path: Path, members: list[tuple[tarfile.TarInfo, bytes | None]]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for info, content in members:
            archive.addfile(info, None if content is None else io.BytesIO(content))


def rejected(*arguments: object) -> None:
    result = subprocess.run(
        [str(argument) for argument in arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    assert result.returncode != 0, result.stdout


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="nix-os-archive-safety.") as raw:
        root = Path(raw)
        valid = root / "valid.tar.gz"
        make_tar(valid, [member("payload"), member("payload/file", b"ok")])
        subprocess.run([SAFE_EXTRACT, "--required-prefix", "payload", valid, root / "out"], check=True)

        traversal = root / "traversal.tar.gz"
        make_tar(traversal, [member("payload"), member("payload/../../escape", b"bad")])
        rejected(SAFE_EXTRACT, "--required-prefix", "payload", traversal, root / "traversal-out")
        assert not (root / "escape").exists()

        duplicate = root / "duplicate.tar.gz"
        make_tar(duplicate, [member("payload"), member("payload/file", b"one"), member("payload/file", b"two")])
        rejected(SAFE_EXTRACT, "--required-prefix", "payload", duplicate, root / "duplicate-out")

        link_info, _ = member("payload/link", kind=tarfile.SYMTYPE)
        link_info.linkname = "/tmp/escape"
        links = root / "links.tar.gz"
        make_tar(links, [member("payload"), (link_info, None)])
        rejected(SAFE_EXTRACT, "--required-prefix", "payload", links, root / "links-out")

        dot_root = root / "dot-root.tar.gz"
        make_tar(dot_root, [member("."), member("./state", b"ok")])
        subprocess.run([SAFE_EXTRACT, "--validate-only", "--allow-dot-root", dot_root], check=True)

        unsafe_state = root / "unsafe-state.tar.gz"
        make_tar(unsafe_state, [member("."), member("./../escape", b"bad")])
        rejected(SAFE_EXTRACT, "--validate-only", "--allow-dot-root", unsafe_state)

        payload = root / "checksums"
        payload.mkdir()
        (payload / "file").write_bytes(b"ok")
        (payload / "SHA256SUMS").write_text(f"{'0' * 64}  ../escape\n", encoding="utf-8")
        rejected(VERIFY_PAYLOAD, payload)

        artifact = root / "artifact"
        artifact.write_bytes(b"ciphertext")
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        (root / "artifact.sha256").write_text(f"{digest}  ../artifact\n", encoding="utf-8")
        rejected(VERIFY_SIDECAR, artifact)

    print("Backup archive safety tests passed.")


if __name__ == "__main__":
    main()
