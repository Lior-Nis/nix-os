# Upstream compatibility snapshot

Last researched: **2026-09-24**. Slice 0 image manifests were resolved directly from their official registries. This is not permission to skip revalidation: at the start of each later implementation slice, confirm the selected stable release, read its migration notes, and record the exact image/package digest in deployment configuration.

Only official documentation and official repositories are authoritative for implementation. Search results, blog posts, and this summary are navigation aids.

## Dependency findings

| Dependency | Verified stable baseline | Supported surface Nix will use | V0 decision |
|---|---:|---|---|
| Paperclip | `v2026.916.1` (2026-09-21) | Official GHCR image, JSON API/OpenAPI, agent keys, issues/projects/goals/approvals, built-in adapters, PostgreSQL | Slice 0 pins `ghcr.io/paperclipai/paperclip:2026.916.1@sha256:a02ac35ac41df911af477422ea0e781cf41d2b2c600c66f0a5ac9d8c63f52c2c`. |
| Hermes Agent | `v2026.9.14` / `v0.21.3` (2026-09-14) | persistent isolated profiles, Telegram gateway, Runs API, MCP client, Docker gateway supervision | Conversational employees. One writer per profile; Paperclip calls the existing gateway rather than spawning a second Hermes process. |
| OpenCode | `v1.18.30` (2026-09-09) | non-interactive `opencode run --format json`; Paperclip's built-in `opencode_local` adapter resumes sessions | Coding harness. Keep model/provider configurable and validate the selected model with `opencode models`. |
| Todoist | API v1 | official REST API/SDK, opaque string IDs, cursor pagination, HMAC-signed webhooks with delivery IDs | Human-action projection only. Use API v1, not retired REST v2 examples. |
| n8n | `2.39.10` stable (2026-09-21); `2.40.x` was prerelease | Docker, PostgreSQL, webhook and deterministic workflow nodes | Add only with the Todoist slice. No queue mode, Redis, workers, or AI-agent workflows in V0. |
| PostgreSQL | `17.11-alpine3.24` | Paperclip external database; `pg_dump`/`pg_restore` | Slice 0 pins `postgres:17.11-alpine3.24@sha256:b0f9560a2de083e2cc7382e75f808c7381a32852a7ec49117deedb300e552b24`. |
| Caddy | `v2.11.4` | automatic TLS reverse proxy | Slice 0 pins `caddy:2.11.4-alpine@sha256:6aeddd44c3078b0f9a35206472a11420648a79c184603ef95957d0a20044cb2b`; it is the only public ingress. |
| Telegram Bot API | current HTTP Bot API | Hermes' native Telegram adapter; Telegram update identity and allowlists | Telegram terminates at Hermes, not a custom bot service and not Paperclip's experimental Telegram connector. |
| GitHub | current GitHub App API | least-privilege installation access, PRs, protected branches, webhooks only when needed | Canonical Git provider for `nix-os` and `nix-brain`. Prefer a GitHub App or Paperclip's supported GitHub connection over a broad PAT. |
| Docker Compose | current Compose specification | single-server production deployment, explicit secrets/volumes/networks | Initial Hostinger runtime. No orchestrator. |

## Evidence and version-sensitive assumptions

### Paperclip

