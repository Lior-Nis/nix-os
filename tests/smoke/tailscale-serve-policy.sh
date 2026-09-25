#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
validator="$repo_root/scripts/check-tailscale-serve-state"
fixtures="$repo_root/tests/fixtures/tailscale-serve"
fqdn='nix-os.tail1234.ts.net'
target='http://127.0.0.1:3100'

"$validator" --expect empty "$fixtures/empty.json" >/dev/null
"$validator" --expect inspect "$fixtures/allow-funnel.json" >/dev/null
"$validator" --expect paperclip --fqdn "$fqdn" --target "$target" "$fixtures/valid.json" >/dev/null

for invalid_fixture in allow-funnel unexpected-handler unexpected-port unexpected-target foreground-funnel unexpected-service allow-funnel-false; do
  if "$validator" --expect paperclip --fqdn "$fqdn" --target "$target" \
    "$fixtures/${invalid_fixture}.json" >/dev/null 2>&1; then
    printf 'invalid Tailscale fixture unexpectedly passed: %s\n' "$invalid_fixture" >&2
    exit 1
  fi
done

printf 'Tailscale Serve/Funnel status policy fixtures passed.\n'
