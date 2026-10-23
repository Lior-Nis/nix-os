#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
MANIFEST="$ROOT/nix-os.yaml"
HERMES_HOME=${HERMES_HOME:-"${HOME}/.hermes"}
HERMES_BIN=${HERMES_BIN:-hermes}
MODE=preview

usage() {
  printf 'Usage: %s [--apply]\n' "${0##*/}"
  printf 'Default is PREVIEW. --apply creates only missing Hermes state.\n'
}

if (($# > 1)); then usage >&2; exit 2; fi
if (($# == 1)); then
  case "$1" in
    --apply) MODE=apply ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
fi

if [[ $MODE == preview ]]; then
  printf 'Nix OS bootstrap: PREVIEW (no files or Hermes state will be changed)\n'
else
  printf 'Nix OS bootstrap: APPLY (missing state only; existing state is preserved)\n'
  if [[ "$HERMES_BIN" == */* ]]; then
    [[ -x "$HERMES_BIN" ]] || { printf 'error: Hermes executable not found: %s\n' "$HERMES_BIN" >&2; exit 1; }
  else
    command -v "$HERMES_BIN" >/dev/null 2>&1 || { printf 'error: Hermes CLI not found: %s\n' "$HERMES_BIN" >&2; exit 1; }
  fi
  python3 "$ROOT/scripts/verify.py"
fi

mapfile -t PROFILE_ROWS < <(python3 - "$MANIFEST" <<'PY'
import json, sys
manifest = json.load(open(sys.argv[1], encoding="utf-8"))
for p in manifest["profiles"]:
    print("\t".join((p["id"], p["hermes_profile"], p["role"])))
PY
)
mapfile -t PROJECT_ROWS < <(python3 - "$MANIFEST" <<'PY'
import json, sys
manifest = json.load(open(sys.argv[1], encoding="utf-8"))
for p in manifest["projects"]:
    print("\t".join((p["id"], p["name"], p["lead"], p["board"], p["workspace"])))
PY
)

profile_dir() {
  if [[ $1 == default ]]; then printf '%s' "$HERMES_HOME"; else printf '%s/profiles/%s' "$HERMES_HOME" "$1"; fi
}

profile_has_state() {
  local dir=$1
  [[ -e "$dir/SOUL.md" || -e "$dir/config.yaml" || -e "$dir/profile.yaml" || -e "$dir/.env" || -e "$dir/auth.json" || -e "$dir/state.db" ]]
}

expand_workspace() {
  local value=$1
  case "$value" in
    '${HOME}'/*) printf '%s/%s' "$HOME" "${value#\$\{HOME\}/}" ;;
    *) printf 'error: workspace must start with ${HOME}/: %s\n' "$value" >&2; return 1 ;;
  esac
}

board_state() {
  local slug=$1 output state
  if ! output=$("$HERMES_BIN" -p default kanban boards list --json); then
    printf 'error: could not read Hermes board state; refusing to mutate.\n' >&2
    return 2
  fi
  if ! state=$(python3 -c 'import json,sys
slug=sys.argv[1]
try:
    value=json.load(sys.stdin)
except (json.JSONDecodeError, UnicodeError):
    raise SystemExit(2)
if isinstance(value, dict):
    items=value.get("boards")
elif isinstance(value, list):
    items=value
else:
    raise SystemExit(2)
if not isinstance(items, list) or not all(isinstance(x, dict) and isinstance(x.get("slug"), str) for x in items):
    raise SystemExit(2)
print("present" if any(x["slug"] == slug for x in items) else "missing")' "$slug" <<<"$output"); then
    printf 'error: Hermes returned invalid board state; refusing to mutate.\n' >&2
    return 2
  fi
  printf '%s' "$state"
}

project_state() {
  local slug=$1 output status
  if output=$("$HERMES_BIN" -p default project show "$slug" 2>&1); then
    printf 'present'
    return 0
  else
    status=$?
  fi
  if [[ $status -eq 1 && $output == "project: no such project: $slug" ]]; then
    printf 'missing'
    return 0
  fi
  printf 'error: could not read Hermes project %s state; refusing to mutate.\n' "$slug" >&2
  return 2
}

declare -A BOARD_STATES=()
declare -A PROJECT_STATES=()
if [[ $MODE == apply ]]; then
  for row in "${PROJECT_ROWS[@]}"; do
    IFS=$'\t' read -r id _name _lead board _workspace <<<"$row"
    if ! BOARD_STATES["$board"]=$(board_state "$board"); then exit 1; fi
    if ! PROJECT_STATES["$id"]=$(project_state "$id"); then exit 1; fi
  done
fi

for row in "${PROFILE_ROWS[@]}"; do
  IFS=$'\t' read -r id hermes_name role <<<"$row"
  target=$(profile_dir "$hermes_name")
  contract="$ROOT/profiles/$id/ROLE.md"
  if [[ $hermes_name == default ]]; then
    printf '[preserve] LNX maps to default profile at %s; bootstrap never overwrites default identity/configuration.\n' "$target"
    continue
  fi
  if [[ -e "$target" ]] || profile_has_state "$target"; then
    printf '[preserve] profile %s already exists at %s; no SOUL/config/profile state will be changed.\n' "$hermes_name" "$target"
    continue
  fi
  if [[ $MODE == preview ]]; then
    printf '[would create] isolated Hermes profile directory %s for %s\n' "$target" "$role"
    printf '[would install] %s -> %s/SOUL.md (new profile only)\n' "$contract" "$target"
    continue
  fi
  mkdir -p -m 0700 "$(dirname "$target")"
  if ! mkdir -m 0700 "$target"; then
    if [[ -d "$target" ]]; then
      printf '[preserve] profile %s appeared concurrently at %s; leaving it untouched.\n' "$hermes_name" "$target"
      continue
    fi
    printf '[error] could not create profile directory %s; refusing to continue.\n' "$target" >&2
    exit 1
  fi
  if ! install -m 0600 "$contract" "$target/SOUL.md"; then
    rmdir "$target" 2>/dev/null || true
    printf '[error] could not install the role contract for %s; removed the empty profile directory.\n' "$hermes_name" >&2
    exit 1
  fi
  printf '[created] profile %s and installed its role contract.\n' "$hermes_name"
done

for row in "${PROJECT_ROWS[@]}"; do
  IFS=$'\t' read -r id name lead board workspace_template <<<"$row"
  workspace=$(expand_workspace "$workspace_template")
  if [[ $MODE == preview ]]; then
    printf '[would ensure] board %s and project %s (lead: %s, workspace: %s) under the default profile.\n' "$board" "$id" "$lead" "$workspace"
    continue
  fi
  if [[ ${BOARD_STATES[$board]} == present ]]; then
    printf '[preserve] board %s already exists.\n' "$board"
  else
    "$HERMES_BIN" -p default kanban boards create "$board" --name "$name" --description "$name delegated execution" --default-workdir "$workspace"
    printf '[created] board %s.\n' "$board"
  fi
  if [[ ${PROJECT_STATES[$id]} == present ]]; then
    printf '[preserve] project %s already exists.\n' "$id"
  else
    "$HERMES_BIN" -p default project create "$name" "$workspace" --slug "$id" --primary "$workspace" --description "$name portfolio project" --board "$board"
    printf '[created] project %s bound to board %s.\n' "$id" "$board"
  fi
done

cat <<'INSTRUCTIONS'

Manual Discord setup for LNX/default (bootstrap never handles tokens):
  1. Run: hermes -p default gateway setup
  2. Select Discord and enter the bot credential only in the interactive Hermes prompt.
  3. Configure the Discord user/server allowlist in that prompt; do not enable other profiles.
  4. Verify: hermes -p default doctor
  5. Start only after review: hermes -p default gateway start

Do not place the Discord credential in nix-os.yaml, config examples, shell history,
or this repository. Pulse, Algua, and MeaBeclick profiles remain internal.
INSTRUCTIONS
