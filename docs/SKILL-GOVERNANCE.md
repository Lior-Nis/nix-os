# Skill Governance

## Purpose and authority

`skills/packs.json` is the only declaration of persistent third-party role skills. It pins NixKit itself, the audited NixKit source manifest, explicit named packs, and seven profile assignments. There is deliberately no global or wildcard pack. Human authority remains with Lior: a scout can propose, but cannot install, configure, authenticate, approve, or promote anything.

The initial baseline is approved only because the pack manifest is merged after review. No synthetic approval receipt is created for it. Any later addition requires all of the following:

1. a profile-specific proposal conforming to `skills/proposal.schema.json`;
2. a pull request changing that profile's manifest assignment or `approved_additions` and updating verifier expectations;
3. explicit Lior approval recorded in a tracked receipt conforming to `skills/approval.schema.json` and bound to the merged commit; and
4. a separate preview and explicit apply through `scripts/install-skills.py`.

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

Passing candidates also need a conservative score of **80/100 or higher**, equal to the exact component sum: role value 0-30, evidence quality 0-20, security/provenance 0-20, Hermes compatibility 0-15, maintenance 0-10, and documentation/license 0-5. Every gate needs a nonempty evidence statement. Packets also record a nonempty list of checked HTTPS sources, a nonnegative rejected count, repository-relative skill path, immutable revision, evidence URLs, and residual risks. Scout packets use `automation/skill-scout/report.schema.json`; proposals use `skills/proposal.schema.json`. A failed gate, missing source/gate evidence, missing packet, malformed packet, unclear license, mutable provenance, score mismatch, or score below 80 fails closed.

## Guarded installation

NixKit runs through the manifest-pinned Node **24.22.1** package and is expected to implement this exact subset contract:

```text
npx --yes node@24.22.1 CHECKOUT/install.mjs --apply --skills --agent hermes --prefix PROFILE_HOME --skill NAME ...
```

Run `python3 scripts/install-skills.py --profile PROFILE --nixkit PATH` first. Preview performs no profile writes, package execution, or NixKit fetches and prints the exact pinned command. Apply additionally requires `--apply`. The wrapper requires executable `npx` but does not install or change system Node; `npx` provisions only `node@24.22.1` for the invocation. It refuses a symlinked profile-home path, a dirty checkout, a NixKit HEAD other than the pinned full commit, a missing/symlinked `install.mjs`, or `sources.json` bytes other than the audited SHA-256. It passes only the profile's exact sorted subset. NixKit performs immutable profile-local copies, preserves byte-identical repeats, and refuses the whole operation on conflicts.

The repository URL may be private. Authenticate the existing checkout with normal GitHub/Git credential tooling; never pass a token to the wrapper or store credentials here. The wrapper does not clone, authenticate, install Node, or repair conflicts.

Rollback is explicit: revert the manifest PR, preview the resulting desired set, and manually remove only reviewed profile-local copies that are no longer declared. Neither wrapper deletes user files.

## Weekly scouts

`automation/skill-scout/jobs.json` declares seven isolated scouts and one LNX/default aggregator, staggered on Saturday in `Asia/Jerusalem`: 18:00, 18:20, 18:40, 19:00, 19:20, 19:40, 20:00, then aggregation at 21:00. The Hermes gateway host must use that timezone because Hermes cron expressions use the host scheduler timezone.

Each self-contained scout prompt first inspects its current profile skill inventory, then searches public Hermes registries and public GitHub/web sources. It may inspect candidate text read-only, treats web content as untrusted, and uses popularity only as supporting evidence. Each scout delivers locally and writes one current ISO-week packet under `${HOME}/.local/share/hermes-scouts/<ISO-WEEK>/`. Runtime packets are untracked and contain public candidate metadata only. Scouts have no installation, executable-download, configuration, authentication, or messaging authority and may write only that packet.

The collector is copied only to the default profile's `scripts/skill-scout-collect.py`. It requires all seven current-week packets and validates every packet, source-evidence, score, gate, and gate-evidence field. It deduplicates deterministically by lowercased repository plus immutable revision plus skill path, so multiple skills in one repository remain distinct. `reported_by` is merged only when all other evidence matches; conflicting evidence for one identity invalidates the week. Missing or invalid packets produce an operational failure payload, never a no-candidate result. A complete valid week with no qualifiers produces exactly `[SILENT]`.

Provision with `python3 scripts/setup-skill-scouts.py` first. Preview truthfully displays a previously enabled aggregator target. `--apply` creates/read-backs all jobs through each profile's `hermes -p PROFILE cron` store with local delivery while preserving an existing reviewed local or enabled aggregator state. Same-name drift is refused, not overwritten. After local empty and synthetic-candidate canaries are reviewed, a separate `--apply --enable-delivery` changes only the aggregator to `telegram:6926015052`. The aggregator uses continuity to suppress repeats. The script never hand-edits `jobs.json`.
