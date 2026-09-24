# ADR 0001: Start with one VPS and Docker Compose

- Status: Accepted
- Date: 2026-09-22

## Context

V0 needs a portable, inexpensive, observable runtime on a Hostinger VPS. The workload is one company, four conversational Hermes employees, one OpenCode engineer, and low initial concurrency. High availability and elastic scaling are not requirements.

## Decision

Run V0 on one Linux VPS with Docker Compose.

- Caddy is the only public ingress on ports 80/443.
- Paperclip, Hermes, PostgreSQL, and later n8n communicate on private Compose networks.
- Use PostgreSQL 17 with separate database roles and databases for Paperclip and n8n.
- Use named volumes or explicit host directories for state, never container layers.
- Pin stable image versions and immutable digests in the production lock/configuration.
- Back up critical state off-host and test restore before a stateful slice is complete.

## Consequences

This has a single-host failure domain and brief downtime during host maintenance. That is acceptable in V0. Compose configuration is portable, but state portability depends on database dumps, volume backups, encryption keys, and restore tests.

Do not add Redis, n8n queue workers, Kubernetes, distributed runners, or an external observability stack. Revisit only after measured resource contention or recovery requirements justify them.
