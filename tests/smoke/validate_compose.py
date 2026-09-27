#!/usr/bin/env python3
import json
import pathlib
import sys


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


compose_path = pathlib.Path(sys.argv[1])
repo_root = pathlib.Path(sys.argv[2])
config = json.loads(compose_path.read_text())
services = config.get("services", {})

require(set(services) == {"paperclip", "postgres", "hermes"}, "Slice 1 must contain only Paperclip, PostgreSQL, and Hermes")
for name, service in services.items():
    image = service.get("image", "")
    require("@sha256:" in image, f"{name} image is not digest-pinned")
    require(":latest" not in image, f"{name} uses latest")
    require(service.get("restart") == "unless-stopped", f"{name} restart policy is missing")
    require("healthcheck" in service, f"{name} healthcheck is missing")

require(not services["postgres"].get("ports"), "PostgreSQL must not publish ports")
require(not services["hermes"].get("ports"), "Hermes must not publish host ports")
paperclip_ports = services["paperclip"].get("ports", [])
require(len(paperclip_ports) == 1, "Paperclip must publish exactly one loopback port")
paperclip_port = paperclip_ports[0]
require(str(paperclip_port.get("target")) == "3100", "Paperclip container port must remain 3100")
require(str(paperclip_port.get("published")) == "0", "test config must request an ephemeral host port")
require(paperclip_port.get("host_ip") == "127.0.0.1", "Paperclip must bind only to host loopback")

paperclip_mounts = services["paperclip"].get("volumes", [])
postgres_mounts = services["postgres"].get("volumes", [])
require(any(mount.get("target") == "/paperclip" for mount in paperclip_mounts), "Paperclip state is not persistent")
require(any(mount.get("target") == "/var/lib/postgresql/data" for mount in postgres_mounts), "PostgreSQL state is not persistent")
hermes_mounts = services["hermes"].get("volumes", [])
require(any(mount.get("target") == "/opt/data" for mount in hermes_mounts), "Hermes state is not persistent")
require(any(mount.get("target") == "/workspace/nix-brain" and mount.get("read_only") for mount in hermes_mounts), "nix-brain must be mounted read-only")
require(
    any(mount.get("target") == "/docker-entrypoint-initdb.d/10-paperclip.sh" for mount in postgres_mounts),
    "non-superuser Paperclip role initialization is missing",
)
require(config.get("networks", {}).get("data", {}).get("internal") is True, "data network must be internal")
require(config.get("networks", {}).get("app", {}).get("internal") is not True, "Paperclip app network must allow outbound access")
require(config.get("networks", {}).get("hermes_egress", {}).get("internal") is not True, "Hermes egress network must allow outbound access")
require(config.get("networks", {}).get("agent", {}).get("internal") is True, "agent network must be internal")
require(set(services["paperclip"].get("networks", {})) == {"app", "data", "agent"}, "Paperclip network boundary is wrong")
require(set(services["postgres"].get("networks", {})) == {"data"}, "PostgreSQL must remain on the internal data network")
require(set(services["hermes"].get("networks", {})) == {"hermes_egress", "agent"}, "Hermes must use only its egress and agent networks")

paperclip_env = services["paperclip"].get("environment", {})
require(paperclip_env.get("PAPERCLIP_DEPLOYMENT_MODE") == "authenticated", "Paperclip auth mode is wrong")
require(paperclip_env.get("PAPERCLIP_DEPLOYMENT_EXPOSURE") == "private", "tailnet ingress must use private exposure mode")
require(paperclip_env.get("PAPERCLIP_PUBLIC_URL") == "https://nix-os.test-tailnet.ts.net", "Paperclip public URL is wrong")
require(paperclip_env.get("PAPERCLIP_MIGRATION_AUTO_APPLY") == "true", "migration policy must be explicit")
require(paperclip_env.get("PAPERCLIP_ENABLE_COMPANY_DELETION") == "false", "company deletion must be disabled")

require(not (repo_root / "deploy/caddy").exists(), "Caddy runtime configuration must be removed")

for script in (
    "backup-config",
    "bootstrap-ceo",
    "check-migrations",
    "check-tailscale-serve-state",
    "configure-tailscale",
    "initialize-paperclip",
    "restore-config",
    "vps-preflight",
):
    path = repo_root / "scripts" / script
    require(path.is_file(), f"required operator script is missing: {script}")

