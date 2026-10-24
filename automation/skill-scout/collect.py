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
RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
MAX_PACKET_BYTES = 131_072
MAX_CANDIDATES = 50
MAX_AGGREGATE_CANDIDATES = 100
MAX_TEXT = 4_096
MAX_URL = 2_048
MAX_EVIDENCE_URLS = 100
MAX_RISKS = 50
MAX_RENDER_BYTES = 262_144
MAX_JSON_DEPTH = 100
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN(?: [A-Z0-9]+)* PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    "OpenAI key": re.compile(r"\bsk-[A-Za-z0-9_-]{32,}\b"),
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "Discord bot token": re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{20,30}\.[A-Za-z0-9_-]{6,8}\.[A-Za-z0-9_-]{25,45}(?![A-Za-z0-9_-])"),
    "Discord webhook credential": re.compile(r"https://(?:(?:canary|ptb)\.)?discord(?:app)?\.com/api/webhooks/[0-9]{17,20}/[A-Za-z0-9._-]{30,}"),
    "Discord webhook token": re.compile(r"(?i)\bdiscord[_ -]?webhook(?:[_ -]?token)?\s*[:=]\s*[A-Za-z0-9._-]{30,}"),
    "xox workspace token": re.compile(r"\bxox[bp]-[A-Za-z0-9-]{20,}\b"),
    "bearer/token value": re.compile(r"(?i)\b(?:bearer\s+|api[_-]?key\s*[:=]\s*|access[_-]?token\s*[:=]\s*|secret[_-]?key\s*[:=]\s*)[A-Za-z0-9_./+\-=]{16,}"),
    "credential query parameter": re.compile(r"(?i)[?&](?:api[_-]?key|access[_-]?token|auth(?:orization)?|bearer|client[_-]?secret|secret|token|key)=[^&#\s]{8,}"),
    "JWT": re.compile(r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?![A-Za-z0-9_-])"),
    "npm token": re.compile(r"\bnpm_[A-Za-z0-9]{36}\b"),
    "Stripe key": re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
}
PROTECTED_PATH = re.compile(r"(?i)(?:^|[/_.-])(?:students?|customers?|payments?|pricing|cardholders?|invoices?)(?:[/_.-]|$)")
HTTP_URL = re.compile(r"(?i)https?://[^\s<>\"']+")
DISCORD_WEBHOOK_HOSTS = {
    "discord.com", "canary.discord.com", "ptb.discord.com",
    "discordapp.com", "canary.discordapp.com", "ptb.discordapp.com",
}


def _contains_discord_webhook_url(text: str) -> bool:
    for match in HTTP_URL.finditer(text):
        candidate = match.group(0).rstrip(".,;:!?)]}")
        try:
            parsed = urlsplit(candidate)
            hostname = (parsed.hostname or "").lower()
            port = parsed.port
        except ValueError:
            continue
        if (
            parsed.scheme.lower() in {"http", "https"}
            and hostname in DISCORD_WEBHOOK_HOSTS
            and (port is None or port == 443)
            and parsed.path.startswith("/api/webhooks/")
        ):
            return True
    return False


def current_iso_week() -> str:
    iso = date.today().isocalendar()
    return f"{iso.year:04d}-W{iso.week:02d}"


