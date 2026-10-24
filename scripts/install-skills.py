#!/usr/bin/env python3
"""Preview or apply an exact profile skill pack through pinned NixKit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PROFILE_MAP = {
    "lnx": "default", "pulse": "pulse", "algua": "algua", "meabeclick": "meabeclick",
    "meabeclickux": "meabeclickux", "meabeclickeng": "meabeclickeng", "meabeclickgrowth": "meabeclickgrowth",
}
SHA = re.compile(r"^[a-f0-9]{40}$")
SKILL = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class Refusal(RuntimeError):
    pass


def _run(command: list[str], cwd: Path) -> str:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise Refusal(f"command failed: {' '.join(command)}: {detail}")
    return result.stdout.strip()


def _check_no_symlink(path: Path) -> None:
    current = path
    while True:
        if current.is_symlink():
            raise Refusal(f"profile home path contains a symlink: {current}")
        if current == current.parent:
            break
        current = current.parent


def _load_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Refusal(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise Refusal(f"{label} root must be an object")
    return value


def _approval_skills(path: Path, profile: str) -> tuple[set[str], str]:
    approval = _load_json(path, "approval receipt")
    required = {"schema_version", "proposal_id", "profile", "skills", "approved_by", "approved_at", "manifest_commit"}
    if set(approval) != required or approval.get("schema_version") != 1:
        raise Refusal("malformed approval receipt")
    if approval.get("profile") != profile or approval.get("approved_by") != "Lior":
        raise Refusal("approval receipt is not bound to this profile and Lior")
    if not isinstance(approval.get("manifest_commit"), str) or not SHA.fullmatch(approval["manifest_commit"]):
        raise Refusal("approval receipt has invalid manifest_commit")
    skills = approval.get("skills")
    if not isinstance(skills, list) or not skills or len(skills) != len(set(skills)) or any(not isinstance(x, str) or not SKILL.fullmatch(x) for x in skills):
        raise Refusal("approval receipt has invalid skills")
    if not isinstance(approval.get("approved_at"), str) or "T" not in approval["approved_at"]:
        raise Refusal("approval receipt has invalid approved_at")
    return set(skills), approval["manifest_commit"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, choices=sorted(PROFILE_MAP))
    parser.add_argument("--nixkit", type=Path, default=Path.home() / "src/nixkit")
    parser.add_argument("--manifest", type=Path, default=ROOT / "skills/packs.json")
    parser.add_argument("--skill", action="append", default=[], help="Future approved addition; repeatable")
    parser.add_argument("--approval", type=Path, help="Tracked Lior approval receipt for --skill additions")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        manifest = _load_json(args.manifest, "pack manifest")
        pin = manifest.get("nixkit", {})
        commit, source_hash, node_runtime = pin.get("commit"), pin.get("sources_sha256"), pin.get("node_runtime")
        if not isinstance(commit, str) or not SHA.fullmatch(commit) or not isinstance(source_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", source_hash) or node_runtime != "24.22.1":
            raise Refusal("manifest has invalid NixKit pins")
        checkout = args.nixkit.expanduser().absolute()
        if checkout.is_symlink() or not checkout.is_dir():
            raise Refusal("NixKit checkout must be an existing non-symlink directory")
        if _run(["git", "rev-parse", "HEAD"], checkout) != commit:
            raise Refusal(f"NixKit HEAD does not match pinned commit {commit}")
        if _run(["git", "status", "--porcelain", "--untracked-files=all"], checkout):
            raise Refusal("NixKit checkout must be clean, including untracked files")
        sources = checkout / "sources.json"
        try:
            actual_hash = hashlib.sha256(sources.read_bytes()).hexdigest()
        except OSError as exc:
            raise Refusal(f"cannot read pinned NixKit sources.json: {exc}") from exc
        if actual_hash != source_hash:
            raise Refusal("NixKit sources.json content does not match the audited hash")
        installer = checkout / "install.mjs"
        if not installer.is_file() or installer.is_symlink():
            raise Refusal("NixKit install.mjs is missing or a symlink")
        npx = shutil.which("npx")
        if npx is None or not os.access(npx, os.X_OK):
            raise Refusal("executable npx is required for the pinned Node runtime")
        packs, assignments = manifest.get("packs"), manifest.get("profiles")
        if not isinstance(packs, dict) or not isinstance(assignments, dict) or args.profile not in assignments:
            raise Refusal("pack manifest does not define the requested profile")
        baseline = {skill for pack in assignments[args.profile] for skill in packs.get(pack, [])}
        additions = set(args.skill)
        if any(not SKILL.fullmatch(skill) for skill in additions):
            raise Refusal("invalid requested skill name")
        declared_additions = manifest.get("approved_additions", {}).get(args.profile)
        if not isinstance(declared_additions, list):
            raise Refusal("pack manifest lacks a profile-specific approved_additions list")
        if additions:
            if additions != set(declared_additions):
                raise Refusal("requested additions require a profile-specific manifest PR and Lior approval")
            if args.approval is None:
                raise Refusal("future skill additions require a tracked Lior approval receipt")
            approval_path = args.approval.expanduser().absolute()
            try:
                approval_path.relative_to(ROOT)
            except ValueError as exc:
                raise Refusal("approval receipt must be tracked inside this repository") from exc
            _run(["git", "ls-files", "--error-unmatch", str(approval_path.relative_to(ROOT))], ROOT)
            approved, approved_commit = _approval_skills(approval_path, args.profile)
            repository_commit = _run(["git", "rev-parse", "HEAD"], ROOT)
            if additions != approved or approved_commit != repository_commit:
                raise Refusal("requested skills/manifest commit do not exactly match the approval receipt")
        elif args.approval is not None or declared_additions:
            raise Refusal("declared additions require matching --skill values and an approval receipt")
        skills = sorted(baseline | additions)
        hermes_home = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser().absolute()
        profile_home = hermes_home if PROFILE_MAP[args.profile] == "default" else hermes_home / "profiles" / PROFILE_MAP[args.profile]
        _check_no_symlink(profile_home)
        command = ["npx", "--yes", f"node@{node_runtime}", str(installer), "--apply", "--skills", "--agent", "hermes", "--prefix", str(profile_home)]
        for skill in skills:
            command.extend(["--skill", skill])
        print(("APPLY" if args.apply else "PREVIEW") + f" profile={args.profile} home={profile_home}")
        print("command:", " ".join(json.dumps(value) for value in command))
        if not args.apply:
            return 0
        profile_home.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(command, cwd=checkout, check=False)
        if result.returncode:
            raise Refusal(f"NixKit refused installation (exit {result.returncode}); existing conflicts were preserved")
        print(f"Installed or preserved {len(skills)} audited skill(s) for {args.profile}.")
        return 0
    except Refusal as exc:
        print(f"Refusing: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
