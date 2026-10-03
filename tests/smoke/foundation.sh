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
  printf 'TELEGRAM_BOT_TOKEN=test-token\nTELEGRAM_ALLOWED_USERS=123456789\n'
  printf 'TELEGRAM_ALLOW_ALL_USERS=false\nGATEWAY_ALLOW_ALL_USERS=false\n'
} >"$test_tmp_dir/hermes.env"
mkdir "$test_tmp_dir/nix-brain"
{
  printf 'COMPOSE_PROJECT_NAME=nix-os-test\n'
  printf 'PAPERCLIP_PUBLIC_URL=https://nix-os.test-tailnet.ts.net\n'
  printf 'PAPERCLIP_HOST_PORT=0\n'
  printf 'POSTGRES_ENV_FILE=%s\n' "$test_tmp_dir/postgres.env"
  printf 'PAPERCLIP_ENV_FILE=%s\n' "$test_tmp_dir/paperclip.env"
  printf 'HERMES_ENV_FILE=%s\n' "$test_tmp_dir/hermes.env"
  printf 'NIX_BRAIN_HOST_PATH=%s\n' "$test_tmp_dir/nix-brain"
  printf 'PAPERCLIP_AUTH_DISABLE_SIGN_UP=true\n'
  printf 'BACKUP_OUTPUT_DIR=%s\n' "$test_tmp_dir/backups"
} >"$test_tmp_dir/test.env"
chmod 0600 "$test_tmp_dir"/*.env

NIX_ALLOW_TEST_CONFIG=1 "$repo_root/scripts/check-config" "$test_tmp_dir/test.env"
docker compose --env-file "$test_tmp_dir/test.env" config --format json >"$test_tmp_dir/compose.json"
python3 "$repo_root/tests/smoke/validate_compose.py" "$test_tmp_dir/compose.json" "$repo_root"

grep -v '^PAPERCLIP_PUBLIC_URL=' "$test_tmp_dir/test.env" >"$test_tmp_dir/missing.env"
if NIX_ALLOW_TEST_CONFIG=1 "$repo_root/scripts/check-config" "$test_tmp_dir/missing.env" >/dev/null 2>&1; then
  printf 'missing required configuration unexpectedly passed\n' >&2
  exit 1
fi

cp "$test_tmp_dir/hermes.env" "$test_tmp_dir/hermes-safe.env"
sed 's/^TELEGRAM_ALLOW_ALL_USERS=false$/TELEGRAM_ALLOW_ALL_USERS=true/' \
  "$test_tmp_dir/hermes-safe.env" >"$test_tmp_dir/hermes.env"
if NIX_ALLOW_TEST_CONFIG=1 "$repo_root/scripts/check-config" "$test_tmp_dir/test.env" >/dev/null 2>&1; then
  printf 'unsafe Telegram allow-all configuration unexpectedly passed\n' >&2
  exit 1
fi
mv "$test_tmp_dir/hermes-safe.env" "$test_tmp_dir/hermes.env"

age_private_pattern='AGE-SECRET-KEY-(PQ-)?1[[:alnum:]]{20,}|AGE-PLUGIN-[A-Z0-9-]+-1[[:alnum:]]{20,}'
public_secret_pattern='[0-9]{8,}:[A-Za-z0-9_-]{30,}|pcp_(api|claim|invite|bootstrap)?[_-]?[A-Za-z0-9_-]{30,}|ya29\.[A-Za-z0-9._-]{20,}|"refresh_token"[[:space:]]*:[[:space:]]*"[A-Za-z0-9._/-]{20,}"|^API_SERVER_KEY=[A-Za-z0-9_-]{32,}'

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

printf 'Foundation configuration tests passed.\n'
