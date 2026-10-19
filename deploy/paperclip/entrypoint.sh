#!/bin/sh
set -eu

provider_pack=/runner-cache/nix-specialist-provider-pack
patcher=/opt/nix/patch-specialist-runtime.py

# Patch both reviewable TypeScript and the compiled JavaScript that the pinned
# production image executes. Unknown or partially patched bytes refuse startup.
python3 "$patcher"
python3 "$patcher" --verify

# Each ephemeral sandbox run receives this provider pack. Rebuild only when the exact Nix
# patch marker is absent/stale. Once the marker matches, corruption or manifest
# drift fails closed rather than being hidden by an automatic rebuild.
if python3 "$patcher" --provider-pack "$provider_pack" --marker-matches; then
  python3 "$patcher" --provider-pack "$provider_pack" --verify-provider-pack
else
  # Upstream publishes the pack with an atomic rename. Keep its temporary
  # directory on the cache volume so the rename cannot cross filesystems.
  TMPDIR=/runner-cache \
    PAPERCLIP_RUNNER_SOURCE_REVISION=d554c4789ed3930f8a53ac9fdf6503b3187097da \
    node /app/packages/paperclip-runner/scripts/build-provider-pack.mjs "$provider_pack"
  python3 "$patcher" --provider-pack "$provider_pack" --stamp-provider-pack
  python3 "$patcher" --provider-pack "$provider_pack" --verify-provider-pack
fi

# The image starts as root and later drops to the configured node UID/GID.
# This pack is reconstructible code, not a credential. Make it readable through
# the worker's read-only cache mount so the SSH transport can use the exact
# manifest-matched artifact without receiving cache write access.
if [ "$(id -u)" -eq 0 ]; then
  chown -R "${USER_UID:-1000}:${USER_GID:-1000}" "$provider_pack"
  chmod -R a+rX "$provider_pack"
fi

# Compose does not reliably retain an image CMD when the entrypoint is
# replaced across every supported invocation path. Preserve the pinned
# image's exact server command when no explicit command was supplied.
if [ "$#" -eq 0 ]; then
  set -- node --import ./server/node_modules/tsx/dist/loader.mjs server/dist/index.js
fi

exec /usr/bin/tini -- /usr/local/bin/docker-entrypoint.sh "$@"
