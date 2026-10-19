#!/usr/bin/env bash
set -euo pipefail
umask 077

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
test_tmp_dir=$(mktemp -d /tmp/nix-os-foundation-test.XXXXXX)
trap 'rm -rf "$test_tmp_dir"' EXIT

postgres_password='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
paperclip_db_password='dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd'
printf 'POSTGRES_PASSWORD=%s\n' "$postgres_password" >"$test_tmp_dir/postgres.env"
printf 'PAPERCLIP_DB_PASSWORD=%s\n' "$paperclip_db_password" >>"$test_tmp_dir/postgres.env"
{
  printf 'DATABASE_URL=postgresql://paperclip:%s@postgres:5432/paperclip\n' "$paperclip_db_password"
  printf 'BETTER_AUTH_SECRET=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n'
  printf 'PAPERCLIP_TOOL_ACTION_SIGNING_SECRET=cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc\n'
} >"$test_tmp_dir/paperclip.env"
{
  printf 'API_SERVER_KEY=eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee\n'
  printf 'HERMES_DECISION_WEBHOOK_SECRET=ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff\n'
  printf 'WEBHOOK_SECRET=ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff\n'
  printf 'OPENCODE_GO_API_KEY=test-opencode-go-key-12345678\n'
  printf 'TELEGRAM_BOT_TOKEN=test-token\nTELEGRAM_ALLOWED_USERS=123456789\nTELEGRAM_HOME_CHANNEL=123456789\n'
  printf 'TELEGRAM_ALLOW_ALL_USERS=false\nGATEWAY_ALLOW_ALL_USERS=false\n'
} >"$test_tmp_dir/hermes.env"
printf 'HERMES_TELEGRAM_MODE=disabled\n' >"$test_tmp_dir/hermes-telegram-mode.env"
"$repo_root/tests/fixtures/create-slice3-secret-files" "$test_tmp_dir"
mkdir "$test_tmp_dir/nix-brain"
brain_gid=$("$repo_root/tests/fixtures/select-brain-gid")
chgrp "$brain_gid" "$test_tmp_dir/nix-brain"
chmod 0750 "$test_tmp_dir/nix-brain"
brain_gid=$(stat -c '%g' "$test_tmp_dir/nix-brain" 2>/dev/null || stat -f '%g' "$test_tmp_dir/nix-brain")
{
  printf 'COMPOSE_PROJECT_NAME=nix-os-test\n'
  printf 'PAPERCLIP_PUBLIC_URL=https://nix-os.test-tailnet.ts.net\n'
  printf 'PAPERCLIP_LIOR_USER_ID=lior-test-user\n'
  printf 'PAPERCLIP_HOST_PORT=0\n'
  printf 'POSTGRES_ENV_FILE=%s\n' "$test_tmp_dir/postgres.env"
  printf 'PAPERCLIP_ENV_FILE=%s\n' "$test_tmp_dir/paperclip.env"
  printf 'HERMES_ENV_FILE=%s\n' "$test_tmp_dir/hermes.env"
  printf 'FOUNDER_RELAY_ENV_FILE=%s\n' "$test_tmp_dir/founder-relay.env"
  printf 'HERMES_TELEGRAM_BOT_USERNAME=the_nixos_bot\n'
  printf 'HERMES_TELEGRAM_MODE_FILE=%s\n' "$test_tmp_dir/hermes-telegram-mode.env"
  printf 'SPECIALIST_PROVIDER_ENV_FILE=%s\n' "$test_tmp_dir/specialist-provider.env"
  printf 'NIX_CHIEF_AGENT_ID=11111111-1111-4111-8111-111111111111\n'
  printf 'NIX_APPROVED_PROJECT_ID=22222222-2222-4222-8222-222222222222\n'
  printf 'NIX_PRODUCT_AGENT_ID=33333333-3333-4333-8333-333333333333\n'
  printf 'NIX_GROWTH_AGENT_ID=44444444-4444-4444-8444-444444444444\n'
  printf 'NIX_OPERATIONS_AGENT_ID=55555555-5555-4555-8555-555555555555\n'
  printf 'NIX_SPECIALIST_AGENT_IDS=33333333-3333-4333-8333-333333333333,44444444-4444-4444-8444-444444444444,55555555-5555-4555-8555-555555555555\n'
  printf 'NIX_SPECIALIST_ENVIRONMENT_ID=66666666-6666-4666-8666-666666666666\n'
  printf 'NIX_BRAIN_HOST_PATH=%s\n' "$test_tmp_dir/nix-brain"
  printf 'NIX_BRAIN_GID=%s\n' "$brain_gid"
  printf 'PAPERCLIP_AUTH_DISABLE_SIGN_UP=true\n'
  printf 'BACKUP_OUTPUT_DIR=%s\n' "$test_tmp_dir/backups"
} >"$test_tmp_dir/test.env"
chmod 0600 "$test_tmp_dir"/*.env

NIX_ALLOW_TEST_CONFIG=1 "$repo_root/scripts/check-config" "$test_tmp_dir/test.env"
docker compose --env-file "$test_tmp_dir/test.env" config --format json >"$test_tmp_dir/compose.json"
python3 "$repo_root/tests/smoke/validate_compose.py" "$test_tmp_dir/compose.json" "$repo_root"

for specialist_mutation in \
  'NIX_PRODUCT_AGENT_ID=' \
  'NIX_PRODUCT_AGENT_ID=not-a-uuid' \
  'NIX_GROWTH_AGENT_ID=33333333-3333-4333-8333-333333333333' \
  'NIX_SPECIALIST_AGENT_IDS=33333333-3333-4333-8333-333333333333,55555555-5555-4555-8555-555555555555,44444444-4444-4444-8444-444444444444' \
  'NIX_SPECIALIST_AGENT_IDS=11111111-1111-4111-8111-111111111111,44444444-4444-4444-8444-444444444444,55555555-5555-4555-8555-555555555555'; do
  specialist_key=${specialist_mutation%%=*}
  sed "s|^${specialist_key}=.*$|${specialist_mutation}|" \
    "$test_tmp_dir/test.env" >"$test_tmp_dir/invalid-specialist.env"
  if NIX_ALLOW_TEST_CONFIG=1 "$repo_root/scripts/check-config" "$test_tmp_dir/invalid-specialist.env" >/dev/null 2>&1; then
    printf 'unsafe specialist identity configuration unexpectedly passed: %s\n' "$specialist_mutation" >&2
    exit 1
  fi
done

for identity_mutation in \
  'NIX_CHIEF_AGENT_ID=REPLACE_WITH_CHIEF_AGENT_ID' \
  'NIX_APPROVED_PROJECT_ID=NOT-A-UUID'; do
  identity_key=${identity_mutation%%=*}
  sed "s|^${identity_key}=.*$|${identity_mutation}|" \
    "$test_tmp_dir/test.env" >"$test_tmp_dir/invalid-identity.env"
  if NIX_ALLOW_TEST_CONFIG=1 "$repo_root/scripts/check-config" "$test_tmp_dir/invalid-identity.env" >/dev/null 2>&1; then
    printf 'invalid Chief/project identity unexpectedly passed: %s\n' "$identity_mutation" >&2
    exit 1
  fi
done

cp "$test_tmp_dir/test.env" "$test_tmp_dir/empty-specialists.env"
for specialist_key in \
  NIX_PRODUCT_AGENT_ID NIX_GROWTH_AGENT_ID NIX_OPERATIONS_AGENT_ID \
  NIX_SPECIALIST_AGENT_IDS NIX_SPECIALIST_ENVIRONMENT_ID; do
  sed "s|^${specialist_key}=.*$|${specialist_key}=|" \
    "$test_tmp_dir/empty-specialists.env" >"$test_tmp_dir/empty-specialists.next"
  mv "$test_tmp_dir/empty-specialists.next" "$test_tmp_dir/empty-specialists.env"
done
NIX_ALLOW_TEST_CONFIG=1 "$repo_root/scripts/check-config" "$test_tmp_dir/empty-specialists.env" >/dev/null

grep -Fq 'check_specialist_topology_when_configured' "$repo_root/scripts/ops"
python3 - "$repo_root/scripts/ops" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1]).read_text()
restart = source.split("  restart)", 1)[1].split("    ;;", 1)[0]
assert restart.count("check_specialist_topology_when_configured") == 2
assert restart.index("check_specialist_topology_when_configured") < restart.index('up -d --force-recreate --wait')
assert restart.rindex("check_specialist_topology_when_configured") > restart.index('up -d --force-recreate --wait')
PY

for invalid_brain_gid in 0 999999; do
  sed "s/^NIX_BRAIN_GID=.*$/NIX_BRAIN_GID=$invalid_brain_gid/" \
    "$test_tmp_dir/test.env" >"$test_tmp_dir/wrong-brain-gid.env"
  if NIX_ALLOW_TEST_CONFIG=1 "$repo_root/scripts/check-config" "$test_tmp_dir/wrong-brain-gid.env" >/dev/null 2>&1; then
    printf 'invalid or mismatched nix-brain group unexpectedly passed\n' >&2
    exit 1
  fi
done

for unsafe_brain_mode in 0755 0700; do
  chmod "$unsafe_brain_mode" "$test_tmp_dir/nix-brain"
  if NIX_ALLOW_TEST_CONFIG=1 "$repo_root/scripts/check-config" "$test_tmp_dir/test.env" >/dev/null 2>&1; then
    printf 'unsafe nix-brain directory mode unexpectedly passed\n' >&2
    exit 1
  fi
done
chmod 0750 "$test_tmp_dir/nix-brain"

mv "$test_tmp_dir/nix-brain" "$test_tmp_dir/nix-brain-real"
ln -s "$test_tmp_dir/nix-brain-real" "$test_tmp_dir/nix-brain"
if NIX_ALLOW_TEST_CONFIG=1 "$repo_root/scripts/check-config" "$test_tmp_dir/test.env" >/dev/null 2>&1; then
  printf 'symlinked nix-brain root unexpectedly passed\n' >&2
  exit 1
fi
unlink "$test_tmp_dir/nix-brain"
mv "$test_tmp_dir/nix-brain-real" "$test_tmp_dir/nix-brain"

grep -v '^PAPERCLIP_PUBLIC_URL=' "$test_tmp_dir/test.env" >"$test_tmp_dir/missing.env"
if NIX_ALLOW_TEST_CONFIG=1 "$repo_root/scripts/check-config" "$test_tmp_dir/missing.env" >/dev/null 2>&1; then
  printf 'missing required configuration unexpectedly passed\n' >&2
  exit 1
fi

for provider_secret in DAYTONA_API_KEY OPENCODE_API_KEY OPENCODE_GO_API_KEY OPENCODE_ZEN_API_KEY; do
  cp "$test_tmp_dir/test.env" "$test_tmp_dir/provider-secret.env"
  printf '%s=test-secret-must-stay-external\n' "$provider_secret" >>"$test_tmp_dir/provider-secret.env"
  if NIX_ALLOW_TEST_CONFIG=1 "$repo_root/scripts/check-config" "$test_tmp_dir/provider-secret.env" >/dev/null 2>&1; then
    printf '%s in the deployment environment unexpectedly passed\n' "$provider_secret" >&2
    exit 1
  fi
done

cp "$test_tmp_dir/hermes.env" "$test_tmp_dir/hermes-safe.env"
sed 's/^TELEGRAM_ALLOW_ALL_USERS=false$/TELEGRAM_ALLOW_ALL_USERS=true/' \
  "$test_tmp_dir/hermes-safe.env" >"$test_tmp_dir/hermes.env"
if NIX_ALLOW_TEST_CONFIG=1 "$repo_root/scripts/check-config" "$test_tmp_dir/test.env" >/dev/null 2>&1; then
  printf 'unsafe Telegram allow-all configuration unexpectedly passed\n' >&2
  exit 1
fi
mv "$test_tmp_dir/hermes-safe.env" "$test_tmp_dir/hermes.env"

cp "$test_tmp_dir/hermes.env" "$test_tmp_dir/hermes-safe.env"
printf 'OPENCODE_GO_BASE_URL=https://unreviewed.invalid/v1\n' >>"$test_tmp_dir/hermes.env"
if NIX_ALLOW_TEST_CONFIG=1 "$repo_root/scripts/check-config" "$test_tmp_dir/test.env" >/dev/null 2>&1; then
  printf 'OpenCode Go endpoint override unexpectedly passed\n' >&2
  exit 1
fi
mv "$test_tmp_dir/hermes-safe.env" "$test_tmp_dir/hermes.env"

cp "$test_tmp_dir/founder-relay.env" "$test_tmp_dir/founder-relay-safe.env"
sed 's/^NIX_LIOR_TELEGRAM_CHAT_ID=.*$/NIX_LIOR_TELEGRAM_CHAT_ID=987654321/' \
  "$test_tmp_dir/founder-relay-safe.env" >"$test_tmp_dir/founder-relay.env"
if NIX_ALLOW_TEST_CONFIG=1 "$repo_root/scripts/check-config" "$test_tmp_dir/test.env" >/dev/null 2>&1; then
  printf 'mismatched founder relay Telegram identity unexpectedly passed\n' >&2
  exit 1
fi
mv "$test_tmp_dir/founder-relay-safe.env" "$test_tmp_dir/founder-relay.env"

cp "$test_tmp_dir/specialist-provider.env" "$test_tmp_dir/specialist-provider-safe.env"
{
  printf 'DAYTONA_API_KEY=REPLACE_WITH_DAYTONA_API_KEY\n'
  printf 'OPENCODE_API_KEY=REPLACE_WITH_RESTRICTED_OPENCODE_API_KEY\n'
} >"$test_tmp_dir/specialist-provider.env"
if NIX_ALLOW_TEST_CONFIG=1 "$repo_root/scripts/check-config" "$test_tmp_dir/test.env" >/dev/null 2>&1; then
  printf 'placeholder specialist provider credential unexpectedly passed\n' >&2
  exit 1
fi
mv "$test_tmp_dir/specialist-provider-safe.env" "$test_tmp_dir/specialist-provider.env"

cp "$test_tmp_dir/specialist-provider.env" "$test_tmp_dir/specialist-provider-safe.env"
daytona_fixture=$(grep '^DAYTONA_API_KEY=' "$test_tmp_dir/specialist-provider.env" | cut -d= -f2-)
sed "s|^OPENCODE_API_KEY=.*$|OPENCODE_API_KEY=$daytona_fixture|" \
  "$test_tmp_dir/specialist-provider-safe.env" >"$test_tmp_dir/specialist-provider.env"
if NIX_ALLOW_TEST_CONFIG=1 "$repo_root/scripts/check-config" "$test_tmp_dir/test.env" >/dev/null 2>&1; then
  printf 'reused Daytona key in specialist OpenCode binding unexpectedly passed\n' >&2
  exit 1
fi
mv "$test_tmp_dir/specialist-provider-safe.env" "$test_tmp_dir/specialist-provider.env"

cp "$test_tmp_dir/specialist-provider.env" "$test_tmp_dir/specialist-provider-safe.env"
chief_provider_fixture=$(grep '^OPENCODE_GO_API_KEY=' "$test_tmp_dir/hermes.env" | cut -d= -f2-)
sed "s|^OPENCODE_API_KEY=.*$|OPENCODE_API_KEY=$chief_provider_fixture|" \
  "$test_tmp_dir/specialist-provider-safe.env" >"$test_tmp_dir/specialist-provider.env"
if NIX_ALLOW_TEST_CONFIG=1 "$repo_root/scripts/check-config" "$test_tmp_dir/test.env" >/dev/null 2>&1; then
  printf 'reused Chief provider key in specialist OpenCode binding unexpectedly passed\n' >&2
  exit 1
fi
mv "$test_tmp_dir/specialist-provider-safe.env" "$test_tmp_dir/specialist-provider.env"

cp "$test_tmp_dir/specialist-provider.env" "$test_tmp_dir/specialist-provider-safe.env"
api_fixture=$(grep '^API_SERVER_KEY=' "$test_tmp_dir/hermes.env" | cut -d= -f2-)
sed "s|^DAYTONA_API_KEY=.*$|DAYTONA_API_KEY=$api_fixture|" \
  "$test_tmp_dir/specialist-provider-safe.env" >"$test_tmp_dir/specialist-provider.env"
if NIX_ALLOW_TEST_CONFIG=1 "$repo_root/scripts/check-config" "$test_tmp_dir/test.env" >/dev/null 2>&1; then
  printf 'reused Chief control credential in Daytona binding unexpectedly passed\n' >&2
  exit 1
fi
mv "$test_tmp_dir/specialist-provider-safe.env" "$test_tmp_dir/specialist-provider.env"

cp "$test_tmp_dir/test.env" "$test_tmp_dir/invalid-bot.env"
sed 's/^HERMES_TELEGRAM_BOT_USERNAME=the_nixos_bot$/HERMES_TELEGRAM_BOT_USERNAME=@the_nixos_bot/' \
  "$test_tmp_dir/invalid-bot.env" >"$test_tmp_dir/invalid-bot-new.env"
mv "$test_tmp_dir/invalid-bot-new.env" "$test_tmp_dir/invalid-bot.env"
if NIX_ALLOW_TEST_CONFIG=1 "$repo_root/scripts/check-config" "$test_tmp_dir/invalid-bot.env" >/dev/null 2>&1; then
  printf 'unsafe Telegram bot username configuration unexpectedly passed\n' >&2
  exit 1
fi

age_private_pattern='AGE-SECRET-KEY-(PQ-)?1[[:alnum:]]{20,}|AGE-PLUGIN-[A-Z0-9-]+-1[[:alnum:]]{20,}'
public_secret_pattern='[0-9]{8,}:[A-Za-z0-9_-]{30,}|pcp_(api|claim|invite|bootstrap)?[_-]?[A-Za-z0-9_-]{30,}|ya29\.[A-Za-z0-9._-]{20,}|"refresh_token"[[:space:]]*:[[:space:]]*"[A-Za-z0-9._/-]{20,}"|^API_SERVER_KEY=[A-Za-z0-9_-]{32,}|^OPENCODE(_GO)?_API_KEY=[A-Za-z0-9_-]{40,}'

if grep -RIlE --exclude-dir=.git --exclude='*.md' --exclude='.env.example' \
  '(ghp_[[:alnum:]]{20,}|github_pat_[[:alnum:]_]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|[0-9]{8,}:[A-Za-z0-9_-]{30,})' \
  "$repo_root"; then
  printf 'potential committed secret detected\n' >&2
  exit 1
fi

if grep -RIlE --exclude-dir=.git "$age_private_pattern" "$repo_root"; then
  printf 'age private identity detected in the working tree\n' >&2
  exit 1
fi
if grep -RIlE --exclude-dir=.git "$public_secret_pattern" "$repo_root"; then
  printf 'runtime/API credential pattern detected in the working tree\n' >&2
  exit 1
fi

# Scan every locally reachable commit without printing matching secret text.
while IFS= read -r revision; do
  if git -C "$repo_root" grep -I -q -E "$age_private_pattern" "$revision" --; then
    printf 'age private identity detected in reachable Git history at commit %s\n' "$revision" >&2
    exit 1
  fi
  if git -C "$repo_root" grep -I -q -E "$public_secret_pattern" "$revision" --; then
    printf 'runtime/API credential pattern detected in reachable Git history at commit %s\n' "$revision" >&2
    exit 1
  fi
  if git -C "$repo_root" ls-tree -r --name-only "$revision" \
    | grep -Eq '(^|/)\.env$|(^|/)auth\.json$|(^|/)rclone\.conf$|(^|/)nix-brain/'; then
    printf 'runtime secret file or private nix-brain content detected in reachable Git history at commit %s\n' "$revision" >&2
    exit 1
  fi
done < <(git -C "$repo_root" rev-list --all)

if grep -RIEq 'runs-on:[[:space:]]*self-hosted|pull_request_target:|secrets\.' "$repo_root/.github/workflows"; then
  printf 'public CI must not use self-hosted runners, pull_request_target, or repository secrets\n' >&2
  exit 1
fi
grep -q '^permissions:$' "$repo_root/.github/workflows/ci.yml"
grep -q '^  contents: read$' "$repo_root/.github/workflows/ci.yml"

grep -Fq 'up -d --no-deps --wait --force-recreate hermes' "$repo_root/docs/runbooks/DEPLOY.md"
if grep -Fq "test -z \"\${TELEGRAM_BOT_TOKEN:-}\"" "$repo_root/docs/runbooks/DEPLOY.md"; then
  printf 'deployment runbook must inspect the live gateway process, not docker exec environment defaults\n' >&2
  exit 1
fi
grep -Fq "NIX_EXPECT_TELEGRAM_MODE=\$mode" "$repo_root/scripts/configure-hermes"
grep -Fq "verify-processes \"\$PWD/.env\"" "$repo_root/docs/runbooks/DEPLOY.md"
python3 - "$repo_root" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
deploy = (root / "docs/runbooks/DEPLOY.md").read_text()
restore = (root / "docs/runbooks/RESTORE.md").read_text()
live_sequence = '''sudo -E ./scripts/configure-hermes telegram-enable "$PWD/.env"
sudo -E docker compose --env-file "$PWD/.env" up -d --no-deps --wait --force-recreate hermes
sudo -E ./scripts/configure-hermes verify "$PWD/.env"'''
assert live_sequence in "\n".join(line.strip() for line in deploy.splitlines())
assert live_sequence in "\n".join(line.strip() for line in restore.splitlines())
assert 'verify-processes)' in (root / "scripts/configure-hermes").read_text()
rollback = '''if sudo -E docker compose --env-file "$PWD/.env" stop hermes \\
&& sudo -E ./scripts/configure-hermes telegram-disable "$PWD/.env" \\
&& sudo -E docker compose --env-file "$PWD/.env" up -d --no-deps --wait --force-recreate hermes \\
&& sudo -E ./scripts/configure-hermes verify-processes "$PWD/.env"; then'''
assert rollback in "\n".join(line.strip() for line in deploy.splitlines())
assert "Replacing the individually bind-mounted marker without recreating the container is not a durable rollback." in restore
assert 'NIX_ALLOW_TEST_CONFIG=1 "$repo_root/scripts/check-config" "$restore_config"' in (root / "scripts/restore-smoke").read_text()
assert '-e "NIX_EXPECT_BRAIN_GID=$restore_brain_gid" hermes' in (root / "scripts/restore-smoke").read_text()
PY

printf 'Foundation configuration tests passed.\n'
