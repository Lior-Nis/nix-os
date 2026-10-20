# Nix backup and restore runbook

## Recovery layers

| Layer | Contents | Recovery source |
|---|---|---|
| Git repository | Compose, scripts, tests, and redacted documentation | exact reviewed Git commit |
| Encrypted configuration pack | deployment `.env`; PostgreSQL, Paperclip, Hermes, founder-relay, restricted specialist-provider, and specialist-worker SSH identity files | `gdrive:Nix/backups/config/` |
| Encrypted data backup | PostgreSQL, complete `/paperclip` durable state, and Hermes `/opt/data` durable state, including Runs idempotency and question-delivery outbox databases when present; reconstructible npm/uv caches and npm `.bin` links are excluded | `gdrive:Nix/backups/state/` |
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

sudo rclone --config /home/nix/.config/rclone/rclone.conf copyto --immutable \
  /var/backups/nix-os/<config-artifact>.tar.gz.age \
  gdrive:Nix/backups/config/<config-artifact>.tar.gz.age
sudo rclone --config /home/nix/.config/rclone/rclone.conf copyto --immutable \
  /var/backups/nix-os/<config-artifact>.tar.gz.age.sha256 \
  gdrive:Nix/backups/config/<config-artifact>.tar.gz.age.sha256
```

The script reads the deployment file plus every referenced external credential and worker-identity file, creates no plaintext pack, uses mode `0600`, and logs only non-secret checksums/paths. `specialist-provider.env` contains exactly the restricted OpenCode value and is never mounted into a service. The worker host key, authorized-keys file, and Paperclip client key are non-reconstructible and are included. Paperclip also retains encrypted specialist secret values in its database. The rclone config and age private identity remain outside these artifacts.

## Back up Paperclip and Hermes data

The data backup first requires both accepted topology gates. The specialist gate proves exactly three idle task-scoped workers, three role-specific built-in SSH environments, their exact managed instructions and encrypted-secret bindings, no extra runner or plugin dependency, no worker API keys, and no nonterminal specialist run. It also requires the local worker to be healthy before capture. The script then stops Hermes and Paperclip, repeats the database and volume gates against quiesced state, creates the coordinated PostgreSQL dump and application archives, and restarts services. Reconstructible caches remain excluded; unexpected symlinks or special files fail closed.

For a downloaded-artifact recovery drill, create one short-lived authenticated Paperclip Board session for the three saved-environment probes after restore. Keep its mode-`0600` Netscape cookie jar only on the trusted recovery path; never upload, commit, paste, or log it. Revoke the session and delete the jar after the drill.

```sh
umask 077
recovery_dir="${NIX_RECOVERY_DIR:-$HOME/.local/share/nix-os-recovery}"
test ! -L "$recovery_dir"
install -d -m 0700 "$recovery_dir"
test -O "$recovery_dir"
paperclip_url=$(awk -F= '$1 == "PAPERCLIP_PUBLIC_URL" { print substr($0, length($1) + 2) }' "$PWD/.env")
restore_cookie=$(mktemp "$recovery_dir/paperclip-restore-cookie.XXXXXX")
read -r -p 'Paperclip CEO email: ' paperclip_email
read -r -s -p 'Paperclip CEO password: ' paperclip_password
printf '\n'
signin_body=$(printf '%s\n%s\n' "$paperclip_email" "$paperclip_password" \
  | jq -Rn '[inputs] | {email:.[0],password:.[1]}')
printf '%s' "$signin_body" | curl -fsS -c "$restore_cookie" \
  -H "Origin: $paperclip_url" -H 'Content-Type: application/json' \
  --data-binary @- "$paperclip_url/api/auth/sign-in/email" >/dev/null
unset paperclip_password signin_body
chmod 0600 "$restore_cookie"
curl -fsS -b "$restore_cookie" "$paperclip_url/api/auth/get-session" \
  | jq -e '.user.id != null or .session.userId != null or .userId != null' >/dev/null
printf 'RESTORE_PAPERCLIP_COOKIE_FILE=%s\n' "$restore_cookie"
printf 'BACKUP_PAPERCLIP_COOKIE_FILE=%s\n' "$restore_cookie"
```

Run the state backup below only after that final session check succeeds. If the recovery proof runs on a different trusted host, transfer the cookie jar directly over the recovery SSH path with mode `0600`; do not place it in Google Drive. The restore script parses the jar locally and sends only its `Cookie` header over Compose stdin to the isolated Paperclip loopback. It intentionally ignores the original cookie domain because the restored server has the same session row and restored Better Auth secret; normal server-side expiry and revocation still apply. If the session is no longer valid, create a new dedicated session and a new state backup—never disable the specialist topology/readiness gate.

```sh
sudo -E CONFIG_FILE="$PWD/.env" \
  BACKUP_AGE_RECIPIENT='<PUBLIC_AGE_RECIPIENT>' \
  BACKUP_PAPERCLIP_COOKIE_FILE="$restore_cookie" \
  ./scripts/backup "$PWD/.env"

