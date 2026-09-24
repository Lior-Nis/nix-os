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

require(set(services) == {"caddy", "paperclip", "postgres"}, "only Slice 0 services may exist")
for name, service in services.items():
    image = service.get("image", "")
    require("@sha256:" in image, f"{name} image is not digest-pinned")
    require(":latest" not in image, f"{name} uses latest")
    require(service.get("restart") == "unless-stopped", f"{name} restart policy is missing")
    require("healthcheck" in service, f"{name} healthcheck is missing")

require(not services["postgres"].get("ports"), "PostgreSQL must not publish ports")
require(not services["paperclip"].get("ports"), "Paperclip must not publish ports")
caddy_ports = services["caddy"].get("ports", [])
published = {(str(item.get("published")), item.get("protocol", "tcp")) for item in caddy_ports}
require(published == {("80", "tcp"), ("443", "tcp"), ("443", "udp")}, "unexpected public ports")

paperclip_mounts = services["paperclip"].get("volumes", [])
postgres_mounts = services["postgres"].get("volumes", [])
require(any(mount.get("target") == "/paperclip" for mount in paperclip_mounts), "Paperclip state is not persistent")
require(any(mount.get("target") == "/var/lib/postgresql/data" for mount in postgres_mounts), "PostgreSQL state is not persistent")
require(
    any(mount.get("target") == "/docker-entrypoint-initdb.d/10-paperclip.sh" for mount in postgres_mounts),
    "non-superuser Paperclip role initialization is missing",
)
require(config.get("networks", {}).get("data", {}).get("internal") is True, "data network must be internal")

paperclip_env = services["paperclip"].get("environment", {})
require(paperclip_env.get("PAPERCLIP_DEPLOYMENT_MODE") == "authenticated", "Paperclip auth mode is wrong")
require(paperclip_env.get("PAPERCLIP_DEPLOYMENT_EXPOSURE") == "public", "public ingress must use public exposure mode")
require(paperclip_env.get("PAPERCLIP_MIGRATION_AUTO_APPLY") == "true", "migration policy must be explicit")
require(paperclip_env.get("PAPERCLIP_ENABLE_COMPANY_DELETION") == "false", "company deletion must be disabled")

caddyfile = (repo_root / "deploy/caddy/Caddyfile").read_text()
require("{$PAPERCLIP_HOSTNAME}" in caddyfile, "Caddy hostname must remain configurable")
require("reverse_proxy paperclip:3100" in caddyfile, "Caddy must proxy only to Paperclip")

example = (repo_root / ".env.example").read_text()
for key in (
    "COMPOSE_PROJECT_NAME",
    "PAPERCLIP_HOSTNAME",
    "ACME_EMAIL",
    "POSTGRES_ENV_FILE",
    "PAPERCLIP_ENV_FILE",
    "PAPERCLIP_AUTH_DISABLE_SIGN_UP",
    "BACKUP_OUTPUT_DIR",
):
    require(f"{key}=" in example, f".env.example does not document {key}")

gitignore = (repo_root / ".gitignore").read_text()
for ignored in (".env", "secrets/", "backups/", "*.dump", "*.age"):
    require(ignored in gitignore, f".gitignore does not cover {ignored}")

print("Rendered Compose invariants passed.")
