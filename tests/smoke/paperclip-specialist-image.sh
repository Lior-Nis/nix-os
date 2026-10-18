#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
image='ghcr.io/paperclipai/paperclip:2026.916.1@sha256:a02ac35ac41df911af477422ea0e781cf41d2b2c600c66f0a5ac9d8c63f52c2c'

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
    node --check /app/packages/paperclip-runner/dist/drivers/opencode/opencode-server-driver.js
    node /app/cli/node_modules/tsx/dist/cli.mjs /opt/nix/paperclip-specialist-runtime.mjs
    cd /app
    pnpm --filter @paperclipai/server exec tsc --noEmit --pretty false
  '

cache_volume="nix-paperclip-specialist-smoke-$$"
docker volume create "$cache_volume" >/dev/null
trap 'docker volume rm -f "$cache_volume" >/dev/null 2>&1 || true' EXIT
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

docker run --rm --entrypoint sh -v "$cache_volume:/runner-cache" "$image" -ec \
  'printf "tamper" >> /runner-cache/nix-specialist-provider-pack/dist/drivers/opencode/opencode-server-driver.js'
if docker run "${entrypoint_args[@]}" >/dev/null 2>&1; then
  echo 'tampered marked provider pack did not fail closed' >&2
  exit 1
fi

echo 'paperclip specialist pinned-image smoke: ok'