sudo rclone --config /home/nix/.config/rclone/rclone.conf copyto --immutable \
  /var/backups/nix-os/<state-artifact>.tar.gz.age \
  gdrive:Nix/backups/state/<state-artifact>.tar.gz.age
sudo rclone --config /home/nix/.config/rclone/rclone.conf copyto --immutable \
  /var/backups/nix-os/<state-artifact>.tar.gz.age.sha256 \
  gdrive:Nix/backups/state/<state-artifact>.tar.gz.age.sha256
```

Create the configuration and state artifacts consecutively without changing configuration or deploying between them. Record the production Git SHA, both artifact basenames, and both outer SHA-256 values together in the acceptance evidence. The two artifact formats validate their own contents but are not cryptographically cross-linked to each other.

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
umask 077
recovery_dir="${NIX_RECOVERY_DIR:-$HOME/.local/share/nix-os-recovery}"
escrow_dir="<ABSOLUTE_ESCROW_DIRECTORY>"
test ! -L "$recovery_dir"
install -d -m 0700 "$recovery_dir"
test -O "$recovery_dir"
(cd "$escrow_dir" && sha256sum --check rclone.conf.age.sha256)
age --decrypt --identity "$HOME/.config/nix/age/identity.txt" \
  --output "$recovery_dir/rclone.conf" \
  "$escrow_dir/rclone.conf.age"
chmod 0600 "$recovery_dir/rclone.conf"
scp "$recovery_dir/rclone.conf" nix@<REPLACEMENT_VPS>:/tmp/nix-rclone.conf

ssh nix@<REPLACEMENT_VPS> \
  'sudo install -d -o root -g root -m 0700 /home/nix/.config/rclone && sudo install -o root -g root -m 0600 /tmp/nix-rclone.conf /home/nix/.config/rclone/rclone.conf && rm -f /tmp/nix-rclone.conf && sudo rclone --config /home/nix/.config/rclone/rclone.conf lsf gdrive: --max-depth 1 >/dev/null'
```

Confirm `sudo rclone --config /home/nix/.config/rclone/rclone.conf config file` resolves to `/home/nix/.config/rclone/rclone.conf`. The production copy is root-owned and mode `0600`, so every backup and recovery transfer names it explicitly and runs `rclone` through `sudo`; do not relax its ownership so the operator can invoke plain `rclone`. A new OAuth flow or a different client is not an equivalent substitute for this recovery step: under `drive.file`, it may not see the existing backup objects. Securely remove `$recovery_dir/rclone.conf` after the replacement copy and the downloaded-artifact checks below succeed.

## Download and prove the remote copy

Do not use original local artifacts for recovery evidence:

```sh
umask 077
recovery_dir="${NIX_RECOVERY_DIR:-$HOME/.local/share/nix-os-recovery}"
test ! -L "$recovery_dir"
install -d -m 0700 "$recovery_dir"
test -O "$recovery_dir"
sudo rclone --config /home/nix/.config/rclone/rclone.conf copyto gdrive:Nix/backups/config/<config-artifact>.tar.gz.age "$recovery_dir/<config-artifact>.tar.gz.age"
sudo rclone --config /home/nix/.config/rclone/rclone.conf copyto gdrive:Nix/backups/config/<config-artifact>.tar.gz.age.sha256 "$recovery_dir/<config-artifact>.tar.gz.age.sha256"
sudo rclone --config /home/nix/.config/rclone/rclone.conf copyto gdrive:Nix/backups/state/<state-artifact>.tar.gz.age "$recovery_dir/<state-artifact>.tar.gz.age"
sudo rclone --config /home/nix/.config/rclone/rclone.conf copyto gdrive:Nix/backups/state/<state-artifact>.tar.gz.age.sha256 "$recovery_dir/<state-artifact>.tar.gz.age.sha256"
sudo chown "$(id -u):$(id -g)" \
  "$recovery_dir/<config-artifact>.tar.gz.age" \
  "$recovery_dir/<config-artifact>.tar.gz.age.sha256" \
  "$recovery_dir/<state-artifact>.tar.gz.age" \
  "$recovery_dir/<state-artifact>.tar.gz.age.sha256"
chmod 0600 \
  "$recovery_dir/<config-artifact>.tar.gz.age" \
  "$recovery_dir/<config-artifact>.tar.gz.age.sha256" \
  "$recovery_dir/<state-artifact>.tar.gz.age" \
  "$recovery_dir/<state-artifact>.tar.gz.age.sha256"
./scripts/verify-artifact-sidecar "$recovery_dir/<config-artifact>.tar.gz.age"
./scripts/verify-artifact-sidecar "$recovery_dir/<state-artifact>.tar.gz.age"
```

