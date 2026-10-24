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

`skills/packs.json` pins NixKit checkout `f5377ca3219daf4f33f6e8525f9438318dabcd2f` and audited `sources.json` SHA-256 `110ecc3872b4fe45ede667afd4ca757d59aef850672045a639eae5ef78415a83`, whose seven LNX skills retain source snapshot `da5f36fc4c470fa28ffdcab1a6c6aaa3750bded3`. It classifies all 57 source skills into explicit persistent role packs, task-only tools, or exclusions. There is no universal pack. The baseline and all named role packs are unchanged. `web-design-guidelines` and `find-docs` remain task-only because their pinned skill instructions fetch mutable latest dependencies at runtime. Caveman and Watch retain their receipt-backed LNX-only single-skill approvals.

The exact `product-development` pack remains approved for LNX as proposal `lnx-product-development-92338765`, with the seven LNX adaptations plus `writing-plans` and `subagent-driven-development` in a fixed order. Its historical receipt remains bound to proposal commit `083d008d3a83cd178e1f79bf962967ae7054fc0e`, proposal-file SHA-256 `06db117e1d84486a50f7beaae32f83fc3540ca8fd01eb5dc7fcf0f9e62100288`, and Lior's exact Discord approval message ID and timestamp; the NixKit pin advance does not rewrite that evidence.

This proposal state declares 11 least-privilege profile-skill assignments: LNX gets `todoist-cli`; Pulse gets `technical-project-management`; UX gets `rtl-design` and `web-accessibility`; Engineering gets `performance`, `web-accessibility`, `systematic-debugging`, and `test-driven-development`; Growth gets `analytics`, `customer-research`, and `social-media-content-calendar`. Algua and MeaBeclick Lead receive no additions. Each assignment has its own immutable single-skill proposal. No new approval receipt exists yet, so none of these 11 additions is installable in this stage.

`scripts/install-skills.py` verifies the exact clean NixKit revision, audited `sources.json`, and the working `install.mjs` bytes against both the pinned Git object and approved SHA-256 before preview or execution, including strict byte-, type-, mode-, symlink-, and file-set verification of the local `skills/watch` Git tree. It rejects symlinked profile homes, recursively inventories validated skill frontmatter to prevent categorized legacy-name collisions, resolves the executable `npx` path once, prints the exact Node 24.22.1 Hermes subset command, revalidates installer and local-tree bytes immediately before execution, and mutates only with `--apply`. Proposed packs never enter the effective set; only baseline profile packs plus exact receipt-backed approved pack additions do. Product-development additionally fails closed unless the approval evidence matches the canonical Discord message ID `1563556252829622396` and timestamp `2026-10-24T14:14:20.145000+00:00`. Each declared single-skill addition must be covered exactly once by repeatable `--approval` receipts. See [Skill Governance](docs/SKILL-GOVERNANCE.md) for candidate gates, promotion, migration, rollback, and private-checkout authentication.

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
