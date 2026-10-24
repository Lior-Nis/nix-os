from __future__ import annotations

import importlib.util
import hashlib
import json
import os
from pathlib import Path
import re
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
        self.assertEqual("f5377ca3219daf4f33f6e8525f9438318dabcd2f", packs["nixkit"]["commit"])
        self.assertEqual("110ecc3872b4fe45ede667afd4ca757d59aef850672045a639eae5ef78415a83", packs["nixkit"]["sources_sha256"])
        self.assertEqual(64, len(packs["nixkit"]["sources_sha256"]))
        self.assertEqual("24.22.1", packs["nixkit"]["node_runtime"])
        self.assertEqual(PROFILES, set(packs["profiles"]))
        self.assertEqual({
            "lnx": ["caveman", "watch", "todoist-cli"],
            "pulse": ["technical-project-management"],
            "algua": [],
            "meabeclick": [],
            "meabeclickux": ["rtl-design", "web-accessibility"],
            "meabeclickeng": ["performance", "web-accessibility", "systematic-debugging", "test-driven-development"],
            "meabeclickgrowth": ["analytics", "customer-research", "social-media-content-calendar"],
        }, packs["approved_additions"])
        self.assertTrue(all(not values for values in packs["proposed_pack_additions"].values()))
        self.assertEqual(["product-development"], packs["approved_pack_additions"]["lnx"])
        self.assertTrue(all(not values for profile, values in packs["approved_pack_additions"].items() if profile != "lnx"))
        self.assertNotIn("global", packs["packs"])
        self.assertEqual([], packs["packs"]["public-research"])
        self.assertIn("research", packs["excluded"])
        persistent = {
            skill
            for profile_packs in packs["profiles"].values()
            for pack in profile_packs
            for skill in packs["packs"][pack]
        }
        self.assertNotIn("research", persistent)
        self.assertNotIn("universal", packs["packs"])
        self.assertTrue(all(packs["profiles"][profile] for profile in PROFILES))
        persistent = set().union(*(set(value) for value in packs["packs"].values()))
        task_only = set(packs["task_only"])
        excluded = set(packs["excluded"])
        self.assertFalse(persistent & task_only)
        self.assertFalse(persistent & excluded)
        self.assertFalse(task_only & excluded)
        self.assertEqual(57, len(persistent | task_only | excluded))
        self.assertIn("watch", task_only)

    def test_product_pack_is_exact_approved_and_only_changes_lnx_effective_set(self):
        packs = json.loads((ROOT / "skills/packs.json").read_text(encoding="utf-8"))
        expected = ["lnx-grilling", "lnx-grill-me", "lnx-domain-modeling", "lnx-grill-with-docs", "lnx-to-spec", "lnx-writing-for-agents", "nix-idea-to-mvp", "writing-plans", "subagent-driven-development"]
        self.assertEqual(expected, packs["packs"]["product-development"])
        self.assertEqual(["baseline-evidence", "orchestrator-control"], packs["profiles"]["lnx"])
        self.assertNotIn("verification-before-completion", expected)
        for profile in PROFILES:
            effective = {skill for pack in packs["profiles"][profile] + packs["approved_pack_additions"][profile] for skill in packs["packs"][pack]}
            baseline = {skill for pack in packs["profiles"][profile] for skill in packs["packs"][pack]}
            if profile == "lnx":
                self.assertEqual(baseline | set(expected), effective, profile)
            else:
                self.assertEqual(baseline, effective, profile)

    def test_product_pack_proposal_exactly_binds_request_and_pins(self):
        proposal = json.loads((ROOT / "skills/pack-proposals/lnx-product-development-92338765.json").read_text(encoding="utf-8"))
        self.assertEqual("lnx-product-development-92338765", proposal["proposal_id"])
        self.assertEqual("lnx", proposal["profile"])
        self.assertEqual("product-development", proposal["pack"])
        self.assertEqual("92338765a1cc942b2a20dda3f1e220d6be0225e1", proposal["nixkit"]["commit"])
        self.assertEqual("da5f36fc4c470fa28ffdcab1a6c6aaa3750bded3", proposal["nixkit"]["snapshot_commit"])
        self.assertEqual("6493103af689bdf4bae5455e1d901646fe079e51a69c53b6f5bcf57c62786d21", proposal["nixkit"]["sources_sha256"])
        self.assertEqual({"kind": "request/proposal", "platform": "discord", "author_id": "454290355320520714", "channel_id": "1563181903253737542", "message_id": "1563496182829948941", "quote": "sync it", "timestamp": "2026-10-24T10:15:38.341000+00:00"}, proposal["request_evidence"])
        self.assertEqual("pending_approval", proposal["status"])
        receipt = json.loads((ROOT / "skills/pack-approvals/lnx-product-development-92338765.json").read_text(encoding="utf-8"))
        self.assertEqual("083d008d3a83cd178e1f79bf962967ae7054fc0e", receipt["proposal_git_commit"])
        self.assertEqual("06db117e1d84486a50f7beaae32f83fc3540ca8fd01eb5dc7fcf0f9e62100288", receipt["proposal_file_sha256"])
        self.assertEqual({"kind": "approval", "platform": "discord", "author_id": "454290355320520714", "channel_id": "1563181903253737542", "message_id": "1563556252829622396", "quote": "approve lnx-product-development-92338765 at 083d008d3a83cd178e1f79bf962967ae7054fc0e", "timestamp": "2026-10-24T14:14:20.145000+00:00"}, receipt["approval_evidence"])

    def test_exact_eleven_proposals_preserve_selected_candidate_evidence(self):
        expected = {
            "lnx-todoist-cli-340d7b21": ("lnx", "todoist-cli", "392101a83690254bb49e8afcca26f925912f6582239fed00c670c18bee95fb16"),
            "pulse-technical-project-management-7f446e60": ("pulse", "technical-project-management", "baba66152591061ee8976890094eec5f5f61c75040ac819759bc0331fe1f7ab6"),
            "meabeclickux-rtl-design-b7c52294": ("meabeclickux", "rtl-design", "a40394d43bac390bd9ac35af925e75480388d5363e8266ec7c3cc9108bc0f2ad"),
            "meabeclickux-web-accessibility-7f446e60": ("meabeclickux", "web-accessibility", "cfd82febb9b9b2918802be38094c0504c4efa5cc101461df753c03251329812f"),
            "meabeclickeng-performance-afa8da94": ("meabeclickeng", "performance", "03f5621c95234d6b36bce88ae56d4b34dbf398cc7359baab554184349a9e29ee"),
            "meabeclickeng-web-accessibility-7f446e60": ("meabeclickeng", "web-accessibility", "cb9fdd69b877365f877b27f6d4630ed36bca37c2a6025fc5987af04c4a641200"),
            "meabeclickeng-systematic-debugging-51414605": ("meabeclickeng", "systematic-debugging", "79aea3a17afe46460848c3fbacb42d13e8dd9373cde1ae6379020d2062dac724"),
            "meabeclickeng-test-driven-development-51414605": ("meabeclickeng", "test-driven-development", "0cc56d15a8cb3d3f5ffc4c888e677be037625140c274b11934ce5bf4682fa6c8"),
            "meabeclickgrowth-analytics-e85f3cbc": ("meabeclickgrowth", "analytics", "21b77593ee901f5629e52db84d2df9d4c8b13629056cc8185135dbec36fbf69d"),
            "meabeclickgrowth-customer-research-e85f3cbc": ("meabeclickgrowth", "customer-research", "dc0058708aefc89b3d7b5b3299f0d82bf90fb5e381ec785291a3560b72fd1746"),
            "meabeclickgrowth-social-media-content-calendar-0319e113": ("meabeclickgrowth", "social-media-content-calendar", "9bcebf18e107574437e6ebdd610ed86fbb9d02cd5920ab63a63ef5604c3a578f"),
        }
        actual_new = {path.stem for path in (ROOT / "skills/proposals").glob("*.json")} - {"lnx-caveman-d8ede5cf", "lnx-watch-a9cb5b57"}
        self.assertEqual(set(expected), actual_new)
        for proposal_id, (profile, name, digest) in expected.items():
            proposal = json.loads((ROOT / f"skills/proposals/{proposal_id}.json").read_text(encoding="utf-8"))
            self.assertEqual((proposal_id, profile, name, "candidate"), (proposal["proposal_id"], proposal["profile"], proposal["name"], proposal["status"]))
            actual_digest = hashlib.sha256(json.dumps(proposal, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
            self.assertEqual(digest, actual_digest, proposal_id)
        expected_receipts = {"lnx-caveman-d8ede5cf.json", "lnx-watch-a9cb5b57.json"} | {f"{proposal_id}.json" for proposal_id in expected}
        self.assertEqual(expected_receipts, {path.name for path in (ROOT / "skills/approvals").glob("*.json")})

    def test_lnx_caveman_proposal_matches_pinned_source_and_policy(self):
        installer = load_module("skill_installer_caveman_proposal", ROOT / "scripts/install-skills.py")
        manifest = json.loads((ROOT / "skills/packs.json").read_text(encoding="utf-8"))
        proposal = json.loads((ROOT / "skills/proposals/lnx-caveman-d8ede5cf.json").read_text(encoding="utf-8"))
        catalog = {"caveman": ("JuliusBrussee/caveman", "d8ede5cf0c27cc86a074c3224bcbba280a76c60e", None)}
        installer._validate_proposal(
            proposal,
            "lnx-caveman-d8ede5cf",
            "lnx",
            {"caveman"},
            catalog,
        )
        with mock.patch.object(installer, "_tracked_clean"):
            installer._approval(
                ROOT / "skills/approvals/lnx-caveman-d8ede5cf.json",
                "lnx",
                manifest,
                {"caveman"},
                catalog,
            )

    def test_lnx_watch_proposal_matches_exact_local_source_and_policy(self):
        installer = load_module("skill_installer_watch_proposal", ROOT / "scripts/install-skills.py")
        proposal = json.loads((ROOT / "skills/proposals/lnx-watch-a9cb5b57.json").read_text(encoding="utf-8"))
        catalog = {"watch": ("its-nix/kit", installer.NIXKIT_COMMIT, "skills/watch")}
        installer._validate_proposal(proposal, "lnx-watch-a9cb5b57", "lnx", {"watch"}, catalog)
        manifest = json.loads((ROOT / "skills/packs.json").read_text(encoding="utf-8"))
        with mock.patch.object(installer, "_tracked_clean"):
            installer._approval(
                ROOT / "skills/approvals/lnx-watch-a9cb5b57.json",
                "lnx",
                manifest,
                {"watch"},
                catalog,
            )
        self.assertGreaterEqual(proposal["score"], 80)
        risk_text = " ".join(proposal["risks"]).lower()
        for required in ("youtube", "dependencies", "model provider", "2 gib", "four hours", "cached", "login", "cookies", "proxy", "paywall"):
            self.assertIn(required, risk_text)
        wrong_path = json.loads(json.dumps(proposal))
        wrong_path["skill_path"] = "skills/other"
        wrong_path["source_url"] = wrong_path["source_url"].replace("skills/watch", "skills/other")
        with self.assertRaisesRegex(installer.Refusal, "exact audited repository path"):
            installer._validate_proposal(wrong_path, "lnx-watch-a9cb5b57", "lnx", {"watch"}, catalog)

    def test_source_catalog_accepts_only_exact_audited_local_discriminator(self):
        installer = load_module("skill_installer_local_catalog", ROOT / "scripts/install-skills.py")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sources.json"
            remote = sorted(installer.NIXKIT_SKILLS - {"watch"})
            valid = [{"repo": "example/catalog", "ref": "a" * 40, "skills": remote}, {"local": "skills", "skills": ["watch"]}]
            path.write_text(json.dumps(valid), encoding="utf-8")
            catalog = installer._source_catalog(path)
            self.assertEqual(("its-nix/kit", installer.NIXKIT_COMMIT, "skills/watch"), catalog["watch"])
            mutations = (
                [{"repo": "example/catalog", "ref": "a" * 40, "skills": remote + ["watch"]}],
                [valid[0], {"local": "skills", "skills": ["watch"], "ref": "a" * 40}],
                [valid[0], {"local": "other", "skills": ["watch"]}],
                [valid[0], {"local": "skills", "skills": ["watch", "caveman"]}],
            )
            for changed in mutations:
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaises(installer.Refusal):
                    installer._source_catalog(path)

    def test_source_catalog_normalizes_and_provenance_binds_optional_github_path(self):
        installer = load_module("skill_installer_scoped_catalog", ROOT / "scripts/install-skills.py")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sources.json"
            ordinary = sorted(installer.NIXKIT_SKILLS - {"watch", "social-media-content-calendar"})
            scoped_path = "optional-skills/creative/social-media-content-calendar"
            valid = [
                {"repo": "example/catalog", "ref": "a" * 40, "skills": ordinary},
                {"repo": "NousResearch/hermes-agent", "ref": "b" * 40, "path": scoped_path, "skills": ["social-media-content-calendar"]},
                {"local": "skills", "skills": ["watch"]},
            ]
            path.write_text(json.dumps(valid), encoding="utf-8")
            catalog = installer._source_catalog(path)
            self.assertEqual(("NousResearch/hermes-agent", "b" * 40, scoped_path), catalog["social-media-content-calendar"])
            proposal = json.loads((ROOT / "skills/proposals/meabeclickgrowth-social-media-content-calendar-0319e113.json").read_text(encoding="utf-8"))
            bound = {"social-media-content-calendar": (proposal["repository"], proposal["revision"], proposal["skill_path"])}
            installer._validate_proposal(proposal, proposal["proposal_id"], proposal["profile"], {proposal["name"]}, bound)
            wrong = json.loads(json.dumps(proposal)); wrong["skill_path"] = "optional-skills/social-media-content-calendar"; wrong["source_url"] = f"https://github.com/{wrong['repository']}/tree/{wrong['revision']}/{wrong['skill_path']}"; wrong["evidence_urls"][0] = wrong["source_url"]
            with self.assertRaisesRegex(installer.Refusal, "exact audited repository path"):
                installer._validate_proposal(wrong, wrong["proposal_id"], wrong["profile"], {wrong["name"]}, bound)
            for invalid in ("/absolute", ".", "./optional-skills", "optional-skills/./creative", "../escape", "a/../escape", "a//b", ""):
                changed = json.loads(json.dumps(valid)); changed[1]["path"] = invalid; path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaises(installer.Refusal, msg=invalid): installer._source_catalog(path)

            schema = json.loads((ROOT / "skills/proposal.schema.json").read_text(encoding="utf-8"))
            schema_path = re.compile(schema["properties"]["skill_path"]["pattern"])
            for invalid in ("", ".", "./optional-skills", "optional-skills/./creative", "..", "optional-skills/../creative", "optional-skills//creative"):
                self.assertIsNone(schema_path.fullmatch(invalid), invalid)
                malicious = json.loads(json.dumps(proposal)); malicious["skill_path"] = invalid
                with self.assertRaisesRegex(installer.Refusal, "repository/path/revision"):
                    installer._validate_proposal(malicious, malicious["proposal_id"], malicious["profile"], {malicious["name"]}, bound)

    def test_installer_compile_time_pin_and_topology_match_canonical_manifest(self):
        installer = load_module("skill_installer_contract", ROOT / "scripts/install-skills.py")
        manifest = json.loads((ROOT / "skills/packs.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["nixkit"]["repository"], installer.NIXKIT_REPOSITORY)
        self.assertEqual(manifest["nixkit"]["commit"], installer.NIXKIT_COMMIT)
        self.assertEqual(manifest["nixkit"]["sources_sha256"], installer.NIXKIT_SOURCES_SHA256)
        self.assertEqual("9748b8338c88c766208fa54fa144c95f0cd282a72f95327f485641ce85c18041", installer.NIXKIT_INSTALLER_SHA256)
        self.assertEqual({"skills/watch": "64685da3912a54d5f672c4bdce0e89b69b4cd6c8"}, installer.NIXKIT_LOCAL_TREES)
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
        packs["approved_additions"] = {profile: [] for profile in PROFILES}
        source_skills = sorted({
            skill
            for values in packs["packs"].values()
            for skill in values
        } | set(packs["task_only"]) | set(packs["excluded"]))
        source_skills.remove("agent-browser")
        source_skills.remove("watch")
        snapshot_skills = ["lnx-grilling", "lnx-grill-me", "lnx-domain-modeling", "lnx-grill-with-docs", "lnx-to-spec", "lnx-writing-for-agents", "nix-idea-to-mvp"]
        source_skills = [skill for skill in source_skills if skill not in snapshot_skills]
        sources = [
            {"repo": "example/source", "ref": "b" * 40, "skills": source_skills},
            {"repo": "its-nix/kit", "ref": "da5f36fc4c470fa28ffdcab1a6c6aaa3750bded3", "skills": snapshot_skills},
            {"repo": "vercel-labs/agent-browser", "ref": "dac13bb87468fe9d74a040d862720f6cc17a9565", "skills": ["agent-browser"]},
            {"local": "skills", "skills": ["watch"]},
        ]
        (kit / "sources.json").write_text(json.dumps(sources), encoding="utf-8")
        (kit / "install.mjs").write_text("// fixture: execution is intercepted by fake npx\n", encoding="utf-8")
        (kit / ".gitignore").write_text("/skills/watch/ignored.payload\n", encoding="utf-8")
        (kit / "skills/watch").mkdir(parents=True)
        (kit / "skills/watch/SKILL.md").write_text("---\nname: watch\n---\n", encoding="utf-8")
        helper = kit / "skills/watch/helper.py"
        helper.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        helper.chmod(0o755)
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
        watch_tree = subprocess.check_output(["git", "rev-parse", f"{commit}:skills/watch"], cwd=kit, text=True).strip()
        packs["nixkit"]["commit"] = commit
        import hashlib
        packs["nixkit"]["sources_sha256"] = hashlib.sha256((kit / "sources.json").read_bytes()).hexdigest()
        fixture_root = base / "repo"
        (fixture_root / "scripts").mkdir(parents=True)
        (fixture_root / "skills").mkdir()
        script = fixture_root / "scripts/install-skills.py"
        source = self.script.read_text(encoding="utf-8")
        source = source.replace("f5377ca3219daf4f33f6e8525f9438318dabcd2f", commit)
        source = source.replace("110ecc3872b4fe45ede667afd4ca757d59aef850672045a639eae5ef78415a83", packs["nixkit"]["sources_sha256"])
        source = source.replace("92338765a1cc942b2a20dda3f1e220d6be0225e1", commit)
        source = source.replace("6493103af689bdf4bae5455e1d901646fe079e51a69c53b6f5bcf57c62786d21", packs["nixkit"]["sources_sha256"])
        fixture_installer_sha = hashlib.sha256((kit / "install.mjs").read_bytes()).hexdigest()
        source = source.replace("9748b8338c88c766208fa54fa144c95f0cd282a72f95327f485641ce85c18041", fixture_installer_sha)
        source = source.replace("64685da3912a54d5f672c4bdce0e89b69b4cd6c8", watch_tree)
        script.write_text(source, encoding="utf-8")
        manifest = fixture_root / "skills/packs.json"
        proposal_manifest = json.loads(json.dumps(packs))
        proposal_manifest["proposed_pack_additions"]["lnx"] = ["product-development"]
        proposal_manifest["approved_pack_additions"]["lnx"] = []
        manifest.write_text(json.dumps(proposal_manifest), encoding="utf-8")
        proposal = json.loads((ROOT / "skills/pack-proposals/lnx-product-development-92338765.json").read_text(encoding="utf-8"))
        proposal["nixkit"]["commit"] = commit
        proposal["nixkit"]["sources_sha256"] = packs["nixkit"]["sources_sha256"]
        proposal_path = fixture_root / "skills/pack-proposals/lnx-product-development-92338765.json"
        proposal_path.parent.mkdir(parents=True)
        proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=fixture_root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=fixture_root, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=fixture_root, check=True)
        subprocess.run(["git", "add", "."], cwd=fixture_root, check=True)
        subprocess.run(["git", "commit", "-qm", "canonical proposal fixture"], cwd=fixture_root, check=True)
        proposal_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=fixture_root, text=True).strip()
        proposal_hash = hashlib.sha256(subprocess.check_output(["git", "show", f"{proposal_commit}:skills/pack-proposals/lnx-product-development-92338765.json"], cwd=fixture_root)).hexdigest()
        proposal_manifest_hash = hashlib.sha256(subprocess.check_output(["git", "show", f"{proposal_commit}:skills/packs.json"], cwd=fixture_root)).hexdigest()
        source = source.replace("083d008d3a83cd178e1f79bf962967ae7054fc0e", proposal_commit)
        source = source.replace("06db117e1d84486a50f7beaae32f83fc3540ca8fd01eb5dc7fcf0f9e62100288", proposal_hash)
        source = source.replace("7a8a7f67f2498f147f03833501b9c1c39e35bd1cee624e3e833061d77a62cf3f", proposal_manifest_hash)
        script.write_text(source, encoding="utf-8")
        manifest.write_text(json.dumps(packs), encoding="utf-8")
        receipt = json.loads((ROOT / "skills/pack-approvals/lnx-product-development-92338765.json").read_text(encoding="utf-8"))
        receipt["proposal_git_commit"] = proposal_commit
        receipt["proposal_file_sha256"] = proposal_hash
        receipt["nixkit"]["commit"] = commit
        receipt["nixkit"]["sources_sha256"] = packs["nixkit"]["sources_sha256"]
        receipt["approval_evidence"]["quote"] = f"approve lnx-product-development-92338765 at {proposal_commit}"
        receipt_path = fixture_root / "skills/pack-approvals/lnx-product-development-92338765.json"
        receipt_path.parent.mkdir(parents=True)
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=fixture_root, check=True)
        subprocess.run(["git", "commit", "-qm", "activate canonical fixture"], cwd=fixture_root, check=True)
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
            self.assertIn(json.dumps(str(base / "bin/npx")) + ' "--yes" "node@24.22.1"', preview.stdout)
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

    def test_hidden_installer_mutations_are_rejected_before_npx_or_profile_writes(self):
        for flag in ("--assume-unchanged", "--skip-worktree"):
            with self.subTest(flag=flag), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                home, hermes_home, kit, manifest, script, fixture_root, env = self._fixture(base)
                subprocess.run(["git", "update-index", flag, "install.mjs"], cwd=kit, check=True)
                (kit / "install.mjs").write_text("throw new Error('unreviewed payload');\n", encoding="utf-8")
                self.assertEqual("", subprocess.check_output(
                    ["git", "status", "--porcelain", "--untracked-files=all"], cwd=kit, text=True
                ))
                command = ["python3", str(script), "--nixkit", str(kit), "--profile", "pulse"]
                for mode in ([], ["--apply"]):
                    result = subprocess.run(command + mode, cwd=fixture_root, env=env, text=True, capture_output=True)
                    self.assertEqual(2, result.returncode, result.stdout + result.stderr)
                    self.assertIn("install.mjs bytes do not match", result.stderr)
                self.assertFalse((base / "calls.json").exists(), "npx must not run for hidden installer mutations")
                self.assertFalse(hermes_home.exists(), "refused installer must not create profile state")

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

    def test_rejects_ignored_file_inside_pinned_local_tree_without_invoking_nixkit(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home, hermes_home, kit, manifest, script, fixture_root, env = self._fixture(base)
            ignored = kit / "skills/watch/ignored.payload"
            ignored.write_text("not in reviewed Git tree", encoding="utf-8")
            self.assertEqual("", subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=all"], cwd=kit, text=True
            ))
            command = ["python3", str(script), "--nixkit", str(kit), "--profile", "pulse"]
            result = subprocess.run(command, cwd=fixture_root, env=env, text=True, capture_output=True)
            self.assertEqual(2, result.returncode)
            self.assertIn("file set differs from Git tree", result.stderr)
            self.assertFalse((base / "calls.json").exists(), "NixKit must not run after exact-tree refusal")
            self.assertFalse(hermes_home.exists(), "refused payload must not be copied into a profile")

    def test_pack_cannot_be_folded_into_baseline(self):
        installer = load_module("skill_installer_pack_baseline", self.script)
        manifest = json.loads((ROOT / "skills/packs.json").read_text(encoding="utf-8"))
        manifest["profiles"]["lnx"].append("product-development")
        with self.assertRaises(installer.Refusal):
            installer._canonical_manifest(manifest)

    def test_pending_pack_rejects_orphan_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home, hermes_home, kit, manifest_path, script, fixture_root, env = self._fixture(base)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["proposed_pack_additions"]["lnx"] = ["product-development"]
            manifest["approved_pack_additions"]["lnx"] = []
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            receipt = fixture_root / "skills/pack-approvals/lnx-product-development-92338765.json"
            receipt.write_text("{}", encoding="utf-8")
            result = subprocess.run(
                ["python3", str(script), "--nixkit", str(kit), "--profile", "pulse"],
                cwd=fixture_root, env=env, text=True, capture_output=True,
            )
            self.assertEqual(2, result.returncode)
            self.assertIn("pack-approvals", result.stderr)

    def test_only_exact_committed_pack_approval_enables_product_development(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home, hermes_home, kit, manifest_path, script, fixture_root, env = self._fixture(base)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            receipt_path = fixture_root / "skills/pack-approvals/lnx-product-development-92338765.json"
            command = ["python3", str(script), "--nixkit", str(kit), "--profile", "lnx"]
            valid = subprocess.run(command, cwd=fixture_root, env=env, text=True, capture_output=True)
            self.assertEqual(0, valid.returncode, valid.stderr)
            for skill in manifest["packs"]["product-development"]:
                self.assertIn(f'"{skill}"', valid.stdout)

            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            correct_hash = receipt["proposal_file_sha256"]
            receipt["proposal_file_sha256"] = "0" * 64
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=fixture_root, check=True)
            subprocess.run(["git", "commit", "-qm", "forged proposal hash"], cwd=fixture_root, check=True)
            forged_hash = subprocess.run(command, cwd=fixture_root, env=env, text=True, capture_output=True)
            self.assertEqual(2, forged_hash.returncode)
            self.assertIn("canonical proposal commit and file hash", forged_hash.stderr)

            receipt["proposal_file_sha256"] = correct_hash
            receipt["approval_evidence"]["message_id"] = "1563556252829622397"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=fixture_root, check=True)
            subprocess.run(["git", "commit", "-qm", "alter approval message id"], cwd=fixture_root, check=True)
            forged_message = subprocess.run(command, cwd=fixture_root, env=env, text=True, capture_output=True)
            self.assertEqual(2, forged_message.returncode)
            self.assertIn("exact verified Discord message ID, timestamp", forged_message.stderr)

            receipt["approval_evidence"]["message_id"] = "1563556252829622396"
            receipt["approval_evidence"]["timestamp"] = "2026-10-24T14:14:20.145001+00:00"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=fixture_root, check=True)
            subprocess.run(["git", "commit", "-qm", "alter approval timestamp"], cwd=fixture_root, check=True)
            forged_timestamp = subprocess.run(command, cwd=fixture_root, env=env, text=True, capture_output=True)
            self.assertEqual(2, forged_timestamp.returncode)
            self.assertIn("exact verified Discord message ID, timestamp", forged_timestamp.stderr)

            receipt["approval_evidence"]["timestamp"] = "2026-10-24T14:14:20.145000+00:00"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=fixture_root, check=True)
            subprocess.run(["git", "commit", "-qm", "restore exact approval"], cwd=fixture_root, check=True)
            restored = subprocess.run(command, cwd=fixture_root, env=env, text=True, capture_output=True)
            self.assertEqual(0, restored.returncode, restored.stderr)

    def test_pack_approval_rejects_wrong_discord_author(self):
        installer = load_module("skill_installer_wrong_approval_author", self.script)
        proposal_id = "lnx-product-development-92338765"
        commit = "a" * 40
        evidence = {"kind": "approval", "platform": "discord", "author_id": "454290355320520715", "channel_id": "1563181903253737542", "message_id": "1563999999999999999", "quote": f"approve {proposal_id} at {commit}", "timestamp": "2026-10-24T16:00:00Z"}
        with self.assertRaisesRegex(installer.Refusal, "verified Discord user"):
            installer._validate_pack_approval_evidence(evidence, proposal_id, commit)

    def test_pack_approval_rejects_explicit_non_approval_quote(self):
        installer = load_module("skill_installer_non_approval_quote", self.script)
        proposal_id = "lnx-product-development-92338765"
        commit = "a" * 40
        evidence = {"kind": "approval", "platform": "discord", "author_id": "454290355320520714", "channel_id": "1563181903253737542", "message_id": "1563999999999999999", "quote": f"do not approve {proposal_id} at {commit}", "timestamp": "2026-10-24T16:00:00Z"}
        with self.assertRaisesRegex(installer.Refusal, "must exactly equal"):
            installer._validate_pack_approval_evidence(evidence, proposal_id, commit)

    def test_recursive_duplicate_frontmatter_refuses_before_nixkit_or_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home, hermes_home, kit, manifest, script, fixture_root, env = self._fixture(base)
            legacy = hermes_home / "profiles/pulse/skills/product-development/verification-before-completion"
            legacy.mkdir(parents=True)
            (legacy / "SKILL.md").write_text("---\nname: verification-before-completion\n---\nlegacy\n", encoding="utf-8")
            canonical = hermes_home / "profiles/pulse/skills/verification-before-completion/SKILL.md"
            result = subprocess.run(["python3", str(script), "--nixkit", str(kit), "--profile", "pulse", "--apply"], cwd=fixture_root, env=env, text=True, capture_output=True)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("outside its sole canonical destination", result.stderr)
            self.assertFalse((base / "calls.json").exists())
            self.assertFalse(canonical.exists())
            categorized = hermes_home / "skills/product-development/lnx-grilling"
            categorized.mkdir(parents=True)
            (categorized / "SKILL.md").write_text("---\nname: lnx-grilling\n---\nlegacy\n", encoding="utf-8")
            installer = load_module("skill_installer_recursive_duplicate", script)
            with self.assertRaisesRegex(installer.Refusal, "outside its sole canonical destination"):
                installer._preflight_duplicate_names(hermes_home, {"lnx-grilling"})

    def test_recursive_preflight_rejects_legacy_skill_directory_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); profile_home = root / "profile"; skills = profile_home / "skills"
            target = root / "legacy-target"; target.mkdir(parents=True); skills.mkdir(parents=True)
            (target / "SKILL.md").write_text("---\nname: lnx-grilling\n---\nlegacy\n", encoding="utf-8")
            (skills / "legacy-category").symlink_to(target, target_is_directory=True)
            installer = load_module("skill_installer_directory_symlink", self.script)
            with self.assertRaisesRegex(installer.Refusal, "must not contain symlinks"):
                installer._preflight_duplicate_names(profile_home, {"lnx-grilling"})

    def test_recursive_preflight_rejects_legacy_skill_manifest_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); profile_home = root / "profile"; legacy = profile_home / "skills/legacy/lnx-grilling"
            target = root / "legacy-SKILL.md"; target.write_text("---\nname: lnx-grilling\n---\nlegacy\n", encoding="utf-8")
            legacy.mkdir(parents=True); (legacy / "SKILL.md").symlink_to(target)
            installer = load_module("skill_installer_manifest_symlink", self.script)
            with self.assertRaisesRegex(installer.Refusal, "must not contain symlinks"):
                installer._preflight_duplicate_names(profile_home, {"lnx-grilling"})

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

    def test_main_requires_exact_disjoint_multi_receipt_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home, hermes_home, kit, manifest_path, script, fixture_root, env = self._fixture(base)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["approved_additions"]["lnx"] = ["caveman", "watch"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            kit_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=kit, text=True).strip()

            def proposal(proposal_id, profile, name, repository, revision, skill_path):
                source = f"https://github.com/{repository}/tree/{revision}/{skill_path}"
                return {
                    "schema_version": 1, "proposal_id": proposal_id, "profile": profile, "name": name,
                    "summary": f"Audited {name} skill", "rationale": "Fills a reviewed role gap",
                    "source_url": source, "repository": repository, "skill_path": skill_path,
                    "revision": revision, "license": "MIT",
                    "evidence_urls": [source, f"https://github.com/{repository}/blob/{revision}/LICENSE"],
                    "risks": [],
                    "score_components": {"role_value": 27, "evidence_quality": 18, "security_provenance": 18, "hermes_compatibility": 14, "maintenance": 9, "documentation_license": 4},
                    "score": 90, "gates": {gate: True for gate in ("relevance", "provenance", "reliability", "safety_privacy", "license", "hermes_compatibility", "non_duplication")},
                    "gate_evidence": {gate: "Reviewed evidence" for gate in ("relevance", "provenance", "reliability", "safety_privacy", "license", "hermes_compatibility", "non_duplication")},
                    "status": "candidate",
                }

            proposals = fixture_root / "skills/proposals"
            proposals.mkdir()
            records = {
                "lnx-caveman": proposal("lnx-caveman", "lnx", "caveman", "example/source", "b" * 40, "skills/caveman"),
                "lnx-watch": proposal("lnx-watch", "lnx", "watch", "its-nix/kit", kit_commit, "skills/watch"),
                "pulse-watch": proposal("pulse-watch", "pulse", "watch", "its-nix/kit", kit_commit, "skills/watch"),
                "lnx-cross-skill": proposal("lnx-cross-skill", "lnx", "caveman", "example/source", "b" * 40, "skills/caveman"),
            }
            for proposal_id, record in records.items():
                (proposals / f"{proposal_id}.json").write_text(json.dumps(record), encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=fixture_root, check=True)
            subprocess.run(["git", "commit", "-qm", "propose two skills"], cwd=fixture_root, check=True)
            manifest_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=fixture_root, text=True).strip()

            approvals = fixture_root / "skills/approvals"
            approvals.mkdir()
            def receipt(proposal_id, profile, skills):
                return {"schema_version": 1, "proposal_id": proposal_id, "profile": profile, "skills": skills, "approved_by": "Lior", "approved_at": "2026-10-24T15:00:00Z", "manifest_commit": manifest_commit}
            receipt_records = {
                "lnx-caveman": receipt("lnx-caveman", "lnx", ["caveman"]),
                "lnx-watch": receipt("lnx-watch", "lnx", ["watch"]),
                "pulse-watch": receipt("pulse-watch", "pulse", ["watch"]),
                "lnx-cross-skill": receipt("lnx-cross-skill", "lnx", ["watch"]),
            }
            for proposal_id, record in receipt_records.items():
                (approvals / f"{proposal_id}.json").write_text(json.dumps(record), encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=fixture_root, check=True)
            subprocess.run(["git", "commit", "-qm", "record separate approvals"], cwd=fixture_root, check=True)

            base_command = ["python3", str(script), "--nixkit", str(kit), "--profile", "lnx", "--skill", "caveman", "--skill", "watch"]
            caveman = str(approvals / "lnx-caveman.json")
            watch = str(approvals / "lnx-watch.json")
            success = subprocess.run(base_command + ["--approval", caveman, "--approval", watch], cwd=fixture_root, env=env, text=True, capture_output=True)
            self.assertEqual(0, success.returncode, success.stderr)
            self.assertIn("caveman", success.stdout)
            self.assertIn("watch", success.stdout)

            cases = {
                "missing": (["--approval", caveman], "exactly cover"),
                "duplicate-overlap": (["--approval", caveman, "--approval", caveman, "--approval", watch], "disjoint"),
                "cross-profile": (["--approval", caveman, "--approval", str(approvals / "pulse-watch.json")], "misbound"),
                "cross-skill": (["--approval", caveman, "--approval", str(approvals / "lnx-cross-skill.json")], "identity/status/skills"),
            }
            for label, (arguments, message) in cases.items():
                with self.subTest(label=label):
                    result = subprocess.run(base_command + arguments, cwd=fixture_root, env=env, text=True, capture_output=True)
                    self.assertEqual(2, result.returncode)
                    self.assertIn(message, result.stderr)

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
        catalog = {"agent-browser": (repository, revision, None)}
        installer._validate_proposal(proposal, "pulse-agent-browser", "pulse", {"agent-browser"}, catalog)
        with self.assertRaisesRegex(installer.Refusal, "uniquely belong"):
            installer._validate_proposal(proposal, "pulse-agent-browser", "pulse", {"agent-browser"}, {"agent-browser": ("evil/repo", revision, None)})
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
        catalog = {"useful": (repository, revision, None)}
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

    def test_collector_merges_role_specific_reports_for_same_skill(self):
        week = "2026-W43"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self._candidate()
            second = self._candidate()
            second["rationale"] = "A different profile-specific role gap"
            second["score_components"]["role_value"] = 28
            second["score"] = 91
            second["license"] = "MIT; verified at the pinned revision."
            second["risks"] = ["Profile-specific risk"]
            second["evidence_urls"].append(
                f"https://github.com/example/useful/blob/{'a' * 40}/skills/useful/SKILL.md"
            )
            self._write_week(root, week, {"lnx": [first], "pulse": [second]})
            result = self.collect.collect_packets(root, week)
            self.assertEqual("ok", result["status"], result)
            self.assertEqual(1, len(result["candidates"]))
            merged = result["candidates"][0]
            self.assertEqual(["lnx", "pulse"], merged["reported_by"])
            self.assertEqual(91, merged["score"])
            self.assertEqual(["Profile-specific risk"], merged["risks"])
            self.assertEqual(3, len(merged["evidence_urls"]))

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
        mixed_case_webhook = "HTTPS://PTB.DiscordApp.Com:443/api/webhooks/" + "2" * 18 + "/" + "X" * 60
        payloads = (
            "sk-" + "A" * 40, "ghp_" + "A" * 30, "github" + "_pat_" + "B" * 60,
            "AKIA" + "A" * 16, discord, webhook, mixed_case_webhook, "discord_webhook_token=" + "T" * 60, "xox" + "b-" + "1" * 12 + "-" + "C" * 30,
            "xox" + "p-" + "2" * 12 + "-" + "D" * 30, "-----BEGIN" + " PRIVATE KEY-----",
            "private/customers/payments/data.json", "bad\u0001control",
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

    def test_collector_allows_public_customer_research_skill_metadata(self):
        week = "2026-W43"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = self._candidate(name="customer-research", path="skills/customer-research")
            self._write_week(root, week, {"lnx": [candidate]})
            result = self.collect.collect_packets(root, week)
            self.assertEqual("ok", result["status"], result)
            self.assertEqual(["customer-research"], [item["name"] for item in result["candidates"]])

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

    def test_aggregate_prompt_requires_concise_semantic_deduplication(self):
        prompt = (ROOT / "automation/skill-scout/aggregate-prompt.md").read_text(encoding="utf-8")
        self.assertIn("exactly one best candidate per capability", prompt)
        self.assertIn("Do not print raw evidence URLs", prompt)
        self.assertIn("under 20 lines", prompt)
        self.assertIn("Union the relevant `reported_by` profiles", prompt)
        self.assertIn("Never install", prompt)

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

    def test_collector_publication_preserves_destination_created_after_preflight(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "source.py"; destination = root / "collector.py"
            source.write_text("safe", encoding="utf-8")
            real_link = os.link

            def race(source_path, destination_path, **kwargs):
                destination.write_text("concurrent", encoding="utf-8")
                return real_link(source_path, destination_path, **kwargs)

            with mock.patch.object(self.setup.os, "link", side_effect=race):
                with self.assertRaisesRegex(self.setup.Refusal, "preserved it.*manual recovery required"):
                    self.setup._install_collector_atomic(destination, source)
            self.assertEqual("concurrent", destination.read_text(encoding="utf-8"))
            self.assertFalse(destination.with_suffix(".tmp").exists())

    def test_collector_rollback_preserves_replacement_same_content_inode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "source.py"; destination = root / "collector.py"
            source.write_text("safe", encoding="utf-8")
            identity = self.setup._install_collector_atomic(destination, source)
            self.assertIsNotNone(identity)
            replacement = root / "replacement"
            replacement.write_bytes(source.read_bytes()); replacement.chmod(0o700)
            os.replace(replacement, destination)
            self.assertNotEqual(identity.inode, destination.stat().st_ino)
            failures = self.setup._rollback("/missing/hermes", root, [], [], [], destination, identity)
            self.assertTrue(destination.is_file())
            self.assertEqual(source.read_bytes(), destination.read_bytes())
            self.assertTrue(any("inode/device/type/content/mode changed" in failure for failure in failures), failures)

    def test_collector_post_publication_sync_failure_keeps_committed_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "source.py"; destination = root / "collector.py"
            source.write_text("safe", encoding="utf-8")
            real_fsync = self.setup.os.fsync
            calls = 0

            def fail_first_directory_sync(fd):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected directory fsync failure")
                return real_fsync(fd)

            with mock.patch.object(self.setup.os, "fsync", side_effect=fail_first_directory_sync):
                identity = self.setup._install_collector_atomic(destination, source)
            self.assertIsNotNone(identity)
            self.assertEqual("safe", destination.read_text(encoding="utf-8"))
            self.assertFalse(destination.with_suffix(".tmp").exists())

    def test_create_output_requires_exact_real_hermes_id_shape(self):
        output = "Created job: abcdef123456\n  Name: example\n  Schedule: 0 1 * * *"
        self.assertEqual("abcdef123456", self.setup._created_job_id(output))
        for invalid in ("abcdef123456", "Created job: ABCDEF123456", "Created job: abcdef12", "Created job: abcdef123456\nCreated job: fedcba654321"):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(self.setup.Refusal, "manual recovery required"):
                self.setup._created_job_id(invalid)

    def test_exact_job_requires_enabled_operational_state(self):
        desired = self.setup.EXPECTED_JOBS[0]
        actual = {
            "id": "fixture", "name": desired["name"], "schedule": {"kind": "cron", "value": desired["schedule"]},
            "prompt": self.setup._prompt(desired), "deliver": ["local"], "continuity": False, "script": None,
        }
        self.assertTrue(self.setup._is_exact(actual, desired))  # documented legacy missing-enabled shape
        for field, value in (("enabled", True), ("state", "scheduled"), ("status", "active")):
            changed = dict(actual); changed[field] = value
            self.assertTrue(self.setup._is_exact(changed, desired), (field, value))
        rejected = (
            ("enabled", False), ("enabled", None), ("enabled", 0), ("enabled", 1),
            ("state", "paused"), ("state", "disabled"), ("state", "running"),
            ("status", "paused"), ("status", "disabled"), ("status", "enabled"),
            ("paused_at", "2026-10-24T12:00:00Z"), ("paused", True), ("pause_marker", "manual"),
        )
        for field, value in rejected:
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
                    job={'id':f'{count:012x}', 'name':value('--name'), 'schedule':{'kind':'cron','value':cmd[2]}, 'prompt':cmd[3], 'deliver':[value('--deliver','local')], 'continuity':'--continuity' in cmd, 'script':value('--script')}
                    if count==2:
                        job['enabled']=False
                        jobs.append({'id':'cccccccccccc', **{key:value for key,value in job.items() if key!='id'}, 'enabled':True})
                    jobs.append(job); f.write_text(json.dumps(jobs)); print(f"Created job: {job['id']}"); print(f"  Name: {job['name']}"); raise SystemExit(0)
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
            self.assertIn(preexisting[0], all_jobs)
            concurrent = [job for job in all_jobs if job.get("id") == "cccccccccccc"]
            self.assertEqual(1, len(concurrent), all_jobs)
            self.assertEqual(self.setup.EXPECTED_JOBS[1]["name"], concurrent[0]["name"])
            self.assertFalse({"000000000001", "000000000002"} & {job.get("id") for job in all_jobs}, all_jobs)
            self.assertFalse((home / ".hermes/scripts/skill-scout-collect.py").exists())
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual({"000000000001", "000000000002"}, {call[-1] for call in calls if call[2:4] == ["cron", "remove"]})
            self.assertNotIn("cccccccccccc", {call[-1] for call in calls if call[2:4] == ["cron", "remove"]})

    def test_delivery_rollback_preserves_concurrent_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); state = root / "state"; state.mkdir()
            current = {"id": "abcdef123456", "name": "nix-skill-scout-aggregate", "deliver": ["telegram:concurrent"]}
            (state / "default.json").write_text(json.dumps([current]), encoding="utf-8")
            with mock.patch.dict(os.environ, {"HERMES_SCOUT_TEST_STORE": str(state), "NIX_OS_SCOUT_TEST_MODE": "1"}):
                failures = self.setup._rollback(
                    "/missing/hermes", root, [], [],
                    [("default", current["id"], current["name"], "local", "telegram:6926015052")],
                    root / "collector.py", None,
                )
            preserved = json.loads((state / "default.json").read_text(encoding="utf-8"))[0]
            self.assertEqual(["telegram:concurrent"], preserved["deliver"])
            self.assertTrue(any("preserved concurrent value; manual recovery required" in failure for failure in failures), failures)

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
                    j={'id':uuid.uuid4().hex[:12], 'name':value('--name'), 'schedule':{'kind':'cron','value':schedule}, 'schedule_display':schedule, 'prompt':prompt, 'deliver':[value('--deliver','local')], 'continuity':'--continuity' in cmd, 'script':value('--script')}
                    jobs.append(j); f.write_text(json.dumps(jobs)); print(f"Created job: {j['id']}"); print(f"  Name: {j['name']}")
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
