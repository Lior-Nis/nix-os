#!/bin/sh
set -eu

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

exec /opt/hermes/docker/entrypoint-dispatch.sh "$@"
