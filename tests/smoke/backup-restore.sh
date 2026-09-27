#!/usr/bin/env bash
set -euo pipefail
umask 077

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
smoke_tmp_dir=$(mktemp -d /tmp/nix-os-backup-smoke.XXXXXX)
smoke_suffix=$(openssl rand -hex 8)
smoke_project="nix-os-smoke-$smoke_suffix"
restore_project="nix-os-restore-smoke-$smoke_suffix"
config_file="$smoke_tmp_dir/smoke.env"
compose=(docker compose --env-file "$config_file")
source_cookie=/tmp/nix-os-source-cookie.txt
source_response=/tmp/nix-os-source-response.json
restore_config=''
archive_helper_image='postgres:17.11-alpine3.24@sha256:b0f9560a2de083e2cc7382e75f808c7381a32852a7ec49117deedb300e552b24'

fail() { printf 'backup/restore smoke error: %s\n' "$*" >&2; exit 1; }
hash_stream() { if command -v sha256sum >/dev/null 2>&1; then sha256sum | cut -d' ' -f1; else shasum -a 256 | cut -d' ' -f1; fi; }

assert_project_absent() {
  local project=$1 resource

  [[ -z $(docker ps -aq --filter "label=com.docker.compose.project=$project") ]] \
    || fail "unexpected pre-existing containers for Compose project $project"
  [[ -z $(docker network ls -q --filter "label=com.docker.compose.project=$project") ]] \
    || fail "unexpected pre-existing networks for Compose project $project"
  for resource in postgres_data paperclip_data hermes_data; do
    if docker volume inspect "${project}_${resource}" >/dev/null 2>&1; then
      fail "unexpected pre-existing volume ${project}_${resource}"
    fi
  done
}

source_post() {
  local path=$1 body=$2 status
  status=$(printf '%s' "$body" | "${compose[@]}" exec -T paperclip curl -sS \
    -o "$source_response" -w '%{http_code}' -c "$source_cookie" -b "$source_cookie" \
    -H 'Content-Type: application/json' -H 'Origin: https://nix-os.test-tailnet.ts.net' \
    -X POST "http://127.0.0.1:3100${path}" --data-binary @-)
  [[ "$status" =~ ^2 ]] || fail "source API POST $path returned HTTP $status"
  "${compose[@]}" exec -T paperclip cat "$source_response"
}

source_get() {
  "${compose[@]}" exec -T paperclip curl -fsS -c "$source_cookie" -b "$source_cookie" \
    "http://127.0.0.1:3100$1"
}

cleanup() {
  if [[ -n "$restore_config" && -f "$restore_config" ]]; then
    docker compose --env-file "$restore_config" down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
  "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  docker volume rm "${restore_project}_paperclip_data" "${restore_project}_postgres_data" >/dev/null 2>&1 || true
  rm -rf "$smoke_tmp_dir"
}
trap cleanup EXIT

