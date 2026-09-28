# Nix Business OS V0 implementation plan

Status: **SLICE 0: ACCEPTED. SLICE 1: IMPLEMENTED, REVIEW PENDING.** Slice 1 has not been independently reviewed, deployed, or live-accepted. Updated 2026-09-28.

## How to use this plan

Implement slices in order. A later slice may start only when its dependencies and the previous slice's exit criteria are satisfied. Revalidate all affected upstream releases against `docs/UPSTREAM.md` before editing integration configuration.

Each slice is vertical: it ends in a behavior Lior can observe and a failure Lior can diagnose. A tool being installed is not, by itself, a completed slice.

## Material discoveries and prerequisites

### Repository facts

The supplied directory was empty on 2026-09-22. The reviewed foundation and remediation were merged through PRs. The reviewed tailnet-only amendment passed hosted `foundation` and `recovery` CI in PR #3 and merged as canonical production commit `a6205378c70048c76a8ad15c73da3c6777e6404f`.

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
| Hostinger VPS SSH access and supported Linux host | Slice 0 deploy | Tailscale is already joined; Docker Engine/Compose and remaining prerequisites must pass preflight |
| Tailscale MagicDNS/HTTPS enablement | Slice 0 deploy | discover the real suffix from the VPS; never invent it; web consent may be interactive |
| Google Drive OAuth for `rclone` | Slice 0 exit | use Lior's account and owned Desktop OAuth client; upload ciphertext only |
| age identity custody | Slice 0 exit | generated on Lior's Mac; keep a second safe copy outside the VPS and never Git |
| ChatGPT/Codex subscription device authorization | Slice 1 live deploy | stored in the Hermes volume; no paid API key by default |
| Telegram bot token and Lior's numeric Telegram user ID | Slice 1 live deploy | enter directly in `/etc/nix-os/hermes.env`; exact multi-topic UX remains Slice 3 |
| canonical private `nix-brain` clone | Slice 1 live deploy | mount read-only for Chief; PR write access remains Slice 4 |
| Todoist project/token or OAuth app details | Slice 7 | not required earlier |

If deploy credentials are unavailable, an agent may complete local automated work for a slice but must not mark the slice done or fabricate manual verification.

## Slice sequence

| Slice | End-to-end outcome |
|---:|---|
| 0 | Authenticated Paperclip survives restart and a verified backup restore on the Compose foundation. |
| 1 | Lior tells Chief of Staff in Telegram to create work and receives a real Paperclip issue ID. |
| 2 | A Paperclip issue wakes the same Chief profile, which executes and updates the issue to a terminal or explicit blocked state. |
| 3 | Product, Growth, and Operations join as isolated Telegram/Paperclip employees; cross-employee work is visible in Paperclip. |
| 4 | An employee reads `nix-brain`, opens a linked knowledge PR, gets hosted CI green and consequential review, then merges through the approved process. |
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
- Canonical GitHub remote. `nix-os` is public; `nix-brain` remains private.
- For production verification: VPS access, connected Tailscale/MagicDNS/HTTPS, and Google Drive OAuth.
- Revalidate Paperclip, Tailscale Serve, PostgreSQL, Docker Engine, Compose, and rclone. Record exact container tags and digests.

### Components/files affected

- `compose.yaml` and a minimal production override only if actually needed.
- `.env.example` containing variable names/placeholders, never values.
- First-start PostgreSQL application-role initializer under `deploy/postgres/`; Tailscale remains a host service.
- Small operator scripts for config validation, migration preflight, official Paperclip initialization, verified CEO bootstrap, data/config backup, restore, and VPS prerequisite checks; no daemon or framework.
- `tests/smoke/foundation.*`, encrypted config-pack smoke, and realistic Paperclip recovery smoke.
- `.github/workflows/ci.yml`.
- `docs/runbooks/DEPLOY.md` and `docs/runbooks/RESTORE.md`.
- Updates to `docs/UPSTREAM.md` with selected digests.

