#!/usr/bin/env bash
set -euo pipefail
umask 077

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
image='nousresearch/hermes-agent:v2026.9.14@sha256:99641e57ec762c59e54cb44aa6746b7fc68c18b3c5ddb088af54234c613d9294'
suffix=$(openssl rand -hex 8)
container="nix-hermes-contract-$suffix"
volume="nix-hermes-contract-$suffix"
api_key=$(openssl rand -hex 32)

cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  docker volume rm "$volume" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker volume create "$volume" >/dev/null

docker run --rm --entrypoint python3 \
  --volume "$repo_root/deploy/hermes/config.yaml:/nix/config.yaml:ro" \
  "$image" -c '
import os, pathlib, yaml
from types import SimpleNamespace
from gateway.authz_mixin import GatewayAuthorizationMixin
from gateway.config import Platform
from gateway.profile_routing import parse_profile_routes, match_profile_route
from gateway.session import SessionSource
from hermes_cli.config import _expand_env_vars
from plugins.platforms.telegram.adapter import TelegramAdapter

cfg = yaml.safe_load(pathlib.Path("/nix/config.yaml").read_text())
assert cfg["model"] == {"provider": "openai-codex", "default": "gpt-5.4"}
assert cfg["gateway"]["multiplex_profiles"] is False
expected_toolsets = ["file", "skills", "memory", "session_search", "paperclip"]
assert cfg["platform_toolsets"] == {
  "cli": expected_toolsets,
  "telegram": expected_toolsets,
  "api_server": expected_toolsets,
}
assert cfg["unauthorized_dm_behavior"] == "ignore"
assert cfg["platforms"]["telegram"]["unauthorized_dm_behavior"] == "ignore"
assert cfg["platforms"]["telegram"]["guest_mode"] is False
assert cfg["platforms"]["telegram"]["allow_bots"] == "none"
assert "group_policy" not in cfg["platforms"]["telegram"]
os.environ["TELEGRAM_ALLOWED_USERS"] = "123456789"
os.environ["TELEGRAM_ALLOW_ALL_USERS"] = "false"
os.environ["GATEWAY_ALLOW_ALL_USERS"] = "false"
os.environ["TELEGRAM_ALLOW_BOTS"] = "none"
expanded = _expand_env_vars(cfg)
assert expanded["platforms"]["telegram"]["allowed_chats"] == ["123456789"]

class TelegramGate:
    def __init__(self, chat_id, chat_type, user_id, *, is_bot=False, thread_id=None):
        self.message = SimpleNamespace(
            chat=SimpleNamespace(id=chat_id, type=chat_type, is_forum=chat_type == "forum"),
            from_user=SimpleNamespace(id=user_id, is_bot=is_bot),
            message_thread_id=thread_id,
            is_topic_message=thread_id is not None,
        )
    _observe_bot_identity_from_message = lambda self, message: None
    _is_own_message = lambda self, message: False
    _is_group_chat = lambda self, message: message.chat.type != "private"
    _effective_message_thread_id = lambda self, message: message.message_thread_id
    _topic_gates_pass = lambda self, thread_id, warn_non_numeric: True
    _chat_id_str = lambda self, message: str(message.chat.id)
    _telegram_exclusive_bot_mentions = lambda self: False
    _is_guest_mention = lambda self, message: False
    _telegram_allowed_chats = lambda self: {"123456789"}
    _telegram_free_response_chats = lambda self: set()
    _telegram_is_free_response_topic = lambda self, message: False
    _telegram_bots_require_mention = lambda self: True
    _sender_is_other_bot = lambda self, message: bool(message.from_user.is_bot)
    _message_mentions_bot = lambda self, message: False
    _telegram_require_mention = lambda self: True
    _is_reply_to_bot = lambda self, message: False
    _telegram_guest_mode = lambda self: False
    _message_matches_mention_patterns = lambda self, message: False

class AuthHarness(GatewayAuthorizationMixin):
    _adapter_profile_for_source = lambda self, source: None
    _pairing_store_for = lambda self, source: None
    _adapter_resolved_allowlist_ids = lambda self, source: set()
    _adapter_flag = lambda self, *args, **kwargs: False
    _adapter_extra_allowlist_authorizes = lambda self, *args, **kwargs: False
    _adapter_extra_for_source = lambda self, source: {"allow_bots": "none"}

auth = AuthHarness()
def accepted(gate):
    message = gate.message
    chat_type = "dm" if message.chat.type == "private" else ("forum" if message.chat.type == "forum" else "group")
    source = SessionSource(
        platform=Platform.TELEGRAM,
        chat_id=str(message.chat.id),
        chat_type=chat_type,
        user_id=str(message.from_user.id),
        thread_id=str(message.message_thread_id) if message.message_thread_id is not None else None,
        is_bot=message.from_user.is_bot,
    )
    return TelegramAdapter._should_process_message(gate, message) and auth._is_user_authorized(source)