docker info >/dev/null
command -v jq >/dev/null 2>&1 || fail "jq is required"
command -v age >/dev/null 2>&1 || fail "age is required"
command -v age-keygen >/dev/null 2>&1 || fail "age-keygen is required"
assert_project_absent "$smoke_project"
assert_project_absent "$restore_project"
age-keygen -o "$smoke_tmp_dir/backup-identity.txt" >/dev/null 2>&1
backup_recipient=$(age-keygen -y "$smoke_tmp_dir/backup-identity.txt")
postgres_password=$(openssl rand -hex 32)
paperclip_db_password=$(openssl rand -hex 32)
admin_password="Aa1!$(openssl rand -hex 20)"
canary_value=$(openssl rand -hex 32)
printf 'POSTGRES_PASSWORD=%s\nPAPERCLIP_DB_PASSWORD=%s\n' "$postgres_password" "$paperclip_db_password" >"$smoke_tmp_dir/postgres.env"
{
  printf 'DATABASE_URL=postgresql://paperclip:%s@postgres:5432/paperclip\n' "$paperclip_db_password"
  printf 'BETTER_AUTH_SECRET=%s\n' "$(openssl rand -hex 32)"
  printf 'PAPERCLIP_TOOL_ACTION_SIGNING_SECRET=%s\n' "$(openssl rand -hex 32)"
} >"$smoke_tmp_dir/paperclip.env"
{
  printf 'API_SERVER_KEY=%s\n' "$(openssl rand -hex 32)"
  printf 'TELEGRAM_BOT_TOKEN=test-token\nTELEGRAM_ALLOWED_USERS=123456789\n'
  printf 'TELEGRAM_ALLOW_ALL_USERS=false\nGATEWAY_ALLOW_ALL_USERS=false\n'
} >"$smoke_tmp_dir/hermes.env"
mkdir "$smoke_tmp_dir/nix-brain"
{
  printf 'COMPOSE_PROJECT_NAME=%s\n' "$smoke_project"
  printf 'PAPERCLIP_PUBLIC_URL=https://nix-os.test-tailnet.ts.net\nPAPERCLIP_HOST_PORT=0\n'
  printf 'POSTGRES_ENV_FILE=%s\nPAPERCLIP_ENV_FILE=%s\n' "$smoke_tmp_dir/postgres.env" "$smoke_tmp_dir/paperclip.env"
  printf 'HERMES_ENV_FILE=%s\nNIX_BRAIN_HOST_PATH=%s\n' "$smoke_tmp_dir/hermes.env" "$smoke_tmp_dir/nix-brain"
  printf 'PAPERCLIP_AUTH_DISABLE_SIGN_UP=false\nBACKUP_OUTPUT_DIR=%s\n' "$smoke_tmp_dir/backups"
} >"$config_file"
chmod 0600 "$smoke_tmp_dir"/*.env

NIX_ALLOW_TEST_CONFIG=1 "$repo_root/scripts/check-config" "$config_file"
docker volume create "${smoke_project}_hermes_data" >/dev/null
docker run --rm --volume "${smoke_project}_hermes_data:/state" "$archive_helper_image" sh -ec '
  install -d /state/memories /state/sessions /state/skills/grill-me
  printf "chief-of-staff-continuity-v1\n" >/state/memories/slice-1-continuity.txt
  printf "telegram-session-fixture-v1\n" >/state/sessions/slice-1-session.json
  printf "%s\n" "---" "name: grill-me" "---" >/state/skills/grill-me/SKILL.md
  printf "%s\n" "PAPERCLIP_API_KEY=pcp_fixture_only" "PAPERCLIP_COMPANY_ID=fixture-company" "PAPERCLIP_AGENT_ID=fixture-agent" >/state/.env
  printf "%s\n" "{\"provider\":\"openai-codex\",\"fixture\":true}" >/state/auth.json
  printf "%s\n" "{\"desired_state\":\"running\",\"fixture\":true}" >/state/gateway_state.json
'
"${compose[@]}" up -d --wait postgres
NIX_ALLOW_TEST_CONFIG=1 "$repo_root/scripts/check-migrations" "$config_file"
"${compose[@]}" exec -T postgres psql -U paperclip -d paperclip -c 'CREATE TABLE migration_preflight_canary (id integer);' >/dev/null
if NIX_ALLOW_TEST_CONFIG=1 "$repo_root/scripts/check-migrations" "$config_file" >/dev/null 2>&1; then
  fail "migration preflight accepted a non-empty database without a journal"
fi
"${compose[@]}" exec -T postgres psql -U paperclip -d paperclip -c 'DROP TABLE migration_preflight_canary;' >/dev/null

NIX_ALLOW_TEST_CONFIG=1 "$repo_root/scripts/initialize-paperclip" "$config_file"
"${compose[@]}" up -d --wait paperclip
role_flags=$("${compose[@]}" exec -T postgres psql -U postgres -d postgres -At \
  -c "SELECT rolsuper || ':' || rolcreatedb || ':' || rolcreaterole FROM pg_roles WHERE rolname = 'paperclip'")
[[ "$role_flags" == 'false:false:false' ]] || fail "Paperclip database role is over-privileged: $role_flags"

anonymous_status=$("${compose[@]}" exec -T paperclip curl -sS -o "$source_response" -w '%{http_code}' \
  http://127.0.0.1:3100/api/companies)
[[ ! "$anonymous_status" =~ ^2 ]] || fail "anonymous client could access authenticated Paperclip API"

signup_body=$(jq -nc --arg password "$admin_password" '{name:"Slice Zero Admin",email:"slice-zero-admin@paperclip.test",password:$password}')
source_post '/api/auth/sign-up/email' "$signup_body" >/dev/null
source_post '/api/bootstrap/claim' '{}' >/dev/null
session_json=$(source_get '/api/auth/get-session')
jq -e '.user.id != null or .session.userId != null or .userId != null' >/dev/null <<<"$session_json" || fail "CEO session was not established"
health_json=$("${compose[@]}" exec -T paperclip curl -fsS http://127.0.0.1:3100/api/health)
grep -q '"bootstrapStatus":"ready"' <<<"$health_json" || fail "instance did not become bootstrap ready"
if NIX_ALLOW_TEST_CONFIG=1 "$repo_root/scripts/bootstrap-ceo" "$config_file" >/dev/null 2>&1; then
  fail "bootstrap command unexpectedly created another invite after CEO claim"
fi

sed 's/^PAPERCLIP_AUTH_DISABLE_SIGN_UP=false$/PAPERCLIP_AUTH_DISABLE_SIGN_UP=true/' "$config_file" >"$smoke_tmp_dir/smoke-disabled.env"
mv "$smoke_tmp_dir/smoke-disabled.env" "$config_file"
chmod 0600 "$config_file"
"${compose[@]}" up -d --force-recreate --wait paperclip
"${compose[@]}" exec -T paperclip rm -f "$source_cookie"
disabled_status=$(printf '%s' '{"name":"Blocked Signup","email":"blocked-signup@paperclip.test","password":"Aa1!blocked-signup-password"}' \
  | "${compose[@]}" exec -T paperclip curl -sS -o "$source_response" -w '%{http_code}' \
    -c "$source_cookie" -b "$source_cookie" -H 'Content-Type: application/json' -H 'Origin: https://nix-os.test-tailnet.ts.net' \
    -X POST http://127.0.0.1:3100/api/auth/sign-up/email --data-binary @-)
[[ ! "$disabled_status" =~ ^2 ]] || fail "new signup succeeded after signup was disabled"
signin_body=$(jq -nc --arg password "$admin_password" '{email:"slice-zero-admin@paperclip.test",password:$password}')
source_post '/api/auth/sign-in/email' "$signin_body" >/dev/null
source_get '/api/auth/get-session' | jq -e '.user.id != null or .session.userId != null or .userId != null' >/dev/null || fail "existing CEO could not authenticate"

company_json=$(source_post '/api/companies' '{"name":"Slice 0 Recovery Company","description":"supported API recovery fixture","budgetMonthlyCents":100}')
company_id=$(jq -er '.id' <<<"$company_json")
issue_json=$(source_post "/api/companies/${company_id}/issues" '{"title":"Slice 0 recovery issue","description":"real Paperclip state must survive restore"}')
issue_id=$(jq -er '.id' <<<"$issue_json")
[[ $(jq -r '.companyId' <<<"$issue_json") == "$company_id" ]] || fail "created issue relationship is wrong"

attachment_bytes='slice-0-known-attachment-bytes-v1'
attachment_sha=$(printf '%s' "$attachment_bytes" | hash_stream)
printf '%s' "$attachment_bytes" | "${compose[@]}" exec -T paperclip sh -c 'cat > /tmp/nix-os-attachment.txt'
attachment_json=$("${compose[@]}" exec -T paperclip curl -fsS -c "$source_cookie" -b "$source_cookie" \
  -H 'Origin: https://nix-os.test-tailnet.ts.net' -F 'file=@/tmp/nix-os-attachment.txt;type=text/plain' \
  "http://127.0.0.1:3100/api/companies/${company_id}/issues/${issue_id}/attachments")
attachment_id=$(jq -er '.id' <<<"$attachment_json")
[[ $(jq -r '.sha256' <<<"$attachment_json") == "$attachment_sha" ]] || fail "Paperclip attachment checksum did not match source bytes"

secret_body=$(jq -nc --arg value "$canary_value" '{name:"Slice 0 recovery canary",key:"NIX_SLICE_0_CANARY",provider:"local_encrypted",value:$value,description:"Harmless restore canary"}')
secret_json=$(source_post "/api/companies/${company_id}/secrets" "$secret_body")
secret_id=$(jq -er '.id' <<<"$secret_json")
unset canary_value secret_body

environment_body=$(jq -nc --arg secret_id "$secret_id" '{name:"Slice 0 secret recovery probe",driver:"ssh",config:{host:"127.0.0.1",port:1,username:"nix-recovery",remoteWorkspacePath:"/tmp",privateKeySecretRef:{type:"secret_ref",secretId:$secret_id,version:"latest"}},envVars:{}}')
environment_json=$(source_post "/api/companies/${company_id}/environments" "$environment_body")
environment_id=$(jq -er '.id' <<<"$environment_json")
source_probe=$(source_post "/api/environments/${environment_id}/probe" '{}')
jq -e '.driver == "ssh" and .ok == false' >/dev/null <<<"$source_probe" || fail "source environment probe did not execute"
source_access_events=$(source_get "/api/secrets/${secret_id}/access-events")
jq -e --arg environment_id "$environment_id" '.[] | select(.outcome == "success" and .consumerType == "environment" and .consumerId == $environment_id)' \
  >/dev/null <<<"$source_access_events" || fail "source canary was not resolved successfully"

"${compose[@]}" stop postgres
health_status=$("${compose[@]}" exec -T paperclip sh -ec "curl --silent --output /tmp/database-down-health.json --write-out '%{http_code}' http://127.0.0.1:3100/api/health")
[[ "$health_status" == 503 ]] || fail "expected health HTTP 503 with PostgreSQL stopped, got $health_status"
"${compose[@]}" exec -T paperclip grep -q 'database_unreachable' /tmp/database-down-health.json
"${compose[@]}" up -d --wait postgres paperclip

artifact=$(NIX_ALLOW_TEST_CONFIG=1 BACKUP_OUTPUT_DIR="$smoke_tmp_dir/backups" BACKUP_AGE_RECIPIENT="$backup_recipient" \
  "$repo_root/scripts/backup" "$config_file" | tail -n 1)
[[ -f "$artifact" ]] || fail "backup artifact missing: $artifact"
download_dir="$smoke_tmp_dir/downloaded"
mkdir "$download_dir"
cp "$artifact" "${artifact}.sha256" "$download_dir/"
artifact="$download_dir/$(basename "$artifact")"

restore_work_dir="$smoke_tmp_dir/restore"
restore_config="$restore_work_dir/restore.env"
RESTORE_PROJECT_NAME="$restore_project" RESTORE_KEEP=true RESTORE_WORK_DIR="$restore_work_dir" \
  AGE_IDENTITY_FILE="$smoke_tmp_dir/backup-identity.txt" \
  RESTORE_POSTGRES_ENV_FILE="$smoke_tmp_dir/postgres.env" RESTORE_PAPERCLIP_ENV_FILE="$smoke_tmp_dir/paperclip.env" \
  RESTORE_HERMES_ENV_FILE="$smoke_tmp_dir/hermes.env" \
  "$repo_root/scripts/restore-smoke" "$artifact"

[[ -f "$restore_config" ]] || fail "could not locate retained restore configuration"
restore_compose=(docker compose --env-file "$restore_config")
restore_cookie=/tmp/nix-os-restore-cookie.txt
restore_response=/tmp/nix-os-restore-response.json
restore_post() {
  local path=$1 body=$2 status
  status=$(printf '%s' "$body" | "${restore_compose[@]}" exec -T paperclip curl -sS \
    -o "$restore_response" -w '%{http_code}' -c "$restore_cookie" -b "$restore_cookie" \
    -H 'Content-Type: application/json' -H 'Origin: https://nix-os.restore-test.ts.net' \
    -X POST "http://127.0.0.1:3100${path}" --data-binary @-)
  [[ "$status" =~ ^2 ]] || fail "restored API POST $path returned HTTP $status"
  "${restore_compose[@]}" exec -T paperclip cat "$restore_response"
}
restore_get() {
  "${restore_compose[@]}" exec -T paperclip curl -fsS -c "$restore_cookie" -b "$restore_cookie" \
    "http://127.0.0.1:3100$1"
}

restore_post '/api/auth/sign-in/email' "$signin_body" >/dev/null
restore_get '/api/auth/get-session' | jq -e '.user.id != null or .session.userId != null or .userId != null' >/dev/null || fail "restored CEO could not authenticate"
restored_company=$(restore_get "/api/companies/${company_id}")
[[ $(jq -r '.name' <<<"$restored_company") == 'Slice 0 Recovery Company' ]] || fail "company did not survive restore"
restored_issue=$(restore_get "/api/issues/${issue_id}")
[[ $(jq -r '.title' <<<"$restored_issue") == 'Slice 0 recovery issue' ]] || fail "issue did not survive restore"
[[ $(jq -r '.companyId' <<<"$restored_issue") == "$company_id" ]] || fail "issue/company relationship did not survive restore"
restored_attachments=$(restore_get "/api/issues/${issue_id}/attachments")
jq -e --arg id "$attachment_id" --arg sha "$attachment_sha" '.[] | select(.id == $id and .sha256 == $sha)' >/dev/null <<<"$restored_attachments" || fail "attachment metadata did not survive restore"
restored_attachment_sha=$("${restore_compose[@]}" exec -T paperclip curl -fsS -b "$restore_cookie" "http://127.0.0.1:3100/api/attachments/${attachment_id}/content" | hash_stream)
[[ "$restored_attachment_sha" == "$attachment_sha" ]] || fail "restored attachment bytes failed checksum verification"
restored_secrets=$(restore_get "/api/companies/${company_id}/secrets")
jq -e --arg id "$secret_id" '.[] | select(.id == $id and .provider == "local_encrypted" and .latestVersion == 1)' >/dev/null <<<"$restored_secrets" || fail "encrypted canary secret metadata did not survive restore"
restored_events_before=$(restore_get "/api/secrets/${secret_id}/access-events" | jq 'length')
restored_probe=$(restore_post "/api/environments/${environment_id}/probe" '{}')
jq -e '.driver == "ssh" and .ok == false' >/dev/null <<<"$restored_probe" || fail "restored environment probe did not execute"
restored_access_events=$(restore_get "/api/secrets/${secret_id}/access-events")
restored_events_after=$(jq 'length' <<<"$restored_access_events")
(( restored_events_after == restored_events_before + 1 )) || fail "restored canary resolution did not create one access event"
jq -e --arg environment_id "$environment_id" '.[0] | select(.outcome == "success" and .consumerType == "environment" and .consumerId == $environment_id)' \
  >/dev/null <<<"$restored_access_events" || fail "restored canary could not be decrypted with the recovered master key"
restored_health=$("${restore_compose[@]}" exec -T paperclip curl -fsS http://127.0.0.1:3100/api/health)
grep -q '"status":"ok"' <<<"$restored_health" || fail "restored Paperclip health did not report ok"
docker run --rm --volume "${restore_project}_hermes_data:/state:ro" "$archive_helper_image" sh -ec '
  grep -qx chief-of-staff-continuity-v1 /state/memories/slice-1-continuity.txt
  grep -qx telegram-session-fixture-v1 /state/sessions/slice-1-session.json
  grep -q "name: grill-me" /state/skills/grill-me/SKILL.md
  grep -q "PAPERCLIP_AGENT_ID=fixture-agent" /state/.env
  grep -q "openai-codex" /state/auth.json
  grep -q "desired_state" /state/gateway_state.json
' || fail "restored Hermes identity/session/skill fixtures are incomplete"

"${restore_compose[@]}" down --volumes --remove-orphans
printf 'Fresh bootstrap and realistic Paperclip backup/restore smoke passed.\n'
