#!/bin/sh
set -eu
umask 077

host_key=/run/secrets/specialist_host_key
authorized_keys=/run/secrets/specialist_authorized_keys

fail() {
  printf 'specialist worker startup error: %s\n' "$*" >&2
  exit 1
}

require_private_regular_file() {
  path=$1
  label=$2
  [ -f "$path" ] || fail "$label is missing or is not a regular file"
  [ ! -L "$path" ] || fail "$label must not be a symlink"
  mode=$(stat -c '%a' "$path")
  case "$mode" in 400|600) ;; *) fail "$label must have mode 0400 or 0600" ;; esac
}

require_private_regular_file "$host_key" 'SSH host key'
require_private_regular_file "$authorized_keys" 'SSH authorized-keys file'
nonempty_lines=$(awk 'NF && $1 !~ /^#/ { count += 1 } END { print count + 0 }' "$authorized_keys")
[ "$nonempty_lines" = 1 ] || fail 'SSH authorized-keys file must contain exactly one non-comment key'
grep -Eq '^restrict ssh-ed25519 [A-Za-z0-9+/]+={0,3}( [^[:cntrl:]]+)?$' "$authorized_keys" \
  || fail 'SSH authorized key must be one restricted Ed25519 key'

install -d -o root -g root -m 0755 /run/sshd
install -o root -g root -m 0644 "$authorized_keys" /run/sshd/authorized_keys
install -d -o worker -g worker -m 0700 \
  /workspaces/product /workspaces/growth /workspaces/operations

/usr/sbin/sshd -t -f /etc/ssh/sshd_config || fail 'OpenSSH configuration validation failed'
printf 'specialist worker boundary ready\n'
exec /usr/sbin/sshd -D -e -f /etc/ssh/sshd_config
