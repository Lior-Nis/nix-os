#!/usr/bin/env bash
set -euo pipefail
umask 077

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
smoke_tmp_dir=$(mktemp -d /tmp/nix-os-backup-smoke.XXXXXX)
smoke_project="nix-os-smoke-$$"
restore_project="nix-os-restore-smoke-$$"
config_file="$smoke_tmp_dir/smoke.env"
compose=(docker compose --env-file "$config_file")

cleanup() {
  "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  docker volume rm "${restore_project}_paperclip_data" "${restore_project}_postgres_data" >/dev/null 2>&1 || true
  rm -rf "$smoke_tmp_dir"
}
trap cleanup EXIT

docker info >/dev/null
postgres_password=$(openssl rand -hex 32)
paperclip_db_password=$(openssl rand -hex 32)
printf 'POSTGRES_PASSWORD=%s\n' "$postgres_password" >"$smoke_tmp_dir/postgres.env"
printf 'PAPERCLIP_DB_PASSWORD=%s\n' "$paperclip_db_password" >>"$smoke_tmp_dir/postgres.env"
{
  printf 'DATABASE_URL=postgresql://paperclip:%s@postgres:5432/paperclip\n' "$paperclip_db_password"
  printf 'BETTER_AUTH_SECRET=%s\n' "$(openssl rand -hex 32)"
  printf 'PAPERCLIP_TOOL_ACTION_SIGNING_SECRET=%s\n' "$(openssl rand -hex 32)"
} >"$smoke_tmp_dir/paperclip.env"
{
  printf 'COMPOSE_PROJECT_NAME=%s\n' "$smoke_project"
  printf 'PAPERCLIP_HOSTNAME=paperclip.test\n'
  printf 'ACME_EMAIL=operator@test.invalid\n'
  printf 'POSTGRES_ENV_FILE=%s\n' "$smoke_tmp_dir/postgres.env"
  printf 'PAPERCLIP_ENV_FILE=%s\n' "$smoke_tmp_dir/paperclip.env"
  printf 'PAPERCLIP_AUTH_DISABLE_SIGN_UP=true\n'
  printf 'BACKUP_OUTPUT_DIR=%s\n' "$smoke_tmp_dir/backups"
} >"$config_file"
chmod 0600 "$smoke_tmp_dir"/*.env

NIX_ALLOW_TEST_CONFIG=1 "$repo_root/scripts/check-config" "$config_file"
"${compose[@]}" up -d --wait postgres paperclip
role_flags=$("${compose[@]}" exec -T postgres psql -U postgres -d postgres -At \
  -c "SELECT rolsuper || ':' || rolcreatedb || ':' || rolcreaterole FROM pg_roles WHERE rolname = 'paperclip'")
[[ "$role_flags" == 'false:false:false' ]] || { printf 'Paperclip database role is over-privileged: %s\n' "$role_flags" >&2; exit 1; }
"${compose[@]}" exec -T postgres psql -U paperclip -d paperclip \
  -c "CREATE SCHEMA nix_backup_smoke; CREATE TABLE nix_backup_smoke.marker (value text PRIMARY KEY); INSERT INTO nix_backup_smoke.marker VALUES ('slice-0-round-trip');"
"${compose[@]}" exec -T paperclip sh -ec "printf '%s\n' 'slice-0-volume-round-trip' > /paperclip/restore-smoke-marker.txt"

"${compose[@]}" stop postgres
health_status=$("${compose[@]}" exec -T paperclip sh -ec \
  "curl --silent --output /tmp/database-down-health.json --write-out '%{http_code}' http://127.0.0.1:3100/api/health")
[[ "$health_status" == 503 ]] || { printf 'expected health HTTP 503 with PostgreSQL stopped, got %s\n' "$health_status" >&2; exit 1; }
"${compose[@]}" exec -T paperclip grep -q 'database_unreachable' /tmp/database-down-health.json
"${compose[@]}" up -d --wait postgres paperclip

artifact=$(BACKUP_OUTPUT_DIR="$smoke_tmp_dir/backups" "$repo_root/scripts/backup" "$config_file" | tail -n 1)
[[ -f "$artifact" ]] || { printf 'backup artifact missing: %s\n' "$artifact" >&2; exit 1; }

download_dir="$smoke_tmp_dir/downloaded"
mkdir "$download_dir"
cp "$artifact" "${artifact}.sha256" "$download_dir/"
artifact="$download_dir/$(basename "$artifact")"

restore_work_dir="$smoke_tmp_dir/restore"
RESTORE_PROJECT_NAME="$restore_project" RESTORE_KEEP=true \
  RESTORE_WORK_DIR="$restore_work_dir" \
  "$repo_root/scripts/restore-smoke" "$artifact"

restore_config="$restore_work_dir/restore.env"
if [[ -f "$restore_config" ]]; then
  restore_compose=(docker compose --env-file "$restore_config")
  marker=$("${restore_compose[@]}" exec -T postgres psql -U paperclip -d paperclip -At \
    -c "SELECT value FROM nix_backup_smoke.marker")
  [[ "$marker" == 'slice-0-round-trip' ]] || { printf 'database marker did not survive restore\n' >&2; exit 1; }
  volume_marker=$("${restore_compose[@]}" exec -T paperclip sh -ec 'cat /paperclip/restore-smoke-marker.txt')
  [[ "$volume_marker" == 'slice-0-volume-round-trip' ]] || { printf 'volume marker did not survive restore\n' >&2; exit 1; }
  "${restore_compose[@]}" down --volumes --remove-orphans
else
  printf 'could not locate retained restore configuration\n' >&2
  exit 1
fi

printf 'Backup and isolated restore smoke passed.\n'
