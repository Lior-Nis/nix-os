# Nix backup and restore runbook

## Recovery layers

| Layer | Contents | Recovery source |
|---|---|---|
| Git repository | Compose, scripts, tests, and redacted documentation | exact reviewed Git commit |
| Encrypted configuration pack | `.env`, `postgres.env`, `paperclip.env`, and `hermes.env` | `gdrive:Nix/backups/config/` |
| Encrypted data backup | PostgreSQL, complete `/paperclip`, and complete Hermes `/opt/data` state | `gdrive:Nix/backups/state/` |
| Tailscale Serve state | hostname and Serve rule | replaceable from `scripts/configure-tailscale`; not backed up |
| Tailscale/rclone auth | external platform credentials | reauthenticate; never Git or data backup |

The age private identity must be held off the VPS. Caddy/TLS state does not exist; Tailscale manages tailnet certificates.

## Age identity custody

The production identity is generated on Lior's Mac at `~/.config/nix/age/identity.txt` with mode `0600`; `recipient.txt` contains only its public recipient. Never copy the identity to the repository or VPS. Keep a second safe copy outside the VPS, ideally in a password manager or equivalent secure personal backup. Only the `age1...` recipient is supplied to VPS backup commands.

Repository policy ignores only the documented `.config/nix/age/identity.txt` layout if it is accidentally copied into a checkout. CI scans the working tree and every locally reachable Git commit for classic `AGE-SECRET-KEY-1`, post-quantum `AGE-SECRET-KEY-PQ-1`, and plugin `AGE-PLUGIN-...-1` private identities without printing matching contents.

## Back up configuration and secrets

After first secret generation and after every `.env` or external-secret change:

```sh
sudo -E CONFIG_FILE="$PWD/.env" \
  BACKUP_AGE_RECIPIENT='<PUBLIC_AGE_RECIPIENT>' \
  ./scripts/backup-config "$PWD/.env"

rclone copyto --immutable /var/backups/nix-os/<config-artifact>.tar.gz.age \
  gdrive:Nix/backups/config/<config-artifact>.tar.gz.age
rclone copyto --immutable /var/backups/nix-os/<config-artifact>.tar.gz.age.sha256 \
  gdrive:Nix/backups/config/<config-artifact>.tar.gz.age.sha256
```

The script reads exactly the four external files, creates no plaintext pack, uses mode `0600`, and logs only non-secret checksums/paths. `hermes.env` contains the Telegram and Runs API credentials. The separately claimed Paperclip agent key and provider OAuth state live in the Hermes volume. The rclone config is a runtime secret and is intentionally excluded; recovery may reauthenticate.

## Back up Paperclip and Hermes data

The data backup briefly stops Hermes first and Paperclip second, then creates a coordinated PostgreSQL dump plus `/paperclip` and Hermes `/opt/data` archives. It restarts Paperclip before Hermes:

```sh
sudo -E CONFIG_FILE="$PWD/.env" \
  BACKUP_AGE_RECIPIENT='<PUBLIC_AGE_RECIPIENT>' \
  ./scripts/backup "$PWD/.env"

rclone copyto --immutable /var/backups/nix-os/<state-artifact>.tar.gz.age \
  gdrive:Nix/backups/state/<state-artifact>.tar.gz.age
rclone copyto --immutable /var/backups/nix-os/<state-artifact>.tar.gz.age.sha256 \
  gdrive:Nix/backups/state/<state-artifact>.tar.gz.age.sha256
```

Unencrypted output is for isolated tests only and must never leave the VPS.

## Download and prove the remote copy

Do not use original local artifacts for recovery evidence:

```sh
mkdir -m 0700 /secure/recovery
rclone copyto gdrive:Nix/backups/config/<config-artifact>.tar.gz.age /secure/recovery/<config-artifact>.tar.gz.age
rclone copyto gdrive:Nix/backups/config/<config-artifact>.tar.gz.age.sha256 /secure/recovery/<config-artifact>.tar.gz.age.sha256
rclone copyto gdrive:Nix/backups/state/<state-artifact>.tar.gz.age /secure/recovery/<state-artifact>.tar.gz.age
rclone copyto gdrive:Nix/backups/state/<state-artifact>.tar.gz.age.sha256 /secure/recovery/<state-artifact>.tar.gz.age.sha256
(cd /secure/recovery && sha256sum --check <config-artifact>.tar.gz.age.sha256)
(cd /secure/recovery && sha256sum --check <state-artifact>.tar.gz.age.sha256)
```

Transfer the downloaded encrypted files to the Mac or another isolated recovery host holding the age identity. Google Drive must contain only ciphertext and checksum sidecars.

Restore configuration first:

