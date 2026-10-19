#!/usr/bin/env python3
"""Focused contracts for the local-SSH Slice 3 bootstrap."""

from __future__ import annotations

import runpy
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
module = runpy.run_path(str(ROOT / "scripts/bootstrap-paperclip-specialists"))


class Api:
    def __init__(self) -> None:
        self.environments: list[dict[str, object]] = []
        self.agents: list[dict[str, object]] = []
        self.probes: list[str] = []

    def get(self, path: str) -> object:
        if path.endswith("/environments"):
            return self.environments
        if path.endswith("/agents"):
            return self.agents
        if path.endswith("/keys"):
            return []
        if "/instructions-bundle/file?path=AGENTS.md" in path:
            agent_id = path.split("/agents/", 1)[1].split("/", 1)[0]
            agent = next(row for row in self.agents if row["id"] == agent_id)
            slug = str(agent["metadata"]["specialistRole"])
            content = (ROOT / f"deploy/specialists/{slug}.md").read_text(encoding="utf-8")
            return {
                "path": "AGENTS.md",
                "size": len(content.encode("utf-8")),
                "language": "markdown",
                "isEntryFile": True,
                "markdown": True,
                "editable": True,
                "virtual": False,
                "deprecated": False,
                "content": content,
            }
        raise AssertionError(path)

    def post(self, path: str, payload: dict[str, object] | None = None) -> object:
        if path.endswith("/environments"):
            row = {
                "id": f"00000000-0000-4000-8000-{len(self.environments) + 1:012d}",
                **(payload or {}),
            }
            self.environments.append(row)
            return row
        if "/probe?" in path:
            self.probes.append(path)
            return {"ok": True, "driver": "ssh"}
        raise AssertionError(path)

    def patch(self, path: str, payload: dict[str, object]) -> object:
        if path.endswith("/permissions"):
            agent_id = path.split("/agents/", 1)[1].split("/", 1)[0]
            agent = next(row for row in self.agents if row["id"] == agent_id)
            current = agent.get("permissions")
            assert isinstance(current, dict)
            agent["permissions"] = {**current, **payload}
            return agent
        raise AssertionError(path)


def main() -> None:
    api = Api()
    company_id = "33333333-3333-4333-8333-333333333333"
    ssh_secret_id = "11111111-1111-4111-8111-111111111111"
    provider_secret_id = "22222222-2222-4222-8222-222222222222"
    known_hosts = "[specialist-worker]:2222 ssh-ed25519 AAAATEST"
    environment_ids: dict[str, str] = {}

    for slug in ("product", "growth", "operations"):
        environment_ids[slug] = module["ensure_environment"](
            api,
            company_id,
            ssh_secret_id,
            provider_secret_id,
            known_hosts,
            slug,
            probe_environment=True,
        )

    assert module["expected_permissions"](
        company_id,
        "33333333-3333-4333-8333-333333333334",
        ["33333333-3333-4333-8333-333333333335"],
    ) == {
        "canCreateAgents": False,
        "canCreateSkills": False,
        "canAssignTasks": True,
        "trustPreset": "standard",
        "authorizationPolicy": {"trustPreset": "standard"},
    }

    assert len(set(environment_ids.values())) == 3
    assert len(api.probes) == 3
    for row, slug in zip(api.environments, ("product", "growth", "operations"), strict=True):
        assert row["driver"] == "ssh"
        assert row["status"] == "active"
        assert row["metadata"] == {
            "nix": module["ENVIRONMENT_MARKER"],
            "specialistRole": slug,
        }
        config = row["config"]
        assert isinstance(config, dict)
        assert config["host"] == "specialist-worker"
        assert config["port"] == 2222
        assert config["username"] == "worker"
        assert config["remoteWorkspacePath"] == f"/workspaces/{slug}"
        assert config["privateKey"] is None
        assert config["privateKeySecretRef"]["secretId"] == ssh_secret_id
        assert config["knownHosts"] == known_hosts
        assert config["strictHostKeyChecking"] is True
        assert row["envVars"] == {
            "OPENCODE_API_KEY": {
                "type": "secret_ref",
                "secretId": provider_secret_id,
                "version": "latest",
                "projectionClass": "unclassified",
                "projectionAllowlistKey": None,
            }
        }

    chief_id = "33333333-3333-4333-8333-333333333336"
    project_id = "33333333-3333-4333-8333-333333333334"
    former_permissions = {
        "canCreateAgents": False,
        "canCreateSkills": False,
        "canAssignTasks": True,
        "trustPreset": "low_trust_review",
        "authorizationPolicy": {
            "trustPreset": "low_trust_review",
            "reviewPreset": {
                "id": "low_trust_review",
                "version": 1,
                "rawOutputDisposition": "quarantine",
            },
            "trustBoundary": {
                "mode": "low_trust_review",
                "companyId": company_id,
                "projectIds": [project_id],
            },
        },
    }
    for index, (slug, name, role, capabilities) in enumerate(module["ROLES"], start=10):
        agent_id = f"00000000-0000-4000-8000-{index:012d}"
        api.agents.append(
            {
                "id": agent_id,
                "name": name,
                "role": role,
                "reportsTo": chief_id,
                "capabilities": capabilities,
                "adapterType": "paperclip_runner",
                "adapterConfig": module["expected_adapter_config"](company_id, agent_id),
                "defaultEnvironmentId": environment_ids[slug],
                "budgetMonthlyCents": 0,
                "runtimeConfig": {"heartbeat": {"enabled": False, "maxConcurrentRuns": 1}},
                "status": "idle",
                "permissions": dict(former_permissions),
                "metadata": {"nix": module["AGENT_MARKER"], "specialistRole": slug},
            }
        )
    converged = module["ensure_agents"](
        api, company_id, chief_id, project_id, environment_ids
    )
    assert set(converged) == {"product", "growth", "operations"}
    expected_permissions = module["expected_permissions"](
        company_id, project_id, list(converged.values())
    )
    assert all(row["permissions"] == expected_permissions for row in api.agents)
    assert all(
        "reviewPreset" not in row["permissions"]["authorizationPolicy"]
        and "trustBoundary" not in row["permissions"]["authorizationPolicy"]
        for row in api.agents
    )

    with tempfile.TemporaryDirectory() as directory:
        provider_file = Path(directory) / "specialist-provider.env"
        provider_file.write_text("OPENCODE_API_KEY=fixture-opencode-key\n", encoding="utf-8")
        provider_file.chmod(0o600)
        assert module["read_provider_keys"](provider_file) == {
            "OPENCODE_API_KEY": "fixture-opencode-key"
        }
        provider_file.write_text(
            "OPENCODE_API_KEY=fixture-opencode-key\nEXTRA_SECRET=forbidden\n",
            encoding="utf-8",
        )
        try:
            module["read_provider_keys"](provider_file)
        except module["BootstrapError"]:
            pass
        else:
            raise AssertionError("legacy provider keys must fail closed")

    print("Paperclip specialist local-SSH bootstrap tests passed.")


if __name__ == "__main__":
    main()
