# ADR 0006: Keep Hermes gateway traffic on a dedicated internal Compose network

- Status: Accepted
- Date: 2026-09-28

## Context

Slice 1 adds one persistent Hermes gateway that receives Telegram updates by outbound polling and exposes an authenticated Runs API for Paperclip. Paperclip's built-in `hermes_gateway` adapter must reach that API. In one-host Docker Compose, the supported address is `http://hermes:8642`; Paperclip v2026.916.1 rejects non-loopback cleartext HTTP unless `dangerouslyAllowInsecureRemoteHttp` is explicitly enabled.

Publishing Hermes on the VPS loopback or tailnet would widen the boundary without helping Telegram or Paperclip. Adding TLS between two same-host containers would add certificate/proxy machinery solely for this hop.

## Decision

- Add an internal Compose network named `agent`, attached only to Paperclip and Hermes.
- Do not publish the Hermes Runs API or dashboard on any host interface.
- Require a distinct 256-bit `API_SERVER_KEY` on the Runs API even on the internal network.
- Configure the Chief of Staff Paperclip agent with `apiBaseUrl: http://hermes:8642`, `paperclipApiUrl: http://paperclip:3100`, `sessionKeyStrategy: issue`, and `dangerouslyAllowInsecureRemoteHttp: true`.
- Hermes reaches Paperclip with a separate claimed Paperclip agent key through the official MCP server. PostgreSQL remains isolated on the separate `data` network.
- Telegram terminates only at Hermes through outbound Bot API polling. Paperclip's experimental Telegram connector remains disabled.

## Consequences

The insecure-HTTP escape hatch is narrowly scoped to a non-published, same-host Docker bridge, while application authentication remains mandatory. Anyone with control of the Docker host is already inside the accepted V0 failure boundary. The setting must not be reused for a LAN, tailnet, or Internet URL. If Hermes moves off-host, use authenticated HTTPS and revisit this decision.

The default Hermes profile is the Chief of Staff in Slice 1. The pinned release's supported multiplexer can later add isolated profiles and Telegram topic routes without adding another Telegram ingress, but multiplexing stays disabled until the employee-expansion slice.
