#!/usr/bin/env python3
"""Validate the safe, declarative Nix OS repository using stdlib only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

REQUIRED_FILES = {
    "README.md",
    "CONTRIBUTING.md",
    ".gitignore",
    "nix-os.yaml",
    "docs/ARCHITECTURE.md",
    "docs/STATE-AND-SECRETS.md",
    "config/hermes.example.yaml",
    "scripts/bootstrap.sh",
    "scripts/verify.py",
    "tests/test_repository.py",
    ".github/workflows/ci.yml",
}
EXPECTED_PROFILES = {
    "lnx", "pulse", "algua", "meabeclick", "meabeclickux",
    "meabeclickeng", "meabeclickgrowth",
}
EXPECTED_PROJECTS = {"pulse", "algua", "meabeclick"}
EXPECTED_PROFILE_LAYOUT = {
    "lnx": ("default", "orchestrator", None, ["pulse", "algua", "meabeclick"]),
    "pulse": ("pulse", "lead", None, ["pulse"]),
    "algua": ("algua", "lead", None, ["algua"]),
    "meabeclick": ("meabeclick", "lead", None, ["meabeclick"]),
    "meabeclickux": ("meabeclickux", "specialist", "meabeclick", ["meabeclick"]),
    "meabeclickeng": ("meabeclickeng", "specialist", "meabeclick", ["meabeclick"]),
    "meabeclickgrowth": ("meabeclickgrowth", "specialist", "meabeclick", ["meabeclick"]),
}
EXPECTED_PROJECT_LAYOUT = {
    "pulse": ("Pulse", "pulse", "pulse", "${HOME}/Projects/pulse"),
    "algua": ("Algua", "algua", "algua", "${HOME}/Projects/algua"),
    "meabeclick": ("MeaBeclick", "meabeclick", "meabeclick", "${HOME}/Projects/meabeclick"),
}
EXPECTED_PLANES = {
    "human_messaging": "discord",
    "lior_commitments": "todoist",
    "delegated_execution": "hermes-kanban",
    "durable_evidence": ["github", "project-docs"],
}
UNSAFE_BASENAMES = {
    ".env", "auth.json", "credentials.json", "token.json", "google_token.json",
    "cookies.txt", ".netrc", ".npmrc", ".pypirc", ".git-credentials",
    ".dockerconfigjson", "state.db", "kanban.db", "profile.yaml",
}
UNSAFE_SUFFIXES = {
    ".sqlite", ".sqlite3", ".db", ".log", ".jsonl", ".key", ".pem",
    ".p12", ".pfx", ".crt", ".cer",
}
UNSAFE_PARTS = {
    "sessions", "memories", "logs", "cache", "caches", "transcripts",
    "checkpoints", "backups", "runtime", "state-snapshots", "cron",
}
MAX_REPOSITORY_FILE_BYTES = 1_000_000
ABSOLUTE_HOME = re.compile(r"(?<![A-Za-z0-9_])/(?:home|Users)/[^\s`'\"/]+")
LEGACY_TERMS = ("paper" + "clip", "n" + "8n", "s" + "lack")
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN(?: [A-Z0-9]+)* PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    "OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9_-]{32,}\b"),
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "Discord bot token": re.compile(
        r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{20,30}\.[A-Za-z0-9_-]{6,8}\."
        r"[A-Za-z0-9_-]{25,45}(?![A-Za-z0-9_-])"
    ),
}
HERMES_PROFILE_NAME = re.compile(r"^[a-z0-9]+$")
SQLITE_SIDECAR = re.compile(r"^.+\.(?:db|sqlite|sqlite3)-(?:wal|shm|journal)$")


def _load_manifest(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append("missing required file: nix-os.yaml")
        return {}
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"nix-os.yaml must be valid JSON (a YAML subset): {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append("nix-os.yaml root must be an object")
        return {}
    return value


def _ids(items: Any, label: str, errors: list[str]) -> tuple[list[dict[str, Any]], set[str]]:
    if not isinstance(items, list):
        errors.append(f"manifest {label} must be a list")
        return [], set()
    records: list[dict[str, Any]] = []
    identifiers: list[str] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"manifest {label}[{index}] must be an object")
            continue
        identifier = item.get("id")
        if not isinstance(identifier, str) or not identifier:
            errors.append(f"manifest {label}[{index}] has no valid id")
            continue
        records.append(item)
        identifiers.append(identifier)
    duplicates = sorted({item for item in identifiers if identifiers.count(item) > 1})
    if duplicates:
        errors.append(f"duplicate {label} ids: {', '.join(duplicates)}")
    return records, set(identifiers)


def _validate_manifest(root: Path, manifest: dict[str, Any], errors: list[str]) -> None:
    if manifest.get("schema_version") != 1:
        errors.append("manifest schema_version must be 1")
    profiles, profile_ids = _ids(manifest.get("profiles"), "profiles", errors)
    projects, project_ids = _ids(manifest.get("projects"), "projects", errors)
    if profile_ids != EXPECTED_PROFILES:
        errors.append(f"manifest profiles must be exactly {sorted(EXPECTED_PROFILES)}")
    if project_ids != EXPECTED_PROJECTS:
        errors.append(f"manifest projects must be exactly {sorted(EXPECTED_PROJECTS)}")
    if manifest.get("orchestrator") != "lnx":
        errors.append("manifest orchestrator must be lnx")
    if manifest.get("discord_visible_profiles") != ["lnx"]:
        errors.append("exactly one initial Discord-visible profile is required: lnx")
    todoist = manifest.get("todoist")
    if not isinstance(todoist, dict) or todoist.get("cli") != "td" or todoist.get("scope") != "lior-only":
        errors.append("Todoist must use td and scope lior-only")
    if manifest.get("planes") != EXPECTED_PLANES:
        errors.append(f"authority planes must be exactly {EXPECTED_PLANES!r}")

    by_profile = {item["id"]: item for item in profiles}
    hermes_names: list[str] = []
    for item in profiles:
        profile_id = item["id"]
        hermes_name = item.get("hermes_profile")
        if not isinstance(hermes_name, str) or not HERMES_PROFILE_NAME.fullmatch(hermes_name):
            errors.append(f"profile {profile_id} has invalid Hermes profile name {hermes_name!r}")
        else:
            hermes_names.append(hermes_name)
        expected = EXPECTED_PROFILE_LAYOUT.get(profile_id)
        actual = (hermes_name, item.get("kind"), item.get("parent"), item.get("projects"))
        if expected is not None and actual != expected:
            errors.append(f"profile {profile_id} layout must be exactly {expected!r}")
        contract = root / "profiles" / profile_id / "ROLE.md"
        if not contract.is_file():
            errors.append(f"missing role contract for profile {profile_id}: profiles/{profile_id}/ROLE.md")
        refs = item.get("projects")
        if not isinstance(refs, list):
            errors.append(f"profile {profile_id} projects must be a list")
        else:
            for ref in refs:
                if ref not in project_ids:
                    errors.append(f"profile {profile_id} references unknown project {ref}")
        parent = item.get("parent")
        if parent is not None:
            if parent not in profile_ids:
                errors.append(f"profile {profile_id} parent references missing profile {parent}")
            elif by_profile.get(parent, {}).get("kind") != "lead":
                errors.append(f"profile {profile_id} parent {parent} is not a lead")

    board_ids: list[str] = []
    for item in projects:
        project_id = item["id"]
        expected_project = EXPECTED_PROJECT_LAYOUT.get(project_id)
        actual_project = (item.get("name"), item.get("lead"), item.get("board"), item.get("workspace"))
        if expected_project is not None and actual_project != expected_project:
            errors.append(f"project {project_id} layout must be exactly {expected_project!r}")
        lead = item.get("lead")
        if lead not in profile_ids:
            errors.append(f"project {project_id} lead references missing profile {lead}")
        elif by_profile.get(lead, {}).get("kind") != "lead":
            errors.append(f"project {project_id} lead {lead} is not a lead profile")
        elif project_id not in by_profile[lead].get("projects", []):
            errors.append(f"project {project_id} is not declared by lead {lead}")
        board = item.get("board")
        if not isinstance(board, str) or not board:
            errors.append(f"project {project_id} has no valid board")
        else:
            board_ids.append(board)

    if len(board_ids) != len(set(board_ids)):
        errors.append("project board references must be unique")
    if len(hermes_names) != len(set(hermes_names)):
        errors.append("Hermes profile names must be unique")


def _repository_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part in {".git", "__pycache__"} for part in relative.parts):
            continue
        if path.is_file():
            files.append(path)
    return sorted(files)


def _unsafe_name(relative: Path) -> bool:
    lowered = tuple(part.lower() for part in relative.parts)
    basename = lowered[-1]
    if (
        basename in UNSAFE_BASENAMES
        or basename.startswith(".env.")
        or basename.startswith("state.db-")
        or basename.startswith("kanban.db-")
        or SQLITE_SIDECAR.fullmatch(basename)
    ):
        return True
    if any(part in UNSAFE_PARTS for part in lowered[:-1]):
        return True
    return any(basename.endswith(suffix) for suffix in UNSAFE_SUFFIXES)


def _in_readme_migration_note(text: str, match_start: int) -> bool:
    before = text[:match_start].lower()
    last_h2 = before.rfind("\n## ")
    heading_end = before.find("\n", last_h2 + 1) if last_h2 >= 0 else -1
    heading = before[last_h2:heading_end] if last_h2 >= 0 and heading_end >= 0 else ""
    return "migration note" in heading


def _validate_files(root: Path, errors: list[str]) -> None:
    for path in _repository_files(root):
        relative = path.relative_to(root)
        rel = relative.as_posix()
        if _unsafe_name(relative):
            errors.append(f"unsafe secret/runtime filename present: {rel}")
        try:
            size = path.stat().st_size
        except OSError as exc:
            errors.append(f"cannot stat repository file {rel}: {exc}")
            continue
        if size > MAX_REPOSITORY_FILE_BYTES:
            errors.append(f"repository file is too large for safety inspection: {rel}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            errors.append(f"non-UTF-8 or binary repository file is not allowed: {rel}")
            continue
        except OSError as exc:
            errors.append(f"cannot read repository file {rel}: {exc}")
            continue
        if "\x00" in text:
            errors.append(f"binary repository file is not allowed: {rel}")
            continue
        if ABSOLUTE_HOME.search(text):
            errors.append(f"absolute /home or /Users path found in {rel}; use ${{HOME}}")
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                errors.append(f"possible {label} found in {rel}")
        position = 0
        for line in text.splitlines(keepends=True):
            lowered = line.lower()
            for term in LEGACY_TERMS:
                local_start = lowered.find(term)
                if local_start < 0:
                    continue
                if rel == "README.md" and _in_readme_migration_note(text, position + local_start):
                    continue
                errors.append(f"legacy architecture term '{term}' found outside migration note: {rel}")
            position += len(line)


def validate_repository(root: Path) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    for required in sorted(REQUIRED_FILES):
        if not (root / required).is_file():
            errors.append(f"missing required file: {required}")
    manifest = _load_manifest(root / "nix-os.yaml", errors)
    if manifest:
        _validate_manifest(root, manifest, errors)
    _validate_files(root, errors)
    return sorted(set(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    errors = validate_repository(args.root)
    if errors:
        print(f"Repository verification failed ({len(errors)} error(s)):", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("Repository verification passed: manifest, contracts, safety rules, and references are consistent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
