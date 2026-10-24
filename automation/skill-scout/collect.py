#!/usr/bin/env python3
"""Validate and combine current-week skill-scout packets (stdlib only)."""

from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

EXPECTED_PROFILES = ("lnx", "pulse", "algua", "meabeclick", "meabeclickux", "meabeclickeng", "meabeclickgrowth")
HARD_GATES = ("relevance", "provenance", "reliability", "safety_privacy", "license", "hermes_compatibility", "non_duplication")
SCORE_LIMITS = {
    "role_value": 30,
    "evidence_quality": 20,
    "security_provenance": 20,
    "hermes_compatibility": 15,
    "maintenance": 10,
    "documentation_license": 5,
}
PACKET_FIELDS = {"schema_version", "week", "profile", "generated_at", "checked_sources", "rejected_count", "candidates"}
CANDIDATE_FIELDS = {
    "name", "summary", "rationale", "source_url", "repository", "skill_path", "revision", "license",
    "evidence_urls", "risks", "score_components", "score", "gates", "gate_evidence",
}
NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
REVISION = re.compile(r"^[a-f0-9]{40}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
WEEK = re.compile(r"^[0-9]{4}-W[0-9]{2}$")
SKILL_PATH = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*$")


def current_iso_week() -> str:
    iso = date.today().isocalendar()
    return f"{iso.year:04d}-W{iso.week:02d}"


def _is_https_url(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urlsplit(value.strip())
    return parsed.scheme == "https" and bool(parsed.netloc) and parsed.username is None and parsed.password is None


def _valid_nonempty_strings(value: object) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, str) and bool(item.strip()) for item in value)


