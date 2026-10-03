# Nix Business OS V0 architecture

Status: Slice 0 is accepted in production. Slice 1 Chief of Staff integration is implemented for review as of 2026-09-28 and is not yet deployed.

## Purpose and scope

Nix coordinates a one-person company by composing existing products. Lior sets direction and performs only high-return human work. Agents execute within approved goals, expose their work in Paperclip, and turn durable learning into reviewed changes to `nix-brain`.

V0 is deliberately a single-company, single-operator system. It is not a general agent platform.

## System topology

```text
Lior
├── ChatGPT (strategy and research outside the execution loop)
└── Telegram (conversation, grilling, decisions)
      └── Hermes gateway
          ├── Chief of Staff profile
          ├── Product profile
          ├── Growth profile (marketing + sales)
          └── Operations profile
                    │ official Paperclip MCP/API
                    ▼
                Paperclip
          authoritative work graph
              │        │        │
              │        │        └── human-action projection ── n8n ── Todoist
              │        └── opencode_local ── OpenCode Engineer ── GitHub PR
              └── hermes_gateway ── persistent employee execution

nix-brain: separate Git repository for durable knowledge and roadmaps
GitHub: canonical Git provider and PR review boundary
Hostinger VPS + Docker Compose: initial runtime
PostgreSQL: Paperclip state; later a separate n8n database
```

There is no Engineering Manager in V0. The OpenCode-backed Engineer is a Paperclip agent/runtime identity, not a Hermes manager profile. Growth owns marketing and sales.

## Component responsibilities

| Component | Owns | Must not own |
|---|---|---|
| Paperclip | company goals, projects, issues, hierarchy, assignments, status, blockers, approvals, execution history | durable knowledge corpus, casual chat, duplicate task truth |
| Telegram + Hermes | direct conversation, clarification, grilling, decisions, employee persona and working memory | authoritative task state, roadmaps, human reminders |
| Hermes profiles | isolated employee identity, memory, sessions, tools, Telegram context | shared company truth or another employee's credentials |
| OpenCode | repository-local engineering execution and verification | company prioritization or project approval |
| `nix-brain` | reviewed durable facts, policies, decisions, playbooks, roadmaps | live issue status or transient research notes |
| Todoist | concrete tasks only Lior can personally perform | questions, approvals, agent work, project backlog |
| n8n | deterministic event plumbing, validation, retries, narrow projections | agent reasoning, planning, authoritative business state |
| GitHub | canonical Git history, pull requests, and hosted CI | company work graph |

## Identity mapping

Each persistent employee has exactly one Hermes profile and one Paperclip agent identity.

| Employee | Hermes | Paperclip adapter | Telegram |
|---|---|---|---|
| Chief of Staff | persistent isolated profile | `hermes_gateway` | Chief topic/context |
| Product | persistent isolated profile | `hermes_gateway` | Product topic/context |
| Growth | persistent isolated profile | `hermes_gateway` | Growth topic/context |
| Operations | persistent isolated profile | `hermes_gateway` | Operations topic/context |
| Engineer | none | `opencode_local` | reached through the assigning employee/Paperclip issue |

Temporary research subagents are children of the requesting Hermes employee. They receive a bounded question and fresh conversational context. They are not persistent employees. Their work may remain inside the parent Paperclip issue; create a child issue when the result needs an independent owner, lifecycle, review, or cross-employee handoff.

## Core flows

### Conversation to committed work

1. Lior speaks in an employee's Telegram context.
2. Hermes clarifies conversationally when needed. A question is not a task.
3. When the exchange creates a commitment, Hermes uses the official Paperclip MCP tool to create or update an issue.
4. Hermes replies with the Paperclip identifier and a concise statement of the commitment.
5. Paperclip becomes authoritative immediately; Telegram is not later reconciled as a backlog.

