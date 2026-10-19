# Nix deployment runbook

The accepted foundation runs Paperclip, PostgreSQL, and exactly one internal Hermes service with tailnet-only ingress on one Hostinger VPS. The Slice 3 extension adds task-scoped workers in fresh credential-minimal Daytona sandboxes while Chief remains the only persistent Telegram employee; it adds no internal executor service or host listener. Commands run from a clean clone at a reviewed commit. Tailscale is a host prerequisite, not a Compose service.

## Supported VPS baseline

The tested V0 host is Ubuntu 24.04 LTS on x86_64/amd64. It needs Docker Engine 27+, Docker Compose 2.30+, Git, Bash, curl, OpenSSL, tar, GNU `sha256sum`, `age`, `jq`, `rclone`, Tailscale, 10 GiB free below `/var/lib/docker`, and a reachable Docker daemon. Tailscale must already be joined and connected.

Run the read-only check:

```sh
./scripts/vps-preflight
```

## Access and exposure contract

- Public Internet: emergency SSH only for Nix; no Paperclip, PostgreSQL, or Nix listener is public. Independently owned cohosted services may have their own exposure policy.
- Tailnet: ordinary SSH to `nix-os` and Paperclip HTTPS through Tailscale Serve.
- Host loopback: Paperclip at `127.0.0.1:${PAPERCLIP_HOST_PORT:-3100}`.
- Compose internal networks: PostgreSQL alone with Paperclip on `data`; Paperclip and Hermes on internal `agent`; Hermes alone on `hermes_egress`; Paperclip uses `app` for required outbound access, including Daytona.
- Never run `tailscale funnel` for Paperclip or the Nix-owned `:443` endpoint.

Keep the current `root@<VPS_PUBLIC_IP>` SSH recovery path until the `nix` path is proven. Resolve the real address from Lior's local SSH configuration; do not publish it in repository documentation. Do not change sshd or firewall recovery policy during this amendment.

## Repository and external prerequisites

V0 uses this convention instead of paid GitHub branch protection:

```text
feature branch -> PR -> hosted CI green -> review when consequential -> merge
```

Agents must not intentionally push directly to `main`. Before deploying, require both hosted `foundation` and `recovery` jobs to pass on the amendment PR and deploy the recorded merged `main` SHA.

Other prerequisites are Hostinger root SSH access, Tailscale membership with MagicDNS, an age recipient whose private identity is held off the VPS, and a Google Drive `rclone` remote. If Tailscale HTTPS is not enabled, the CLI will surface the Tailscale admin consent URL; enable MagicDNS/HTTPS there and acknowledge certificate-transparency publication of the machine/tailnet names, then rerun the command.

## Create and prove the `nix` operator

Run once over the existing root recovery session. Reuse Lior's existing authorized key; do not copy private key material.

```sh
adduser --disabled-password --gecos '' nix
install -d -o nix -g nix -m 0700 /home/nix/.ssh
install -o nix -g nix -m 0600 /root/.ssh/authorized_keys /home/nix/.ssh/authorized_keys
usermod -aG sudo,docker nix
printf 'nix ALL=(ALL:ALL) NOPASSWD: ALL\n' >/etc/sudoers.d/nix-os-operator
chmod 0440 /etc/sudoers.d/nix-os-operator
visudo -cf /etc/sudoers.d/nix-os-operator
tailscale set --hostname=nix-os
tailscale set --operator=nix
```

From Lior's tailnet-connected Mac, prove all three before relying on this path:

```sh
ssh nix@nix-os 'id && sudo -n true && docker info >/dev/null'
```

Keep root/public-IP recovery available. Review its tightening separately only after recovery access has been considered.

## First deployment

1. As `nix`, clone the public `nix-os` repository into an operator-owned directory, check out the reviewed merged SHA, and run `./scripts/vps-preflight`. `nix-brain` remains a separate private clone.

2. Create configuration:

   ```sh
   cp .env.example .env
   chmod 0600 .env
   editor .env
   ```

   Run `tailscale status --json | jq -r '.Self.DNSName'` after naming the host. Remove its trailing dot and set `PAPERCLIP_PUBLIC_URL=https://<that-fqdn>`. It must be the real `https://nix-os.<tailnet-name>.ts.net`, never a guessed suffix. Leave the loopback port at 3100 unless it conflicts. For a fresh deployment of the current stack, create the private brain checkout as described in the Slice 1 section below and set both `NIX_BRAIN_HOST_PATH` and its actual positive numeric `NIX_BRAIN_GID` before running either secret initializer; initialization fails closed if they disagree.

3. Generate external service secrets outside the checkout:

   ```sh
   sudo CONFIG_FILE="$PWD/.env" ./scripts/init-secrets "$PWD/.env"
   sudo chown root:root /etc/nix-os/postgres.env /etc/nix-os/paperclip.env
   sudo chmod 0600 /etc/nix-os/postgres.env /etc/nix-os/paperclip.env
   ```

4. Validate and deploy the Compose services:

   ```sh
   sudo -E CONFIG_FILE="$PWD/.env" ./scripts/check-config "$PWD/.env"
   sudo -E CONFIG_FILE="$PWD/.env" ./scripts/ops deploy
   ```

   This starts PostgreSQL, performs the read-only migration preflight, provisions and validates official `authenticated/private` Paperclip configuration, and starts Paperclip. Paperclip listens on `0.0.0.0:3100` inside its isolated container namespace so Docker can forward it; Docker publishes the port only at VPS host `127.0.0.1:3100`.