- The current stable release is [Paperclip v2026.916.1](https://github.com/PaperclipAI/paperclip/releases/tag/v2026.916.1), commit `d554c4789ed3930f8a53ac9fdf6503b3187097da`. It is a no-migration patch over `v2026.916.0`.
- The official registry publishes the stable image tag without a leading `v`: `2026.916.1`. The `v2026.916.1` image reference does not exist. Both `2026.916.1` and `sha-d554c47` resolved to the pinned multi-architecture digest recorded above on 2026-09-24.
- The [API overview](https://docs.paperclip.ing/reference/api/overview/) documents bearer-authenticated board and agent identities, `GET /api/health`, and a runtime OpenAPI document at `GET /api/openapi.json`.
- The [Hermes Gateway adapter](https://docs.paperclip.ing/reference/adapters/hermes-gateway/) is built in. It calls `POST /v1/runs`, follows SSE events with polling fallback, stops timed-out runs, and supports issue-scoped sessions.
- The official [Hermes Gateway onboarding guide](https://github.com/PaperclipAI/paperclip/blob/master/doc/HERMES_GATEWAY_ONBOARDING.md) distinguishes the Hermes inference key, Hermes API-server key, and claimed Paperclip agent key. These must remain separate.
- The adapter currently declares `supportsLocalAgentJwt: false` in the [official source](https://github.com/PaperclipAI/paperclip/blob/master/packages/adapters/hermes/src/gateway/index.ts). Therefore an always-on Hermes profile needs its own revocable Paperclip agent key for Telegram-originated and gateway-originated Paperclip calls. Slice 2 must run the upstream gateway E2E smoke rather than assuming callback auth works.
- The official [Paperclip MCP server](https://github.com/PaperclipAI/paperclip/tree/master/packages/mcp-server) is a thin wrapper over the REST API and exposes issue read/write, questions, confirmations, approvals, projects, and goals. Nix will tool-allowlist it instead of building a bridge.
- The [OpenCode adapter](https://docs.paperclip.ing/reference/adapters/opencode/) runs `opencode run --format json`, supports provider/model selection, and resumes sessions when `cwd` matches.
- Paperclip uses PostgreSQL and supports a local Docker PostgreSQL mode in its [database documentation](https://docs.paperclip.ing/reference/deploy/database/). The single-VPS choice is ours; it is not a claim that a local database is more durable than managed PostgreSQL.
- The exact release's [Docker guide](https://github.com/PaperclipAI/paperclip/blob/v2026.916.1/doc/DOCKER.md) supports an external PostgreSQL 17 Compose stack, persists all non-database Paperclip state under `/paperclip`, and uses `PAPERCLIP_PUBLIC_URL` as the canonical auth/invite origin. Its official Docker onboarding smoke provisions configuration with `paperclipai onboard` before starting the server and then exercises real signup/bootstrap-invite acceptance.
- `paperclipai auth bootstrap-ceo` requires `/paperclip/instances/default/config.json`. In this release, the missing-config branch prints `Run paperclip onboard first` but returns exit status zero, so Nix verifies a real active invite through `GET /api/invites/:token` rather than trusting the command status.
- Non-interactive `onboard --yes` forces trusted loopback unless a private `--bind` preset is supplied; `--bind lan` in turn writes `authenticated/private`. The CLI has no non-interactive public preset. Nix therefore runs the official Quickstart onboarding path in a bounded pseudo-terminal so environment-aware defaults produce `authenticated/public`, external PostgreSQL, an explicit HTTPS public URL, local-disk storage, and local-encrypted secrets. It validates every resulting field before server startup.
- The official PostgreSQL image grants superuser status to `POSTGRES_USER`. Nix therefore keeps the image's `postgres` bootstrap administrator separate and creates the application-facing `paperclip` database owner with `NOSUPERUSER`, `NOCREATEDB`, and `NOCREATEROLE` during first initialization.
- Required Slice 0 variables are `DATABASE_URL`, `BETTER_AUTH_SECRET`, and `PAPERCLIP_TOOL_ACTION_SIGNING_SECRET`, plus the explicit deployment/public URL settings. `PAPERCLIP_HOME=/paperclip` is a persistent named volume. The tool-action secret has no fallback.
- On an empty external database, the server bootstraps the bundled Drizzle migrations. On an upgraded database, a non-interactive process applies pending migrations; Slice 0 makes this deliberate with `PAPERCLIP_MIGRATION_AUTO_APPLY=true` and always backs up before upgrade. In the pinned source, a non-empty PostgreSQL schema without the expected Drizzle migration journal enters the auto-migration path, is inspected, and is rejected before any migrations are applied. Nix keeps a separate read-only table/journal preflight as defense in depth: the documented deploy, upgrade, restart, and restore workflows fail earlier with a clearer operator error. A direct Compose startup or engine-managed container restart does not necessarily run the Nix preflight, but the pinned upstream guard still fails closed before mutation. Future releases still require migration-source review.
- Anonymous `GET /api/health` is intentionally redacted in authenticated mode, probes PostgreSQL with `SELECT 1`, returns HTTP 503 with `database_unreachable` when that probe fails, and reports `status: ok` only after startup recovery reaches ready.
- Internet exposure uses `authenticated/public`, which requires an external PostgreSQL URL and disables browser-first ownership claim. [ADR 0004](decisions/0004-paperclip-public-bootstrap.md) records the one-time CLI invite and post-bootstrap signup closure.
- The supported company, issue, attachment, secrets, and environment-probe routes are sufficient for realistic backup/restore fixtures. Attachment bytes live below `/paperclip`; their metadata and company/issue relationships live in PostgreSQL. Secret creation through the board API stores `local_encrypted` ciphertext, and normal reads expose metadata only. A board-authorized environment probe resolves a bound secret server-side and records a success access event without returning its value. Slice 0 uses that supported surface to prove restored ciphertext still decrypts with the restored master key without introducing an agent or logging plaintext.
- Paperclip [company exports](https://docs.paperclip.ing/how-to/back-up-and-restore-a-company/) deliberately omit approvals, cost events, activity history, secret values, and machine-specific state. They supplement rather than replace database and volume backups.

### Hermes Agent

- The current stable release is [Hermes Agent v2026.9.14](https://github.com/NousResearch/hermes-agent/releases/tag/v2026.9.14).
- [Profiles](https://hermes-agent.nousresearch.com/docs/user-guide/profiles) isolate configuration, secrets, memory, sessions, skills, and state. Upstream explicitly warns against two agent processes writing the same profile.
- The [messaging gateway](https://hermes-agent.nousresearch.com/docs/user-guide/messaging) natively supports Telegram and persistent sessions.
- The [programmatic API](https://hermes-agent.nousresearch.com/docs/developer-guide/programmatic-integration) provides authenticated Runs endpoints and SSE events used by Paperclip.
- [Multi-profile gateways](https://hermes-agent.nousresearch.com/docs/user-guide/multi-profile-gateways) can route a single listener to isolated profiles and enforce per-profile credentials. Topic-to-profile routing must be smoke-tested against the pinned release before expanding beyond Chief of Staff.
- Hermes' [MCP configuration](https://hermes-agent.nousresearch.com/docs/reference/mcp-config-reference) supports stdio servers, explicit tool filtering, and secret references such as `${env:PAPERCLIP_API_KEY}` resolved from the active profile's secret scope.

### Telegram

The [Telegram Bot API](https://core.telegram.org/bots/api) offers mutually exclusive polling and webhook delivery. Hermes owns this choice. The API documents `update_id` for deduplication and an optional webhook secret header; Nix must not add a second Telegram receiver.

### Todoist

The [Todoist developer platform](https://developer.todoist.com/) now presents one API, official SDKs/CLI/MCP, and webhooks. The [API v1 reference](https://developer.todoist.com/api/v1/) documents opaque string IDs, cursor pagination, JSON errors, webhook HMAC verification, and redelivery with the same delivery ID.

### n8n

- The stable tag on 2026-09-22 was [n8n 2.39.10](https://github.com/n8n-io/n8n/releases/tag/n8n%402.39.10).
- n8n supports PostgreSQL 17 and 18 (plus compatibility support for 16) in its [official database guide](https://github.com/n8n-io/n8n-docs/blob/main/docs/deploy/host-n8n/configure-n8n/choose-n8ns-database.md).
- n8n uses `N8N_ENCRYPTION_KEY` to protect stored credentials; the official [encryption-key guide](https://github.com/n8n-io/n8n-docs/blob/main/docs/deploy/host-n8n/configure-n8n/basic-configuration/configuration-examples/set-a-custom-encryption-key.md) makes that key part of the restore contract.

### Infrastructure

- Docker documents [single-server production Compose](https://docs.docker.com/compose/how-tos/production/) and [per-service Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/).
- PostgreSQL documents consistent logical exports with [`pg_dump`](https://www.postgresql.org/docs/17/app-pgdump.html) and stresses regular, verified backups in its [backup guide](https://www.postgresql.org/docs/17/backup.html).
- GitHub recommends minimum GitHub App permissions in [Choosing permissions for a GitHub App](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app).

## Known overlaps that are intentionally not used

- Paperclip now has experimental chat connectors, including Telegram. The locked architecture puts conversation in Hermes, so these stay disabled in V0.
- Paperclip and Hermes both contain task/kanban-like features. Paperclip alone is authoritative; Hermes-native kanban is not used for company work.
- Todoist offers MCP and a CLI. The V0 projection must be deterministic and policy-filtered, so n8n owns the eventual sync rather than giving every agent direct Todoist write access.
- Paperclip and n8n have broad plugin/connector ecosystems. V0 uses only integrations required by an accepted slice.
