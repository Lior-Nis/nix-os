#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import importlib.machinery
import importlib.util
import os
import pathlib
import tempfile


REPO = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_loader(
    "nix_paperclip_specialist_topology",
    importlib.machinery.SourceFileLoader(
        "nix_paperclip_specialist_topology",
        str(REPO / "scripts/check-paperclip-specialist-topology"),
    ),
)
assert spec and spec.loader
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


COMPANY_ID = "11111111-1111-4111-8111-111111111111"
CHIEF_ID = "22222222-2222-4222-8222-222222222222"
PROJECT_ID = "33333333-3333-4333-8333-333333333333"
ENVIRONMENT_ID = "44444444-4444-4444-8444-444444444444"
PRODUCT_ID = "55555555-5555-4555-8555-555555555555"
GROWTH_ID = "66666666-6666-4666-8666-666666666666"
OPERATIONS_ID = "77777777-7777-4777-8777-777777777777"
DAYTONA_SECRET_ID = "88888888-8888-4888-8888-888888888888"
PROVIDER_SECRET_ID = "99999999-9999-4999-8999-999999999999"
DAYTONA_KEY = "fixture-daytona-key"
PROVIDER_KEY = "fixture-provider-key"
DAYTONA_FINGERPRINT = hashlib.sha256(DAYTONA_KEY.encode()).hexdigest()
PROVIDER_FINGERPRINT = hashlib.sha256(PROVIDER_KEY.encode()).hexdigest()


def expected() -> dict:
    return {
        "chiefId": CHIEF_ID,
        "projectId": PROJECT_ID,
        "environmentId": ENVIRONMENT_ID,
        "specialistIds": {
            "product": PRODUCT_ID,
            "growth": GROWTH_ID,
            "operations": OPERATIONS_ID,
        },
        "secretFingerprints": {
            "nix-specialist-daytona-api-key": DAYTONA_FINGERPRINT,
            "nix-specialist-opencode-api-key": PROVIDER_FINGERPRINT,
        },
    }


