#!/usr/bin/env python3
"""Preview or reconcile isolated weekly skill-scout cron jobs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
AUTOMATION = ROOT / "automation/skill-scout"
EXPECTED_JOBS = [
    {"name": "nix-skill-scout-pulse", "kind": "scout", "profile": "pulse", "hermes_profile": "pulse", "schedule": "0 18 * * 6", "prompt_file": "scout-prompt.md", "delivery": "local"},
    {"name": "nix-skill-scout-algua", "kind": "scout", "profile": "algua", "hermes_profile": "algua", "schedule": "20 18 * * 6", "prompt_file": "scout-prompt.md", "delivery": "local"},
    {"name": "nix-skill-scout-meabeclick", "kind": "scout", "profile": "meabeclick", "hermes_profile": "meabeclick", "schedule": "40 18 * * 6", "prompt_file": "scout-prompt.md", "delivery": "local"},
    {"name": "nix-skill-scout-meabeclickux", "kind": "scout", "profile": "meabeclickux", "hermes_profile": "meabeclickux", "schedule": "0 19 * * 6", "prompt_file": "scout-prompt.md", "delivery": "local"},
    {"name": "nix-skill-scout-meabeclickeng", "kind": "scout", "profile": "meabeclickeng", "hermes_profile": "meabeclickeng", "schedule": "20 19 * * 6", "prompt_file": "scout-prompt.md", "delivery": "local"},
    {"name": "nix-skill-scout-meabeclickgrowth", "kind": "scout", "profile": "meabeclickgrowth", "hermes_profile": "meabeclickgrowth", "schedule": "40 19 * * 6", "prompt_file": "scout-prompt.md", "delivery": "local"},
    {"name": "nix-skill-scout-lnx", "kind": "scout", "profile": "lnx", "hermes_profile": "default", "schedule": "0 20 * * 6", "prompt_file": "scout-prompt.md", "delivery": "local"},
    {"name": "nix-skill-scout-aggregate", "kind": "aggregator", "profile": "lnx", "hermes_profile": "default", "schedule": "0 21 * * 6", "prompt_file": "aggregate-prompt.md", "script": "skill-scout-collect.py", "delivery": "local", "delivery_enabled": "telegram:6926015052", "continuity": True},
]
CANONICAL_FILES = (
    "automation/skill-scout/jobs.json", "automation/skill-scout/scout-prompt.md",
    "automation/skill-scout/aggregate-prompt.md", "automation/skill-scout/collect.py",
    "scripts/setup-skill-scouts.py",
)


class Refusal(RuntimeError):
    pass


def _load(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Refusal(f"cannot read {path}: {exc}") from exc


def _profile_home(base: Path, profile: str) -> Path:
    return base if profile == "default" else base / "profiles" / profile


def _job_store(base: Path, profile: str) -> Path:
    override = os.environ.get("HERMES_SCOUT_TEST_STORE")
    if override:
        _validate_test_store_override()
        return Path(override) / f"{profile}.json"
    return _profile_home(base, profile) / "cron/jobs.json"


def _validate_test_store_override() -> None:
    if os.environ.get("HERMES_SCOUT_TEST_STORE") and os.environ.get("NIX_OS_SCOUT_TEST_MODE") != "1":
        raise Refusal("HERMES_SCOUT_TEST_STORE is forbidden outside explicit test mode")


def _read_jobs(path: Path) -> list[dict]:
    if not path.exists():
        return []
    value = _load(path)
    if isinstance(value, dict):
        value = value.get("jobs")
    if not isinstance(value, list) or any(not isinstance(job, dict) for job in value):
        raise Refusal(f"cron store is not a readable job list: {path}")
    return value


def _prompt(job: dict) -> str:
    text = (AUTOMATION / job["prompt_file"]).read_text(encoding="utf-8").strip()
    return text.replace("{{PROFILE}}", job["profile"])


def _schedule_value(job: dict) -> object:
    schedule = job.get("schedule")
    if isinstance(schedule, dict):
        return schedule.get("value") or schedule.get("expr") or schedule.get("display")
    return schedule


def _delivery(job: dict) -> list[str]:
    value = job.get("deliver") or ["local"]
    return [value] if isinstance(value, str) else value


def _is_exact(actual: dict, desired: dict) -> bool:
    if actual.get("name") != desired["name"] or _schedule_value(actual) != desired["schedule"]:
        return False
    if actual.get("prompt") != _prompt(desired):
        return False
    expected_script = desired.get("script")
    actual_script = actual.get("script")
    if expected_script:
        if actual_script not in (expected_script, str(_profile_home(Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))), "default") / "scripts" / expected_script)):
            return False
    elif actual_script:
        return False
    continuity = bool(actual.get("continuity")) or "self" in (actual.get("context_from") or [])
    if continuity != bool(desired.get("continuity")):
        return False
    allowed_delivery = {desired["delivery"]}
    if desired["kind"] == "aggregator":
        allowed_delivery.add(desired["delivery_enabled"])
    return len(_delivery(actual)) == 1 and _delivery(actual)[0] in allowed_delivery


def _run_hermes(binary: str, profile: str, args: list[str]) -> None:
    env = os.environ.copy()
    env["TZ"] = "Asia/Jerusalem"
    result = subprocess.run([binary, "-p", profile, *args], text=True, capture_output=True, env=env, check=False)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise Refusal(f"Hermes {profile} {' '.join(args)} failed: {detail}")


def _create_args(job: dict) -> list[str]:
    args = ["cron", "create", job["schedule"], _prompt(job), "--name", job["name"], "--deliver", "local"]
    if job.get("script"):
        args.extend(["--script", job["script"]])
    if job.get("continuity"):
        args.append("--continuity")
    return args


def _preview_delivery(base: Path, job: dict, enable_delivery: bool) -> str:
    if job["kind"] != "aggregator":
        return job["delivery"]
    if enable_delivery:
        return job["delivery_enabled"]
    existing = _read_jobs(_job_store(base, job["hermes_profile"]))
    matches = [item for item in existing if item.get("name") == job["name"]]
    if len(matches) == 1 and _delivery(matches[0]) == [job["delivery_enabled"]]:
        return job["delivery_enabled"]
    return job["delivery"]


def _collector_preflight(destination: Path, source: Path) -> None:
    current = destination
    while True:
        if current.is_symlink():
            raise Refusal(f"collector destination contains symlink: {current}")
        if current == current.parent:
            break
        current = current.parent
    if destination.exists() and destination.read_bytes() != source.read_bytes():
        raise Refusal(f"refusing to replace conflicting collector: {destination}")


def _canonical_spec(value: object) -> list[dict]:
    expected = {"schema_version": 1, "timezone": "Asia/Jerusalem", "packet_root": "${HOME}/.local/share/hermes-scouts", "jobs": EXPECTED_JOBS}
    if value != expected:
        raise Refusal("skill-scout manifest must exactly match the hardcoded eight-job canonical topology")
    return EXPECTED_JOBS


def _require_clean_governance() -> None:
    status = subprocess.run(["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=ROOT, text=True, capture_output=True, check=False)
    if status.returncode or status.stdout:
        raise Refusal("Nix OS repository must be clean, including untracked files, before apply")
    for relative in CANONICAL_FILES:
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", relative], cwd=ROOT, text=True, capture_output=True, check=False)
        if tracked.returncode:
            raise Refusal(f"canonical scout governance file must be tracked and committed: {relative}")


def _install_collector_atomic(destination: Path, source: Path) -> None:
    if destination.exists():
        return
    temporary = destination.with_suffix(".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd: int | None = None
    owned: tuple[int, int] | None = None
    try:
        fd = os.open(temporary, flags, 0o700)
        os.fchmod(fd, 0o700)
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise Refusal("collector temporary path is not a regular file")
        owned = (opened.st_dev, opened.st_ino)
        data = source.read_bytes()
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short write while installing collector")
            view = view[written:]
        os.fsync(fd)
        os.close(fd)
        fd = None
        current = os.lstat(temporary)
        if not stat.S_ISREG(current.st_mode) or (current.st_dev, current.st_ino) != owned:
            raise Refusal("collector temporary inode changed before atomic replace")
        os.replace(temporary, destination)
        owned = None
    except FileExistsError as exc:
        raise Refusal(f"collector temporary path already exists: {temporary}") from exc
    finally:
        if fd is not None:
            os.close(fd)
        if owned is not None:
            try:
                current = os.lstat(temporary)
                if (current.st_dev, current.st_ino) == owned:
                    os.unlink(temporary)
            except FileNotFoundError:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--enable-delivery", action="store_true", help="Switch only the aggregator to its reviewed Telegram target")
    args = parser.parse_args()
    try:
        _validate_test_store_override()
        spec = _load(AUTOMATION / "jobs.json")
        jobs = _canonical_spec(spec)
        base = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser().absolute()
        binary = os.environ.get("HERMES_BIN", "hermes")
        collector_source = AUTOMATION / "collect.py"
        collector_dest = base / "scripts/skill-scout-collect.py"
        _collector_preflight(collector_dest, collector_source)
        print(("APPLY" if args.apply else "PREVIEW") + " weekly skill-scout reconciliation")
        print("Timezone contract: Asia/Jerusalem (the Hermes gateway host must use this timezone).")
        for job in jobs:
            print(f"  {job['hermes_profile']}: {job['name']} @ {job['schedule']} -> {_preview_delivery(base, job, args.enable_delivery)}")
        if not args.apply:
            return 0

        _require_clean_governance()

        by_profile: dict[str, list[dict]] = {}
        for desired in jobs:
            by_profile.setdefault(desired["hermes_profile"], []).append(desired)
        existing_by_profile: dict[str, list[dict]] = {}
        for profile, wanted in by_profile.items():
            _run_hermes(binary, profile, ["cron", "list", "--all"])
            existing = _read_jobs(_job_store(base, profile))
            existing_by_profile[profile] = existing
            for desired in wanted:
                matches = [job for job in existing if job.get("name") == desired["name"]]
                if len(matches) > 1:
                    raise Refusal(f"duplicate same-name jobs for {desired['name']}")
                if matches and not _is_exact(matches[0], desired):
                    raise Refusal(f"same-name cron drift detected for {desired['name']}; refusing overwrite")

        collector_dest.parent.mkdir(parents=True, exist_ok=True)
        _install_collector_atomic(collector_dest, collector_source)

        for profile, wanted in by_profile.items():
            for desired in wanted:
                current = next((job for job in existing_by_profile[profile] if job.get("name") == desired["name"]), None)
                if current is None:
                    _run_hermes(binary, profile, _create_args(desired))
                    refreshed = _read_jobs(_job_store(base, profile))
                    current = next((job for job in refreshed if job.get("name") == desired["name"]), None)
                    if current is None or not _is_exact(current, desired):
                        raise Refusal(f"Hermes readback mismatch after creating {desired['name']}")
                    existing_by_profile[profile] = refreshed
                if args.enable_delivery and desired["kind"] == "aggregator" and _delivery(current) != [desired["delivery_enabled"]]:
                    identifier = current.get("id")
                    if not isinstance(identifier, str) or not identifier:
                        raise Refusal("aggregator has no stable job id for delivery edit")
                    _run_hermes(binary, profile, ["cron", "edit", identifier, "--deliver", desired["delivery_enabled"]])
                    refreshed = _read_jobs(_job_store(base, profile))
                    current = next((job for job in refreshed if job.get("name") == desired["name"]), None)
                    if current is None or _delivery(current) != [desired["delivery_enabled"]] or not _is_exact(current, desired):
                        raise Refusal("aggregator delivery readback mismatch")
        print("Skill-scout jobs reconciled and read back successfully.")
        return 0
    except (OSError, KeyError, TypeError, Refusal) as exc:
        print(f"Refusing: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