workflow = (repo_root / ".github/workflows/ci.yml").read_text()
require("recovery:" in workflow, "CI must include the required recovery job")
require("RUN_DOCKER_SMOKE=1 ./scripts/ci" in workflow, "CI recovery job must run all Docker recovery smokes")

tailscale_script = (repo_root / "scripts/configure-tailscale").read_text()
require("tailscale set --hostname=nix-os" in tailscale_script, "Tailscale machine naming is not reproducible")
require("tailscale set --operator=nix" in tailscale_script, "Tailscale operator user is not configured")
require("tailscale serve reset" in tailscale_script, "stale Tailscale web-serving state is not reset")
require("tailscale serve status --json" in tailscale_script, "complete Tailscale state is not inspected")
require("tailscale serve --bg --yes --https=443" in tailscale_script, "exclusive HTTPS Serve route is not explicit")
require("check-tailscale-serve-state" in tailscale_script, "final Tailscale state policy is not enforced")

paperclip_environment = services["paperclip"].get("environment", {})
require(paperclip_environment.get("HOST") == "0.0.0.0", "container listener must support Docker forwarding")

hermes_environment = services["hermes"].get("environment", {})
require(hermes_environment.get("API_SERVER_ENABLED") == "true", "Hermes Runs API must be enabled")
require(hermes_environment.get("API_SERVER_HOST") == "0.0.0.0", "Hermes must listen on the private Docker bridge")
require(hermes_environment.get("HERMES_GATEWAY_BOOTSTRAP_STATE") == "running", "Hermes gateway restart persistence is missing")
require("@sha256:99641e57" in services["hermes"].get("image", ""), "Hermes image digest is not the reviewed pin")

hermes_config = (repo_root / "deploy/hermes/config.yaml").read_text()
require("provider: openai-codex" in hermes_config, "Hermes provider is not explicit")
require("multiplex_profiles: false" in hermes_config, "Slice 1 must not enable profile multiplexing")
require("group_policy: disabled" in hermes_config, "Slice 1 Telegram groups must be disabled")
require('allowed_chats: ["${TELEGRAM_ALLOWED_USERS}"]' in hermes_config, "Slice 1 must hard-gate Telegram to Lior's direct chat")
require("@paperclipai/mcp-server@2026.916.1" in hermes_config, "Paperclip MCP package is not pinned")
for forbidden_tool in ("paperclipCreateApproval", "paperclipApprovalDecision", "paperclipApiRequest", "paperclipControlIssueWorkspaceServices"):
    require(forbidden_tool not in hermes_config, f"forbidden Paperclip tool is enabled: {forbidden_tool}")
require((repo_root / "deploy/hermes/SOUL.md").is_file(), "Chief of Staff SOUL is missing")

onboarding = (repo_root / "scripts/onboard-hermes-agent").read_text()
for required_join_setting in (
    'adapterType:"hermes_gateway"',
    'apiBaseUrl:"http://hermes:8642"',
    'paperclipApiUrl:"http://paperclip:3100"',
    'sessionKeyStrategy:"issue"',
    'dangerouslyAllowInsecureRemoteHttp:true',
):
    require(required_join_setting in onboarding, f"Hermes join contract is missing: {required_join_setting}")
require("claim-api-key" in onboarding, "Hermes join flow must claim a supported Paperclip agent key")
require("psql" not in onboarding and "postgres" not in onboarding.lower(), "Hermes onboarding must not manipulate PostgreSQL directly")

example = (repo_root / ".env.example").read_text()
for key in (
    "COMPOSE_PROJECT_NAME",
    "PAPERCLIP_PUBLIC_URL",
    "PAPERCLIP_HOST_PORT",
    "POSTGRES_ENV_FILE",
    "PAPERCLIP_ENV_FILE",
    "HERMES_ENV_FILE",
    "NIX_BRAIN_HOST_PATH",
    "PAPERCLIP_AUTH_DISABLE_SIGN_UP",
    "BACKUP_OUTPUT_DIR",
):
    require(f"{key}=" in example, f".env.example does not document {key}")

gitignore = (repo_root / ".gitignore").read_text()
for ignored in (".env", "secrets/", "backups/", "*.dump", "*.age", ".config/nix/age/identity.txt"):
    require(ignored in gitignore, f".gitignore does not cover {ignored}")

print("Rendered Compose invariants passed.")
