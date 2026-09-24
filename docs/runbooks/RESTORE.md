# Slice 0 backup and restore runbook

## Recovery layers

| Layer | Contents | Recovery source |
|---|---|---|
| Git repository | Compose, Caddy, scripts, tests, and redacted documentation | exact reviewed Git commit |
| Encrypted configuration pack | deployment `.env`, `postgres.env`, and `paperclip.env` | separate age-encrypted off-host object |
| Data backup | PostgreSQL plus the complete persistent `/paperclip` state | age-encrypted off-host object |
| Caddy TLS state | certificates and ACME cache | replaceable; deliberately not backed up |

Configuration and data are separate artifacts because they have different change and custody patterns. Both are required for a faithful recovery. The `/paperclip` data archive includes instance configuration, uploads, `PAPERCLIP_AGENT_JWT_SECRET`, and the local encrypted-secrets master key.

## Back up external configuration and secrets

Create a configuration pack after first secret generation and after every `.env` or external secret rotation:

```sh
sudo -E CONFIG_FILE="$PWD/.env" \
  BACKUP_AGE_RECIPIENT='<AGE_RECIPIENT>' \
  ./scripts/backup-config "$PWD/.env"
```

The script reads exactly `.env` and the two absolute secret-file paths declared inside it. It refuses to create an unencrypted pack, writes mode `0600`, includes internal SHA-256 checksums and original destination paths, and never logs file contents. Copy the `.tar.gz.age` and `.sha256` sidecar off-host with the approved client.

Restore onto a clean host after cloning the recorded Git commit:

```sh
rclone copy '<REMOTE>:<BUCKET>/nix-os/config/nix-os-config-<timestamp>.tar.gz.age' /secure/recovery/
rclone copy '<REMOTE>:<BUCKET>/nix-os/config/nix-os-config-<timestamp>.tar.gz.age.sha256' /secure/recovery/

sudo -E AGE_IDENTITY_FILE=/secure/path/age-identity.txt \
  ./scripts/restore-config \
  /secure/recovery/nix-os-config-<timestamp>.tar.gz.age \
  "$PWD/.env"
```

Restore refuses to overwrite existing files unless `CONFIG_RESTORE_FORCE=true` is explicitly set. It validates the encrypted object's sidecar when present, validates every checksum inside the decrypted pack, restores all three files with mode `0600`, and prints only SHA-256 fingerprints. Compare those non-secret fingerprints with the expected recovery record; never print or diff secret contents in a log.

`tests/smoke/config-backup.sh` performs this round trip under an isolated root and byte-compares the source/restored files without logging them.

## Back up Paperclip data

`scripts/backup` briefly stops Paperclip so the database and `/paperclip` volume are captured during one write-free interval. The artifact contains:

- a PostgreSQL custom-format dump;
- the complete Paperclip volume, including uploaded assets, instance configuration, and the encrypted-secrets master key;
- database counts and Paperclip file hashes;
- Git commit and exact image references;
- checksums for every payload.

For production, encrypt directly to the off-host recipient:

```sh
sudo -E CONFIG_FILE="$PWD/.env" \
  BACKUP_AGE_RECIPIENT='<AGE_RECIPIENT>' \
  ./scripts/backup "$PWD/.env"

rclone copy --immutable /var/backups/nix-os/<artifact>.tar.gz.age '<REMOTE>:<BUCKET>/nix-os/data/'
rclone copy --immutable /var/backups/nix-os/<artifact>.tar.gz.age.sha256 '<REMOTE>:<BUCKET>/nix-os/data/'
```

Without `BACKUP_AGE_RECIPIENT`, the script clearly marks a local artifact as unencrypted. That mode exists for isolated tests only; never upload it as a production backup. Confirm the remote checksum before reporting success, and retain at least one previously verified off-host backup during rotation.

## Automated isolated restore

The restore smoke refuses production-like project names, creates fresh volumes, restores both state classes, verifies database counts and every `/paperclip` file hash, and starts only PostgreSQL and Paperclip. For an encrypted object downloaded from the remote:

```sh
sudo -E \
  AGE_IDENTITY_FILE=/secure/path/age-identity.txt \
  RESTORE_POSTGRES_ENV_FILE=/etc/nix-os/postgres.env \
  RESTORE_PAPERCLIP_ENV_FILE=/etc/nix-os/paperclip.env \
  ./scripts/restore-smoke /secure/recovery/<artifact>.tar.gz.age
```

