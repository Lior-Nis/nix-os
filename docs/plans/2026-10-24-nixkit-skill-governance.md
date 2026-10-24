# NixKit Role Skills and Weekly Scouting Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Equip Nix OS with conservative per-profile NixKit skill packs and an approval-gated weekly skill-discovery loop that sends Lior at most one qualifying digest.

**Architecture:** NixKit remains the pinned upstream content fetcher and gains a Hermes copy target plus exact subset selection. Nix OS owns the role pack manifest, approval receipts, safe installation wrapper, seven isolated profile scouts, and one LNX aggregator. Runtime scout packets and Hermes cron state remain outside Git.

**Tech Stack:** Bash, Node.js 24, Python 3.11 stdlib, Hermes CLI/cron, GitHub Actions.

---

### Task 1: Add subset-aware Hermes installation to NixKit

**Objective:** Support `--agent hermes`, repeated `--skill`, profile-home prefixes, immutable copied installations, and provenance validation without weakening preview/conflict behavior.

**Files:**
- Modify: `/tmp/its-nix-kit-review/install.mjs`
- Modify: `/tmp/its-nix-kit-review/tests/install.test.mjs`
- Modify: `/tmp/its-nix-kit-review/README.md`
- Modify: `/tmp/its-nix-kit-review/.gitignore`

**Steps:**
1. Add failing tests for Hermes subset preview, copy installation, idempotence, collision refusal, unknown skill rejection, and lock/hash mismatch.
2. Run `npx -y node@24.22.1 --test tests/install.test.mjs` and confirm failure.
3. Implement the smallest complete installer changes. Preview must not fetch or write; apply preflights every destination before any copy; existing identical copied directories are preserved; any difference refuses the whole operation.
4. Run the Node 24 tests and `bash -n install.sh`.
5. Commit the NixKit change.

### Task 2: Declare Nix OS skill packs and governance

**Objective:** Add an exact NixKit commit pin, seven explicit profile assignments, task-only/excluded classifications, scoring gates, and approval/proposal schemas.

**Files:**
- Create: `skills/packs.json`
- Create: `skills/proposal.schema.json`
- Create: `skills/approval.schema.json`
- Create: `docs/SKILL-GOVERNANCE.md`
- Modify: `nix-os.yaml`
- Modify: `scripts/verify.py`
- Modify: `tests/test_repository.py`

**Steps:**
1. Add failing manifest/verifier tests for all seven profiles, exact immutable commit pin, nonempty explicit packs, no wildcard/global pack, complete 41-skill classification, and gate/threshold policy.
2. Add the conservative audited pack matrix; reuse Hermes-native workflows where NixKit names conflict.
3. Enforce schema and cross-reference checks in the stdlib verifier.
4. Run focused and full unit tests.

### Task 3: Add approval-bound, preview-first installation

**Objective:** Install only the exact approved skill set into one exact Hermes profile through the pinned NixKit revision.

**Files:**
- Create: `scripts/skills.py`
- Create: `tests/test_skills.py`
- Modify: `.gitignore`
- Modify: `README.md`
- Modify: `docs/STATE-AND-SECRETS.md`

**Steps:**
1. Add failing tests for preview purity, profile/revision/skill binding, malformed approval rejection, profile-home symlink rejection, conflicting skill preservation, and idempotence.
2. Implement `plan`, `install`, and validation operations using exact profile homes and NixKit commit/source pins.
3. Require `--apply` and a tracked approval receipt for installation beyond the explicitly approved initial baseline.
4. Test with fake NixKit/Hermes homes and then an isolated real NixKit checkout under Node 24.

### Task 4: Add weekly scout and aggregation automation

**Objective:** Provision seven local-only role scouts and one LNX aggregator with shared schema-valid runtime packets and native `[SILENT]` suppression.

**Files:**
- Create: `automation/skill-scout/jobs.json`
- Create: `automation/skill-scout/scout-prompt.md`
- Create: `automation/skill-scout/aggregate-prompt.md`
- Create: `automation/skill-scout/collect.py`
- Create: `scripts/setup-skill-scouts.py`
- Modify: `tests/test_skills.py`
- Modify: `docs/SKILL-GOVERNANCE.md`

**Steps:**
1. Add failing tests for seven exact profiles, staggered Saturday schedules, local scout delivery, sole LNX delivery, hard gates, score >=80, no-install language, missing-report failure, deterministic deduplication, and empty `[SILENT]` path.
2. Implement preview-first reconciliation; refuse same-name drift instead of overwriting unknown jobs.
3. Install the collector only under the default profile scripts directory and keep weekly packets under `${HOME}/.local/share/hermes-scouts/`.
4. Verify temporary Hermes homes before touching live cron state.

### Task 5: Integrate documentation and CI

**Objective:** Make all new policy and scripts part of the canonical repository verification contract.

**Files:**
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/STATE-AND-SECRETS.md`
- Modify: `CONTRIBUTING.md`
- Modify: `.github/workflows/ci.yml`

**Steps:**
1. Document baseline, role, task-only, candidate, approval, promotion, rollback, private-repository authentication, and Node 24 behavior.
2. Add syntax/preview gates for the new scripts.
3. Run unit tests, verifier, Python/Bash syntax, previews, and `git diff --check`.

### Task 6: Review, publish, and canary live setup

**Objective:** Obtain independent spec/security approval, open verified PRs, and create live jobs only after local canaries pass.

**Steps:**
1. Run independent specification review, then independent quality/security review; fix and re-review every important finding.
2. Push the NixKit branch and open a PR; read back exact head/files/checks.
3. Pin that exact NixKit head in Nix OS, push the Nix OS branch, open a PR, and read back exact state.
4. Apply the explicitly approved initial baseline packs to the seven live profiles and verify installed bytes per profile.
5. Create all eight jobs initially with local delivery, manually canary empty and one synthetic qualifying packet, then set only the aggregator to the explicit Telegram origin target.
6. Verify live job definitions, scheduler status, profile skill inventories, and no unintended cross-profile installations.
7. Do not merge either PR without separate consequential merge approval.