def _is_https_url(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urlsplit(value.strip())
    return parsed.scheme == "https" and bool(parsed.netloc) and parsed.username is None and parsed.password is None


def _valid_nonempty_strings(value: object) -> bool:
    return isinstance(value, list) and bool(value) and len(value) <= MAX_EVIDENCE_URLS and all(isinstance(item, str) and bool(item.strip()) and len(item) <= MAX_URL for item in value)


def _screen_text(text: str, location: str) -> list[str]:
    errors = []
    if "\x00" in text or any(ord(char) < 32 and char not in "\t\r\n" for char in text):
        errors.append(f"{location}: NUL/control characters are forbidden")
    if _contains_discord_webhook_url(text):
        errors.append(f"{location}: possible Discord webhook credential is forbidden")
    for label, pattern in SECRET_PATTERNS.items():
        if pattern.search(text):
            errors.append(f"{location}: possible {label} is forbidden")
    if PROTECTED_PATH.search(text):
        errors.append(f"{location}: protected student/customer/payment/pricing path indicator is forbidden")
    return errors


def _screen_value(value: object, location: str) -> list[str]:
    if isinstance(value, str):
        return _screen_text(value, location)
    if isinstance(value, list):
        return [error for item in value for error in _screen_value(item, location)]
    if isinstance(value, dict):
        return [error for key, item in value.items() for error in _screen_value(key, location) + _screen_value(item, location)]
    return []


def _json_nesting_error(text: str) -> str | None:
    """Bound JSON container nesting without interpreting escaped string data."""
    depth = 0
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                return f"JSON nesting exceeds {MAX_JSON_DEPTH}"
        elif char in "]}":
            depth -= 1
    return None


def _github_url(repository: str, kind: str, revision: str, path: str) -> str:
    return f"https://github.com/{repository}/{kind}/{revision}/{path}"


def _validate_candidate(value: object, location: str) -> tuple[dict, list[str]]:
    if not isinstance(value, dict):
        return {}, [f"{location}: candidate must be an object"]
    errors: list[str] = []
    if set(value) != CANDIDATE_FIELDS:
        errors.append(f"{location}: fields must be exactly {sorted(CANDIDATE_FIELDS)}")
    if not isinstance(value.get("name"), str) or not NAME.fullmatch(value["name"]):
        errors.append(f"{location}: invalid name")
    for field in ("summary", "rationale", "license"):
        if not isinstance(value.get(field), str) or not value[field].strip() or len(value[field]) > MAX_TEXT:
            errors.append(f"{location}: {field} is required")
    if not _is_https_url(value.get("source_url")):
        errors.append(f"{location}: source_url must be an https URL")
    if not isinstance(value.get("repository"), str) or not REPOSITORY.fullmatch(value["repository"]):
        errors.append(f"{location}: invalid repository")
    if not isinstance(value.get("skill_path"), str) or not SKILL_PATH.fullmatch(value["skill_path"]):
        errors.append(f"{location}: invalid repository-relative skill_path")
    if not isinstance(value.get("revision"), str) or not REVISION.fullmatch(value["revision"]):
        errors.append(f"{location}: revision must be a full lowercase commit SHA")
    if all(isinstance(value.get(field), str) for field in ("repository", "revision", "skill_path")):
        expected_source = _github_url(value["repository"], "tree", value["revision"], value["skill_path"])
        if value.get("source_url") != expected_source:
            errors.append(f"{location}: source_url must exactly pin repository/revision/skill_path")
    evidence_urls = value.get("evidence_urls")
    if not _valid_nonempty_strings(evidence_urls) or len(evidence_urls or []) < 2 or not all(_is_https_url(url) for url in evidence_urls or []):
        errors.append(f"{location}: evidence_urls must contain 2-100 bounded https URLs")
    elif all(isinstance(value.get(field), str) for field in ("repository", "revision", "skill_path")):
        source = _github_url(value["repository"], "tree", value["revision"], value["skill_path"])
        prefixes = (f"/{value['repository']}/blob/{value['revision']}/", f"/{value['repository']}/tree/{value['revision']}/")
        license_evidence = False
        for url in evidence_urls:
            parsed = urlsplit(url)
            if parsed.scheme != "https" or parsed.netloc != "github.com" or parsed.query or parsed.fragment:
                continue
            for prefix in prefixes:
                if parsed.path.startswith(prefix):
                    relative = parsed.path[len(prefix):]
                    if any(re.fullmatch(r"(?:LICENSE|COPYING|NOTICE)(?:[._-].*)?", part, re.I) for part in relative.split("/") if part):
                        license_evidence = True
        if source not in evidence_urls or not license_evidence:
            errors.append(f"{location}: evidence_urls require same-repository/revision source and license evidence")
    risks = value.get("risks")
    if not isinstance(risks, list) or len(risks) > MAX_RISKS or any(not isinstance(risk, str) or not risk.strip() or len(risk) > MAX_TEXT for risk in risks):
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
        not isinstance(gate_evidence.get(gate), str) or not gate_evidence[gate].strip() or len(gate_evidence[gate]) > MAX_TEXT for gate in HARD_GATES
    ):
        errors.append(f"{location}: gate_evidence must contain a nonempty string for every hard gate")
    return dict(value), errors


def _valid_generated_at(value: object, week: str) -> bool:
    if not isinstance(value, str) or not RFC3339.fullmatch(value):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return False
    iso = parsed.date().isocalendar()
    return week == f"{iso.year:04d}-W{iso.week:02d}"


