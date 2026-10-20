#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
image='ghcr.io/paperclipai/paperclip:2026.916.1@sha256:a02ac35ac41df911af477422ea0e781cf41d2b2c600c66f0a5ac9d8c63f52c2c'
worker_image="nix-specialist-provider-pack-worker:test-$$"

python3 "$repo_root/tests/smoke/paperclip-specialist-patch.py"

docker run --rm --entrypoint sh \
  -v "$repo_root/deploy/paperclip/patch-specialist-runtime.py:/opt/nix/patch-specialist-runtime.py:ro" \
  -v "$repo_root/tests/smoke/paperclip-specialist-runtime.mjs:/opt/nix/paperclip-specialist-runtime.mjs:ro" \
  "$image" -ec '
    python3 /opt/nix/patch-specialist-runtime.py
    python3 /opt/nix/patch-specialist-runtime.py --verify
    python3 /opt/nix/patch-specialist-runtime.py
    node --check /app/server/dist/routes/issues.js
    node --check /app/server/dist/services/native-runtime/paperclip-runner-tool-authority.js
    node --check /app/packages/paperclip-runner/dist/control-plane/durable-prp-control-plane.js
    node --check /app/server/dist/vendor/paperclip-runner/control-plane/durable-prp-control-plane.js
    node --check /app/packages/paperclip-runner/dist/drivers/opencode/opencode-server-driver.js
    node --check /app/server/dist/vendor/paperclip-runner/drivers/opencode/opencode-server-driver.js
    node --check /app/packages/paperclip-runner/dist/cli/opencode-app-server-proxy.cjs
    node --check /app/packages/paperclip-runner/dist/cli/opencode-app-server-proxy.js
    node --check /app/server/dist/vendor/paperclip-runner/cli/opencode-app-server-proxy.cjs
    node --check /app/server/dist/vendor/paperclip-runner/cli/opencode-app-server-proxy.js
    node /app/cli/node_modules/tsx/dist/cli.mjs /opt/nix/paperclip-specialist-runtime.mjs
    cd /app
    pnpm --filter @paperclipai/server exec tsc --noEmit --pretty false
  '

cache_volume="nix-paperclip-specialist-smoke-$$"
docker volume create "$cache_volume" >/dev/null
trap 'docker volume rm -f "$cache_volume" >/dev/null 2>&1 || true; docker image rm -f "$worker_image" >/dev/null 2>&1 || true' EXIT
entrypoint_args=(
  --rm
  --entrypoint /opt/nix/paperclip-entrypoint.sh
  -v "$repo_root/deploy/paperclip/entrypoint.sh:/opt/nix/paperclip-entrypoint.sh:ro"
  -v "$repo_root/deploy/paperclip/patch-specialist-runtime.py:/opt/nix/patch-specialist-runtime.py:ro"
  -v "$cache_volume:/runner-cache"
  "$image"
  true
)
docker run "${entrypoint_args[@]}"
# A matching marker verifies and reuses the provider pack without rebuilding.
docker run "${entrypoint_args[@]}"

# SSH transports cannot upload a provider directory. The worker mounts this
# reconstructible cache read-only and must be able to read every pack artifact
# as its unprivileged uid.
docker run --rm --entrypoint sh --user 10001:10001 \
  -v "$cache_volume:/runner-cache:ro" "$image" -ec '
    test -r /runner-cache/nix-specialist-provider-pack/provider-pack.json
    test -x /runner-cache/nix-specialist-provider-pack/node_modules/.bin/opencode
    test -z "$(find /runner-cache/nix-specialist-provider-pack -type f ! -readable -print -quit)"
    ! printf tamper >> /runner-cache/nix-specialist-provider-pack/provider-pack.json
  '

docker build --quiet --tag "$worker_image" "$repo_root/deploy/specialist-worker" >/dev/null
docker run --rm --read-only --entrypoint sh --user 10001:10001 \
  --tmpfs /tmp:mode=1777,size=256m \
  --tmpfs /home/worker/.config:uid=10001,gid=10001,mode=0700,size=16m \
  --tmpfs /home/worker/.cache:uid=10001,gid=10001,mode=0700,size=512m \
  --tmpfs /home/worker/.local:uid=10001,gid=10001,mode=0700,size=256m \
  -v "$cache_volume:/runner-cache:ro" "$worker_image" -ec '
    pack=/opt/paperclip-runner/provider-pack
    test -r "$pack/provider-pack.json"
    test "$("$pack/node_modules/.bin/opencode" --version)" = 1.18.29
    ! printf tamper >> "$pack/provider-pack.json"
  '

docker run --rm --entrypoint sh -v "$cache_volume:/runner-cache" "$image" -ec \
  'printf "tamper" >> /runner-cache/nix-specialist-provider-pack/dist/drivers/opencode/opencode-server-driver.js'
if docker run "${entrypoint_args[@]}" >/dev/null 2>&1; then
  echo 'tampered marked provider pack did not fail closed' >&2
  exit 1
fi

echo 'paperclip specialist pinned-image smoke: ok'
