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
    "scripts/install-skills.py",
    "scripts/setup-skill-scouts.py",
    "skills/packs.json",
    "skills/proposal.schema.json",
    "skills/approval.schema.json",
    "automation/skill-scout/jobs.json",
    "automation/skill-scout/report.schema.json",
    "automation/skill-scout/scout-prompt.md",
    "automation/skill-scout/aggregate-prompt.md",
    "automation/skill-scout/collect.py",
    "docs/SKILL-GOVERNANCE.md",
    "tests/test_repository.py",
    "tests/test_skills.py",
    ".github/workflows/ci.yml",
}
EXPECTED_PROFILES = {
    "lnx", "pulse", "algua", "meabeclick", "meabeclickux",
    "meabeclickeng", "meabeclickgrowth",
}
EXPECTED_PROJECTS = {"pulse", "algua", "meabeclick"}
NIXKIT_COMMIT = "5d9ac621d4b2862c94ff8aa419f2f9fc6c9f68f4"
NIXKIT_SOURCES_SHA256 = "8c465cac697c5dc90a37e3a75242bac2f178c8768d7181883a3b9d673670b656"
NIXKIT_SKILLS = {
    "using-superpowers", "brainstorming", "writing-plans", "executing-plans",
    "systematic-debugging", "test-driven-development", "verification-before-completion",
    "requesting-code-review", "receiving-code-review", "using-git-worktrees",
    "finishing-a-development-branch", "subagent-driven-development", "dispatching-parallel-agents",
    "diagnosing-superpowers", "setup-matt-pocock-skills", "grill-with-docs", "grilling",
    "domain-modeling", "to-spec", "to-tickets", "codebase-design", "research", "handoff",
    "caveman", "ponytail", "frontend-design", "web-design-guidelines", "agent-browser",
    "remotion-best-practices", "auto-editor", "auto-editor-effects", "auto-editor-export",
    "auto-editor-transcribe", "obsidian-markdown", "qmd", "gws-shared", "gws-drive",
    "gws-docs", "gws-drive-upload", "gws-docs-write", "find-docs",
}
EXPECTED_PACKS = {
    "baseline-evidence": ["verification-before-completion"],
    "orchestrator-control": ["dispatching-parallel-agents", "receiving-code-review", "handoff"],
    "project-lead-core": ["brainstorming", "domain-modeling", "to-spec", "to-tickets", "codebase-design", "receiving-code-review", "handoff"],
    "public-research": ["research"],
    "engineering-delivery": ["executing-plans", "using-git-worktrees", "finishing-a-development-branch", "receiving-code-review", "codebase-design"],
    "ux-design-review": ["frontend-design"],
}
EXPECTED_PACK_ASSIGNMENTS = {
    "lnx": ["baseline-evidence", "orchestrator-control"],
    "pulse": ["baseline-evidence", "project-lead-core", "public-research"],
    "algua": ["baseline-evidence", "project-lead-core", "public-research"],
    "meabeclick": ["baseline-evidence", "project-lead-core", "public-research"],
    "meabeclickux": ["baseline-evidence", "ux-design-review"],
    "meabeclickeng": ["baseline-evidence", "engineering-delivery"],
    "meabeclickgrowth": ["baseline-evidence", "public-research"],
}
HARD_GATES = {"relevance", "provenance", "reliability", "safety_privacy", "license", "hermes_compatibility", "non_duplication"}
SCORE_LIMITS = {
    "role_value": 30, "evidence_quality": 20, "security_provenance": 20,
    "hermes_compatibility": 15, "maintenance": 10, "documentation_license": 5,
}
SCOUT_CANDIDATE_FIELDS = {
    "name", "summary", "rationale", "source_url", "repository", "skill_path", "revision", "license",
    "evidence_urls", "risks", "score_components", "score", "gates", "gate_evidence",
}
EXPECTED_SCOUT_JOBS = [
    {"name": "nix-skill-scout-pulse", "kind": "scout", "profile": "pulse", "hermes_profile": "pulse", "schedule": "0 18 * * 6", "prompt_file": "scout-prompt.md", "delivery": "local"},
    {"name": "nix-skill-scout-algua", "kind": "scout", "profile": "algua", "hermes_profile": "algua", "schedule": "20 18 * * 6", "prompt_file": "scout-prompt.md", "delivery": "local"},
    {"name": "nix-skill-scout-meabeclick", "kind": "scout", "profile": "meabeclick", "hermes_profile": "meabeclick", "schedule": "40 18 * * 6", "prompt_file": "scout-prompt.md", "delivery": "local"},
    {"name": "nix-skill-scout-meabeclickux", "kind": "scout", "profile": "meabeclickux", "hermes_profile": "meabeclickux", "schedule": "0 19 * * 6", "prompt_file": "scout-prompt.md", "delivery": "local"},
    {"name": "nix-skill-scout-meabeclickeng", "kind": "scout", "profile": "meabeclickeng", "hermes_profile": "meabeclickeng", "schedule": "20 19 * * 6", "prompt_file": "scout-prompt.md", "delivery": "local"},
    {"name": "nix-skill-scout-meabeclickgrowth", "kind": "scout", "profile": "meabeclickgrowth", "hermes_profile": "meabeclickgrowth", "schedule": "40 19 * * 6", "prompt_file": "scout-prompt.md", "delivery": "local"},
    {"name": "nix-skill-scout-lnx", "kind": "scout", "profile": "lnx", "hermes_profile": "default", "schedule": "0 20 * * 6", "prompt_file": "scout-prompt.md", "delivery": "local"},
    {"name": "nix-skill-scout-aggregate", "kind": "aggregator", "profile": "lnx", "hermes_profile": "default", "schedule": "0 21 * * 6", "prompt_file": "aggregate-prompt.md", "script": "skill-scout-collect.py", "delivery": "local", "delivery_enabled": "telegram:6926015052", "continuity": True},
]
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


