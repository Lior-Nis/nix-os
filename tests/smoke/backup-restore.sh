#!/usr/bin/env bash
set -euo pipefail
umask 077

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
smoke_tmp_dir=$(mktemp -d /tmp/nix-os-backup-smoke.XXXXXX)
smoke_suffix=$(openssl rand -hex 8)
smoke_project="nix-os-smoke-$smoke_suffix"
restore_project="nix-os-restore-smoke-$smoke_suffix"
config_file="$smoke_tmp_dir/smoke.env"
runtime_mode_file="$smoke_tmp_dir/hermes-runtime-mode.env"
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

source_patch() {
  local path=$1 body=$2 status
  status=$(printf '%s' "$body" | "${compose[@]}" exec -T paperclip curl -sS \
    -o "$source_response" -w '%{http_code}' -c "$source_cookie" -b "$source_cookie" \
    -H 'Content-Type: application/json' -H 'Origin: https://nix-os.test-tailnet.ts.net' \
    -X PATCH "http://127.0.0.1:3100${path}" --data-binary @-)
  [[ "$status" =~ ^2 ]] || fail "source API PATCH $path returned HTTP $status"
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
  decision_webhook_secret=$(openssl rand -hex 32)
  printf 'HERMES_DECISION_WEBHOOK_SECRET=%s\n' "$decision_webhook_secret"
  printf 'WEBHOOK_SECRET=%s\n' "$decision_webhook_secret"
  printf 'OPENCODE_GO_API_KEY=test-opencode-go-key-12345678\n'
  printf 'TELEGRAM_BOT_TOKEN=test-token\nTELEGRAM_ALLOWED_USERS=123456789\nTELEGRAM_HOME_CHANNEL=123456789\n'
  printf 'TELEGRAM_ALLOW_ALL_USERS=false\nGATEWAY_ALLOW_ALL_USERS=false\n'
} >"$smoke_tmp_dir/hermes.env"
printf 'HERMES_TELEGRAM_MODE=disabled\n' >"$smoke_tmp_dir/hermes-telegram-mode.env"
mkdir "$smoke_tmp_dir/nix-brain"
printf '# Recovery brain fixture\n' >"$smoke_tmp_dir/nix-brain/README.md"
git -C "$smoke_tmp_dir/nix-brain" init -q
git -C "$smoke_tmp_dir/nix-brain" add README.md
brain_gid=$("$repo_root/tests/fixtures/select-brain-gid")
chgrp -R "$brain_gid" "$smoke_tmp_dir/nix-brain"
chmod -R g+rX,o-rwx "$smoke_tmp_dir/nix-brain"
brain_gid=$(stat -c '%g' "$smoke_tmp_dir/nix-brain" 2>/dev/null || stat -f '%g' "$smoke_tmp_dir/nix-brain")
{
  printf 'COMPOSE_PROJECT_NAME=%s\n' "$smoke_project"
  printf 'PAPERCLIP_PUBLIC_URL=https://nix-os.test-tailnet.ts.net\nPAPERCLIP_LIOR_USER_ID=lior-test-user\nPAPERCLIP_HOST_PORT=0\n'
  printf 'POSTGRES_ENV_FILE=%s\nPAPERCLIP_ENV_FILE=%s\n' "$smoke_tmp_dir/postgres.env" "$smoke_tmp_dir/paperclip.env"
  printf 'HERMES_ENV_FILE=%s\nNIX_BRAIN_HOST_PATH=%s\n' "$smoke_tmp_dir/hermes.env" "$smoke_tmp_dir/nix-brain"
  printf 'NIX_BRAIN_GID=%s\n' "$brain_gid"
  printf 'HERMES_TELEGRAM_BOT_USERNAME=the_nixos_bot\n'
  printf 'HERMES_TELEGRAM_MODE_FILE=%s\n' "$smoke_tmp_dir/hermes-telegram-mode.env"
  printf 'PAPERCLIP_AUTH_DISABLE_SIGN_UP=false\nBACKUP_OUTPUT_DIR=%s\n' "$smoke_tmp_dir/backups"
} >"$config_file"
chmod 0600 "$smoke_tmp_dir"/*.env

NIX_ALLOW_TEST_CONFIG=1 "$repo_root/scripts/check-config" "$config_file"
# Docker Desktop presents bind-mounted files as root-owned, while native Linux
# preserves the host runner UID. Keep the config fixture readable for later
# non-root host validation, but give every source Hermes lifecycle command a
# separate root-owned runtime marker matching production.
cp "$smoke_tmp_dir/hermes-telegram-mode.env" "$runtime_mode_file"
docker run --rm --volume "$runtime_mode_file:/mode.env" "$archive_helper_image" sh -ec '
  chown 0:0 /mode.env
  chmod 0600 /mode.env
'
docker volume create "${smoke_project}_hermes_data" >/dev/null
docker run --rm --volume "${smoke_project}_hermes_data:/state" "$archive_helper_image" sh -ec '
  install -d /state/memories /state/sessions /state/logs/gateways/default
  printf "chief-of-staff-continuity-v1\n" >/state/memories/slice-1-continuity.txt
  printf "telegram-session-fixture-v1\n" >/state/sessions/slice-1-session.json
  printf "%s\n" "{\"desired_state\":\"running\",\"fixture\":true}" >/state/gateway_state.json
  chown -R 10000:10000 /state
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
board_user_id=$(jq -er '.user.id // .session.userId // .userId' <<<"$session_json") \
  || fail "CEO session was not established"
sed "s/^PAPERCLIP_LIOR_USER_ID=.*/PAPERCLIP_LIOR_USER_ID=$board_user_id/" "$config_file" \
  >"$smoke_tmp_dir/smoke-board-user.env"
