# Nix Business OS V0 implementation plan

Status: Slice 0 remediation is implemented and locally verified; live activation and acceptance still await the external prerequisites listed below. Updated 2026-09-24.

## How to use this plan

Implement slices in order. A later slice may start only when its dependencies and the previous slice's exit criteria are satisfied. Revalidate all affected upstream releases against `docs/UPSTREAM.md` before editing integration configuration.

Each slice is vertical: it ends in a behavior Lior can observe and a failure Lior can diagnose. A tool being installed is not, by itself, a completed slice.

## Material discoveries and prerequisites

### Repository facts

The supplied directory was completely empty and was not a Git worktree on 2026-09-22. There was no PRD, `AGENTS.md`, architecture, code, or prior state to preserve. The documentation baseline and Slice 0 implementation now exist on the `slice-0-foundation` branch; Slice 0 still needs its canonical private GitHub remote.

### Decisions already made

- Use Paperclip's `hermes_gateway`, not `hermes_local`, for persistent Telegram employees. Two Hermes writers on one profile are unsupported.
- Use the official Paperclip MCP server for Hermes-originated Paperclip work. Do not write a bridge service.
- Use Paperclip's built-in `opencode_local` adapter for the Engineer.
- Delay n8n until an actual deterministic workflow exists (Todoist projection).
- Treat Paperclip export as a portability aid, not a full database backup.
- Keep Paperclip's experimental Telegram/chat connector and Hermes-native kanban disabled.

### Human-provided prerequisites

These are not needed to author Slice 0 code, but are needed for the indicated manual verification:

| Input | Needed by | Notes |
|---|---|---|
| canonical private GitHub repo URL for `nix-os` | Slice 0 | repository currently has no remote |
| Hostinger VPS SSH access and supported Linux host | Slice 0 deploy | Docker Engine/Compose must be installable |
| DNS name for Paperclip | Slice 0 deploy | point to VPS before Caddy TLS verification |
| age recipient/identity custody and encrypted off-host destination credentials | Slice 0 exit | identity must survive VPS loss; object storage or another host; never Git |
| model/provider credential and chosen model | Slice 1 | keep provider portable; no model is locked by architecture |
| Telegram bot token, Lior's numeric Telegram user ID, private group/topic identifiers | Slice 1 | exact multi-topic UX is proven later in Slice 3 |
| separate private GitHub repo for `nix-brain` | Slice 4 | create manually or with an approved GitHub operation |
| Todoist project/token or OAuth app details | Slice 7 | not required earlier |

If deploy credentials are unavailable, an agent may complete local automated work for a slice but must not mark the slice done or fabricate manual verification.

## Slice sequence

| Slice | End-to-end outcome |
|---:|---|
| 0 | Authenticated Paperclip survives restart and a verified backup restore on the Compose foundation. |
| 1 | Lior tells Chief of Staff in Telegram to create work and receives a real Paperclip issue ID. |
| 2 | A Paperclip issue wakes the same Chief profile, which executes and updates the issue to a terminal or explicit blocked state. |
| 3 | Product, Growth, and Operations join as isolated Telegram/Paperclip employees; cross-employee work is visible in Paperclip. |
| 4 | An employee reads `nix-brain`, opens a linked knowledge PR, and cannot bypass review. |
| 5 | One proposal completes challenge → research → grilling → roadmap PR → approval → Paperclip project. |
| 6 | A Paperclip engineering issue produces a tested GitHub pull request through OpenCode. |
| 7 | An eligible human-only Paperclip action appears in Todoist and completion returns to Paperclip through minimal n8n. |
| 8 | Operations/Brainkeeper detects a stale or conflicting brain statement without silently resolving it. |
| 9 | A real small project traverses the complete system and recovery/runbooks are proven. |

---

## Slice 0 — Reproducible, recoverable control-plane foundation

### Objective

Create the smallest production-shaped Hostinger Compose deployment that proves Paperclip, authenticated ingress, PostgreSQL persistence, CI validation, secret separation, and backup/restore. Do not add Hermes or n8n yet.

### User-visible outcome

Lior can open Paperclip over HTTPS, authenticate, create the Nix company and a disposable smoke issue, restart the stack without data loss, and see the same issue. An operator can restore a backup into an isolated stack and verify it.

### Dependencies

- This documentation baseline and accepted ADRs.
- Canonical private GitHub remote.
- For production verification: VPS access, DNS, and off-host backup destination.
- Revalidate Paperclip, Caddy, PostgreSQL, Docker Engine, and Compose stable releases. Record exact tags and image digests.

### Components/files affected

- `compose.yaml` and a minimal production override only if actually needed.
- `.env.example` containing variable names/placeholders, never values.
- `deploy/caddy/Caddyfile` and the first-start PostgreSQL application-role initializer under `deploy/postgres/`.
- Small operator scripts for config validation, migration preflight, official Paperclip initialization, verified CEO bootstrap, data/config backup, restore, and VPS prerequisite checks; no daemon or framework.
- `tests/smoke/foundation.*`, encrypted config-pack smoke, and realistic Paperclip recovery smoke.
- `.github/workflows/ci.yml`.
- `docs/runbooks/DEPLOY.md` and `docs/runbooks/RESTORE.md`.
- Updates to `docs/UPSTREAM.md` with selected digests.

### Exact acceptance criteria

