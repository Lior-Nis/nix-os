#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
test_dir=$(mktemp -d /tmp/nix-specialist-worker.XXXXXX)
container="nix-specialist-worker-test-$$"
network="nix-specialist-worker-test-$$"
volume="nix_specialist_worker_test_$$"
image="nix-specialist-worker:test-$$"

cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
  docker volume rm "$volume" >/dev/null 2>&1 || true
  rm -rf "$test_dir"
}
trap cleanup EXIT

ssh-keygen -q -t ed25519 -N '' -C test-host -f "$test_dir/host"
ssh-keygen -q -t ed25519 -N '' -C test-client -f "$test_dir/client"
{ printf 'restrict '; cat "$test_dir/client.pub"; } >"$test_dir/authorized_keys"
printf '[%s]:2222 %s\n' "$container" "$(cat "$test_dir/host.pub")" >"$test_dir/known_hosts"
chmod 0600 "$test_dir/host" "$test_dir/client" "$test_dir/authorized_keys" "$test_dir/known_hosts"

docker build --pull --tag "$image" "$repo_root/deploy/specialist-worker"
docker network create --internal "$network" >/dev/null
docker volume create "$volume" >/dev/null
docker run -d --name "$container" \
  --network "$network" \
  --read-only \
  --init \
  --pids-limit 256 \
  --cpus 1 \
  --memory 2g \
  --cap-drop ALL \
  --cap-add CHOWN \
  --cap-add DAC_OVERRIDE \
  --cap-add KILL \
  --cap-add SETGID \
  --cap-add SETUID \
  --cap-add SYS_CHROOT \
  --security-opt no-new-privileges:true \
  --mount "type=volume,source=$volume,target=/workspaces" \
  --mount "type=bind,source=$test_dir/host,target=/run/secrets/specialist_host_key,readonly" \
  --mount "type=bind,source=$test_dir/authorized_keys,target=/run/secrets/specialist_authorized_keys,readonly" \
  --tmpfs /run:size=16m,mode=0755 \
  --tmpfs /tmp:size=256m,mode=1777 \
  --tmpfs /home/worker/.cache:uid=10001,gid=10001,mode=0700,size=512m \
  --tmpfs /home/worker/.local:uid=10001,gid=10001,mode=0700,size=256m \
  "$image" >/dev/null

authenticated=0
for _ in $(seq 1 30); do
  if docker run --rm --network "$network" \
    --mount "type=bind,source=$test_dir/client,target=/run/client,readonly" \
    --mount "type=bind,source=$test_dir/known_hosts,target=/run/known_hosts,readonly" \
    ghcr.io/paperclipai/paperclip:2026.916.1@sha256:a02ac35ac41df911af477422ea0e781cf41d2b2c600c66f0a5ac9d8c63f52c2c \
    ssh -i /run/client -o BatchMode=yes -o IdentitiesOnly=yes \
      -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/run/known_hosts \
      -p 2222 "worker@$container" \
      'test "$(id -u):$(id -g)" = 10001:10001
       test "$(awk "/^CapEff:/ {print \$2}" /proc/self/status)" = 0000000000000000
       test -d /workspaces/product && test -d /workspaces/growth && test -d /workspaces/operations
       test ! -e /var/run/docker.sock && test ! -e /run/docker.sock
       ! touch /etc/nix-worker-rootfs-write-test
       touch /workspaces/product/nix-worker-volume-write-test' >/dev/null 2>&1; then
    authenticated=1
    break
  fi
  sleep 1
done

[[ $authenticated == 1 ]] || {
  docker logs "$container" >&2
  printf 'authenticated specialist worker boundary check failed\n' >&2
  exit 1
}

[[ -z $(docker inspect --format '{{json .HostConfig.PortBindings}}' "$container" | grep -o 'HostPort' || true) ]] \
  || { printf 'specialist worker unexpectedly publishes a host port\n' >&2; exit 1; }

printf 'Hardened local specialist worker tests passed.\n'
