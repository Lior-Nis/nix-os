# ADR 0007: Separate control-plane credentials from generic execution

- Status: Accepted
- Date: 2026-10-01

## Context

A persistent employee needs a long-lived Paperclip credential for Telegram-originated work. If that same profile has terminal, process, code, browser, or arbitrary network execution, it can bypass its Paperclip MCP allowlist and use the credential against broader REST operations.

## Decision

- A persistent control-plane employee that holds a privileged company credential receives only the narrow tools required for its role.
- Slice 1 Chief of Staff uses explicit restrictive toolsets for CLI, Telegram, and API-server lanes. Its only Paperclip write path is the allowlisted official Paperclip MCP.
- Generic execution capabilities and broad control-plane credentials must not coexist in one profile or sandbox.
- Future execution workers may receive terminal, browser, or computer-use capabilities, but must use separate identities and credentials that do not grant broad control-plane authority.

## Consequences

The Chief cannot directly perform arbitrary shell or web execution. It delegates future execution through auditable Paperclip work to separately isolated workers. Every Hermes upgrade must revalidate resolved concrete tools for all production invocation lanes so an upstream preset change cannot silently reopen the boundary.
