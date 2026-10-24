# Nix OS

Nix OS is a lean, declarative operating repository for the Nix portfolio. It describes seven isolated Hermes profiles, three project boards, role boundaries, and the safe bootstrap path. It is an organizational operating system, not a Linux distribution.

## Current topology

- **LNX (`default`)** is Lior's portfolio orchestrator and the only initially Discord-visible identity.
- **Leads:** Pulse, Algua, and MeaBeclick.
- **MeaBeclick specialists:** UX, Engineering, and Growth, routed through the MeaBeclick Lead.
- **Boards/projects:** `pulse`, `algua`, and `meabeclick`.

Internal profiles do not get messaging identities by default. LNX receives human requests and alerts, delegates bounded work through Hermes Kanban, and returns concise decisions or escalation requests.

## Authority by plane

| Plane | Authority |
| --- | --- |
| Discord | Human messaging, alerts, and live voice through LNX only |
| Todoist (`td`) | Tasks personally assigned to Lior; never delegated-agent work |
| Hermes Kanban | Durable delegated execution, ownership, status, and handoffs |
| GitHub and project docs | Durable technical artifacts, decisions, reviews, and evidence |

The manifest in `nix-os.yaml` is JSON, which is a strict YAML subset. This allows validation with the Python standard library and no package installation.

## Safe start

```bash
python3 scripts/verify.py
python3 -m unittest discover -s tests -v
bash scripts/bootstrap.sh          # preview only
bash scripts/bootstrap.sh --apply  # explicit local mutation
python3 scripts/install-skills.py --profile lnx --nixkit /path/to/nixkit
python3 scripts/setup-skill-scouts.py  # preview only
```

The apply mode creates only missing named profile directories with reviewed role contracts, then uses Hermes CLI for missing boards and projects. It deliberately avoids `hermes profile create`, because that command initializes unrelated active-profile state. Existing profile identity and configuration are preserved; only the requested missing profile directories, boards, and project records are added. The script never reads or writes credentials, memories, sessions, transcripts, or copied runtime data.

After apply, configure Discord manually for the default profile as printed by the script. Keep the bot credential in Hermes' interactive secret setup, never in this repository.

## Governed role skills

`skills/packs.json` pins NixKit and classifies its 41 source skills into explicit persistent role packs, task-only tools, or exclusions. There is no universal pack. The baseline is evidence verification; each profile adds only its audited role packs. `web-design-guidelines` and `find-docs` remain task-only because their pinned skill instructions fetch mutable latest dependencies at runtime.

`scripts/install-skills.py` verifies the exact clean NixKit revision and audited `sources.json`, rejects symlinked profile homes, requires executable `npx`, prints the exact `npx --yes node@24.22.1 .../install.mjs` Hermes subset command, and mutates only with `--apply`. It does not install or replace the host's system Node. Initial packs derive only from the merged manifest; future additions require a profile-specific manifest PR and a tracked approval receipt from Lior. See [Skill Governance](docs/SKILL-GOVERNANCE.md) for candidate gates, promotion, rollback, and private-checkout authentication.

## Weekly scouting

Seven role scouts run locally on staggered Saturday `Asia/Jerusalem` schedules. A default-profile aggregator validates all seven current-week packets, deterministically deduplicates qualifying candidates, and returns `[SILENT]` only for a complete valid week with nothing to report. Provisioning is preview-first:

```bash
python3 scripts/setup-skill-scouts.py
python3 scripts/setup-skill-scouts.py --apply                  # local canary delivery
python3 scripts/setup-skill-scouts.py --apply --enable-delivery # aggregator only, after canaries
```

Only the aggregator's second-stage delivery target is `telegram:6926015052`. Runtime packets stay under `${HOME}/.local/share/hermes-scouts/` and never enter Git.

## Migration note

The previous Paperclip-based design remains preserved remotely at `archive/paperclip-os-2026-10-23`. This repository does not use Paperclip, n8n, Slack, a custom agent runtime, or one Discord bot per internal agent. The archive branch is historical evidence only and must not be modified by this bootstrap.

## Repository map

- `nix-os.yaml` — safe topology and authority manifest
- `profiles/*/ROLE.md` — reviewable role contracts installed locally as `SOUL.md` only for newly created profiles
- `config/hermes.example.yaml` — non-secret baseline settings
- `scripts/bootstrap.sh` — preview-first local bootstrap
- `scripts/install-skills.py` — pinned, exact-subset NixKit role installation
- `scripts/setup-skill-scouts.py` — preview-first per-profile cron reconciliation
- `skills/` — role packs and proposal/approval schemas
- `automation/skill-scout/` — declarative jobs, prompts, report schema, and collector
- `scripts/verify.py` — dependency-free repository safety verifier
- `docs/` — architecture, state, secret, and skill-governance boundaries
