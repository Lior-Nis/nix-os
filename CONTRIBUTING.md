# Contributing to Nix OS

This repository is the safe, Git-tracked declaration of Nix's lean Hermes operating system.

## Required boundaries

- LNX is Lior's personal portfolio orchestrator and the only initially Discord-visible profile.
- Project Leads own project decomposition and synthesis; specialists execute fresh bounded assignments.
- Discord is the primary human messaging, alert, and live-voice plane.
- Todoist, accessed through `td`, contains only commitments assigned to Lior.
- Hermes Kanban holds delegated execution state.
- GitHub and project documents hold durable requirements, decisions, reviews, and evidence.
- Do not add a second task authority, workflow engine, custom agent runtime, or messaging identity for every internal profile without an explicit accepted need.

## Safety

Never add credentials, tokens, `.env` files, authentication stores, memories, sessions, transcripts, databases, logs, caches, backups, UI metadata, customer/student/payment data, or copied live profile directories. Use `${HOME}` placeholders instead of machine-specific paths.

## Change discipline

1. Read `README.md`, `nix-os.yaml`, and `docs/ARCHITECTURE.md` before changing topology.
2. Keep the manifest, role contracts, bootstrap behavior, tests, and documentation consistent.
3. Bootstrap must remain preview-first, idempotent, and non-destructive to existing profiles.
4. Use feature branches and pull requests for consequential changes.
5. Keep every NixKit source skill in exactly one semantic class: persistent, task-only, or excluded. Persistent role assignment must be explicit; no wildcard/global pack.
6. New persistent skills require all hard gates, score >=80, immutable provenance/license evidence, a profile-specific manifest PR, and explicit Lior approval. Popularity alone is never sufficient.
7. Never hand-edit live Hermes cron stores. Scout changes remain preview-first, local-delivery first, and fail closed on missing packets or same-name drift.
8. Run:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/verify.py
bash -n scripts/bootstrap.sh
python3 -m py_compile scripts/verify.py scripts/install-skills.py scripts/setup-skill-scouts.py automation/skill-scout/collect.py
bash scripts/bootstrap.sh
python3 scripts/setup-skill-scouts.py
```