### Exact acceptance criteria

1. Private GitHub remote is configured; changes use feature branch -> PR -> hosted CI green -> consequential review -> merge. Agents do not intentionally push directly to `main`.
2. Production images are pinned to stable versions and immutable digests. No `latest` tag exists.
3. `docker compose config` succeeds with a generated non-secret test fixture and fails clearly when required settings are absent.
4. The Compose stack contains only Paperclip and PostgreSQL plus short-lived backup helpers when invoked.
5. Paperclip listens on all interfaces only inside its container namespace; Docker publishes it solely on VPS host loopback for Tailscale Serve. PostgreSQL publishes no host port. Neither is directly reachable through public or tailnet host interfaces.
6. The Tailscale node is named `nix-os`; MagicDNS works; complete Serve/Funnel state contains only HTTPS `:443` root proxying to Paperclip loopback, with no `AllowFunnel`, foreground/service config, extra port, or handler. Paperclip runs `authenticated/private`, still requires login, and reports healthy internally and through the tailnet URL.
7. PostgreSQL uses a non-superuser Paperclip role and a persistent volume. Paperclip home/storage uses a persistent volume.
8. Secret values are loaded from root-owned files outside the checkout or per-service Compose secrets where the image supports `_FILE`. `git grep` and repository history contain no live secret.
9. Fresh volumes are provisioned through Paperclip's official onboarding path; a real authenticated user claims the private instance (verified CLI invite only as fallback); after signup is disabled, new signup fails and the CEO can still authenticate.
10. Create a smoke company/issue through Paperclip's API, recreate containers, and demonstrate the objects and known-byte attachment persist.
11. Data backup produces a timestamped PostgreSQL custom-format dump, Paperclip home/storage archive, configuration commit SHA, dependency-version manifest, and checksums. A separate mandatory age-encrypted configuration pack contains `.env` and the two external secret files.
12. Restore into a separate Compose project/network, never over production. The restored CEO can authenticate; company/issue relationships and attachment checksum match; a bound environment probe records successful canary-secret resolution without returning plaintext; and health passes.
13. Logs and health checks make database-unavailable and migration/preflight failure states distinguishable.
14. No Hermes, OpenCode, Todoist, n8n, Redis, custom application, or metrics stack is introduced.

### Automated tests

- Compose render validation with placeholder secrets.
- Assertions that only approved ports are published and every stateful service has a persistent mount.
- Assertions that images are version/digest pinned and no `latest` appears.
- Secret-pattern and reachable-history scans, including classic, post-quantum, and plugin age identity prefixes, plus tests that external secret/data/backup paths and the documented Nix age identity path are ignored.
- Fixture tests require exact complete Tailscale state: valid Serve-only passes; Funnel permission, foreground Funnel, unexpected handler, unexpected port, unexpected target, and even a persisted false `AllowFunnel` entry fail.
- Bash syntax and ShellCheck for operator scripts, plus static consistency checks across Compose, the environment contract, loopback exposure, and ignore rules.
- Read-only migration preflight: accept an empty database and a migrated Paperclip database; reject a non-empty schema without the expected Drizzle journal before Paperclip starts.
- Fresh-bootstrap/recovery smoke: start from clean volumes, run official onboarding, validate `authenticated/private`, create a real user and claim the instance through the supported private API, disable signup, prove existing login, create a company/related issue/attachment/local-encrypted canary through supported APIs, resolve it through a bound environment probe, exercise `503 database_unreachable` and recovery, back up, restore with original external secrets into distinct fresh volumes, and verify authentication, values/relationships, attachment bytes, one new successful canary-resolution access event, and health.
- Encrypted configuration-pack smoke: create with an ephemeral age recipient, relocate it, restore under an isolated root, verify sidecar/internal checksums, byte equality, file modes, and reconstructed config without logging contents.

### Manual end-to-end verification