1. Repository default branch and private GitHub remote are configured; branch protection is documented or enabled.
2. Production images are pinned to stable versions and immutable digests. No `latest` tag exists.
3. `docker compose config` succeeds with a generated non-secret test fixture and fails clearly when required settings are absent.
4. The stack contains only Caddy, Paperclip, and PostgreSQL plus a short-lived backup job when invoked.
5. Only Caddy publishes host ports. PostgreSQL and Paperclip are reachable only on private Compose networks.
6. Paperclip runs in authenticated/public mode behind HTTPS; `/api/health` reports healthy through the public URL and from the internal network.
7. PostgreSQL uses a non-superuser Paperclip role and a persistent volume. Paperclip home/storage uses a persistent volume.
8. Secret values are loaded from root-owned files outside the checkout or per-service Compose secrets where the image supports `_FILE`. `git grep` and repository history contain no live secret.
9. Fresh volumes are provisioned through Paperclip's official onboarding path; a real user accepts a verified CEO invite; after signup is disabled, new signup fails and the CEO can still authenticate.
10. Create a smoke company/issue through Paperclip's API, recreate containers, and demonstrate the objects and known-byte attachment persist.
11. Data backup produces a timestamped PostgreSQL custom-format dump, Paperclip home/storage archive, configuration commit SHA, dependency-version manifest, and checksums. A separate mandatory age-encrypted configuration pack contains `.env` and the two external secret files.
12. Restore into a separate Compose project/network, never over production. The restored CEO can authenticate; company/issue relationships and attachment checksum match; a bound environment probe records successful canary-secret resolution without returning plaintext; and health passes.
13. Logs and health checks make database-unavailable and migration/preflight failure states distinguishable.
14. No Hermes, OpenCode, Todoist, n8n, Redis, custom application, or metrics stack is introduced.

### Automated tests

- Compose render validation with placeholder secrets.
- Assertions that only approved ports are published and every stateful service has a persistent mount.
- Assertions that images are version/digest pinned and no `latest` appears.
- Secret-pattern scan plus a test that `.env`, `secrets/`, data, and backup paths are ignored.
- Bash syntax and ShellCheck for operator scripts, plus static consistency checks across Compose, the environment contract, Caddy, and ignore rules.
- Read-only migration preflight: accept an empty database and a migrated Paperclip database; reject a non-empty schema without the expected Drizzle journal before Paperclip starts.
- Fresh-bootstrap/recovery smoke: start from clean volumes, run official onboarding, validate public instance configuration, create a real user and verified CEO invite, accept it, disable signup, prove existing login, create a company/related issue/attachment/local-encrypted canary through supported APIs, resolve the canary through a bound environment probe, exercise `503 database_unreachable` and recovery, back up, restore with original external secrets into distinct fresh volumes, and verify authentication, values/relationships, attachment bytes, one new successful canary-resolution access event, and health.
- Encrypted configuration-pack smoke: create with an ephemeral age recipient, relocate it, restore under an isolated root, verify sidecar/internal checksums, byte equality, file modes, and reconstructed config without logging contents.

### Manual end-to-end verification

1. Point DNS to the VPS and deploy from a clean clone at a recorded commit.
2. Confirm 80/443 are the only public service ports with an external port probe.
3. Complete Paperclip signup and verified CEO bootstrap, disable signup, prove new signup is rejected, and prove the existing CEO can sign in.
4. Create the Nix company, set a deliberately tiny initial budget, and add a disposable issue, known-byte attachment, and harmless encrypted-secret canary.
5. Run `docker compose down` without volume deletion, start again, and verify both objects.
6. Create and upload both the encrypted configuration pack and encrypted data backup, download them, then run the isolated restore with original external secret files.
7. Authenticate, verify company/issue relationship and attachment checksum, run the bound environment probe and verify one new successful canary access event without printing its value, verify health, and destroy the restore environment.
8. Record non-secret evidence and restore timestamp in a Paperclip Operations issue once the production company exists.

### Failure modes

- DNS/TLS not ready: Caddy is unhealthy or HTTPS cannot issue; keep Paperclip unexposed rather than publish port 3100.
- Database unavailable/migration failed: Paperclip stays unhealthy and restart policy does not hide the root error.
- Missing secret: config check fails before deployment and names the missing secret, never its value.
- Backup upload failed: local backup remains with failure status; do not report success until off-host checksum is confirmed.
- Restore target collision: script exits before touching any existing volume/database.
- Disk full: health/backup fails visibly; retention never deletes the last known-good off-host backup.

### Deliberately deferred

Hermes, Telegram, OpenCode, GitHub App automation, `nix-brain`, Todoist, n8n, comprehensive monitoring, HA, automatic upgrades, and zero-downtime deployment.

### Implementation record — 2026-09-24

The repository portion of Slice 0 and the independent-review remediation are complete. The Compose stack still contains only Caddy, Paperclip, and PostgreSQL. Deploy now performs migration preflight and official fresh-instance onboarding before server startup; CEO bootstrap requires API evidence of an active invite. Data recovery uses real Paperclip objects, and an independent age-encrypted configuration pack makes the external `.env` and service-secret recovery concrete.

### Live acceptance record — 2026-09-24

Status: **INCOMPLETE — stopped at Gate 1 branch protection.** No VPS deployment was attempted.