Transfer the downloaded encrypted files to the Mac or another isolated recovery host holding the age identity. Google Drive must contain only ciphertext and checksum sidecars.

Both restore entry points require the exact adjacent `.sha256` sidecar and fail before decryption or extraction when it is missing, unsafe, or mismatched. There is no production bypass.

Restore configuration first:

```sh
recovery_dir="${NIX_RECOVERY_DIR:-$HOME/.local/share/nix-os-recovery}"
install -d -m 0700 "$recovery_dir/config-root"
AGE_IDENTITY_FILE="$HOME/.config/nix/age/identity.txt" \
CONFIG_RESTORE_ROOT="$recovery_dir/config-root" \
  ./scripts/restore-config \
    "$recovery_dir/<config-artifact>.tar.gz.age" \
    "$recovery_dir/restored-deployment.env"
```

The tool validates outer and inner checksums, restores mode `0600`, and prints only fingerprints. The acceptance drill always targets a new isolated root; never point this step at production `.env` or `/etc/nix-os`. It refuses overwrites unless `CONFIG_RESTORE_FORCE=true` is explicit.

## Isolated recovery proof

Run with the downloaded data object and restored original secret files:

```sh
recovery_dir="${NIX_RECOVERY_DIR:-$HOME/.local/share/nix-os-recovery}"
sudo -E \
  AGE_IDENTITY_FILE="$HOME/.config/nix/age/identity.txt" \
  RESTORE_POSTGRES_ENV_FILE="$recovery_dir/config-root/etc/nix-os/postgres.env" \
  RESTORE_PAPERCLIP_ENV_FILE="$recovery_dir/config-root/etc/nix-os/paperclip.env" \
  RESTORE_HERMES_ENV_FILE="$recovery_dir/config-root/etc/nix-os/hermes.env" \
  RESTORE_FOUNDER_RELAY_ENV_FILE="$recovery_dir/config-root/etc/nix-os/founder-relay.env" \
  RESTORE_SPECIALIST_PROVIDER_ENV_FILE="$recovery_dir/config-root/etc/nix-os/specialist-provider.env" \
  RESTORE_SPECIALIST_WORKER_HOST_KEY_FILE="$recovery_dir/config-root/etc/nix-os/specialist-worker/host_ed25519" \
  RESTORE_SPECIALIST_WORKER_AUTHORIZED_KEYS_FILE="$recovery_dir/config-root/etc/nix-os/specialist-worker/authorized_keys" \
  RESTORE_SPECIALIST_WORKER_CLIENT_KEY_FILE="$recovery_dir/config-root/etc/nix-os/specialist-worker/client_ed25519" \
  RESTORE_PAPERCLIP_COOKIE_FILE="$recovery_dir/paperclip-restore-cookie.<suffix>" \
  RESTORE_NIX_CHIEF_AGENT_ID='<restored NIX_CHIEF_AGENT_ID>' \
  RESTORE_NIX_APPROVED_PROJECT_ID='<restored NIX_APPROVED_PROJECT_ID>' \
  RESTORE_NIX_PRODUCT_AGENT_ID='<restored NIX_PRODUCT_AGENT_ID>' \
  RESTORE_NIX_GROWTH_AGENT_ID='<restored NIX_GROWTH_AGENT_ID>' \
  RESTORE_NIX_OPERATIONS_AGENT_ID='<restored NIX_OPERATIONS_AGENT_ID>' \
  RESTORE_NIX_SPECIALIST_AGENT_IDS='<restored NIX_SPECIALIST_AGENT_IDS>' \
  RESTORE_NIX_PRODUCT_ENVIRONMENT_ID='<restored NIX_PRODUCT_ENVIRONMENT_ID>' \
  RESTORE_NIX_GROWTH_ENVIRONMENT_ID='<restored NIX_GROWTH_ENVIRONMENT_ID>' \
  RESTORE_NIX_OPERATIONS_ENVIRONMENT_ID='<restored NIX_OPERATIONS_ENVIRONMENT_ID>' \
  RESTORE_NIX_SPECIALIST_ENVIRONMENT_IDS='<restored NIX_SPECIALIST_ENVIRONMENT_IDS>' \
  ./scripts/restore-smoke "$recovery_dir/<state-artifact>.tar.gz.age"
```