def safe_fixture() -> dict:
    specialist_ids = [PRODUCT_ID, GROWTH_ID, OPERATIONS_ID]
    permissions = checker.expected_permissions(COMPANY_ID, PROJECT_ID, specialist_ids)
    rows = []
    for slug, agent_id in zip(checker.ROLE_SPECS, specialist_ids, strict=True):
        name, role = checker.ROLE_SPECS[slug]
        rows.append(
            {
                "id": agent_id,
                "companyId": COMPANY_ID,
                "name": name,
                "role": role,
                "title": f"Task-scoped {name} specialist",
                "status": "idle",
                "reportsTo": CHIEF_ID,
                "capabilities": "fixture",
                "adapterType": "paperclip_runner",
                "adapterConfig": checker.expected_adapter_config(COMPANY_ID, agent_id),
                "runtimeConfig": {"heartbeat": {"enabled": False, "maxConcurrentRuns": 1}},
                "permissions": copy.deepcopy(permissions),
                "budgetMonthlyCents": 0,
                "defaultEnvironmentId": ENVIRONMENT_ID,
                "metadata": {
                    "nix": copy.deepcopy(checker.AGENT_MARKER),
                    "specialistRole": slug,
                },
            }
        )
    rows.extend(
        [
            {
                "id": CHIEF_ID,
                "companyId": COMPANY_ID,
                "name": "Chief of Staff",
                "role": "ceo",
                "title": "Chief of Staff",
                "status": "idle",
                "reportsTo": None,
                "capabilities": "fixture",
                "adapterType": "hermes_gateway",
                "adapterConfig": {},
                "runtimeConfig": {},
                "permissions": {
                    "canCreateAgents": False,
                    "canCreateSkills": False,
                    "canAssignTasks": True,
                },
                "budgetMonthlyCents": 0,
                "defaultEnvironmentId": None,
                "metadata": {},
            },
            {
                "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "companyId": COMPANY_ID,
                "name": "Nix Bootstrap CEO",
                "role": "general",
                "title": "Bootstrap",
                "status": "paused",
                "reportsTo": CHIEF_ID,
                "capabilities": "fixture",
                "adapterType": "process",
                "adapterConfig": {},
                "runtimeConfig": {"heartbeat": {"enabled": False, "maxConcurrentRuns": 1}},
                "permissions": {},
                "budgetMonthlyCents": 0,
                "defaultEnvironmentId": None,
                "metadata": {},
            },
        ]
    )
    return {
        "chief": {
            "id": CHIEF_ID,
            "companyId": COMPANY_ID,
            "name": "Chief of Staff",
            "role": "ceo",
            "status": "idle",
            "reportsTo": None,
            "adapterType": "hermes_gateway",
            "adapterConfig": {},
            "permissions": {
                "canCreateAgents": False,
                "canCreateSkills": False,
                "canAssignTasks": True,
            },
        },
        "project": {"id": PROJECT_ID, "companyId": COMPANY_ID},
        "agents": rows,
        "keys": [
            {"agentId": PRODUCT_ID, "revoked": True},
            {"agentId": GROWTH_ID, "revoked": True},
        ],
        "environments": [
            {
                "id": ENVIRONMENT_ID,
                "name": "Nix task-scoped Daytona sandbox",
                "driver": "sandbox",
                "status": "active",
                "config": {
                    "provider": "daytona",
                    "apiKey": DAYTONA_SECRET_ID,
                    "apiUrl": None,
                    "image": "daytonaio/sandbox:0.8.0@sha256:eadf88e4391072b7ad4bed27d9cadfc9fe9d8ed375d9219d34c2ccb518f213e3",
                    "target": "eu",
                    "snapshot": None,
                    "language": None,
                    "timeoutMs": 300000,
                    "livenessTimeoutMs": 30000,
                    "cpu": 1,
                    "memory": 2,
                    "disk": 5,
                    "gpu": None,
                    "autoStopInterval": 15,
                    "autoArchiveInterval": 60,
                    "reuseLease": False,
                    "archiveOnRelease": False,
                    "runnerLifecycleMode": "per_turn",
                    "autoDeleteInterval": 60,
                },
                "envVars": {
                    "OPENCODE_API_KEY": {
                        "type": "secret_ref",
                        "secretId": PROVIDER_SECRET_ID,
                        "version": "latest",
                        "projectionClass": "unclassified",
                        "projectionAllowlistKey": None,
                    }
                },
                "metadata": {"nix": copy.deepcopy(checker.ENVIRONMENT_MARKER)},
            }
        ],
        "secrets": [
            {
                "id": DAYTONA_SECRET_ID,
                "companyId": COMPANY_ID,
                "key": "nix-specialist-daytona-api-key",
                "status": "active",
                "managedMode": "paperclip_managed",
                "description": f"Nix Slice 3 daytona; sha256={DAYTONA_FINGERPRINT}",
                "deleted": False,
            },
            {
                "id": PROVIDER_SECRET_ID,
                "companyId": COMPANY_ID,
                "key": "nix-specialist-opencode-api-key",
                "status": "active",
                "managedMode": "paperclip_managed",
                "description": f"Nix Slice 3 provider; sha256={PROVIDER_FINGERPRINT}",
                "deleted": False,
            },
        ],
        "bindings": [
            {
                "secretId": DAYTONA_SECRET_ID,
                "targetType": "environment",
                "targetId": ENVIRONMENT_ID,
                "configPath": "apiKey",
                "versionSelector": "latest",
                "required": True,
            },
            {
                "secretId": PROVIDER_SECRET_ID,
                "targetType": "environment",
                "targetId": ENVIRONMENT_ID,
                "configPath": "env.OPENCODE_API_KEY",
                "versionSelector": "latest",
                "required": True,
            },
        ],
        "unsafeLeases": [],
        "unsafeRuns": [],
        "plugins": [
            {
                "id": "aaaaaaaa-1111-4111-8111-111111111111",
                "pluginKey": "paperclip.daytona-sandbox-provider",
                "packageName": "@paperclipai/plugin-daytona",
                "version": "0.1.7",
                "status": "ready",
                "lastError": None,
                "manifest": {
                    "id": "paperclip.daytona-sandbox-provider",
                    "version": "0.1.7",
                    "capabilities": ["environment.drivers.register"],
                    "environmentDrivers": [{"driverKey": "daytona", "kind": "sandbox_provider"}],
                },
            }
        ],
        "experimental": {"enableEnvironments": True, "enableNativeRunner": True},
        "markedSpecialistCount": 3,
    }


def expect_rejected(mutator, message: str) -> None:
    fixture = safe_fixture()
    mutator(fixture)
    try:
        checker.validate_topology(expected(), fixture)
    except checker.TopologyError as exc:
        assert message in str(exc), (message, str(exc))
    else:
        raise AssertionError(f"unsafe specialist topology unexpectedly accepted: {message}")