| Gate | Evidence | Status |
|---|---|---|
| 1. GitHub | Private `Lior-Nis/nix-os` created; reviewed branch SHA `2b16f2be7b310a6e8d759ed4e78b69f78778848a`; hosted Actions run `36002280447` passed `foundation` and `recovery`; PR `#1` merged to `main` at `3349a37d830b86fada050191a4562436bf15de5d`. Private `Lior-Nis/nix-brain` canonical `main` is `68a1da87f1a30fb646cef7ecaba38e9ee437c2ad`. A later hosted recovery run on the evidence-only commit exposed a cold-runner onboarding timing defect: the fixed five-second prompt input could arrive before the CLI was ready. The smallest fix increases the bounded prompt delay and timeout without changing the official onboarding path; `./scripts/ci` and a clean full local bootstrap/recovery smoke passed after the correction, and PR `#2` carries it for hosted validation. GitHub rejected required-check branch protection for the private repository with HTTP 403 because the current account plan does not provide that feature; making the repositories public is not acceptable. | **BLOCKED** pending GitHub Pro (or migration to a private organization/repository plan that supports protected branches), then require `foundation` and `recovery` on `main`. |
| 2. VPS prerequisites | Not attempted because Gate 1 is incomplete. | Pending |
| 3. Firewall/network exposure | Not attempted because Gate 1 is incomplete. | Pending |
| 4. DNS/TLS | Not attempted because Gate 1 is incomplete. | Pending |
| 5. Production bootstrap | Not attempted because Gate 1 is incomplete. | Pending |
| 6. Recovery canaries | Not attempted because Gate 1 is incomplete. | Pending |
| 7. Encrypted backups | Not attempted because Gate 1 is incomplete. | Pending |
| 8. Off-host storage | Not attempted because Gate 1 is incomplete. | Pending |
| 9. Isolated production recovery | Not attempted because Gate 1 is incomplete. | Pending |
| 10. Final production checks | Not attempted because Gate 1 is incomplete. | Pending |

Resume from Gate 1 after the private repository has a plan that supports branch protection. Apply strict required status checks `foundation` and `recovery` to `main`, verify the protection through the GitHub API, and only then continue with the VPS preflight. Do not treat the successful hosted CI or merge alone as completion of Gate 1.

Locally verified:

- Compose rendering and policy assertions, including service count, private PostgreSQL/Paperclip networking, persistent mounts, pinned images, health checks, and required configuration failures.
- Bash syntax and ShellCheck 0.11.0 for every operator and smoke-test script.
- Caddy 2.11.4 validation against the committed Caddyfile.
- A clean-volume Docker smoke using Paperclip 2026.916.1 and PostgreSQL 17.11: official onboarding and validated `authenticated/public` config; real signup, verified bootstrap invite, invite acceptance, signup closure, existing CEO login; least-privilege database role; missing-journal rejection; real company/issue/attachment/encrypted-canary creation through supported APIs; source canary resolution without plaintext output; database-backed health failure/recovery; age-encrypted backup relocation/decryption; restore with the original external secret files into fresh volumes; restored CEO login, company/issue relationship, attachment-byte checksum, a new successful canary-resolution access event using the recovered master key, exact `/paperclip` file comparison, and health.
- A real age-encrypted configuration-pack round trip using an ephemeral identity, including external/inner checksum verification, isolated path reconstruction, mode `0600`, and byte equality without content logging.
- Local secret-pattern checks and ignore-rule checks. No live credential was created inside the repository.

Not yet verifiable without external access:

- GitHub remote push, hosted CI execution, and default-branch protection.
- Hostinger VPS deployment, external 80/443-only port probe, DNS, automatic TLS issuance, and public health.
- Real browser bootstrap/CEO verification and public signup closure on the deployed hostname (the same lifecycle is automated locally through supported HTTP interfaces).
- Encryption with Lior's real age recipient, config/data upload to the selected off-host destination, download, remote checksum confirmation, and isolated restore with original external secret files.

Current upstream constraints discovered during implementation:

- Stable Paperclip is `v2026.916.1`; the container tag is `2026.916.1` without the `v` prefix.
- Authenticated/public deployment requires external PostgreSQL and explicit auth/tool-action signing secrets. The tool-action signing secret has no safe fallback.
- `/api/health` is database-backed and returns `503` with `database_unreachable` when PostgreSQL cannot be reached.
- The pinned server enters its auto-migration path when a non-empty database lacks the expected Drizzle journal, inspects that state, and rejects it before applying migrations. Nix keeps its own read-only preflight as defense in depth so the documented deploy, upgrade, restart, and restore workflows fail earlier with a clearer operator error. Direct Compose startup or an engine-managed container restart does not necessarily run the Nix preflight; the pinned upstream guard still fails closed before mutation. Future releases still require migration review.
- `/paperclip` is persistent application state independent of PostgreSQL and must be backed up with the database.
- Public mode disables the browser-first admin claim. The CLI requires instance config and can return zero when config is missing, so official onboarding runs first and the wrapper verifies the resulting invite through the API rather than by exit code.
- The pinned CLI has no non-interactive public-onboarding preset: `--yes`/`--bind` selects trusted/private modes. Nix runs the official Quickstart prompt in a bounded pseudo-terminal so public environment defaults are honored, then validates the exact generated config before startup.
- Normal board secret reads never return values, but the supported board-authorized environment probe resolves a bound secret and records a success event without returning plaintext. This makes cryptographic recovery locally testable without a later-slice agent.

Exact prerequisites for live activation are: the canonical private GitHub repository URL; Hostinger VPS SSH access to Ubuntu 24.04 x86_64 with Docker Engine 27+/Compose 2.30+ and the documented tools; the Paperclip DNS hostname pointed at that VPS; and an age recipient/identity plus credentials/path for an encrypted off-host backup destination.

Slice 1 entry condition: the canonical branch is protected with both CI jobs green; the Hostinger deployment passes firewall/TLS and browser CEO/signup checks; current encrypted config and data artifacts exist off-host with confirmed checksums; their downloaded copies pass isolated restore with original external secrets; the restored CEO/company/issue/attachment/health checks pass; and the canary secret resolves without plaintext logging. Only then revalidate the current Hermes, Paperclip MCP, Telegram, and model-provider documentation and implement Slice 1.

