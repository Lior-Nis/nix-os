# Slice 0 backup and restore runbook

## What is protected

`scripts/backup` briefly stops Paperclip so PostgreSQL and the `/paperclip` volume are captured across one write-free interval. The resulting artifact contains:

- a PostgreSQL custom-format dump;
- the complete Paperclip volume, including uploaded assets, instance configuration, and the local encrypted-secrets master key;
- file hashes and database object counts;
- the Git commit and exact Compose image references;
- checksums for every payload.

It does not include `/etc/nix-os/postgres.env` or `/etc/nix-os/paperclip.env`. Those are secrets and require a separate encrypted backup. Caddy certificate state is intentionally excluded because it is replaceable from DNS and the tracked Caddyfile.

## Create a backup

```sh
sudo -E CONFIG_FILE="$PWD/.env" ./scripts/backup "$PWD/.env"
```

The default destination comes from `BACKUP_OUTPUT_DIR`. Artifacts and checksum sidecars are mode `0600`. Without `BACKUP_AGE_RECIPIENT`, the local artifact is deliberately marked as unencrypted and must not be uploaded as-is.

To encrypt directly with an age recipient:

```sh
sudo -E CONFIG_FILE="$PWD/.env" \
  BACKUP_AGE_RECIPIENT='age1...' \
  ./scripts/backup "$PWD/.env"
```

Upload is intentionally destination-agnostic. After configuring an approved encrypted remote, copy both the artifact and checksum with the provider's supported client. For example:

```sh
rclone copy --immutable /var/backups/nix-os/<artifact>.age <REMOTE>:<BUCKET>/nix-os/
rclone copy --immutable /var/backups/nix-os/<artifact>.age.sha256 <REMOTE>:<BUCKET>/nix-os/
```

Replace `<REMOTE>` and `<BUCKET>` only with supplied values. Confirm the remote checksum before treating the backup as complete. Keep at least one previously verified off-host backup when applying retention.

## Isolated restore smoke

The smoke restore refuses the source project name and `nix-os`, creates fresh volumes under a unique project, restores both state classes, compares database counts and every Paperclip file hash, and starts only PostgreSQL and Paperclip. Caddy is not started, so no production ports or certificates are touched.

```sh
sudo -E ./scripts/restore-smoke /absolute/path/to/nix-os-....tar.gz
```

For an age-encrypted artifact:

```sh
sudo -E AGE_IDENTITY_FILE=/secure/path/age-identity.txt \
  ./scripts/restore-smoke /absolute/path/to/nix-os-....tar.gz.age
```

Successful output states `Restore smoke passed`. By default the isolated project and temporary secrets are deleted. For diagnosis only, set `RESTORE_KEEP=true`; the script prints the exact cleanup command.

## Production recovery

Production recovery is intentionally manual in V0. It is destructive if aimed at an existing project, so use a clean host and confirm the target named volumes do not exist.

1. Clone the exact Git commit named in `manifest.env`, restore `.env`, and restore the original external secret files from their encrypted backup. Preserving `BETTER_AUTH_SECRET` preserves valid auth sessions; rotating it intentionally invalidates them.
2. Verify the downloaded artifact beside its sidecar, decrypt when necessary, extract it into a root-private work directory, and verify every internal payload:

   ```sh
   mkdir -m 0700 /tmp/nix-os-recovery
   cd /tmp/nix-os-recovery
   (cd /path/to && sha256sum --check <artifact>.age.sha256)
   age --decrypt --identity /secure/path/age-identity.txt \
     --output backup.tar.gz /path/to/<artifact>.age
   tar -xzf backup.tar.gz
   cd nix-os-<source-project>-<timestamp>
   sha256sum --check SHA256SUMS
   ```

   For a local unencrypted artifact, verify its `.tar.gz.sha256` sidecar in the same way and copy the `.tar.gz` to `backup.tar.gz`; an off-host production artifact must be encrypted.

3. Run the isolated smoke first. Do not continue if database counts, file hashes, or health differ:

   ```sh
   AGE_IDENTITY_FILE=/secure/path/age-identity.txt ./scripts/restore-smoke /path/to/<artifact>.age
   ```

4. Set `<project>` below to the exact `COMPOSE_PROJECT_NAME` in `.env`. Confirm both `docker volume inspect <project>_postgres_data` and `docker volume inspect <project>_paperclip_data` report that the volumes do not exist. Then create stopped containers and empty named volumes:

   ```sh
   sudo docker compose --env-file .env down
   sudo docker compose --env-file .env create postgres paperclip
   ```

5. Restore the Paperclip home into the empty volume, start PostgreSQL so its first-start role initializer runs, then restore the logical dump:

   ```sh
   sudo docker run --rm \
     --volume <project>_paperclip_data:/target \
     --volume /tmp/nix-os-recovery/nix-os-<source-project>-<timestamp>:/backup:ro \
     caddy:2.11.4-alpine@sha256:6aeddd44c3078b0f9a35206472a11420648a79c184603ef95957d0a20044cb2b \
     sh -ec 'cd /target && tar -xzf /backup/paperclip-data.tar.gz'
   sudo docker compose --env-file .env up -d --wait postgres
   sudo docker compose --env-file .env exec -T postgres pg_restore \
     --username paperclip --dbname paperclip --clean --if-exists \
     --no-owner --no-privileges \
     < /tmp/nix-os-recovery/nix-os-<source-project>-<timestamp>/postgres.dump
   ```

6. Start Paperclip and Caddy, then verify both paths:

   ```sh
   sudo docker compose --env-file .env up -d --wait paperclip caddy
   sudo -E CONFIG_FILE="$PWD/.env" ./scripts/ops health
   ```

7. Confirm a sampled company, issue, and attachment in the UI before reopening normal operation. Securely remove the decrypted recovery directory after acceptance; retain the encrypted off-host artifact.

Never restore over running production volumes. The initial objectives are RPO no greater than 24 hours and manual RTO no greater than 8 hours. Schedule a daily backup and a monthly isolated restore after the live host and remote destination are available.
