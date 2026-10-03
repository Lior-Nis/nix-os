# Nix deployment runbook

Slice 0 production runs Paperclip and PostgreSQL with tailnet-only ingress on one Hostinger VPS. The reviewed Slice 1 extension adds exactly one internal Hermes service. Commands run from a clean clone at a reviewed commit. Tailscale is a host prerequisite, not a Compose service.

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
- Compose internal networks: PostgreSQL alone with Paperclip on `data`; Paperclip and Hermes alone on `agent`.
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

   Run `tailscale status --json | jq -r '.Self.DNSName'` after naming the host. Remove its trailing dot and set `PAPERCLIP_PUBLIC_URL=https://<that-fqdn>`. It must be the real `https://nix-os.<tailnet-name>.ts.net`, never a guessed suffix. Leave the loopback port at 3100 unless it conflicts.

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

Run `rclone config` as the `nix` operator. Create remote `gdrive` using Lior's Google Drive account and an owned Google Desktop OAuth client ID; rclone's shared client ID is being retired during 2026. Complete browser OAuth interactively. The resulting rclone config is a runtime secret outside Git and may be recreated during recovery.

Use only:

```text
gdrive:Nix/backups/config/
gdrive:Nix/backups/state/
```

Only `.age` objects and checksum sidecars may be uploaded. Google Drive must never receive plaintext configuration, database dumps, or volume archives.

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
```

The checkout is operator-owned so it can be refreshed deliberately; Compose mounts it read-only inside Hermes. Do not give Chief a GitHub write credential in Slice 1.

Update the deployment `.env` from the reviewed example:

```text
HERMES_ENV_FILE=/etc/nix-os/hermes.env
NIX_BRAIN_HOST_PATH=/opt/nix-brain
```

Create only the new Hermes external secret file without touching existing Slice 0 secrets:

```sh
sudo -E CONFIG_FILE="$PWD/.env" ./scripts/init-hermes-secrets "$PWD/.env"
sudoedit /etc/nix-os/hermes.env
```

Replace both Telegram placeholders directly in the editor. Keep the generated `API_SERVER_KEY`; do not reuse it as any other credential. The completed file contains exactly the API server key, Telegram token/user allowlist, and two explicit false allow-all flags. Keep mode `0600`. The Git-controlled Hermes config uses Lior's positive user ID as its non-empty `allowed_chats` value; because Telegram group/forum IDs are negative, this is the pinned release's hard DM-only gate in addition to `guest_mode: false` and `allow_bots: none`. `group_policy` is not a supported pinned-release setting and is intentionally absent.

### 2. Deploy and authorize the provider

```sh
sudo -E ./scripts/check-config "$PWD/.env"
sudo -E ./scripts/check-migrations "$PWD/.env"
sudo -E docker compose --env-file "$PWD/.env" pull hermes
sudo -E docker compose --env-file "$PWD/.env" up -d --wait postgres paperclip hermes
sudo -E ./scripts/configure-hermes auth "$PWD/.env"
sudo -E ./scripts/configure-hermes install-skill "$PWD/.env"
```

The tracked Paperclip runtime configuration adds only the isolated Docker service name `paperclip` to the upstream private-host allowlist; Compose policy and `scripts/initialize-paperclip` validate the setting. This is required for Hermes' internal URL, works with the existing Slice 0 instance file, and does not publish another listener. The auth command starts Hermes' supported OpenAI device-code flow for `openai-codex`. Lior completes the displayed browser authorization; the OAuth credential is stored under persistent `/opt/data`, not in Git or `hermes.env`. The selected model is `gpt-5.4`; change it only through reviewed config if the subscription does not offer it.

Confirm the bot answers Lior's `ping`. Do not proceed if Telegram reports a second polling consumer. From a different Telegram identity, send a message and verify it is silently ignored and causes no tool call; sanitize logs before recording evidence.

### 3. Create the approved project and onboard Chief

In Paperclip, find the existing `Nix Business OS V0` project and its company. If that approved initiative does not yet have a Paperclip Project, create exactly that one project—this implements already-approved scope, not new strategy. Record its non-secret project ID.

Use Paperclip's board UI to generate one agent invite for the company. Do not give its token to the model or place it in Telegram. Run the supported generic join through the repository wrapper:

```sh
sudo -E ./scripts/onboard-hermes-agent submit "$PWD/.env"
```

Paste the one-time invite token only into the script's hidden prompt. The wrapper calls Paperclip's supported invite endpoint from Hermes and stores the claim secret plus gateway defaults in a mode-`0600` temporary file beside `hermes.env`. It requests:

```text
adapterType: hermes_gateway
apiBaseUrl: http://hermes:8642
paperclipApiUrl: http://paperclip:3100
sessionKeyStrategy: issue
dangerouslyAllowInsecureRemoteHttp: true
```

The last setting is allowed only on the non-published same-host `agent` network documented by ADR 0006. In Paperclip, review the pending `Chief of Staff` join and approve it. Then claim its one-time key without printing it:

```sh
sudo -E ./scripts/onboard-hermes-agent claim "$PWD/.env"
sudo -E ./scripts/configure-hermes verify "$PWD/.env"
```

Before contacting the one-time claim endpoint, the claim command verifies the profile, ownership, writability, free space, and destination mode inside the Hermes container. It then claims, writes a prepared mode-`0600` temporary file, flushes it, atomically renames it to `/opt/data/.env`, flushes the directory, and verifies the resulting Paperclip identity. Only after those checks does it remove the pending marker and host-side claim state. It never prints the key or places it in a process argument. The command prints only company and agent IDs, restarts Hermes, and `verify` proves API auth, the exact restricted tool surface, provider auth, skill presence, and bounded Paperclip MCP identity without displaying credentials.

The one-time secret cannot be replayed. If Paperclip consumed it but no valid `/opt/data/.env` can be recovered, preserve the helper's pending marker and inspect the volume first. If the credential is genuinely lost, use supported Paperclip administration to revoke the orphaned agent key (or remove the orphaned agent), issue a new agent invite, and repeat the flow. Never retry the consumed secret or edit the Paperclip database.

The verified Chief surface must be identical for `cli`, `telegram`, and `api_server`: `file`, `skills`, `memory`, `session_search`, and bounded `paperclip`. The runtime validator expands these labels and fails if terminal, process management, code execution, browser/web/connectors, delegation, cron, computer-use, an unexpected MCP operation, or any other tool appears. The nine allowed Paperclip operations remain the only Paperclip write path.

Inspect the agent in Paperclip and verify adapter type, URLs, issue session strategy, and responsible user. Confirm the Hermes Runs API has no host-published port:

```sh
sudo -E docker compose --env-file "$PWD/.env" ps
sudo ss -lntup
```

Public probes from outside the VPS must still show no Nix service on 80, 443, 3100, 5432, 8443, 8642, 9119, or 10000. Attribute any response to its actual owner: the known PDM `8443`, Hatch `10000`, unrelated port-80 workload, and recovery SSH exception are not Nix exposure and must not be changed by this deployment.

### 4. Live Slice 1 acceptance

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