The Slice 1 Chief profile has explicit, identical `cli`, `telegram`, and `api_server` toolsets containing only file access, memory, session search, and the bounded Paperclip MCP. Mutable skill-management tools, terminal, process management, code execution, browser/web/connectors, cron, delegation, and computer-use are disabled. Generic file writes and patches are confined by the pinned runtime's `HERMES_WRITE_SAFE_ROOT` guard to `/opt/data/memories`; credential files remain unreadable, broad search omits them, `nix-brain` is mounted read-only, and symlink escapes fail closed. The MCP allowlist includes issue reads/writes but excludes creation of top-level goals/projects and administrative mutations. Because the profile has no generic execution or raw network tool, this is an enforced credential boundary rather than prompt-only policy.

Per [ADR 0007](decisions/0007-separate-control-plane-credentials-from-execution.md), a control-plane employee may hold a privileged company credential only with a narrow tool surface. Future execution workers may receive terminal/browser/computer-use as required, but must not inherit the employee's broad control-plane credential. No execution worker is introduced in Slice 1.

### Paperclip to employee execution

1. An issue is assigned to a Hermes-backed Paperclip agent.
2. Paperclip's built-in `hermes_gateway` adapter creates an idempotently correlated Hermes run and observes SSE, with polling fallback.
3. Hermes uses issue-scoped session identity and the official Paperclip MCP/API to read context, add progress, create permitted child work, and report the result.
4. The issue status and comments in Paperclip are the execution record.

Paperclip-to-Hermes and Hermes-to-Paperclip credentials are different. They are never included in prompts or comments.

### Cross-employee delegation

- A substantive handoff creates or reassigns a Paperclip issue, normally a child of the initiating work.
- The receiving employee wakes from Paperclip, not from an invisible agent-to-agent chat.
- A quick factual lookup by a temporary subagent within the same employee run does not require a separate work item unless separately trackable.

### Durable learning

1. An employee discovers a reusable fact, policy, decision, or playbook change while executing Paperclip work.
2. The employee branches from current `nix-brain`, makes a focused change, and opens a GitHub pull request linked to the Paperclip issue.
3. CI checks structure, links, and policy constraints.
4. Lior or an explicitly authorized reviewer approves/merges. Agents do not silently overwrite durable knowledge on the default branch.
5. Roadmaps live in the brain; task decomposition and status live in Paperclip.

### Human action projection

A Paperclip item is eligible for Todoist only when all of these are true:

- Lior is the required executor, not merely approver or answerer.
- The action cannot reasonably be completed by an agent with existing access.
- It has a concrete verb and observable completion condition.
- It is marked with the explicit human-action policy marker defined in Slice 7.

Clarification questions, approval requests, choices, status notifications, and agent tasks are ineligible. n8n mirrors eligible items and their completion state; it does not infer eligibility with an LLM.

## Project Inception contract

Project Inception is an operating sequence, not a new service:

1. **Challenge:** the closest employee tests the proposal, scope, constraints, and expected value.
2. **Research:** that employee uses bounded temporary subagents when useful.
3. **Grilling:** consequential ambiguities are asked directly in the employee's Telegram context; no Todoist tasks are created.
4. **Roadmap:** the employee drafts the roadmap in `nix-brain`, separating outcomes from live tasks.
5. **Brain PR:** the roadmap and durable discoveries are reviewed through GitHub.
6. **Approval:** Lior explicitly approves the new top-level project/goal.
7. **Paperclip project:** only after approval, create the project/goal and executable issue tree in Paperclip.

Subordinate work inside that approved boundary may be created and executed autonomously.

## Approval policy

| Action | V0 behavior |
|---|---|
| Create subordinate issue inside approved scope | autonomous |
| Research, code, test, draft brain PR | autonomous |
| Ask Lior for clarification | Telegram conversation; not Todoist |
| Create a new top-level project/goal | explicit Lior approval before creation |
| Merge a `nix-brain` or product PR | approval required initially |
| Send external communication | draft autonomously; approval before send |
| Meaningful spend or new paid commitment | approval before purchase/commitment |
| Destructive production action | approval immediately before action |
| Major irreversible decision | approval before execution |
| Routine reversible execution | autonomous and logged |

Approval is kept as close as possible to the actual side effect. A vague earlier approval does not authorize a materially different action.

