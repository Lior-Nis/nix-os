# ADR 0003: Keep work, knowledge, and human actions in separate authorities

- Status: Accepted
- Date: 2026-09-22

## Context

Paperclip, Git, Telegram, and Todoist all can appear to hold tasks or decisions. Allowing multiple writable authorities would create drift and reconciliation infrastructure.

## Decision

- Paperclip owns goals, projects, issues, assignments, approvals, blockers, and live execution status.
- `nix-brain` owns durable knowledge and approved roadmaps. Updates arrive through pull requests.
- Telegram carries the human conversation. Consequential answers are linked or summarized back to the relevant Paperclip issue and, when durable, to a brain PR.
- Todoist is a lossy, rebuildable projection of Paperclip items that require physical or otherwise human-only execution by Lior.
- n8n performs deterministic projections and callbacks. It does not decide what work should exist.

No bidirectional generic synchronization layer will be built. Each integration has an explicit owner and narrow mapping.

## Consequences

Deleting a Todoist projection must not delete the Paperclip source. A roadmap merge does not itself create live execution state until Lior approves the top-level Paperclip project. Chat history is not durable knowledge merely because it exists.
