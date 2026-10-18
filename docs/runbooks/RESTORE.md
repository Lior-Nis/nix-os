# Nix backup and restore runbook

## Recovery layers

| Layer | Contents | Recovery source |
|---|---|---|
| Git repository | Compose, scripts, tests, and redacted documentation | exact reviewed Git commit |
| Encrypted configuration pack | deployment `.env`; PostgreSQL, Paperclip, Hermes, and founder-relay env files; and the specialist Daytona/OpenCode provider-import file | `gdrive:Nix/backups/config/` |
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

The script reads the deployment file plus the referenced external credential files, creates no plaintext pack, uses mode `0600`, and logs only non-secret checksums/paths. `hermes.env` contains the Telegram, Runs API, OpenCode Go, and fixed decision-webhook credentials plus the external-only Telegram home-chat setting. `founder-relay.env` contains the separate relay HMAC secret and pinned direct-message identity. `specialist-provider.env` contains exactly the Daytona and restricted OpenCode values used only for deliberate import/rotation into Paperclip's encrypted company secret store; it is never mounted or injected into a service. The separately claimed Chief Paperclip agent key lives in the Hermes volume, while specialist secret values also survive inside the encrypted Paperclip database/volume state. A legacy or additional provider `auth.json` is preserved and permission-checked when present, but OpenCode Go recovery does not require synthetic OAuth state. The rclone config is intentionally excluded because it is the credential used to fetch these packs. Preserve the exact config in a separate age-encrypted escrow outside this Drive; a new or different OAuth client cannot assume visibility of the `drive.file` objects.

## Back up Paperclip and Hermes data

The data backup first requires both the accepted Chief topology and the complete specialist topology—including exactly three idle and no other nonterminated `paperclip_runner` workers, the exact Git-tracked Product/Growth/Operations managed instruction bytes, the ready Daytona manifest record, their bounded sandbox environment, the exact two secret-binding rows, two encrypted Paperclip secret records, and no specialist API keys. It also requires a private authenticated Board cookie jar and uses it before shutdown to prove that the live plugin worker advertises saved/unsaved probe and run execution, that the supported environment and secret-metadata APIs match the recorded topology, and that the installed `@paperclipai/plugin-daytona@2026.916.1` npm package under `/paperclip` retains the reviewed package-lock integrity, a complete dependency tree, and exact critical executable files. Paperclip records the plugin manifest version `0.1.7` in its API/database; the package lock is the authority for the distinct npm release version. This catches a loaded-but-deleted or partially damaged plugin before its only recoverable copy is archived. It refuses while any specialist run is queued, scheduled for retry, or running, or a Daytona lease is active, retained, or pending cleanup, so the database cannot preserve an ambiguous remote side effect. The query admits only the pinned release's documented terminal run and lease statuses; an unknown future status also blocks capture. It stops Hermes and Paperclip, repeats the database-and-volume topology gates against the quiesced state, then creates a coordinated PostgreSQL dump plus `/paperclip` and Hermes `/opt/data` archives; it does not require an application API after shutdown. It restarts Paperclip and then Hermes. The Hermes archive includes every durable `/opt/data` file, including `/opt/data/runs_idempotency.db` and `/opt/data/state/paperclip-question-delivery.db` when present; backup refuses either database if it is not a regular single-link uid/gid `10000:10000`, mode-`0600` file. The reconstructible `/opt/data/.npm` and `/opt/data/home/.cache` npm/uv caches are excluded and must be fetched again from exact package pins during recovery. Paperclip npm `.bin` links are also reconstructible and excluded, while all package files and dependency metadata remain archived. Any symlink outside those reviewed cache locations or any special file fails backup. Source hardlinks may be materialized as independent regular archive members—for example, Hermes uv lazy packages linked to its excluded cache—but the post-build validator rejects any link member encoded in either archive; published inner archives contain directories and regular files only. The databases are non-reconstructible execution/delivery evidence, not caches.

