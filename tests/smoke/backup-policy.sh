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

# shellcheck disable=SC2016
grep -Fq 'test "$(find /state -maxdepth 1 -name ".paperclip-claim-*.pending" | wc -l | tr -d " ")" = 0' \
  "$repo_root/scripts/backup" || fail 'backup does not reject pending claim markers'
grep -Fq 'test ! -e /state/mcp-tokens/nix-os-paperclip-claim-stage.json' "$repo_root/scripts/backup" \
  || fail 'backup does not reject a staged claim secret'
grep -Fq 'scripts/check-paperclip-specialist-topology' "$repo_root/scripts/backup" \
  || fail 'backup does not gate production capture on specialist topology'
grep -Fq 'NIX_BACKUP_PRE_SPECIALIST_TRANSITION is allowed only before any Slice 3 identity is configured' \
  "$repo_root/scripts/backup" \
  || fail 'backup lacks the narrowly guarded Slice 2 to Slice 3 transition mode'
# shellcheck disable=SC2016
grep -Fq 'NIX_BACKUP_PRE_SPECIALIST_TRANSITION=1 "$repo_root/scripts/backup"' "$repo_root/scripts/ops" \
  || fail 'upgrade does not use the guarded pre-specialist backup path'
grep -Fq 'scripts/check-paperclip-specialist-topology' "$repo_root/scripts/restore-smoke" \
  || fail 'restore smoke does not validate the recovered specialist topology'