The smoke refuses production project names and pre-existing target volumes, restores the original external files with mode `0600`, and rejects partial input. Before either application starts it requires both topology gates against the restored database and managed instruction bytes. Starting Paperclip also starts the restored local worker. Through the private Board session, recovery executes all three saved SSH environment probes and requires successful key authentication, while proving the OpenCode credential is not ambient in Paperclip. It then verifies database/file checksums, Hermes health, its restricted API and file boundaries, claimed Chief identity, durable idempotency/outbox state, and Telegram-disabled startup. CI never contacts the real Telegram bot or model provider.

After the isolated proof and evidence capture finish, destroy the isolated Compose project and delete every copy of the dedicated cookie jar from the source and recovery hosts. Signing out that dedicated session in Paperclip is preferred when production remains available; deletion of the jar alone removes the local bearer but does not revoke the server-side session.

A clean restore requires outbound package-registry access to rebuild the deliberately excluded `/opt/data/.npm` and `/opt/data/home/.cache` caches. The Paperclip MCP package remains exactly pinned at `@paperclipai/mcp-server@2026.916.1`; restored Hermes uses fresh npm/uv caches and preserves their normal link/import semantics instead of materializing cache links as regular files.

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
-> the post-`pg_restore` read-only topology gate passes before either application starts: Paperclip has exactly one live root CEO (Chief), Chief has restricted explicit permissions and one receipt-matched Lior-owned standard key, and the retained bootstrap manager is `general`, reports to Chief, remains paused and credentialless, and has `/bin/false`, disabled heartbeat, zero budget, and stripped permissions
-> the post-`pg_restore` specialist topology gate passes before application startup: Product, Growth, and Operations use their distinct SSH environments, retain exact managed instructions and bounded approved-project permissions, reference only the reviewed encrypted SSH/OpenCode secrets, have no API keys, and no Engineering Manager exists
-> after Paperclip startup, the local worker is healthy and each restored Product, Growth, and Operations SSH environment probe authenticates successfully; the provider value remains absent from control-plane process environments
-> Hermes has no staged claim or pending claim marker; backups are accepted only after the verified claim receipt and credential are fully converged
-> when present, restored Hermes Runs idempotency and question-delivery databases match the archived bytes and retain safe ownership/mode; recovery does not replay `pending` or `unknown` Telegram delivery automatically
-> after the isolated runtime is destroyed, production Telegram resumes and Chief answers only Lior
-> OpenCode Go authentication and a live model probe succeed from restored Hermes
-> one harmless restored specialist issue runs through the native runner with the restored encrypted secret references and leaves attributable Paperclip evidence, without creating a specialist Telegram identity or persistent session
-> Chief reads the restored Paperclip issue and read-only nix-brain checkout
-> application and database health pass
-> isolated environment is destroyed
```

Record only non-secret IDs, relationships, SHA-256 values, timestamps, Git SHA, and result.

## Full replacement-host recovery

Only after the isolated proof passes:

1. Rebuild Ubuntu/Docker/Tailscale prerequisites, recreate/prove the `nix` operator, and clone the recorded Git SHA to `/opt/nix-os` as a non-symlinked checkout. Restore the downloaded config pack into the isolated recovery root described above; do not put the age identity on the replacement VPS. On that recovery host, package only the nine restored deployment files (the deployment file, five service/relay/provider files, and all three worker identity files), validate the transfer archive, create a checksum sidecar, preflight a new operator-owned destination, and send both files over the authenticated recovery SSH path:

   ```sh
   # Run on the isolated recovery host after `restore-config` has succeeded.
   umask 077
   recovery_dir="${NIX_RECOVERY_DIR:-$HOME/.local/share/nix-os-recovery}"
   config_stage=$(mktemp -d "$recovery_dir/config-transfer.XXXXXX")
   config_payload="$config_stage/nix-os-config-transfer"
   install -d -m 0700 "$config_payload"
   install -m 0600 "$recovery_dir/restored-deployment.env" "$config_payload/deployment.env"
   for name in postgres paperclip hermes founder-relay specialist-provider; do
     source_file="$recovery_dir/config-root/etc/nix-os/$name.env"
     test -f "$source_file" && test ! -L "$source_file"
     install -m 0600 "$source_file" "$config_payload/$name.env"
   done
   worker_source="$recovery_dir/config-root/etc/nix-os/specialist-worker"
   for mapping in host_ed25519:specialist-worker-host-key \
     authorized_keys:specialist-worker-authorized-keys \
     client_ed25519:specialist-worker-client-key; do
     source_name=${mapping%%:*}
     payload_name=${mapping#*:}
     source_file="$worker_source/$source_name"
     test -f "$source_file" && test ! -L "$source_file"
     install -m 0600 "$source_file" "$config_payload/$payload_name"
   done
   config_archive="$recovery_dir/config-transfer.tar.gz"
   test ! -e "$config_archive" && test ! -e "$config_archive.sha256"
   COPYFILE_DISABLE=1 tar -C "$config_stage" -czf "$config_archive" nix-os-config-transfer
   ./scripts/safe-extract-tar --required-prefix nix-os-config-transfer \
     --validate-only "$config_archive"
   if command -v sha256sum >/dev/null 2>&1; then
     config_digest=$(sha256sum "$config_archive" | awk '{print $1}')
   else
     config_digest=$(shasum -a 256 "$config_archive" | awk '{print $1}')
   fi
   printf '%s  %s\n' "$config_digest" "$(basename "$config_archive")" \
     >"$config_archive.sha256"
   chmod 0600 "$config_archive" "$config_archive.sha256"
   ./scripts/verify-artifact-sidecar "$config_archive"
   ssh nix@<REPLACEMENT_VPS> \
     'set -eu
      umask 077
      recovery_dir="$HOME/.local/share/nix-os-recovery"
      for path in "$HOME/.local" "$HOME/.local/share" "$recovery_dir"; do
        test ! -L "$path"
      done
      install -d -m 0700 "$recovery_dir"
      test -O "$recovery_dir"
      test ! -e "$recovery_dir/config-transfer.tar.gz"
      test ! -e "$recovery_dir/config-transfer.tar.gz.sha256"'
   scp "$config_archive" "$config_archive.sha256" \
     nix@<REPLACEMENT_VPS>:.local/share/nix-os-recovery/
   ```

   In the reviewed checkout on the replacement VPS, reverify and safely extract the archive before root installs any target. A replacement recovery is fail-closed if any target already exists; inspect and remove a partial attempt deliberately instead of overwriting it:

   ```sh
   cd /opt/nix-os
   umask 077
   recovery_dir="${NIX_RECOVERY_DIR:-$HOME/.local/share/nix-os-recovery}"
   config_archive="$recovery_dir/config-transfer.tar.gz"
   test -d /opt/nix-os && test ! -L /opt/nix-os
   test ! -L "$recovery_dir" && test -O "$recovery_dir"
   ./scripts/verify-artifact-sidecar "$config_archive"
   config_work=$(mktemp -d "$recovery_dir/config-install.XXXXXX")
   ./scripts/safe-extract-tar --required-prefix nix-os-config-transfer \
     "$config_archive" "$config_work"
   config_payload="$config_work/nix-os-config-transfer"
   for name in deployment postgres paperclip hermes founder-relay specialist-provider; do
     test -f "$config_payload/$name.env" && test ! -L "$config_payload/$name.env"
   done
   for name in specialist-worker-host-key specialist-worker-authorized-keys specialist-worker-client-key; do
     test -f "$config_payload/$name" && test ! -L "$config_payload/$name"
   done
   sudo sh -ec '
     test ! -e /opt/nix-os/.env
     test ! -e /etc/nix-os && test ! -L /etc/nix-os
     for name in postgres paperclip hermes founder-relay specialist-provider; do
       test ! -e "/etc/nix-os/$name.env"
     done
     test ! -e /etc/nix-os/specialist-worker
   '
   sudo install -d -o root -g root -m 0700 /etc/nix-os
   sudo install -d -o root -g root -m 0700 /etc/nix-os/specialist-worker
   sudo install -o root -g root -m 0600 "$config_payload/deployment.env" /opt/nix-os/.env
   for name in postgres paperclip hermes founder-relay specialist-provider; do
     sudo install -o root -g root -m 0600 \
       "$config_payload/$name.env" "/etc/nix-os/$name.env"
   done
   sudo install -o root -g root -m 0600 \
     "$config_payload/specialist-worker-host-key" \
     /etc/nix-os/specialist-worker/host_ed25519
   sudo install -o root -g root -m 0600 \
     "$config_payload/specialist-worker-authorized-keys" \
     /etc/nix-os/specialist-worker/authorized_keys
   sudo install -o root -g root -m 0600 \
     "$config_payload/specialist-worker-client-key" \
     /etc/nix-os/specialist-worker/client_ed25519
   ```

   Do not run Compose yet. Keep both plaintext transfer archives and extracted work directories only until replacement-host acceptance is complete, then securely remove them on their respective hosts.
2. Re-clone canonical `nix-brain` at the configured host path. It is Git-reconstructible and is not part of the state backup. Keep the checkout root non-symlinked and private with group read/traverse and no permissions for other users. On the replacement host, resolve the restored path without printing the deployment file, require a fresh absolute target, clone as the operator, record its actual group ID, update only the non-secret `NIX_BRAIN_GID` line, and validate the complete restored configuration before Compose runs:

   ```sh
   cd /opt/nix-os
   brain_path=$(sudo awk -F= '$1 == "NIX_BRAIN_HOST_PATH" { print substr($0, length($1) + 2) }' .env)
   case "$brain_path" in
     /*) ;;
     *) printf '%s\n' 'NIX_BRAIN_HOST_PATH must be absolute' >&2; exit 1 ;;
   esac
   test ! -e "$brain_path" && test ! -L "$brain_path"
   sudo install -d -o nix -g nix -m 0750 "$brain_path"
   git clone git@github.com:Lior-Nis/nix-brain.git "$brain_path"
   chmod 0750 "$brain_path"
   test -d "$brain_path" && test ! -L "$brain_path" && test -O "$brain_path"
   brain_gid=$(stat -c '%g' "$brain_path")
   case "$brain_gid" in
     ''|0|*[!0-9]*) printf '%s\n' 'unsafe nix-brain group ID' >&2; exit 1 ;;
   esac
   sudo sed -i -E "s/^NIX_BRAIN_GID=.*/NIX_BRAIN_GID=$brain_gid/" .env
   sudo -E ./scripts/check-config "$PWD/.env"
   ```

   A replacement host need not reuse the old host's group ID, but the selected value must not collide with the pinned Hermes image's system-group inventory. If `check-config` reports a collision, create a dedicated nonzero host group, assign the checkout to it, repeat the update with that numeric GID, and re-run the check; never make the private checkout world-readable.
3. Run `sudo -E ./scripts/configure-hermes telegram-disable "$PWD/.env"` before any Compose command. The mode marker is intentionally excluded from the config pack, so a replacement host always starts Telegram-disabled until explicit cutover. At container entry, any legacy Telegram variables in the restored profile `.env` are atomically removed before Hermes starts; the external root-owned secret file remains the only Telegram credential source. Confirm target volumes do not exist, then create every service without starting it:

   ```sh
   project_name=$(sudo awk -F= '$1 == "COMPOSE_PROJECT_NAME" { print substr($0, length($1) + 2) }' "$PWD/.env")
   case "$project_name" in
     ''|*[!A-Za-z0-9_-]*) printf '%s\n' 'unsafe COMPOSE_PROJECT_NAME' >&2; exit 1 ;;
   esac
   paperclip_volume="${project_name}_paperclip_data"
   runner_cache_volume="${project_name}_paperclip_runner_cache"
   postgres_volume="${project_name}_postgres_data"
   hermes_volume="${project_name}_hermes_data"
   for volume in "$paperclip_volume" "$runner_cache_volume" "$postgres_volume" "$hermes_volume"; do
     if sudo docker volume inspect "$volume" >/dev/null 2>&1; then
       printf 'refusing existing recovery volume: %s\n' "$volume" >&2
       exit 1
     fi
   done
   sudo -E docker compose --env-file "$PWD/.env" create postgres paperclip hermes
   ```

   The Paperclip runner-cache volume is reconstructible and must start empty; it is rebuilt and hash-verified by the pinned Paperclip entrypoint rather than restored from the state artifact.
4. Keep the age identity on the isolated recovery host. There, verify the downloaded encrypted artifact and decrypt it to one temporary plaintext transfer archive; verify that plaintext archive completely before sending it over the authenticated recovery SSH path:

   ```sh
   # Run on the isolated recovery host that holds the age identity.
   umask 077
   recovery_dir="${NIX_RECOVERY_DIR:-$HOME/.local/share/nix-os-recovery}"
   state_artifact="$recovery_dir/<state-artifact>.tar.gz.age"
   AGE_IDENTITY_FILE="$HOME/.config/nix/age/identity.txt"
   test ! -L "$recovery_dir"
   test -O "$recovery_dir"
   ./scripts/verify-artifact-sidecar "$state_artifact"
   transfer_archive="$recovery_dir/state-transfer.tar.gz"
   test ! -e "$transfer_archive" && test ! -e "$transfer_archive.sha256"
   age --decrypt --identity "$AGE_IDENTITY_FILE" \
     --output "$transfer_archive" "$state_artifact"
   transfer_check=$(mktemp -d "$recovery_dir/transfer-check.XXXXXX")
   ./scripts/safe-extract-tar --required-prefix nix-os- \
     "$transfer_archive" "$transfer_check"
   transfer_payload=$(find "$transfer_check" -mindepth 1 -maxdepth 1 \
     -type d -name 'nix-os-*' -print)
   case "$transfer_payload" in
     ''|*$'\n'*) printf '%s\n' 'state archive must contain exactly one payload directory' >&2; exit 1 ;;
   esac
   ./scripts/verify-backup-checksums "$transfer_payload"
   ./scripts/safe-extract-tar --validate-only --allow-dot-root \
     "$transfer_payload/paperclip-data.tar.gz"
   ./scripts/safe-extract-tar --validate-only --allow-dot-root \
     "$transfer_payload/hermes-data.tar.gz"
   if command -v sha256sum >/dev/null 2>&1; then
     transfer_digest=$(sha256sum "$transfer_archive" | awk '{print $1}')
   else
     transfer_digest=$(shasum -a 256 "$transfer_archive" | awk '{print $1}')
   fi
   printf '%s  %s\n' "$transfer_digest" "$(basename "$transfer_archive")" \
     >"$transfer_archive.sha256"
   chmod 0600 "$transfer_archive" "$transfer_archive.sha256"
   ./scripts/verify-artifact-sidecar "$transfer_archive"
   ssh nix@<REPLACEMENT_VPS> \
     'set -eu
      umask 077
      recovery_dir="$HOME/.local/share/nix-os-recovery"
      for path in "$HOME/.local" "$HOME/.local/share" "$recovery_dir"; do
        test ! -L "$path"
      done
      install -d -m 0700 "$recovery_dir"
      test -O "$recovery_dir"
      test ! -e "$recovery_dir/state-transfer.tar.gz"
      test ! -e "$recovery_dir/state-transfer.tar.gz.sha256"'
   scp "$transfer_archive" "$transfer_archive.sha256" \
     nix@<REPLACEMENT_VPS>:.local/share/nix-os-recovery/
   ```

   The age identity never leaves the recovery host. On the replacement VPS, verify the transferred plaintext archive again, safely extract it to a new operator-owned directory, revalidate its internal checksums, and reject unsafe members in both nested archives before any target volume is emptied:

   ```sh
   # Run in the reviewed nix-os checkout on the replacement VPS.
   umask 077
   recovery_dir="${NIX_RECOVERY_DIR:-$HOME/.local/share/nix-os-recovery}"
   transfer_archive="$recovery_dir/state-transfer.tar.gz"
   test ! -L "$recovery_dir" && test -O "$recovery_dir"
   ./scripts/verify-artifact-sidecar "$transfer_archive"
   restore_work=$(mktemp -d "$recovery_dir/full-restore.XXXXXX")
   ./scripts/safe-extract-tar --required-prefix nix-os- \
     "$transfer_archive" "$restore_work"
   payload_dir=$(find "$restore_work" -mindepth 1 -maxdepth 1 \
     -type d -name 'nix-os-*' -print)
   case "$payload_dir" in
     ''|*$'\n'*) printf '%s\n' 'state archive must contain exactly one payload directory' >&2; exit 1 ;;
   esac
   ./scripts/verify-backup-checksums "$payload_dir"
   ./scripts/safe-extract-tar --validate-only --allow-dot-root \
     "$payload_dir/paperclip-data.tar.gz"
   ./scripts/safe-extract-tar --validate-only --allow-dot-root \
     "$payload_dir/hermes-data.tar.gz"
   ```

   The single-directory checks must succeed exactly once on both hosts. If any verifier fails, stop; do not empty a volume or substitute raw `tar` inspection. After the restored services and downloaded-artifact acceptance checks pass, securely remove the plaintext transfer archive, its sidecar, and both extracted work directories. The encrypted `.age` object may remain; the private age identity and its escrow never enter the VPS.
5. Restore `/paperclip` and Hermes `/opt/data` with the pinned PostgreSQL image as the archive helper:

   ```sh
   archive_helper='postgres:17.11-alpine3.24@sha256:b0f9560a2de083e2cc7382e75f808c7381a32852a7ec49117deedb300e552b24'
   sudo docker run --rm --network none --read-only --tmpfs /tmp \
     --volume "$paperclip_volume:/target" \
     --volume "$payload_dir:/backup:ro" \
     "$archive_helper" \
     sh -ec 'find /target -mindepth 1 -delete && cd /target && tar -xzf /backup/paperclip-data.tar.gz'
   sudo docker run --rm --network none --read-only --tmpfs /tmp \
     --volume "$hermes_volume:/target" \
     --volume "$payload_dir:/backup:ro" \
     "$archive_helper" \
     sh -ec 'find /target -mindepth 1 -delete && cd /target && tar -xzf /backup/hermes-data.tar.gz'
   ```

   The raw extraction is permitted only after both nested archives passed `safe-extract-tar --validate-only`; that validator accepts directories and regular files only and rejects links, special files, duplicate paths, and escapes. The `find` deletion is safe here only because step 3 proved these are newly created recovery volumes; it removes image-seeded defaults before exact archive restoration. Do not restore the reconstructible runner-cache volume.

6. Start only PostgreSQL, restore the verified dump, and run both topology gates before either application starts:

   ```sh
   sudo -E docker compose --env-file "$PWD/.env" up -d --wait postgres
   sudo -E docker compose --env-file "$PWD/.env" exec -T postgres \
     pg_restore --username paperclip --dbname paperclip \
       --clean --if-exists --no-owner --no-privileges \
       <"$payload_dir/postgres.dump"
   sudo -E ./scripts/check-paperclip-chief-topology "$PWD/.env"
   sudo -E ./scripts/check-paperclip-specialist-topology "$PWD/.env"
   sudo -E ./scripts/check-migrations "$PWD/.env"
   sudo -E docker compose --env-file "$PWD/.env" up -d --wait paperclip hermes
   ```

   The Chief gate proves the claimed Chief, restricted permissions, sole-root topology, inert bootstrap manager, and receipt-matched key ownership. The specialist gate proves three role-specific SSH environments, exact encrypted secret bindings, managed instruction bytes, no extra runner or sandbox plugin, and no specialist API key or Engineering Manager. Paperclip starts the restored worker dependency and each saved environment is probed through the supported Board API.
7. Run `scripts/configure-tailscale` to reconstruct the node name, Nix-owned Paperclip handler, and—when UFW is active—the single project-owned exact-worker-egress-IP-to-tailnet TCP 443 rule without changing unrelated routes. The command never enables inactive UFW; in either firewall state it validates the worker IP against the restored private Compose subnet and verifies CA-valid `/api/health` from the restored worker. Verify tailnet health and Paperclip public non-exposure, including that Hermes ports 8642, 8644, and 9119 are not host-published.
8. Run `scripts/configure-hermes verify` and both topology gates while Telegram remains disabled. Verify Chief and the inert bootstrap manager, then execute one harmless restored issue per specialist role through its saved local SSH environment without giving any worker an API key or Telegram identity. Only after proving any previous poller for this exact bot token is stopped, enable Telegram, force-recreate only Hermes, and rerun the verifier:

   ```sh
   sudo -E ./scripts/configure-hermes telegram-enable "$PWD/.env"
   sudo -E docker compose --env-file "$PWD/.env" up -d --no-deps --wait --force-recreate hermes
   sudo -E ./scripts/configure-hermes verify "$PWD/.env"
   ```

   On rollback, stop Hermes, disable the marker, force-recreate only Hermes, and run `scripts/configure-hermes verify-processes` before starting another poller for the same token. If recreation or verification fails, stop Hermes again and leave every same-token poller disabled until the failure is diagnosed. Do not stop or restart gateways for distinct bots. Replacing the individually bind-mounted marker without recreating the container is not a durable rollback. Securely remove decrypted temporary files. Never restore over running production volumes.

V0 targets manual RTO <= 8 hours when a current verified artifact is available; it does not claim an unattended RPO. Run the authenticated state-backup ceremony after meaningful non-reconstructible state changes and immediately before and after consequential deployment or configuration transitions, and create a config pack after every configuration change. The required broad Board session is short-lived and must never be stored for cron or retained in backup artifacts. Keep the monthly downloaded-off-host restore. Adopt an unattended schedule/RPO only after upstream provides a least-privilege readiness credential that can be automated without weakening the pre-stop specialist gate.
