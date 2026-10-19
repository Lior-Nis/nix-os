#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
test_dir=$(mktemp -d /tmp/nix-specialist-worker.XXXXXX)
container="nix-specialist-worker-test-$$"
network="nix-specialist-worker-test-$$"
volume="nix_specialist_worker_test_$$"
image="nix-specialist-worker:test-$$"
paperclip_image='ghcr.io/paperclipai/paperclip:2026.916.1@sha256:a02ac35ac41df911af477422ea0e781cf41d2b2c600c66f0a5ac9d8c63f52c2c'

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
chmod 0600 "$test_dir/host" "$test_dir/authorized_keys"
# These are disposable test-only inputs inside a mode-0700 temporary directory.
# Make them readable through Docker user-namespace mappings, then copy them to
# private files inside the client container before OpenSSH reads them.
chmod 0644 "$test_dir/client" "$test_dir/known_hosts"

# Linux bind mounts preserve host ownership. Match production's root-owned
# worker files so sshd StrictModes validates the absolute authorized-keys path.
if [[ $(uname -s) == Linux && $(id -u) != 0 ]]; then
  sudo -n chown root:root "$test_dir/host" "$test_dir/authorized_keys"
fi

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
  --tmpfs /home/worker/.config:uid=10001,gid=10001,mode=0700,size=16m \
  --tmpfs /home/worker/.cache:uid=10001,gid=10001,mode=0700,size=512m \
  --tmpfs /home/worker/.local:uid=10001,gid=10001,mode=0700,size=256m \
  "$image" >/dev/null

authenticated=0
ssh_error="$test_dir/ssh-error.log"
for _ in $(seq 1 10); do
  if docker run --rm --network "$network" \
    --mount "type=bind,source=$test_dir/client,target=/run/client-source,readonly" \
    --mount "type=bind,source=$test_dir/known_hosts,target=/run/known-hosts-source,readonly" \
    ghcr.io/paperclipai/paperclip:2026.916.1@sha256:a02ac35ac41df911af477422ea0e781cf41d2b2c600c66f0a5ac9d8c63f52c2c \
    sh -ec '
      install -m 0600 /run/client-source /tmp/client
      install -m 0600 /run/known-hosts-source /tmp/known_hosts
      exec ssh -i /tmp/client -o BatchMode=yes -o IdentitiesOnly=yes \
        -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/tmp/known_hosts "$@"
    ' sh -p 2222 "worker@$container" \
      'test "$(id -u):$(id -g)" = 10001:10001
       test "$(awk "/^CapEff:/ {print \$2}" /proc/self/status)" = 0000000000000000
       test -d /workspaces/product && test -d /workspaces/growth && test -d /workspaces/operations
       test -L /opt/paperclip-runner/provider-pack
       test ! -e /var/run/docker.sock && test ! -e /run/docker.sock
       ! touch /etc/nix-worker-rootfs-write-test
       touch /workspaces/product/nix-worker-volume-write-test' >/dev/null 2>"$ssh_error"; then
    authenticated=1
    break
  fi
  sleep 1
done

[[ $authenticated == 1 ]] || {
  sed -n '1,80p' "$ssh_error" >&2
  docker logs "$container" >&2
  printf 'authenticated specialist worker boundary check failed\n' >&2
  exit 1
}

# Execute the exact runner artifact shipped by the pinned Paperclip image. This
# catches worker-base ABI drift before a live task reaches provider startup.
docker run --rm --entrypoint sh \
  --mount "type=volume,source=$volume,target=/shared" \
  "$paperclip_image" -ec '
    cp /app/packages/paperclip-runner/dist/bin/paperclip-runnerd /shared/paperclip-runnerd
    chmod 0755 /shared/paperclip-runnerd
  '
docker exec --user 10001:10001 "$container" \
  /workspaces/paperclip-runnerd --build-metadata \
  | python3 -c '
import json, sys
metadata = json.load(sys.stdin)
assert metadata.get("schema") == "paperclip-runner/runnerd-build-metadata/v1"
assert metadata.get("binaryContractVersion") == 2
assert "dial_wss" in metadata.get("prpTransportModes", [])
'

[[ -z $(docker inspect --format '{{json .HostConfig.PortBindings}}' "$container" | grep -o 'HostPort' || true) ]] \
  || { printf 'specialist worker unexpectedly publishes a host port\n' >&2; exit 1; }

printf 'Hardened local specialist worker tests passed.\n'