1. Deploy from a clean clone at a recorded commit, create/prove the `nix` operator, name the Tailscale node `nix-os`, and discover its real MagicDNS FQDN.
2. Configure the exclusive Tailscale Serve state and confirm tailnet access. From outside the VPS/tailnet, prove ports 80, 443, 3100, 5432, 8443, and 10000 do not expose Nix; attribute any pre-existing unrelated public listener explicitly. Also prove the Tailscale FQDN has no public Funnel endpoint on 443, 8443, or 10000.
3. Complete authenticated private signup and browser ownership claim, disable signup, prove new signup is rejected, and prove the existing CEO can sign in.
4. Create the Nix company, set a deliberately tiny initial budget, and add a disposable issue, known-byte attachment, and harmless encrypted-secret canary.
5. Run `docker compose down` without volume deletion, start again, and verify both objects.
6. Create and upload both the encrypted configuration pack and encrypted data backup, download them, then run the isolated restore with original external secret files.
7. Authenticate, verify company/issue relationship and attachment checksum, run the bound environment probe and verify one new successful canary access event without printing its value, verify health, and destroy the restore environment.
8. Record non-secret evidence and restore timestamp in a Paperclip Operations issue once the production company exists.

### Failure modes

- MagicDNS/Tailscale HTTPS not ready: stop at the surfaced admin consent action; keep Paperclip loopback-only rather than publish port 3100.
- Database unavailable/migration failed: Paperclip stays unhealthy and restart policy does not hide the root error.
- Missing secret: config check fails before deployment and names the missing secret, never its value.
- Backup upload failed: local backup remains with failure status; do not report success until off-host checksum is confirmed.
- Restore target collision: script exits before touching any existing volume/database.
- Disk full: health/backup fails visibly; retention never deletes the last known-good off-host backup.

### Deliberately deferred

Hermes, Telegram, OpenCode, GitHub App automation, `nix-brain`, Todoist, n8n, comprehensive monitoring, HA, automatic upgrades, and zero-downtime deployment.

### Tailnet amendment record — 2026-09-25

The reviewed foundation remediation was merged through PR #2; canonical `main` is `c6c56d521edec0451c073662c383605c9f769a41`. Branch protection is deliberately not a V0 requirement. The repository convention is feature branch, pull request, hosted `foundation` and `recovery` checks green, consequential review, then merge; agents do not intentionally push directly to `main`.

Lior clarified before deployment that Paperclip must be tailnet-only. The amendment removes Caddy, reduces Compose to Paperclip and PostgreSQL, binds Paperclip to host loopback, uses reconstructible Tailscale Serve HTTPS, and changes Paperclip to `authenticated/private` without weakening login. ADR 0005 preserves why ADR 0004 was superseded.

The production age identity was generated on Lior's Mac, not the VPS. Its private path is `~/.config/nix/age/identity.txt` (mode `0600`); its public recipient is `age15fxuw6eqj5sk9w9znpyxpqmkprzcpcfc60luaxg4auafu6ndhf8q0dagj0`. The private key is not in Git and must receive a second safe personal copy.

Repository validation covers Compose rendering, loopback-only Paperclip publishing, internal-only PostgreSQL, pinned images, private authenticated onboarding and browser claim, signup closure, migration guard/preflight, realistic encrypted backup/restore, configuration-pack round trip, ShellCheck, and CI workflow lint. Real Tailscale integration is intentionally not faked locally.

### Live acceptance record — 2026-09-25 through 2026-09-27

Status: **SLICE 0: ACCEPTED.** All repository and live acceptance gates passed; this record entered canonical `main` through the documented evidence-PR workflow with hosted CI green.