---

## Slice 1 — Telegram to Chief of Staff to Paperclip work creation

### Objective

Add one persistent Hermes Chief of Staff profile and prove that a Telegram conversation can create and read Paperclip work through official upstream surfaces.

### User-visible outcome

In the private Chief of Staff Telegram context, Lior can say “Create a work item to …”. Chief replies with the created Paperclip identifier/title, and the issue is immediately visible in Paperclip. A request that is only a question stays in Telegram.

### Dependencies

- Slice 0 complete.
- Telegram bot token, Lior allowlist ID, provider credential/model, and a deliberately small spend limit.
- Revalidate pinned Hermes release, Paperclip MCP package compatibility, and Telegram setup docs.

### Components/files affected

- Add Hermes service, private network, persistent profile volume, resource limits, and health check to Compose.
- `config/hermes/chief/config.yaml` and `SOUL.md` templates without secrets.
- Secret-name additions to `.env.example`/runbook.
- Idempotent operator provisioning step for Chief Paperclip agent key and Hermes API key.
- `tests/contracts/paperclip-mcp.*` and `tests/e2e/telegram-work-creation.md`.
- Architecture/runbook updates if verified behavior differs.

### Exact acceptance criteria

1. One Hermes profile named/identified as Chief of Staff has isolated persistent state and starts under upstream-supported gateway supervision.
2. Telegram is handled by Hermes' native adapter. There is no custom Telegram receiver and Paperclip's Telegram connector is disabled.
3. Only Lior's allowlisted Telegram identity is accepted; an unauthorized identity receives no agent/tool access.
4. Hermes' Runs API is private to Compose and requires a unique `API_SERVER_KEY` even internally.
5. The Chief profile receives a separate revocable Paperclip agent key and can call the official `@paperclipai/mcp-server` at the internal Paperclip URL.
6. The MCP server/package is pinned; its tool allowlist permits health/identity, issue list/get/create/update/comment/question/confirmation operations needed by the slice and excludes project/goal creation, approvals decisions, arbitrary API escape hatch, and destructive tools.
7. A Telegram commitment creates exactly one Paperclip issue with useful title/body, source context, and Chief ownership or routing. Chief replies with the actual issue identifier only after the API succeeds.
8. A Telegram question or clarification exchange creates no issue unless Lior explicitly creates a commitment.
9. A request to create a new top-level project/goal is not executed; Chief asks for/records approval through the allowed conversational path.
10. A simulated Telegram redelivery is handled by Hermes/Telegram update identity without duplicate tool execution, or the limitation is evidenced and a bounded idempotency mechanism is added at the workflow edge—not a general event bus.
11. Restarting Hermes preserves the Chief profile and conversation continuity.
12. No Todoist object is created; Todoist is not configured.

### Automated tests

- Config schema/static checks: no secret literals, API server not publicly published, allowlist required, MCP package pinned, dangerous tools absent.
- Contract test against the pinned Paperclip OpenAPI/MCP surface: authenticate as Chief, list, create, fetch, and comment on a disposable issue; clean up through a board test fixture.
- Hermes readiness contract: `/health`, `/v1/capabilities`, authenticated run creation/SSE/stop on the private network.
- Unauthorized Telegram/user fixture test if upstream provides an adapter harness; otherwise capture this as mandatory manual evidence.
- Restart test checks profile files/state persist.

### Manual end-to-end verification

1. Message Chief from Lior's account with a pure question; confirm a useful reply and zero new Paperclip issues.
2. Send an explicit work commitment with an unusual marker string.
3. Confirm Chief replies with one Paperclip ID, and that issue contains the marker/source and correct assignee.
4. Ask Chief to retrieve the issue by ID and summarize its current state.
5. Restart Hermes and continue the Telegram conversation.
6. Attempt access from a non-allowlisted test identity and verify denial in sanitized logs.

### Failure modes

- Telegram works but Paperclip is down: Chief says recording failed, does not invent an ID, and a safe retry does not duplicate confirmed work.
- MCP package/API drift: startup/contract check fails with the incompatible version and route/tool name.
- Agent key revoked: Paperclip returns 401; Chief cannot mutate work and escalation names credential repair, not a model failure.
- Model/provider unavailable: Hermes reports failure while Paperclip remains healthy; no half-created commitment is claimed.
- Bot token conflict or duplicate gateway: upstream token lock prevents the second writer from starting.
- Tool call proposes forbidden top-level project/goal: capability is absent and Chief asks Lior instead.

### Deliberately deferred

Paperclip-triggered execution, Product/Growth/Operations, Telegram topic multiplexing, brain access, OpenCode, Todoist, n8n, external communication, and spending tools.

---

## Slice 2 — Paperclip and Chief of Staff execution loop

### Objective

Make Paperclip able to wake the same persistent Chief profile, execute an assigned issue, and receive auditable progress/result state.

### User-visible outcome

Lior assigns/wakes a bounded issue in Paperclip. The Chief checks it out, performs a harmless task, comments with evidence, and moves it to `done`, `in_review`, or an explicit `blocked` state. The run transcript is visible in Paperclip.

### Dependencies

- Slice 1 complete.
- Current Paperclip Hermes Gateway onboarding and E2E smoke verified against pinned versions.

### Components/files affected

- Chief Paperclip adapter configuration (`hermes_gateway`) with secret reference, internal URL, issue-scoped session strategy, timeout, and reconnect policy.
- Idempotent join/approve/claim operator procedure.
- Chief operating instructions for checkout, status, child work, approval, and escalation.
- `tests/e2e/paperclip-hermes-loop.*` and runbook diagnostics.