def _dedupe_key(candidate: dict) -> tuple[str, str, str]:
    return (candidate["repository"].lower(), candidate["revision"], candidate["skill_path"])


def collect_packets(packet_dir: Path, week: str) -> dict:
    errors: list[str] = []
    candidates: list[dict] = []
    if not WEEK.fullmatch(week):
        return {"schema_version": 1, "week": week, "status": "invalid", "errors": ["invalid ISO week"], "candidates": []}
    try:
        year, number = int(week[:4]), int(week[6:])
        date.fromisocalendar(year, number, 1)
    except ValueError:
        return {"schema_version": 1, "week": week, "status": "invalid", "errors": ["invalid ISO week"], "candidates": []}
    if week != current_iso_week():
        return {"schema_version": 1, "week": week, "status": "invalid", "errors": ["requested week is not the current ISO week"], "candidates": []}
    for profile in EXPECTED_PROFILES:
        path = packet_dir / f"{profile}.json"
        if not path.is_file():
            errors.append(f"missing packet: {profile}")
            continue
        try:
            if path.stat().st_size > MAX_PACKET_BYTES:
                errors.append(f"invalid packet {profile}: packet exceeds size limit")
                continue
            raw = path.read_text(encoding="utf-8")
            screening = _screen_text(raw, f"packet {profile}")
            if screening:
                errors.extend(screening)
                continue
            nesting_error = _json_nesting_error(raw)
            if nesting_error:
                errors.append(f"invalid packet {profile}: {nesting_error}")
                continue
            packet = json.loads(raw)
        except (OSError, UnicodeError, json.JSONDecodeError, RecursionError, MemoryError) as exc:
            errors.append(f"invalid packet {profile}: {exc}")
            continue
        if not isinstance(packet, dict):
            errors.append(f"invalid packet {profile}: root must be an object")
            continue
        try:
            structured_screening = _screen_value(packet, f"packet {profile}")
        except (RecursionError, MemoryError) as exc:
            errors.append(f"invalid packet {profile}: cannot safely inspect JSON: {type(exc).__name__}")
            continue
        if structured_screening:
            errors.extend(structured_screening)
            continue
        if set(packet) != PACKET_FIELDS:
            errors.append(f"invalid packet {profile}: fields must be exactly {sorted(PACKET_FIELDS)}")
        if packet.get("schema_version") != 1 or packet.get("week") != week or packet.get("profile") != profile:
            errors.append(f"invalid packet {profile}: identity/week mismatch")
        if not _valid_generated_at(packet.get("generated_at"), week):
            errors.append(f"invalid packet {profile}: generated_at must be strict RFC3339 in the packet ISO week")
        checked_sources = packet.get("checked_sources")
        if not _valid_nonempty_strings(checked_sources) or not all(_is_https_url(url) for url in checked_sources or []):
            errors.append(f"invalid packet {profile}: checked_sources must be a nonempty list of https URLs")
        rejected_count = packet.get("rejected_count")
        if isinstance(rejected_count, bool) or not isinstance(rejected_count, int) or rejected_count < 0:
            errors.append(f"invalid packet {profile}: rejected_count must be a nonnegative integer")
        values = packet.get("candidates")
        if not isinstance(values, list) or len(values) > MAX_CANDIDATES:
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
    if len(output) > MAX_AGGREGATE_CANDIDATES:
        return {"schema_version": 1, "week": week, "status": "invalid", "errors": ["candidate aggregate exceeds size limit"], "candidates": []}
    result = {"schema_version": 1, "week": week, "status": "ok", "errors": [], "candidates": output}
    if len(json.dumps(result, sort_keys=True).encode("utf-8")) > MAX_RENDER_BYTES:
        return {"schema_version": 1, "week": week, "status": "invalid", "errors": ["candidate aggregate exceeds rendered size limit"], "candidates": []}
    return result


def render_for_aggregator(result: dict) -> str:
    if result.get("status") == "ok" and not result.get("candidates"):
        return "[SILENT]"
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if len(rendered.encode("utf-8")) > MAX_RENDER_BYTES:
        rendered = json.dumps({"schema_version": 1, "week": result.get("week"), "status": "invalid", "errors": ["collector output exceeds rendered size limit"], "candidates": []}, indent=2, sort_keys=True)
    return rendered


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
