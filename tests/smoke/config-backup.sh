#!/usr/bin/env bash
set -euo pipefail
umask 077

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
test_tmp_dir=$(mktemp -d /tmp/nix-os-config-pack-test.XXXXXX)
trap 'rm -rf "$test_tmp_dir"' EXIT

command -v age >/dev/null 2>&1 || { printf 'age is required for the configuration-pack test\n' >&2; exit 1; }
command -v age-keygen >/dev/null 2>&1 || { printf 'age-keygen is required for the configuration-pack test\n' >&2; exit 1; }

source_dir="$test_tmp_dir/source"
mkdir -p "$source_dir/secrets" "$source_dir/backups"
postgres_password=$(openssl rand -hex 32)
paperclip_db_password=$(openssl rand -hex 32)
printf 'POSTGRES_PASSWORD=%s\nPAPERCLIP_DB_PASSWORD=%s\n' "$postgres_password" "$paperclip_db_password" >"$source_dir/secrets/postgres.env"
{
  printf 'DATABASE_URL=postgresql://paperclip:%s@postgres:5432/paperclip\n' "$paperclip_db_password"
  printf 'BETTER_AUTH_SECRET=%s\n' "$(openssl rand -hex 32)"
  printf 'PAPERCLIP_TOOL_ACTION_SIGNING_SECRET=%s\n' "$(openssl rand -hex 32)"
} >"$source_dir/secrets/paperclip.env"
{
  printf 'API_SERVER_KEY=%s\n' "$(openssl rand -hex 32)"
  printf 'TELEGRAM_BOT_TOKEN=test-token\nTELEGRAM_ALLOWED_USERS=123456789\n'
  printf 'TELEGRAM_ALLOW_ALL_USERS=false\nGATEWAY_ALLOW_ALL_USERS=false\n'
} >"$source_dir/secrets/hermes.env"
mkdir "$source_dir/nix-brain"
{
  printf 'COMPOSE_PROJECT_NAME=nix-os-config-pack-test\n'
  printf 'PAPERCLIP_PUBLIC_URL=https://nix-os.test-tailnet.ts.net\n'
  printf 'PAPERCLIP_HOST_PORT=3100\n'
  printf 'POSTGRES_ENV_FILE=%s\n' "$source_dir/secrets/postgres.env"
  printf 'PAPERCLIP_ENV_FILE=%s\n' "$source_dir/secrets/paperclip.env"
  printf 'HERMES_ENV_FILE=%s\n' "$source_dir/secrets/hermes.env"
  printf 'NIX_BRAIN_HOST_PATH=%s\n' "$source_dir/nix-brain"
  printf 'PAPERCLIP_AUTH_DISABLE_SIGN_UP=true\n'
  printf 'BACKUP_OUTPUT_DIR=%s\n' "$source_dir/backups"
} >"$source_dir/deployment.env"
chmod 0600 "$source_dir"/deployment.env "$source_dir"/secrets/*.env

age-keygen -o "$test_tmp_dir/identity.txt" >/dev/null 2>&1
recipient=$(age-keygen -y "$test_tmp_dir/identity.txt")
artifact=$(NIX_ALLOW_TEST_CONFIG=1 BACKUP_AGE_RECIPIENT="$recipient" \
  "$repo_root/scripts/backup-config" "$source_dir/deployment.env" | tail -n 1)
[[ -f "$artifact" && -f "${artifact}.sha256" ]] || { printf 'encrypted configuration pack was not created\n' >&2; exit 1; }

download_dir="$test_tmp_dir/downloaded"
mkdir "$download_dir"
cp "$artifact" "${artifact}.sha256" "$download_dir/"
artifact="$download_dir/$(basename "$artifact")"

restore_root="$test_tmp_dir/restored-root"
restored_config="$test_tmp_dir/restored-checkout/.env"
CONFIG_RESTORE_ROOT="$restore_root" AGE_IDENTITY_FILE="$test_tmp_dir/identity.txt" \
  "$repo_root/scripts/restore-config" "$artifact" "$restored_config" >/dev/null

restored_postgres="$restore_root$source_dir/secrets/postgres.env"
restored_paperclip="$restore_root$source_dir/secrets/paperclip.env"
restored_hermes="$restore_root$source_dir/secrets/hermes.env"
cmp -s "$source_dir/secrets/postgres.env" "$restored_postgres"
cmp -s "$source_dir/secrets/paperclip.env" "$restored_paperclip"
cmp -s "$source_dir/secrets/hermes.env" "$restored_hermes"
for restored_file in "$restored_config" "$restored_postgres" "$restored_paperclip" "$restored_hermes"; do
  mode=$(stat -c '%a' "$restored_file" 2>/dev/null || stat -f '%Lp' "$restored_file")
  [[ "$mode" == 600 ]] || { printf 'restored file has unsafe mode %s: %s\n' "$mode" "$restored_file" >&2; exit 1; }
done
NIX_ALLOW_TEST_CONFIG=1 "$repo_root/scripts/check-config" "$restored_config" >/dev/null

printf 'Encrypted configuration-pack backup and restore passed.\n'