### Exact acceptance criteria

1. Paperclip can reach the authenticated Hermes Runs API over the private network; it is not exposed publicly.
2. Hermes can reach Paperclip using its claimed Chief agent identity; the Hermes API key and Paperclip key are demonstrably different.
3. The upstream `smoke:hermes-gateway-e2e` behavior is reproduced or wrapped without copying its runtime logic.
4. A Paperclip run carries correlation among Paperclip issue ID, Paperclip run ID, Hermes run ID, and logs without leaking credentials.
5. Duplicate Paperclip run creation with the same run identity does not cause duplicate substantive side effects; verify actual pinned Hermes idempotency behavior rather than trusting the header alone.
6. Chief can read/check out the assigned issue, add progress/evidence, and reach a valid terminal/review/blocked state under Paperclip ownership rules.
7. `sessionKeyStrategy: issue` prevents context from one test issue appearing in another.
8. A bounded child issue inside the same approved scope can be created autonomously and linked to its parent.
9. A consequential ambiguity blocks the issue and produces a question in Chief's Telegram context, not Todoist.
10. Timeout, gateway restart, and SSE interruption leave a visible failed/timed-out run and a retryable issue; polling fallback is evidenced.

### Automated tests

- Fresh-state Paperclip↔Hermes gateway smoke based on upstream documented endpoints.
- Issue lifecycle contract including checkout conflict, comment, child creation, and allowed terminal states.
- Two-issue session-isolation test using unique canary text.
- Duplicate run/correlation test and SSE disconnect/poll fallback test where practical.
- Secret-redaction assertions over captured diagnostics.

### Manual end-to-end verification

Create a harmless Paperclip issue asking Chief to inspect a known public fact or local fixture, wake it, observe the live run, and verify its evidence/status. Interrupt one second issue by restarting Hermes, then retry it and confirm a single final result with the failed attempt still auditable.

### Failure modes

Gateway auth mismatch, static Paperclip key not present after onboarding, run-lock conflict, session bleed, dropped SSE, model timeout, and a run that finishes in Hermes but not Paperclip. Each must map to a documented diagnostic and safe retry.

### Deliberately deferred

Multiple employees, durable brain writes, engineering execution, Todoist, n8n, and nontrivial external actions.

---

## Slice 3 — Isolated Product, Growth, and Operations employees

### Objective

Expand the proven employee pattern to the locked V0 organization and prove cross-employee delegation through Paperclip.

### User-visible outcome

Lior can address Chief, Product, Growth, and Operations in distinct Telegram contexts. Each retains its own persona/memory and creates/executes work as its matching Paperclip identity. Product can delegate a substantive Growth request that appears as Paperclip work.

### Dependencies

- Slice 2 complete and stable under normal use.
- Telegram group/topic design selected from verified Hermes capabilities: preferred one private forum bot plus multiplexed topic/profile routes; supported independent profile gateways are the fallback.

### Components/files affected

- Three additional Hermes profile config/SOUL templates and Paperclip agent records.
- Telegram routing/topic configuration and per-profile secret scopes.
- Org chart/reporting/delegation policy in Paperclip.
- Isolation and cross-agent E2E tests; backup manifest extended for all profiles.

### Exact acceptance criteria

1. Exactly four persistent Hermes employee profiles exist: Chief, Product, Growth, Operations. No Engineering Manager exists.
2. Each profile has isolated SOUL, model config, memory, sessions, Paperclip agent key, Telegram authorization, and logs.
3. Growth instructions explicitly cover both marketing and sales.
4. Telegram routing sends a canary in each context to only the expected profile; no profile can read a sibling's memory/secret canary.
5. Paperclip's adapter URL/auth invokes the matching profile for all four employees. If multiplexed prefixed Runs URLs are unsupported by the pinned adapter, use independently supervised upstream gateways and record the change in an ADR.
6. Product handing substantive work to Growth creates/reassigns a visible Paperclip child issue before Growth executes it.
7. A bounded temporary research subagent stays owned by the requesting employee and returns into the parent issue; it does not become a fifth persistent employee.
8. Agents cannot create top-level projects/goals through their normal tool allowlist.
9. Backup/restore covers all profile state and proves restored identity isolation.

### Automated tests

- Profile configuration uniqueness and missing-secret checks.
- Four-way Runs API routing canaries and session/memory isolation tests.
- Cross-agent delegation test asserts a Paperclip issue/parent/assignee transition exists.
- Org invariant test rejects an Engineering Manager and verifies Growth responsibility markers.
- Restore smoke samples each profile.

### Manual end-to-end verification

Hold a short conversation in each Telegram context, ask each employee its role, then ask Product to request a Growth deliverable. Confirm Growth executes only after a Paperclip handoff and that all activity is attributable to the correct identities.

### Failure modes

Topic routed to wrong profile, shared bot token conflict, shared `.env` leakage, Paperclip adapter URL pointing to the wrong prefix/port, duplicate gateway writer, or cross-agent work done only in chat. Fail closed and disable the affected route.

### Deliberately deferred

More roles, Engineering Manager, permanent Research employee, per-profile containers without a measured isolation need, shared memory service, and dynamic org design.

---

## Slice 4 — `nix-brain` read and pull-request write loop

### Objective

Make the separate Git-backed brain useful to employees without turning it into a task database or allowing direct default-branch writes.

### User-visible outcome

An employee can answer from current brain content, propose a focused durable update on a branch, open a GitHub PR linked to Paperclip work, and surface the PR for review.

### Dependencies

- Slice 3 complete.
- Separate private `nix-brain` GitHub repository and initial minimal taxonomy approved by Lior.
- Current GitHub App/Paperclip GitHub connector capabilities and permissions revalidated.

