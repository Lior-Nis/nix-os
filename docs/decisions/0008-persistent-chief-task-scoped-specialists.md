# ADR 0008: Keep only Chief persistent and run specialists task-scoped

- Status: Accepted
- Date: 2026-10-16
- Supersedes in part: ADR 0002 and ADR 0006 clauses that planned persistent Product, Growth, and Operations Hermes profiles or Telegram topic routes

## Context

V0 needs one durable human conversation and decision interface, but Product, Growth, and Operations work begins from bounded Paperclip issues. Keeping every role continuously resident would add profile state, credentials, Telegram routing, backup surface, and cross-profile isolation work before a demonstrated need. It would also give long-lived control-plane identities more opportunity to accumulate broad company credentials.

Paperclip remains the authoritative work graph. Telegram is only Lior's conversation, grilling, and decision interface through Chief. A specialist can request a founder decision by blocking its Paperclip issue; Chief carries the question to Telegram, records Lior's answer back in Paperclip, and resumes the originating work.

## Decision

- Chief of Staff is the only persistent Hermes profile and the only human-facing Telegram employee in initial V0.
- Product, Growth, and Operations are task-scoped Paperclip worker identities. Growth owns both marketing and sales.
- A specialist receives fresh bounded context and role-scoped tools for one assigned issue, records attributable evidence/status in Paperclip, and terminates. It has no persistent Telegram conversation or Chief memory access.
- The exact task runtime/adapter is chosen from supported upstream Paperclip surfaces during the worker slice after version revalidation. Do not build a custom agent runtime or router.
- Task-scoped execution credentials must not include Chief's broad company-control credential. Workers may receive shell/browser/computer-use only when their task requires it and only with task-scoped credentials.
- Consequential ambiguity follows `specialist -> Paperclip -> Chief -> Telegram -> Lior -> Paperclip -> originating specialist`. No specialist silently invents founder policy.
- Hermes profile multiplexing and specialist Telegram routes remain disabled unless a later demonstrated requirement is accepted in a superseding ADR.

## Consequences

The initial operating system has less persistent state, fewer long-lived credentials, and one clear human entry point. Specialists may have higher cold-start cost and must reconstruct context from Paperclip and approved durable knowledge. That is acceptable in V0 and makes task isolation, recovery, and privilege review simpler. If a role later demonstrates a need for persistent conversational memory, that change requires an explicit architecture decision and renewed credential/tool-boundary review.