def _load_json_object(path: Path, label: str, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"{label} must be valid JSON: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{label} root must be an object")
        return {}
    return value


def _validate_evidence_schema(schema: dict[str, Any], relative: str, errors: list[str], report: bool) -> None:
    definitions = schema.get("$defs")
    if not isinstance(definitions, dict):
        errors.append(f"{relative} must define the evidence contract")
        return
    score = definitions.get("score_components")
    if not isinstance(score, dict) or set(score.get("required", [])) != set(SCORE_LIMITS) or set((score.get("properties") or {})) != set(SCORE_LIMITS) or score.get("additionalProperties") is not False:
        errors.append(f"{relative} score_components fields must be exact")
    else:
        for name, maximum in SCORE_LIMITS.items():
            if score["properties"].get(name) != {"type": "integer", "minimum": 0, "maximum": maximum}:
                errors.append(f"{relative} score component {name} must be exactly 0-{maximum}")
    for definition, evidence in (("gates", False), ("gate_evidence", True)):
        contract = definitions.get(definition)
        if not isinstance(contract, dict) or set(contract.get("required", [])) != HARD_GATES or set((contract.get("properties") or {})) != HARD_GATES or contract.get("additionalProperties") is not False:
            errors.append(f"{relative} {definition} fields must be the exact seven hard gates")
            continue
        expected = {"type": "string", "minLength": 1} if evidence else {"const": True}
        if any(contract["properties"].get(gate) != expected for gate in HARD_GATES):
            errors.append(f"{relative} {definition} values do not fail closed")
    candidate = definitions.get("candidate") if report else schema
    if not isinstance(candidate, dict):
        errors.append(f"{relative} candidate contract must be an object")
        return
    required = set(candidate.get("required", []))
    expected_required = SCOUT_CANDIDATE_FIELDS if report else SCOUT_CANDIDATE_FIELDS | {"schema_version", "proposal_id", "profile", "status"}
    if required != expected_required:
        errors.append(f"{relative} candidate required fields must be exact")
        return
    properties = candidate.get("properties") or {}
    if properties.get("score") != {"type": "integer", "minimum": 80, "maximum": 100}:
        errors.append(f"{relative} candidate score must be constrained to 80-100")
    evidence_urls = properties.get("evidence_urls")
    expected_url_items = {"type": "string", "maxLength": 2048, "pattern": "^https://"}
    if not isinstance(evidence_urls, dict) or evidence_urls.get("minItems") != 2 or evidence_urls.get("maxItems") != 100 or evidence_urls.get("items") != expected_url_items:
        errors.append(f"{relative} evidence_urls must require bounded HTTPS source and license evidence")
    source_url = properties.get("source_url")
    if not isinstance(source_url, dict) or source_url.get("maxLength") != 2048 or "github\\.com" not in source_url.get("pattern", "") or "[a-f0-9]{40}" not in source_url.get("pattern", ""):
        errors.append(f"{relative} source_url must require immutable GitHub revision evidence")
    if properties.get("gates") != {"$ref": "#/$defs/gates"} or properties.get("gate_evidence") != {"$ref": "#/$defs/gate_evidence"} or properties.get("score_components") != {"$ref": "#/$defs/score_components"}:
        errors.append(f"{relative} candidate must bind the exact score and gate contracts")
    if report:
        packet_fields = {"schema_version", "week", "profile", "generated_at", "checked_sources", "rejected_count", "candidates"}
        if set(schema.get("required", [])) != packet_fields or set((schema.get("properties") or {})) != packet_fields:
            errors.append(f"{relative} packet fields must be exact")
        checked = schema.get("properties", {}).get("checked_sources", {})
        if checked.get("minItems") != 1 or checked.get("items", {}).get("pattern") != "^https://":
            errors.append(f"{relative} checked_sources must require HTTPS evidence")
        if schema.get("properties", {}).get("rejected_count") != {"type": "integer", "minimum": 0}:
            errors.append(f"{relative} rejected_count must be nonnegative")


