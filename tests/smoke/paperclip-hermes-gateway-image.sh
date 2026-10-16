#!/usr/bin/env bash
set -euo pipefail
umask 077

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
hermes_image='nousresearch/hermes-agent:v2026.9.14@sha256:99641e57ec762c59e54cb44aa6746b7fc68c18b3c5ddb088af54234c613d9294'
paperclip_image='ghcr.io/paperclipai/paperclip:2026.916.1@sha256:a02ac35ac41df911af477422ea0e781cf41d2b2c600c66f0a5ac9d8c63f52c2c'
suffix=$(openssl rand -hex 8)
container="nix-hermes-gateway-$suffix"
network="nix-hermes-gateway-$suffix"
volume="nix-hermes-gateway-$suffix"
brain_volume="nix-hermes-gateway-brain-$suffix"
mode_dir="/tmp/${container}-mode"
mode_file="$mode_dir/mode.env"
api_key=$(openssl rand -hex 32)
decision_webhook_secret=$(openssl rand -hex 32)
brain_gid=12345

cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
  docker volume rm "$volume" >/dev/null 2>&1 || true
  docker volume rm "$brain_volume" >/dev/null 2>&1 || true
  rm -rf "$mode_dir"
}
trap cleanup EXIT

mkdir -m 0700 "$mode_dir"
docker run --rm --volume "$mode_dir:/out" --entrypoint sh "$hermes_image" -ec '
  printf "HERMES_TELEGRAM_MODE=disabled\n" > /out/mode.env
  chmod 0600 /out/mode.env
'
docker network create "$network" >/dev/null
docker volume create "$volume" >/dev/null
docker volume create "$brain_volume" >/dev/null
docker run --rm --volume "$volume:/state" --entrypoint sh "$hermes_image" -ec '
  chown -R 10000:10000 /state
  chmod 0700 /state
'
docker run --rm --user 10000:10000 --volume "$volume:/opt/data" --entrypoint sh "$hermes_image" -ec '
  mkdir -p /opt/data/logs/gateways /opt/data/memories /opt/data/sessions /opt/data/state
'
docker run --rm --volume "$brain_volume:/brain" --entrypoint sh "$hermes_image" -ec '
  git -C /brain init -q
  printf "# Restricted brain fixture\n" > /brain/README.md
  git -C /brain add README.md
  chgrp -R 12345 /brain
  chmod -R g+rX,o-rwx /brain
'

docker run -d --name "$container" --network "$network" --entrypoint /bin/sh \
  --group-add "$brain_gid" --volume "$volume:/opt/data" \
  --volume "$repo_root/deploy/hermes/entrypoint.sh:/opt/nix/entrypoint.sh:ro" \
  --volume "$repo_root/deploy/hermes/startup-boundary.py:/opt/nix/startup-boundary.py:ro" \
  --volume "$repo_root/deploy/hermes/patch-run-attribution.py:/opt/nix/patch-run-attribution.py:ro" \
  --volume "$mode_file:/run/nix/hermes-telegram-mode.env:ro" \
  --volume "$repo_root/deploy/hermes/config.yaml:/opt/data/config.yaml:ro" \
  --volume "$repo_root/deploy/hermes/SOUL.md:/opt/data/SOUL.md:ro" \
  --volume "$repo_root/deploy/hermes/validate-tool-boundary.py:/opt/nix/validate-tool-boundary.py:ro" \
  --volume "$repo_root/deploy/hermes/run-scoped-paperclip-mcp.py:/opt/nix/run-scoped-paperclip-mcp.py:ro" \
  --volume "$repo_root/deploy/hermes/paperclip_question_delivery.py:/opt/nix/paperclip_question_delivery.py:ro" \
  --volume "$brain_volume:/workspace/nix-brain:ro" \
  --env API_SERVER_ENABLED=true --env API_SERVER_HOST=0.0.0.0 --env API_SERVER_PORT=8642 \
  --env API_SERVER_KEY="$api_key" --env HERMES_GATEWAY_BOOTSTRAP_STATE=running \
  --env HERMES_DECISION_WEBHOOK_SECRET="$decision_webhook_secret" \
  --env WEBHOOK_ENABLED=true --env WEBHOOK_SECRET="$decision_webhook_secret" \
  --env TELEGRAM_BOT_TOKEN=nix-disabled-token-canary \
  --env TELEGRAM_ALLOWED_USERS=123456789 --env TELEGRAM_HOME_CHANNEL=123456789 \
  --env TELEGRAM_ALLOW_ALL_USERS=false --env GATEWAY_ALLOW_ALL_USERS=false \
  --env HERMES_WRITE_SAFE_ROOT=/opt/data/memories --env "NIX_BRAIN_GID=$brain_gid" \
  --env PAPERCLIP_API_KEY=pcp_gateway_fixture --env PAPERCLIP_COMPANY_ID=contract-company \
  --env PAPERCLIP_AGENT_ID=contract-agent --env PAPERCLIP_LIOR_USER_ID=lior-contract-user \
  "$hermes_image" /opt/nix/entrypoint.sh gateway run >/dev/null

