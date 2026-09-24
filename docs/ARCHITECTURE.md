# Nix Business OS V0 architecture

Status: Slice 0 foundation implemented locally, 2026-09-24. No runtime has been deployed from this repository yet.

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
| GitHub | canonical Git history, pull requests, branch protection | company work graph |

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

The MCP tool allowlist in the first slices includes issue reads/writes but excludes creation of top-level goals/projects. That makes the V0 approval rule a capability boundary as well as an instruction.

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

Per [ADR 0001](decisions/0001-single-vps-compose.md), V0 runs on one Hostinger Linux VPS using Docker Compose. [ADR 0004](decisions/0004-paperclip-public-bootstrap.md) defines the authenticated Internet bootstrap boundary.

- Caddy publishes 80/443 and terminates TLS.
- Paperclip's UI/API is public only through Caddy, with Paperclip running in `authenticated/public` mode. Its container publishes no host port.
- PostgreSQL has no host-published port.
- Hermes Runs API and dashboard are private to the Compose network; Telegram access is outbound from Hermes.
- n8n is absent until its first required workflow. When added, only its signed webhook routes and authenticated UI are exposed.
- Containers run without privileged mode, Docker socket mounts, or host networking unless a documented upstream limitation and a new ADR require it.
- Health checks cover process readiness and dependency reachability, not just open ports.

The initial database is PostgreSQL 17 with a non-superuser Paperclip role. Later services receive separate roles/databases. Sharing one server reduces operations; database-level credentials and backups preserve separation. No Redis or worker queues are present.

## Configuration, state, and secrets

| Class | Examples | Location and recovery |
|---|---|---|
| Git-controlled configuration | Compose files, Caddyfile, redacted Hermes config/SOUL templates, policy text, tests, n8n workflow JSON after Slice 7 | GitHub `nix-os`; rebuildable from a commit |
| Runtime state | Paperclip PostgreSQL data, Paperclip uploads/config, Hermes `state.db`/sessions/memory, n8n database and storage, local worktrees/logs | named volumes/host state directory; restored from verified off-host backups |
| Durable company knowledge | `nix-brain` Markdown and Git history | separate private GitHub repository; local clones are disposable |
| Secrets | bot token, model keys, Hermes API keys, Paperclip agent keys, DB passwords, GitHub App key, Todoist token, n8n encryption key | root-owned files or an operator secret store outside the checkout; per-service injection; separately backed up encrypted |

Configuration portability is not state portability. A Compose file cannot restore an employee's memory, a work graph, credentials, or encryption keys.

## Minimum backup and restore contract

Slice 0 establishes the procedure; later slices extend its manifest.

| State | Backup | Restore proof |
|---|---|---|
| Paperclip database | nightly compressed logical dump, encrypted and copied off-host | restore to an isolated database; `/api/health` and sampled company/issue counts match |
| Paperclip home/storage | encrypted file backup coordinated with the database backup | attachments/config readable; secret master key present |
| Paperclip portable company bundle | periodic export including company, agents, projects, skills, issues | preview/import to a disposable company |
| Hermes profile state | quiesced volume snapshot or stop-the-gateway file backup | profile starts; Telegram allowlist, memory, and a sample session survive |
| `nix-brain` and source repos | GitHub remote plus protected branches | fresh clone and CI pass |
| n8n (when added) | its database, storage volume, workflow exports, and `N8N_ENCRYPTION_KEY` | credentials decrypt and Todoist test workflow runs |

The Paperclip portable bundle is not a full backup because upstream excludes approvals and activity/cost history. Database restore remains required. At least monthly, restore the whole stack into an isolated Compose project and record the result in a Paperclip Operations issue.

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
