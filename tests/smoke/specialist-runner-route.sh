#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
test_dir=$(mktemp -d /tmp/nix-specialist-runner-route.XXXXXX)
trap 'rm -rf "$test_dir"' EXIT
mkdir -p "$test_dir/bin"

cat >"$test_dir/test.env" <<'EOF'
COMPOSE_PROJECT_NAME=nix-os-test
PAPERCLIP_PUBLIC_URL=https://nix-os.test-tailnet.ts.net
PAPERCLIP_RUNNER_PUBLIC_URL=wss://nix-os.test-tailnet.ts.net
EOF

cat >"$test_dir/bin/sudo" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ ${1:-} != -- ]] || shift
exec "$@"
EOF

cat >"$test_dir/bin/tailscale" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ ${1:-} == ip && ${2:-} == -4 ]]
cat "$FAKE_TAIL_IP_FILE"
EOF

cat >"$test_dir/bin/docker" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

if [[ ${1:-} == compose ]]; then
  shift
  [[ ${1:-} == --env-file ]]
  shift 2
  if [[ ${1:-} == ps && ${2:-} == --status && ${3:-} == running && ${4:-} == -q && ${5:-} == specialist-worker ]]; then
    [[ ${FAKE_WORKER_RUNNING:-1} == 1 ]] && printf '%s\n' worker123
    exit 0
  fi
  if [[ ${1:-} == exec ]]; then
    [[ " $* " == *' specialist-worker node -e '* ]]
    [[ ${*: -1} == https://nix-os.test-tailnet.ts.net/api/health ]]
    printf 'probe\n' >>"$FAKE_PROBE_LOG"
    exit 0
  fi
elif [[ ${1:-} == inspect && ${2:-} == worker123 ]]; then
  cat <<JSON
[{"Config":{"Labels":{"com.docker.compose.project":"nix-os-test","com.docker.compose.service":"specialist-worker"}},"NetworkSettings":{"Networks":{"nix-os-test_specialist_egress":{}}}}]
JSON
  exit 0
elif [[ ${1:-} == network && ${2:-} == inspect && ${3:-} == nix-os-test_specialist_egress ]]; then
  extra=''
  if [[ ${FAKE_EXTRA_CONTAINER:-0} == 1 ]]; then
    extra=',"other456":{"Name":"foreign"}'
  fi
  cat <<JSON
[{"Driver":"bridge","Internal":false,"Labels":{"com.docker.compose.project":"nix-os-test","com.docker.compose.network":"specialist_egress"},"IPAM":{"Config":[{"Subnet":"172.25.0.0/16"}]},"Containers":{"worker123":{"Name":"worker","IPv4Address":"${FAKE_WORKER_IPV4:-172.25.0.2/16}"}${extra}}}]
JSON
  exit 0
fi

printf 'unexpected fake docker invocation: %s\n' "$*" >&2
exit 1
EOF

cat >"$test_dir/bin/ufw" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

if [[ ${1:-} == status && ${2:-} == numbered ]]; then
  if [[ ${FAKE_UFW_ACTIVE:-1} == 0 ]]; then
    printf 'Status: inactive\n'
    exit 0
  fi
  printf 'Status: active\n\n'
  awk '{ printf "[ %d] %s\n", NR, $0 }' "$FAKE_UFW_STATE"
  exit 0
fi

printf '%s\n' "$*" >>"$FAKE_UFW_LOG"
if [[ ${1:-} == --force && ${2:-} == delete && ${3:-} =~ ^[0-9]+$ ]]; then
  awk -v target="$3" 'NR != target' "$FAKE_UFW_STATE" >"$FAKE_UFW_STATE.next"
  mv "$FAKE_UFW_STATE.next" "$FAKE_UFW_STATE"
  exit 0
fi

if [[ ${1:-} == allow ]]; then
  source=''
  destination=''
  comment=''
  while (( $# > 0 )); do
    case "$1" in
      from) source=${2:-}; shift 2 ;;
      to) destination=${2:-}; shift 2 ;;
      comment) comment=${2:-}; shift 2 ;;
      *) shift ;;
    esac
  done
  [[ -n "$source" && -n "$destination" && -n "$comment" ]]
  printf '%s 443/tcp ALLOW IN %s # %s\n' "$destination" "$source" "$comment" \
    >>"$FAKE_UFW_STATE"
  exit 0
fi

printf 'unexpected fake ufw invocation: %s\n' "$*" >&2
exit 1
EOF

