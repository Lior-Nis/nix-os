# Architecture

## Purpose

Nix is a six-human portfolio organization supported by seven role-isolated Hermes profiles. Human authority remains with Lior and the relevant human owners; profiles coordinate and execute bounded work but do not manufacture authority.

## Topology

```text
Lior ⇄ Discord ⇄ LNX/default
                     ├── Pulse Lead ───────── Pulse board
                     ├── Algua Lead ───────── Algua board
                     └── MeaBeclick Lead ──── MeaBeclick board
                              ├── UX Specialist
                              ├── Engineering Specialist
                              └── Growth Specialist
```

LNX is the portfolio front door and the only initially exposed messaging identity. Leads own project decomposition and synthesis. Specialists operate only inside their stated duties and return evidence to the MeaBeclick Lead.

## Planes and sources of truth

### Human communication plane

Discord carries requests, alerts, decision prompts, and live voice. It is not the canonical task ledger or evidence store. Internal profiles do not need platform accounts.

### Personal commitment plane

Todoist, through `td`, contains only commitments assigned to Lior. A lead must not mirror delegated cards into Todoist. When Lior must act, the orchestrator may create or request one clearly worded personal task.

### Delegated execution plane

Hermes Kanban is the durable work queue. Each project has one board and one persistent lead. Cards carry scope, assignee, dependencies, status, and completion evidence. Specialists communicate through board handoffs rather than extra messaging bots.

### Evidence plane

GitHub is canonical for code, issues, reviews, and CI. Project documents are canonical for approved decisions, operating notes, and deliverables that do not belong in source control. A chat claim is not durable evidence.

## Control flow

1. Lior sends a request to LNX.
2. LNX decides whether it is a personal commitment, a direct answer, or delegated work.
3. Delegated work is routed to the correct project board and lead.
4. A lead decomposes work and assigns a specialist only when the specialist contract fits.
5. Workers attach verifiable artifacts or references and identify blockers.
6. The lead synthesizes; LNX escalates decisions or reports outcomes to Lior.

## Deliberate non-goals

The initial system has no external workflow engine, second team-chat plane, bespoke multi-agent runtime, or messaging bot for every internal role. Profiles and Kanban supply the required isolation and durable coordination.

## Trust boundary

Profiles isolate Hermes state but are not OS sandboxes. Role contracts constrain behavior; filesystem and credential isolation must be enforced by local deployment controls. Sensitive data must never enter Kanban card bodies, role files, this manifest, or source control.