| Gate | Evidence | Status |
|---|---|---|
| GitHub baseline | Reviewed amendment PR #3 completed the documented feature-branch workflow; hosted `foundation` and `recovery` jobs were green before merge. Canonical/deployed `main` is `a6205378c70048c76a8ad15c73da3c6777e6404f`. | Passed |
| VPS prerequisites | Hostinger VPS runs Ubuntu 24.04.4 LTS, x86_64, kernel 6.8.0-134-generic, Docker Engine 29.6.1, Compose 5.3.1, Tailscale 1.102.2, rclone 1.75.1, age 1.1.1, jq 1.7, and Git 2.43.0. Preflight passed with approximately 70 GB free and 7.8 GiB RAM. | Passed |
| Operator | User `nix` owns `/opt/nix-os`, authenticates with the existing SSH key over `ssh nix@nix-os`, and passed non-interactive sudo, Docker, and repository-operation checks. Root/public-IP SSH remains available for recovery. | Passed |
| Tailnet identity and HTTPS | Node name is `nix-os`; MagicDNS resolves `nix-os.tailee691f.ts.net` to `100.82.50.51`. Tailnet HTTPS health passed. Certificate CN/SAN matches the FQDN, issuer is Let's Encrypt YE1, and validity is 2026-09-25 through 2026-12-24. | Passed |
| Serve/Funnel invariant | Final raw state is exactly `TCP.443.HTTPS=true` plus `/ -> http://127.0.0.1:3100` for `nix-os.tailee691f.ts.net:443`. The repository validator passed; no `AllowFunnel`, Funnel state, extra handler, port, or target exists. | Passed |
| Host/public exposure | Docker publishes Paperclip only as `127.0.0.1:3100`; PostgreSQL has no host publication. External probes found 443, 3100, 5432, 8443, and 10000 closed/filtered. Port 22 is the retained recovery SSH path. Port 80 is open only for a pre-existing unrelated nginx workload and does not route to Nix. Listener inspection attributes tailnet `:443` exclusively to `tailscaled`. | Passed |
| Paperclip bootstrap/auth | Production is healthy at pinned Paperclip `2026.916.1`, `authenticated/private`, bootstrap `ready`, with no active invite. Lior claimed CEO/admin, signed out/in, and a final authenticated production dashboard check succeeded. Signup returns `EMAIL_PASSWORD_SIGN_UP_DISABLED`; anonymous session and company API calls return 401 and 403 respectively. | Passed |
| Recovery fixtures | Company `45726d0d-f871-4391-8af8-f4b509bc51ba` (`RECOVERY CANARY - Slice 0 - 2026-09-26`) contains related issue `f919084c-c0b8-4c18-9adb-396637b321b0` (`REC-1`). Attachment `c35e7432-5621-4391-872c-a2ae05f12ed7` has SHA-256 `cf797f279b650e40f883fcd28830670b81a584642bc0616e8c1d2ebcb3173923`. Secret `6858a93f-5660-4753-b6d7-56e7176335fc` is `local_encrypted`; its plaintext was never logged. | Passed |
| Encrypted backups | Configuration artifact `nix-os-config-20260926T082005Z.tar.gz.age` SHA-256 is `7310f6b77507b01a94ce7ff6bbdcc12e74b80800dd0019be2fefa3e3063e6123`. State artifact `nix-os-nix-os-20260926T082015Z.tar.gz.age` SHA-256 is `26f957a692f1c59d009b2b7658386fa3e5f927c1135dff553eb1e9c7f74a6a87`. Both ciphertexts and checksum sidecars exist under `gdrive:Nix/backups/{config,state}`. | Passed |
| Off-host round trip | All four files were downloaded from Google Drive into a separate recovery directory. Sidecars verified on the VPS and Mac; the Mac-held identity decrypted both downloaded ciphertexts without printing contents. Google Drive contains ciphertext and sidecars only. | Passed |
| Isolated recovery | Downloaded artifacts restored into fresh project `nix-os-live-restore-20260926`. `/paperclip` hashes and database counts matched; the migration preflight passed with 211 tables and a Drizzle journal; PostgreSQL and Paperclip became healthy. Lior authenticated as restored CEO. Company/issue IDs and relationship matched; attachment bytes matched the recorded SHA-256. A restored-master-key SSH-environment probe added exactly one successful canary access event without outputting plaintext. | Passed |
| Recovery cleanup | The isolated containers, networks, and both fresh volumes were destroyed. Temporary plaintext config/state files were removed from the VPS and Mac. Production and encrypted local/off-host artifacts were retained. Production health, auth, migrations, volumes, Serve state, and non-exposure checks passed afterward at 2026-09-27T20:48:55Z. | Passed |
| Age custody | Private identity remains only at `~/.config/nix/age/identity.txt` on Lior's Mac with mode `0600`; the public recipient is `age15fxuw6eqj5sk9w9znpyxpqmkprzcpcfc60luaxg4auafu6ndhf8q0dagj0`. It was never copied to the VPS or Git. Lior confirmed a second safe personal copy on 2026-09-27. | Passed |

