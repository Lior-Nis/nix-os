#!/usr/bin/env bash
set -euo pipefail
umask 077

# Secret-free full-stack acceptance for the pinned Paperclip native runner.
# The first-party fake sandbox provider covers the plugin/lease/transport gate;
# the instance-managed local environment separately covers runnerd/OpenCode.

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
tmp_dir=$(mktemp -d /tmp/nix-paperclip-specialist-integration.XXXXXX)
suffix=$(openssl rand -hex 8)
project="nix-paperclip-integration-$suffix"
image="nix-paperclip-integration:$suffix"
compose_file="$tmp_dir/compose.yaml"
paperclip_env="$tmp_dir/paperclip.env"
relay_env="$tmp_dir/relay.env"
state_file="$tmp_dir/state.json"
authority_state="$tmp_dir/authority.json"
cookie_file="$tmp_dir/cookies.txt"
paperclip_logs="$tmp_dir/paperclip.log"
signature_sentinel=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
base_image='ghcr.io/paperclipai/paperclip:2026.916.1@sha256:a02ac35ac41df911af477422ea0e781cf41d2b2c600c66f0a5ac9d8c63f52c2c'
compose=(docker compose -p "$project" -f "$compose_file")

fail() {
  printf 'paperclip specialist integration error: %s\n' "$*" >&2
  exit 1
}

cleanup() {
  local status=$?
  if (( status != 0 )) && [[ -f "$compose_file" ]]; then
    printf 'Disposable Paperclip status at failure:\n' >&2
    "${compose[@]}" ps >&2 || true
    printf 'Disposable Paperclip logs at failure:\n' >&2
    "${compose[@]}" logs --no-color --tail 240 paperclip >&2 || true
  fi
  if [[ -f "$compose_file" ]]; then
    "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
  docker image rm "$image" >/dev/null 2>&1 || true
  rm -rf "$tmp_dir"
  return "$status"
}
trap cleanup EXIT

command -v docker >/dev/null 2>&1 || fail "docker is required"
command -v openssl >/dev/null 2>&1 || fail "openssl is required"
command -v python3 >/dev/null 2>&1 || fail "python3 is required"
command -v jq >/dev/null 2>&1 || fail "jq is required"
docker info >/dev/null

postgres_password=$(openssl rand -hex 32)
paperclip_password=$(openssl rand -hex 32)
admin_password="Aa1!$(openssl rand -hex 20)"
relay_secret=$(openssl rand -hex 32)

cat >"$paperclip_env" <<EOF
DATABASE_URL=postgresql://paperclip:${paperclip_password}@postgres:5432/paperclip
BETTER_AUTH_SECRET=$(openssl rand -hex 32)
PAPERCLIP_TOOL_ACTION_SIGNING_SECRET=$(openssl rand -hex 32)
EOF
cat >"$relay_env" <<EOF
NIX_PAPERCLIP_SPECIALIST_AGENT_IDS=
NIX_PAPERCLIP_FOUNDER_USER_ID=lior-bootstrap
PAPERCLIP_LIOR_USER_ID=lior-bootstrap
NIX_CHIEF_AGENT_ID=
NIX_LIOR_TELEGRAM_USER_ID=123456789
NIX_LIOR_TELEGRAM_CHAT_ID=123456789
NIX_FOUNDER_RELAY_SECRET=${relay_secret}
EOF
chmod 0600 "$paperclip_env" "$relay_env"

cat >"$compose_file" <<EOF
services:
  postgres:
    image: postgres:17.11-alpine3.24@sha256:b0f9560a2de083e2cc7382e75f808c7381a32852a7ec49117deedb300e552b24
    environment:
      POSTGRES_USER: postgres
      POSTGRES_DB: postgres
      POSTGRES_PASSWORD: ${postgres_password}
      PAPERCLIP_DB_PASSWORD: ${paperclip_password}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ${repo_root}/deploy/postgres/10-paperclip.sh:/docker-entrypoint-initdb.d/10-paperclip.sh:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U paperclip -d paperclip"]
      interval: 2s
      timeout: 3s
      retries: 30
  paperclip:
    image: ${image}
    entrypoint: ["/opt/nix/paperclip-specialist-authority-entrypoint.sh"]
    env_file:
      - ${paperclip_env}
      - ${relay_env}
    environment:
      HOST: 0.0.0.0
      PORT: "3100"
      SERVE_UI: "true"
      PAPERCLIP_HOME: /paperclip
      PAPERCLIP_INSTANCE_ID: default
      PAPERCLIP_DEPLOYMENT_MODE: authenticated
      PAPERCLIP_DEPLOYMENT_EXPOSURE: private
      PAPERCLIP_PUBLIC_URL: https://nix-os.test-tailnet.ts.net
      PAPERCLIP_API_URL: http://127.0.0.1:3100
      PAPERCLIP_ALLOWED_HOSTNAMES: paperclip
      PAPERCLIP_AUTH_DISABLE_SIGN_UP: "false"
      PAPERCLIP_ENABLE_COMPANY_DELETION: "false"
      PAPERCLIP_SECRETS_STRICT_MODE: "true"
      PAPERCLIP_DB_BACKUP_ENABLED: "false"
      PAPERCLIP_MIGRATION_AUTO_APPLY: "true"
      PAPERCLIP_RUNNER_REMOTE_BINARY_PATH: /app/packages/paperclip-runner/dist/bin/paperclip-runnerd
      PAPERCLIP_RUNNER_REMOTE_PROVIDER_PACK_PATH: /runner-cache/nix-specialist-provider-pack
      NIX_TEST_AUTHORITY_ONLY: "${NIX_TEST_AUTHORITY_ONLY:-false}"
    volumes:
      - paperclip_data:/paperclip
      - runner_cache:/runner-cache
      - ${repo_root}/deploy/paperclip/entrypoint.sh:/opt/nix/paperclip-entrypoint.sh:ro
      - ${repo_root}/tests/smoke/paperclip-specialist-authority-entrypoint.sh:/opt/nix/paperclip-specialist-authority-entrypoint.sh:ro
      - ${repo_root}/deploy/paperclip/patch-specialist-runtime.py:/opt/nix/patch-specialist-runtime.py:ro
      - ${repo_root}/tests/smoke/paperclip-specialist-authority.mjs:/opt/nix/paperclip-specialist-authority.mjs:ro
    ports:
      - "127.0.0.1::3100"
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      default:
        aliases: [hermes]
    healthcheck:
      test: ["CMD-SHELL", "curl -fsS http://127.0.0.1:3100/api/health | grep -q '\"status\":\"ok\"'"]
      interval: 3s
      timeout: 5s
      # A fresh CI runner builds the pinned upstream provider pack on first boot.
      retries: 120
      start_period: 30s