Supplying the two restored external secret files proves the recovered application is using the original database/auth secrets. Without those variables the smoke deliberately generates disposable credentials, which is useful only for structural testing. Successful output states `Restore smoke passed`. By default the isolated project is removed; `RESTORE_KEEP=true` retains it and prints its cleanup command.

The required CI recovery job goes further on every repository change: from clean volumes it provisions the official Paperclip instance config, signs up a real user, creates and accepts a verified bootstrap CEO invite, disables signup, proves existing login, creates a real company and related issue through the API, uploads known bytes, creates a harmless `local_encrypted` canary secret bound to a disposable environment probe, creates and relocates an age-encrypted data backup, decrypts and restores it into fresh volumes with the original external secrets, then verifies CEO login, object values/relationships, attachment SHA-256, one new successful canary-resolution access event, and health.

Paperclip's normal authenticated board reads intentionally never return secret plaintext. Its supported environment probe does resolve secrets bound to the environment server-side and records an access event. The smoke binds the canary as a disposable SSH environment's private-key reference and probes closed loopback port 1. HTTP 200 with the expected transport failure proves the probe executed; exactly one new access event with `outcome=success`, `consumerType=environment`, and the restored environment ID proves decryption succeeded before that deliberate transport failure. Neither response contains the secret value.

## Production recovery

Production recovery is intentionally manual and destructive if aimed at an existing project. Use a clean host and verify target volumes do not exist.

1. Download the encrypted configuration and data artifacts plus both sidecars. Verify and restore the config pack as described above. Clone/checkout the exact Git commit recorded in the backup.

2. Verify and decrypt the data artifact into a root-private directory:

   ```sh
   mkdir -m 0700 /tmp/nix-os-recovery
   cd /tmp/nix-os-recovery
   (cd /secure/recovery && sha256sum --check <artifact>.tar.gz.age.sha256)
   age --decrypt --identity /secure/path/age-identity.txt \
     --output backup.tar.gz /secure/recovery/<artifact>.tar.gz.age
   tar -xzf backup.tar.gz
   cd nix-os-<source-project>-<timestamp>
   sha256sum --check SHA256SUMS
   ```

3. Run the isolated restore first with the original restored secret files. Do not proceed if counts, file hashes, object verification, authentication, or health fail.

4. Set `<project>` to the exact `COMPOSE_PROJECT_NAME` in `.env`. Confirm `docker volume inspect <project>_postgres_data` and `<project>_paperclip_data` both report not found. Then create stopped containers and empty named volumes:

   ```sh
   sudo docker compose --env-file .env down
   sudo docker compose --env-file .env create postgres paperclip
   ```

5. Restore `/paperclip`, start PostgreSQL so its first-start role initializer runs, and restore the logical dump:

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

6. Run the Nix read-only migration preflight before starting Paperclip, then start Paperclip and Caddy. This gives the documented restore path an earlier, clearer failure; the pinned Paperclip release also rejects a non-empty database without its migration journal before applying migrations:

   ```sh
   sudo -E CONFIG_FILE="$PWD/.env" ./scripts/check-migrations "$PWD/.env"
   sudo docker compose --env-file .env up -d --wait paperclip caddy
   sudo -E CONFIG_FILE="$PWD/.env" ./scripts/ops health
   ```

7. Complete the full live recovery gate before reopening normal work:

   ```text
   create harmless canary secret
   + real company
   + real issue linked to that company
   + known-byte attachment with recorded SHA-256
   → encrypted data backup and encrypted config pack
   → upload both off-host and verify remote checksums
   → download both artifacts
   → isolated restore with original external secret files
   → authenticate as the existing CEO
   → verify company/issue values and relationship
   → download attachment and match its SHA-256
   → resolve the canary through its bound disposable environment probe and verify one new successful access event without printing its value
   → health passes
   → destroy the isolated restore environment and decrypted temporary files
   ```

   Use the same procedure as the automated smoke: note the canary access-event count; `POST /api/environments/<probe-environment-id>/probe` as the authenticated CEO; require HTTP 200; then `GET /api/secrets/<canary-secret-id>/access-events` and require the count to increase by one with the newest event reporting `outcome=success`, `consumerType=environment`, and the probe environment ID. The SSH transport result is deliberately `ok=false` because port 1 is closed; secret resolution happens first. Never echo the value or place it in issue text/logs. Record the date, Git commit, artifact fingerprints, and result—not credentials—in Operations evidence.

Never restore over running production volumes. Initial targets are RPO no greater than 24 hours and manual RTO no greater than 8 hours. Schedule daily encrypted data backups, config packs after configuration changes, and a monthly downloaded-off-host isolated restore once the live destination exists.
