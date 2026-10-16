#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
image='nousresearch/hermes-agent:v2026.9.14@sha256:99641e57ec762c59e54cb44aa6746b7fc68c18b3c5ddb088af54234c613d9294'

docker run --rm --entrypoint sh \
  --volume "$repo_root/deploy/hermes/patch-run-attribution.py:/opt/nix/patch-run-attribution.py:ro" \
  --volume "$repo_root/tests/smoke/hermes-run-attribution-image.py:/opt/nix/hermes-run-attribution-image.py:ro" \
  "$image" -ec '
    python3 /opt/nix/patch-run-attribution.py
    python3 /opt/nix/patch-run-attribution.py --verify
    cd /opt/hermes
    python3 /opt/nix/hermes-run-attribution-image.py
  '
