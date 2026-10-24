from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {"lnx", "pulse", "algua", "meabeclick", "meabeclickux", "meabeclickeng", "meabeclickgrowth"}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PackContractTests(unittest.TestCase):
    def test_exact_profiles_pin_and_complete_skill_classification(self):
        packs = json.loads((ROOT / "skills/packs.json").read_text(encoding="utf-8"))
        self.assertEqual("5d9ac621d4b2862c94ff8aa419f2f9fc6c9f68f4", packs["nixkit"]["commit"])
        self.assertEqual(64, len(packs["nixkit"]["sources_sha256"]))
        self.assertEqual("24.22.1", packs["nixkit"]["node_runtime"])
        self.assertEqual(PROFILES, set(packs["profiles"]))
        self.assertNotIn("global", packs["packs"])
        self.assertNotIn("universal", packs["packs"])
        self.assertTrue(all(packs["profiles"][profile] for profile in PROFILES))
        persistent = set().union(*(set(value) for value in packs["packs"].values()))
        task_only = set(packs["task_only"])
        excluded = set(packs["excluded"])
        self.assertFalse(persistent & task_only)
        self.assertFalse(persistent & excluded)
        self.assertFalse(task_only & excluded)
        self.assertEqual(41, len(persistent | task_only | excluded))

    def test_installer_compile_time_pin_and_topology_match_canonical_manifest(self):
        installer = load_module("skill_installer_contract", ROOT / "scripts/install-skills.py")
        manifest = json.loads((ROOT / "skills/packs.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["nixkit"]["repository"], installer.NIXKIT_REPOSITORY)
        self.assertEqual(manifest["nixkit"]["commit"], installer.NIXKIT_COMMIT)
        self.assertEqual(manifest["nixkit"]["sources_sha256"], installer.NIXKIT_SOURCES_SHA256)
        self.assertEqual(manifest["nixkit"]["node_runtime"], installer.NODE_RUNTIME)
        self.assertEqual(manifest["packs"], installer.EXPECTED_PACKS)
        self.assertEqual(manifest["profiles"], installer.EXPECTED_ASSIGNMENTS)
        self.assertEqual(PROFILES, set(installer.PROFILE_MAP))

    def test_policy_has_hard_gates_and_threshold(self):
        packs = json.loads((ROOT / "skills/packs.json").read_text(encoding="utf-8"))
        self.assertEqual(80, packs["governance"]["minimum_score"])
        self.assertEqual(
            {"relevance", "provenance", "reliability", "safety_privacy", "license", "hermes_compatibility", "non_duplication"},
            set(packs["governance"]["hard_gates"]),
        )
        self.assertEqual("evidence_only", packs["governance"]["popularity"])


class SkillInstallerTests(unittest.TestCase):
    def setUp(self):
        self.script = ROOT / "scripts/install-skills.py"

    def _fixture(self, base: Path):
        home = base / "home"
        hermes_home = home / ".hermes"
        kit = base / "kit"
        kit.mkdir()
        packs = json.loads((ROOT / "skills/packs.json").read_text(encoding="utf-8"))
        source_skills = sorted({
            skill
            for values in packs["packs"].values()
            for skill in values
        } | set(packs["task_only"]) | set(packs["excluded"]))
        source_skills.remove("agent-browser")
        sources = [
            {"repo": "example/source", "ref": "b" * 40, "skills": source_skills},
            {"repo": "vercel-labs/agent-browser", "ref": "dac13bb87468fe9d74a040d862720f6cc17a9565", "skills": ["agent-browser"]},
        ]
        (kit / "sources.json").write_text(json.dumps(sources), encoding="utf-8")
        (kit / "install.mjs").write_text("// fixture: execution is intercepted by fake npx\n", encoding="utf-8")
        bin_dir = base / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "npx"
        fake.write_text(textwrap.dedent("""\
            #!/usr/bin/env python3
            import json, os, pathlib, sys
            pathlib.Path(os.environ["NIXKIT_LOG"]).write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
        """), encoding="utf-8")
        fake.chmod(0o755)
        subprocess.run(["git", "init", "-q"], cwd=kit, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=kit, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=kit, check=True)
        subprocess.run(["git", "add", "."], cwd=kit, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=kit, check=True)
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=kit, text=True).strip()
        packs["nixkit"]["commit"] = commit
        import hashlib
        packs["nixkit"]["sources_sha256"] = hashlib.sha256((kit / "sources.json").read_bytes()).hexdigest()
        fixture_root = base / "repo"
        (fixture_root / "scripts").mkdir(parents=True)
        (fixture_root / "skills").mkdir()
        script = fixture_root / "scripts/install-skills.py"
        source = self.script.read_text(encoding="utf-8")
        source = source.replace("5d9ac621d4b2862c94ff8aa419f2f9fc6c9f68f4", commit)
        source = source.replace("8c465cac697c5dc90a37e3a75242bac2f178c8768d7181883a3b9d673670b656", packs["nixkit"]["sources_sha256"])
        script.write_text(source, encoding="utf-8")
        manifest = fixture_root / "skills/packs.json"
        manifest.write_text(json.dumps(packs), encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=fixture_root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=fixture_root, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=fixture_root, check=True)
        subprocess.run(["git", "add", "."], cwd=fixture_root, check=True)
        subprocess.run(["git", "commit", "-qm", "canonical fixture"], cwd=fixture_root, check=True)
        env = os.environ.copy()
        env.update({"HOME": str(home), "HERMES_HOME": str(hermes_home), "NIXKIT_LOG": str(base / "calls.json"), "PATH": str(bin_dir) + os.pathsep + env["PATH"]})
        return home, hermes_home, kit, manifest, script, fixture_root, env

    def test_preview_is_pure_and_apply_binds_profile_revision_and_exact_subset(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home, hermes_home, kit, manifest, script, fixture_root, env = self._fixture(base)
            command = ["python3", str(script), "--nixkit", str(kit), "--profile", "pulse"]
            preview = subprocess.run(command, cwd=fixture_root, env=env, text=True, capture_output=True)
            self.assertEqual(0, preview.returncode, preview.stderr)
            self.assertIn("PREVIEW", preview.stdout)
            self.assertIn('"npx" "--yes" "node@24.22.1"', preview.stdout)
            self.assertIn(json.dumps(str(kit / "install.mjs")), preview.stdout)
            self.assertFalse((base / "calls.json").exists())
            self.assertFalse(hermes_home.exists())
            applied = subprocess.run(command + ["--apply"], cwd=fixture_root, env=env, text=True, capture_output=True)
            self.assertEqual(0, applied.returncode, applied.stderr)
            repeated = subprocess.run(command + ["--apply"], cwd=fixture_root, env=env, text=True, capture_output=True)
            self.assertEqual(0, repeated.returncode, repeated.stderr)
            args = json.loads((base / "calls.json").read_text(encoding="utf-8"))
            self.assertEqual(["--yes", "node@24.22.1", str(kit / "install.mjs"), "--apply", "--skills", "--agent", "hermes", "--prefix", str(hermes_home / "profiles/pulse")], args[:9])
            self.assertEqual(["--skill"] * len(args[9::2]), args[9::2])
            packs = json.loads(manifest.read_text(encoding="utf-8"))
            expected = sorted({skill for pack in packs["profiles"]["pulse"] for skill in packs["packs"][pack]})
            self.assertEqual(expected, args[10::2])
            (fixture_root / "untracked").write_text("dirty", encoding="utf-8")
            refused = subprocess.run(command + ["--apply"], cwd=fixture_root, env=env, text=True, capture_output=True)
            self.assertNotEqual(0, refused.returncode)
            self.assertIn("including untracked", refused.stderr)

    def test_rejects_dirty_checkout_symlink_home_and_unapproved_addition(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home, hermes_home, kit, manifest, script, fixture_root, env = self._fixture(base)
            (kit / "dirty").write_text("x", encoding="utf-8")
            command = ["python3", str(script), "--nixkit", str(kit)]
            result = subprocess.run(command + ["--profile", "lnx"], cwd=fixture_root, env=env, text=True, capture_output=True)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("clean", result.stderr)
            (kit / "dirty").unlink()
            hermes_home.parent.mkdir(parents=True)
            hermes_home.symlink_to(base / "elsewhere", target_is_directory=True)
            result = subprocess.run(command + ["--profile", "lnx"], cwd=fixture_root, env=env, text=True, capture_output=True)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("symlink", result.stderr)
            result = subprocess.run(command + ["--profile", "pulse", "--skill", "agent-browser"], cwd=fixture_root, env=env, text=True, capture_output=True)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("approval", result.stderr)

    def test_two_commit_approval_loads_manifest_and_proposal_from_ancestor(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home, hermes_home, kit, manifest_path, script, fixture_root, env = self._fixture(base)
            manifest = json.loads(manifest_path.read_text()); manifest["approved_additions"]["pulse"] = ["agent-browser"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            revision = "dac13bb87468fe9d74a040d862720f6cc17a9565"; repository = "vercel-labs/agent-browser"; skill_path = "skills/agent-browser"
            proposal = {
                "schema_version": 1, "proposal_id": "pulse-agent-browser", "profile": "pulse", "name": "agent-browser",
                "summary": "Audited browser skill", "rationale": "Fills a role gap",
                "source_url": f"https://github.com/{repository}/tree/{revision}/{skill_path}", "repository": repository,
                "skill_path": skill_path, "revision": revision, "license": "MIT",
                "evidence_urls": [f"https://github.com/{repository}/tree/{revision}/{skill_path}", f"https://github.com/{repository}/blob/{revision}/LICENSE"],
                "risks": [], "score_components": {"role_value": 27, "evidence_quality": 18, "security_provenance": 18, "hermes_compatibility": 14, "maintenance": 9, "documentation_license": 4},
                "score": 90, "gates": {name: True for name in ("relevance", "provenance", "reliability", "safety_privacy", "license", "hermes_compatibility", "non_duplication")},
                "gate_evidence": {name: "Reviewed evidence" for name in ("relevance", "provenance", "reliability", "safety_privacy", "license", "hermes_compatibility", "non_duplication")}, "status": "candidate",
            }
            proposal_path = fixture_root / "skills/proposals/pulse-agent-browser.json"; proposal_path.parent.mkdir(); proposal_path.write_text(json.dumps(proposal))
            subprocess.run(["git", "add", "."], cwd=fixture_root, check=True); subprocess.run(["git", "commit", "-qm", "propose skill"], cwd=fixture_root, check=True)
            manifest_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=fixture_root, text=True).strip()
            receipt = {"schema_version": 1, "proposal_id": "pulse-agent-browser", "profile": "pulse", "skills": ["agent-browser"], "approved_by": "Lior", "approved_at": "2026-10-24T15:00:00Z", "manifest_commit": manifest_commit}
            receipt_path = fixture_root / "skills/approvals/pulse-agent-browser.json"; receipt_path.parent.mkdir(); receipt_path.write_text(json.dumps(receipt))
            subprocess.run(["git", "add", "."], cwd=fixture_root, check=True); subprocess.run(["git", "commit", "-qm", "record approval"], cwd=fixture_root, check=True)
            command = ["python3", str(script), "--nixkit", str(kit), "--profile", "pulse", "--skill", "agent-browser", "--approval", str(receipt_path)]
            result = subprocess.run(command, cwd=fixture_root, env=env, text=True, capture_output=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("agent-browser", result.stdout)
            receipt["approved_at"] = "2026-10-24 15:00:00"; receipt_path.write_text(json.dumps(receipt))
            dirty = subprocess.run(command, cwd=fixture_root, env=env, text=True, capture_output=True)
            self.assertNotEqual(0, dirty.returncode); self.assertIn("dirty", dirty.stderr)

    def test_proposal_requires_catalog_binding_and_exact_same_origin_license_url(self):
        installer = load_module("skill_installer_provenance", self.script)
        revision = "dac13bb87468fe9d74a040d862720f6cc17a9565"
        repository = "vercel-labs/agent-browser"
        proposal = {
            "schema_version": 1, "proposal_id": "pulse-agent-browser", "profile": "pulse", "name": "agent-browser",
            "summary": "Audited browser skill", "rationale": "Fills a role gap",
            "source_url": f"https://github.com/{repository}/tree/{revision}/skills/agent-browser", "repository": repository,
            "skill_path": "skills/agent-browser", "revision": revision, "license": "MIT",
            "evidence_urls": [f"https://github.com/{repository}/tree/{revision}/skills/agent-browser", f"https://github.com/{repository}/blob/{revision}/LICENSE"],
            "risks": [], "score_components": {"role_value": 27, "evidence_quality": 18, "security_provenance": 18, "hermes_compatibility": 14, "maintenance": 9, "documentation_license": 4},
            "score": 90, "gates": {name: True for name in installer.HARD_GATES},
            "gate_evidence": {name: "Reviewed evidence" for name in installer.HARD_GATES}, "status": "candidate",
        }
        catalog = {"agent-browser": (repository, revision)}
        installer._validate_proposal(proposal, "pulse-agent-browser", "pulse", {"agent-browser"}, catalog)
        with self.assertRaisesRegex(installer.Refusal, "uniquely belong"):
            installer._validate_proposal(proposal, "pulse-agent-browser", "pulse", {"agent-browser"}, {"agent-browser": ("evil/repo", revision)})
        proposal["evidence_urls"][1] = f"https://github.com.evil.invalid/{repository}/blob/{revision}/LICENSE"
        with self.assertRaisesRegex(installer.Refusal, "same-origin"):
            installer._validate_proposal(proposal, "pulse-agent-browser", "pulse", {"agent-browser"}, catalog)

    def test_proposal_runtime_enforces_all_bounded_schema_fields(self):
        installer = load_module("skill_installer_bounds", self.script)
        revision = "a" * 40; repository = "example/useful"; source = f"https://github.com/{repository}/tree/{revision}/skills/useful"
        proposal = {
            "schema_version": 1, "proposal_id": "pulse-useful", "profile": "pulse", "name": "useful",
            "summary": "Useful", "rationale": "Needed", "source_url": source, "repository": repository,
            "skill_path": "skills/useful", "revision": revision, "license": "MIT",
            "evidence_urls": [source, f"https://github.com/{repository}/blob/{revision}/LICENSE"], "risks": [],
            "score_components": {"role_value": 27, "evidence_quality": 18, "security_provenance": 18, "hermes_compatibility": 14, "maintenance": 9, "documentation_license": 4},
            "score": 90, "gates": {gate: True for gate in installer.HARD_GATES},
            "gate_evidence": {gate: "Reviewed" for gate in installer.HARD_GATES}, "status": "candidate",
        }
        catalog = {"useful": (repository, revision)}
        installer._validate_proposal(proposal, "pulse-useful", "pulse", {"useful"}, catalog)
        mutations = {
            "string-risks": lambda p: p.update(risks="not-a-list"),
            "overlong-summary": lambda p: p.update(summary="x" * (installer.MAX_TEXT + 1)),
            "overlong-gate-evidence": lambda p: p["gate_evidence"].update(relevance="x" * (installer.MAX_TEXT + 1)),
            "one-evidence-url": lambda p: p.update(evidence_urls=[source]),
        }
        for label, mutate in mutations.items():
            changed = json.loads(json.dumps(proposal)); mutate(changed)
            with self.subTest(label=label), self.assertRaises(installer.Refusal):
                installer._validate_proposal(changed, "pulse-useful", "pulse", {"useful"}, catalog)

    def test_proposal_and_report_schema_limits_match_runtime(self):
        installer = load_module("skill_installer_schema_limits", self.script)
        collector = load_module("skill_collector_schema_limits", ROOT / "automation/skill-scout/collect.py")
        for relative, candidate in (
            ("skills/proposal.schema.json", None),
            ("automation/skill-scout/report.schema.json", "candidate"),
        ):
            schema = json.loads((ROOT / relative).read_text(encoding="utf-8"))
            contract = schema if candidate is None else schema["$defs"][candidate]
            self.assertEqual(installer.MAX_TEXT, collector.MAX_TEXT)
            self.assertEqual(installer.MAX_RISKS, collector.MAX_RISKS)
            self.assertEqual(installer.MAX_EVIDENCE_URLS, collector.MAX_EVIDENCE_URLS)
            self.assertEqual(installer.MAX_TEXT, contract["properties"]["summary"]["maxLength"])
            self.assertEqual(installer.MAX_RISKS, contract["properties"]["risks"]["maxItems"])
            self.assertEqual(installer.MAX_TEXT, contract["properties"]["risks"]["items"]["maxLength"])
            self.assertEqual(installer.MAX_EVIDENCE_URLS, contract["properties"]["evidence_urls"]["maxItems"])
            self.assertEqual(2, contract["properties"]["evidence_urls"]["minItems"])
            for gate in installer.HARD_GATES:
                self.assertEqual(installer.MAX_TEXT, schema["$defs"]["gate_evidence"]["properties"][gate]["maxLength"])

    def test_proposal_schema_has_no_unvalidated_optional_popularity_field(self):
        schema = json.loads((ROOT / "skills/proposal.schema.json").read_text(encoding="utf-8"))
        self.assertNotIn("popularity_evidence", schema["properties"])

    def test_manifest_override_is_not_an_interface(self):
        result = subprocess.run(["python3", str(self.script), "--manifest", "/tmp/evil.json", "--profile", "lnx"], cwd=ROOT, text=True, capture_output=True)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("unrecognized arguments", result.stderr)


class ScoutTests(unittest.TestCase):
    def setUp(self):
        self.collect = load_module("skill_scout_collect", ROOT / "automation/skill-scout/collect.py")

    def _candidate(self, name="useful", path="skills/useful", repository="example/useful"):
        return {
            "name": name,
            "summary": "A relevant audited skill",
            "rationale": "It fills a verified role gap",
            "source_url": f"https://github.com/{repository}/tree/{'a' * 40}/{path}",
            "repository": repository,
            "skill_path": path,
            "revision": "a" * 40,
            "license": "MIT",
            "evidence_urls": [
                f"https://github.com/{repository}/tree/{'a' * 40}/{path}",
                f"https://github.com/{repository}/blob/{'a' * 40}/LICENSE",
            ],
            "risks": [],
            "score_components": {
                "role_value": 27, "evidence_quality": 18, "security_provenance": 18,
                "hermes_compatibility": 14, "maintenance": 9, "documentation_license": 4,
            },
            "score": 90,
            "gates": {gate: True for gate in self.collect.HARD_GATES},
            "gate_evidence": {gate: f"Evidence for {gate}" for gate in self.collect.HARD_GATES},
        }

    def _packet(self, profile, week, candidates=None):
        return {
            "schema_version": 1, "week": week, "profile": profile,
            "generated_at": "2026-10-24T12:00:00Z",
            "checked_sources": ["https://github.com/topics/hermes-agent"],
            "rejected_count": 0, "candidates": candidates or [],
        }

    def _write_week(self, root, week, candidates_by_profile=None):
        candidates_by_profile = candidates_by_profile or {}
        for profile in self.collect.EXPECTED_PROFILES:
            packet = self._packet(profile, week, candidates_by_profile.get(profile, []))
            (root / f"{profile}.json").write_text(json.dumps(packet), encoding="utf-8")

    def test_jobs_are_staggered_local_first_and_aggregator_only_delivery_target(self):
        data = json.loads((ROOT / "automation/skill-scout/jobs.json").read_text(encoding="utf-8"))
        self.assertEqual("Asia/Jerusalem", data["timezone"])
        self.assertEqual(8, len(data["jobs"]))
        scouts = [job for job in data["jobs"] if job["kind"] == "scout"]
        aggregators = [job for job in data["jobs"] if job["kind"] == "aggregator"]
        self.assertEqual(7, len(scouts))
        self.assertEqual({"default", "pulse", "algua", "meabeclick", "meabeclickux", "meabeclickeng", "meabeclickgrowth"}, {job["hermes_profile"] for job in scouts})
        self.assertTrue(all(job["delivery"] == "local" for job in scouts))
        self.assertEqual(["telegram:6926015052"], [job["delivery_enabled"] for job in aggregators])
        self.assertTrue(aggregators[0]["continuity"])

    def test_collector_validates_all_packets_dedupes_and_silences_empty(self):
        week = "2026-W43"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = self._candidate(name="same", repository="Example/Useful")
            self._write_week(root, week, {"lnx": [candidate], "pulse": [candidate]})
            result = self.collect.collect_packets(root, week)
            self.assertEqual("ok", result["status"])
            self.assertEqual(1, len(result["candidates"]))
            self.assertEqual(["lnx", "pulse"], result["candidates"][0]["reported_by"])
            for path in root.glob("*.json"):
                data = json.loads(path.read_text(encoding="utf-8")); data["candidates"] = []
                path.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual("[SILENT]", self.collect.render_for_aggregator(self.collect.collect_packets(root, week)))
            (root / "pulse.json").unlink()
            failed = self.collect.collect_packets(root, week)
            self.assertEqual("invalid", failed["status"])
            self.assertNotEqual("[SILENT]", self.collect.render_for_aggregator(failed))

    def test_collector_rejects_missing_source_evidence(self):
        week = "2026-W43"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); self._write_week(root, week, {"lnx": [self._candidate()]})
            packet = json.loads((root / "pulse.json").read_text()); packet["checked_sources"] = []
            (root / "pulse.json").write_text(json.dumps(packet), encoding="utf-8")
            self.assertEqual("invalid", self.collect.collect_packets(root, week)["status"])
            packet = self._packet("pulse", week, [self._candidate()]); packet["candidates"][0]["evidence_urls"] = []
            (root / "pulse.json").write_text(json.dumps(packet), encoding="utf-8")
            self.assertEqual("invalid", self.collect.collect_packets(root, week)["status"])

    def test_collector_rejects_score_sum_and_component_limits(self):
        week = "2026-W43"
        for mutation in ("sum", "limit"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); candidate = self._candidate()
                if mutation == "sum": candidate["score"] = 89
                else: candidate["score_components"]["role_value"] = 31
                self._write_week(root, week, {"lnx": [candidate]})
                self.assertEqual("invalid", self.collect.collect_packets(root, week)["status"])

    def test_collector_rejects_false_gate(self):
        week = "2026-W43"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); candidate = self._candidate(); candidate["gates"]["license"] = False
            self._write_week(root, week, {"lnx": [candidate]})
            self.assertEqual("invalid", self.collect.collect_packets(root, week)["status"])

    def test_collector_keeps_same_repository_distinct_skill_paths(self):
        week = "2026-W43"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_week(root, week, {"lnx": [self._candidate(path="skills/one")], "pulse": [self._candidate(path="skills/two")]})
            result = self.collect.collect_packets(root, week)
            self.assertEqual("ok", result["status"])
            self.assertEqual(["skills/one", "skills/two"], [item["skill_path"] for item in result["candidates"]])

    def test_collector_rejects_conflicting_duplicate_evidence(self):
        week = "2026-W43"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); first = self._candidate(); second = self._candidate(); second["license"] = "Apache-2.0"
            self._write_week(root, week, {"lnx": [first], "pulse": [second]})
            result = self.collect.collect_packets(root, week)
            self.assertEqual("invalid", result["status"])
            self.assertTrue(any("conflicting evidence" in error for error in result["errors"]))

    def test_collector_rejects_mutable_or_unrelated_provenance(self):
        week = "2026-W43"
        mutations = {
            "mutable-source": lambda c: c.update(source_url="https://github.com/example/useful/tree/main/skills/useful"),
            "unrelated-license": lambda c: c.update(evidence_urls=[c["source_url"], f"https://github.com/other/repo/blob/{'a' * 40}/LICENSE"]),
            "mutable-license": lambda c: c.update(evidence_urls=[c["source_url"], "https://github.com/example/useful/blob/main/LICENSE"]),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); candidate = self._candidate(); mutate(candidate)
                self._write_week(root, week, {"lnx": [candidate]})
                self.assertEqual("invalid", self.collect.collect_packets(root, week)["status"])

    def test_collector_rejects_invalid_stale_and_timestamp_mismatched_weeks(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual("invalid", self.collect.collect_packets(Path(tmp), "2026-W99")["status"])
            self.assertEqual("invalid", self.collect.collect_packets(Path(tmp), "2025-W43")["status"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); self._write_week(root, "2026-W43")
            packet = json.loads((root / "lnx.json").read_text()); packet["generated_at"] = "2026-10-12T12:00:00Z"
            (root / "lnx.json").write_text(json.dumps(packet), encoding="utf-8")
            self.assertEqual("invalid", self.collect.collect_packets(root, "2026-W43")["status"])

    def test_collector_screens_secrets_controls_and_protected_paths_before_forwarding(self):
        week = "2026-W43"
        discord = "M" * 24 + "." + "N" * 6 + "." + "P" * 30
        webhook = "https://discord.com/api/webhooks/" + "1" * 18 + "/" + "W" * 60
        payloads = (
            "sk-" + "A" * 40, "ghp_" + "A" * 30, "github" + "_pat_" + "B" * 60,
            "AKIA" + "A" * 16, discord, webhook, "discord_webhook_token=" + "T" * 60, "xox" + "b-" + "1" * 12 + "-" + "C" * 30,
            "xox" + "p-" + "2" * 12 + "-" + "D" * 30, "-----BEGIN" + " PRIVATE KEY-----",
            "private/customer-payments/data.json", "bad\u0001control",
        )
        for payload in payloads:
            with self.subTest(payload=payload[:12]), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); candidate = self._candidate(); candidate["summary"] = payload
                self._write_week(root, week, {"lnx": [candidate]})
                result = self.collect.collect_packets(root, week)
                self.assertEqual("invalid", result["status"])
                self.assertEqual([], result["candidates"])
                self.assertNotIn(payload, self.collect.render_for_aggregator(result))
        ordinary = "https://github.com/example/repo/commit/" + "a" * 40
        self.assertEqual([], self.collect._screen_text(ordinary, "ordinary"))

    def test_collector_rejects_oversized_packet_and_bounds_rendering(self):
        week = "2026-W43"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); self._write_week(root, week)
            packet = self._packet("lnx", week, [self._candidate()])
            packet["candidates"][0]["gate_evidence"]["relevance"] = "x" * 200_000
            (root / "lnx.json").write_text(json.dumps(packet), encoding="utf-8")
            result = self.collect.collect_packets(root, week)
            self.assertEqual("invalid", result["status"])
            self.assertTrue(any("size limit" in error for error in result["errors"]), result)
            rendered = self.collect.render_for_aggregator({"week": week, "status": "invalid", "errors": ["x" * (self.collect.MAX_RENDER_BYTES + 1)], "candidates": []})
            self.assertLessEqual(len(rendered.encode("utf-8")), self.collect.MAX_RENDER_BYTES)
            self.assertNotIn("x" * 1000, rendered)

    def test_collector_rejects_deep_json_as_invalid_without_crashing(self):
        week = "2026-W43"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_week(root, week)
            deep = "[" * 1100 + "0" + "]" * 1100
            (root / "lnx.json").write_text(deep, encoding="utf-8")
            result = self.collect.collect_packets(root, week)
            self.assertEqual("invalid", result["status"])
            self.assertTrue(any("nesting" in error for error in result["errors"]))

    def test_scout_prompt_is_self_contained_and_names_every_field(self):
        prompt = (ROOT / "automation/skill-scout/scout-prompt.md").read_text(encoding="utf-8")
        for field in self.collect.PACKET_FIELDS | self.collect.CANDIDATE_FIELDS | set(self.collect.SCORE_LIMITS) | set(self.collect.HARD_GATES):
            self.assertIn(f'"{field}"', prompt, field)
        self.assertIn("complete packet contract", prompt)
        self.assertIn("installed skill inventory first", prompt)
        self.assertIn("public Hermes skill registries", prompt)
        self.assertIn("untrusted research content", prompt)


class ScoutSetupTests(unittest.TestCase):
    def setUp(self):
        self.setup = load_module("skill_scout_setup", ROOT / "scripts/setup-skill-scouts.py")

    def test_manifest_validation_is_exact_and_rejects_unknown_or_traversal_fields(self):
        spec = json.loads((ROOT / "automation/skill-scout/jobs.json").read_text(encoding="utf-8"))
        self.assertEqual(8, len(self.setup._canonical_spec(spec)))
        for mutation in ("unknown", "traversal", "delivery"):
            changed = json.loads(json.dumps(spec))
            if mutation == "unknown": changed["jobs"][0]["extra"] = True
            elif mutation == "traversal": changed["jobs"][0]["prompt_file"] = "../scout-prompt.md"
            else: changed["jobs"][0]["delivery"] = "telegram:evil"
            with self.subTest(mutation=mutation), self.assertRaises(self.setup.Refusal):
                self.setup._canonical_spec(changed)

    def test_test_store_override_requires_explicit_test_mode(self):
        with mock.patch.dict(os.environ, {"HERMES_SCOUT_TEST_STORE": "/tmp/fake"}, clear=False):
            os.environ.pop("NIX_OS_SCOUT_TEST_MODE", None)
            with self.assertRaisesRegex(self.setup.Refusal, "explicit test mode"):
                self.setup._job_store(Path("/tmp/home"), "default")
            os.environ["NIX_OS_SCOUT_TEST_MODE"] = "1"
            self.assertEqual(Path("/tmp/fake/default.json"), self.setup._job_store(Path("/tmp/home"), "default"))

    def test_collector_atomic_install_rejects_existing_temp_symlink_and_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "source.py"; destination = root / "collector.py"; target = root / "victim"
            source.write_text("safe", encoding="utf-8"); target.write_text("unchanged", encoding="utf-8")
            temporary = destination.with_suffix(".tmp")
            temporary.symlink_to(target)
            with self.assertRaisesRegex(self.setup.Refusal, "already exists"):
                self.setup._install_collector_atomic(destination, source)
            self.assertEqual("unchanged", target.read_text(encoding="utf-8"))
            self.assertTrue(temporary.is_symlink())
            temporary.unlink(); temporary.write_text("attacker", encoding="utf-8")
            with self.assertRaisesRegex(self.setup.Refusal, "already exists"):
                self.setup._install_collector_atomic(destination, source)
            self.assertEqual("attacker", temporary.read_text(encoding="utf-8"))

    def test_exact_job_requires_enabled_operational_state(self):
        desired = self.setup.EXPECTED_JOBS[0]
        actual = {
            "id": "fixture", "name": desired["name"], "schedule": {"kind": "cron", "value": desired["schedule"]},
            "prompt": self.setup._prompt(desired), "deliver": ["local"], "continuity": False, "script": None,
        }
        self.assertTrue(self.setup._is_exact(actual, desired))  # real legacy persisted shape
        for field, value in (("enabled", True), ("state", "scheduled"), ("status", "active")):
            changed = dict(actual); changed[field] = value
            self.assertTrue(self.setup._is_exact(changed, desired), (field, value))
        for field, value in (("enabled", False), ("state", "paused"), ("status", "disabled")):
            changed = dict(actual); changed[field] = value
            self.assertFalse(self.setup._is_exact(changed, desired), (field, value))

    def test_apply_rolls_back_new_jobs_and_collector_on_second_readback_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); home = base / "home"; state = base / "state"; log = base / "calls.jsonl"; counter = base / "count"
            state.mkdir()
            preexisting = [{"id": "keep-me", "name": "unrelated-user-job", "enabled": False}]
            (state / "pulse.json").write_text(json.dumps(preexisting), encoding="utf-8")
            fake = base / "hermes"
            fake.write_text(textwrap.dedent("""\
                #!/usr/bin/env python3
                import json, os, pathlib, sys
                args=sys.argv[1:]; profile=args[1]; cmd=args[2:]
                root=pathlib.Path(os.environ['FAKE_STATE']); f=root/f'{profile}.json'; jobs=json.loads(f.read_text()) if f.exists() else []
                with pathlib.Path(os.environ['FAKE_LOG']).open('a') as out: out.write(json.dumps(args)+'\\n')
                if cmd[:2]==['cron','list']:
                    raise SystemExit(0)
                if cmd[:2]==['cron','create']:
                    count_path=pathlib.Path(os.environ['FAKE_COUNT']); count=int(count_path.read_text())+1 if count_path.exists() else 1; count_path.write_text(str(count))
                    def value(flag, default=None): return cmd[cmd.index(flag)+1] if flag in cmd else default
                    job={'id':f'new-{count}', 'name':value('--name'), 'schedule':{'kind':'cron','value':cmd[2]}, 'prompt':cmd[3], 'deliver':[value('--deliver','local')], 'continuity':'--continuity' in cmd, 'script':value('--script')}
                    if count==2: job['enabled']=False
                    jobs.append(job); f.write_text(json.dumps(jobs)); print(job['id']); raise SystemExit(0)
                if cmd[:2]==['cron','remove']:
                    identifier=cmd[2]; jobs=[job for job in jobs if job.get('id')!=identifier]; f.write_text(json.dumps(jobs)); raise SystemExit(0)
                if cmd[:2]==['cron','edit']:
                    identifier=cmd[2]; job=next(job for job in jobs if job.get('id')==identifier); job['deliver']=[cmd[cmd.index('--deliver')+1]]; f.write_text(json.dumps(jobs)); raise SystemExit(0)
                raise SystemExit('unexpected '+repr(cmd))
            """), encoding="utf-8")
            fake.chmod(0o755)
            env = os.environ.copy(); env.update({
                "HOME": str(home), "HERMES_HOME": str(home / ".hermes"), "HERMES_BIN": str(fake),
                "FAKE_STATE": str(state), "FAKE_LOG": str(log), "FAKE_COUNT": str(counter),
                "HERMES_SCOUT_TEST_STORE": str(state), "NIX_OS_SCOUT_TEST_MODE": "1",
            })
            result = subprocess.run(["python3", str(ROOT / "scripts/setup-skill-scouts.py"), "--apply"], cwd=ROOT, env=env, text=True, capture_output=True)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("readback mismatch", result.stderr)
            all_jobs = [job for path in state.glob("*.json") for job in json.loads(path.read_text())]
            self.assertEqual(preexisting, all_jobs)
            self.assertFalse((home / ".hermes/scripts/skill-scout-collect.py").exists())
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual({"new-1", "new-2"}, {call[-1] for call in calls if call[2:4] == ["cron", "remove"]})

    def test_preview_create_readback_idempotence_and_drift_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "home"; state = base / "state"; log = base / "calls.jsonl"
            fake = base / "hermes"
            fake.write_text(textwrap.dedent("""\
                #!/usr/bin/env python3
                import json, os, pathlib, sys, uuid
                args=sys.argv[1:]; profile=args[1] if args[:1]==['-p'] else 'default'; cmd=args[2:] if args[:1]==['-p'] else args
                root=pathlib.Path(os.environ['FAKE_STATE']); root.mkdir(parents=True, exist_ok=True); f=root/f'{profile}.json'
                jobs=json.loads(f.read_text()) if f.exists() else []
                with pathlib.Path(os.environ['FAKE_LOG']).open('a') as out: out.write(json.dumps(args)+'\\n')
                if cmd[:2]==['cron','list']:
                    for j in jobs: print(f"  {j['id']} [active]\\n    Name:      {j['name']}\\n    Schedule:  {j['schedule_display']}\\n    Deliver:   {', '.join(j['deliver'])}")
                elif cmd[:2]==['cron','create']:
                    schedule,prompt=cmd[2],cmd[3]
                    def value(flag, default=None): return cmd[cmd.index(flag)+1] if flag in cmd else default
                    j={'id':uuid.uuid4().hex[:8], 'name':value('--name'), 'schedule':{'kind':'cron','value':schedule}, 'schedule_display':schedule, 'prompt':prompt, 'deliver':[value('--deliver','local')], 'continuity':'--continuity' in cmd, 'script':value('--script')}
                    jobs.append(j); f.write_text(json.dumps(jobs)); print(j['id'])
                elif cmd[:2]==['cron','edit']:
                    ref=cmd[2]; j=next(x for x in jobs if x['id']==ref or x['name']==ref); j['deliver']=[cmd[cmd.index('--deliver')+1]]; f.write_text(json.dumps(jobs))
                else: raise SystemExit('unexpected '+repr(cmd))
            """), encoding="utf-8")
            fake.chmod(0o755)
            env=os.environ.copy(); env.update({"HOME":str(home), "HERMES_HOME":str(home/".hermes"), "HERMES_BIN":str(fake), "FAKE_STATE":str(state), "FAKE_LOG":str(log), "HERMES_SCOUT_TEST_STORE":str(state), "NIX_OS_SCOUT_TEST_MODE":"1"})
            cmd=["python3", str(ROOT/"scripts/setup-skill-scouts.py")]
            preview=subprocess.run(cmd, cwd=ROOT, env=env, text=True, capture_output=True)
            self.assertEqual(0, preview.returncode, preview.stderr); self.assertIn("PREVIEW", preview.stdout); self.assertFalse(state.exists())
            first=subprocess.run(cmd+["--apply"], cwd=ROOT, env=env, text=True, capture_output=True)
            self.assertEqual(0, first.returncode, first.stderr)
            before=log.read_text().splitlines()
            second=subprocess.run(cmd+["--apply"], cwd=ROOT, env=env, text=True, capture_output=True)
            self.assertEqual(0, second.returncode, second.stderr)
            after=log.read_text().splitlines()[len(before):]
            self.assertFalse(any('"create"' in line for line in after), after)
            enabled=subprocess.run(cmd+["--apply", "--enable-delivery"], cwd=ROOT, env=env, text=True, capture_output=True)
            self.assertEqual(0, enabled.returncode, enabled.stderr)
            preview_enabled=subprocess.run(cmd, cwd=ROOT, env=env, text=True, capture_output=True)
            self.assertIn("nix-skill-scout-aggregate @ 0 21 * * 6 -> telegram:6926015052", preview_enabled.stdout)
            before_preserve=log.read_text().splitlines()
            preserve=subprocess.run(cmd+["--apply"], cwd=ROOT, env=env, text=True, capture_output=True)
            self.assertEqual(0, preserve.returncode, preserve.stderr)
            self.assertFalse(any('"edit"' in line for line in log.read_text().splitlines()[len(before_preserve):]))
            aggregator=next(job for job in json.loads((state/"default.json").read_text()) if job["name"]=="nix-skill-scout-aggregate")
            self.assertEqual(["telegram:6926015052"], aggregator["deliver"])
            jobs=json.loads((state/"pulse.json").read_text()); jobs[0]["prompt"]="drift"; (state/"pulse.json").write_text(json.dumps(jobs))
            drift=subprocess.run(cmd+["--apply"], cwd=ROOT, env=env, text=True, capture_output=True)
            self.assertNotEqual(0, drift.returncode); self.assertIn("drift", drift.stderr.lower())


if __name__ == "__main__":
    unittest.main()