restore_specialist_check_line=$(awk '
  /"\$repo_root\/scripts\/check-paperclip-specialist-topology" "\$restore_config"/ {
    print NR
    exit
  }
' "$repo_root/scripts/restore-smoke")
restore_paperclip_start_line=$(awk '
  /"\$\{compose_restore\[@\]\}" up -d --wait paperclip/ {
    print NR
    exit
  }
' "$repo_root/scripts/restore-smoke")
[[ -n "$restore_specialist_check_line" && -n "$restore_paperclip_start_line" \
  && "$restore_specialist_check_line" -lt "$restore_paperclip_start_line" ]] \
  || fail 'restore smoke can start Paperclip before the recovered specialist topology and instruction bundles pass'
# shellcheck disable=SC2016
grep -Fq 'restore_runner_cache_volume="${restore_project}_paperclip_runner_cache"' \
  "$repo_root/scripts/restore-smoke" \
  || fail 'restore smoke does not reject a colliding Paperclip runner cache volume'
grep -Fq '/probe?companyId=' \
  "$repo_root/scripts/restore-smoke" \
  || fail 'restore smoke does not authenticate through each restored SSH environment'
# shellcheck disable=SC2016
grep -Fq 'test -z "${OPENCODE_API_KEY:-}"' "$repo_root/scripts/restore-smoke" \
  || fail 'restore smoke does not reject host-environment provider credential leakage'
# shellcheck disable=SC2016
grep -Fq 'test ! -L "/state/$path"' "$repo_root/scripts/backup" \
  || fail 'backup does not reject dangling Slice 2 state symlinks before following them'
# shellcheck disable=SC2016
grep -Fq 'test ! -L "/state/$path"' "$repo_root/scripts/restore-smoke" \
  || fail 'restore does not reject dangling Slice 2 state symlinks before following them'

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
  printf 'COMPOSE_PROJECT_NAME=nix-os-backup-policy-test\n'
  printf 'PAPERCLIP_PUBLIC_URL=https://nix-os.test-tailnet.ts.net\nPAPERCLIP_RUNNER_PUBLIC_URL=wss://nix-os.test-tailnet.ts.net\nPAPERCLIP_LIOR_USER_ID=lior-test-user\nPAPERCLIP_HOST_PORT=0\n'
  printf 'POSTGRES_ENV_FILE=%s\nPAPERCLIP_ENV_FILE=%s\n' "$test_tmp_dir/postgres.env" "$test_tmp_dir/paperclip.env"
  printf 'HERMES_ENV_FILE=%s\nNIX_BRAIN_HOST_PATH=%s\n' "$test_tmp_dir/hermes.env" "$test_tmp_dir/nix-brain"
  printf 'FOUNDER_RELAY_ENV_FILE=%s\n' "$test_tmp_dir/founder-relay.env"
  printf 'SPECIALIST_PROVIDER_ENV_FILE=%s\n' "$test_tmp_dir/specialist-provider.env"
  printf 'SPECIALIST_WORKER_HOST_KEY_FILE=%s\n' "$test_tmp_dir/specialist-host-key"
  printf 'SPECIALIST_WORKER_AUTHORIZED_KEYS_FILE=%s\n' "$test_tmp_dir/specialist-authorized-keys"
  printf 'SPECIALIST_WORKER_CLIENT_KEY_FILE=%s\n' "$test_tmp_dir/specialist-client-key"
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
  printf 'NIX_BRAIN_GID=%s\n' "$brain_gid"
  printf 'HERMES_TELEGRAM_BOT_USERNAME=the_nixos_bot\n'
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

saved_sidecar="$test_tmp_dir/plaintext-artifact.sha256.saved"
mv "${plaintext_artifact}.sha256" "$saved_sidecar"
if PATH="$fake_bin:$PATH" "$repo_root/scripts/restore-smoke" "$plaintext_artifact" \
  >"$test_tmp_dir/restore-missing-sidecar.out" \
  2>"$test_tmp_dir/restore-missing-sidecar.err"; then
  fail 'restore smoke accepted an artifact without its checksum sidecar'
fi
grep -q 'sidecar is missing or unsafe' "$test_tmp_dir/restore-missing-sidecar.err" \
  || fail 'restore smoke missing-sidecar failure was not explicit'
mv "$saved_sidecar" "${plaintext_artifact}.sha256"

cp "${plaintext_artifact}.sha256" "$saved_sidecar"
printf '%064d  %s\n' 0 "$(basename "$plaintext_artifact")" \
  >"${plaintext_artifact}.sha256"
if PATH="$fake_bin:$PATH" "$repo_root/scripts/restore-smoke" "$plaintext_artifact" \
  >"$test_tmp_dir/restore-tampered-sidecar.out" \
  2>"$test_tmp_dir/restore-tampered-sidecar.err"; then
  fail 'restore smoke accepted a mismatched checksum sidecar'
fi
grep -q 'checksum mismatch' "$test_tmp_dir/restore-tampered-sidecar.err" \
  || fail 'restore smoke checksum-mismatch failure was not explicit'
mv "$saved_sidecar" "${plaintext_artifact}.sha256"
rm -rf "$test_tmp_dir/backups"

if PATH="$fake_bin:$PATH" NIX_ALLOW_TEST_CONFIG=1 FAKE_AGE_EXIT=23 \
  BACKUP_AGE_RECIPIENT=age1fixture \
  "$repo_root/scripts/backup" "$test_tmp_dir/test.env" >"$test_tmp_dir/age.out" 2>"$test_tmp_dir/age.err"; then
  fail 'backup unexpectedly succeeded when age failed'
fi
if [[ -d "$test_tmp_dir/backups" ]] && find "$test_tmp_dir/backups" -type f -print -quit | grep -q .; then
  fail 'age failure left a plaintext, partial, or published backup artifact behind'
fi

fake_docker_log="$test_tmp_dir/unsafe-topology-docker.log"
if PATH="$fake_bin:$PATH" NIX_ALLOW_TEST_CONFIG=1 \
  NIX_TEST_ONLY_ALLOW_UNENCRYPTED_BACKUP=1 FAKE_TOPOLOGY_UNSAFE=1 \
  FAKE_DOCKER_LOG="$fake_docker_log" \
  "$repo_root/scripts/backup" "$test_tmp_dir/test.env" \
  >"$test_tmp_dir/topology.out" 2>"$test_tmp_dir/topology.err"; then
  fail 'backup unexpectedly accepted unsafe Chief topology'
fi
grep -q 'Paperclip Chief topology is unsafe' "$test_tmp_dir/topology.err" \
  || fail 'unsafe Chief topology failure was not explicit'
if grep -Eq '(^| )stop( |$)' "$fake_docker_log"; then
  fail 'unsafe Chief topology stopped a service before backup refusal'
fi
if [[ -d "$test_tmp_dir/backups" ]] && find "$test_tmp_dir/backups" -type f -print -quit | grep -q .; then
  fail 'unsafe Chief topology published a backup artifact'
fi

post_stop_log="$test_tmp_dir/post-stop-drift-docker.log"
if PATH="$fake_bin:$PATH" NIX_ALLOW_TEST_CONFIG=1 \
  NIX_TEST_ONLY_ALLOW_UNENCRYPTED_BACKUP=1 FAKE_TOPOLOGY_DRIFT_AFTER_STOP=1 \
  FAKE_DOCKER_LOG="$post_stop_log" \
  "$repo_root/scripts/backup" "$test_tmp_dir/test.env" \
  >"$test_tmp_dir/post-stop.out" 2>"$test_tmp_dir/post-stop.err"; then
  fail 'backup unexpectedly accepted post-stop Chief topology drift'
fi
grep -q 'Paperclip Chief topology is unsafe' "$test_tmp_dir/post-stop.err" \
  || fail 'post-stop Chief topology failure was not explicit'
grep -Eq '(^| )stop( |$).*hermes' "$post_stop_log" \
  || fail 'post-stop drift fixture did not quiesce Hermes'
grep -Eq '(^| )stop( |$).*paperclip' "$post_stop_log" \
  || fail 'post-stop drift fixture did not quiesce Paperclip'
if grep -Eq '(^| )pg_dump( |$)' "$post_stop_log"; then
  fail 'post-stop Chief topology drift reached pg_dump'
fi

service_log="$test_tmp_dir/service-order-docker.log"
BACKUP_OUTPUT_DIR="$test_tmp_dir/service-order-backups" \
  PATH="$fake_bin:$PATH" NIX_ALLOW_TEST_CONFIG=1 \
  NIX_TEST_ONLY_ALLOW_UNENCRYPTED_BACKUP=1 FAKE_SERVICES_RUNNING=1 \
  FAKE_DOCKER_LOG="$service_log" \
  "$repo_root/scripts/backup" "$test_tmp_dir/test.env" >/dev/null
paperclip_stop_line=$(grep -n 'stop paperclip' "$service_log" | head -n 1 | cut -d: -f1)
paperclip_start_line=$(grep -n 'up -d --wait paperclip' "$service_log" | head -n 1 | cut -d: -f1)
[[ -n "$paperclip_stop_line" && -n "$paperclip_start_line" ]] \
  || fail 'backup did not quiesce and restart Paperclip'

printf 'State backup encryption policy tests passed.\n'
