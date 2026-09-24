# Slice 0 deployment runbook

This runbook deploys only Caddy, Paperclip, and PostgreSQL on one Linux VPS. Commands run from a clean clone of this repository.

## External prerequisites

- A private GitHub remote for this repository and a protected default branch.
- Hostinger VPS access with Docker Engine and Docker Compose v2 installed.
- A DNS A/AAAA record for the chosen Paperclip hostname pointing to the VPS.
- TCP 80/443 and UDP 443 allowed to the VPS. Do not allow TCP 3100 or 5432.
- An encrypted off-host destination for backup artifacts.

These values are not present in Git and must not be invented by an implementation agent.

## First deployment

1. Clone the private GitHub repository onto the VPS and check out the reviewed Slice 0 commit.
2. Create the non-secret deployment configuration:

   ```sh
   cp .env.example .env
   chmod 0600 .env
   editor .env
   ```

   Replace `PAPERCLIP_HOSTNAME` and `ACME_EMAIL`. Keep the secret-file paths outside the checkout. Select a stable lowercase `COMPOSE_PROJECT_NAME`; changing it creates a different set of volumes.

3. Generate the external secret files:

   ```sh
   sudo CONFIG_FILE="$PWD/.env" ./scripts/init-secrets "$PWD/.env"
   sudo chown root:root /etc/nix-os/postgres.env /etc/nix-os/paperclip.env
   sudo chmod 0600 /etc/nix-os/postgres.env /etc/nix-os/paperclip.env
   ```

   `postgres.env` contains distinct `POSTGRES_PASSWORD` (database administrator) and `PAPERCLIP_DB_PASSWORD` values. The first-start initialization creates `paperclip` as a non-superuser application role and gives it ownership of the `paperclip` database. `paperclip.env` contains the matching application `DATABASE_URL`, `BETTER_AUTH_SECRET`, and `PAPERCLIP_TOOL_ACTION_SIGNING_SECRET`. Back up both files separately in encrypted storage.

4. Validate and deploy:

   ```sh
   sudo -E CONFIG_FILE="$PWD/.env" ./scripts/check-config "$PWD/.env"
   sudo -E CONFIG_FILE="$PWD/.env" ./scripts/ops deploy
   ```

5. Confirm the external firewall exposes only 80/443 and verify health:

   ```sh
   sudo -E CONFIG_FILE="$PWD/.env" ./scripts/ops status
   sudo -E CONFIG_FILE="$PWD/.env" ./scripts/ops health
   ```

6. Bootstrap the first administrator. With `PAPERCLIP_AUTH_DISABLE_SIGN_UP=false`, create the intended account in the browser, then mint the one-time invite inside the pinned image:

   ```sh
   sudo docker compose --env-file .env exec paperclip \
     pnpm paperclipai auth bootstrap-ceo
   ```

   Open the printed HTTPS invite URL while signed in and accept it. Do not send that URL through chat or store it in an issue.

7. Immediately change `PAPERCLIP_AUTH_DISABLE_SIGN_UP=true` in `.env`, then apply and verify:

   ```sh
   sudo -E CONFIG_FILE="$PWD/.env" ./scripts/ops restart
   ```

8. Create the Nix company, a disposable issue, and an attachment. Restart without deleting volumes and confirm they survive:

   ```sh
   sudo docker compose --env-file .env down
   sudo docker compose --env-file .env up -d --wait
   ```

## Routine operations

```sh
make CONFIG_FILE=.env status
make CONFIG_FILE=.env health
make CONFIG_FILE=.env logs
make CONFIG_FILE=.env restart
```

Logs may contain operational metadata. Do not paste raw logs into public systems without reviewing them for user content or credentials.

## Upgrade

Re-read the target Paperclip release notes and update the tag and digest together in `compose.yaml`. Update `docs/UPSTREAM.md`, run CI, and review migrations. Then:

```sh
sudo -E CONFIG_FILE="$PWD/.env" ./scripts/ops upgrade
```

The command validates configuration, creates a backup while Paperclip is stopped, pulls pinned images, starts the stack, allows Paperclip to apply bundled migrations explicitly, and waits for health. If startup fails, preserve the backup and inspect `paperclip` and `postgres` logs. Do not point an older application image at a database after irreversible migrations unless upstream documents that rollback as safe.

## Missing live prerequisites

The repository cannot complete the live deployment until Lior supplies the private GitHub remote, VPS access, hostname/DNS, and encrypted off-host backup destination. Once supplied:

```sh
git remote add origin <PRIVATE_GITHUB_URL>
git push -u origin slice-0-foundation
ssh <VPS_HOST>
# follow First deployment above
```

Enable default-branch protection in GitHub with the `foundation` CI check required before merge.
