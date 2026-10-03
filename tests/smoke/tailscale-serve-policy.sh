#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
validator="$repo_root/scripts/check-tailscale-serve-state"
fixtures="$repo_root/tests/fixtures/tailscale-serve"
fqdn='nix-os.tail1234.ts.net'
target='http://127.0.0.1:3100'

"$validator" --expect empty "$fixtures/empty.json" >/dev/null
"$validator" --expect inspect "$fixtures/allow-funnel.json" >/dev/null
for valid_fixture in valid unexpected-handler foreground-funnel unexpected-service coexistence-after; do
  "$validator" --expect paperclip --fqdn "$fqdn" --target "$target" \
    "$fixtures/${valid_fixture}.json" >/dev/null
done

for invalid_fixture in allow-funnel allow-funnel-false foreground-paperclip-funnel unexpected-port unexpected-target; do
  if "$validator" --expect paperclip --fqdn "$fqdn" --target "$target" \
    "$fixtures/${invalid_fixture}.json" >/dev/null 2>&1; then
    printf 'invalid Tailscale fixture unexpectedly passed: %s\n' "$invalid_fixture" >&2
    exit 1
  fi
done

"$validator" --expect preserved --fqdn "$fqdn" \
  --before "$fixtures/coexistence-before.json" "$fixtures/coexistence-after.json" >/dev/null

for clobbered_fixture in coexistence-clobbered coexistence-modified-handler; do
  if "$validator" --expect preserved --fqdn "$fqdn" \
    --before "$fixtures/coexistence-before.json" \
    "$fixtures/${clobbered_fixture}.json" >/dev/null 2>&1; then
    printf 'clobbered Tailscale fixture unexpectedly passed: %s\n' "$clobbered_fixture" >&2
    exit 1
  fi
done

printf 'Tailscale endpoint ownership and preservation fixtures passed.\n'