mv "$smoke_tmp_dir/smoke-board-user.env" "$config_file"
chmod 0600 "$config_file"
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
project_json=$(source_post "/api/companies/${company_id}/projects" \
  '{"name":"Nix MCP Boundary Fixture","description":"Existing approved project for bounded Chief operations."}')
project_id=$(jq -er '.id' <<<"$project_json")
temp_json=$(source_post "/api/companies/${company_id}/agents" \
  '{"name":"Nix Bootstrap CEO","role":"ceo","capabilities":"Temporary inert manager for the disposable Hermes recovery join.","adapterType":"process","adapterConfig":{"command":"/bin/false","args":[]},"runtimeConfig":{"heartbeat":{"enabled":false}},"budgetMonthlyCents":0,"permissions":{"canCreateAgents":false,"canCreateSkills":false,"canAssignTasks":false},"metadata":{"nixBootstrap":{"kind":"temporary-chief-manager","version":1}}}')
temp_agent_id=$(jq -er '.id' <<<"$temp_json")
source_patch "/api/agents/${temp_agent_id}/permissions" \
  '{"canCreateAgents":false,"canCreateSkills":false,"canAssignTasks":false}' >/dev/null

# Exercise the supported invite -> approval -> one-time claim flow and persist
# the resulting key inside the same Hermes volume that the backup will capture.
invite_json=$(source_post "/api/companies/${company_id}/invites" '{"allowedJoinTypes":"agent"}')
invite_token=$(jq -er '.token' <<<"$invite_json")
hermes_api_key=$(grep -E '^API_SERVER_KEY=' "$smoke_tmp_dir/hermes.env" | cut -d= -f2-)
accept_body=$(jq -nc --arg api_key "$hermes_api_key" '{
  requestType:"agent",
  agentName:"Chief of Staff",
  adapterType:"hermes_gateway",
  capabilities:"Bounded Paperclip recovery fixture",
  agentDefaultsPayload:{
    apiBaseUrl:"http://hermes:8642",
    apiKey:$api_key,
    paperclipApiUrl:"http://paperclip:3100",
    sessionKeyStrategy:"issue",
    dangerouslyAllowInsecureRemoteHttp:true
  }
}')
join_json=$(source_post "/api/invites/${invite_token}/accept" "$accept_body")
join_id=$(jq -er '.id' <<<"$join_json")
source_post "/api/companies/${company_id}/join-requests/${join_id}/approve" '{}' >/dev/null
join_state="$smoke_tmp_dir/hermes-join.json"
printf '%s\n' "$join_json" >"$join_state"
chmod 0600 "$join_state"
claim_result=$("${compose[@]}" run --rm --no-deps -T --user 10000:10000 --entrypoint python3 hermes \
  /opt/nix/claim-agent.py claim <"$join_state")
