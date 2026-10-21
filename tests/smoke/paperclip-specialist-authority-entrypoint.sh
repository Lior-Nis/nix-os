#!/bin/sh
set -eu

if [ "${NIX_TEST_AUTHORITY_ONLY:-false}" != true ]; then
  exec /opt/nix/paperclip-entrypoint.sh "$@"
fi

python3 /opt/nix/patch-specialist-runtime.py
python3 /opt/nix/patch-specialist-runtime.py --verify

if [ "$#" -eq 0 ]; then
  set -- node --import ./server/node_modules/tsx/dist/loader.mjs server/dist/index.js
fi
exec /usr/bin/tini -- /usr/local/bin/docker-entrypoint.sh "$@"