### Components/files affected

- Brain clone/worktree configuration and employee read path.
- Least-privilege GitHub App or supported Paperclip GitHub connection.
- Brain contribution instructions and CI in the `nix-brain` repository.
- Integration tests linking issue ↔ branch ↔ PR.

### Exact acceptance criteria

1. `nix-brain` is a separate Git repository; no runtime databases, transcripts, or secrets are committed.
2. Default branch is protected from agent direct pushes and requires passing CI/review.
3. Employees read from a known fetched commit and report that revision in evidence when consequential.
4. A Paperclip issue produces a focused branch/commit/PR with reciprocal links.
5. Roadmaps have a documented brain path; live checklists/status remain in Paperclip.
6. GitHub credential scope is limited to the required repositories and contents/PR operations; external communication/merge remains approval-gated.
7. Concurrent edits use separate branches/worktrees and surface merge conflicts; no last-writer overwrite.
8. A failed push leaves the Paperclip issue open/blocked and the local commit recoverable.

### Automated tests

- Brain schema/link/Markdown checks and a policy test rejecting obvious live task-state fields in roadmap documents.
- Git integration against a disposable repository or local bare remote: branch, commit, PR adapter contract/mocked GitHub boundary, conflict behavior.
- Permission test demonstrating direct default-branch push is rejected in the real manual environment.
- Secret scan.

### Manual end-to-end verification

Give Operations a Paperclip issue to add one harmless glossary fact. Verify it reads current content, opens a linked PR, cannot push directly to default, and sees merged content after human approval and refresh.

### Failure modes

Stale clone, GitHub auth expiry, branch conflict, CI failure, PR created against wrong repo/base, or unpushed local-only knowledge. Paperclip status must describe the exact state.

### Deliberately deferred

Vector database/RAG service, semantic search infrastructure, automatic merges, monorepo consolidation, knowledge scoring, and generic skill distribution.

---

## Slice 5 — Project Inception and direct grilling

### Objective

Encode the required inception behavior in employee instructions, capability boundaries, brain templates, and Paperclip approvals—without a custom workflow engine.

### User-visible outcome

A candidate project is challenged, researched, clarified directly with Lior, documented as a roadmap PR, explicitly approved, and only then instantiated as a Paperclip project/goal with executable work.

### Dependencies

- Slice 4 complete.
- One real but small candidate project from Lior.

### Components/files affected

- Employee operating instructions and a concise `nix-brain` roadmap template.
- Paperclip approval/project provisioning procedure or supported routine.
- Inception E2E fixture and audit checklist.

### Exact acceptance criteria

1. The record contains distinct challenge, research, grilling, roadmap PR, approval, and project-creation evidence.
2. Research normally uses temporary subagents owned by the requesting employee; findings return to the parent issue/roadmap sources.
3. The employee closest to each consequential ambiguity asks Lior in its own Telegram context.
4. No clarification or approval question appears in Todoist (which is still absent).
5. Before explicit approval, no top-level Paperclip project/goal is created; agent capability does not permit bypass.
6. The roadmap is merged/approved in `nix-brain` and contains outcomes, constraints, risks, and sequencing—not live issue statuses.
7. Lior's explicit approval is linked to the resulting top-level Paperclip project/goal.
8. After approval, employees may autonomously create and execute subordinate issues inside the accepted scope.
9. A rejected/abandoned proposal closes cleanly without a ghost project.

### Automated tests

- State-machine-style contract test over recorded artifacts, ensuring project creation cannot precede approval.
- Roadmap schema/policy checks.
- Tool allowlist tests for top-level goal/project mutation.
- Test that temporary research identity cannot persist as an employee.

### Manual end-to-end verification

Run one real proposal through every stage. Intentionally leave one consequential ambiguity so the responsible employee must grill Lior. Approve or reject explicitly and inspect the complete Paperclip/Telegram/GitHub audit trail.

### Failure modes

Premature project creation, research with no source/evidence, question routed through the wrong employee, roadmap used as a live tracker, ambiguous approval, or rejected proposal spawning tasks. Halt before project creation.

### Deliberately deferred

Generic BPM engine, automatic portfolio prioritization, formal research evals, and automatic approval inference from casual chat.

---

## Slice 6 — OpenCode engineering execution

### Objective

Prove the primary coding harness can take a Paperclip engineering issue through an isolated repository change, tests, and a reviewable GitHub PR.

### User-visible outcome

An approved project issue assigned to the OpenCode Engineer results in a tested PR linked back to Paperclip, with human approval before merge.

### Dependencies

- Slice 5 complete.
- A small repository/testable issue and configured model/provider.
- Revalidate Paperclip `opencode_local`, OpenCode CLI, and execution-workspace support.

### Components/files affected

- Thin Paperclip image extension or supported host setup containing the pinned OpenCode binary; no wrapper runtime.
- Engineer agent config, instructions file, repository workspace mapping, GitHub credentials.
- Engineering E2E tests and diagnostics runbook.

### Exact acceptance criteria

1. Paperclip owns the Engineer issue and invokes its built-in `opencode_local` adapter.
2. OpenCode version/model are explicit; provider can be changed in configuration without code changes.
3. Work occurs in an issue-specific upstream-supported workspace/worktree. The default branch and unrelated work are not mutated.
4. The Engineer reads repository instructions, implements only issue scope, runs existing tests without weakening them, and reports commands/results.
5. A focused branch/commit/PR is created with Paperclip issue linkage and no secrets.
6. Merge remains approval-gated; external release/deploy is not implied by code completion.
7. Failed tests leave the issue non-done with evidence. A timeout/interruption preserves the branch/worktree for retry.
8. At most one engineering issue per repository runs concurrently in V0 unless workspace isolation proves parallel safety.
9. No Engineering Manager profile/service is introduced.

