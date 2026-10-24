# Skill Governance

## Purpose and authority

`skills/packs.json` is the only declaration of persistent third-party role skills. It pins NixKit itself, the audited NixKit source manifest, explicit named packs, and seven profile assignments. There is deliberately no global or wildcard pack. Human authority remains with Lior: a scout can propose, but cannot install, configure, authenticate, approve, or promote anything.

The initial baseline is approved only because the pack manifest is merged after review. No synthetic approval receipt is created for it. Any later addition uses a deliberately satisfiable two-commit flow and requires all of the following:

1. Commit a profile-specific proposal at `skills/proposals/<proposal_id>.json`, conforming to `skills/proposal.schema.json`, together with the exact `approved_additions` change in canonical `skills/packs.json`. This is the **proposal/manifest commit**.
2. Obtain explicit Lior approval of that committed state. The approval cannot be self-issued by automation.
3. In a later commit, add the receipt at `skills/approvals/<proposal_id>.json`. Its `manifest_commit` is the full SHA of the earlier proposal/manifest commit, and its proposal ID, profile, and exact skill set bind the decision.
4. Preview, then explicitly apply through `scripts/install-skills.py` with matching `--skill` values and the canonical receipt path.

The installer requires the receipt, proposal, manifest, and installer to be tracked, committed, and unmodified; requires `manifest_commit` to be an ancestor of current `HEAD`; and reads both the proposal and manifest with `git show` from that exact commit. It parses the audited pinned NixKit `sources.json`, requires globally unique skill names, and binds each approved name to the proposal's exact source repository and full pinned ref. It also requires the proposal's canonical GitHub tree URL and same-origin, same-repository/ref `LICENSE`, `COPYING`, or `NOTICE` evidence (blob or tree). It revalidates status, all gates, score, current profile assignment, and exact additions. Thus a receipt committed after the state it approves is valid, while a receipt for a stale, dirty, rewritten, lookalike-host, or unrelated state is not.

Popularity, stars, downloads, or social references are evidence only. They never override a failed gate or the score threshold.

## Classification and role packs

Every one of the 41 skills in the pinned NixKit source manifest belongs semantically to exactly one of these classes:

- **Persistent:** appears in one or more named role packs. Reuse between packs is intentional and does not duplicate the source classification.
- **Task-only:** may be considered for a bounded, approved task but is not continuously loaded.
- **Excluded:** conflicts with Hermes-native workflows, duplicates stronger controls, or is intentionally outside the operating model.

The baseline is `verification-before-completion`. LNX adds orchestration and handoff. Project leads add ideation, domain/spec/ticket/codebase design, review reception, handoff, and public research. Engineering adds execution/worktree/branch completion, review reception, and codebase design. UX persistently receives only `frontend-design`; Growth receives public research.

Two otherwise useful skills remain task-only because their pinned skill text delegates to mutable dependencies at runtime: `web-design-guidelines` fetches latest rules, and `find-docs` invokes `npx ctx7@latest`. Persistent assignment would undermine the immutable-source policy. They can move into a role pack only after an immutable dependency policy is implemented and reviewed.

Setup/grilling, browser, media, knowledge, and Google Workspace skills are also task-only. Conflicting/redundant Superpowers bootstrap/planning/debug/TDD/request-review/subagent/diagnostic skills, Caveman, and Ponytail are excluded in favor of existing Hermes-native capabilities.

## Candidate gates and scoring

A candidate must pass every hard gate before score matters:

1. **Relevance** — a specific profile need, not generic novelty.
2. **Provenance** — public repository and immutable full revision are attributable.
3. **Reliability** — instructions and support files are inspectable and credible.
4. **Safety/privacy** — no unbounded secret, private-data, installation, or messaging behavior.
5. **License** — explicit terms permit the intended use.
6. **Hermes compatibility** — commands, tools, paths, and frontmatter work with Hermes or have a documented safe fallback.
7. **Non-duplication** — the capability is not already adequately supplied by Hermes or an assigned skill.

Passing candidates also need a conservative score of **80/100 or higher**, equal to the exact component sum: role value 0-30, evidence quality 0-20, security/provenance 0-20, Hermes compatibility 0-15, maintenance 0-10, and documentation/license 0-5. Every gate needs a nonempty evidence statement. Narrative and gate-evidence strings are limited to 4,096 characters; risks are a list of at most 50 bounded nonempty strings; and evidence has 2-100 HTTPS URLs of at most 2,048 characters. Packets also record a nonempty bounded list of checked HTTPS sources, a nonnegative rejected count, repository-relative skill path, immutable revision, and residual risks. Scout packets use `automation/skill-scout/report.schema.json`; proposals use `skills/proposal.schema.json`, and the installer revalidates the complete exact proposal contract rather than trusting schema conformance. A failed gate, missing source/gate evidence, missing packet, malformed packet, unclear license, mutable provenance, score mismatch, or score below 80 fails closed.

## Guarded installation

NixKit runs through the manifest-pinned Node **24.22.1** package and is expected to implement this exact subset contract:

```text
npx --yes node@24.22.1 CHECKOUT/install.mjs --apply --skills --agent hermes --prefix PROFILE_HOME --skill NAME ...
```