Before every state backup, create one dedicated authenticated Paperclip session immediately before capture. The backup uses it for the live specialist readiness check, and its server-side session row is then present in the PostgreSQL dump. Keep its Netscape cookie jar only on the trusted recovery path; it is a temporary broad board session, not a backup artifact, and must never be uploaded to Drive, committed, pasted into a command, or logged. For a downloaded-artifact acceptance drill, retain this same private jar until the isolated restore finishes; after an ordinary backup, securely discard it once capture succeeds:

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
  RESTORE_PAPERCLIP_COOKIE_FILE="$recovery_dir/paperclip-restore-cookie.<suffix>" \
  RESTORE_NIX_CHIEF_AGENT_ID='<restored NIX_CHIEF_AGENT_ID>' \
  RESTORE_NIX_APPROVED_PROJECT_ID='<restored NIX_APPROVED_PROJECT_ID>' \
  RESTORE_NIX_PRODUCT_AGENT_ID='<restored NIX_PRODUCT_AGENT_ID>' \
  RESTORE_NIX_GROWTH_AGENT_ID='<restored NIX_GROWTH_AGENT_ID>' \
  RESTORE_NIX_OPERATIONS_AGENT_ID='<restored NIX_OPERATIONS_AGENT_ID>' \
  RESTORE_NIX_SPECIALIST_AGENT_IDS='<restored NIX_SPECIALIST_AGENT_IDS>' \
  RESTORE_NIX_SPECIALIST_ENVIRONMENT_ID='<restored NIX_SPECIALIST_ENVIRONMENT_ID>' \
  ./scripts/restore-smoke "$recovery_dir/<state-artifact>.tar.gz.age"