hermes_agent_id=$(jq -er '.agentId' <<<"$claim_result")
[[ $(jq -er '.companyId' <<<"$claim_result") == "$company_id" ]] || fail "claimed Hermes company identity is wrong"
rm -f "$join_state"

# Keep the disposable run alive without invoking a model. This is test-only;
# the agent is restored to hermes_gateway before its state is backed up.
source_patch "/api/agents/${hermes_agent_id}" \
  '{"adapterType":"process","adapterConfig":{"command":"sleep","args":["120"]},"replaceAdapterConfig":true}' \
  >/dev/null

mcp_result=$("${compose[@]}" run --rm --no-deps -T --user 10000:10000 --entrypoint python3 hermes \
  /opt/nix/verify-paperclip-mcp.py --exercise-project "$project_id")
issue_id=$(jq -er '.issueId' <<<"$mcp_result")
issue_json=$(source_get "/api/issues/${issue_id}")
[[ $(jq -r '.companyId' <<<"$issue_json") == "$company_id" ]] || fail "bounded MCP issue/company relationship is wrong"
[[ $(jq -r '.projectId' <<<"$issue_json") == "$project_id" ]] || fail "bounded MCP issue/project relationship is wrong"

# Existing-issue updates and agent comments require an attributable Paperclip
# heartbeat run. Create that run through the supported wakeup endpoint, then
# exercise both tools with the runtime context Paperclip injects into an agent
# execution.
wake_body=$(jq -nc --arg issue_id "$issue_id" '{
  source:"on_demand",
  reason:"slice_1_bounded_mcp_smoke",
  payload:{issueId:$issue_id}
}')
wake_status=$(printf '%s' "$wake_body" | "${compose[@]}" exec -T paperclip curl -sS \
  -o "$source_response" -w '%{http_code}' -c "$source_cookie" -b "$source_cookie" \
  -H 'Content-Type: application/json' -H 'Origin: https://nix-os.test-tailnet.ts.net' \
  -X POST "http://127.0.0.1:3100/api/agents/${hermes_agent_id}/wakeup" --data-binary @-)
wake_json=$("${compose[@]}" exec -T paperclip cat "$source_response")
if [[ ! "$wake_status" =~ ^2 ]]; then
  fail "source agent wakeup returned HTTP $wake_status: $(jq -r '.error // "unreported error"' <<<"$wake_json")"
fi
mcp_run_id=$(jq -er '.id // .runId // .executionRunId // empty' <<<"$wake_json") \
  || fail "source agent wakeup did not create a run: $(jq -c '{status,reason,message}' <<<"$wake_json")"
mcp_run_result=$("${compose[@]}" run --rm --no-deps -T --user 10000:10000 --entrypoint python3 \
  -e PAPERCLIP_RUN_ID="$mcp_run_id" hermes \
  /opt/nix/verify-paperclip-mcp.py --exercise-run "$issue_id" --exercise-project-id "$project_id")
mcp_comment_id=$(jq -er '.commentId' <<<"$mcp_run_result")
mcp_child_id=$(jq -er '.childId' <<<"$mcp_run_result")
question_interaction_id=$(jq -er '.interactionId' <<<"$mcp_run_result")
issue_json=$(source_get "/api/issues/${issue_id}")
[[ $(jq -r '.description' <<<"$issue_json") == 'Updated through the approved Chief tool boundary.' ]] \
  || fail "bounded MCP issue update did not persist"
