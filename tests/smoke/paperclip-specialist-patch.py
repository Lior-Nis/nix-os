#!/usr/bin/env python3
"""Prove the specialist patcher's exact-byte and fail-closed semantics."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
PATCHER = ROOT / "deploy/paperclip/patch-specialist-runtime.py"
spec = importlib.util.spec_from_file_location("paperclip_specialist_patch", PATCHER)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        target = root / "fixture.txt"
        target.write_text("pinned\n")
        patch_spec = module.PatchSpec(
            "fixture.txt",
            module._digest(b"pinned\n"),
            module._digest(b"patched\n"),
            lambda value: value.replace("pinned", "patched"),
        )
        specs = (patch_spec,)
        module.apply_patch(root, specs)
        module.verify_patch(root, specs)
        module.apply_patch(root, specs)
        assert target.read_text() == "patched\n"

        target.write_text("tampered\n")
        for operation in (module.verify_patch, module.apply_patch):
            try:
                operation(root, specs)
            except RuntimeError as error:
                assert any(message in str(error) for message in (
                    "unexpected bytes", "verification failed", "unsupported source",
                ))
            else:
                raise AssertionError("tampered patch target did not fail closed")

    print("paperclip specialist patcher fail-closed behavior: ok")


if __name__ == "__main__":
    main()