for _ in $(seq 1 120); do
  if docker exec --user 10000:10000 "$container" curl -fsS http://127.0.0.1:8642/health >/dev/null 2>&1; then
    break
  fi
  [[ $(docker inspect -f '{{.State.Running}}' "$container") == true ]] \
    || { docker logs "$container" >&2; exit 1; }
  sleep 1
done
docker exec --user 10000:10000 "$container" curl -fsS http://127.0.0.1:8642/health >/dev/null

company_id='11111111-1111-4111-8111-111111111111'
agent_id='22222222-2222-4222-8222-222222222222'
run_a='33333333-3333-4333-8333-333333333333'
issue_a='44444444-4444-4444-8444-444444444444'
run_b='55555555-5555-4555-8555-555555555555'
issue_b='66666666-6666-4666-8666-666666666666'

run_adapter() {
  docker run --rm --network "$network" --entrypoint sh \
    --volume "$repo_root/tests/smoke/paperclip-hermes-gateway-runner.mjs:/tmp/nix-gateway-runner.mjs:ro" \
    --env HERMES_API_BASE_URL="http://${container}:8642" --env HERMES_API_KEY="$api_key" \
    --env PAPERCLIP_COMPANY_ID="$company_id" --env PAPERCLIP_AGENT_ID="$agent_id" \
    "$@" "$paperclip_image" -ec '
      /app/packages/shared/node_modules/.bin/tsc \
        -p /app/packages/shared/tsconfig.json
      /app/packages/adapter-utils/node_modules/.bin/tsc \
        -p /app/packages/adapter-utils/tsconfig.json
      /app/packages/adapters/hermes/node_modules/.bin/tsc \
        -p /app/packages/adapters/hermes/tsconfig.json
      node -e '\''
        const fs = require("node:fs");
        for (const name of ["shared", "adapter-utils"]) {
          const path = `/app/packages/${name}/package.json`;
          const pkg = JSON.parse(fs.readFileSync(path, "utf8"));
          pkg.exports = pkg.publishConfig.exports;
          pkg.main = pkg.publishConfig.main;
          fs.writeFileSync(path, `${JSON.stringify(pkg)}\n`);
        }
      '\''
      node /tmp/nix-gateway-runner.mjs
    '
}

first=$(run_adapter --env PAPERCLIP_RUN_ID="$run_a" --env PAPERCLIP_ISSUE_ID="$issue_a")
first_hermes_run=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["hermesRunId"])' <<<"$first")
first_session_digest=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["sessionDigest"])' <<<"$first")

replay=$(run_adapter --env PAPERCLIP_RUN_ID="$run_a" --env PAPERCLIP_ISSUE_ID="$issue_a" \
  --env EXPECT_HERMES_RUN_ID="$first_hermes_run")
[[ $(python3 -c 'import json,sys; print(json.load(sys.stdin)["hermesRunId"])' <<<"$replay") == "$first_hermes_run" ]]

poll=$(run_adapter --env PAPERCLIP_RUN_ID="$run_b" --env PAPERCLIP_ISSUE_ID="$issue_b" --env FORCE_POLL=1)
poll_hermes_run=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["hermesRunId"])' <<<"$poll")
poll_session_digest=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["sessionDigest"])' <<<"$poll")
[[ "$poll_hermes_run" != "$first_hermes_run" ]]
[[ "$poll_session_digest" != "$first_session_digest" ]]

conflict=$(run_adapter --env PAPERCLIP_RUN_ID="$run_a" --env PAPERCLIP_ISSUE_ID="$issue_b" --env EXPECT_CONFLICT=1)
[[ $(python3 -c 'import json,sys; print(json.load(sys.stdin)["kind"])' <<<"$conflict") == conflict ]]

docker restart "$container" >/dev/null
for _ in $(seq 1 120); do
  if docker exec --user 10000:10000 "$container" curl -fsS http://127.0.0.1:8642/health >/dev/null 2>&1; then
    break
  fi
  [[ $(docker inspect -f '{{.State.Running}}' "$container") == true ]] \
    || { docker logs "$container" >&2; exit 1; }
  sleep 1
done
docker exec --user 10000:10000 "$container" curl -fsS http://127.0.0.1:8642/health >/dev/null
restart_replay=$(run_adapter --env PAPERCLIP_RUN_ID="$run_a" --env PAPERCLIP_ISSUE_ID="$issue_a" \
  --env EXPECT_HERMES_RUN_ID="$first_hermes_run")
[[ $(python3 -c 'import json,sys; print(json.load(sys.stdin)["hermesRunId"])' <<<"$restart_replay") == "$first_hermes_run" ]]

printf 'Pinned Paperclip hermes_gateway adapter and pinned Hermes provider-failure admission contract passed.\n'