volumes:
  postgres_data:
  paperclip_data:
  runner_cache:
EOF

# The plugin is shipped as official source in the exact Paperclip image but is
# intentionally test-only and not prebuilt. Build only that upstream package.
docker build --quiet --tag "$image" - <<EOF >/dev/null
FROM ${base_image}
# The exact release's local runner resolves its build-owned OpenCode package
# relative to server/dist/vendor, while the image's pnpm store owns the exact
# pinned package at the repository root. Production remote runs use the
# provider pack instead; this fixture-only symlink enables the upstream local
# path so hosted CI can exercise runnerd without a public WSS endpoint.
RUN cd /app && pnpm --filter @paperclipai/plugin-fake-sandbox build \
 && test "\$(node -p "require('/app/node_modules/.pnpm/opencode-ai@1.18.29/node_modules/opencode-ai/package.json').version")" = 1.18.29 \
 && mkdir -p /app/server/dist/vendor/node_modules \
 && ln -s /app/node_modules/.pnpm/opencode-ai@1.18.29/node_modules/opencode-ai \
      /app/server/dist/vendor/node_modules/opencode-ai
EOF

"${compose[@]}" up -d --wait postgres

# Provision the supported authenticated/private instance configuration. This
# mirrors scripts/initialize-paperclip without involving production config.
set +e
# The single-quoted program is evaluated inside the container.
# shellcheck disable=SC2016
"${compose[@]}" run --rm --no-deps --entrypoint sh paperclip -ec '
  set +e
  { sleep 20; printf "\r"; sleep 10; printf "n"; } | \
    COREPACK_ENABLE_DOWNLOAD_PROMPT=0 COLUMNS=120 LINES=40 \
    timeout --signal=TERM 90s script -qec \
      "stty rows 40 cols 120; pnpm paperclipai onboard --data-dir /paperclip" /dev/null
  status=$?
  test -s /paperclip/instances/default/config.json || exit "$status"
  case "$status" in 0|124|143) exit 0;; *) exit "$status";; esac
' >/dev/null 2>&1
onboard_status=$?
set -e
(( onboard_status == 0 )) || fail "official Paperclip onboarding failed"

paperclip_started=0
for attempt in 1 2 3; do
  if "${compose[@]}" up -d --wait paperclip; then
    paperclip_started=1
    break
  fi
  (( attempt < 3 )) || break
  # The pinned upstream provider-pack builder may be interrupted while pnpm is
  # populating its disposable cache. Restarting the same container reuses that
  # cache and the named runner-cache volume without changing the tested image.
  "${compose[@]}" start paperclip >/dev/null
done
if (( paperclip_started != 1 )); then
  printf 'paperclip specialist integration error: disposable Paperclip failed to start\n' >&2
  exit 1
fi
paperclip_port=$("${compose[@]}" port paperclip 3100 | awk -F: 'END {print $NF}')
[[ "$paperclip_port" =~ ^[0-9]+$ ]] || fail "could not resolve disposable Paperclip port"
base_url="http://127.0.0.1:${paperclip_port}"

# Phase one creates inert topology while the fail-closed specialist allowlist
# is empty. It never wakes an execution agent.
python3 - "$base_url" "$state_file" "$cookie_file" "$admin_password" <<'PY'
import http.cookies
import json
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

base, state_path, cookie_path, password = sys.argv[1:]
origin = "https://nix-os.test-tailnet.ts.net"
opener = urllib.request.build_opener()
cookies = {}

