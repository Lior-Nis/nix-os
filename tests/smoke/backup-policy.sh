#!/usr/bin/env bash
set -euo pipefail
umask 077

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
test_tmp_dir=$(mktemp -d /tmp/nix-os-backup-policy.XXXXXX)
trap 'rm -rf "$test_tmp_dir"' EXIT

fail() {
  printf 'backup policy test error: %s\n' "$*" >&2
  exit 1
}

fake_bin="$repo_root/tests/fixtures/backup-policy"

postgres_password='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
paperclip_db_password='bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
printf 'POSTGRES_PASSWORD=%s\nPAPERCLIP_DB_PASSWORD=%s\n' \
  "$postgres_password" "$paperclip_db_password" >"$test_tmp_dir/postgres.env"
{
  printf 'DATABASE_URL=postgresql://paperclip:%s@postgres:5432/paperclip\n' "$paperclip_db_password"
  printf 'BETTER_AUTH_SECRET=cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc\n'
  printf 'PAPERCLIP_TOOL_ACTION_SIGNING_SECRET=dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd\n'
} >"$test_tmp_dir/paperclip.env"
{
  printf 'API_SERVER_KEY=eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee\n'
  printf 'TELEGRAM_BOT_TOKEN=test-token\nTELEGRAM_ALLOWED_USERS=123456789\n'
  printf 'TELEGRAM_ALLOW_ALL_USERS=false\nGATEWAY_ALLOW_ALL_USERS=false\n'
} >"$test_tmp_dir/hermes.env"
printf 'HERMES_TELEGRAM_MODE=disabled\n' >"$test_tmp_dir/hermes-telegram-mode.env"
mkdir "$test_tmp_dir/nix-brain"
{
  printf 'COMPOSE_PROJECT_NAME=nix-os-backup-policy-test\n'
  printf 'PAPERCLIP_PUBLIC_URL=https://nix-os.test-tailnet.ts.net\nPAPERCLIP_HOST_PORT=0\n'
  printf 'POSTGRES_ENV_FILE=%s\nPAPERCLIP_ENV_FILE=%s\n' "$test_tmp_dir/postgres.env" "$test_tmp_dir/paperclip.env"
  printf 'HERMES_ENV_FILE=%s\nNIX_BRAIN_HOST_PATH=%s\n' "$test_tmp_dir/hermes.env" "$test_tmp_dir/nix-brain"
  printf 'HERMES_TELEGRAM_MODE_FILE=%s\n' "$test_tmp_dir/hermes-telegram-mode.env"
  printf 'PAPERCLIP_AUTH_DISABLE_SIGN_UP=true\nBACKUP_OUTPUT_DIR=%s\n' "$test_tmp_dir/backups"
} >"$test_tmp_dir/test.env"
chmod 0600 "$test_tmp_dir"/*.env

if PATH="$fake_bin:$PATH" NIX_ALLOW_TEST_CONFIG=1 \
  "$repo_root/scripts/backup" "$test_tmp_dir/test.env" >"$test_tmp_dir/missing.out" 2>"$test_tmp_dir/missing.err"; then
  fail 'backup without BACKUP_AGE_RECIPIENT unexpectedly succeeded'
fi
grep -q 'BACKUP_AGE_RECIPIENT is required' "$test_tmp_dir/missing.err" \
  || fail 'missing-recipient failure was not explicit'
[[ ! -e "$test_tmp_dir/backups" ]] \
  || fail 'missing-recipient failure created the backup output directory'

if PATH="$fake_bin:$PATH" NIX_TEST_ONLY_ALLOW_UNENCRYPTED_BACKUP=1 \
  "$repo_root/scripts/backup" "$test_tmp_dir/test.env" >"$test_tmp_dir/gate.out" 2>"$test_tmp_dir/gate.err"; then
  fail 'test-only plaintext backup bypassed NIX_ALLOW_TEST_CONFIG'
fi
grep -q 'requires NIX_ALLOW_TEST_CONFIG=1' "$test_tmp_dir/gate.err" \
  || fail 'test-only plaintext gate failure was not explicit'

plaintext_artifact=$(PATH="$fake_bin:$PATH" NIX_ALLOW_TEST_CONFIG=1 \
  NIX_TEST_ONLY_ALLOW_UNENCRYPTED_BACKUP=1 \
  "$repo_root/scripts/backup" "$test_tmp_dir/test.env" | tail -n 1)
[[ "$plaintext_artifact" == *.tar.gz && -f "$plaintext_artifact" ]] \
  || fail 'explicit test-only mode did not create its fixture archive'
[[ -f "${plaintext_artifact}.sha256" ]] || fail 'test-only fixture checksum is missing'
tar -tzf "$plaintext_artifact" >/dev/null
rm -rf "$test_tmp_dir/backups"

if PATH="$fake_bin:$PATH" NIX_ALLOW_TEST_CONFIG=1 FAKE_AGE_EXIT=23 \
  BACKUP_AGE_RECIPIENT=age1fixture \
  "$repo_root/scripts/backup" "$test_tmp_dir/test.env" >"$test_tmp_dir/age.out" 2>"$test_tmp_dir/age.err"; then
  fail 'backup unexpectedly succeeded when age failed'
fi
if [[ -d "$test_tmp_dir/backups" ]] && find "$test_tmp_dir/backups" -type f -print -quit | grep -q .; then
  fail 'age failure left a plaintext, partial, or published backup artifact behind'
fi

printf 'State backup encryption policy tests passed.\n'
