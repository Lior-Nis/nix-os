#!/bin/sh
set -eu

case "${NIX_BRAIN_GID:-}" in
  ''|*[!0-9]*|0*)
    echo "Hermes startup refused: NIX_BRAIN_GID must be a positive numeric group ID" >&2
    exit 1
    ;;
esac
brain_group=$(getent group "$NIX_BRAIN_GID" | cut -d: -f1 || true)
if [ -n "$brain_group" ] \
  && [ "$NIX_BRAIN_GID" != 10000 ] \
  && [ "$brain_group" != nix-brain-reader ]; then
  echo "Hermes startup refused: NIX_BRAIN_GID collides with an image system group" >&2
  exit 1
fi
if [ -z "$brain_group" ]; then
  brain_group=nix-brain-reader
  if getent group "$brain_group" >/dev/null 2>&1; then
    echo "Hermes startup refused: reserved brain reader group has an unexpected ID" >&2
    exit 1
  fi
  groupadd --gid "$NIX_BRAIN_GID" "$brain_group"
fi
usermod --append --groups "$brain_group" hermes
if ! id -G hermes | tr ' ' '\n' | grep -qx "$NIX_BRAIN_GID"; then
  echo "Hermes startup refused: failed to install the brain reader group" >&2
  exit 1
fi

if ! mode=$(python3 /opt/nix/startup-boundary.py); then
  echo "Hermes startup refused: Telegram/profile boundary validation failed" >&2
  exit 1
fi
case "$mode" in
  disabled)
    # The real token may remain in the external env file during staging and
    # recovery. Remove it before any Hermes process is started.
    export TELEGRAM_BOT_TOKEN=
    ;;
  live)
    [ -n "${TELEGRAM_BOT_TOKEN:-}" ] || {
      echo "Hermes startup refused: live Telegram mode requires a bot token" >&2
      exit 1
    }
    ;;
  *)
    echo "Hermes startup refused: invalid Telegram mode marker" >&2
    exit 1
    ;;
esac

# The pinned Hermes release does not carry Paperclip's heartbeat identity from
# /v1/runs into long-lived MCP calls. Apply the exact-hash-locked, request-local
# compatibility patch before upstream gateway modules are imported. Unknown
# source bytes fail closed.
python3 /opt/nix/patch-run-attribution.py

exec /opt/hermes/docker/entrypoint-dispatch.sh "$@"