def _validate_skills(root: Path, manifest: dict[str, Any], errors: list[str]) -> None:
    packs = _load_json_object(root / "skills/packs.json", "skills/packs.json", errors)
    if not packs:
        return
    pin = packs.get("nixkit")
    expected_pin = {
        "repository": "https://github.com/its-nix/kit.git", "commit": NIXKIT_COMMIT,
        "sources_sha256": NIXKIT_SOURCES_SHA256, "node_runtime": "24.22.1",
    }
    if pin != expected_pin:
        errors.append("skills/packs.json must use the exact audited NixKit repository, commit, source hash, and Node 24.22.1 runtime")
    if packs.get("packs") != EXPECTED_PACKS:
        errors.append("persistent skill packs must match the conservative audited matrix")
    if packs.get("profiles") != EXPECTED_PACK_ASSIGNMENTS:
        errors.append("profile pack assignments must match all seven explicit role mappings")
    approved_additions = packs.get("approved_additions")
    if approved_additions != {profile: [] for profile in EXPECTED_PROFILES}:
        errors.append("initial approved_additions must be empty for every profile; future additions require a reviewed verifier/manifest PR and Lior approval")
    if any(name in {"global", "universal", "all", "*"} for name in (packs.get("packs") or {})):
        errors.append("wildcard/global/universal skill packs are forbidden")
    persistent = set().union(*(set(values) for values in EXPECTED_PACKS.values()))
    task_only = packs.get("task_only")
    excluded = packs.get("excluded")
    if not isinstance(task_only, list) or not isinstance(excluded, list):
        errors.append("task_only and excluded must be explicit lists")
    else:
        task, omit = set(task_only), set(excluded)
        if len(task) != len(task_only) or len(omit) != len(excluded):
            errors.append("task_only and excluded classifications must not contain duplicates")
        if persistent & task or persistent & omit or task & omit:
            errors.append("persistent, task-only, and excluded classifications must be disjoint")
        if persistent | task | omit != NIXKIT_SKILLS:
            errors.append("all 41 NixKit skills must be classified exactly once semantically")
        if not {"web-design-guidelines", "find-docs"} <= task:
            errors.append("mutable-latest web-design-guidelines and find-docs must remain task-only")
    governance = packs.get("governance")
    if not isinstance(governance, dict) or set(governance.get("hard_gates", [])) != HARD_GATES:
        errors.append("skill governance must declare all seven hard gates")
    elif (
        governance.get("minimum_score") != 80
        or governance.get("popularity") != "evidence_only"
        or governance.get("approval_authority") != "Lior"
        or governance.get("initial_baseline_source") != "merged_reviewed_packs"
        or governance.get("future_additions") != "profile_specific_manifest_pr_and_lior_approval"
    ):
        errors.append("skill governance threshold and approval policy are invalid")
    expected_reference = {
        "packs": "skills/packs.json", "proposal_schema": "skills/proposal.schema.json",
        "approval_schema": "skills/approval.schema.json", "scout_jobs": "automation/skill-scout/jobs.json",
        "scout_report_schema": "automation/skill-scout/report.schema.json",
    }
    if manifest.get("skill_governance") != expected_reference:
        errors.append("nix-os.yaml skill_governance references must be exact")
    loaded_schemas: dict[str, dict[str, Any]] = {}
    for relative in ("skills/proposal.schema.json", "skills/approval.schema.json", "automation/skill-scout/report.schema.json"):
        schema = _load_json_object(root / relative, relative, errors)
        loaded_schemas[relative] = schema
        if schema and schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            errors.append(f"{relative} must use JSON Schema draft 2020-12")
    if loaded_schemas.get("skills/proposal.schema.json"):
        _validate_evidence_schema(loaded_schemas["skills/proposal.schema.json"], "skills/proposal.schema.json", errors, False)
    if loaded_schemas.get("automation/skill-scout/report.schema.json"):
        _validate_evidence_schema(loaded_schemas["automation/skill-scout/report.schema.json"], "automation/skill-scout/report.schema.json", errors, True)
    try:
        scout_prompt = (root / "automation/skill-scout/scout-prompt.md").read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"cannot inspect self-contained scout prompt: {exc}")
        scout_prompt = ""
    prompt_fields = {"checked_sources", "rejected_count", "skill_path", "evidence_urls", "risks", "score_components", "score", "gates", "gate_evidence"} | set(SCORE_LIMITS) | HARD_GATES
    if any(f'"{field}"' not in scout_prompt for field in prompt_fields) or any(text not in scout_prompt for text in (
        "complete packet contract", "installed skill inventory first", "public Hermes skill registries",
        "public GitHub/web sources", "supporting evidence only", "untrusted research content",
        "Do not install or download executable code", "write anywhere except the single packet",
    )):
        errors.append("skill scout prompt must remain self-contained, source-aware, read-only, and explicit about every evidence field")
    jobs = _load_json_object(root / "automation/skill-scout/jobs.json", "automation/skill-scout/jobs.json", errors)
    expected_jobs = {
        "schema_version": 1, "timezone": "Asia/Jerusalem",
        "packet_root": "${HOME}/.local/share/hermes-scouts", "jobs": EXPECTED_SCOUT_JOBS,
    }
    if jobs != expected_jobs:
        errors.append("skill-scout job manifest must exactly declare seven local staggered scouts and the reviewed default-profile aggregator")


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
        _validate_skills(root, manifest, errors)
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