### Automated tests

- Adapter environment smoke using `opencode run --format json` on a fixture repository.
- Workspace isolation assertions and dirty-default-branch check.
- Intentional failing-test fixture confirms failure is surfaced, not bypassed.
- PR metadata/secret scan and session-resume test with the same `cwd`.

### Manual end-to-end verification

Assign a small real defect/doc-code change, observe the Paperclip run, review test output and diff, approve/merge the PR manually, and close the Paperclip issue only after CI passes.

### Failure modes

Invalid model ID, CLI missing, permission prompt hang, dirty/shared workspace, test failure, GitHub auth failure, context/session resume against moved `cwd`, or attempted direct default-branch push. Preserve artifacts and block visibly.

### Deliberately deferred

Parallel coding fleet, custom sandbox provider, browser farm, autonomous merge/deploy, code-review bots, and provider abstraction.

---

## Slice 7 — Minimal n8n and Todoist human-action loop

### Objective

Introduce n8n only to maintain an idempotent, deterministic projection from explicitly eligible Paperclip human actions into Todoist and back.

### User-visible outcome

A concrete action that only Lior can perform appears once in a dedicated Todoist project with a Paperclip link. Completing it updates the Paperclip source. A clarification question never appears in Todoist.

### Dependencies

- Slice 6 complete or an explicit decision to prioritize the human loop sooner.
- Todoist account/project and personal token for single-user V0 (OAuth only if requirements expand).
- Revalidate Todoist API v1/webhooks and stable n8n release.

### Components/files affected

- n8n service, separate PostgreSQL database/role, persistent storage, `N8N_ENCRYPTION_KEY`, authenticated ingress.
- Versioned n8n workflow export(s) for Paperclip→Todoist and Todoist→Paperclip.
- Explicit human-action marker/schema and mapping fields.
- Webhook HMAC/delivery-id handling, tests, runbook, and backup extension.

### Exact acceptance criteria

1. n8n is pinned, single-process, and uses PostgreSQL. No Redis, queue mode, workers, or AI nodes.
2. n8n UI is authenticated; only required webhook paths are public through Caddy.
3. `N8N_ENCRYPTION_KEY` is outside Git, backed up encrypted, and proven during restore.
4. Eligibility is deterministic: explicit human-action marker + Lior executor + concrete action/completion. Questions, approvals, choices, FYIs, and agent-executable work are rejected.
5. An eligible Paperclip item creates exactly one Todoist task with source ID/URL and stable mapping; retries/redeliveries do not duplicate it.
6. Todoist webhook HMAC is verified over the raw body and repeated delivery IDs are idempotent.
7. Completing the Todoist task updates/comments/closes the source according to one documented mapping. Deleting/rewording Todoist never deletes Paperclip source truth.
8. Paperclip unavailability causes bounded retries/dead-letter visibility in n8n; Todoist completion is not lost silently.
9. Todoist API v1 opaque IDs and pagination are treated as strings/cursors.
10. A question asked during the same E2E session results in zero Todoist tasks.
11. Workflow JSON is exported to Git after credential redaction and can be imported into a clean restored n8n instance.

### Automated tests

- Eligibility decision table with positive and negative fixtures, especially clarification/approval cases.
- Mock Todoist/Paperclip contract tests for creation, retry, completion, deletion, signature failure, and duplicate delivery ID.
- Workflow export lint/redaction and clean-import test.
- n8n database/storage/encryption-key restore smoke.

### Manual end-to-end verification

Create one physical human action (for example, “Photograph the device serial label and attach it”) and one clarification question. Confirm only the action appears in Todoist once. Complete it and verify the source Paperclip issue updates with a traceable event.

### Failure modes

Invalid HMAC, duplicate webhook, expired Todoist credential, mapping missing, Paperclip down, n8n encryption key mismatch, or accidental ineligible projection. Invalid/ineligible events stop visibly; Paperclip remains authoritative.

### Deliberately deferred

General bidirectional task sync, natural-language eligibility classification, Todoist as a backlog, multi-user OAuth, calendar sync, reminders policy, and arbitrary n8n automation.

---

## Slice 8 — Brainkeeper and knowledge CI

### Objective

Add a narrow knowledge-maintenance behavior owned by Operations plus deterministic CI, without creating a new persistent employee or silently rewriting meaning.

### User-visible outcome

Operations periodically reports stale links/facts and potential contradictions as a Paperclip issue or brain PR. A semantic contradiction asks for resolution and remains unresolved until reviewed.

### Dependencies

- Slice 4 brain loop complete; Slice 7 n8n is not required.
- Enough real brain content to test useful findings.

### Components/files affected

- Operations Brainkeeper instructions/routine in Paperclip.
- Deterministic brain CI checks and finding format.
- Test corpus containing stale, structural, and semantic-conflict examples.

### Exact acceptance criteria

1. Brainkeeper is an Operations-owned routine/skill, not a fifth persistent employee or service.
2. Deterministic checks cover Markdown validity, internal links, required metadata, duplicate identifiers, and declared review dates.
3. Potential semantic contradictions include both citations/locations and are never auto-resolved or merged.
4. Safe mechanical fixes may be proposed in a PR, but review/merge policy still applies.
5. Findings create/dedupe Paperclip work; they do not become Todoist tasks unless a distinct human-executable action later qualifies.
6. A no-change run produces a concise auditable result and no churn PR.
7. Research needed to assess staleness may use bounded temporary subagents under Operations.