child_json=$(source_get "/api/issues/${mcp_child_id}")
[[ $(jq -r '.parentId' <<<"$child_json") == "$issue_id" ]] \
  || fail "bounded MCP child issue did not retain its parent"
source_get "/api/issues/${issue_id}/interactions" \
  | jq -e --arg id "$question_interaction_id" --arg user "$board_user_id" --arg run "$mcp_run_id" \
    '.[] | select(.id == $id and .kind == "ask_user_questions" and .status == "pending" and .requestedResolverPolicy == "human_only" and .effectiveResolverPolicy == "human_only" and .addresseeUserId == $user and .sourceRunId == $run)' \
    >/dev/null || fail "bounded MCP question policy or run attribution did not persist"

# A second real run for the same Chief may not steal the parent issue's
# checkout while the first run owns it.
conflict_wake_body=$(jq -nc --arg issue_id "$mcp_child_id" '{
  source:"on_demand",
  reason:"slice_2_checkout_conflict_smoke",
  payload:{issueId:$issue_id}
}')
conflict_wake_status=$(printf '%s' "$conflict_wake_body" | "${compose[@]}" exec -T paperclip curl -sS \
  -o "$source_response" -w '%{http_code}' -c "$source_cookie" -b "$source_cookie" \
  -H 'Content-Type: application/json' -H 'Origin: https://nix-os.test-tailnet.ts.net' \
  -X POST "http://127.0.0.1:3100/api/agents/${hermes_agent_id}/wakeup" --data-binary @-)
conflict_wake_json=$("${compose[@]}" exec -T paperclip cat "$source_response")
[[ "$conflict_wake_status" =~ ^2 ]] \
  || fail "competing checkout wakeup returned HTTP $conflict_wake_status"
conflict_run_id=$(jq -er '.id // .runId // .executionRunId // empty' <<<"$conflict_wake_json") \
  || fail "competing checkout wakeup did not create a run"
[[ "$conflict_run_id" != "$mcp_run_id" ]] \
  || fail "competing checkout fixture reused the owning run"
conflict_result=$("${compose[@]}" run --rm --no-deps -T --user 10000:10000 --entrypoint python3 \
  -e PAPERCLIP_RUN_ID="$conflict_run_id" hermes \
  /opt/nix/verify-paperclip-mcp.py --expect-checkout-conflict "$issue_id")
jq -e '.conflict == true' >/dev/null <<<"$conflict_result" \
  || fail "competing Paperclip checkout was not rejected"
source_post "/api/heartbeat-runs/${conflict_run_id}/cancel" '{}' >/dev/null
waiting_result=$("${compose[@]}" run --rm --no-deps -T --user 10000:10000 --entrypoint python3 \
  -e PAPERCLIP_RUN_ID="$mcp_run_id" hermes \
  /opt/nix/verify-paperclip-mcp.py --mark-in-review "$issue_id")
jq -e '.inReview == true' >/dev/null <<<"$waiting_result" \
  || fail "bounded MCP question did not enter its waiting state"
issue_json=$(source_get "/api/issues/${issue_id}")
[[ $(jq -r '.status' <<<"$issue_json") == 'in_review' ]] \
  || fail "bounded MCP question did not leave its issue waiting in review"
source_post "/api/heartbeat-runs/${mcp_run_id}/cancel" '{}' >/dev/null
hermes_adapter_patch=$(jq -nc --arg api_key "$hermes_api_key" '{
  adapterType:"hermes_gateway",
  adapterConfig:{
    apiBaseUrl:"http://hermes:8642",
    apiKey:$api_key,
    paperclipApiUrl:"http://paperclip:3100",
    sessionKeyStrategy:"issue",
    dangerouslyAllowInsecureRemoteHttp:true
  },
  replaceAdapterConfig:true
}')
source_patch "/api/agents/${hermes_agent_id}" "$hermes_adapter_patch" >/dev/null
unset hermes_adapter_patch
source_patch "/api/agents/${hermes_agent_id}/permissions" \
  '{"canCreateAgents":false,"canCreateSkills":false,"canAssignTasks":true}' >/dev/null
