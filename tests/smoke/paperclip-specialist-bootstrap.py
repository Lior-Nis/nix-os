#!/usr/bin/env python3
"""Focused contract tests for the Slice 3 Paperclip specialist bootstrap."""

from __future__ import annotations

import pathlib
import runpy
import tempfile
from types import SimpleNamespace
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[2]
module = runpy.run_path(str(ROOT / "scripts/bootstrap-paperclip-specialists"))


class FakeApi:
    def __init__(self) -> None:
        self.environments: list[dict] = []
        self.agents: list[dict] = []
        self.secrets: list[dict] = []
        self.plugins: list[dict] = []
        self.permissions: dict[str, dict] = {}
        self.probe_count = 0
        self.leases: list[dict] = []
        self.next_id = 0

    def new_id(self) -> str:
        self.next_id += 1
        return f"00000000-0000-4000-8000-{self.next_id:012d}"

    def get(self, path: str):
        if path == "/api/plugins":
            return list(self.plugins)
        if path.endswith("/environments/capabilities"):
            plugin = self.plugins[0]
            return {"sandboxProviders": {"daytona": {
                "status": "supported",
                "supportsSavedProbe": True,
                "supportsUnsavedProbe": True,
                "supportsRunExecution": True,
                "source": "plugin",
                "pluginKey": plugin["pluginKey"],
                "pluginId": plugin["id"],
            }}}
        if path.endswith("/environments"):
            return list(self.environments)
        if path.endswith("/leases"):
            return list(self.leases)
        if path.endswith("/agents"):
            return list(self.agents)
        if path.endswith("/secrets"):
            return list(self.secrets)
        if path.endswith("/keys"):
            return []
        raise AssertionError(f"unexpected GET {path}")

    def post(self, path: str, payload=None):
        payload = dict(payload or {})
        if path == "/api/plugins/install":
            assert payload == {
                "packageName": "@paperclipai/plugin-daytona",
                "version": "2026.916.1",
            }
            row = {
                "id": self.new_id(),
                "pluginKey": "paperclip.daytona-sandbox-provider",
                "packageName": "@paperclipai/plugin-daytona",
                "version": "0.1.7",
                "status": "ready",
                "manifestJson": {
                    "id": "paperclip.daytona-sandbox-provider",
                    "version": "0.1.7",
                    "capabilities": ["environment.drivers.register"],
                    "environmentDrivers": [{"driverKey": "daytona", "kind": "sandbox_provider"}],
                },
            }
            self.plugins.append(row)
            return row
        if path.endswith("/secrets"):
            row = {**payload, "id": self.new_id(), "status": "active", "managedMode": "paperclip_managed"}
            row.pop("value", None)
            self.secrets.append(row)
            return row
        if path.endswith("/environments"):
            row = {**payload, "id": self.new_id()}
            self.environments.append(row)
            return row
        if "/environments/" in path and "/probe" in path:
            self.probe_count += 1
            environment_id = path.split("/environments/", 1)[1].split("/", 1)[0]
            lease = {
                "id": self.new_id(),
                "environmentId": environment_id,
                "status": "released",
                "provider": "daytona",
                "providerLeaseId": self.new_id(),
                "leasePolicy": "ephemeral",
                "issueId": None,
                "heartbeatRunId": None,
                "executionWorkspaceId": None,
            }
            self.leases.append(lease)
            return {"ok": True, "summary": "reachable", "details": {"leaseId": lease["id"]}}
        if path.endswith("/agents"):
            agent_id = self.new_id()
            company_id = path.split("/companies/", 1)[1].split("/", 1)[0]
            instructions_root = (
                f"/paperclip/instances/default/companies/{company_id}/agents/"
                f"{agent_id}/instructions"
            )
            row = {
                **payload,
                "id": agent_id,
                "status": "idle",
                "adapterConfig": {
                    **payload["adapterConfig"],
                    "instructionsFilePath": f"{instructions_root}/AGENTS.md",
                    "instructionsRootPath": instructions_root,
                    "instructionsEntryFile": "AGENTS.md",
                    "instructionsBundleMode": "managed",
                },
            }
            self.agents.append(row)
            return row
        raise AssertionError(f"unexpected POST {path}")

    def patch(self, path: str, payload):
        if path.endswith("/permissions"):
            self.permissions[path.split("/")[3]] = payload
            return payload
        raise AssertionError(f"unexpected PATCH {path}")


