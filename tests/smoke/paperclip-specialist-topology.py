#!/usr/bin/env python3
"""Contract tests for the three-role local-SSH specialist topology."""

from __future__ import annotations

import copy
import runpy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
module = runpy.run_path(str(ROOT / "scripts/check-paperclip-specialist-topology"))
validate_topology = module["validate_topology"]
TopologyError = module["TopologyError"]
AGENT_MARKER = module["AGENT_MARKER"]
ENVIRONMENT_MARKER = module["ENVIRONMENT_MARKER"]
expected_adapter_config = module["expected_adapter_config"]
expected_permissions = module["expected_permissions"]

COMPANY = "11111111-1111-4111-8111-111111111111"
CHIEF = "22222222-2222-4222-8222-222222222222"
PROJECT = "33333333-3333-4333-8333-333333333333"
SSH_SECRET = "44444444-4444-4444-8444-444444444444"
PROVIDER_SECRET = "55555555-5555-4555-8555-555555555555"
AGENTS = {
    "product": "66666666-6666-4666-8666-666666666666",
    "growth": "77777777-7777-4777-8777-777777777777",
    "operations": "88888888-8888-4888-8888-888888888888",
}
ENVIRONMENTS = {
    "product": "99999999-9999-4999-8999-999999999999",
    "growth": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "operations": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
}
KNOWN_HOSTS = "[specialist-worker]:2222 ssh-ed25519 AAAATEST"
FINGERPRINTS = {
    "nix-specialist-worker-ssh-key": "1" * 64,
    "nix-specialist-opencode-api-key": "2" * 64,
}


def fixture() -> tuple[dict[str, object], dict[str, object]]:
    agent_ids = list(AGENTS.values())
    permissions = expected_permissions(COMPANY, PROJECT, agent_ids)
    agents: list[dict[str, object]] = [
        {
            "id": CHIEF,
            "companyId": COMPANY,
            "name": "Chief of Staff",
            "role": "ceo",
            "status": "idle",
            "reportsTo": None,
            "adapterType": "hermes_gateway",
            "permissions": {
                "canCreateAgents": False,
                "canCreateSkills": False,
                "canAssignTasks": True,
            },
        }
    ]
    role_data = {
        "product": ("Product", "pm"),
        "growth": ("Growth", "cmo"),
        "operations": ("Operations", "general"),
    }
    environments: list[dict[str, object]] = []
    bindings: list[dict[str, object]] = []
    for slug, (name, role) in role_data.items():
        agents.append(
            {
                "id": AGENTS[slug],
                "companyId": COMPANY,
                "name": name,
                "role": role,
                "title": f"Task-scoped {name} specialist",
                "status": "idle",
                "reportsTo": CHIEF,
                "capabilities": [],
                "adapterType": "paperclip_runner",
                "adapterConfig": expected_adapter_config(COMPANY, AGENTS[slug]),
                "runtimeConfig": {"heartbeat": {"enabled": False, "maxConcurrentRuns": 1}},
                "permissions": permissions,
                "budgetMonthlyCents": 0,
                "defaultEnvironmentId": ENVIRONMENTS[slug],
                "metadata": {"nix": AGENT_MARKER, "specialistRole": slug},
            }
        )
        environments.append(
            {
                "id": ENVIRONMENTS[slug],
                "name": f"Nix local specialist worker ({slug})",
                "driver": "ssh",
                "status": "active",
                "config": {
                    "host": "specialist-worker",
                    "port": 2222,
                    "username": "worker",
                    "remoteWorkspacePath": f"/workspaces/{slug}",
                    "privateKey": None,
                    "privateKeySecretRef": {
                        "type": "secret_ref",
                        "secretId": SSH_SECRET,
                        "version": "latest",
                    },
                    "knownHosts": KNOWN_HOSTS,
                    "strictHostKeyChecking": True,
                },
                "envVars": {
                    "OPENCODE_API_KEY": {
                        "type": "secret_ref",
                        "secretId": PROVIDER_SECRET,
                        "version": "latest",
                        "projectionClass": "unclassified",
                        "projectionAllowlistKey": None,
                    }
                },
                "metadata": {"nix": ENVIRONMENT_MARKER, "specialistRole": slug},
            }
        )
        bindings.extend(
            (
                {
                    "secretId": SSH_SECRET,
                    "targetType": "environment",
                    "targetId": ENVIRONMENTS[slug],
                    "configPath": "privateKeySecretRef",
                    "versionSelector": "latest",
                    "required": True,
                },
                {
                    "secretId": PROVIDER_SECRET,
                    "targetType": "environment",
                    "targetId": ENVIRONMENTS[slug],
                    "configPath": "env.OPENCODE_API_KEY",
                    "versionSelector": "latest",
                    "required": True,
                },
            )
        )
    expected = {
        "chiefId": CHIEF,
        "projectId": PROJECT,
        "environmentIds": ENVIRONMENTS,
        "specialistIds": AGENTS,
        "knownHosts": KNOWN_HOSTS,
        "secretFingerprints": FINGERPRINTS,
    }
    snapshot = {
        "chief": agents[0],
        "project": {"id": PROJECT, "companyId": COMPANY},
        "agents": agents,
        "keys": [],
        "environments": environments,
        "secrets": [
            {
                "id": SSH_SECRET,
                "companyId": COMPANY,
                "key": "nix-specialist-worker-ssh-key",
                "status": "active",
                "managedMode": "paperclip_managed",
                "description": f"Nix Slice 3 worker-ssh; sha256={FINGERPRINTS['nix-specialist-worker-ssh-key']}",
                "deleted": False,
            },
            {
                "id": PROVIDER_SECRET,
                "companyId": COMPANY,
                "key": "nix-specialist-opencode-api-key",
                "status": "active",
                "managedMode": "paperclip_managed",
                "description": f"Nix Slice 3 provider; sha256={FINGERPRINTS['nix-specialist-opencode-api-key']}",
                "deleted": False,
            },
        ],
        "bindings": bindings,
        "unsafeLeases": [],
        "unsafeRuns": [],
        "plugins": [],
        "experimental": {"enableEnvironments": True, "enableNativeRunner": True},
        "markedSpecialistCount": 3,
    }
    return expected, snapshot


def must_fail(expected: dict[str, object], snapshot: dict[str, object], label: str) -> None:
    try:
        validate_topology(expected, snapshot)
    except TopologyError:
        return
    raise AssertionError(f"unsafe topology was accepted: {label}")


def main() -> None:
    expected, snapshot = fixture()
    validate_topology(expected, snapshot)

    changed = copy.deepcopy(snapshot)
    changed["environments"][1]["config"]["remoteWorkspacePath"] = "/workspaces/product"
    must_fail(expected, changed, "roles share a workspace")

    changed = copy.deepcopy(snapshot)
    changed["plugins"] = [{"pluginKey": "sandbox-provider"}]
    must_fail(expected, changed, "sandbox plugin dependency")

    changed = copy.deepcopy(snapshot)
    changed["unsafeRuns"] = [{"id": CHIEF, "status": "running", "agentId": AGENTS["product"]}]
    must_fail(expected, changed, "nonterminal specialist run")

    changed = copy.deepcopy(snapshot)
    changed["agents"][1]["defaultEnvironmentId"] = ENVIRONMENTS["growth"]
    must_fail(expected, changed, "role assigned to the wrong SSH environment")

    print("Paperclip local-SSH specialist topology tests passed.")


if __name__ == "__main__":
    main()