def request(method, path, body=None, bearer=None, expected=range(200, 300)):
    data = None if body is None else json.dumps(body, separators=(",", ":")).encode()
    headers = {"Accept": "application/json", "Origin": origin}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    if cookies:
        headers["Cookie"] = "; ".join(f"{key}={value}" for key, value in cookies.items())
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with opener.open(req, timeout=90) as res:
            raw = res.read()
            for value in res.headers.get_all("Set-Cookie", []):
                parsed = http.cookies.SimpleCookie()
                parsed.load(value)
                cookies.update({key: morsel.value for key, morsel in parsed.items()})
            if res.status not in expected:
                raise AssertionError(f"{method} {path}: HTTP {res.status}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:1000]
        raise AssertionError(f"{method} {path}: HTTP {exc.code}: {detail}") from exc
    return json.loads(raw) if raw else None

request("POST", "/api/auth/sign-up/email", {
    "name": "Hosted Integration Admin",
    "email": "specialist-integration@paperclip.test",
    "password": password,
})
request("POST", "/api/bootstrap/claim", {})
session = request("GET", "/api/auth/get-session")
founder = session.get("user", {}).get("id") or session.get("session", {}).get("userId") or session.get("userId")
assert isinstance(founder, str) and founder

company = request("POST", "/api/companies", {
    "name": "Hosted Specialist Integration",
    "description": "Disposable secret-free native runner fixture",
    "budgetMonthlyCents": 0,
})
local_environments = request("GET", f"/api/companies/{company['id']}/environments?driver=local")
assert len(local_environments) == 1 and local_environments[0]["driver"] == "local"
project = request("POST", f"/api/companies/{company['id']}/projects", {
    "name": "Approved Integration Fixture",
    "description": "Disposable approved project",
})
request("PATCH", "/api/instance/settings/experimental", {
    "enableEnvironments": True,
    "enableNativeRunner": True,
})
plugin = request("POST", "/api/plugins/install", {
    "packageName": "/app/packages/plugins/paperclip-plugin-fake-sandbox",
    "isLocalPath": True,
})
assert plugin["status"] == "ready", plugin.get("status")
assert plugin["pluginKey"] == "paperclip.fake-sandbox-provider", plugin.get("pluginKey")
health = request("GET", f"/api/plugins/{plugin['id']}/health")
assert health["healthy"] is True

environment = request("POST", f"/api/companies/{company['id']}/environments", {
    "name": "Official fake sandbox",
    "description": "First-party deterministic hosted fixture",
    "driver": "sandbox",
    "status": "active",
    "config": {
        "provider": "fake-plugin",
        "image": "fake:test",
        "timeoutMs": 60000,
        "reuseLease": False,
        "runnerLifecycleMode": "per_turn",
    },
    "envVars": {},
})
probe = request("POST", f"/api/environments/{environment['id']}/probe?companyId={company['id']}", {})
assert probe["ok"] is True
assert probe.get("driver") == "sandbox"
assert probe.get("details", {}).get("provider") == "fake-plugin"

chief = request("POST", f"/api/companies/{company['id']}/agents", {
    "name": "Chief Relay Fixture",
    "role": "general",
    "capabilities": "Founder relay fixture only",
    "adapterType": "process",
    "adapterConfig": {"command": "/bin/false", "args": []},
    "runtimeConfig": {"heartbeat": {"enabled": False}},
    "budgetMonthlyCents": 0,
    "permissions": {"canCreateAgents": False, "canCreateSkills": False},
})
specialist = request("POST", f"/api/companies/{company['id']}/agents", {
    "name": "Hosted Product Fixture",
    "role": "pm",
    "title": "Task-scoped integration specialist",
    "reportsTo": chief["id"],
    "capabilities": "Exercise the native runner lifecycle",
    "adapterType": "paperclip_runner",
    "adapterConfig": {
        "provider": "opencode",
        "model": "nixdummy/model",
        "opencodePermissionMode": "deny",
        "lifecycleMode": "per_turn",
    },
    "instructionsBundle": {
        "entryFile": "AGENTS.md",
        "files": {"AGENTS.md": "Secret-free integration fixture. Do not call tools."},
    },
    "runtimeConfig": {"heartbeat": {"enabled": False, "maxConcurrentRuns": 1}},
    "defaultEnvironmentId": environment["id"],
    "budgetMonthlyCents": 0,
    "permissions": {"canCreateAgents": False, "canCreateSkills": False},
})
growth = request("POST", f"/api/companies/{company['id']}/agents", {
    "name": "Hosted Growth Fixture",
    "role": "cmo",
    "title": "Task-scoped integration specialist",
    "reportsTo": chief["id"],
    "capabilities": "Execute a delegated same-project child task",
    "adapterType": "paperclip_runner",
    "adapterConfig": {
        "provider": "opencode",
        "model": "nixdummy/model",
        "opencodePermissionMode": "deny",
        "lifecycleMode": "per_turn",
    },
    "instructionsBundle": {
        "entryFile": "AGENTS.md",
        "files": {"AGENTS.md": "Secret-free Growth integration fixture. Do not call tools."},
    },
    "runtimeConfig": {"heartbeat": {"enabled": False, "maxConcurrentRuns": 1}},
    "defaultEnvironmentId": local_environments[0]["id"],
    "budgetMonthlyCents": 0,
    "permissions": {"canCreateAgents": False, "canCreateSkills": False},
})
key = request("POST", f"/api/agents/{chief['id']}/keys", {
    "name": "founder-relay-integration",
    "scope": {"kind": "standard"},
})
assert isinstance(key.get("token"), str) and key["token"]

pathlib.Path(state_path).write_text(json.dumps({
    "founderId": founder,
    "companyId": company["id"],
    "projectId": project["id"],
    "environmentId": environment["id"],
    "localEnvironmentId": local_environments[0]["id"],
    "chiefId": chief["id"],
    "specialistId": specialist["id"],
    "growthId": growth["id"],
    "chiefToken": key["token"],
}), encoding="utf-8")
pathlib.Path(state_path).chmod(0o600)
PY

founder_id=$(jq -er '.founderId' "$state_file")
chief_id=$(jq -er '.chiefId' "$state_file")
specialist_id=$(jq -er '.specialistId' "$state_file")
growth_id=$(jq -er '.growthId' "$state_file")
cat >"$relay_env" <<EOF
NIX_PAPERCLIP_SPECIALIST_AGENT_IDS=${specialist_id},${growth_id}
NIX_PAPERCLIP_FOUNDER_USER_ID=${founder_id}
PAPERCLIP_LIOR_USER_ID=${founder_id}
NIX_CHIEF_AGENT_ID=${chief_id}
NIX_LIOR_TELEGRAM_USER_ID=123456789
NIX_LIOR_TELEGRAM_CHAT_ID=123456789
NIX_FOUNDER_RELAY_SECRET=${relay_secret}
EOF
chmod 0600 "$relay_env"
"${compose[@]}" up -d --no-deps --force-recreate --wait paperclip
paperclip_port=$("${compose[@]}" port paperclip 3100 | awk -F: 'END {print $NF}')
[[ "$paperclip_port" =~ ^[0-9]+$ ]] || fail "could not resolve recreated Paperclip port"
base_url="http://127.0.0.1:${paperclip_port}"

# Exercise the exact upstream Paperclip runner authority against the disposable
# real database. Its callback checks that the Product-created child and audit
# attribution committed before the delegated Growth wake was handed off.
company_id=$(jq -er '.companyId' "$state_file")
project_id=$(jq -er '.projectId' "$state_file")
"${compose[@]}" exec -T paperclip \
  node --import /app/server/node_modules/tsx/dist/loader.mjs \
  /opt/nix/paperclip-specialist-authority.mjs \
  "$company_id" "$project_id" "$chief_id" "$specialist_id" "$growth_id" >"$authority_state"
chmod 0600 "$authority_state"
jq -e '.childId and .parentIssueId and .productRunId and .chiefIssueId and .chiefRunId and .interactionId
  and .committedBeforeWake == true' \
  "$authority_state" >/dev/null

if [[ ${NIX_TEST_AUTHORITY_ONLY:-false} == true ]]; then
  printf 'paperclip specialist authority delivery matrix: ok\n'
  exit 0
fi

# Phase two proves the real wake path and the real patched founder relay route.
python3 - "$base_url" "$state_file" "$authority_state" "$admin_password" "$relay_secret" "$signature_sentinel" "$project" "$compose_file" <<'PY'
import hashlib
import hmac
import http.cookies
import json
import subprocess
import threading
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

(
    base, state_path, authority_path, password, relay_secret,
    signature_sentinel, compose_project, compose_path,
) = sys.argv[1:]
state = json.load(open(state_path, encoding="utf-8"))
authority = json.load(open(authority_path, encoding="utf-8"))
origin = "https://nix-os.test-tailnet.ts.net"
opener = urllib.request.build_opener()
cookies = {}

class ApiError(Exception):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail
        super().__init__(f"HTTP {status}: {detail[:500]}")

def request(method, path, body=None, bearer=None, headers=None, expected=range(200, 300)):
    data = None if body is None else json.dumps(body, separators=(",", ":")).encode()
    request_headers = {"Accept": "application/json", "Origin": origin}
    if data is not None:
        request_headers["Content-Type"] = "application/json"
    if bearer:
        request_headers["Authorization"] = f"Bearer {bearer}"
    elif cookies:
        request_headers["Cookie"] = "; ".join(f"{key}={value}" for key, value in cookies.items())
    if headers:
        request_headers.update(headers)
    req = urllib.request.Request(base + path, data=data, headers=request_headers, method=method)
    try:
        with opener.open(req, timeout=90) as res:
            raw = res.read()
            status = res.status
            for value in res.headers.get_all("Set-Cookie", []):
                parsed = http.cookies.SimpleCookie()
                parsed.load(value)
                cookies.update({key: morsel.value for key, morsel in parsed.items()})
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
    detail = raw.decode(errors="replace")
    if status not in expected:
        raise ApiError(status, detail)
    return json.loads(detail) if detail else None

request("POST", "/api/auth/sign-in/email", {
    "email": "specialist-integration@paperclip.test",
    "password": password,
})

sandbox_issue = request("POST", f"/api/companies/{state['companyId']}/issues", {
    "projectId": state["projectId"],
    "title": "Exercise fake sandbox native lifecycle",
    "description": "Start OpenCode and fail only at the intentional dummy provider.",
    "status": "backlog",
    "workMode": "standard",
    "assigneeAgentId": state["specialistId"],
})

wake = request("POST", f"/api/agents/{state['specialistId']}/wakeup", {
    "source": "on_demand",
    "triggerDetail": "manual",
    "reason": "hosted_secret_free_integration",
    "payload": {
        "issueId": sandbox_issue["id"],
        "taskId": sandbox_issue["id"],
        "taskKey": sandbox_issue.get("identifier"),
    },
    "idempotencyKey": f"hosted-sandbox:{sandbox_issue['id']}",
    "forceFreshSession": True,
})
sandbox_run_id = wake["id"]

terminal = {"succeeded", "failed", "cancelled", "timed_out", "interrupted"}
def wait_events(run_id, predicate, timeout=20):
    deadline = time.time() + timeout
    observed = []
    while time.time() < deadline:
        observed = request("GET", f"/api/heartbeat-runs/{run_id}/events?limit=1000")
        if predicate(observed):
            return observed
        time.sleep(0.5)
    return observed

deadline = time.time() + 120
run = wake
while run.get("status") not in terminal and time.time() < deadline:
    time.sleep(1)
    run = request("GET", f"/api/heartbeat-runs/{sandbox_run_id}")
assert run.get("status") == "failed", run.get("status")
assert run.get("runtimeMode") == "native", run.get("runtimeMode")
assert isinstance(run.get("runnerInstanceId"), str) and run["runnerInstanceId"]

events = wait_events(
    sandbox_run_id,
    lambda rows: "runner_transport_ineligible" in json.dumps(rows),
)
event_types = [event.get("eventType") for event in events]
assert "native.process_start_requested" in event_types, event_types
spans = [event.get("payload", {}) for event in events if event.get("eventType") == "run.performance.span"]
for required in ("environment.acquire", "environment.workspace.realize"):
    matched = [span for span in spans if span.get("span") == required]
    assert matched and matched[-1].get("outcome") == "ok", (required, spans)
assert "runner_transport_ineligible" in json.dumps(events), event_types
assert "session.started" not in event_types, event_types

lease = {}
lease_deadline = time.time() + 30
while time.time() < lease_deadline:
    leases = request("GET", f"/api/environments/{state['environmentId']}/leases")
    lease = next(row for row in leases if row.get("heartbeatRunId") == sandbox_run_id)
    if lease.get("releasedAt") and lease.get("status") in {"released", "failed", "expired"}:
        break
    time.sleep(1)
assert lease.get("provider") == "fake-plugin", lease
assert str(lease.get("providerLeaseId", "")).startswith(f"fake-plugin://{sandbox_run_id}/"), lease
assert lease.get("releasedAt"), lease
assert lease.get("status") in {"released", "failed", "expired"}, lease.get("status")

# The official fake provider intentionally has no runner WebSocket ingress.
# Its self-contained supported coverage ends at the exact fail-closed transport
# gate after plugin activation, lease acquisition, workspace realization, and
# cleanup. The instance-managed local environment is the smallest official,
# secret-free path through runnerd and OpenCode in hosted CI; the production
# authenticated WSS transport remains a live-acceptance responsibility.
request("PATCH", f"/api/agents/{state['specialistId']}", {
    "defaultEnvironmentId": state["localEnvironmentId"],
})
first_turn_canary = "PRODUCT_FIRST_TURN_CANARY_7f31b9c2"
local_issue = request("POST", f"/api/companies/{state['companyId']}/issues", {
    "projectId": state["projectId"],
    "title": "Exercise runnerd and OpenCode dummy failure",
    "description": (
        "Start the exact pinned OpenCode runtime and fail only at its nonexistent dummy provider. "
        + first_turn_canary
    ),
    "status": "backlog",
    "workMode": "standard",
    "assigneeAgentId": state["specialistId"],
})
local_wake = request("POST", f"/api/agents/{state['specialistId']}/wakeup", {
    "source": "on_demand",
    "triggerDetail": "manual",
    "reason": "hosted_secret_free_runner_integration",
    "payload": {
        "issueId": local_issue["id"],
        "taskId": local_issue["id"],
        "taskKey": local_issue.get("identifier"),
    },
    "idempotencyKey": f"hosted-local:{local_issue['id']}",
    "forceFreshSession": True,
})
local_run_id = local_wake["id"]
deadline = time.time() + 120
local_run = local_wake
while local_run.get("status") not in terminal and time.time() < deadline:
    time.sleep(1)
    local_run = request("GET", f"/api/heartbeat-runs/{local_run_id}")
assert local_run.get("status") == "failed", local_run.get("status")
assert local_run.get("runtimeMode") == "native", local_run.get("runtimeMode")
assert isinstance(local_run.get("runnerInstanceId"), str) and local_run["runnerInstanceId"]

local_events = wait_events(
    local_run_id,
    lambda rows: "turn.failed" in [event.get("eventType") for event in rows],
)
local_event_types = [event.get("eventType") for event in local_events]
for required in (
    "native.process_start_requested",
    "session.started",
    "turn.submitted",
    "turn.failed",
):
    assert required in local_event_types, (
        required,
        local_event_types,
        {
            "error": local_run.get("error"),
            "errorCode": local_run.get("errorCode"),
            "resultJson": local_run.get("resultJson"),
        },
        [
            {
                "eventType": event.get("eventType"),
                "message": event.get("message"),
                "payload": event.get("payload"),
            }
            for event in local_events
            if event.get("eventType") in {"error", "lifecycle", "native.process_identity_recorded"}
        ],
    )
session_contexts = [
    (((event.get("payload") or {}).get("prpEvent") or {}).get("payload") or {}).get("context") or {}
    for event in local_events
    if event.get("eventType") == "session.started"
]
assert any(context.get("modelProvider") == "nixdummy" for context in session_contexts), session_contexts
assert local_run.get("errorCode") == "adapter_failed", local_run.get("errorCode")
assert (local_run.get("resultJson") or {}).get("summary") == (
    "The OpenCode run failed before it completed."
), local_run.get("resultJson")
turn_failed = next(event for event in local_events if event.get("eventType") == "turn.failed")
turn_failed_payload = (
    ((turn_failed.get("payload") or {}).get("prpEvent") or {}).get("payload") or {}
)
assert turn_failed_payload.get("status") == "failed", turn_failed_payload
assert first_turn_canary in json.dumps(local_events), "Product turn context omitted its canary"

def normalized_session_ids(rows):
    return {
        ((event.get("payload") or {}).get("prpEvent") or {}).get("normalizedSessionId")
        for event in rows
        if ((event.get("payload") or {}).get("prpEvent") or {}).get("normalizedSessionId")
    }

product_sessions = normalized_session_ids(local_events)
assert len(product_sessions) == 1, product_sessions

# The authority fixture already committed this same-project child, its Product
# attribution, and the Growth assignment before handing off the wake request.
# Now execute Growth through the same pinned runnerd/OpenCode path and prove a
# fresh task-scoped session does not inherit Product's first-turn canary.
delegated_child = request("GET", f"/api/issues/{authority['childId']}")
assert delegated_child.get("parentId") == authority["parentIssueId"], delegated_child
assert delegated_child.get("projectId") == state["projectId"], delegated_child
assert delegated_child.get("assigneeAgentId") == state["growthId"], delegated_child
assert delegated_child.get("createdByAgentId") == state["specialistId"], delegated_child
assert delegated_child.get("originRunId") == authority["productRunId"], delegated_child

growth_wake = request("POST", f"/api/agents/{state['growthId']}/wakeup", {
    "source": "assignment",
    "triggerDetail": "system",
    "reason": "issue_assigned",
    "payload": {
        "issueId": delegated_child["id"],
        "taskId": delegated_child["id"],
        "taskKey": delegated_child.get("identifier"),
        "parentIssueId": authority["parentIssueId"],
    },
    "idempotencyKey": f"hosted-growth:{delegated_child['id']}",
    "forceFreshSession": True,
})
growth_run_id = growth_wake["id"]
deadline = time.time() + 120
growth_run = growth_wake
while growth_run.get("status") not in terminal and time.time() < deadline:
    time.sleep(1)
    growth_run = request("GET", f"/api/heartbeat-runs/{growth_run_id}")
assert growth_run.get("status") == "failed", growth_run.get("status")
assert growth_run.get("runtimeMode") == "native", growth_run.get("runtimeMode")
assert growth_run.get("agentId") == state["growthId"], growth_run
assert isinstance(growth_run.get("runnerInstanceId"), str) and growth_run["runnerInstanceId"]
growth_events = wait_events(
    growth_run_id,
    lambda rows: "turn.failed" in [event.get("eventType") for event in rows],
)
growth_event_types = [event.get("eventType") for event in growth_events]
for required in (
    "native.process_start_requested",
    "session.started",
    "turn.submitted",
    "turn.failed",
):
    assert required in growth_event_types, (required, growth_event_types)
growth_contexts = [
    (((event.get("payload") or {}).get("prpEvent") or {}).get("payload") or {}).get("context") or {}
    for event in growth_events
    if event.get("eventType") == "session.started"
]
assert any(context.get("modelProvider") == "nixdummy" for context in growth_contexts), growth_contexts
assert growth_run.get("errorCode") == "adapter_failed", growth_run.get("errorCode")
assert (growth_run.get("resultJson") or {}).get("summary") == (
    "The OpenCode run failed before it completed."
), growth_run.get("resultJson")
growth_sessions = normalized_session_ids(growth_events)
assert len(growth_sessions) == 1, growth_sessions
assert product_sessions.isdisjoint(growth_sessions), (product_sessions, growth_sessions)
assert first_turn_canary not in json.dumps(growth_events), (
    "Product first-turn canary leaked into Growth's fresh context"
)

# Keep the founder-decision fixture independent of the deliberately failed
# OpenCode provider turn. The completed fake-sandbox transport-gate run is a
# stable originating specialist run whose response continuation can enqueue.
issue = sandbox_issue
run_id = sandbox_run_id

interaction = request("POST", f"/api/issues/{issue['id']}/interactions", {
    "kind": "ask_user_questions",
    "idempotencyKey": "founder-route-fixture",
    "sourceRunId": run_id,
    "resolverPolicy": "human_only",
    "addresseeUserId": state["founderId"],
    "continuationPolicy": "wake_assignee",
    "title": "Founder relay fixture",
    "payload": {
        "version": 1,
        "title": "Choose direction",
        "questions": [{
            "id": "direction",
            "prompt": "Choose direction",
            "selectionMode": "single",
            "required": True,
            "options": [
                {"id": "approve", "label": "Approve"},
                {"id": "reject", "label": "Reject"},
            ],
        }],
    },
})
before_runs = request("GET", f"/api/issues/{issue['id']}/runs")
before_activity = request("GET", f"/api/issues/{issue['id']}/activity")
path = f"/api/issues/{issue['id']}/interactions/{interaction['id']}/respond"
def signed_relay(relay_path, answer_id, message_id, idempotency_key):
    body = {"answers": [{"questionId": "direction", "optionIds": [answer_id]}]}
    timestamp = str(int(time.time()))
    canonical_body = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(canonical_body.encode()).hexdigest()
    canonical = "\n".join([
        "v1", timestamp, "POST", relay_path, digest, "telegram", "dm",
        "123456789", "123456789", message_id, idempotency_key,
    ])
    signature = hmac.new(relay_secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return body, {
        "X-Nix-Founder-Relay-Version": "1",
        "X-Nix-Founder-Relay-Timestamp": timestamp,
        "X-Nix-Founder-Relay-Idempotency-Key": idempotency_key,
        "X-Nix-Founder-Relay-Platform": "telegram",
        "X-Nix-Founder-Relay-Chat-Type": "dm",
        "X-Nix-Founder-Relay-User-Id": "123456789",
        "X-Nix-Founder-Relay-Chat-Id": "123456789",
        "X-Nix-Founder-Relay-Message-Id": message_id,
        "X-Nix-Founder-Relay-Signature": f"v1={signature}",
    }

approve_body, approve_headers = signed_relay(path, "approve", "4242", "telegram:4242")
reject_body, reject_headers = signed_relay(path, "reject", "4243", "telegram:4243")

# Reassignment cannot change the immutable source-run classification or let a
# stale question resume a different employee. Exercise that mismatch on the
# separate terminal Product authority issue so upstream ownership-change stop
# state cannot contaminate the unchanged success/continuation fixture below.
mismatch_issue = request("GET", f"/api/issues/{authority['parentIssueId']}")
mismatch_interaction = request(
    "POST",
    f"/api/issues/{mismatch_issue['id']}/interactions",
    {
        "kind": "ask_user_questions",
        "idempotencyKey": "founder-route-reassignment-fixture",
        "sourceRunId": authority["productRunId"],
        "resolverPolicy": "human_only",
        "addresseeUserId": state["founderId"],
        "continuationPolicy": "wake_assignee",
        "title": "Reassigned founder relay fixture",
        "payload": {
            "version": 1,
            "title": "Reassigned Product asks for a founder decision",
            "questions": [{
                "id": "direction",
                "prompt": "Choose direction",
                "selectionMode": "single",
                "required": True,
                "options": [
                    {"id": "approve", "label": "Approve"},
                    {"id": "reject", "label": "Reject"},
                ],
            }],
        },
    },
)
mismatch_path = (
    f"/api/issues/{mismatch_issue['id']}/interactions/"
    f"{mismatch_interaction['id']}/respond"
)
mismatch_body, mismatch_headers = signed_relay(
    mismatch_path, "approve", "4141", "telegram:mismatch:4141"
)
mismatch_before_runs = request("GET", f"/api/issues/{mismatch_issue['id']}/runs")
mismatch_before_activity = request("GET", f"/api/issues/{mismatch_issue['id']}/activity")

try:
    request("POST", mismatch_path, mismatch_body)
    raise AssertionError("headerless Board response passed a reassigned founder relay gate")
except ApiError as exc:
    assert exc.status == 403, exc
    assert json.loads(exc.detail) == {"error": "nix_founder_relay_required"}, exc.detail

# Hold an uncommitted reassignment row lock. Relay preflight still sees the old
# committed specialist assignment, then its answer transaction must wait at
# SELECT ... FOR UPDATE. Commit only after a second connection observes that
# lock wait, and require the in-transaction recheck to reject the stale answer.
# This deterministically exercises the reviewed TOCTOU window.
compose_exec = [
    "docker", "compose", "-p", compose_project, "-f", compose_path,
    "exec", "-T", "postgres", "psql", "--username", "paperclip",
    "--dbname", "paperclip", "--no-psqlrc", "--quiet", "--tuples-only",
    "--no-align",
]
transaction = subprocess.Popen(
    compose_exec,
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    bufsize=1,
)
assert transaction.stdin is not None and transaction.stdout is not None
transaction.stdin.write(
    "BEGIN;\n"
    f"UPDATE issues SET assignee_agent_id = '{state['growthId']}' "
    f"WHERE id = '{mismatch_issue['id']}';\n"
    "SELECT 'NIX_LOCK_READY';\n"
)
transaction.stdin.flush()
lock_ready = False
deadline = time.time() + 10
while time.time() < deadline:
    line = transaction.stdout.readline()
    if line.strip() == "NIX_LOCK_READY":
        lock_ready = True
        break
assert lock_ready, "could not establish the assignment-race transaction lock"

with ThreadPoolExecutor(max_workers=1) as executor:
    stale_relay = executor.submit(
        request,
        "POST",
        mismatch_path,
        mismatch_body,
        state["chiefToken"],
        mismatch_headers,
    )
    waiter_seen = False
    deadline = time.time() + 10
    waiter_query = (
        "SELECT count(*) FROM pg_stat_activity "
        "WHERE datname = 'paperclip' AND wait_event_type = 'Lock' "
        "AND lower(query) LIKE '%assignee_agent_id%' "
        "AND lower(query) LIKE '%for update%';"
    )
    try:
        while time.time() < deadline:
            probe = subprocess.run(
                [*compose_exec, "--command", waiter_query],
                check=True,
                capture_output=True,
                text=True,
            )
            if int(probe.stdout.strip() or "0") >= 1:
                waiter_seen = True
                break
            time.sleep(0.1)
    finally:
        transaction.stdin.write("COMMIT;\n\\q\n")
        transaction.stdin.flush()
    assert waiter_seen, "founder relay did not wait on the issue assignment lock"
    try:
        stale_relay.result(timeout=20)
        raise AssertionError(
            "signed relay crossed a concurrent assignee/source-run mismatch"
        )
    except ApiError as exc:
        assert exc.status == 403, exc
assert transaction.wait(timeout=10) == 0, transaction.stderr.read()

reassigned = request("GET", f"/api/issues/{mismatch_issue['id']}")
assert reassigned.get("assigneeAgentId") == state["growthId"], reassigned
time.sleep(0.25)
mismatch_runs = request("GET", f"/api/issues/{mismatch_issue['id']}/runs")
mismatch_activity = request("GET", f"/api/issues/{mismatch_issue['id']}/activity")
assert {row["runId"] for row in mismatch_runs} == {
    row["runId"] for row in mismatch_before_runs
}, mismatch_runs
assert {row["id"] for row in mismatch_activity} == {
    row["id"] for row in mismatch_before_activity
}, mismatch_activity
assert not any(
    row.get("action") in {
        "issue.founder_relay_reserved",
        "issue.thread_interaction_answered",
    }
    for row in mismatch_activity
), mismatch_activity

request("PATCH", f"/api/issues/{mismatch_issue['id']}", {
    "assigneeAgentId": state["specialistId"],
})
restored = request("GET", f"/api/issues/{mismatch_issue['id']}")
assert restored.get("assigneeAgentId") == state["specialistId"], restored

# The original specialist fixture remains continuously assigned so this is an
# independent positive proof of signed answer, race safety, and continuation.
before_runs = request("GET", f"/api/issues/{issue['id']}/runs")
before_activity = request("GET", f"/api/issues/{issue['id']}/activity")

# An ordinary authenticated Board session cannot answer a founder-routed Nix
# interaction without the Chief's signed Telegram relay. The rejection is
# side-effect-free: no reservation, answer, or continuation run may appear.
try:
    request("POST", path, approve_body)
    raise AssertionError("headerless Board response passed the founder relay gate")
except ApiError as exc:
    assert exc.status == 403, exc
    assert json.loads(exc.detail) == {"error": "nix_founder_relay_required"}, exc.detail
time.sleep(0.25)
headerless_runs = request("GET", f"/api/issues/{issue['id']}/runs")
headerless_activity = request("GET", f"/api/issues/{issue['id']}/activity")
assert {row["runId"] for row in headerless_runs} == {
    row["runId"] for row in before_runs
}, headerless_runs
assert {row["id"] for row in headerless_activity} == {
    row["id"] for row in before_activity
}, headerless_activity
assert not any(
    row.get("action") in {
        "issue.founder_relay_reserved",
        "issue.thread_interaction_answered",
    }
    for row in headerless_activity
), headerless_activity

# A valid Telegram attestation is still rejected unless the request actor is
# the configured Chief agent.
try:
    request("POST", path, approve_body, headers=approve_headers)
    raise AssertionError("board actor unexpectedly passed the Chief-only relay gate")
except ApiError as exc:
    assert exc.status == 403, exc

bad_headers = dict(approve_headers)
bad_headers["X-Nix-Founder-Relay-Signature"] = "v1=" + signature_sentinel
try:
    request("POST", path, approve_body, bearer=state["chiefToken"], headers=bad_headers)
    raise AssertionError("invalid founder relay signature was accepted")
except ApiError as exc:
    assert exc.status == 403, exc

# Distinct, valid Telegram answers race the real route. The transaction may
# persist exactly one reservation/answer; the changed loser must be a conflict,
# never an idempotent replay. The committed request may initially return 503
# while its durable continuation is still materializing. That is deliberately
# outcome-uncertain, so retry only its exact signed body/key until Paperclip can
# prove the immutable origin's continuation run and issue the receipt.
barrier = threading.Barrier(2)
def race_submit(label, body, headers):
    barrier.wait(timeout=10)
    try:
        return label, "ok", request(
            "POST", path, body, bearer=state["chiefToken"], headers=headers
        )
    except ApiError as exc:
        return label, "error", exc

with ThreadPoolExecutor(max_workers=2) as executor:
    race_results = list(executor.map(
        lambda args: race_submit(*args),
        [
            ("approve", approve_body, approve_headers),
            ("reject", reject_body, reject_headers),
        ],
    ))
immediate_winners = [result for result in race_results if result[1] == "ok"]
conflicts = [
    result for result in race_results
    if result[1] == "error" and result[2].status == 409
]
pending = [
    result for result in race_results
    if result[1] == "error" and result[2].status == 503
]
assert len(conflicts) == 1, [
    (label, outcome, getattr(value, "status", None))
    for label, outcome, value in race_results
]
assert len(immediate_winners) + len(pending) == 1, [
    (label, outcome, getattr(value, "status", None))
    for label, outcome, value in race_results
]
winner_label = (immediate_winners or pending)[0][0]
if winner_label == "approve":
    winning_body, winning_headers = approve_body, approve_headers
    losing_body, losing_headers = reject_body, reject_headers
    message_id, idempotency_key = "4242", "telegram:4242"
else:
    winning_body, winning_headers = reject_body, reject_headers
    losing_body, losing_headers = approve_body, approve_headers
    message_id, idempotency_key = "4243", "telegram:4243"

if immediate_winners:
    answered = immediate_winners[0][2]
    expected_initial_replay = False
else:
    expected_initial_replay = True
    deadline = time.time() + 30
    answered = None
    while time.time() < deadline:
        try:
            answered = request(
                "POST", path, winning_body,
                bearer=state["chiefToken"], headers=winning_headers,
            )
            break
        except ApiError as exc:
            assert exc.status == 503, exc
            assert json.loads(exc.detail) == {
                "error": "nix_founder_relay_continuation_pending"
            }, exc.detail
            time.sleep(0.5)
    assert answered is not None, "founder continuation did not become provable"

relay = answered.get("nixFounderRelay", {})
assert answered.get("status") == "answered", answered.get("status")
assert answered.get("resolvedByUserId") == state["founderId"], answered.get("resolvedByUserId")
assert relay == {
    "version": 1,
    "verified": True,
    "interactionId": interaction["id"],
    "issueId": issue["id"],
    "resolverUserId": state["founderId"],
    "sourceMessageId": message_id,
    "idempotencyKey": idempotency_key,
    "originAgentId": state["specialistId"],
    "resumedAgentId": state["specialistId"],
    "replayed": expected_initial_replay,
}, relay

before_ids = {row["runId"] for row in before_runs}
deadline = time.time() + 30
after_runs = []
while time.time() < deadline:
    after_runs = request("GET", f"/api/issues/{issue['id']}/runs")
    if len({row["runId"] for row in after_runs} - before_ids) == 1:
        break
    time.sleep(0.5)
new_runs = [row for row in after_runs if row["runId"] not in before_ids]
assert len(new_runs) == 1, [row.get("runId") for row in new_runs]
resumed = request("GET", f"/api/heartbeat-runs/{new_runs[0]['runId']}")
assert resumed.get("agentId") == state["specialistId"], resumed
snapshot = resumed.get("contextSnapshot") or {}
assert snapshot.get("interactionId") == interaction["id"], snapshot
assert snapshot.get("sourceRunId") == run_id, snapshot
assert snapshot.get("wakeReason") == "issue_commented", snapshot

activity = request("GET", f"/api/issues/{issue['id']}/activity")
reservations = [row for row in activity if row.get("action") == "issue.founder_relay_reserved"]
answers = [row for row in activity if row.get("action") == "issue.thread_interaction_answered"]
assert len(reservations) == 1, len(reservations)
assert len(answers) == 1, len(answers)
assert answers[0].get("actorType") == "user", answers[0]
assert answers[0].get("actorId") == state["founderId"], answers[0]
answer_relay = (answers[0].get("details") or {}).get("nixFounderRelay") or {}
assert answer_relay.get("originAgentId") == state["specialistId"], answer_relay
assert answer_relay.get("resumedAgentId") is None, answer_relay
assert answer_relay.get("continuationStatus") == "pending", answer_relay

# After commit, the losing changed digest is a verifier rejection, not replay.
try:
    request("POST", path, losing_body, bearer=state["chiefToken"], headers=losing_headers)
    raise AssertionError("changed losing founder answer unexpectedly replayed")
except ApiError as exc:
    assert exc.status == 403, exc

replayed = request(
    "POST", path, winning_body, bearer=state["chiefToken"], headers=winning_headers
)
assert replayed.get("nixFounderRelay", {}).get("replayed") is True, replayed
time.sleep(1)
replayed_runs = request("GET", f"/api/issues/{issue['id']}/runs")
assert {row["runId"] for row in replayed_runs} == {row["runId"] for row in after_runs}
replayed_activity = request("GET", f"/api/issues/{issue['id']}/activity")
assert sum(row.get("action") == "issue.founder_relay_reserved" for row in replayed_activity) == 1
assert sum(row.get("action") == "issue.thread_interaction_answered" for row in replayed_activity) == 1

# Preserve the Slice 2 Chief decision path under the same immutable-origin
# rules. This source run represents the bounded Hermes Paperclip attribution;
# Board cannot answer directly, while the signed Chief relay answers as Lior
# and wakes the exact Chief origin rather than a generic/current employee.
chief_issue = request("GET", f"/api/issues/{authority['chiefIssueId']}")
assert chief_issue.get("assigneeAgentId") == state["chiefId"], chief_issue
chief_interaction = request(
    "POST",
    f"/api/issues/{chief_issue['id']}/interactions",
    {
        "kind": "ask_user_questions",
        "idempotencyKey": "chief-founder-route-fixture",
        "sourceRunId": authority["chiefRunId"],
        "resolverPolicy": "human_only",
        "addresseeUserId": state["founderId"],
        "continuationPolicy": "wake_assignee",
        "title": "Chief founder relay fixture",
        "payload": {
            "version": 1,
            "title": "Chief asks for a founder decision",
            "questions": [{
                "id": "direction",
                "prompt": "Choose the Chief direction",
                "selectionMode": "single",
                "required": True,
                "options": [
                    {"id": "approve", "label": "Approve"},
                    {"id": "reject", "label": "Reject"},
                ],
            }],
        },
    },
)
chief_path = (
    f"/api/issues/{chief_issue['id']}/interactions/"
    f"{chief_interaction['id']}/respond"
)
chief_body, chief_headers = signed_relay(
    chief_path, "approve", "5252", "telegram:chief:5252"
)
chief_before_runs = request("GET", f"/api/issues/{chief_issue['id']}/runs")
chief_before_activity = request("GET", f"/api/issues/{chief_issue['id']}/activity")
try:
    request("POST", chief_path, chief_body)
    raise AssertionError("headerless Board response passed the Chief founder relay gate")
except ApiError as exc:
    assert exc.status == 403, exc
    assert json.loads(exc.detail) == {"error": "nix_founder_relay_required"}, exc.detail
time.sleep(0.25)
chief_headerless_runs = request("GET", f"/api/issues/{chief_issue['id']}/runs")
chief_headerless_activity = request("GET", f"/api/issues/{chief_issue['id']}/activity")
assert {row["runId"] for row in chief_headerless_runs} == {
    row["runId"] for row in chief_before_runs
}, chief_headerless_runs
assert {row["id"] for row in chief_headerless_activity} == {
    row["id"] for row in chief_before_activity
}, chief_headerless_activity

chief_initial_replay = False
try:
    chief_answered = request(
        "POST",
        chief_path,
        chief_body,
        bearer=state["chiefToken"],
        headers=chief_headers,
    )
except ApiError as exc:
    assert exc.status == 503, exc
    assert json.loads(exc.detail) == {
        "error": "nix_founder_relay_continuation_pending"
    }, exc.detail
    chief_initial_replay = True
    deadline = time.time() + 30
    chief_answered = None
    while time.time() < deadline:
        try:
            chief_answered = request(
                "POST",
                chief_path,
                chief_body,
                bearer=state["chiefToken"],
                headers=chief_headers,
            )
            break
        except ApiError as retry_exc:
            assert retry_exc.status == 503, retry_exc
            assert json.loads(retry_exc.detail) == {
                "error": "nix_founder_relay_continuation_pending"
            }, retry_exc.detail
            time.sleep(0.5)
    assert chief_answered is not None, "Chief continuation did not become provable"
chief_relay = chief_answered.get("nixFounderRelay", {})
assert chief_answered.get("status") == "answered", chief_answered
assert chief_answered.get("resolvedByUserId") == state["founderId"], chief_answered
assert chief_relay.get("verified") is True, chief_relay
assert chief_relay.get("originAgentId") == state["chiefId"], chief_relay
assert chief_relay.get("resumedAgentId") == state["chiefId"], chief_relay
assert chief_relay.get("replayed") is chief_initial_replay, chief_relay

chief_before_ids = {row["runId"] for row in chief_before_runs}
deadline = time.time() + 30
chief_after_runs = []
while time.time() < deadline:
    chief_after_runs = request("GET", f"/api/issues/{chief_issue['id']}/runs")
    if len({row["runId"] for row in chief_after_runs} - chief_before_ids) == 1:
        break
    time.sleep(0.5)
chief_new_runs = [
    row for row in chief_after_runs if row["runId"] not in chief_before_ids
]
assert len(chief_new_runs) == 1, [row.get("runId") for row in chief_new_runs]
chief_resumed = request("GET", f"/api/heartbeat-runs/{chief_new_runs[0]['runId']}")
assert chief_resumed.get("agentId") == state["chiefId"], chief_resumed
chief_snapshot = chief_resumed.get("contextSnapshot") or {}
assert chief_snapshot.get("interactionId") == chief_interaction["id"], chief_snapshot
assert chief_snapshot.get("sourceRunId") == authority["chiefRunId"], chief_snapshot
# The immediate answer dispatch and the periodic continuation repair are both
# valid upstream paths.  What matters here is that exactly the immutable Chief
# origin is resumed for this answered interaction, which the assertions above
# prove; do not make the integration test race those two schedulers.
assert chief_snapshot.get("wakeReason") in {
    "issue_commented",
    "issue_continuation_needed",
}, chief_snapshot
chief_activity = request("GET", f"/api/issues/{chief_issue['id']}/activity")
chief_reservations = [
    row for row in chief_activity
    if row.get("action") == "issue.founder_relay_reserved"
]
chief_answers = [
    row for row in chief_activity
    if row.get("action") == "issue.thread_interaction_answered"
]
assert len(chief_reservations) == 1, chief_activity
assert len(chief_answers) == 1, chief_activity
chief_answer_relay = (
    (chief_answers[0].get("details") or {}).get("nixFounderRelay") or {}
)
assert chief_answer_relay.get("originAgentId") == state["chiefId"], chief_answer_relay
assert chief_answer_relay.get("resumedAgentId") is None, chief_answer_relay
assert chief_answer_relay.get("continuationStatus") == "pending", chief_answer_relay

PY

# The fixed value is a test sentinel, not a credential. It must never survive
# the real HTTP logger, while the header itself must remain visible as redacted
# evidence that this assertion did not merely miss the request.
"${compose[@]}" logs --no-color paperclip >"$paperclip_logs"
if grep -Fq "$signature_sentinel" "$paperclip_logs"; then
  fail "founder relay signature sentinel leaked into Paperclip logs"
fi
grep -Fq '"x-nix-founder-relay-signature":"[Redacted]"' "$paperclip_logs" \
  || fail "Paperclip logs did not contain redacted founder relay signature evidence"
printf 'paperclip specialist full-stack integration: ok\n'