Current upstream constraints:

- Stable Paperclip remains `v2026.916.1`; image tag is `2026.916.1`. `authenticated/private` is supported for VPN/LAN and still requires authentication. It permits the first authenticated browser session to claim the instance.
- `/api/health` is database-backed and returns `503` with `database_unreachable` when PostgreSQL cannot be reached.
- Pinned Paperclip rejects a non-empty database missing the expected Drizzle journal before mutation. Nix's preflight gives a clearer earlier error on documented workflows but does not wrap every engine restart.
- `/paperclip` contains persistent uploads, instance configuration, and the encrypted-secret master key and must be backed up with PostgreSQL.
- Tailscale Serve `--bg` persists across daemon/host restarts and remains tailnet-only. `tailscale serve reset` clears prior node-level web-serving configuration; Nix validates the raw JSON after reset and after applying the exclusive route. Tailscale HTTPS may require admin web consent. Funnel is not used.
- rclone's shared Google OAuth client ID is being retired during 2026; live Google Drive setup should use Lior's own Desktop OAuth client. Its OAuth config is a runtime secret and may be recreated in recovery.

No Slice 0 prerequisites remain. The non-secret evidence update is merged through the documented PR workflow only after hosted `foundation` and `recovery` CI are green.

Slice 1 entry condition is satisfied. Stop here: Slice 1 still requires separate explicit authorization.

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

- Hermes service, internal `agent` network, persistent `/opt/data` volume, resource limits, and health check in Compose.
- `deploy/hermes/config.yaml` and `SOUL.md`: the default profile is Chief of Staff; multiplexing remains off.
- `HERMES_ENV_FILE` and read-only `NIX_BRAIN_HOST_PATH` configuration, plus safe secret initialization.
- Supported Paperclip `hermes_gateway` invite/approve/claim procedure and distinct credentials.
- Extended encrypted config/data backup, isolated Hermes volume restore, pinned-image/MCP/multiplex contracts, and live E2E checklist.
- ADR 0006 and deployment/recovery documentation.

### Exact acceptance criteria

1. One Hermes profile named/identified as Chief of Staff has isolated persistent state and starts under upstream-supported gateway supervision.
2. Telegram is handled by Hermes' native adapter. There is no custom Telegram receiver and Paperclip's Telegram connector is disabled.
3. Only Lior's allowlisted Telegram identity in the private direct chat is accepted; an unauthorized identity or any group chat receives no agent/tool access.
4. Hermes' Runs API is private to Compose and requires a unique `API_SERVER_KEY` even internally.
5. The Chief profile receives a separate revocable Paperclip agent key and can call the official `@paperclipai/mcp-server` at the internal Paperclip URL.
6. The MCP server/package is pinned; its exact allowlist permits identity, project/issue reads, issue create/update, and comment read/write, and excludes project/goal creation, approvals, arbitrary API escape hatch, connections, runtime control, and destructive tools.
7. A Telegram commitment creates exactly one Paperclip issue with useful title/body, source context, and Chief ownership or routing. Chief replies with the actual issue identifier only after the API succeeds.
8. A Telegram question or clarification exchange creates no issue unless Lior explicitly creates a commitment.
9. A request to create a new top-level project/goal is not executed; Chief asks for/records approval through the allowed conversational path.
10. The default profile topology remains compatible with the pinned release's future Telegram chat/thread-to-profile routing without enabling or creating later employees.
11. Restarting Hermes preserves the Chief profile and conversation continuity.
12. Chief can read the canonical `nix-brain` checkout through a read-only mount; it has no brain write credential.
13. Paperclip stores Chief as a real `hermes_gateway` agent using `http://hermes:8642`, issue-scoped Paperclip sessions, and the bounded same-host HTTP exception from ADR 0006.
14. No Todoist object is created; Todoist is not configured.