```

The smoke refuses production project names and any pre-existing PostgreSQL, Paperclip, Hermes, or Paperclip runner-cache volume, then restores into fresh isolated state. It copies the original founder-relay and specialist provider files into the isolated root with mode `0600`; partial external-config input fails closed. `check-config` proves the restored HMAC identity matches the restored Hermes DM allowlist and the provider-import file contains exactly non-placeholder `DAYTONA_API_KEY` and `OPENCODE_API_KEY` bindings. The specialist agent/environment IDs supplied above are non-secret values from the restored deployment file; do not substitute invented identities during a production recovery drill. After `pg_restore` and before either application starts, the smoke requires both the Chief and specialist topology gates. `RESTORE_REQUIRE_SPECIALIST_TOPOLOGY=false` exists only for the repository's historical pre-Slice-3 recovery fixture and must never be used for a Slice 3 production artifact. After Paperclip starts, the private cookie permits only metadata/readiness verification through supported Board APIs: the exact installed plugin is ready, the live company capabilities route exposes the running Daytona worker for saved probes and run execution, the exact sandbox environment references both restored secret records, and neither credential appears in Paperclip's host environment. Recovery does not create a billable sandbox or reveal a credential. The accepted Slice 1 recovery evidence exercised its historical nine approved MCP operations across identity, existing-project reads, issue create/list/get/update, and comment add/list; that evidence remains unchanged. The Slice 2 configuration expands the exact boundary to eleven by adding checkout and structured questions while still exposing no project/goal/admin mutation or arbitrary API tool. Against the real pinned Paperclip server and official MCP package, the fixture uses supported heartbeat runs to prove checkout, run-attributed issue update/comment/child creation, a forced human-only question addressed to the pinned Lior user with the trusted source run, idempotent exact-key replay, a competing-run HTTP-409 checkout conflict, and transition to `in_review`. It cancels the runs and restores the agent's `hermes_gateway` configuration before backup. The authoritative interaction and genuine Runs idempotency state feed the recovery assertions; a synthetic transport-unknown delivery row additionally proves the conservative no-replay rule. Because Docker may seed a newly attached named volume from image contents during container creation, the script empties each already-validated fresh application volume immediately before extracting its archive. It compares database counts plus every `/paperclip` and Hermes `/opt/data` file hash and verifies Paperclip health. When `runs_idempotency.db` or `state/paperclip-question-delivery.db` was present in the manifest, restore additionally requires the corresponding file to be regular, single-link, uid/gid `10000:10000`, and mode `0600`. The in-memory contract model remains regression coverage only; this Docker smoke is the real pinned integration and restore evidence. It then boots restored Hermes behind a fresh root-owned disabled marker. The isolated checkout generator records the temporary brain directory's actual numeric group ID, and Compose grants only that supplemental group to Hermes; this works with ordinary Linux temporary directories and Docker Desktop bind mounts without making the checkout world-readable. The entrypoint uses the pinned dotenv parser to remove even BOM-prefixed or quoted legacy Telegram controls from restored profile state before clearing the external token and starting upstream supervision. The test proves Hermes health, API-server `401` without the restored key, authenticated API success, the exact restricted API/runtime tool surface and actual file boundary, fixed loopback webhook configuration, an exact file-tool read of tracked brain Markdown plus denied write, Chief profile and receipt presence, and bounded `paperclipMe` identity against isolated restored Paperclip. Neither the selected brain filename nor its contents are logged. CI additionally verifies login, company/project/parent-child relationships, comments, human-only interaction policy/run attribution, attachment checksum, and metadata-only specialist recovery without revealing plaintext. CI does not contact the real Telegram bot or model provider.

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
-> the post-`pg_restore` specialist topology gate also passes before application startup: exactly Product, Growth, and Operations use `paperclip_runner`, report to Chief, retain the exact Git-tracked managed instruction bundle bytes, share only the approved-project low-trust boundary and the exact Daytona environment, reference the two expected encrypted secrets, have no API keys, and no Engineering Manager exists
-> after Paperclip startup, the Daytona manifest record (`0.1.7`) is ready, the archived package lock proves npm release `@paperclipai/plugin-daytona@2026.916.1`, and the supported company capabilities route proves its worker can probe and execute saved environments; neither provider value is exposed or inherited as a host environment variable
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

1. Rebuild Ubuntu/Docker/Tailscale prerequisites, recreate/prove the `nix` operator, and clone the recorded Git SHA to `/opt/nix-os` as a non-symlinked checkout. Restore the downloaded config pack into the isolated recovery root described above; do not put the age identity on the replacement VPS. On that recovery host, package only the six restored deployment files, validate the transfer archive, create a checksum sidecar, preflight a new operator-owned destination, and send both files over the authenticated recovery SSH path:

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
   sudo sh -ec '
     test ! -e /opt/nix-os/.env
     test ! -e /etc/nix-os && test ! -L /etc/nix-os
     for name in postgres paperclip hermes founder-relay specialist-provider; do
       test ! -e "/etc/nix-os/$name.env"
     done
   '
   sudo install -d -o root -g root -m 0700 /etc/nix-os
   sudo install -o root -g root -m 0600 "$config_payload/deployment.env" /opt/nix-os/.env
   for name in postgres paperclip hermes founder-relay specialist-provider; do
     sudo install -o root -g root -m 0600 \
       "$config_payload/$name.env" "/etc/nix-os/$name.env"
   done
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

   The Chief gate must prove the claimed Chief, restricted permissions, sole-root topology, inert bootstrap manager, and API-key ownership from the restored database and Hermes claim receipt. The specialist gate must prove the exact three task-scoped workers, approved-project trust boundary, exact Daytona plugin/environment metadata, secret-reference fingerprints, and absence of worker API keys or an Engineering Manager. Format-3 state artifacts carry the non-secret pinned Lior Paperclip user ID required for the Chief check. When recovering an older format-2 artifact, set `RESTORE_PAPERCLIP_LIOR_USER_ID` to the value in that artifact's matching external configuration pack. Paperclip must rebuild or verify its provider-pack cache and recover the installed plugin worker before it becomes healthy; verify that worker through the supported company capabilities route.
7. Run `scripts/configure-tailscale` to reconstruct the node name and Nix-owned Paperclip handler without changing unrelated routes. Verify tailnet health and Paperclip public non-exposure, including that Hermes ports 8642, 8644, and 9119 are not host-published.
8. Run `scripts/configure-hermes verify` and both topology gates while Telegram remains disabled, then repeat CEO/company/issue/attachment/secret and Chief memory/Paperclip checks. In Paperclip, verify Chief is the only root CEO and the retained bootstrap manager is paused, credentialless, `general`, and reports to Chief; do not delete it on the pinned release. Verify Product, Growth, and Operations retain their exact task-scoped configuration and execute one harmless restored issue through a fresh Daytona sandbox without receiving an API key or Telegram identity. Inspect only supported plugin/environment/secret metadata and the resulting run evidence; never print process environments or secret values. Only after proving any previous poller for this exact bot token is stopped, run `scripts/configure-hermes telegram-enable`, force-recreate only Hermes, and immediately run the full verifier again. A gateway using a separately validated, distinct bot token is unrelated and remains active:

   ```sh
   sudo -E ./scripts/configure-hermes telegram-enable "$PWD/.env"
   sudo -E docker compose --env-file "$PWD/.env" up -d --no-deps --wait --force-recreate hermes
   sudo -E ./scripts/configure-hermes verify "$PWD/.env"
   ```

   On rollback, stop Hermes, disable the marker, force-recreate only Hermes, and run `scripts/configure-hermes verify-processes` before starting another poller for the same token. If recreation or verification fails, stop Hermes again and leave every same-token poller disabled until the failure is diagnosed. Do not stop or restart gateways for distinct bots. Replacing the individually bind-mounted marker without recreating the container is not a durable rollback. Securely remove decrypted temporary files. Never restore over running production volumes.

V0 targets manual RTO <= 8 hours when a current verified artifact is available; it does not claim an unattended RPO. Run the authenticated state-backup ceremony after meaningful non-reconstructible state changes and immediately before and after consequential deployment or configuration transitions, and create a config pack after every configuration change. The required broad Board session is short-lived and must never be stored for cron or retained in backup artifacts. Keep the monthly downloaded-off-host restore. Adopt an unattended schedule/RPO only after upstream provides a least-privilege readiness credential that can be automated without weakening the pre-stop specialist gate.
