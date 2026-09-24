# ADR 0002: Integrate persistent Hermes through supported gateways

- Status: Accepted
- Date: 2026-09-22

## Context

Each employee needs one persistent Hermes identity reachable from Telegram and callable by Paperclip. Hermes warns that two agent processes writing one profile corrupt its state. Paperclip offers both `hermes_local`, which spawns a CLI process, and `hermes_gateway`, which calls an already-running Hermes Runs API.

## Decision

- Telegram terminates at Hermes' native gateway.
- Paperclip invokes that same persistent employee through its built-in `hermes_gateway` adapter.
- Hermes calls Paperclip through the official `@paperclipai/mcp-server` and a distinct, revocable Paperclip agent key.
- Paperclip-to-Hermes uses a separate Hermes `API_SERVER_KEY` stored as a Paperclip secret reference.
- Paperclip sessions use `sessionKeyStrategy: issue` so task context does not bleed across issues.
- Do not run `hermes_local` against a profile whose messaging gateway is active.
- Do not build a Telegram relay, custom agent runtime, or custom Paperclip client service.

Slice 1 starts with one Chief of Staff profile. Slice 3 may enable Hermes' supported profile multiplexer for Telegram topic routing only after proving the pinned release routes both Telegram sessions and prefixed Runs API calls correctly. If that test fails, use upstream-supported independently supervised profile gateways; do not patch around it with a custom router.

## Consequences

There are three distinct credential classes: model/provider credentials, Hermes API-server credentials, and Paperclip agent credentials. Rotation and diagnostics must preserve that distinction. A long-lived Paperclip agent key is necessary for Telegram-originated calls because the gateway adapter does not currently transport Paperclip's per-run local-agent JWT.