### Automated tests

- Config schema/static checks: no secret literals, API server not publicly published, allowlist required, MCP package pinned, dangerous tools absent.
- Pinned Paperclip MCP stdio discovery proves every allowlisted tool still exists; live acceptance exercises list/create/fetch/update/comment as Chief.
- Pinned Hermes image test proves `/health`, authenticated `/v1/capabilities`, unauthenticated rejection, official `grill-me` availability, and named-volume restart continuity.
- Pinned Hermes routing test proves representative Telegram chat/thread routes select future isolated profiles while production multiplexing remains disabled.
- Compose/static checks prove no Hermes host port, exact service/network boundaries, required user allowlist and DM-only chat gate, read-only brain mount, pinned images/packages, and dangerous MCP tools absent.
- Encrypted configuration round trip includes `hermes.env`; coordinated data recovery verifies byte-identical Hermes profile/memory/session/skill state. Real provider and Telegram recovery remain a live gate.

### Manual end-to-end verification

1. Create the one private Telegram bot, discover Lior's numeric ID, authorize only that ID, and complete `openai-codex` device authorization without exposing tokens.
2. Create or identify the already-approved `Nix Business OS V0` Paperclip project, onboard Chief through the supported `hermes_gateway` invite/approve/claim flow, and record the non-secret company/project/agent IDs.
3. Message Chief from Lior's account with `ping`; confirm a reply. Attempt from a non-allowlisted identity and verify silent denial without tool access.
4. Store a harmless continuity fact with supported Hermes memory, restart Hermes, and verify recall.
5. Ask what work exists; verify the response is retrieved from live Paperclip. Create `Slice 1 integration test` at low priority, verify its real project/identifier/status, add a harmless comment/update, then directly change it in Paperclip and prove Chief reads the current state rather than stale chat memory.
6. Restart the runtime and then reboot the VPS. Verify Paperclip, Hermes, Telegram, provider auth, brain read, and Paperclip access all return.
7. Create encrypted config/state backups, upload/download them through Google Drive, restore into fresh isolated volumes, and verify Chief identity, memory/session/skill files, API auth, Paperclip linkage, Telegram resume, and provider auth or the documented reauthorization path. Destroy only the isolated restore runtime.

### Failure modes

- Telegram works but Paperclip is down: Chief says recording failed, does not invent an ID, and a safe retry does not duplicate confirmed work.
- MCP package/API drift: startup/contract check fails with the incompatible version and route/tool name.
- Agent key revoked: Paperclip returns 401; Chief cannot mutate work and escalation names credential repair, not a model failure.
- Model/provider unavailable: Hermes reports failure while Paperclip remains healthy; no half-created commitment is claimed.
- Bot token conflict or duplicate polling process: Telegram reports the conflict; stop the extra gateway rather than adding a relay.
- Tool call proposes forbidden top-level project/goal: capability is absent and Chief asks Lior instead.

### Deliberately deferred

Paperclip-triggered issue execution lifecycle, Product/Growth/Operations, enabled Telegram topic multiplexing, brain PR writeback, OpenCode, Todoist, n8n, Project Inception, external communication, and spending tools.

