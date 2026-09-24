# Slice 0 deployment runbook

This runbook deploys only Caddy, Paperclip, and PostgreSQL on one VPS. Commands run from a clean clone at a reviewed commit.

## Supported VPS baseline

The tested V0 host is Ubuntu 24.04 LTS on x86_64/amd64. It needs:

- Docker Engine 27.0 or newer and a reachable daemon;
- Docker Compose plugin 2.30 or newer;
- Git, Bash, curl, OpenSSL, tar, GNU `sha256sum`, `age`, and `rclone`;
- public TCP 80/443 and UDP 443, with TCP 3100 and 5432 blocked;
- enough disk for the live volumes plus at least one temporary backup and restore.

This is an explicit tested baseline, not an automated host provisioner. After cloning, run the read-only check:

```sh
./scripts/vps-preflight
```

It reports every missing/unsupported prerequisite and exits nonzero until the host is ready.

## External prerequisites

- A private GitHub remote and protected default branch.
- Hostinger VPS SSH access satisfying the baseline above.
- A DNS A/AAAA record for the Paperclip hostname pointing to the VPS.
- An `age` recipient whose identity is stored separately from the VPS.
- An encrypted off-host destination and configured `rclone` remote.

The repository contains placeholders only. Do not invent any of these values.

## First deployment

1. Clone the private repository, check out the reviewed Slice 0 commit, and run `./scripts/vps-preflight`.

2. Create the deployment configuration:

   ```sh
   cp .env.example .env
   chmod 0600 .env
   editor .env
   ```

   Replace `PAPERCLIP_HOSTNAME` and `ACME_EMAIL`. Keep both secret-file paths outside the checkout. Choose a stable lowercase `COMPOSE_PROJECT_NAME`; changing it selects different named volumes.

3. Generate the external secret files:

   ```sh
   sudo CONFIG_FILE="$PWD/.env" ./scripts/init-secrets "$PWD/.env"
   sudo chown root:root /etc/nix-os/postgres.env /etc/nix-os/paperclip.env
   sudo chmod 0600 /etc/nix-os/postgres.env /etc/nix-os/paperclip.env
   ```

   `postgres.env` contains distinct database-administrator and application passwords. `paperclip.env` contains the matching `DATABASE_URL`, `BETTER_AUTH_SECRET`, and `PAPERCLIP_TOOL_ACTION_SIGNING_SECRET`. Paperclip onboarding creates its additional agent JWT secret and encrypted-secrets master key under the persistent `/paperclip` volume.

4. Create the separate encrypted configuration pack and upload it off-host. This captures exactly `.env`, `postgres.env`, and `paperclip.env`; it never creates a plaintext pack:

   ```sh
   sudo -E CONFIG_FILE="$PWD/.env" \
     BACKUP_AGE_RECIPIENT='<AGE_RECIPIENT>' \
     ./scripts/backup-config "$PWD/.env"

   rclone copy --immutable /var/backups/nix-os/nix-os-config-<timestamp>.tar.gz.age \
     '<REMOTE>:<BUCKET>/nix-os/config/'
   rclone copy --immutable /var/backups/nix-os/nix-os-config-<timestamp>.tar.gz.age.sha256 \
     '<REMOTE>:<BUCKET>/nix-os/config/'
   ```

   Replace placeholders only with supplied values. Preserve the age identity somewhere other than this VPS and Git.

5. Validate and deploy:

   ```sh
   sudo -E CONFIG_FILE="$PWD/.env" ./scripts/check-config "$PWD/.env"
   sudo -E CONFIG_FILE="$PWD/.env" ./scripts/ops deploy
   ```

   `ops deploy` pulls the pinned images, starts PostgreSQL, rejects a non-empty database without the Paperclip/Drizzle journal, provisions `/paperclip/instances/default/config.json` through Paperclip's official onboarding command, validates `authenticated/public` plus the explicit public URL, starts Paperclip/Caddy, and waits for health. It does not treat the onboarding command's exit code as proof; the generated configuration is inspected.

6. Confirm only 80/443 are reachable externally, then inspect status and health:

   ```sh
   sudo -E CONFIG_FILE="$PWD/.env" ./scripts/ops status
   sudo -E CONFIG_FILE="$PWD/.env" ./scripts/ops health
   ```

7. Bootstrap the first CEO:

   - Open `https://<PAPERCLIP_HOSTNAME>` and create the intended user while signup is temporarily enabled.
   - While signed in as that user, run:

     ```sh
     sudo -E CONFIG_FILE="$PWD/.env" ./scripts/ops bootstrap-ceo
     ```

   - Open the printed one-time HTTPS invite URL in that same browser and accept it. The script succeeds only after the invite token is returned by Paperclip's invite API as an active human bootstrap invite; a zero CLI exit without an invite is a failure.
   - Confirm the UI shows the user as CEO and `/api/health` reports `bootstrapStatus: ready` with no active bootstrap invite. Do not send or persist the invite URL in chat, Git, issues, or shell history.

8. Immediately set `PAPERCLIP_AUTH_DISABLE_SIGN_UP=true` in `.env`, recreate Paperclip, and verify both sides of the gate:

   ```sh
   sudo -E CONFIG_FILE="$PWD/.env" ./scripts/ops restart
   ```

   In a private browser session, confirm a new signup is rejected. Log out and sign back in as the existing CEO to prove normal authentication still works. Then create a fresh encrypted configuration pack because `.env` changed, upload it, and verify its remote checksum.

9. Create the Nix company, a disposable issue, an attachment with a recorded SHA-256, and the harmless recovery canary secret described in the restore runbook. Restart without deleting volumes and confirm they survive.

## Routine operations

```sh
make CONFIG_FILE=.env status
make CONFIG_FILE=.env health
make CONFIG_FILE=.env logs
make CONFIG_FILE=.env restart
```

Logs may contain operational metadata. Review them before copying anywhere; never expose credentials or bootstrap URLs.

## Upgrade

Re-read the target release notes and migration source, update image tag and digest together, update `docs/UPSTREAM.md`, and run CI. Then:

```sh
sudo -E CONFIG_FILE="$PWD/.env" ./scripts/ops upgrade
```

The command validates configuration, creates a data backup, runs the migration-journal preflight before replacing Paperclip, pulls pinned images, starts the stack, and waits for health. The pinned release warns and enters its migration path for a non-empty database missing its expected journal; Nix deliberately fails earlier to avoid mutating a wrong or partially initialized database. Every future Paperclip release still requires migration review. Never point an older image at a migrated database unless upstream explicitly documents rollback safety.

## Missing live prerequisites

Live acceptance remains pending until Lior supplies the GitHub remote, Hostinger access, DNS hostname, age recipient/identity custody, and off-host destination credentials. Once supplied:

```sh
git remote add origin <PRIVATE_GITHUB_URL>
git push -u origin slice-0-foundation
ssh <VPS_HOST>
# Follow First deployment above.
```

Require both `foundation` and `recovery` GitHub Actions jobs in branch protection. Hosted CI, firewall/TLS, browser bootstrap/login/signup closure, and off-host round-trip results must be recorded from the real infrastructure; this repository does not claim them.