def main() -> None:
    checker.validate_topology(expected(), safe_fixture())

    expect_rejected(
        lambda value: value["chief"].update({"adapterType": "paperclip_runner"}),
        "Chief identity or adapter",
    )
    expect_rejected(
        lambda value: value["project"].update({"companyId": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"}),
        "approved project",
    )
    expect_rejected(
        lambda value: value["experimental"].update({"enableNativeRunner": False}),
        "native runner",
    )
    expect_rejected(
        lambda value: value["agents"][0].update({"name": "Product Copy"}),
        "product specialist topology",
    )
    expect_rejected(
        lambda value: value["agents"][0].update({"status": "paused"}),
        "product specialist topology",
    )
    expect_rejected(
        lambda value: value["agents"][1].update({"status": "error"}),
        "growth specialist topology",
    )
    expect_rejected(
        lambda value: value["agents"][2].update({"status": "active"}),
        "operations specialist topology",
    )
    expect_rejected(
        lambda value: value["agents"][1]["adapterConfig"].update(
            {"model": "opencode/another-model"}
        ),
        "growth specialist topology",
    )
    expect_rejected(
        lambda value: value["agents"][0]["adapterConfig"].update(
            {"instructionsRootPath": "/tmp/untrusted-instructions"}
        ),
        "product specialist topology",
    )
    expect_rejected(
        lambda value: value["agents"][2]["runtimeConfig"]["heartbeat"].update(
            {"enabled": True}
        ),
        "operations specialist topology",
    )
    expect_rejected(
        lambda value: value["agents"][0]["permissions"]["authorizationPolicy"][
            "trustBoundary"
        ].update({"projectIds": []}),
        "product specialist trust boundary",
    )
    expect_rejected(
        lambda value: value["keys"].append({"agentId": GROWTH_ID, "revoked": False}),
        "active API key",
    )
    expect_rejected(
        lambda value: value["environments"][0]["config"].update(
            {"reuseLease": True}
        ),
        "Daytona environment configuration",
    )
    expect_rejected(
        lambda value: value["environments"][0]["config"].update(
            {"apiUrl": "https://attacker.invalid"}
        ),
        "Daytona environment configuration",
    )
    expect_rejected(
        lambda value: value["environments"][0]["config"].update(
            {"unexpectedCredentialSink": "enabled"}
        ),
        "Daytona environment configuration",
    )
    expect_rejected(
        lambda value: value["environments"][0]["config"].update({"apiKey": "plaintext"}),
        "secret references",
    )
    expect_rejected(
        lambda value: value["environments"][0]["envVars"].update(
            {"CHIEF_API_KEY": {"type": "secret_ref"}}
        ),
        "Daytona environment configuration",
    )
    expect_rejected(
        lambda value: value["secrets"][1].update({"status": "disabled"}),
        "opencode-api-key",
    )
    expect_rejected(
        lambda value: value["secrets"][0].update(
            {"description": f"Nix Slice 3 daytona; sha256={'0' * 64}"}
        ),
        "daytona-api-key",
    )
    expect_rejected(
        lambda value: value["plugins"][0].update({"version": "latest"}),
        "Daytona plugin metadata",
    )
    expect_rejected(
        lambda value: value["environments"].append(copy.deepcopy(value["environments"][0])),
        "environment is not unique",
    )
    expect_rejected(
        lambda value: value["agents"].append(
            {
                "id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                "name": "Engineering Manager",
                "title": "Engineering Manager",
                "role": "general",
                "status": "idle",
            }
        ),
        "unexpected Engineering Manager",
    )
    expect_rejected(
        lambda value: value["agents"].append({
            "id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            "status": "idle",
            "adapterType": "paperclip_runner",
        }),
        "outside the specialist allowlist",
    )
    expect_rejected(
        lambda value: value["bindings"][0].update({"configPath": "wrong"}),
        "secret binding rows",
    )
    expect_rejected(
        lambda value: value["unsafeLeases"].append({"id": "lease", "status": "active"}),
        "lease blocks a safe backup",
    )
    expect_rejected(
        lambda value: value["unsafeLeases"].append({"id": "lease", "status": "retained"}),
        "lease blocks a safe backup",
    )
    expect_rejected(
        lambda value: value["unsafeLeases"].append({"id": "lease", "status": "future_state"}),
        "lease blocks a safe backup",
    )
    expect_rejected(
        lambda value: value["unsafeLeases"].append({"id": "lease", "status": None}),
        "lease blocks a safe backup",
    )
    expect_rejected(
        lambda value: value["unsafeRuns"].append({"id": "run", "status": "running"}),
        "specialist run blocks a safe backup",
    )
    expect_rejected(
        lambda value: value["unsafeRuns"].append({"id": "run", "status": "scheduled_retry"}),
        "specialist run blocks a safe backup",
    )
    expect_rejected(
        lambda value: value["unsafeRuns"].append({"id": "run", "status": "future_state"}),
        "specialist run blocks a safe backup",
    )
    expect_rejected(
        lambda value: value["unsafeRuns"].append({"id": "run", "status": None}),
        "specialist run blocks a safe backup",
    )

    query = checker.build_topology_query(
        CHIEF_ID,
        PROJECT_ID,
        ENVIRONMENT_ID,
        {"product": PRODUCT_ID, "growth": GROWTH_ID, "operations": OPERATIONS_ID},
    )
    assert "company_secret_versions" not in query
    assert "value_sha256" not in query
    assert "FROM agent_api_keys" in query
    assert "FROM instance_settings" in query
    assert "FROM environments" in query
    assert "FROM company_secret_bindings" in query
    assert "FROM environment_leases" in query
    assert "(status IS NULL OR status NOT IN ('released', 'expired', 'failed'))" in query
    assert (
        "(status IS NULL OR status NOT IN "
        "('succeeded', 'interrupted', 'failed', 'cancelled', 'timed_out'))"
        in query
    )
    assert "cancelling" not in query
    try:
        checker.build_topology_query(
            f"{CHIEF_ID}' OR true --",
            PROJECT_ID,
            ENVIRONMENT_ID,
            {"product": PRODUCT_ID, "growth": GROWTH_ID, "operations": OPERATIONS_ID},
        )
    except checker.TopologyError as exc:
        assert "UUID" in str(exc)
    else:
        raise AssertionError("SQL identifier injection unexpectedly reached query rendering")

    with tempfile.TemporaryDirectory(prefix="nix-specialist-topology-") as directory:
        root = pathlib.Path(directory)
        config = root / ".env"
        config.write_text(
            f"NIX_PRODUCT_AGENT_ID={PRODUCT_ID}\n"
            f"NIX_GROWTH_AGENT_ID={GROWTH_ID}\n"
            f"NIX_OPERATIONS_AGENT_ID={OPERATIONS_ID}\n"
            f"NIX_SPECIALIST_AGENT_IDS={PRODUCT_ID},{GROWTH_ID},{OPERATIONS_ID}\n",
            encoding="utf-8",
        )
        assert checker.specialist_ids_from_config(config) == expected()["specialistIds"]
        config.write_text(config.read_text(encoding="utf-8") + f"NIX_PRODUCT_AGENT_ID={PRODUCT_ID}\n")
        try:
            checker.specialist_ids_from_config(config)
        except checker.TopologyError as exc:
            assert "exactly once" in str(exc)
        else:
            raise AssertionError("duplicate specialist configuration unexpectedly passed")

        provider_file = root / "provider.env"
        provider_file.write_text(
            f"DAYTONA_API_KEY={DAYTONA_KEY}\nOPENCODE_API_KEY={PROVIDER_KEY}\n",
            encoding="utf-8",
        )
        for path in (provider_file,):
            path.chmod(0o600)
        assert checker.read_provider_key_file(provider_file) == {
            "DAYTONA_API_KEY": DAYTONA_KEY,
            "OPENCODE_API_KEY": PROVIDER_KEY,
        }

        provider_file.write_text(
            f"DAYTONA_API_KEY={DAYTONA_KEY}\n"
            "OPENCODE_API_KEY=REPLACE_WITH_RESTRICTED_OPENCODE_API_KEY\n",
            encoding="utf-8",
        )
        try:
            checker.read_provider_key_file(provider_file)
        except checker.TopologyError as exc:
            assert "usable key" in str(exc)
        else:
            raise AssertionError("provider placeholder unexpectedly passed")

        provider_file.write_text(
            f"DAYTONA_API_KEY={DAYTONA_KEY}\nOPENCODE_API_KEY={PROVIDER_KEY}\nANOTHER_SECRET=unsafe\n",
            encoding="utf-8",
        )
        try:
            checker.read_provider_key_file(provider_file)
        except checker.TopologyError as exc:
            assert "reviewed bindings" in str(exc)
        else:
            raise AssertionError("extra provider binding unexpectedly passed")

        linked = root / "provider-linked"
        os.link(provider_file, linked)
        try:
            checker.read_locked_file(provider_file, "provider file")
        except checker.TopologyError as exc:
            assert "single-link" in str(exc)
        else:
            raise AssertionError("hard-linked provider file unexpectedly passed")

    print("Paperclip specialist topology safety tests passed.")


if __name__ == "__main__":
    main()
