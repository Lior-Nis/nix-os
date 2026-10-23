# State and Secrets

## Git may contain

- the safe topology manifest;
- role contracts containing no personal or customer records;
- non-secret example configuration;
- architecture and operating documentation;
- bootstrap, verification, tests, and CI;
- technical artifacts intended for durable review.

## Git must never contain

- `.env` files or credential exports;
- authentication stores, API keys, bot credentials, cookies, or access tokens;
- memories, user profiles, session histories, transcripts, or UI history;
- SQLite or other runtime databases;
- logs, caches, temporary files, checkpoints, backups, or generated runtime state;
- student, payment, customer, or other protected PII;
- machine-specific paths or copied live profile directories.

`profile.yaml` is runtime/UI metadata and is not a role contract. The repository stores only `profiles/<id>/ROLE.md`. Bootstrap may install that reviewed template as a newly created local profile's `SOUL.md`, but it never imports local metadata into Git.

## Local ownership

Hermes resolves state under `$HERMES_HOME`; when unset, it uses `${HOME}/.hermes`. Each named profile has an isolated local home. The LNX contract maps to Hermes' `default` profile. `ROLE.md` contracts are installed as local `SOUL.md` files only when bootstrap atomically claims an otherwise-missing named profile directory. Bootstrap deliberately does not call `hermes profile create`, because current Hermes versions initialize unrelated state in the active default home.

Existing local profile directories are treated as user-owned. If a directory or identity file already exists, bootstrap reports it and makes no profile-level changes. Configuration remains a deliberate manual operation through Hermes CLI commands.

## Secret setup

Secret enrollment is always interactive and local. Do not pass bot credentials as bootstrap flags, shell arguments, manifest values, CI variables for this repository, or committed placeholders that resemble real credentials. Use Hermes' gateway setup for the default profile and verify the configured allowlist before starting the gateway.

## MeaBeclick privacy boundary

Student and payment records stay in their approved systems. Agents use the minimum necessary information, prefer aggregates or redacted references, and never copy protected records into prompts, board cards, GitHub, project docs, logs, or role files. The bootstrap and verifier do not traverse private knowledge-base locations.

## Incident response

If sensitive state is accidentally added, stop; do not merely add it to `.gitignore`. Remove it from the index and history as appropriate, rotate affected credentials, document the incident in an approved private channel, then re-run repository verification.