chmod +x "$test_dir/bin/docker" "$test_dir/bin/sudo" "$test_dir/bin/tailscale" "$test_dir/bin/ufw"
printf '%s\n' '100.82.50.51' >"$test_dir/tail-ip"
cat >"$test_dir/ufw-state" <<'EOF'
22/tcp ALLOW IN Anywhere # foreign ssh rule
100.82.50.51 443/tcp ALLOW IN 172.25.0.0/16 # nix-os nix-os-test specialist runner
8443/tcp ALLOW IN Anywhere # foreign application rule
EOF
: >"$test_dir/ufw-log"
: >"$test_dir/probe-log"

export PATH="$test_dir/bin:$PATH"
export FAKE_TAIL_IP_FILE="$test_dir/tail-ip"
export FAKE_UFW_STATE="$test_dir/ufw-state"
export FAKE_UFW_LOG="$test_dir/ufw-log"
export FAKE_PROBE_LOG="$test_dir/probe-log"
route="$repo_root/scripts/configure-specialist-runner-route"

if ! FAKE_WORKER_RUNNING=0 "$route" converge-if-running "$test_dir/test.env" \
  | grep -Fq 'not required because specialist-worker is not running'; then
  printf 'pre-specialist conditional convergence did not pass cleanly\n' >&2
  exit 1
fi
[[ ! -s "$test_dir/ufw-log" && ! -s "$test_dir/probe-log" ]]

if ! FAKE_UFW_ACTIVE=0 "$route" converge "$test_dir/test.env" \
  | grep -Fq 'no firewall rule was required or changed'; then
  printf 'inactive UFW path did not pass through the real worker probe\n' >&2
  exit 1
fi
[[ ! -s "$test_dir/ufw-log" ]]
[[ $(wc -l <"$test_dir/probe-log" | tr -d ' ') == 1 ]]
: >"$test_dir/probe-log"

"$route" converge "$test_dir/test.env" >/dev/null
grep -Fxq '22/tcp ALLOW IN Anywhere # foreign ssh rule' "$test_dir/ufw-state"
grep -Fxq '8443/tcp ALLOW IN Anywhere # foreign application rule' "$test_dir/ufw-state"
[[ $(grep -Fc '# nix-os nix-os-test specialist runner' "$test_dir/ufw-state") == 1 ]]
grep -Fxq '100.82.50.51 443/tcp ALLOW IN 172.25.0.2 # nix-os nix-os-test specialist runner' \
  "$test_dir/ufw-state"
[[ $(wc -l <"$test_dir/probe-log" | tr -d ' ') == 1 ]]

mutation_count=$(wc -l <"$test_dir/ufw-log" | tr -d ' ')
"$route" converge "$test_dir/test.env" >/dev/null
"$route" verify "$test_dir/test.env" >/dev/null
[[ $(wc -l <"$test_dir/ufw-log" | tr -d ' ') == "$mutation_count" ]]
[[ $(wc -l <"$test_dir/probe-log" | tr -d ' ') == 3 ]]

cat >>"$test_dir/ufw-state" <<'EOF'
100.82.50.51 443/tcp ALLOW IN 172.25.0.2 # nix-os nix-os-test specialist runner
EOF
if "$route" verify "$test_dir/test.env" >/dev/null 2>&1; then
  printf 'duplicate owned UFW rule unexpectedly passed verification\n' >&2
  exit 1
fi
"$route" converge "$test_dir/test.env" >/dev/null
[[ $(grep -Fc '# nix-os nix-os-test specialist runner' "$test_dir/ufw-state") == 1 ]]

printf '%s\n' '100.82.50.99' >"$test_dir/tail-ip"
"$route" converge "$test_dir/test.env" >/dev/null
grep -Fxq '100.82.50.99 443/tcp ALLOW IN 172.25.0.2 # nix-os nix-os-test specialist runner' \
  "$test_dir/ufw-state"
[[ $(grep -Fc '# nix-os nix-os-test specialist runner' "$test_dir/ufw-state") == 1 ]]

if FAKE_EXTRA_CONTAINER=1 "$route" converge "$test_dir/test.env" >/dev/null 2>&1; then
  printf 'shared specialist egress network unexpectedly passed verification\n' >&2
  exit 1
fi
if FAKE_WORKER_IPV4=172.26.0.2/16 "$route" converge "$test_dir/test.env" >/dev/null 2>&1; then
  printf 'out-of-subnet specialist worker address unexpectedly passed verification\n' >&2
  exit 1
fi

printf 'Specialist runner route ownership and recovery tests passed.\n'