## Deployment and network model

Per [ADR 0001](decisions/0001-single-vps-compose.md), V0 runs on one Hostinger Linux VPS using Docker Compose. [ADR 0005](decisions/0005-tailnet-private-ingress.md) supersedes the unshipped public-Caddy design.

- Tailscale runs on the host. Its machine name is `nix-os`; MagicDNS supplies the actual `nix-os.<tailnet>.ts.net` name.
- Nix owns the node's TCP `443` HTTPS listener, the `/` handler at `nix-os.<tailnet>.ts.net:443`, and the requirement that this endpoint have no Funnel entry. Configuration updates that root handler in place and requires it to proxy to the Paperclip loopback target. Sibling paths on the same web host and all other ports, non-colliding foreground sessions, Services, and Funnel routes remain independently owned; Nix preserves and does not validate their application policy.
- Paperclip runs in `authenticated/private` mode. Tailnet membership limits reachability, while Paperclip login remains mandatory.
- Paperclip listens on `0.0.0.0:3100` inside its isolated container namespace so Docker forwarding works. Docker publishes that container port only on VPS host `127.0.0.1`; it is not directly reachable through the public or tailnet host interfaces. Tailscale Serve is the intentional tailnet-to-loopback path.
- Paperclip has a non-internal Compose network for required outbound access and a separate internal data network; neither publishes ingress.
- PostgreSQL has no host-published port.
- Hermes Runs API and dashboard are private to the Compose network; Telegram access is outbound from Hermes.
- Slice 1 runs one official Hermes container using its default profile as Chief of Staff. `/opt/data` is a named volume; Git supplies the read-only SOUL/config, and a clean `nix-brain` clone is mounted read-only at `/workspace/nix-brain`.
- Hermes and Paperclip share only the internal `agent` network. Paperclip calls `http://hermes:8642` with a dedicated API key; Hermes calls `http://paperclip:3100` through the pinned official MCP server with a different claimed agent key. The supported `PAPERCLIP_ALLOWED_HOSTNAMES=paperclip` setting admits that service hostname through Paperclip's private-host guard; Docker's internal network remains the reachability boundary. Neither internal endpoint is host-published. See [ADR 0006](decisions/0006-private-hermes-gateway-network.md).
- n8n is absent until its first required workflow. When added, only its signed webhook routes and authenticated UI are exposed.
- Containers run without privileged mode, Docker socket mounts, or host networking unless a documented upstream limitation and a new ADR require it.
- Health checks cover process readiness and dependency reachability, not just open ports.

The initial database is PostgreSQL 17 with a non-superuser Paperclip role. Later services receive separate roles/databases. Sharing one server reduces operations; database-level credentials and backups preserve separation. No Redis or worker queues are present.

A fresh Paperclip volume is initialized with the pinned release's official `paperclipai onboard` path before the long-running server starts. Nix validates the resulting instance configuration as external-PostgreSQL `authenticated/private` with the explicit Tailscale HTTPS base URL. Lior creates an authenticated browser session and uses Paperclip's supported private-instance ownership claim; signup is then disabled and a subsequent CEO login is verified. The verified CLI bootstrap invite remains a fallback.

## Configuration, state, and secrets

| Class | Examples | Location and recovery |
|---|---|---|
| Git-controlled configuration | Compose files, Tailscale Serve reconstruction command, redacted Hermes config/SOUL templates, policy text, tests, n8n workflow JSON after Slice 7 | GitHub `nix-os`; rebuildable from a commit |
| External deployment configuration | deployment `.env`, PostgreSQL/Paperclip env files, and Hermes env file containing the Telegram token/allowlist plus Runs API key | separate age-encrypted configuration pack, restored to recorded paths with mode `0600` and verified checksums |
| Runtime state | Paperclip PostgreSQL data, Paperclip uploads/config, Hermes provider OAuth/profile memory/sessions/gateway state, n8n database and storage, local worktrees/logs | named volumes/host state directory; restored from verified off-host backups |
| Durable company knowledge | `nix-brain` Markdown and Git history | separate private GitHub repository; local clones are disposable |
| Secrets | bot token, model credentials, Hermes API keys, Paperclip agent keys, DB passwords, GitHub App key, Todoist token, n8n encryption key | root-owned external files or the relevant encrypted persistent service state outside the checkout; per-service injection; separately backed up encrypted |