source_patch "/api/agents/${hermes_agent_id}" '{"role":"ceo","reportsTo":null}' >/dev/null
source_patch "/api/agents/${temp_agent_id}" \
  "$(jq -nc --arg chief_id "$hermes_agent_id" '{role:"general",reportsTo:$chief_id}')" >/dev/null
source_post "/api/agents/${temp_agent_id}/pause" '{}' >/dev/null

# Create the two real Slice 2 SQLite artifacts in the source volume before the
# coordinated backup. The question fixture records an outcome-unknown delivery
# without opening a socket; recovery must preserve that terminal safety state
# and must never turn its replay into another send attempt.
"${compose[@]}" run --rm --no-deps -T --user 10000:10000 \
  -e "NIX_FIXTURE_ISSUE_ID=$issue_id" \
  -e "NIX_FIXTURE_INTERACTION_ID=$question_interaction_id" \
  --entrypoint python3 hermes - <<'PY'
import json
import os
import sqlite3
import sys

sys.path.insert(0, "/opt/nix")
import paperclip_question_delivery as delivery

issue_id = os.environ["NIX_FIXTURE_ISSUE_ID"]
interaction_id = os.environ["NIX_FIXTURE_INTERACTION_ID"]
payload = {
    "version": 1,
    "title": "Recovery decision fixture",
    "questions": [{
        "id": "direction",
        "prompt": "Choose the recovery fixture direction",
        "selectionMode": "single",
        "required": True,
        "options": [{"id": "continue", "label": "Continue"}],
    }],
}
request = {
    "jsonrpc": "2.0", "id": 1, "method": "tools/call",
    "params": {"name": "paperclipAskUserQuestions", "arguments": {
        "issueId": issue_id, "idempotencyKey": "recovery-question-v1",
        "payload": payload,
    }},
}
interaction = {
    "id": interaction_id, "issueId": issue_id,
    "kind": "ask_user_questions", "status": "pending",
    "requestedResolverPolicy": "human_only",
    "effectiveResolverPolicy": "human_only",
    "addresseeUserId": os.environ["PAPERCLIP_LIOR_USER_ID"],
    "payload": payload,
}
response = {"jsonrpc": "2.0", "id": 1, "result": {
    "content": [{"type": "text", "text": json.dumps(interaction)}],
}}
delivery._post = lambda *_args, **_kwargs: ("unknown", 502)
assert delivery.notify_question_created(response, request) == "unknown"
with sqlite3.connect(delivery.OUTBOX_PATH) as database:
    assert database.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    columns = {row[1] for row in database.execute("PRAGMA table_info(deliveries)")}
    assert {"interaction_id", "payload_digest", "state", "attempt_count", "http_status"} <= columns
    assert database.execute(
        "SELECT state, attempt_count, http_status FROM deliveries WHERE interaction_id = ?",
        (interaction_id,),
    ).fetchone() == ("unknown", 3, 502)
PY

HERMES_TELEGRAM_MODE_FILE="$runtime_mode_file" "${compose[@]}" up -d --wait hermes
runs_idempotency_key=$(python3 -c 'import uuid; print(uuid.uuid4())')
runs_session="paperclip:company:${company_id}:agent:${hermes_agent_id}:issue:${issue_id}"
runs_body=$(jq -nc --arg session "$runs_session" \
  '{input:"Return the recovery fixture marker.",session_id:$session}')