5. Configure reconstructible tailnet ingress:

   ```sh
   CONFIG_FILE="$PWD/.env" ./scripts/configure-tailscale "$PWD/.env"
   ```

   Run this as `nix`. Nix owns the TCP `443` HTTPS listener, `/` at its `fqdn:443` web host, and the absence of a Funnel entry for that endpoint. Sibling paths remain foreign state. PDM on tailnet port `8443` and Hatch on Funnel port `10000` are independently owned examples of valid cohosted state. The script uses sudo to set hostname `nix-os`, grant CLI operator status to `nix`, and retain root-only failure evidence. Before mutation, it allows TCP `443` to be absent or exactly the HTTPS listener and rejects a conflicting listener or any foreground session claiming TCP `443` or the same web host. It then applies the persistent root handler in place with `--https=443 --set-path=/`; this also clears any existing top-level Funnel entry for the owned endpoint. The postcondition verifies the exact Paperclip target, requires the Funnel entry to be absent, and proves all unrelated parsed state is structurally unchanged. It never runs `tailscale serve reset`. Re-run the same script on a replacement VPS; the Nix handler is reconstructible and is not backed up.

   The before/after comparison is fail-visible, not transactional. If the command fails after mutation or the preservation check detects a change, do not rerun it and do not use `tailscale serve reset`. The error reports a root-only directory under `/var/lib/nix-os/tailscale-failures/` containing the available `before.json` and `final.json` snapshots. Inspect them with `sudo`, compare them with a fresh `tailscale serve status --json`, and restore only the affected foreign route using its owning service's documented command. Once current state again matches the preserved pre-change state outside Nix's owned fields, resolve the reported collision and rerun this script. The snapshots contain no credentials, but keep them root-only because they inventory private hostnames and local service targets.

6. Verify actual exposure from both contexts:

   ```sh
   sudo ss -lntup
   sudo docker compose --env-file .env ps
   tailscale serve status --json | ./scripts/check-tailscale-serve-state \
     --expect paperclip --fqdn nix-os.<tailnet-name>.ts.net \
     --target http://127.0.0.1:3100 /dev/stdin
   curl -fsS https://nix-os.<tailnet-name>.ts.net/api/health
   ```

   From a machine outside the VPS and outside the tailnet, probe the public VPS address:

   ```sh
   nmap -Pn -p 80,443,3100,5432,8443,10000 <VPS_PUBLIC_IP>
   ```

   Ports `443`, `3100`, and `5432` must not expose Nix publicly. Attribute every response on another listed port to its actual owner and verify it is not Paperclip; Compose inspection is not a substitute. Prove specifically that Paperclip's Tailscale endpoint is not public:

   ```sh
   if curl --silent --show-error --connect-timeout 5 \
     "https://nix-os.<tailnet-name>.ts.net:443/" >/dev/null; then
     printf '%s\n' 'unexpected public Paperclip Tailscale endpoint on port 443' >&2
     exit 1
   fi
   ```

   Failure to resolve or connect on `443` is expected outside the tailnet. From a tailnet device, confirm Paperclip works only through normal HTTPS `:443` and the certificate hostname matches. Do not alter or use responses on `8443`/`10000` as Paperclip evidence; verify those independently owned services remain unchanged. Also verify `ssh nix@nix-os`.

7. Bootstrap in the browser using Paperclip's supported private-instance path:

   - Open the real Tailscale HTTPS URL. Confirm anonymous access requires authentication.
   - Create Lior's account while signup is temporarily enabled.
   - Use the UI's **Claim this instance** action. Verify the user is CEO/admin and `/api/health` reports `bootstrapStatus: ready`.
   - If browser claim is unavailable, `./scripts/ops bootstrap-ceo` is the verified official CLI-invite fallback; never record its URL.
   - Set `PAPERCLIP_AUTH_DISABLE_SIGN_UP=true` in `.env`, then run `sudo -E CONFIG_FILE="$PWD/.env" ./scripts/ops restart`.
   - In a private browser session verify new signup is rejected. Sign out and back in as the existing CEO.

8. Create a fresh encrypted configuration pack after closing signup and upload it using the restore runbook. Then create the recovery canaries and data backup described there.

## Google Drive setup (live interactive step)

Run `rclone config` interactively as the `nix` operator using the explicit path `/home/nix/.config/rclone/rclone.conf`. Create remote `gdrive` using Lior's Google Drive account, an owned Google Desktop OAuth client ID, and the least-privilege `drive.file` scope; rclone's shared client ID is being retired during 2026. Complete browser OAuth interactively only when the encrypted upload/download test is ready. Create the backup root through this client and configure its `root_folder_id`, so the client does not need visibility into unrelated Drive content. After the upload/download test, harden both the directory and file to root ownership (`root:root`, modes `0700` and `0600`) and thereafter invoke every transfer as `sudo rclone --config /home/nix/.config/rclone/rclone.conf ...`; the ordinary operator must not retain a second readable copy:

```sh
rclone --config /home/nix/.config/rclone/rclone.conf config
rclone --config /home/nix/.config/rclone/rclone.conf lsf gdrive: --max-depth 1 >/dev/null
sudo chown root:root /home/nix/.config/rclone /home/nix/.config/rclone/rclone.conf
sudo chmod 0700 /home/nix/.config/rclone
sudo chmod 0600 /home/nix/.config/rclone/rclone.conf
sudo rclone --config /home/nix/.config/rclone/rclone.conf lsf gdrive: --max-depth 1 >/dev/null
```

The resulting rclone config is a runtime secret outside Git. Escrow an age-encrypted copy separately from this Drive because the refresh token and OAuth client identity are required to regain access after host loss.

Use only:

```text
gdrive:Nix/backups/config/
gdrive:Nix/backups/state/
```

Only `.age` objects and checksum sidecars may be uploaded. Google Drive must never receive plaintext configuration, database dumps, volume archives, or the rclone credential escrow. If older backup objects were created by a different OAuth client, download and verify them first, then re-upload through the narrowed client before revoking the old grant.

## Routine operations and upgrades

```sh
make CONFIG_FILE=.env status
make CONFIG_FILE=.env health
make CONFIG_FILE=.env logs
make CONFIG_FILE=.env restart
```

Before an upgrade, re-read release/migration notes, update tag and digest together, update `docs/UPSTREAM.md`, and get hosted CI green. Then run `scripts/ops upgrade`. The Nix migration preflight gives an earlier, clearer failure. A direct container restart may bypass it, but pinned Paperclip independently rejects a non-empty database without its expected journal before mutation.

## Slice 0 acceptance evidence