Run `python3 scripts/install-skills.py --profile PROFILE --nixkit PATH` first. There is no manifest override: only canonical `skills/packs.json` is accepted. Preview performs no profile writes, package execution, or NixKit fetches and prints the exact pinned command. Apply additionally requires `--apply` and a clean Nix OS repository, including no untracked files. The wrapper requires executable `npx` but does not install or change system Node; `npx` provisions only `node@24.22.1` for the invocation. It refuses a symlinked profile-home path, a dirty checkout, a NixKit HEAD other than the pinned full commit, a missing/symlinked `install.mjs`, or `sources.json` bytes other than the audited SHA-256. It passes only the profile's exact sorted subset. NixKit performs immutable profile-local copies, preserves byte-identical repeats, and refuses the whole operation on conflicts.

The repository URL may be private. Authenticate the existing checkout with normal GitHub/Git credential tooling; never pass a token to the wrapper or store credentials here. The wrapper does not clone, authenticate, install Node, or repair conflicts.

Rollback is explicit: revert the manifest PR, preview the resulting desired set, and manually remove only reviewed profile-local copies that are no longer declared. Neither wrapper deletes user files.

## Weekly scouts

`automation/skill-scout/jobs.json` declares seven isolated scouts and one LNX/default aggregator, staggered on Saturday in `Asia/Jerusalem`: 18:00, 18:20, 18:40, 19:00, 19:20, 19:40, 20:00, then aggregation at 21:00. The Hermes gateway host must use that timezone because Hermes cron expressions use the host scheduler timezone.

Each self-contained scout prompt first inspects its current profile skill inventory, then searches public Hermes registries and public GitHub/web sources. It may inspect candidate text read-only, treats web content as untrusted, and uses popularity only as supporting evidence. Each scout delivers locally and writes one current ISO-week packet under `${HOME}/.local/share/hermes-scouts/<ISO-WEEK>/`. Runtime packets are untracked and contain public candidate metadata only. Scouts have no installation, executable-download, configuration, authentication, or messaging authority and may write only that packet.

The collector is copied only to the default profile's `scripts/skill-scout-collect.py`. Installation claims a missing temporary path with `O_CREAT|O_EXCL|O_NOFOLLOW` where available, mode `0700`, then writes, fsyncs, verifies the owned regular-file inode, and publishes it with a no-clobber hard link. A destination that appears concurrently is preserved and causes refusal; any pre-existing temporary file/symlink is likewise refused and never removed. It accepts only the actual current ISO week (validated with the ISO calendar), and every strict timezone-aware RFC 3339 `generated_at` must fall in that week. Individual packets are limited to 128 KiB, and aggregate candidate count and rendered collector output are independently bounded. It requires all seven current-week packets and validates every packet, source-evidence, score, gate, and gate-evidence field. Candidate `source_url` must be the exact immutable GitHub tree URL for the declared repository, full revision, and skill path; evidence must include that source URL plus same-origin, same-repository/revision `LICENSE`/`COPYING`/`NOTICE` evidence. Mutable branches and unrelated or lookalike-host license pages fail closed. Before any candidate reaches aggregation, bounded packet/candidate/text and JSON nesting limits plus recursive screening reject NUL/control characters, private keys, OpenAI/GitHub (including fine-grained `github_pat_`)/AWS/Discord bot and webhook/npm/Stripe/Google credentials, `xoxb`/`xoxp` workspace tokens, bearer/query tokens, JWTs, and protected student/customer/payment/pricing path indicators. Parse `RecursionError`/`MemoryError` conditions become invalid operational results rather than crashes. Rejected content is never forwarded. It deduplicates deterministically by lowercased repository plus immutable revision plus skill path, so multiple skills in one repository remain distinct. `reported_by` is merged only when all other evidence matches; conflicting evidence for one identity invalidates the week. Missing or invalid packets produce an operational failure payload, never a no-candidate result. A complete valid week with no qualifiers produces exactly `[SILENT]`.

Provision with `python3 scripts/setup-skill-scouts.py` first. Preview is nonmutating, validates the exact hardcoded eight-job topology, and truthfully displays a previously enabled aggregator target. Unknown fields, profiles, kinds, schedules, delivery drift, traversal-like prompt names, explicitly disabled jobs, and paused/disabled operational states fail before mutation. Legacy persisted jobs without an operational field and current jobs marked enabled/active/scheduled remain compatible. `--apply` additionally requires the entire Nix OS repository clean (including untracked files) and the jobs manifest, both prompts, collector, and setup script tracked, committed, and unmodified. It creates/read-backs all jobs through each profile's canonical `hermes -p PROFILE cron` store with local delivery while preserving an existing reviewed local or enabled aggregator state. `HERMES_SCOUT_TEST_STORE` is refused in production and is available only with `NIX_OS_SCOUT_TEST_MODE=1`; even then fake CLI-created state must pass the same exact readback. Same-name drift is refused, not overwritten. If a later create, edit, or readback fails, reconciliation removes only job IDs newly created by that invocation through `hermes cron remove`, verifies their absence, restores any pre-existing aggregator delivery target it changed, and removes the collector only when that invocation installed it and its identity/content still match. Pre-existing state is never removed, and rollback failures are reported alongside the original refusal. After local empty and synthetic-candidate canaries are reviewed, a separate `--apply --enable-delivery` changes only the LNX/default aggregator to exactly `telegram:6926015052`; only that job has the exact collector script and continuity. The aggregator uses continuity to suppress repeats. The script never hand-edits `jobs.json`.
