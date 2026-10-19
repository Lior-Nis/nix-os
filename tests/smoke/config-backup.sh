#!/usr/bin/env bash
set -euo pipefail
umask 077

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
test_tmp_dir=$(mktemp -d /tmp/nix-os-config-pack-test.XXXXXX)
trap 'rm -rf "$test_tmp_dir"' EXIT

write_artifact_sidecar() {
  local artifact=$1 digest
  if command -v sha256sum >/dev/null 2>&1; then
    digest=$(sha256sum "$artifact" | cut -d' ' -f1)
  else
    digest=$(shasum -a 256 "$artifact" | cut -d' ' -f1)
  fi
  printf '%s  %s\n' "$digest" "$(basename "$artifact")" >"${artifact}.sha256"
  chmod 0600 "${artifact}.sha256"
}

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
  decision_webhook_secret=$(openssl rand -hex 32)
  printf 'HERMES_DECISION_WEBHOOK_SECRET=%s\n' "$decision_webhook_secret"
  printf 'WEBHOOK_SECRET=%s\n' "$decision_webhook_secret"
  printf 'OPENCODE_GO_API_KEY=test-opencode-go-key-12345678\n'
  printf 'TELEGRAM_BOT_TOKEN=test-token\nTELEGRAM_ALLOWED_USERS=123456789\nTELEGRAM_HOME_CHANNEL=123456789\n'
  printf 'TELEGRAM_ALLOW_ALL_USERS=false\nGATEWAY_ALLOW_ALL_USERS=false\n'
} >"$source_dir/secrets/hermes.env"
printf 'HERMES_TELEGRAM_MODE=disabled\n' >"$source_dir/secrets/hermes-telegram-mode.env"
"$repo_root/tests/fixtures/create-slice3-secret-files" "$source_dir/secrets"
mkdir "$source_dir/nix-brain"
brain_gid=$("$repo_root/tests/fixtures/select-brain-gid")
chgrp "$brain_gid" "$source_dir/nix-brain"
chmod 0750 "$source_dir/nix-brain"
brain_gid=$(stat -c '%g' "$source_dir/nix-brain" 2>/dev/null || stat -f '%g' "$source_dir/nix-brain")
{
  printf 'COMPOSE_PROJECT_NAME=nix-os-config-pack-test\n'
  printf 'PAPERCLIP_PUBLIC_URL=https://nix-os.test-tailnet.ts.net\n'
  printf 'PAPERCLIP_RUNNER_PUBLIC_URL=wss://nix-os.test-tailnet.ts.net\n'
  printf 'PAPERCLIP_LIOR_USER_ID=lior-test-user\n'
  printf 'PAPERCLIP_HOST_PORT=3100\n'
  printf 'POSTGRES_ENV_FILE=%s\n' "$source_dir/secrets/postgres.env"
  printf 'PAPERCLIP_ENV_FILE=%s\n' "$source_dir/secrets/paperclip.env"
  printf 'HERMES_ENV_FILE=%s\n' "$source_dir/secrets/hermes.env"
  printf 'FOUNDER_RELAY_ENV_FILE=%s\n' "$source_dir/secrets/founder-relay.env"
  printf 'HERMES_TELEGRAM_BOT_USERNAME=the_nixos_bot\n'
  printf 'HERMES_TELEGRAM_MODE_FILE=%s\n' "$source_dir/secrets/hermes-telegram-mode.env"
  printf 'SPECIALIST_PROVIDER_ENV_FILE=%s\n' "$source_dir/secrets/specialist-provider.env"
  printf 'SPECIALIST_WORKER_HOST_KEY_FILE=%s\n' "$source_dir/secrets/specialist-host-key"
  printf 'SPECIALIST_WORKER_AUTHORIZED_KEYS_FILE=%s\n' "$source_dir/secrets/specialist-authorized-keys"
  printf 'SPECIALIST_WORKER_CLIENT_KEY_FILE=%s\n' "$source_dir/secrets/specialist-client-key"
  printf 'NIX_CHIEF_AGENT_ID=11111111-1111-4111-8111-111111111111\n'
  printf 'NIX_APPROVED_PROJECT_ID=22222222-2222-4222-8222-222222222222\n'
  printf 'NIX_PRODUCT_AGENT_ID=33333333-3333-4333-8333-333333333333\n'
  printf 'NIX_GROWTH_AGENT_ID=44444444-4444-4444-8444-444444444444\n'
  printf 'NIX_OPERATIONS_AGENT_ID=55555555-5555-4555-8555-555555555555\n'
  printf 'NIX_SPECIALIST_AGENT_IDS=33333333-3333-4333-8333-333333333333,44444444-4444-4444-8444-444444444444,55555555-5555-4555-8555-555555555555\n'
  printf 'NIX_PRODUCT_ENVIRONMENT_ID=66666666-6666-4666-8666-666666666666\n'
  printf 'NIX_GROWTH_ENVIRONMENT_ID=77777777-7777-4777-8777-777777777777\n'
  printf 'NIX_OPERATIONS_ENVIRONMENT_ID=88888888-8888-4888-8888-888888888888\n'
  printf 'NIX_SPECIALIST_ENVIRONMENT_IDS=66666666-6666-4666-8666-666666666666,77777777-7777-4777-8777-777777777777,88888888-8888-4888-8888-888888888888\n'
  printf 'NIX_BRAIN_HOST_PATH=%s\n' "$source_dir/nix-brain"
  printf 'NIX_BRAIN_GID=%s\n' "$brain_gid"
  printf 'PAPERCLIP_AUTH_DISABLE_SIGN_UP=true\n'
  printf 'BACKUP_OUTPUT_DIR=%s\n' "$source_dir/backups"
} >"$source_dir/deployment.env"
chmod 0600 "$source_dir"/deployment.env "$source_dir"/secrets/*.env

age-keygen -o "$test_tmp_dir/identity.txt" >/dev/null 2>&1
recipient=$(age-keygen -y "$test_tmp_dir/identity.txt")
artifact=$(NIX_ALLOW_TEST_CONFIG=1 BACKUP_AGE_RECIPIENT="$recipient" \
  "$repo_root/scripts/backup-config" "$source_dir/deployment.env" | tail -n 1)
[[ -f "$artifact" && -f "${artifact}.sha256" ]] || { printf 'encrypted configuration pack was not created\n' >&2; exit 1; }

missing_sidecar_artifact="$test_tmp_dir/missing-sidecar.tar.gz.age"
cp "$artifact" "$missing_sidecar_artifact"
if CONFIG_RESTORE_ROOT="$test_tmp_dir/missing-sidecar-root" \
  AGE_IDENTITY_FILE="$test_tmp_dir/identity.txt" \
  "$repo_root/scripts/restore-config" "$missing_sidecar_artifact" \
  "$test_tmp_dir/missing-sidecar-root/checkout/.env" \
  >"$test_tmp_dir/missing-sidecar.out" 2>"$test_tmp_dir/missing-sidecar.err"; then
  printf 'configuration restore accepted an artifact without its checksum sidecar\n' >&2
  exit 1
fi
grep -q 'sidecar is missing or unsafe' "$test_tmp_dir/missing-sidecar.err"

tampered_sidecar_artifact="$test_tmp_dir/tampered-sidecar.tar.gz.age"
cp "$artifact" "$tampered_sidecar_artifact"
printf '%064d  %s\n' 0 "$(basename "$tampered_sidecar_artifact")" \
  >"${tampered_sidecar_artifact}.sha256"
if CONFIG_RESTORE_ROOT="$test_tmp_dir/tampered-sidecar-root" \
  AGE_IDENTITY_FILE="$test_tmp_dir/identity.txt" \
  "$repo_root/scripts/restore-config" "$tampered_sidecar_artifact" \
  "$test_tmp_dir/tampered-sidecar-root/checkout/.env" \
  >"$test_tmp_dir/tampered-sidecar.out" 2>"$test_tmp_dir/tampered-sidecar.err"; then
  printf 'configuration restore accepted a mismatched checksum sidecar\n' >&2
  exit 1
fi
grep -q 'checksum mismatch' "$test_tmp_dir/tampered-sidecar.err"

publish_failure_dir="$test_tmp_dir/publish-failure"
if NIX_ALLOW_TEST_CONFIG=1 NIX_TEST_FAIL_CONFIG_PUBLISH_AFTER_ARTIFACT=1 \
  BACKUP_OUTPUT_DIR="$publish_failure_dir" BACKUP_AGE_RECIPIENT="$recipient" \
  "$repo_root/scripts/backup-config" "$source_dir/deployment.env" \
  >"$test_tmp_dir/publish-failure.out" 2>"$test_tmp_dir/publish-failure.err"; then
  printf 'configuration backup unexpectedly survived its injected publish failure\n' >&2
  exit 1
fi
grep -q 'injected configuration publish failure' "$test_tmp_dir/publish-failure.err"
if find "$publish_failure_dir" -type f -print -quit | grep -q .; then
  printf 'configuration publish failure left a partial artifact or sidecar\n' >&2
  exit 1
fi

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
restored_founder_relay="$restore_root$source_dir/secrets/founder-relay.env"
restored_provider_env="$restore_root$source_dir/secrets/specialist-provider.env"
cmp -s "$source_dir/secrets/postgres.env" "$restored_postgres"
cmp -s "$source_dir/secrets/paperclip.env" "$restored_paperclip"
cmp -s "$source_dir/secrets/hermes.env" "$restored_hermes"
cmp -s "$source_dir/secrets/founder-relay.env" "$restored_founder_relay"
cmp -s "$source_dir/secrets/specialist-provider.env" "$restored_provider_env"
for restored_file in \
  "$restored_config" \
  "$restored_postgres" \
  "$restored_paperclip" \
  "$restored_hermes" \
  "$restored_founder_relay" \
  "$restored_provider_env"; do
  mode=$(stat -c '%a' "$restored_file" 2>/dev/null || stat -f '%Lp' "$restored_file")
  [[ "$mode" == 600 ]] || { printf 'restored file has unsafe mode %s: %s\n' "$mode" "$restored_file" >&2; exit 1; }
done
NIX_ALLOW_TEST_CONFIG=1 "$repo_root/scripts/check-config" "$restored_config" >/dev/null

symlink_root="$test_tmp_dir/symlink-root"
symlink_escape="$test_tmp_dir/symlink-escape"
mkdir -p "$symlink_root" "$symlink_escape"
ln -s "$symlink_escape" "$symlink_root/tmp"
if CONFIG_RESTORE_ROOT="$symlink_root" AGE_IDENTITY_FILE="$test_tmp_dir/identity.txt" \
  "$repo_root/scripts/restore-config" "$artifact" "$symlink_root/checkout/.env" \
  >"$test_tmp_dir/symlink.out" 2>"$test_tmp_dir/symlink.err"; then
  printf 'configuration restore followed a symlink out of its restore root\n' >&2
  exit 1
fi
[[ -z $(find "$symlink_escape" -mindepth 1 -print -quit) ]] \
  || { printf 'configuration restore wrote through its restore-root symlink\n' >&2; exit 1; }

tamper_dir="$test_tmp_dir/tampered"
mkdir -p "$tamper_dir/unpacked"
age --decrypt --identity "$test_tmp_dir/identity.txt" --output "$tamper_dir/config.tar.gz" "$artifact"
tar -xzf "$tamper_dir/config.tar.gz" -C "$tamper_dir/unpacked"
tamper_payload=$(find "$tamper_dir/unpacked" -mindepth 1 -maxdepth 1 -type d -name 'nix-os-config-*')
printf 'POSTGRES_ENV_FILE=/duplicate/must-fail\n' >>"$tamper_payload/manifest.env"
(
  cd "$tamper_payload"
  manifest_digest=$(sha256sum manifest.env 2>/dev/null || shasum -a 256 manifest.env)
  awk -v replacement="$manifest_digest" '$2 == "manifest.env" { print replacement; next } { print }' \
    SHA256SUMS >SHA256SUMS.new
  mv SHA256SUMS.new SHA256SUMS
)
COPYFILE_DISABLE=1 tar -C "$tamper_dir/unpacked" -czf - "$(basename "$tamper_payload")" \
  | age --recipient "$recipient" --output "$tamper_dir/duplicate-manifest.tar.gz.age"
write_artifact_sidecar "$tamper_dir/duplicate-manifest.tar.gz.age"
if CONFIG_RESTORE_ROOT="$test_tmp_dir/duplicate-root" AGE_IDENTITY_FILE="$test_tmp_dir/identity.txt" \
  "$repo_root/scripts/restore-config" "$tamper_dir/duplicate-manifest.tar.gz.age" \
  "$test_tmp_dir/duplicate-root/checkout/.env" \
  >"$test_tmp_dir/duplicate.out" 2>"$test_tmp_dir/duplicate.err"; then
  printf 'configuration restore accepted a duplicate manifest path\n' >&2
  exit 1
fi
grep -q 'requires exactly one non-empty POSTGRES_ENV_FILE' "$test_tmp_dir/duplicate.err"

path_tamper_dir="$test_tmp_dir/path-tampered"
mkdir -p "$path_tamper_dir/unpacked"
tar -xzf "$tamper_dir/config.tar.gz" -C "$path_tamper_dir/unpacked"
path_tamper_payload=$(find "$path_tamper_dir/unpacked" -mindepth 1 -maxdepth 1 -type d -name 'nix-os-config-*')
awk '
  /^POSTGRES_ENV_FILE=/ { print "POSTGRES_ENV_FILE=/tmp/../restore-escape/postgres.env"; next }
  { print }
' "$path_tamper_payload/manifest.env" >"$path_tamper_payload/manifest.env.new"
mv "$path_tamper_payload/manifest.env.new" "$path_tamper_payload/manifest.env"
(
  cd "$path_tamper_payload"
  manifest_digest=$(sha256sum manifest.env 2>/dev/null || shasum -a 256 manifest.env)
  awk -v replacement="$manifest_digest" '$2 == "manifest.env" { print replacement; next } { print }' \
    SHA256SUMS >SHA256SUMS.new
  mv SHA256SUMS.new SHA256SUMS
)
COPYFILE_DISABLE=1 tar -C "$path_tamper_dir/unpacked" -czf - "$(basename "$path_tamper_payload")" \
  | age --recipient "$recipient" --output "$path_tamper_dir/non-normalized-manifest.tar.gz.age"
write_artifact_sidecar "$path_tamper_dir/non-normalized-manifest.tar.gz.age"
if CONFIG_RESTORE_ROOT="$test_tmp_dir/non-normalized-root" AGE_IDENTITY_FILE="$test_tmp_dir/identity.txt" \
  "$repo_root/scripts/restore-config" "$path_tamper_dir/non-normalized-manifest.tar.gz.age" \
  "$test_tmp_dir/non-normalized-root/checkout/.env" \
  >"$test_tmp_dir/non-normalized.out" 2>"$test_tmp_dir/non-normalized.err"; then
  printf 'configuration restore accepted a non-normalized manifest path\n' >&2
  exit 1
fi
grep -q 'unsafe or non-normalized secret path' "$test_tmp_dir/non-normalized.err"

printf 'Encrypted configuration-pack backup and restore passed.\n'