```sh
sudo -E AGE_IDENTITY_FILE="$HOME/.config/nix/age/identity.txt" \
  ./scripts/restore-config /secure/recovery/<config-artifact>.tar.gz.age "$PWD/.env"
```

The tool validates outer and inner checksums, restores mode `0600`, and prints only fingerprints. It refuses overwrites unless `CONFIG_RESTORE_FORCE=true` is explicit.

## Isolated recovery proof

Run with the downloaded data object and restored original secret files:

```sh
sudo -E \
  AGE_IDENTITY_FILE="$HOME/.config/nix/age/identity.txt" \
  RESTORE_POSTGRES_ENV_FILE=/etc/nix-os/postgres.env \
  RESTORE_PAPERCLIP_ENV_FILE=/etc/nix-os/paperclip.env \
  RESTORE_HERMES_ENV_FILE=/etc/nix-os/hermes.env \
  ./scripts/restore-smoke /secure/recovery/<state-artifact>.tar.gz.age
```

The smoke refuses production project names and pre-existing volumes and restores into fresh isolated state. Because Docker may seed a newly attached named volume from image contents during container creation, the script empties each already-validated fresh application volume immediately before extracting its archive. It compares database counts plus every `/paperclip` and Hermes `/opt/data` file hash and verifies Paperclip health. CI additionally creates a real CEO, company/issue relation, attachment bytes, encrypted canary, and representative Chief memory/session/skill/provider/gateway/Paperclip-link files; after restore it verifies all hashes, login, relationship, attachment checksum, and a new successful server-side secret-resolution audit event without revealing plaintext. CI cannot contact the real Telegram bot or OpenAI account.

The production acceptance gate uses the same supported Paperclip interfaces:

```text
recovery-labelled company + related issue + known-byte attachment + harmless local_encrypted canary
-> encrypted config and state artifacts
-> upload to Google Drive
-> download both artifacts again
-> checksums and age decryption pass using the separately held identity
-> fresh isolated restore with original external secret files
-> CEO authenticates
-> company/issue relationship matches
-> downloaded attachment SHA-256 matches
-> bound environment probe creates one new successful canary access event without plaintext output
-> Chief profile/SOUL, continuity memory, Telegram session, grill-me skill, gateway state, provider auth metadata, and claimed Paperclip identity are present
-> restored Hermes starts with its authenticated API private to Compose
-> Telegram bot resumes and Chief answers only Lior
-> openai-codex auth still works, or the documented device-code reauthentication is completed and recorded
-> Chief reads the restored Paperclip issue and read-only nix-brain checkout
-> application and database health pass
-> isolated environment is destroyed
```

Record only non-secret IDs, relationships, SHA-256 values, timestamps, Git SHA, and result.

## Full replacement-host recovery

Only after the isolated proof passes:

1. Rebuild Ubuntu/Docker/Tailscale prerequisites, clone the recorded Git SHA, recreate/prove the `nix` operator, and restore the config pack.
2. Re-clone canonical `nix-brain` at the configured host path. It is Git-reconstructible and is not part of the state backup.
3. Confirm target volumes do not exist, then run `sudo docker compose --env-file .env create postgres paperclip hermes`.
4. Decrypt the state archive in a mode-0700 temporary directory and validate its internal `SHA256SUMS`.
5. Restore `/paperclip` and Hermes `/opt/data` with the pinned PostgreSQL image as the archive helper:

   ```sh
   sudo docker run --rm \
     --volume <project>_paperclip_data:/target \
     --volume /secure/decrypted-payload:/backup:ro \
     postgres:17.11-alpine3.24@sha256:b0f9560a2de083e2cc7382e75f808c7381a32852a7ec49117deedb300e552b24 \
     sh -ec 'find /target -mindepth 1 -delete && cd /target && tar -xzf /backup/paperclip-data.tar.gz'
   ```

   Repeat the command with `<project>_hermes_data:/target` and `/backup/hermes-data.tar.gz`. The `find` deletion is safe here only because the procedure has already proved these are newly created, isolated restore volumes; it removes image-seeded defaults before exact archive restoration.

6. Start PostgreSQL, restore `postgres.dump` with `pg_restore --clean --if-exists --no-owner --no-privileges`, run `scripts/check-migrations`, then start Paperclip and Hermes.
7. Run `scripts/configure-tailscale` to reconstruct the node name and Serve rule. Verify tailnet health and public non-exposure, including that Hermes ports 8642 and 9119 are not host-published.
8. Run `scripts/configure-hermes verify`, then repeat CEO/company/issue/attachment/secret and Chief Telegram/memory/Paperclip checks. Securely remove decrypted temporary files. Never restore over running production volumes.

Targets remain RPO <= 24 hours and manual RTO <= 8 hours. Schedule daily state backups, config packs after changes, and a monthly downloaded-off-host restore.
