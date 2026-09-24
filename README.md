# Nix Business OS V0

Nix is an AI-native operating system for a highly autonomous one-person company. This repository owns deployable configuration, operating policy, integration tests, and architecture documentation. It does not own the live company work graph or durable company knowledge.

Start here:

1. Read [AGENTS.md](AGENTS.md).
2. Read [the architecture](docs/ARCHITECTURE.md) and accepted ADRs.
3. Check the [upstream compatibility snapshot](docs/UPSTREAM.md).
4. Execute exactly one unblocked slice from [the implementation plan](docs/IMPLEMENTATION_PLAN.md).

The repository was empty when the initial architecture pass began on 2026-09-22. Slice 0 now contains the local Compose, validation, backup, restore, CI, and operator foundation. It has not yet been deployed to a VPS because the external prerequisites listed in the implementation plan have not been supplied.

## Authority boundaries

- Paperclip: authoritative work graph, assignments, execution state, and approvals.
- Telegram: conversation, clarification, grilling, and decisions.
- `nix-brain`: durable knowledge and roadmaps, changed by pull request.
- Todoist: a projection containing only actions that require Lior to perform them.
- Git: configuration and code, never runtime state or secrets.

## Planned repository shape

Slices add directories only when they need them:

```text
.
├── AGENTS.md
├── README.md
├── docs/
│   ├── ARCHITECTURE.md
│   ├── IMPLEMENTATION_PLAN.md
│   ├── UPSTREAM.md
│   └── decisions/
├── compose.yaml            # Slice 0 services and state boundaries
├── deploy/
│   ├── caddy/              # Public TLS ingress
│   └── postgres/           # First-start least-privilege role initialization
├── scripts/                # Small operator scripts, not a runtime
├── tests/smoke/            # Configuration and recovery tests
├── docs/runbooks/          # Deploy and restore procedures
└── .github/workflows/      # Lightweight validation CI
```

Do not create placeholder applications, libraries, or services to fill this tree.
