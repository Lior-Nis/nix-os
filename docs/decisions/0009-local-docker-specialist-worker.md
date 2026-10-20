# ADR 0009: Use one hardened local Docker worker for V0 specialists

- Status: Accepted
- Date: 2026-10-19

## Context

Slice 3 needs task-scoped shell execution without giving broad company-control
credentials to the executor. A hosted sandbox subscription and a multi-layer
VM/container platform add cost and operations that V0 does not currently need.
Lior explicitly accepts the residual risk that a worker may escape ordinary
container isolation.

## Decision

- Run one reconstructible specialist worker container on the existing VPS.
- Use Paperclip's built-in SSH environment driver and native
  `paperclip_runner`; do not add a sandbox platform or custom runtime.
- Give Product, Growth, and Operations three environment rows and separate
  `/workspaces/<role>` roots on that one container. V0 uses one Unix worker
  identity, so these roots organize work but are not a security boundary.
  Each agent remains `per_turn` with one concurrent run.
- Keep the worker credential-poor: only the task-resolved OpenCode provider
  key enters a run. Lean V0 may reuse Hermes' model-only OpenCode Go key; it
  is not a company-control credential. Chief, Telegram, Paperclip-control,
  GitHub, Todoist, brain, host Docker socket, and host filesystem credentials
  are absent.
- Publish no SSH port. Paperclip reaches port 2222 on an internal Compose
  network with strict host-key checking. Native runner reconnects through the
  authenticated tailnet-only `wss://` Paperclip endpoint.
- Admit that reconnect path with one reconstructible, project-owned UFW rule
  from the worker's exact current IPv4 on its non-internal Compose egress
  network to the host's current Tailscale IPv4 on TCP 443. Validate that worker
  address against the owned private subnet, derive both sides from live state,
  verify HTTPS from the worker, and preserve unrelated firewall/Tailscale routes.
  Do not auto-enable inactive UFW; make no firewall mutation in that state and
  accept only when the same worker-side HTTPS probe succeeds.
- Use a read-only root filesystem, non-root SSH sessions, drop all container
  capabilities before adding only those OpenSSH needs, `no-new-privileges`,
  and explicit CPU, memory, and PID bounds. The named workspace volume is not
  quota-backed and persists role files between turns.

## Consequences

This is an agile V0 boundary, not hostile-code containment. A kernel or Docker
escape could reach the VPS failure domain, so the worker must never receive
broad control-plane credentials. The worker image and workspaces are
reconstructible; SSH keys and the OpenCode secret are encrypted backup state.
The accepted V0 tradeoff is that task-scoped model sessions are fresh, while
files in the shared worker volume are visible to the common Unix identity and
may persist between sequential jobs. Paperclip remains the task/context
authority; workers must not treat leftover files as authoritative input.
Introduce per-role identities plus per-run workspace cleanup (or stronger
isolation) before parallel specialist execution, multi-tenant use, untrusted
third-party code, or any worker credential expansion.
If measured risk or multi-tenant use later demands stronger isolation, the SSH
environment may move to an owned VM without changing Paperclip authority.
