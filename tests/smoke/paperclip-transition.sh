#!/usr/bin/env bash
set -euo pipefail
umask 077

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
test_tmp_dir=$(mktemp -d /tmp/nix-os-paperclip-transition.XXXXXX)
trap 'rm -rf "$test_tmp_dir"' EXIT

fixture_bin="$test_tmp_dir/bin"
fixture_state="$test_tmp_dir/state"
mkdir -p "$fixture_bin" "$fixture_state" "$test_tmp_dir/nix-brain"
ln -s "$repo_root/tests/fixtures/paperclip-transition/docker" "$fixture_bin/docker"

postgres_password='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
paperclip_db_password='dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd'
printf 'POSTGRES_PASSWORD=%s\nPAPERCLIP_DB_PASSWORD=%s\n' \
  "$postgres_password" "$paperclip_db_password" >"$test_tmp_dir/postgres.env"
{
  printf 'DATABASE_URL=postgresql://paperclip:%s@postgres:5432/paperclip\n' "$paperclip_db_password"
  printf 'BETTER_AUTH_SECRET=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n'
  printf 'PAPERCLIP_TOOL_ACTION_SIGNING_SECRET=cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc\n'
} >"$test_tmp_dir/paperclip.env"
{
  printf 'API_SERVER_KEY=eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee\n'
  printf 'TELEGRAM_BOT_TOKEN=test-token\nTELEGRAM_ALLOWED_USERS=123456789\n'
  printf 'TELEGRAM_ALLOW_ALL_USERS=false\nGATEWAY_ALLOW_ALL_USERS=false\n'
} >"$test_tmp_dir/hermes.env"
printf 'HERMES_TELEGRAM_MODE=disabled\n' >"$test_tmp_dir/hermes-telegram-mode.env"
{
  printf 'COMPOSE_PROJECT_NAME=nix-os-transition\n'
  printf 'PAPERCLIP_PUBLIC_URL=https://nix-os.test-tailnet.ts.net\n'
  printf 'PAPERCLIP_LIOR_USER_ID=lior-test-user\n'
  printf 'PAPERCLIP_HOST_PORT=0\n'
  printf 'POSTGRES_ENV_FILE=%s\n' "$test_tmp_dir/postgres.env"
  printf 'PAPERCLIP_ENV_FILE=%s\n' "$test_tmp_dir/paperclip.env"
  printf 'HERMES_ENV_FILE=%s\n' "$test_tmp_dir/hermes.env"
  printf 'HERMES_TELEGRAM_MODE_FILE=%s\n' "$test_tmp_dir/hermes-telegram-mode.env"
  printf 'NIX_BRAIN_HOST_PATH=%s\n' "$test_tmp_dir/nix-brain"
  printf 'PAPERCLIP_AUTH_DISABLE_SIGN_UP=true\n'
  printf 'BACKUP_OUTPUT_DIR=%s\n' "$test_tmp_dir/backups"
} >"$test_tmp_dir/test.env"
chmod 0600 "$test_tmp_dir"/*.env

printf 'paperclip-old\n' >"$fixture_state/paperclip-id"
printf 'postgres-unchanged\n' >"$fixture_state/postgres-id"
printf 'hermes-unchanged\n' >"$fixture_state/hermes-id"
printf 'foreign-network-unchanged\n' >"$fixture_state/foreign-network"
printf '0\n' >"$fixture_state/recreate-count"
: >"$fixture_state/commands.log"

export PATH="$fixture_bin:$PATH"
export PAPERCLIP_TRANSITION_FIXTURE_STATE="$fixture_state"
export NIX_ALLOW_TEST_CONFIG=1

output=$("$repo_root/scripts/transition-paperclip" "$test_tmp_dir/test.env")
grep -q 'Paperclip alone was recreated' <<<"$output"
[[ $(cat "$fixture_state/paperclip-id") == paperclip-new ]]
[[ $(cat "$fixture_state/recreate-count") == 1 ]]
[[ $(cat "$fixture_state/postgres-id") == postgres-unchanged ]]
[[ $(cat "$fixture_state/hermes-id") == hermes-unchanged ]]
[[ $(cat "$fixture_state/foreign-network") == foreign-network-unchanged ]]
grep -q 'up -d --no-deps --force-recreate --wait paperclip' "$fixture_state/commands.log"
if grep -Eq 'up .*\b(postgres|hermes)\b' "$fixture_state/commands.log"; then
  printf 'transition attempted to recreate PostgreSQL or Hermes\n' >&2
  exit 1
fi

command_count=$(wc -l <"$fixture_state/commands.log" | tr -d ' ')
output=$("$repo_root/scripts/transition-paperclip" "$test_tmp_dir/test.env")
grep -q 'already transition-compliant' <<<"$output"
[[ $(cat "$fixture_state/recreate-count") == 1 ]]
[[ $(wc -l <"$fixture_state/commands.log" | tr -d ' ') -gt $command_count ]]
[[ $(grep -c 'up -d --no-deps --force-recreate --wait paperclip' "$fixture_state/commands.log") == 1 ]]

printf 'paperclip-old\n' >"$fixture_state/paperclip-id"
export PAPERCLIP_TRANSITION_FIXTURE_FAIL_MIGRATION=1
if "$repo_root/scripts/transition-paperclip" "$test_tmp_dir/test.env" >/dev/null 2>&1; then
  printf 'failed migration preflight unexpectedly recreated Paperclip\n' >&2
  exit 1
fi
unset PAPERCLIP_TRANSITION_FIXTURE_FAIL_MIGRATION
[[ $(cat "$fixture_state/paperclip-id") == paperclip-old ]]
[[ $(cat "$fixture_state/recreate-count") == 1 ]]

printf 'Paperclip Slice 0 to Slice 1 transition tests passed.\n'