Slice 0 has passed these gates. Its non-secret production evidence is recorded in `docs/IMPLEMENTATION_PLAN.md`.

## Slice 1 deployment: Chief of Staff

Run this section only after independent review, a green hosted PR, and merge to `main`. Record the merged SHA. It extends the running stack to exactly PostgreSQL, Paperclip, and Hermes; it does not change Tailscale Serve or expose another port.

### 1. Prepare Telegram and the brain checkout

In Telegram, open the verified `@BotFather`, send `/newbot`, and create one private bot for Nix. Keep the token on the VPS only; never paste it into an issue, PR, shell history, or chat with an agent. Ask the verified `@userinfobot` for Lior's numeric Telegram user ID and independently confirm the returned account identity. Slice 1 enables no group access.

Create a clean read-only-use clone of the canonical brain as `nix`:

```sh
sudo install -d -o nix -g nix -m 0750 /opt/nix-brain
git clone git@github.com:Lior-Nis/nix-brain.git /opt/nix-brain
git -C /opt/nix-brain switch main
git -C /opt/nix-brain pull --ff-only
stat -c '%g' /opt/nix-brain
```

The checkout is operator-owned so it can be refreshed deliberately; keep its root a real directory (not a symlink) with mode `0750` or an equivalently private mode that grants the group read/traverse and grants nothing to other users. Record the positive numeric group ID printed by `stat`. Configuration refuses a GID that collides with any group already present in the pinned Hermes image (except Hermes' own primary `10000`), preventing accidental membership in groups such as `shadow`. Compose mounts the checkout read-only and grants Hermes only the validated supplemental group. The reviewed entrypoint creates/maps only its dedicated collision-free reader group, does so idempotently across container restarts, and the verifier inspects the live gateway's retained groups; configuration alone is not accepted as proof. Do not give Chief a GitHub write credential in Slice 1.

Update the deployment `.env` from the reviewed example:

```text
HERMES_ENV_FILE=/etc/nix-os/hermes.env
HERMES_TELEGRAM_BOT_USERNAME=the_nixos_bot
HERMES_TELEGRAM_MODE_FILE=/etc/nix-os/hermes-telegram-mode.env
NIX_BRAIN_HOST_PATH=/opt/nix-brain
NIX_BRAIN_GID=<numeric output of stat -c %g /opt/nix-brain>
```

Create only the new Hermes external secret file without touching existing Slice 0 secrets:

```sh
sudo -E CONFIG_FILE="$PWD/.env" ./scripts/init-hermes-secrets "$PWD/.env"
sudo ./scripts/rotate-hermes-telegram-token "$PWD/.env"
sudoedit /etc/nix-os/hermes.env
```

The rotation helper prompts for the BotFather token through `/dev/tty` with terminal echo disabled. It never accepts the token in an argument or environment variable. It verifies BotFather token shape and calls Telegram `getMe`; `ok`, `result.is_bot`, and the case-insensitive username must match the non-secret `HERMES_TELEGRAM_BOT_USERNAME` before the file can change. The helper then replaces exactly one `TELEGRAM_BOT_TOKEN` entry with an atomic, fsynced mode-`0600` rewrite while preserving every other byte. It rejects a relative, symlinked, non-regular, hard-linked, non-root-owned, or group/world-accessible production secret file. Only the validated non-secret bot ID and username are printed.

For an operator pipeline that already receives the token securely on standard input, use `--stdin`; still never place the token in the command line, an environment variable, a file in the checkout, or chat. With `sudoedit`, replace the numeric user-ID placeholders and `OPENCODE_GO_API_KEY` placeholder. Set `TELEGRAM_HOME_CHANNEL` to the same positive ID as `TELEGRAM_ALLOWED_USERS`. Keep the generated `API_SERVER_KEY` and the generated decision-webhook secret; do not reuse either for another credential. `HERMES_DECISION_WEBHOOK_SECRET` and upstream's `WEBHOOK_SECRET` alias must remain identical to each other but distinct from `API_SERVER_KEY`. The completed file contains exactly those three key entries, the OpenCode Go key, Telegram token/user allowlist/home chat, and two explicit false allow-all flags. Keep mode `0600`. The Git-controlled Hermes config uses Lior's positive user ID as its non-empty `allowed_chats` value; because Telegram group/forum IDs are negative, this is the pinned release's hard DM-only gate in addition to `guest_mode: false` and `allow_bots: none`. `group_policy` is not a supported pinned-release setting and is intentionally absent.

### 2. Deploy and authorize the provider

The pinned Hermes image supports OpenCode Go natively. The reviewed profile selects provider `opencode-go` and model `gpt-5.6-luna`; `OPENCODE_GO_API_KEY` is read only from the external Hermes secret file. Do not add a custom endpoint or copy the key into Git-controlled YAML, process arguments, chat, or logs. `configure-hermes auth` verifies that the running container sees the credential and that Hermes recognizes the provider without printing the key.

Secret initialization also creates a root-owned mode-`0600` marker at `/etc/nix-os/hermes-telegram-mode.env`, initially containing `HERMES_TELEGRAM_MODE=disabled`. Marker changes fsync the new file and parent directory before reporting success. The Compose-mounted entrypoint first removes any stale profile-level Telegram credential/admission variables from `/opt/data/.env` with an atomic, fsync-durable rewrite, then clears the external bot token unless the marker explicitly says `live`; unsafe profile metadata or a missing, malformed, or unsafe marker fails closed. This keeps the root-owned external secret file as Telegram's only credential source even after restoring older profile state.

The persistent marker applies to deploy, restart, upgrade, backup restart, rollback, and recovery. Keep it disabled until the intended bot identity and polling ownership have been established:

```sh
sudo -E ./scripts/check-config "$PWD/.env"
sudo -E ./scripts/check-migrations "$PWD/.env"
sudo -E ./scripts/transition-paperclip "$PWD/.env"
sudo -E docker compose --env-file "$PWD/.env" pull hermes
sudo -E ./scripts/configure-hermes files-preflight "$PWD/.env"
sudo -E docker compose --env-file "$PWD/.env" up -d --no-deps --wait --force-recreate hermes
sudo -E ./scripts/configure-hermes auth "$PWD/.env"
sudo -E ./scripts/configure-hermes verify-processes "$PWD/.env"
```

The tracked Paperclip runtime configuration adds only the isolated Docker service name `paperclip` to the upstream private-host allowlist. On the existing Slice 0 deployment, `transition-paperclip` validates migrations and named-volume attachments, then recreates only Paperclip when it still lacks that hostname or the internal `agent` network; PostgreSQL, Hermes, unrelated services, and unrelated Docker networks are not targeted. It is a no-op after the topology is compliant. Hermes is deliberately force-recreated after the reviewed checkout changes: its Nix helpers are individual file bind mounts, and Git may replace their host inodes while a running container retains the old mounted inode. The named profile volume is preserved and the disabled mode marker keeps Telegram inert. As defense in depth, `converge` compares the reviewed and in-container claim-helper SHA-256 values before executing that helper or opening the browser approval. It performs this same bounded Hermes-only refresh once only when the hashes differ and the external marker is an operator-owned, mode-`0600` regular file set exactly to `disabled`, then verifies the mounted hash again. A matching helper that rejects `status`, a live/unsafe marker, or a post-refresh mismatch fails closed without another service change. The persistent marker keeps Telegram inert even though `hermes.env` contains the migrated token. `files-preflight` explicitly empties known Telegram, Runs API, Paperclip, and provider credential variables before exercising disposable protected-file fixtures as uid/gid `10000:10000`. It also uses the real Hermes file tool to read an actual tracked Markdown file from the private brain checkout and proves that same file cannot be written, without printing its path or contents. `check-config` refuses a missing, nonnumeric, zero, or stale `NIX_BRAIN_GID`, so changing ownership of the checkout requires updating the deployment value before recreating Hermes. The pre-claim `verify-processes` action checks the running process identity, singleton gateway, Telegram token/admission state, and Telegram model routing from both primary SQLite state and the legacy-import file. Every stored override must be absent (so the reviewed global route applies) or match the reviewed OpenCode Go route exactly; config, environment, and Telegram channel endpoint/model overrides are rejected too. The full verifier additionally requires the claimed Paperclip credential and therefore runs after `converge`.

Do not test the new bot yet. Telegram permits only one poller for a given bot token. A gateway using a different, independently validated bot token is not a competing poller and must not be stopped merely because it also uses Telegram.

### 3. Create the approved project and onboard Chief

In Paperclip, identify the production company and record its non-secret company ID. Before the first privileged run, bind the deployment to Lior's non-secret Paperclip user ID:

```sh
sudo -E ./scripts/bootstrap-paperclip-chief identify <company-id> --config "$PWD/.env"
```

Approve the ephemeral browser challenge while signed in as Lior, then copy the printed non-secret ID into `PAPERCLIP_LIOR_USER_ID` in `.env` and rerun `scripts/check-config`. `identify` is safe to repeat and self-revokes its board credential. Every prepare/converge/finalize run thereafter rejects and revokes a credential approved by any other Paperclip user; a name, email, or Telegram ID is not a substitute for this immutable ID.

The reviewed helper below converges the already-approved `Nix Business OS V0` Goal and Project through supported APIs.

The production company currently has no agent. Pinned Paperclip cannot approve its first external-agent join without an existing CEO manager. Run the one-shot reviewed operator flow:

```sh
sudo -E ./scripts/bootstrap-paperclip-chief converge <company-id> --config "$PWD/.env"
```

The helper prints one ephemeral Paperclip CLI-approval URL. Open it while signed in as Lior, inspect the requested company-scoped board action, and approve it. No separate invite creation, token relay, join approval, claim, or finalization click is required. The helper polls only with the challenge secret, keeps the resulting board credential in memory, verifies the approving identity has an active `owner` or `admin` membership in the exact company, self-revokes the credential on success or failure, and proves the revoked credential gets `401`. If revocation fails, stop and revoke the reported non-secret key ID in Paperclip.

Within that already-approved scope, the helper also converges the exact company-level Goal `Complete Nix Business OS V0` and Project `Nix Business OS V0`. It lists exact titles first (including archived projects), stops on duplicates, creates the goal only when absent as active/company-level/unowned, and creates the project only when absent with idempotency key `nix-business-os-v0-approved-v1`, status `in_progress`, and the goal link. It unarchives the one exact project if necessary and prints only their non-secret IDs.

For the agent bootstrap, the helper requires the company to be empty (or in an exact recoverable state created by a prior run), creates the temporary CEO through Paperclip's supported `agent-hires` API, performs the board approval as this explicit Lior-run action, strips create/assign permissions, and verifies that it has no API keys. The temporary record stays `idle` until the join is approved because it is the current manager, but it cannot perform useful work: its only command is `/bin/false`, heartbeat is disabled, budget is zero, and it has no credential.

Using the same in-memory board credential, `converge` creates an agent-only invite and immediately accepts it. The response must identify that exact invite and the expected agent request/name/adapter before anything is staged or approved. The invite token is never printed or persisted. Before approving the resulting Chief join, it sends the claim response over stdin to the in-container helper, which atomically stages the claim secret as a mode-`0600`, fsynced `/opt/data/mcp-tokens/nix-os-paperclip-claim-stage.json` file in a private operator-owned directory. Pinned Hermes hard-denies file-tool reads and searches beneath `mcp-tokens`; the runtime boundary check proves direct reads, symlink reads, filename searches, and content searches cannot expose its random canary fixture. The staged secret is never returned by status, placed in an argument/environment variable, logged, or exposed to the model.

```text
adapterType: hermes_gateway
apiBaseUrl: http://hermes:8642
paperclipApiUrl: http://paperclip:3100
sessionKeyStrategy: issue
dangerouslyAllowInsecureRemoteHttp: true
```

The last setting is allowed only on the non-published same-host `agent` network documented by ADR 0006. Before creating the invite, the helper verifies the claim destination. The in-container claim then writes a prepared mode-`0600` file, flushes it, atomically renames it to `/opt/data/.env`, flushes the directory, and verifies the resulting Paperclip identity. Finalization restricts Chief's explicit permission flags (no agent/skill creation; task assignment retained), promotes Chief to the sole root CEO, then demotes the bootstrap record to `general` reporting to Chief, reapplies its zero-permission policy, and pauses it. Only after the complete org shape is re-read and validated does the helper restart Hermes and run the full restricted-runtime verification. The helper prints only non-secret company Goal/Project/agent identifiers. The Chief flags are defense in depth because the pinned CEO role itself can still authorize agent creation; the enforced runtime boundary remains the restricted Hermes tool surface.

A rerun is convergent. It pages through accepted/active invites and acts only on a join uniquely correlated by both IDs to its accepted `nix-os:first-chief:v1` marker. A staged pending join is approved and resumed; a staged approved join resumes without returning its secret to the host. A verified credential/receipt completes finalization. If an approved join has no usable persisted credential, the helper revokes only recognized active `initial-join-key`/`nix-chief-recovery` standard keys owned by the pinned Lior user, creates one replacement standard key through Paperclip's supported board API, and sends it over stdin to atomic persistence/identity verification. Before replacing `.env`, the in-container helper fsyncs a non-secret recovery marker. An ambiguous host response is resolved from the verified credential, exact marker, and receipt; a persisted key is never revoked. If no credential was persisted, the exact marker is removed durably before key revocation so either side of a crash is safely retryable. Unexpected keys, marker fields, or topology fail closed. Successful claim/recovery removes the protected stage and matching recovery marker.

The granular `bootstrap-paperclip-chief prepare`, `onboard-hermes-agent submit`, `onboard-hermes-agent claim`, and `bootstrap-paperclip-chief finalize` commands remain emergency recovery tools only. They add human steps and must not replace `converge` in the normal production path.

The one-time claim secret is never blindly replayed. If the claim endpoint consumed it across a crash, `converge` uses the bounded replacement-key recovery above. Never delete the retained bootstrap record or edit the Paperclip database. Before stopping either service, state backup runs the read-only `check-paperclip-chief-topology` gate against the database and Hermes claim metadata. It refuses staged/pending claims, unsafe Chief permissions or gateway configuration, another live root, a non-inert bootstrap manager, or ambiguous/incorrect API-key ownership. Run `converge` to a verified final topology first, then back up the full Hermes volume.

The verified Chief surface must be identical for `cli`, `telegram`, and `api_server`: `file`, `memory`, `session_search`, and bounded `paperclip`. The runtime validator expands these labels and fails if mutable skill management, terminal, process management, code execution, browser/web/connectors, delegation, cron, computer-use, an unexpected MCP operation, or any other tool appears. A second pinned-runtime check proves `.env`/`auth.json` cannot be read or found by broad search, file writes/patches stay under `/opt/data/memories` even across symlinks, and the built-in `grill-me` guidance is readable but not writable. The nine allowed Paperclip operations remain the only Paperclip write path.

### 4. Telegram bot activation and per-token single-poller cutover

Immediately before activation, re-prove the VPS gateway is healthy and Telegram-disabled. The configured production identity must already have passed the rotation helper's `getMe` check as `@the_nixos_bot`.

If this is a migration of the **same bot token**, first stop and disable the gateway that currently polls that token, then enable and recreate VPS Hermes. If this is the dedicated `@the_nixos_bot` token and the `pop` gateway uses the distinct `@the_lnx_bot` token, preserve the `pop` gateway: it is unrelated and can coexist. For the dedicated-bot path, run only:

```sh
sudo -E docker compose --env-file "$PWD/.env" exec -T --user 10000:10000 hermes curl -fsS http://127.0.0.1:8642/health >/dev/null
sudo -E ./scripts/configure-hermes verify "$PWD/.env"
sudo -E ./scripts/configure-hermes telegram-enable "$PWD/.env"
sudo -E docker compose --env-file "$PWD/.env" up -d --no-deps --wait --force-recreate hermes
sudo -E ./scripts/configure-hermes verify "$PWD/.env"
```

For a same-token migration only, insert this proof immediately before `telegram-enable`:

```sh
ssh <same-token-old-host> 'systemctl --user disable --now hermes-gateway.service && ! systemctl --user is-active --quiet hermes-gateway.service && ! systemctl --user is-enabled --quiet hermes-gateway.service'
```

There must never be two active pollers for the same token. If the VPS Hermes health check, Telegram reply, or authorization check fails, make the disabled state durable before restarting a same-token old gateway. Because the marker is an individual file bind mount, replacing it is not enough for an existing container: stop Hermes, write the disabled marker, force-recreate Hermes against that marker, and prove the new gateway process has no Telegram token. If any step fails, stop Hermes again. Restart an old gateway only when it owns the same token and was stopped for this migration; never alter an unrelated bot gateway as rollback:

```sh
if sudo -E docker compose --env-file "$PWD/.env" stop hermes \
  && sudo -E ./scripts/configure-hermes telegram-disable "$PWD/.env" \
  && sudo -E docker compose --env-file "$PWD/.env" up -d --no-deps --wait --force-recreate hermes \
  && sudo -E ./scripts/configure-hermes verify-processes "$PWD/.env"; then
  ssh <same-token-old-host> 'systemctl --user enable --now hermes-gateway.service && systemctl --user is-active --quiet hermes-gateway.service && systemctl --user is-enabled --quiet hermes-gateway.service'
else
  sudo -E docker compose --env-file "$PWD/.env" stop hermes
  printf 'VPS Hermes could not be proved Telegram-disabled; do not start any same-token poller.\n' >&2
  false
fi
```

Omit the `ssh <same-token-old-host>` rollback line entirely for the dedicated-bot path. Keep `/etc/nix-os/hermes-telegram-mode.env` root-owned and mode `0600`; routine operations and recovery all obey it. For a same-token migration, the previous host's unit must be both inactive and disabled before the VPS marker becomes live, so its reboot cannot silently recreate a competing poller. A validated distinct bot such as `@the_lnx_bot` on `pop` remains active. Only after these proofs should `@the_nixos_bot` answer Lior's `ping`. Do not proceed if Telegram reports a polling conflict for this bot. From a different Telegram identity, send a message and verify it is silently ignored and causes no tool call; sanitize logs before recording evidence.

Inspect the agent in Paperclip and verify adapter type, URLs, issue session strategy, and responsible user. Confirm the Hermes Runs API has no host-published port:

```sh
sudo -E docker compose --env-file "$PWD/.env" ps
sudo ss -lntup
```

Public probes from outside the VPS must still show no Nix service on 80, 443, 3100, 5432, 8443, 8642, 9119, or 10000. Attribute any response to its actual owner: the known PDM `8443`, Hatch `10000`, unrelated port-80 workload, and recovery SSH exception are not Nix exposure and must not be changed by this deployment.

### 5. Live Slice 1 acceptance

Use the private Telegram conversation with Chief and verify each result in Paperclip:

1. Send `ping`; only Lior's private direct chat receives a response. Add the bot temporarily to a test group, mention it as Lior, and verify it remains silent with no tool call; then remove it.
2. Store the harmless memory fact `Slice 1 continuity marker is cedar-47`, restart only Hermes, then ask for the marker.
3. Ask `What work exists in the Nix Business OS project?`; compare with current Paperclip state.
4. Ask `Create a low-priority test task in the Nix Business OS project titled "Slice 1 integration test".` Confirm exactly one issue exists in the correct project and Chief returns its identifier/status only after creation.
5. Ask Chief to add a harmless comment and update that issue. Verify the change in Paperclip.
6. Change the issue directly in Paperclip, then ask Chief for its status. It must retrieve current Paperclip state, not Telegram memory.
7. Ask a pure clarification question and verify no issue is created. Ask for a new top-level project and verify Chief does not create it.
8. Restart the Compose runtime, then reboot the VPS. After each, verify Paperclip health, bot response, continuity marker, brain read, and current Paperclip issue access.

Complete the Slice 1 downloaded-off-host recovery gate in `RESTORE.md`. Record timestamps plus non-secret company/project/agent/issue IDs in the implementation plan only after every gate passes. Do not start Slice 2.

## Slice 2 pre-acceptance deployment diagnostics

Use this section only from a reviewed, green, merged Slice 2 commit. It documents the intended diagnostics and does not by itself establish Slice 2 acceptance.

On a fresh install, the reviewed secret initializer creates the Slice 2 fields. On an existing Slice 1 deployment it deliberately refuses to overwrite `/etc/nix-os/hermes.env`; use `sudoedit` to preserve the existing values and add a newly generated 64-lowercase-hex `HERMES_DECISION_WEBHOOK_SECRET`, an identical `WEBHOOK_SECRET`, and `TELEGRAM_HOME_CHANNEL` equal to the sole existing `TELEGRAM_ALLOWED_USERS` value. Never print the secret. Confirm `.env` still pins `PAPERCLIP_LIOR_USER_ID` to Lior's immutable Paperclip user ID. Then run the ordinary configuration and runtime gates:

```sh
sudo -E ./scripts/check-config "$PWD/.env"
sudo -E ./scripts/check-paperclip-chief-topology "$PWD/.env"
sudo -E docker compose --env-file "$PWD/.env" up -d --no-deps --wait --force-recreate hermes
sudo -E ./scripts/configure-hermes verify "$PWD/.env"
sudo -E docker compose --env-file "$PWD/.env" exec -T --user 10000:10000 hermes \
  python3 /opt/nix/validate-tool-boundary.py webhook-config
```

The verifier must find exactly eleven Paperclip tools, with checkout and structured questions as the only additions to the accepted Slice 1 nine-tool surface. It must also prove the webhook binds only to container loopback on port 8644, has one fixed HMAC route, uses `deliver_only` to the existing Telegram adapter, permits no dynamic subscription, and keeps `paperclipApiRequest` out of the model-visible catalog. Neither 8642 nor 8644 may be host-published.

The two new state files live inside the already-backed-up Hermes volume. Inspect metadata without dumping either database:

```sh
sudo -E docker compose --env-file "$PWD/.env" exec -T --user 10000:10000 hermes \
  sh -ec 'for path in /opt/data/runs_idempotency.db /opt/data/state/paperclip-question-delivery.db; do test ! -e "$path" || stat -c "%F %h %u:%g %a %n" "$path"; done'
```

Every existing file must be a uid/gid `10000:10000`, mode `0600`, regular single-link file. `runs_idempotency.db` preserves Runs API replay/conflict state across restart. The question outbox preserves one row per authoritative Paperclip interaction. Treat `failed_not_sent` as the only automatically retryable notification state; `unknown` means delivery may have occurred and must not be replayed blindly. Do not print webhook payloads, question bodies, Telegram chat IDs, or secrets while diagnosing. Use sanitized service logs and the Paperclip interaction/run records for correlation.

Before live acceptance, run the fast in-memory contract model from the reviewed checkout. It is regression coverage, not upstream integration or acceptance evidence:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tests/e2e/paperclip-hermes-loop.py
```

Hosted Docker CI additionally runs `tests/smoke/paperclip-hermes-gateway-image.sh`. That fresh-state check compiles and invokes the exact adapter source in the pinned Paperclip image against the pinned Hermes image. It proves run admission, redacted correlation, event-stream use, polling fallback, issue-session isolation, idempotent replay and conflict, and replay after a gateway restart. With no provider secret, the admitted runs are expected to end in a visible provider failure; this is admission and transport evidence only, not a successful employee lifecycle. The following `tests/smoke/backup-restore.sh` CI step separately uses a real pinned Paperclip server and the exact official MCP package under supported heartbeat runs to prove checkout, run-attributed issue update/comment/child creation, forced human-only structured questioning addressed to the pinned Lior user, exact-key replay, a real competing-run HTTP-409 checkout conflict, transition to `in_review`, and preservation of the resulting interaction plus execution/delivery databases through encrypted backup and isolated restore. Neither secret-free check replaces the successful live lifecycle acceptance below.

Live acceptance must still prove the Paperclip issue/run/Hermes-run correlation, one child issue, issue-scoped session isolation, a human-only question addressed exactly to Lior and delivered once through Chief's existing Telegram chat, and an interrupted attempt followed by one deliberate successful retry. Do not record Slice 2 as accepted until the PR, hosted CI, independent review, deployment, live checks, and recovery extension all pass.

## Recover a settled interrupted Hermes run

Do not clear a legacy execution hold by editing PostgreSQL, deleting the failed run, or repeatedly pressing retry. First inspect the issue, source heartbeat run, Hermes run/log correlation, comments, child issues, pending interactions, provider state, and active leases. If any external outcome is uncertain, keep the issue blocked and reconcile it manually before allowing replay.

For a conclusively stopped provider with no performed action, use a short-lived authenticated Paperclip Board session and the supported `POST /api/issues/:id/recovery-actions/resolve` route. The pinned settled-legacy path requires Board authority, no competing active recovery, `outcome="restored"`, and `sourceIssueStatus="todo"`. Send this strict shape, substituting only the exact recorded IDs and evidence:

```json
{
  "actionId": "<exact-recovery-action-id>",
  "outcome": "restored",
  "sourceIssueStatus": "todo",
  "executionReconciliation": {
    "runId": "<exact-source-run-id>",
    "providerStopped": true,
    "actionOutcome": "not_performed",
    "outcomeEvidence": "<at least 20 characters of concrete evidence>"
  }
}
```

Other outcomes must describe the actually observed result; never label an ambiguous dispatch as `not_performed` merely to unblock work. At this pin, `GET /api/issues/:id/recovery-actions` projects only the currently active action and can return an empty list even while a settled `replay=blocked` hold remains. Read the exact ID from the already-recorded recovery response/activity or the issue's `executionBlocker.recoveryActionId` projection. If neither supplies it, stop for upstream diagnosis. Never guess an action ID, and never read or write PostgreSQL to bypass this control.

Create the temporary Board session only through Paperclip's official CLI/browser approval flow. Put its data directory in a root-owned mode-`0700` temporary directory and require the credential file to be mode `0600`; do not place its bearer token in command arguments, environment variables, logs, or documentation. Read the token only inside the invoking process. After use, revoke it server-side, prove the captured old token receives HTTP 401, run the supported logout, and verify the credential store contains zero entries.

After Paperclip accepts the reconciliation, verify that it—not an operator script—creates the successor. Confirm the predecessor remains failed and auditable, the successor links through `retryOfRunId`, the issue and session context match, and only one final result/comment exists. A provider-authentication failure before model or tool execution is a separate attributable failed run and requires its own evidence-backed recovery. Finally capture a new consecutive encrypted configuration/state backup pair.

## Slice 3 deployment: task-scoped specialists

Use this section only from a reviewed, hosted-CI-green, merged Slice 3 commit. It installs the exact first-party Daytona sandbox plugin and adds three Paperclip worker records; it adds no Compose executor, Telegram receiver, public route, persistent specialist profile, Engineering Manager, or n8n service. Do not mark Slice 3 accepted until the live decision/resume, reboot, and downloaded Google Drive recovery gates pass.

### 1. Prepare non-secret identities and external secrets

Keep the accepted Chief and approved-project records. Set their exact UUIDs in the production deployment file before starting the Slice 3 services:

```text
NIX_CHIEF_AGENT_ID=<accepted Chief UUID>
NIX_APPROVED_PROJECT_ID=<already-approved Nix Business OS V0 project UUID>
```

Copy the remaining Slice 3 variable names and external paths from `.env.example`. For the first activation only, leave `NIX_PRODUCT_AGENT_ID`, `NIX_GROWTH_AGENT_ID`, `NIX_OPERATIONS_AGENT_ID`, `NIX_SPECIALIST_AGENT_IDS`, and `NIX_SPECIALIST_ENVIRONMENT_ID` empty during the safe pre-bootstrap phase. A nonempty placeholder or partial set is invalid. No specialist exists or is remotely invokable while the allowlist is empty. On a recovery rerun, preserve the complete values previously published by bootstrap: recovery accepts only a complete, internally consistent set whose marked Paperclip environment/agents match exactly and whose live allowlist is either still empty or already exact. It creates no replacement identities and completes the force-recreate. Do not create or approve a new top-level project.

Create the founder-relay file and one root-owned provider-import file locally on the VPS:

```sh
sudo -E ./scripts/init-founder-relay-secret "$PWD/.env"
sudo install -m 0600 -o root -g root /dev/null /etc/nix-os/specialist-provider.env
sudoedit /etc/nix-os/specialist-provider.env
```

Enter exactly `DAYTONA_API_KEY=<Daytona API key>` and `OPENCODE_API_KEY=<restricted-service-key>`, one per line. Use an OpenCode key limited to model requests; do not place Chief, Paperclip Board, Telegram, GitHub, Todoist, or brain credentials in this file. Never pass either value in a command argument, inherited host environment, issue, PR, or chat. The bootstrap imports/rotates both values into Paperclip's encrypted company secret store; the host file remains only for encrypted configuration backup and deliberate rotation.

Validate the complete external contract without printing a credential:

```sh
sudo -E ./scripts/check-config "$PWD/.env"
sudo -E ./scripts/check-paperclip-chief-topology "$PWD/.env"
```

`check-config` proves the exact two provider bindings, file permissions, and founder identity/secret separation. It must pass before any Compose change.

### 2. Activate the pinned Paperclip boundary

Recreate Paperclip from the merged commit. Its entrypoint verifies exact pinned source/output hashes and builds or verifies the matching OpenCode provider pack in its separate cache volume:

```sh
sudo -E docker compose --env-file "$PWD/.env" up -d --no-deps --wait --force-recreate paperclip
```

An unknown Paperclip source, partial patch, stale matching marker, or changed provider artifact must leave Paperclip unhealthy. Do not bypass the patch verifier or edit the provider pack. The provider-import file is not mounted or injected into Paperclip, and no host port, public WebSocket, Tailscale handler, or Funnel route is added for Daytona.

### 3. Converge the Paperclip environment and workers

Run the reviewed one-shot bootstrap with the already-accepted company UUID:

```sh
sudo -E ./scripts/bootstrap-paperclip-specialists <company-id> --config "$PWD/.env"
```

The helper prints one ephemeral Paperclip CLI-approval URL. Open it as Lior, verify that it requests the instance-admin `converge Nix task-scoped specialists` Board action, and approve it. The helper requires `cli-auth/me.isInstanceAdmin=true`, verifies the pinned Lior owner/admin identity, and revokes the temporary Board credential on success or failure. On first activation, before requesting approval it requires all five specialist/environment ID fields to be empty, verifies the exact in-container runtime patch, and proves the running container has the empty fail-closed specialist floor. A recovery rerun instead requires the complete previously published identity set described above. Existing specialists must be exactly idle, and the helper reads each managed `AGENTS.md` back through Paperclip's supported instance-admin instructions-bundle API and compares the exact Git-tracked bytes; missing or drifted instructions fail without implicit repair. It creates workers only under that restrictive floor, verifies the same readback after creation, writes the final IDs atomically, then force-recreates Paperclip and Hermes with the exact allowlist.

Within that approval, the helper enables Paperclip environments/native runner; installs and verifies exactly `@paperclipai/plugin-daytona@2026.916.1`; requires the live company capabilities route to expose the running Daytona provider for saved probes and run execution; imports or rotates exactly two Paperclip-managed encrypted secrets with non-secret fingerprints; and creates then probes one strict `sandbox/daytona` environment once. The environment pins the reviewed image digest, EU target, 1 CPU, 2 GiB RAM, 5 GiB disk, no lease reuse, `per_turn`, and 60-minute auto-delete. The probe's released lease is durable recovery evidence: if the process crashes after a clean probe but before publishing IDs, a rerun reuses that exact completed receipt instead of creating a second sandbox. Any active, failed, ambiguous, or unexpected lease stops recovery for operator reconciliation. Only after the probe succeeds does the helper create exactly Product, Growth, and Operations. They report to Chief, use `paperclip_runner`, `opencode/gpt-5.6-luna`, disabled scheduled heartbeat, `maxConcurrentRuns: 1`, zero monthly budget, and no API keys. They receive only the server-scoped Paperclip PRP catalog; OpenCode shell/file tools are denied. It writes only their non-secret agent/environment UUIDs back to `.env`, recreates the consumers, then rechecks live plugin-worker capabilities without creating a second paid sandbox. A drifted plugin, environment, secret binding, or worker is detected by bootstrap and the final topology gate and fails closed rather than being silently repaired.

The helper already recreated Paperclip and Hermes with the final allowlist. Run every boundary/topology gate:

```sh
sudo -E ./scripts/check-config "$PWD/.env"
sudo -E ./scripts/check-paperclip-chief-topology "$PWD/.env"
sudo -E ./scripts/check-paperclip-specialist-topology "$PWD/.env"
sudo -E ./scripts/configure-hermes verify "$PWD/.env"
sudo -E docker compose --env-file "$PWD/.env" ps
sudo ss -lntup
```

The specialist topology gate must prove the exact three idle workers, their exact single-file managed instruction manifests and Git-tracked bytes, Chief manager, approved project boundary, low-trust permissions, specialist-only assignment set, exact Daytona plugin/environment/secret metadata and fingerprints, no worker API keys, and no Engineering Manager. It also blocks every nonterminal or unknown specialist run/Daytona-lease status. The Hermes verifier must still prove the accepted Chief boundary plus the one fixed founder-decision tool; no shell/process/browser/raw-API escape path is permitted. No new host listener is expected, and the existing Tailscale Serve/Funnel state must remain unchanged.

### 4. Live founder-decision and cross-role acceptance

Use the existing private `@the_nixos_bot` direct chat; do not create a specialist bot or Telegram topic. Ask Chief to create approved-project Product work whose definition of done requires a visible Product-to-Growth child handoff and one genuine consequential choice. Inspect Paperclip and require all of the following before answering:

1. Product runs as the configured task-scoped specialist and records attributable progress in its assigned issue.
2. Growth starts only after Product creates a same-project child assigned to Growth. No chat-only handoff or top-level project/goal appears.
3. The ambiguity becomes one pending `ask_user_questions` interaction with `human_only`, Lior's immutable Paperclip user ID, the source run, and the Product issue. No Todoist object exists.
4. Chief delivers the question through its existing Telegram chat. Reply there as Lior with an explicit option; Chief must use the exact issue/interaction identifiers and stable `founder-decision:<interaction-id>` key.
5. Paperclip records Lior as resolver and returns a verified founder-relay receipt whose originating and resumed agent IDs are identical. Only that originating specialist resumes; Chief and another specialist do not take ownership.
6. Exact replay of the same answer/key is idempotent; a changed answer for that key is rejected. A non-Lior DM, group/forum context, API/CLI call, or Paperclip-triggered Chief run cannot invoke the relay.
7. Product and Growth finish with attributable evidence/status, and a fresh Operations issue also completes through a new bounded sandbox with no context from the prior tasks.

Then restart the stack and reboot the VPS. Re-run both topology gates, `configure-hermes verify`, service health, provider inference, Telegram authorization, Paperclip issue/receipt readback, and the Tailscale route-preservation check. Chief remains the only persistent/human-facing employee.

Finally create a consecutive encrypted configuration/state pair, upload it, download distinct copies from Google Drive, and run the isolated proof in `RESTORE.md`. The restored stack must pass both topology gates before application startup, recover the exact plugin/environment/secret metadata, and prove the live plugin worker through the supported capabilities route without exposing provider values. Record only non-secret IDs, timestamps, Git SHA, relationships, and ciphertext checksums in the Slice 3 acceptance record.