Configuration portability is not state portability. A Compose file cannot restore an employee's memory, a work graph, credentials, or encryption keys.

## Minimum backup and restore contract

Slice 0 establishes the procedure; later slices extend its manifest.

| State | Backup | Restore proof |
|---|---|---|
| External Slice 0 configuration/secrets | age-encrypted config pack after every change | restore `.env`, `postgres.env`, and `paperclip.env` with mode `0600`; internal and external checksums pass without logging contents |
| Paperclip database | nightly compressed logical dump, encrypted and copied off-host | restore to an isolated database; CEO authenticates and real company/issue values and relationships match |
| Paperclip home/storage | encrypted file backup coordinated with the database backup | attachment bytes match a known SHA-256; config and encrypted-secret master key are preserved |
| Paperclip portable company bundle | periodic export including company, agents, projects, skills, issues | preview/import to a disposable company |
| Hermes profile state | stop Hermes, archive the complete `/opt/data` volume with the coordinated Paperclip backup | restored Hermes boots with Telegram disabled, rejects unauthenticated API access, accepts the restored API key, loads the exact restricted tool surface and profile state, and resolves its claimed identity through bounded Paperclip MCP; live Telegram/provider operation is rechecked only after the isolated restore is destroyed |
| `nix-os` source | public GitHub repository plus feature-branch/PR/green-CI convention | fresh clone and CI pass; secrets and runtime state remain excluded |
| `nix-brain` | separate private GitHub repository | fresh authenticated clone and knowledge checks pass |
| n8n (when added) | its database, storage volume, workflow exports, and `N8N_ENCRYPTION_KEY` | credentials decrypt and Todoist test workflow runs |

The Paperclip portable bundle is not a full backup because upstream excludes approvals and activity/cost history. Database restore remains required. At least monthly, restore a downloaded off-host data artifact together with the original external configuration pack into an isolated Compose project. Verify CEO authentication, a company/issue relationship, attachment bytes, health, and a harmless encrypted-secret canary through a bound environment probe whose access event reports successful resolution without exposing its value; then record non-secret evidence in a Paperclip Operations issue.

Target initial objectives: daily recovery point (RPO <= 24 hours) and same-day manual recovery (RTO <= 8 hours). These are operating targets, not an HA promise.

## Observability

V0 uses what the composed tools already expose:

- structured container logs with service, correlation/run/issue identifiers where available;
- Docker health status and Paperclip `/api/health`;
- Paperclip run transcripts, activity, approvals, and issue comments;
- Hermes gateway/profile logs and run IDs;
- n8n execution history when installed;
- GitHub checks and PR history.

Secrets and message bodies are not copied into an extra log platform. A lightweight external uptime check may be added in Slice 0; a metrics stack is deferred.

## Graceful failure rules

- If Paperclip is unavailable, Hermes may continue conversation but must say that commitment recording failed and retry safely; it must not claim work was recorded.
- If Hermes is unavailable, Paperclip retains the issue and visible failed/timed-out run for retry.
- If GitHub is unavailable, keep the Paperclip issue open/blocked and preserve the local branch; do not treat unpushed files as durable knowledge.
- If Todoist projection fails, Paperclip remains authoritative and n8n retries idempotently.
- If a human approval or consequential clarification is missing, block the relevant Paperclip issue and ask in Telegram. Do not manufacture a Todoist question.
- Semantic contradictions in `nix-brain` produce findings/PR discussion, never an automatic winner.

## Explicitly out of V0

No custom agent runtime, task manager, knowledge database, skill package manager, dashboard, Kubernetes, generic plugin framework, formal skill eval system, sophisticated cost accounting, Jev, CRM/GTM stack, browser farm, multi-provider abstraction layer, multi-region failover, or speculative event bus.
