# Nix backup and restore runbook

## Recovery layers

| Layer | Contents | Recovery source |
|---|---|---|
| Git repository | Compose, scripts, tests, and redacted documentation | exact reviewed Git commit |
| Encrypted configuration pack | `.env`, `postgres.env`, `paperclip.env`, and `hermes.env` | `gdrive:Nix/backups/config/` |
| Encrypted data backup | PostgreSQL, complete `/paperclip`, and complete Hermes `/opt/data` state | `gdrive:Nix/backups/state/` |
| Nix-owned Tailscale Serve state | hostname and Paperclip `:443/` handler | replaceable from `scripts/configure-tailscale`; unrelated cohosted routes are preserved and remain separately owned |
| Tailscale auth | external platform credential | reauthenticate; never Git or data backup |
| rclone OAuth config | exact owned-client identity and refresh credential required by `drive.file` | separately age-encrypted escrow outside Git, the VPS, and the Drive it protects |

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

The script reads exactly the four external files, creates no plaintext pack, uses mode `0600`, and logs only non-secret checksums/paths. `hermes.env` contains the Telegram and Runs API credentials. The separately claimed Paperclip agent key and provider OAuth state live in the Hermes volume. The rclone config is intentionally excluded because it is the credential used to fetch these packs. Preserve the exact config in a separate age-encrypted escrow outside this Drive; a new or different OAuth client cannot assume visibility of the `drive.file` objects.

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

State backups fail before touching services or the output directory unless
`BACKUP_AGE_RECIPIENT` is set and `age` is available. The archive is streamed
directly into age encryption; no plaintext state archive is written to the
backup directory. Partial output is removed if packaging or encryption fails.

Unencrypted output exists only for isolated fixtures that explicitly set both
`NIX_TEST_ONLY_ALLOW_UNENCRYPTED_BACKUP=1` and `NIX_ALLOW_TEST_CONFIG=1`. Never
use that test-only switch for production, upload its output, or retain it after
the fixture completes.

## Restore Drive access from the separate credential escrow

On an isolated recovery host holding the age identity, retrieve the encrypted rclone-config escrow from its custody location outside Google Drive. Verify its recorded checksum, decrypt it without printing it, and transfer the plaintext config to the replacement VPS over the recovery SSH path. Then install it for the dedicated operator:

```sh
mkdir -m 0700 /secure/recovery
(cd /secure/escrow && sha256sum --check rclone.conf.age.sha256)
age --decrypt --identity "$HOME/.config/nix/age/identity.txt" \
  --output /secure/recovery/rclone.conf \
  /secure/escrow/rclone.conf.age
chmod 0600 /secure/recovery/rclone.conf
scp /secure/recovery/rclone.conf nix@<REPLACEMENT_VPS>:/tmp/nix-rclone.conf

ssh nix@<REPLACEMENT_VPS> \
  'sudo install -d -o nix -g nix -m 0700 /home/nix/.config/rclone && sudo install -o nix -g nix -m 0600 /tmp/nix-rclone.conf /home/nix/.config/rclone/rclone.conf && rm -f /tmp/nix-rclone.conf && rclone lsf gdrive: --max-depth 1 >/dev/null'
```

Confirm `rclone config file` resolves to `/home/nix/.config/rclone/rclone.conf`. A new OAuth flow or a different client is not an equivalent substitute for this recovery step: under `drive.file`, it may not see the existing backup objects. Securely remove `/secure/recovery/rclone.conf` after the replacement copy and the downloaded-artifact checks below succeed.

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

The smoke refuses production project names and pre-existing volumes and restores into fresh isolated state. Before backup, its real claimed Chief credential exercises all nine approved MCP operations across identity, existing-project reads, issue create/list/get/update, and comment add/list; the restricted runtime exposes no project/goal/admin mutation tool. The pinned server requires a heartbeat run for existing-issue mutations, so the fixture temporarily uses Paperclip's supported process adapter to hold a disposable issue run open without a model call, supplies that non-secret run ID to the official MCP, proves update/comment attribution, cancels the run, and restores the agent's `hermes_gateway` configuration before backup. Because Docker may seed a newly attached named volume from image contents during container creation, the script empties each already-validated fresh application volume immediately before extracting its archive. It compares database counts plus every `/paperclip` and Hermes `/opt/data` file hash and verifies Paperclip health. It then boots restored Hermes behind a fresh root-owned disabled marker. The entrypoint uses the pinned dotenv parser to remove even BOM-prefixed or quoted legacy Telegram controls from restored profile state before clearing the external token and starting upstream supervision. The test proves Hermes health, API-server `401` without the restored key, authenticated API success, the exact restricted API/runtime tool surface and actual file boundary, Chief profile and receipt presence, and bounded `paperclipMe` identity against isolated restored Paperclip. CI additionally creates a real CEO, company/project/issue relation, MCP comment, attachment bytes, encrypted canary, and representative Chief memory/session/provider/gateway state; after restore it verifies login, relationships, comment, attachment checksum, and a new successful server-side secret-resolution audit event without revealing plaintext. CI does not contact the real Telegram bot or OpenAI account.

A clean restore requires outbound npm registry access the first time the exact `@paperclipai/mcp-server@2026.916.1` package is fetched by `npx`. The version is pinned; this network/cache dependency is reconstructible and is not backed up as critical state.

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
-> Chief profile/SOUL, continuity memory, Telegram session, gateway state, provider auth metadata, and claimed Paperclip identity are present; pinned image-provided grill-me guidance is readable but not writable through file tools
-> restored Hermes starts with Telegram explicitly disabled and its authenticated API private to Compose
-> unauthenticated API gets 401; authenticated capabilities and exact restricted tool surfaces pass
-> bounded Paperclip MCP resolves the restored Chief identity against isolated restored Paperclip
-> Paperclip has exactly one root CEO (Chief); the retained bootstrap manager is `general`, reports to Chief, remains paused and credentialless, and has `/bin/false`, disabled heartbeat, zero budget, and stripped permissions
-> Hermes has no staged claim or pending claim marker; backups are accepted only after the verified claim receipt and credential are fully converged
-> after the isolated runtime is destroyed, production Telegram resumes and Chief answers only Lior
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
3. Run `sudo -E ./scripts/configure-hermes telegram-disable "$PWD/.env"` before any Compose command. The mode marker is intentionally excluded from the config pack, so a replacement host always starts Telegram-disabled until explicit cutover. At container entry, any legacy Telegram variables in the restored profile `.env` are atomically removed before Hermes starts; the external root-owned secret file remains the only Telegram credential source. Confirm target volumes do not exist, then run `sudo docker compose --env-file .env create postgres paperclip hermes`.
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
7. Run `scripts/configure-tailscale` to reconstruct the node name and Nix-owned Paperclip handler without changing unrelated routes. Verify tailnet health and Paperclip public non-exposure, including that Hermes ports 8642 and 9119 are not host-published.
8. Run `scripts/configure-hermes verify` while Telegram remains disabled, then repeat CEO/company/issue/attachment/secret and Chief memory/Paperclip checks. In Paperclip, verify Chief is the only root CEO and the retained bootstrap manager is paused, credentialless, `general`, and reports to Chief; do not delete it on the pinned release. Only after proving the previous poller is stopped, run `scripts/configure-hermes telegram-enable` and force-recreate only Hermes. On rollback, disable the marker before starting another poller. Securely remove decrypted temporary files. Never restore over running production volumes.

Targets remain RPO <= 24 hours and manual RTO <= 8 hours. Schedule daily state backups, config packs after changes, and a monthly downloaded-off-host restore.