assert accepted(TelegramGate(123456789, "private", 123456789)) is True
assert accepted(TelegramGate(987654321, "private", 987654321)) is False
assert accepted(TelegramGate(-100111, "group", 123456789)) is False
assert accepted(TelegramGate(-100222, "forum", 123456789, thread_id=42)) is False
assert accepted(TelegramGate(555555555, "private", 555555555, is_bot=True)) is False
server = cfg["mcp_servers"]["paperclip"]
assert server["args"] == ["-y", "--min-release-age=0", "@paperclipai/mcp-server@2026.916.1"]
assert set(server["tools"]["include"]) == {
  "paperclipMe", "paperclipListIssues", "paperclipGetIssue",
  "paperclipListComments", "paperclipListProjects", "paperclipGetProject",
  "paperclipCreateIssue", "paperclipUpdateIssue", "paperclipAddComment",
}
routes = parse_profile_routes([
  {"name": "future-product-topic", "platform": "telegram", "chat_id": "-1001", "thread_id": "22", "profile": "product"},
  {"name": "future-growth-topic", "platform": "telegram", "chat_id": "-1001", "thread_id": "33", "profile": "growth"},
])
assert match_profile_route(routes, "telegram", chat_id="-1001", thread_id="22").profile == "product"
assert match_profile_route(routes, "telegram", chat_id="-1001", thread_id="33").profile == "growth"
assert match_profile_route(routes, "telegram", chat_id="-1001", thread_id="44") is None
skill = pathlib.Path("/opt/hermes/optional-skills/software-development/grill-me/SKILL.md")
assert skill.is_file()
assert "name: grill-me" in skill.read_text()
'

mcp_listing=$(docker run --rm --entrypoint hermes \
  --env PAPERCLIP_API_KEY=pcp_contract_fixture \
  --env PAPERCLIP_COMPANY_ID=contract-company \
  --env PAPERCLIP_AGENT_ID=contract-agent \
  --volume "$repo_root/deploy/hermes/config.yaml:/opt/data/config.yaml:ro" \
  "$image" mcp list)
grep -q 'paperclip' <<<"$mcp_listing"
grep -q '9 selected' <<<"$mcp_listing"
grep -q 'enabled' <<<"$mcp_listing"

docker run --rm --entrypoint python3 \
  --volume "$repo_root/tests/smoke/probe-paperclip-mcp.py:/nix/probe-paperclip-mcp.py:ro" \
  "$image" /nix/probe-paperclip-mcp.py

docker run --rm --entrypoint sh --volume "$volume:/opt/data" "$image" -ec '
  mkdir -p /opt/data/memories /opt/data/sessions
  printf "%s\n" "restart-continuity-v1" > /opt/data/memories/contract.txt
'
docker run -d --name "$container" --volume "$volume:/opt/data" \
  --volume "$repo_root/deploy/hermes/config.yaml:/opt/data/config.yaml:ro" \
  --volume "$repo_root/deploy/hermes/SOUL.md:/opt/data/SOUL.md:ro" \
  --volume "$repo_root/deploy/hermes/validate-tool-boundary.py:/opt/nix/validate-tool-boundary.py:ro" \
  --volume "$repo_root:/workspace/nix-brain:ro" \
  --env API_SERVER_ENABLED=true --env API_SERVER_HOST=0.0.0.0 --env API_SERVER_PORT=8642 \
  --env API_SERVER_KEY="$api_key" --env HERMES_GATEWAY_BOOTSTRAP_STATE=running \
  --env PAPERCLIP_API_KEY=pcp_contract_fixture --env PAPERCLIP_COMPANY_ID=contract-company \
  --env PAPERCLIP_AGENT_ID=contract-agent \
  "$image" gateway run >/dev/null

for _ in $(seq 1 120); do
  if docker exec "$container" curl -fsS http://127.0.0.1:8642/health >/dev/null 2>&1; then break; fi
  sleep 1
done
docker exec "$container" curl -fsS http://127.0.0.1:8642/health >/dev/null
unauthorized=$(docker exec "$container" curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8642/v1/capabilities)
[[ "$unauthorized" == 401 ]] || { printf 'Hermes Runs API accepted unauthenticated request: HTTP %s\n' "$unauthorized" >&2; exit 1; }
docker exec "$container" curl -fsS -H "Authorization: Bearer $api_key" http://127.0.0.1:8642/v1/capabilities >/dev/null
for _ in $(seq 1 120); do
  if toolsets_json=$(docker exec "$container" curl -fsS -H "Authorization: Bearer $api_key" http://127.0.0.1:8642/v1/toolsets 2>/dev/null); then break; fi
  sleep 1
done
printf '%s' "$toolsets_json" | docker exec -i "$container" python3 /opt/nix/validate-tool-boundary.py api
docker exec "$container" python3 /opt/nix/validate-tool-boundary.py runtime >"/tmp/${container}-tool-boundary.json"
python3 - "$container" <<'PY'
import json, pathlib, sys
summary = json.loads(pathlib.Path(f"/tmp/{sys.argv[1]}-tool-boundary.json").read_text())
expected = ["file", "memory", "paperclip", "session_search", "skills"]
for lane in ("cli", "telegram", "api_server"):
    assert summary[lane]["toolsets"] == expected
    assert "terminal" not in summary[lane]["tools"]
    assert "process_manage" not in summary[lane]["tools"]
    assert "execute_code" not in summary[lane]["tools"]
PY
rm -f "/tmp/${container}-tool-boundary.json"
docker restart "$container" >/dev/null
for _ in $(seq 1 120); do
  if docker exec "$container" curl -fsS http://127.0.0.1:8642/health >/dev/null 2>&1; then break; fi
  sleep 1
done
docker exec "$container" grep -qx restart-continuity-v1 /opt/data/memories/contract.txt
docker exec "$container" test ! -w /opt/data/config.yaml
docker exec "$container" test ! -w /opt/data/SOUL.md
docker exec "$container" test ! -w /workspace/nix-brain/AGENTS.md
docker exec "$container" curl -fsS -H "Authorization: Bearer $api_key" http://127.0.0.1:8642/v1/capabilities >/dev/null

printf 'Pinned Hermes restricted toolsets, Telegram authorization, authenticated API, and restart continuity passed.\n'