def main() -> None:
    source = (ROOT / "scripts/bootstrap-paperclip-specialists").read_text(encoding="utf-8")
    assert '"requestedAccess": "instance_admin_required"' in source
    assert 'identity.get("isInstanceAdmin") is not True' in source
    company = "11111111-1111-4111-8111-111111111111"
    chief = "22222222-2222-4222-8222-222222222222"
    project = "33333333-3333-4333-8333-333333333333"
    daytona_secret = "44444444-4444-4444-8444-444444444444"
    provider_secret = "55555555-5555-4555-8555-555555555555"
    api = FakeApi()

    with tempfile.TemporaryDirectory() as directory:
        config = pathlib.Path(directory) / ".env"
        config.write_text("COMPOSE_PROJECT_NAME=nix-test\n", encoding="utf-8")
        with patch("subprocess.run", side_effect=[
            SimpleNamespace(returncode=0, stdout="container-id\n"),
            SimpleNamespace(returncode=0, stdout=module["PAPERCLIP_IMAGE"] + "\n"),
        ]) as subprocess_run:
            module["verify_live_paperclip_image"](config)
        assert subprocess_run.call_count == 2
        with patch("subprocess.run", side_effect=[
            SimpleNamespace(returncode=0, stdout="container-id\n"),
            SimpleNamespace(returncode=0, stdout="ghcr.io/paperclipai/paperclip:wrong\n"),
        ]):
            try:
                module["verify_live_paperclip_image"](config)
            except module["BootstrapError"] as exc:
                assert "exact pinned image digest" in str(exc)
            else:
                raise AssertionError("an unpinned live Paperclip image passed preflight")

    plugin_id = module["ensure_daytona_plugin"](api, company)
    assert plugin_id == api.plugins[0]["id"]
    assert module["ensure_daytona_plugin"](api, company) == plugin_id
    assert len(api.plugins) == 1

    environment_id = module["ensure_environment"](
        api, company, daytona_secret, provider_secret, probe_environment=True,
    )
    assert api.probe_count == 1
    environment = api.environments[0]
    assert environment["driver"] == "sandbox"
    assert environment["config"]["provider"] == "daytona"
    assert environment["config"]["apiKey"] == daytona_secret
    assert environment["config"]["target"] == "eu"
    assert environment["config"]["cpu"] == 1
    assert environment["config"]["memory"] == 2
    assert environment["config"]["disk"] == 5
    assert environment["config"]["reuseLease"] is False
    assert environment["config"]["runnerLifecycleMode"] == "per_turn"
    assert environment["config"]["autoDeleteInterval"] == 60
    assert environment["envVars"] == {
        "OPENCODE_API_KEY": {
            "type": "secret_ref",
            "secretId": provider_secret,
            "version": "latest",
            "projectionClass": "unclassified",
            "projectionAllowlistKey": None,
        }
    }

    specialists = module["ensure_agents"](
        api, company, chief, project, environment_id
    )
    assert set(specialists) == {"product", "growth", "operations"}
    assert {row["role"] for row in api.agents} == {"pm", "cmo", "general"}
    assert all(row["reportsTo"] == chief for row in api.agents)
    assert all(row["adapterType"] == "paperclip_runner" for row in api.agents)
    assert all(
        row["adapterConfig"] == module["expected_adapter_config"](company, row["id"])
        for row in api.agents
    )
    assert all(row["runtimeConfig"] == {"heartbeat": {"enabled": False, "maxConcurrentRuns": 1}} for row in api.agents)
    assert all(row["budgetMonthlyCents"] == 0 for row in api.agents)
    assert all(row["instructionsBundle"]["entryFile"] == "AGENTS.md" for row in api.agents)

    ids = [specialists[slug] for slug, *_ in module["ROLES"]]
    assert set(api.permissions) == set(ids)
    for permissions in api.permissions.values():
        assert permissions["canCreateAgents"] is False
        assert permissions["canCreateSkills"] is False
        assert permissions["canAssignTasks"] is True
        assert permissions["trustPreset"] == "low_trust_review"
        boundary = permissions["authorizationPolicy"]["trustBoundary"]
        assert boundary["companyId"] == company
        assert boundary["projectIds"] == [project]
        assert boundary["allowedAgentIds"] == ids
        assert boundary["allowedToolClasses"] == ["tests.local"]

    # A second convergence accepts the exact marked topology and creates none.
    assert module["ensure_environment"](
        api, company, daytona_secret, provider_secret, probe_environment=True,
    ) == environment_id
    assert api.probe_count == 1
    api.leases[0]["status"] = "active"
    try:
        module["ensure_environment"](
            api, company, daytona_secret, provider_secret, probe_environment=True,
        )
    except module["BootstrapError"] as exc:
        assert "reconcile" in str(exc)
    else:
        raise AssertionError("unresolved Daytona lease allowed a second paid probe")
    api.leases[0]["status"] = "released"
    assert module["ensure_agents"](api, company, chief, project, environment_id) == specialists
    assert len(api.environments) == 1
    assert len(api.agents) == 3

    # Initial bootstrap is allowed only while both the checked-in config and
    # the running, hash-verified server enforce the empty restrictive floor.
    with tempfile.TemporaryDirectory() as directory:
        config = pathlib.Path(directory) / ".env"
        config.write_text(
            "NIX_PRODUCT_AGENT_ID=\n"
            "NIX_GROWTH_AGENT_ID=\n"
            "NIX_OPERATIONS_AGENT_ID=\n"
            "NIX_SPECIALIST_AGENT_IDS=\n"
            "NIX_SPECIALIST_ENVIRONMENT_ID=\n",
            encoding="utf-8",
        )
        compose_calls: list[tuple[str, ...]] = []
        with patch.dict(module["preflight_specialist_floor"].__globals__, {
            "run_compose": lambda _config, *arguments: compose_calls.append(arguments),
            "verify_live_paperclip_image": lambda _config: None,
        }), patch("subprocess.run") as subprocess_run:
            subprocess_run.return_value.returncode = 0
            assert module["preflight_specialist_floor"](config) is None
        assert compose_calls == [(
            "exec", "-T", "paperclip", "python3",
            "/opt/nix/patch-specialist-runtime.py", "--verify",
        )]
        assert subprocess_run.call_args.args[0][-5:] == [
            "sh", "-ec",
            'live=${NIX_PAPERCLIP_SPECIALIST_AGENT_IDS:-}; test -z "$live" || test "$live" = "$1"',
            "specialist-floor", "",
        ]

        config.write_text(config.read_text().replace(
            "NIX_PRODUCT_AGENT_ID=\n", f"NIX_PRODUCT_AGENT_ID={specialists['product']}\n"
        ))
        try:
            module["preflight_specialist_floor"](config)
        except module["BootstrapError"] as exc:
            assert "state is partial" in str(exc)
        else:
            raise AssertionError("partial specialist state passed the empty-floor preflight")

        config.write_text(
            f"NIX_PRODUCT_AGENT_ID={specialists['product']}\n"
            f"NIX_GROWTH_AGENT_ID={specialists['growth']}\n"
            f"NIX_OPERATIONS_AGENT_ID={specialists['operations']}\n"
            "NIX_SPECIALIST_AGENT_IDS=" + ",".join(
                specialists[slug] for slug, *_ in module["ROLES"]
            ) + "\n"
            f"NIX_SPECIALIST_ENVIRONMENT_ID={environment_id}\n",
            encoding="utf-8",
        )
        with patch.dict(module["preflight_specialist_floor"].__globals__, {
            "run_compose": lambda *_args: None,
            "verify_live_paperclip_image": lambda _config: None,
        }), patch("subprocess.run") as subprocess_run:
            subprocess_run.return_value.returncode = 0
            recovered = module["preflight_specialist_floor"](config)
        assert recovered == {
            **specialists,
            "environment": environment_id,
        }
        assert subprocess_run.call_args.args[0][-1] == ",".join(
            specialists[slug] for slug, *_ in module["ROLES"]
        )

        module["verify_configured_topology"](api, company, recovered)
        wrong = dict(recovered)
        wrong["product"] = "99999999-9999-4999-8999-999999999999"
        try:
            module["verify_configured_topology"](api, company, wrong)
        except module["BootstrapError"] as exc:
            assert "recovery identities do not exactly match" in str(exc)
        else:
            raise AssertionError("mismatched recovery topology unexpectedly passed")

    with tempfile.TemporaryDirectory() as directory:
        config = pathlib.Path(directory) / ".env"
        config.write_text("A=1\nNIX_PRODUCT_AGENT_ID=old\n", encoding="utf-8")
        config.chmod(0o600)
        module["update_config"](
            config,
            {
                "NIX_PRODUCT_AGENT_ID": specialists["product"],
                "NIX_GROWTH_AGENT_ID": specialists["growth"],
            },
        )
        contents = config.read_text(encoding="utf-8")
        assert contents.count("NIX_PRODUCT_AGENT_ID=") == 1
        assert f"NIX_PRODUCT_AGENT_ID={specialists['product']}" in contents
        assert f"NIX_GROWTH_AGENT_ID={specialists['growth']}" in contents
        assert config.stat().st_mode & 0o777 == 0o600

    # Both control-plane consumers reload the final allowlist after all three
    # identities exist. The empty-list server floor remains restrictive during
    # this short transition, so there is no separately reachable executor.
    api = FakeApi()
    module["ensure_daytona_plugin"](api, company)
    with tempfile.TemporaryDirectory() as directory:
        config = pathlib.Path(directory) / ".env"
        config.write_text("NIX_SPECIALIST_AGENT_IDS=\n", encoding="utf-8")
        config.chmod(0o600)
        compose_calls: list[tuple[str, ...]] = []

        def fake_compose(_config: pathlib.Path, *arguments: str) -> None:
            compose_calls.append(arguments)
            if arguments[:2] == ("up", "-d") and "paperclip" in arguments:
                assert len(api.agents) == 3
                assert "NIX_SPECIALIST_AGENT_IDS=" + ",".join(
                    row["id"] for row in api.agents
                ) in config.read_text(encoding="utf-8")

        with patch.dict(module["activate_specialists"].__globals__, {"run_compose": fake_compose}):
            activated = module["activate_specialists"](
                api, config, company, chief, project, environment_id
            )
        assert set(activated) == {"product", "growth", "operations"}
        assert compose_calls == [
            ("up", "-d", "--no-deps", "--wait", "--force-recreate", "paperclip", "hermes")
        ]

    # A creation failure never restarts the control-plane with a partial list.
    compose_calls = []
    with tempfile.TemporaryDirectory() as directory:
        config = pathlib.Path(directory) / ".env"
        config.write_text("NIX_SPECIALIST_AGENT_IDS=\n", encoding="utf-8")
        config.chmod(0o600)
        with patch.dict(module["activate_specialists"].__globals__, {
            "run_compose": lambda _config, *arguments: compose_calls.append(arguments),
            "ensure_agents": lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("fixture")),
        }):
            try:
                module["activate_specialists"](
                    FakeApi(), config, company, chief, project, environment_id
                )
            except RuntimeError:
                pass
            else:
                raise AssertionError("specialist creation failure unexpectedly succeeded")
        assert compose_calls == []

    print("Paperclip specialist bootstrap contract tests passed.")


if __name__ == "__main__":
    main()