def _validate_candidate(value: object, location: str) -> tuple[dict, list[str]]:
    if not isinstance(value, dict):
        return {}, [f"{location}: candidate must be an object"]
    errors: list[str] = []
    if set(value) != CANDIDATE_FIELDS:
        errors.append(f"{location}: fields must be exactly {sorted(CANDIDATE_FIELDS)}")
    if not isinstance(value.get("name"), str) or not NAME.fullmatch(value["name"]):
        errors.append(f"{location}: invalid name")
    for field in ("summary", "rationale", "license"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            errors.append(f"{location}: {field} is required")
    if not _is_https_url(value.get("source_url")):
        errors.append(f"{location}: source_url must be an https URL")
    if not isinstance(value.get("repository"), str) or not REPOSITORY.fullmatch(value["repository"]):
        errors.append(f"{location}: invalid repository")
    if not isinstance(value.get("skill_path"), str) or not SKILL_PATH.fullmatch(value["skill_path"]):
        errors.append(f"{location}: invalid repository-relative skill_path")
    if not isinstance(value.get("revision"), str) or not REVISION.fullmatch(value["revision"]):
        errors.append(f"{location}: revision must be a full lowercase commit SHA")
    evidence_urls = value.get("evidence_urls")
    if not _valid_nonempty_strings(evidence_urls) or not all(_is_https_url(url) for url in evidence_urls or []):
        errors.append(f"{location}: evidence_urls must be a nonempty list of https URLs")
    risks = value.get("risks")
    if not isinstance(risks, list) or any(not isinstance(risk, str) or not risk.strip() for risk in risks):
        errors.append(f"{location}: risks must be a list of nonempty strings")

    components = value.get("score_components")
    component_sum = None
    if not isinstance(components, dict) or set(components) != set(SCORE_LIMITS):
        errors.append(f"{location}: score_components must contain exactly {sorted(SCORE_LIMITS)}")
    else:
        invalid_components = [
            name for name, maximum in SCORE_LIMITS.items()
            if isinstance(components.get(name), bool) or not isinstance(components.get(name), int) or not 0 <= components[name] <= maximum
        ]
        if invalid_components:
            errors.append(f"{location}: score component outside its declared limit: {sorted(invalid_components)}")
        else:
            component_sum = sum(components.values())
    score = value.get("score")
    if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
        errors.append(f"{location}: score must be an integer from 0 to 100")
    elif component_sum is not None and score != component_sum:
        errors.append(f"{location}: score must equal the score_components sum")
    elif score < 80:
        errors.append(f"{location}: score must be at least 80")

    gates = value.get("gates")
    if not isinstance(gates, dict) or set(gates) != set(HARD_GATES) or any(not isinstance(gates.get(gate), bool) for gate in HARD_GATES):
        errors.append(f"{location}: all hard gates must be explicit booleans")
    elif not all(gates.values()):
        errors.append(f"{location}: every hard gate must pass")
    gate_evidence = value.get("gate_evidence")
    if not isinstance(gate_evidence, dict) or set(gate_evidence) != set(HARD_GATES) or any(
        not isinstance(gate_evidence.get(gate), str) or not gate_evidence[gate].strip() for gate in HARD_GATES
    ):
        errors.append(f"{location}: gate_evidence must contain a nonempty string for every hard gate")
    return dict(value), errors


def _valid_generated_at(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _dedupe_key(candidate: dict) -> tuple[str, str, str]:
    return (candidate["repository"].lower(), candidate["revision"], candidate["skill_path"])


def collect_packets(packet_dir: Path, week: str) -> dict:
    errors: list[str] = []
    candidates: list[dict] = []
    if not WEEK.fullmatch(week):
        return {"schema_version": 1, "week": week, "status": "invalid", "errors": ["invalid ISO week"], "candidates": []}
    for profile in EXPECTED_PROFILES:
        path = packet_dir / f"{profile}.json"
        if not path.is_file():
            errors.append(f"missing packet: {profile}")
            continue
        try:
            packet = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"invalid packet {profile}: {exc}")
            continue
        if not isinstance(packet, dict):
            errors.append(f"invalid packet {profile}: root must be an object")
            continue
        if set(packet) != PACKET_FIELDS:
            errors.append(f"invalid packet {profile}: fields must be exactly {sorted(PACKET_FIELDS)}")
        if packet.get("schema_version") != 1 or packet.get("week") != week or packet.get("profile") != profile:
            errors.append(f"invalid packet {profile}: identity/week mismatch")
        if not _valid_generated_at(packet.get("generated_at")):
            errors.append(f"invalid packet {profile}: generated_at must be timezone-aware ISO-8601")
        checked_sources = packet.get("checked_sources")
        if not _valid_nonempty_strings(checked_sources) or not all(_is_https_url(url) for url in checked_sources or []):
            errors.append(f"invalid packet {profile}: checked_sources must be a nonempty list of https URLs")
        rejected_count = packet.get("rejected_count")
        if isinstance(rejected_count, bool) or not isinstance(rejected_count, int) or rejected_count < 0:
            errors.append(f"invalid packet {profile}: rejected_count must be a nonnegative integer")
        values = packet.get("candidates")
        if not isinstance(values, list):
            errors.append(f"invalid packet {profile}: candidates must be a list")
            continue
        for index, value in enumerate(values):
            candidate, candidate_errors = _validate_candidate(value, f"{profile}.candidates[{index}]")
            errors.extend(candidate_errors)
            if not candidate_errors:
                candidate["reported_by"] = [profile]
                candidates.append(candidate)
    if errors:
        return {"schema_version": 1, "week": week, "status": "invalid", "errors": sorted(errors), "candidates": []}

    deduplicated: dict[tuple[str, str, str], dict] = {}
    conflicts: list[str] = []
    for candidate in sorted(candidates, key=lambda item: (_dedupe_key(item), item["reported_by"][0])):
        key = _dedupe_key(candidate)
        existing = deduplicated.get(key)
        if existing is None:
            deduplicated[key] = candidate
            continue
        existing_evidence = {field: value for field, value in existing.items() if field != "reported_by"}
        candidate_evidence = {field: value for field, value in candidate.items() if field != "reported_by"}
        if existing_evidence != candidate_evidence:
            conflicts.append(f"conflicting evidence for {key[0]}@{key[1]}:{key[2]}")
            continue
        existing["reported_by"] = sorted(set(existing["reported_by"] + candidate["reported_by"]))
    if conflicts:
        return {"schema_version": 1, "week": week, "status": "invalid", "errors": sorted(set(conflicts)), "candidates": []}
    output = sorted(deduplicated.values(), key=lambda item: (_dedupe_key(item), item["name"]))
    return {"schema_version": 1, "week": week, "status": "ok", "errors": [], "candidates": output}


def render_for_aggregator(result: dict) -> str:
    if result.get("status") == "ok" and not result.get("candidates"):
        return "[SILENT]"
    return json.dumps(result, indent=2, sort_keys=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path.home() / ".local/share/hermes-scouts")
    parser.add_argument("--week", default=current_iso_week())
    args = parser.parse_args()
    result = collect_packets(args.data_root / args.week, args.week)
    print(render_for_aggregator(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