### Repository implementation record — 2026-09-28

Implemented on `slice-1-chief-of-staff` for independent review; no production changes have been made.

- Pinned Hermes `v2026.9.14` image and Paperclip MCP `2026.916.1`.
- The Hermes image's 14-day npm release-age policy rejects this matching recent Paperclip package, so only that exact pinned `npx` invocation uses `--min-release-age=0`; the package tool contract is tested from the pinned image.
- Added only one new runtime service, `hermes`; the complete stack is Paperclip, PostgreSQL, and Hermes.
- The default Hermes profile is Chief of Staff, with Git-controlled config/SOUL, persistent `/opt/data`, native Telegram polling, `openai-codex`, one optional `grill-me` skill, read-only `nix-brain`, and a least-capability Paperclip MCP allowlist.
- Added an internal-only Paperclip/Hermes network and no host publication. The Runs API requires a separate generated key.
- Extended state backup format to version 2 and config-pack format to version 2 to include Hermes state and `hermes.env`.
- Local automated validation covers the pinned image/API/routing/skill contract and byte-identical Hermes state recovery. Telegram, provider OAuth, real Paperclip onboarding/project IDs, VPS reboot, and downloaded Google Drive recovery necessarily remain live acceptance after independent review.
- Pull request #5 was opened from the feature branch. Its initial Actions runs were rejected before any step started by the private-repository account spending gate. Lior then made `nix-os` public; `nix-brain` remains private. The hosted pull-request rerun at `42c5f9580b4125add70e9da70ee27e1b6d1d6055` passed `foundation` in 16 seconds and `recovery` in 5 minutes 4 seconds. Independent review and production deployment remain pending.

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

- Exercise the existing Slice 1 `hermes_gateway` configuration for Paperclip-triggered execution; do not create a second Chief identity or gateway.
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
2. Employees use feature branches and PRs, never intentionally push directly to `main`, and merge only after passing CI and required review.
3. Employees read from a known fetched commit and report that revision in evidence when consequential.
4. A Paperclip issue produces a focused branch/commit/PR with reciprocal links.
5. Roadmaps have a documented brain path; live checklists/status remain in Paperclip.
6. GitHub credential scope is limited to the required repositories and contents/PR operations; external communication/merge remains approval-gated.
7. Concurrent edits use separate branches/worktrees and surface merge conflicts; no last-writer overwrite.
8. A failed push leaves the Paperclip issue open/blocked and the local commit recoverable.

### Automated tests

- Brain schema/link/Markdown checks and a policy test rejecting obvious live task-state fields in roadmap documents.
- Git integration against a disposable repository or local bare remote: branch, commit, PR adapter contract/mocked GitHub boundary, conflict behavior.
- Process evidence that the employee used a feature branch and PR, hosted CI passed, consequential review occurred when required, and merge followed without an intentional direct push to `main`.
- Secret scan.

### Manual end-to-end verification

Give Operations a Paperclip issue to add one harmless glossary fact. Verify it reads current content, opens a linked feature-branch PR, waits for hosted CI and required review, merges through that process without intentionally pushing to `main`, and sees merged content after refresh.

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

Invalid model ID, CLI missing, permission prompt hang, dirty/shared workspace, test failure, GitHub auth failure, context/session resume against moved `cwd`, or an agent attempting to skip the required feature-branch/PR process. Preserve artifacts and block visibly.

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
2. n8n UI is authenticated; any public webhook requirement is designed and reviewed in Slice 7 rather than preinstalling Caddy in Slice 0.
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

Obtain independent review of pull request #5. If approved, merge and execute the Slice 1 deployment/live-acceptance section in `docs/runbooks/DEPLOY.md`, followed by the downloaded-artifact recovery proof in `docs/runbooks/RESTORE.md`. Do not begin Slice 2 until every live Slice 1 gate is evidenced and this status becomes `SLICE 1: ACCEPTED`.