### Automated tests

- Fixture tests for broken link, stale review date, duplicate ID, exact duplicate, and conflicting semantic statements.
- Assertion that semantic conflict produces a finding with no changed source file.
- Rerun/deduplication test and clean-corpus no-op test.

### Manual end-to-end verification

Seed one harmless stale fact and one deliberate contradiction. Run the routine. Confirm the stale item may receive a proposed PR while the contradiction stays as a clearly located unresolved finding for Lior.

### Failure modes

False positive, source unavailable, PR conflict, duplicate findings, or model attempting to choose a semantic winner. Keep the source unchanged and make the finding reviewable.

### Deliberately deferred

Embeddings/vector search, autonomous semantic reconciliation, knowledge confidence scores, formal eval infrastructure, and automatic document expiration.

---

## Slice 9 — Real end-to-end project and V0 hardening

### Objective

Use one real, small, reversible project to validate the operating system as a whole and fix only observed gaps.

### User-visible outcome

Lior can initiate and approve a project from Telegram, observe autonomous cross-employee and engineering execution in Paperclip, review brain/code PRs, perform any true human action from Todoist, and recover the system from backup.

### Dependencies

- Slices 0–8 complete.
- A bounded project with measurable outcome, low spend, and no risky external communication requirement.

### Components/files affected

Only files justified by failures observed during the real run; final runbooks, acceptance evidence, and dependency locks.

### Exact acceptance criteria

1. The project follows the entire inception contract before top-level Paperclip creation.
2. At least two persistent employees collaborate through Paperclip, with no substantive hidden chat handoff.
3. At least one bounded temporary research subagent contributes to its parent's work.
4. OpenCode produces a tested reviewable PR when engineering work exists.
5. Durable learning produces a reviewed `nix-brain` PR.
6. At least one consequential ambiguity is grilled through the closest employee's Telegram context.
7. If a genuine human-only action exists, it round-trips through Todoist; otherwise the test explicitly demonstrates zero spurious Todoist tasks.
8. Approval gates prevent a rehearsed external-send, spend, destructive action, and top-level project bypass.
9. Agents exhaust a documented autonomous alternative before one controlled escalation.
10. Full backup and isolated restore meet the initial RPO/RTO targets, including Paperclip, all Hermes profiles, brain/source clones, and n8n credential decryption.
11. Every production image/package is pinned and the upstream snapshot reflects deployed reality.
12. Post-run review removes or defers unused configuration; no speculative service remains.

### Automated tests

Run the complete CI, contract, E2E, secret, backup, and restore suite. Add regression tests only for failures actually encountered. Produce a machine-readable version/health report without secrets.

### Manual end-to-end verification

Execute the chosen project from initial Telegram proposal through outcome and retrospective. Then restore the stack into an isolated environment and sample one artifact from every authority: Paperclip issue/run, Hermes profile memory/session, brain PR content, code PR, and n8n/Todoist mapping if used.

### Failure modes

Any authority drift, untraceable handoff, missed approval, secret exposure, duplicate projection, unrecoverable state, or false success claim reopens the owning slice. Do not mask a failed contract with manual database edits.

### Deliberately deferred

Everything explicitly excluded by the mission plus any feature not demanded by the real project.

---

## Requirement traceability

Every locked requirement is implemented or explicitly delayed to a named slice.

| Requirement | Owning slice(s) |
|---|---|
| Paperclip authoritative work graph | 0 establishes; 1–9 enforce |
| Telegram for conversation, clarification, grilling, decisions | 1 establishes; 3 and 5 complete routing/process |
| Todoist only for real human-executable work | 7 |
| Clarification questions never become Todoist tasks | 1/2 behavior; 7 deterministic negative tests |
| Exhaust autonomous alternatives before escalating | 2 instructions; proven in 9 |
| Cross-agent substantive work becomes Paperclip work | 3 |
| Autonomous subordinate work inside approved scope | 2 child issue; 5 approved-project boundary |
| New top-level projects/goals need Lior approval | capability restriction in 1; full flow in 5 |
| Durable knowledge via PRs to `nix-brain` | 4 |
| Approval for external communication, spend, destructive/irreversible action | policy from 1; exercised in 9 |
| Routine execution otherwise autonomous | 2 onward |
| Project Inception sequence | 5 |
| Roadmaps in brain; live execution in Paperclip | 4 and 5 |
| Closest employee grills Lior directly | 3 routing; 5 proof |
| Brainkeeper flags but never silently resolves contradictions | 8 |
| Chief, Product, Growth, Operations Hermes profiles | Chief in 1; remaining roles in 3 |
| No Engineering Manager | 3 invariant and 6 |
| Growth owns marketing and sales | 3 |
| Temporary research subagents owned by requester | 3 establishes; 5/8 exercise |
| OpenCode primary coding harness | 6 |
| n8n deterministic plumbing only | 7 |
| GitHub canonical provider | 0 source; 4/6 PR flows |
| Hostinger VPS + Docker Compose | 0 |
| Broad autonomy with durable learning | 2, 4, 5, 9 |
| Git config vs runtime state vs secrets and recovery | 0 implements architecture contract; extended in 3/7/9 |

## Exact next implementation task

Activate **Slice 0 in production** using `docs/runbooks/DEPLOY.md`, then complete the production and downloaded-off-host restore evidence listed in the Slice 0 implementation record. This is operational completion of Slice 0, not Slice 1 implementation.

After the Slice 1 entry condition above is satisfied, implement only the Telegram → Hermes Chief of Staff → Paperclip work-creation path. Do not add later-slice services while doing so.