# shellcheck disable=SC2016
runs_first=$(printf '%s' "$runs_body" | "${compose[@]}" exec -T --user 10000:10000 \
  -e "NIX_FIXTURE_RUN_KEY=$runs_idempotency_key" \
  -e "NIX_FIXTURE_RUN_SESSION=$runs_session" hermes sh -ec '
    curl -fsS -H "Authorization: Bearer $API_SERVER_KEY" \
      -H "Idempotency-Key: $NIX_FIXTURE_RUN_KEY" \
      -H "X-Hermes-Session-Key: $NIX_FIXTURE_RUN_SESSION" \
      -H "Content-Type: application/json" --data-binary @- \
      http://127.0.0.1:8642/v1/runs
  ')
runs_hermes_id=$(jq -er '.run_id | select(test("^run_[0-9a-f]{32}$"))' <<<"$runs_first") \
  || fail "source Hermes Runs API did not return a valid run identity"
[[ $(jq -r '.replayed' <<<"$runs_first") == false ]] \
  || fail "source Hermes Runs API unexpectedly replayed the first request"
"${compose[@]}" exec -T --user 10000:10000 \
  -e "NIX_FIXTURE_RUN_KEY=$runs_idempotency_key" \
  -e "NIX_FIXTURE_HERMES_RUN_ID=$runs_hermes_id" hermes python3 - <<'PY'
import os
import sqlite3

path = "/opt/data/runs_idempotency.db"
with sqlite3.connect(path) as database:
    assert database.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    columns = {row[1] for row in database.execute("PRAGMA table_info(run_idempotency)")}
    assert {"scope", "idempotency_key", "fingerprint", "run_id", "status_json"} <= columns
    assert database.execute(
        "SELECT run_id FROM run_idempotency WHERE idempotency_key = ?",
        (os.environ["NIX_FIXTURE_RUN_KEY"],),
    ).fetchone() == (os.environ["NIX_FIXTURE_HERMES_RUN_ID"],)
PY

docker run --rm --volume "${smoke_project}_hermes_data:/state:ro" "$archive_helper_image" sh -ec '
  for path in .env .paperclip-claim-receipt.json; do
    test "$(stat -c %u:%g "/state/$path")" = 10000:10000
    test "$(stat -c %a "/state/$path")" = 600
  done
  for path in runs_idempotency.db state/paperclip-question-delivery.db; do
    test -f "/state/$path"
    test ! -L "/state/$path"
    test "$(stat -c %h "/state/$path")" = 1
    test "$(stat -c %u:%g "/state/$path")" = 10000:10000
    test "$(stat -c %a "/state/$path")" = 600
  done
' || fail "source Hermes credentials/auth/claim receipt metadata is unsafe"

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

# Cancelling the disposable process-adapter heartbeat may move an issue out of
# its transient in_review state. Record the authoritative status immediately
# before backup so recovery proves exact state preservation at the backup
# boundary.
source_issue_status_at_backup=$(source_get "/api/issues/${issue_id}" | jq -er '.status')

artifact=$(NIX_ALLOW_TEST_CONFIG=1 HERMES_TELEGRAM_MODE_FILE="$runtime_mode_file" \
  BACKUP_OUTPUT_DIR="$smoke_tmp_dir/backups" BACKUP_AGE_RECIPIENT="$backup_recipient" \
  "$repo_root/scripts/backup" "$config_file" | tail -n 1)
[[ -f "$artifact" ]] || fail "backup artifact missing: $artifact"
download_dir="$smoke_tmp_dir/downloaded"
mkdir "$download_dir"
cp "$artifact" "${artifact}.sha256" "$download_dir/"
artifact="$download_dir/$(basename "$artifact")"

restore_work_dir="$smoke_tmp_dir/restore"
restore_config="$restore_work_dir/restore.env"
RESTORE_PROJECT_NAME="$restore_project" RESTORE_KEEP=true RESTORE_WORK_DIR="$restore_work_dir" \
  NIX_RESTORE_INJECT_PROFILE_TELEGRAM_CANARY=1 \
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
[[ $(jq -r '.title' <<<"$restored_issue") == 'Slice 1 bounded MCP recovery issue' ]] || fail "issue did not survive restore"
[[ $(jq -r '.companyId' <<<"$restored_issue") == "$company_id" ]] || fail "issue/company relationship did not survive restore"
[[ $(jq -r '.projectId' <<<"$restored_issue") == "$project_id" ]] || fail "issue/project relationship did not survive restore"
[[ $(jq -r '.status' <<<"$restored_issue") == "$source_issue_status_at_backup" ]] \
  || fail "issue lifecycle state did not survive restore"
restored_child=$(restore_get "/api/issues/${mcp_child_id}")
[[ $(jq -r '.parentId' <<<"$restored_child") == "$issue_id" ]] \
  || fail "bounded MCP child/parent relationship did not survive restore"
[[ $(jq -r '.projectId' <<<"$restored_child") == "$project_id" ]] \
  || fail "bounded MCP child/project relationship did not survive restore"
restore_get "/api/issues/${issue_id}/interactions" \
  | jq -e --arg id "$question_interaction_id" --arg user "$board_user_id" --arg run "$mcp_run_id" \
    '.[] | select(.id == $id and .kind == "ask_user_questions" and .status == "pending" and .requestedResolverPolicy == "human_only" and .effectiveResolverPolicy == "human_only" and .addresseeUserId == $user and .sourceRunId == $run)' \
    >/dev/null || fail "bounded MCP question policy or run attribution did not survive restore"
restore_get "/api/issues/${issue_id}/comments" \
  | jq -e --arg id "$mcp_comment_id" '.[] | select(.id == $id and .body == "Slice 1 bounded MCP comment fixture.")' >/dev/null \
  || fail "bounded MCP comment did not survive restore"
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
# shellcheck disable=SC2016
restored_runs_replay=$(printf '%s' "$runs_body" | "${restore_compose[@]}" exec -T --user 10000:10000 \
  -e "NIX_FIXTURE_RUN_KEY=$runs_idempotency_key" \
  -e "NIX_FIXTURE_RUN_SESSION=$runs_session" hermes sh -ec '
    curl -fsS -H "Authorization: Bearer $API_SERVER_KEY" \
      -H "Idempotency-Key: $NIX_FIXTURE_RUN_KEY" \
      -H "X-Hermes-Session-Key: $NIX_FIXTURE_RUN_SESSION" \
      -H "Content-Type: application/json" --data-binary @- \
      http://127.0.0.1:8642/v1/runs
  ')
jq -e --arg run_id "$runs_hermes_id" \
  '.run_id == $run_id and .replayed == true' >/dev/null <<<"$restored_runs_replay" \
  || fail "restored Runs idempotency record did not replay the original Hermes run"
"${restore_compose[@]}" exec -T --user 10000:10000 \
  -e "NIX_FIXTURE_RUN_KEY=$runs_idempotency_key" \
  -e "NIX_FIXTURE_HERMES_RUN_ID=$runs_hermes_id" \
  -e "NIX_FIXTURE_ISSUE_ID=$issue_id" \
  -e "NIX_FIXTURE_INTERACTION_ID=$question_interaction_id" hermes python3 - <<'PY'
import json
import os
import sqlite3
import sys

sys.path.insert(0, "/opt/nix")
import paperclip_question_delivery as delivery

with sqlite3.connect("/opt/data/runs_idempotency.db") as database:
    assert database.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert database.execute(
        "SELECT run_id FROM run_idempotency WHERE idempotency_key = ?",
        (os.environ["NIX_FIXTURE_RUN_KEY"],),
    ).fetchone() == (os.environ["NIX_FIXTURE_HERMES_RUN_ID"],)

issue_id = os.environ["NIX_FIXTURE_ISSUE_ID"]
interaction_id = os.environ["NIX_FIXTURE_INTERACTION_ID"]
payload = {
    "version": 1,
    "title": "Recovery decision fixture",
    "questions": [{
        "id": "direction",
        "prompt": "Choose the recovery fixture direction",
        "selectionMode": "single", "required": True,
        "options": [{"id": "continue", "label": "Continue"}],
    }],
}
request = {
    "jsonrpc": "2.0", "id": 1, "method": "tools/call",
    "params": {"name": "paperclipAskUserQuestions", "arguments": {
        "issueId": issue_id, "idempotencyKey": "recovery-question-v1",
        "payload": payload,
    }},
}
interaction = {
    "id": interaction_id, "issueId": issue_id,
    "kind": "ask_user_questions", "status": "pending",
    "requestedResolverPolicy": "human_only",
    "effectiveResolverPolicy": "human_only",
    "addresseeUserId": os.environ["PAPERCLIP_LIOR_USER_ID"],
    "payload": payload,
}
response = {"jsonrpc": "2.0", "id": 1, "result": {
    "content": [{"type": "text", "text": json.dumps(interaction)}],
}}
def forbidden_send(*_args, **_kwargs):
    raise AssertionError("restored unknown notification attempted a replay")
delivery._post = forbidden_send
assert delivery.notify_question_created(response, request) == "unknown"
with sqlite3.connect(delivery.OUTBOX_PATH) as database:
    assert database.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    columns = {row[1] for row in database.execute("PRAGMA table_info(deliveries)")}
    assert {"interaction_id", "payload_digest", "state", "attempt_count", "http_status"} <= columns
    assert database.execute(
        "SELECT state, attempt_count, http_status FROM deliveries WHERE interaction_id = ?",
        (interaction_id,),
    ).fetchone() == ("unknown", 3, 502)
PY
docker run --rm --volume "${restore_project}_hermes_data:/state:ro" "$archive_helper_image" sh -ec '
  grep -qx chief-of-staff-continuity-v1 /state/memories/slice-1-continuity.txt
  grep -qx telegram-session-fixture-v1 /state/sessions/slice-1-session.json
  if test -e /state/auth.json; then
    test "$(stat -c %a /state/auth.json)" = 600
    test "$(stat -c %u:%g /state/auth.json)" = 10000:10000
  fi
  grep -q "desired_state" /state/gateway_state.json
  test "$(stat -c %a /state/.env)" = 600
  test "$(stat -c %u:%g /state/.env)" = 10000:10000
  test -s /state/.paperclip-claim-receipt.json
  test "$(stat -c %a /state/.paperclip-claim-receipt.json)" = 600
  test "$(stat -c %u:%g /state/.paperclip-claim-receipt.json)" = 10000:10000
  for path in runs_idempotency.db state/paperclip-question-delivery.db; do
    test -f "/state/$path"
    test ! -L "/state/$path"
    test "$(stat -c %h "/state/$path")" = 1
    test "$(stat -c %u:%g "/state/$path")" = 10000:10000
    test "$(stat -c %a "/state/$path")" = 600
  done
  ! grep -Eq "^[[:space:]]*(export[[:space:]]+)?(HERMES_DECISION_WEBHOOK_SECRET|PAPERCLIP_LIOR_USER_ID|TELEGRAM_BOT_TOKEN|TELEGRAM_HOME_CHANNEL|TELEGRAM_ALLOWED_USERS|TELEGRAM_ALLOW_ALL_USERS|GATEWAY_ALLOW_ALL_USERS|WEBHOOK_SECRET)[[:space:]]*=" /state/.env
' || fail "restored Hermes identity/session/skill fixtures are incomplete"
# shellcheck disable=SC2016
"${restore_compose[@]}" exec -T -e EXPECTED_AGENT_ID="$hermes_agent_id" hermes sh -ec \
  'test "$(grep -E "^PAPERCLIP_AGENT_ID=" /opt/data/.env | cut -d= -f2-)" = "$EXPECTED_AGENT_ID"' \
  2>/dev/null \
  || fail "restored Hermes agent identifier differs from the claimed source identity"

"${restore_compose[@]}" down --volumes --remove-orphans
printf 'Fresh bootstrap and realistic Paperclip backup/restore smoke passed.\n'
