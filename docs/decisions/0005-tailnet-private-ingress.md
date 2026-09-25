# ADR 0005: Use tailnet-only Tailscale Serve ingress

- Status: Accepted
- Date: 2026-09-25
- Supersedes: [ADR 0004](0004-paperclip-public-bootstrap.md) and the public-ingress clause of [ADR 0001](0001-single-vps-compose.md)

## Context

ADR 0004 assumed that Lior needed Paperclip on a public Internet hostname. Before production deployment, Lior clarified that every intended client is a device on his Tailscale tailnet. Keeping Caddy and a public endpoint would add attack surface and operations without serving a V0 requirement.

Paperclip v2026.916.1 explicitly defines `authenticated/private` for VPN/LAN use. Private describes network exposure; it does not disable human authentication. Tailscale Serve can terminate tailnet HTTPS and proxy to a loopback-only service while tailnet access-control policy remains in force.

## Decision

- The VPS Tailscale machine name is `nix-os`; its actual MagicDNS FQDN is discovered from the connected tailnet rather than guessed.
- Tailscale Serve provides HTTPS only inside the tailnet and proxies to Paperclip on `127.0.0.1:3100` by default. Funnel is not configured.
- Compose binds Paperclip's host port only to `127.0.0.1`. PostgreSQL publishes no host port. Caddy is absent from the V0 runtime.
- Paperclip runs as `authenticated/private` with its explicit base URL set to the Tailscale HTTPS FQDN. Login remains mandatory.
- A fresh private instance uses Paperclip's supported browser ownership claim after signup. Signup is disabled immediately after Lior becomes CEO and a subsequent login is verified. The CLI bootstrap-invite wrapper remains an official recovery fallback, not the preferred private bootstrap path.
- Tailscale Serve state is reconstructible from the repository command and is not backed up. Tailscale identity/authentication and access-control policy remain external platform state.
- The existing public-IP root SSH path remains an emergency recovery path until `nix` login over Tailscale, sudo, Docker operation, and recovery access are proven.

## Consequences

Paperclip, PostgreSQL, and ports 80/443 are not exposed on the VPS public interface for Nix. Tailnet membership, MagicDNS, HTTPS enablement, and Tailscale ACLs become live prerequisites. The single VPS remains a failure boundary. The service is inaccessible if Tailscale is unavailable, which is acceptable for V0 and preferable to public exposure.
