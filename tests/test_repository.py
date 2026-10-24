from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {
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
    "docs/SKILL-GOVERNANCE.md",
    "automation/skill-scout/jobs.json",
    "automation/skill-scout/report.schema.json",
    "automation/skill-scout/collect.py",
    "tests/test_skills.py",
    ".github/workflows/ci.yml",
    *{f"profiles/{name}/ROLE.md" for name in (
        "lnx", "pulse", "algua", "meabeclick", "meabeclickux",
        "meabeclickeng", "meabeclickgrowth"
    )},
}


def load_verifier():
    path = ROOT / "scripts/verify.py"
    spec = importlib.util.spec_from_file_location("repository_verifier", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RepositoryContractTests(unittest.TestCase):
    def test_required_files_exist(self):
        missing = sorted(path for path in REQUIRED if not (ROOT / path).is_file())
        self.assertEqual([], missing)

    def test_manifest_declares_exact_safe_topology(self):
        manifest = json.loads((ROOT / "nix-os.yaml").read_text(encoding="utf-8"))
        profiles = {item["id"]: item for item in manifest["profiles"]}
        self.assertEqual(
            {"lnx", "pulse", "algua", "meabeclick", "meabeclickux", "meabeclickeng", "meabeclickgrowth"},
            set(profiles),
        )
        self.assertEqual("default", profiles["lnx"]["hermes_profile"])
        self.assertEqual("lnx", manifest["orchestrator"])
        self.assertEqual(["lnx"], manifest["discord_visible_profiles"])
        self.assertEqual({"pulse", "algua", "meabeclick"}, {p["id"] for p in manifest["projects"]})
        self.assertEqual("lior-only", manifest["todoist"]["scope"])

    def test_repository_verifier_passes(self):
        verifier = load_verifier()
        self.assertEqual([], verifier.validate_repository(ROOT))

    def test_verifier_rejects_invalid_lead_reference(self):
        verifier = load_verifier()
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "repo"
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            manifest = json.loads((copy / "nix-os.yaml").read_text(encoding="utf-8"))
            manifest["projects"][0]["lead"] = "missing-profile"
            (copy / "nix-os.yaml").write_text(json.dumps(manifest), encoding="utf-8")
            errors = verifier.validate_repository(copy)
            self.assertTrue(any("lead" in error and "missing-profile" in error for error in errors), errors)

    def test_verifier_rejects_runtime_schema_and_scout_manifest_drift(self):
        verifier = load_verifier()
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "repo"
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            packs_path = copy / "skills/packs.json"
            packs = json.loads(packs_path.read_text(encoding="utf-8"))
            packs["nixkit"]["node_runtime"] = "24"
            packs_path.write_text(json.dumps(packs), encoding="utf-8")
            report_path = copy / "automation/skill-scout/report.schema.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["$defs"]["score_components"]["properties"]["role_value"]["maximum"] = 31
            report["$defs"]["gate_evidence"]["properties"]["relevance"]["maxLength"] = 999
            report_path.write_text(json.dumps(report), encoding="utf-8")
            proposal_path = copy / "skills/proposal.schema.json"
            proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
            proposal["properties"]["risks"]["maxItems"] = 51
            proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
            jobs_path = copy / "automation/skill-scout/jobs.json"
            jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
            jobs["jobs"][0]["delivery"] = "telegram:unexpected"
            jobs_path.write_text(json.dumps(jobs), encoding="utf-8")
            errors = verifier.validate_repository(copy)
            self.assertTrue(any("Node 24.22.1" in error for error in errors), errors)
            self.assertTrue(any("role_value" in error and "0-30" in error for error in errors), errors)
            self.assertTrue(any("gate_evidence" in error and "fail closed" in error for error in errors), errors)
            self.assertTrue(any("risks must be a bounded list" in error for error in errors), errors)
            self.assertTrue(any("job manifest must exactly" in error for error in errors), errors)

    def test_verifier_rejects_secret_runtime_name_and_absolute_home(self):
        verifier = load_verifier()
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "repo"
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            (copy / "auth.json").write_text("{}", encoding="utf-8")
            (copy / "leaked.key").write_text("not-even-a-real-key", encoding="utf-8")
            (copy / ".netrc").write_text("machine example.invalid\n", encoding="utf-8")
            (copy / ".npmrc").write_text("//example.invalid/:_authToken=fake\n", encoding="utf-8")
            (copy / "state.db-wal").write_text("runtime", encoding="utf-8")
            sidecars = (
                "other.db-wal", "other.db-journal", "other.db-shm",
                "other.sqlite-wal", "other.sqlite-journal", "other.sqlite-shm",
                "other.sqlite3-wal", "other.sqlite3-journal", "other.sqlite3-shm",
            )
            for sidecar in sidecars:
                (copy / sidecar).write_text("runtime", encoding="utf-8")
            (copy / "binary-fixture").write_bytes(b"plain\x00text")
            (copy / "cron").mkdir()
            (copy / "cron/jobs.json").write_text("{}", encoding="utf-8")
            leaked_token = "sk-" + "A" * 40
            (copy / "notes").write_text(leaked_token, encoding="utf-8")
            fine_grained = "github" + "_pat_" + "B" * 60
            webhook = "https://discord.com/api/webhooks/" + "1" * 18 + "/" + "W" * 60
            workspace_token = "xox" + "b-" + "1" * 12 + "-" + "C" * 30
            (copy / "more-notes").write_text("\n".join((fine_grained, webhook, workspace_token)), encoding="utf-8")
            absolute_home = "/" + "home/example/private"
            (copy / "docs/unsafe.md").write_text(
                f"path: {absolute_home}\ncredential: {leaked_token}\n",
                encoding="utf-8",
            )
            errors = verifier.validate_repository(copy)
            self.assertTrue(any("auth.json" in error for error in errors), errors)
            self.assertTrue(any("leaked.key" in error for error in errors), errors)
            self.assertTrue(any(".netrc" in error for error in errors), errors)
            self.assertTrue(any(".npmrc" in error for error in errors), errors)
            self.assertTrue(any("state.db-wal" in error for error in errors), errors)
            for sidecar in sidecars:
                self.assertTrue(any(sidecar in error for error in errors), errors)
            self.assertTrue(any("binary repository file" in error and "binary-fixture" in error for error in errors), errors)
            self.assertTrue(any("cron/jobs.json" in error for error in errors), errors)
            self.assertTrue(any("OpenAI-style key" in error and "notes" in error for error in errors), errors)
            self.assertTrue(any("GitHub token" in error and "more-notes" in error for error in errors), errors)
            self.assertTrue(any("Discord webhook" in error and "more-notes" in error for error in errors), errors)
            self.assertTrue(any("xox workspace" in error and "more-notes" in error for error in errors), errors)
            self.assertTrue(any("absolute /home" in error for error in errors), errors)

    def test_verifier_rejects_unsafe_profile_mapping_and_workspace_traversal(self):
        verifier = load_verifier()
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "repo"
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            manifest_path = copy / "nix-os.yaml"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            next(profile for profile in manifest["profiles"] if profile["id"] == "pulse")["hermes_profile"] = "default"
            next(project for project in manifest["projects"] if project["id"] == "pulse")["workspace"] = "${HOME}/../../etc"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            errors = verifier.validate_repository(copy)
            self.assertTrue(any("profile pulse layout" in error for error in errors), errors)
            self.assertTrue(any("Hermes profile names must be unique" in error for error in errors), errors)
            self.assertTrue(any("project pulse layout" in error for error in errors), errors)

    def test_verifier_rejects_board_and_authority_plane_drift(self):
        verifier = load_verifier()
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "repo"
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            manifest_path = copy / "nix-os.yaml"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            pulse = next(project for project in manifest["projects"] if project["id"] == "pulse")
            algua = next(project for project in manifest["projects"] if project["id"] == "algua")
            pulse["board"], algua["board"] = algua["board"], pulse["board"]
            manifest["planes"] = {"human_messaging": "email"}
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            errors = verifier.validate_repository(copy)
            self.assertTrue(any("project pulse layout" in error for error in errors), errors)
            self.assertTrue(any("project algua layout" in error for error in errors), errors)
            self.assertTrue(any("authority planes must be exactly" in error for error in errors), errors)

    def test_verifier_rejects_legacy_architecture_outside_migration_note(self):
        verifier = load_verifier()
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "repo"
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            legacy_term = "n" + "8n"
            (copy / "docs/legacy.md").write_text(f"Use {legacy_term} as the workflow runtime.", encoding="utf-8")
            errors = verifier.validate_repository(copy)
            self.assertTrue(any("legacy architecture" in error for error in errors), errors)

    def test_bootstrap_preview_is_non_mutating_without_hermes(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            env = os.environ.copy()
            env.update({"HOME": str(home), "HERMES_HOME": str(home / ".hermes"), "HERMES_BIN": "/missing/hermes"})
            result = subprocess.run(
                ["bash", str(ROOT / "scripts/bootstrap.sh")],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("PREVIEW", result.stdout)
            self.assertFalse((home / ".hermes").exists())

    def test_bootstrap_apply_preserves_existing_profile_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "home"
            hermes_home = home / ".hermes"
            existing = hermes_home / "profiles/pulse"
            existing.mkdir(parents=True)
            (hermes_home / "profiles").chmod(0o750)
            sentinel = hermes_home / "sentinel.txt"
            sentinel.write_text("leave default state alone\n", encoding="utf-8")
            (existing / "SOUL.md").write_text("keep me\n", encoding="utf-8")
            (existing / "config.yaml").write_text("keep: true\n", encoding="utf-8")
            fake = base / "hermes"
            fake.write_text(textwrap.dedent("""\
                #!/usr/bin/env python3
                import json, os, pathlib, sys
                args = sys.argv[1:]
                hh = pathlib.Path(os.environ["HERMES_HOME"])
                log = pathlib.Path(os.environ["HERMES_FAKE_LOG"])
                with log.open("a", encoding="utf-8") as out:
                    out.write(json.dumps(args) + "\\n")
                filtered = args[:]
                if filtered[:2] == ["-p", "default"]:
                    filtered = filtered[2:]
                if filtered[:3] == ["kanban", "boards", "list"]:
                    board_dir = hh / "fake-boards"
                    items = [{"slug": p.name} for p in board_dir.iterdir()] if board_dir.exists() else []
                    print(json.dumps(items))
                elif filtered[:3] == ["kanban", "boards", "create"]:
                    p = hh / "fake-boards" / filtered[3]
                    p.mkdir(parents=True, exist_ok=False)
                elif filtered[:2] == ["project", "show"]:
                    marker = hh / "fake-projects" / filtered[2]
                    if marker.exists():
                        raise SystemExit(0)
                    print(f"project: no such project: {filtered[2]}", file=sys.stderr)
                    raise SystemExit(1)
                elif filtered[:2] == ["project", "create"]:
                    slug = filtered[filtered.index("--slug") + 1]
                    (hh / "fake-projects" / slug).mkdir(parents=True, exist_ok=False)
            """), encoding="utf-8")
            fake.chmod(0o755)
            log = base / "calls.jsonl"
            env = os.environ.copy()
            env.update({
                "HOME": str(home), "HERMES_HOME": str(hermes_home),
                "HERMES_BIN": str(fake), "HERMES_FAKE_LOG": str(log),
            })
            command = ["bash", str(ROOT / "scripts/bootstrap.sh"), "--apply"]
            first = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True, check=False)
            self.assertEqual(0, first.returncode, first.stderr)
            self.assertEqual("keep me\n", (existing / "SOUL.md").read_text(encoding="utf-8"))
            self.assertEqual("keep: true\n", (existing / "config.yaml").read_text(encoding="utf-8"))
            self.assertEqual("leave default state alone\n", sentinel.read_text(encoding="utf-8"))
            self.assertEqual(0o750, (hermes_home / "profiles").stat().st_mode & 0o777)
            for profile in ("algua", "meabeclick", "meabeclickux", "meabeclickeng", "meabeclickgrowth"):
                installed = hermes_home / "profiles" / profile / "SOUL.md"
                expected = ROOT / "profiles" / profile / "ROLE.md"
                self.assertEqual(expected.read_text(encoding="utf-8"), installed.read_text(encoding="utf-8"))
                self.assertEqual(0o600, installed.stat().st_mode & 0o777)
            calls_after_first = log.read_text(encoding="utf-8").splitlines()
            calls = [json.loads(line) for line in calls_after_first]
            self.assertFalse(any("profile" in call and "create" in call for call in calls), calls)
            for project in ("pulse", "algua", "meabeclick"):
                workspace = str(home / "Projects" / project)
                board_call = next(
                    call for call in calls
                    if call[:5] == ["-p", "default", "kanban", "boards", "create"] and call[5] == project
                )
                self.assertEqual(workspace, board_call[board_call.index("--default-workdir") + 1])
                project_call = next(
                    call for call in calls
                    if call[:4] == ["-p", "default", "project", "create"]
                    and "--slug" in call and call[call.index("--slug") + 1] == project
                )
                self.assertEqual(workspace, project_call[5])
                self.assertEqual(workspace, project_call[project_call.index("--primary") + 1])
            second = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True, check=False)
            self.assertEqual(0, second.returncode, second.stderr)
            calls_after_second = log.read_text(encoding="utf-8").splitlines()
            create_calls_second = [line for line in calls_after_second[len(calls_after_first):] if '"create"' in line]
            self.assertEqual([], create_calls_second, create_calls_second)
            self.assertNotIn("DISCORD", log.read_text(encoding="utf-8").upper())

    def test_bootstrap_apply_fails_closed_when_state_cannot_be_read(self):
        fake_source = textwrap.dedent("""\
            #!/usr/bin/env python3
            import json, os, pathlib, sys
            args = sys.argv[1:]
            with pathlib.Path(os.environ["HERMES_FAKE_LOG"]).open("a", encoding="utf-8") as out:
                out.write(json.dumps(args) + "\\n")
            filtered = args[2:] if args[:2] == ["-p", "default"] else args
            mode = os.environ["FAIL_MODE"]
            if filtered[:3] == ["kanban", "boards", "list"]:
                if mode == "board-error":
                    raise SystemExit(42)
                if mode == "board-invalid":
                    print("not-json")
                    raise SystemExit(0)
                print("[]")
                raise SystemExit(0)
            if filtered[:2] == ["project", "show"]:
                raise SystemExit(42)
            raise SystemExit("unexpected mutation command")
        """)
        for mode in ("board-error", "board-invalid", "project-error"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                home = base / "home"
                hermes_home = home / ".hermes"
                hermes_home.mkdir(parents=True)
                sentinel = hermes_home / "sentinel.txt"
                sentinel.write_text("unchanged\n", encoding="utf-8")
                fake = base / "hermes"
                fake.write_text(fake_source, encoding="utf-8")
                fake.chmod(0o755)
                log = base / "calls.jsonl"
                env = os.environ.copy()
                env.update({
                    "HOME": str(home), "HERMES_HOME": str(hermes_home),
                    "HERMES_BIN": str(fake), "HERMES_FAKE_LOG": str(log),
                    "FAIL_MODE": mode,
                })
                result = subprocess.run(
                    ["bash", str(ROOT / "scripts/bootstrap.sh"), "--apply"],
                    cwd=ROOT, env=env, text=True, capture_output=True, check=False,
                )
                self.assertNotEqual(0, result.returncode, result.stdout)
                self.assertEqual("unchanged\n", sentinel.read_text(encoding="utf-8"))
                self.assertFalse((hermes_home / "profiles").exists())
                calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
                self.assertFalse(any("create" in call for call in calls), calls)

    def test_bootstrap_rejects_dangling_profile_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "home"
            hermes_home = home / ".hermes"
            (hermes_home / "profiles/pulse").mkdir(parents=True)
            (hermes_home / "profiles/algua").symlink_to(base / "missing-target", target_is_directory=True)
            fake = base / "hermes"
            fake.write_text(textwrap.dedent("""\
                #!/usr/bin/env python3
                import json, sys
                args = sys.argv[1:]
                filtered = args[2:] if args[:2] == ["-p", "default"] else args
                if filtered[:3] == ["kanban", "boards", "list"]:
                    print("[]")
                elif filtered[:2] == ["project", "show"]:
                    print(f"project: no such project: {filtered[2]}", file=sys.stderr)
                    raise SystemExit(1)
                else:
                    raise SystemExit("unexpected mutation command")
            """), encoding="utf-8")
            fake.chmod(0o755)
            env = os.environ.copy()
            env.update({"HOME": str(home), "HERMES_HOME": str(hermes_home), "HERMES_BIN": str(fake)})
            result = subprocess.run(
                ["bash", str(ROOT / "scripts/bootstrap.sh"), "--apply"],
                cwd=ROOT, env=env, text=True, capture_output=True, check=False,
            )
            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("could not create profile directory", result.stderr)
            self.assertTrue((hermes_home / "profiles/algua").is_symlink())


if __name__ == "__main__":
    unittest.main()
