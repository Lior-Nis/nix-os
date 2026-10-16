#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import tempfile


REPO = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_loader(
    "nix_paperclip_chief_topology",
    importlib.machinery.SourceFileLoader(
        "nix_paperclip_chief_topology", str(REPO / "scripts/check-paperclip-chief-topology")
    ),
)
assert spec and spec.loader
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


COMPANY_ID = "11111111-1111-4111-8111-111111111111"
CHIEF_ID = "22222222-2222-4222-8222-222222222222"
TEMP_ID = "33333333-3333-4333-8333-333333333333"
KEY_ID = "44444444-4444-4444-8444-444444444444"
REQUEST_ID = "55555555-5555-4555-8555-555555555555"
BOARD_USER_ID = "lior-user"


def safe_fixture() -> tuple[dict, dict]:
    metadata = {
        "credentialPresent": True,
        "credentialSha256": "a" * 64,
        "gatewayKeySha256": "d" * 64,
        "companyId": COMPANY_ID,
        "agentId": CHIEF_ID,
        "receipt": {
            "requestId": REQUEST_ID,
            "companyId": COMPANY_ID,
            "agentId": CHIEF_ID,
            "keyId": KEY_ID,
        },
    }
    snapshot = {
        "agents": [
            {
                "id": CHIEF_ID,
                "name": "Chief of Staff",
                "role": "ceo",
                "status": "idle",
                "reportsTo": None,
                "hasNixBootstrap": False,
                "marker": None,
                "budgetMonthlyCents": 0,
                "permissions": {
                    "canCreateAgents": False,
                    "canCreateSkills": False,
                    "canAssignTasks": True,
                },
                "tempAdapterSafe": None,
                "tempRuntimeSafe": None,
                "chiefGatewaySafe": True,
                "chiefHasApiKey": True,
                "chiefGatewayKeyHash": "d" * 64,
            },
            {
                "id": TEMP_ID,
                "name": "Nix Bootstrap CEO",
                "role": "general",
                "status": "paused",
                "reportsTo": CHIEF_ID,
                "hasNixBootstrap": True,
                "marker": {"kind": "temporary-chief-manager", "version": 1},
                "budgetMonthlyCents": 0,
                "permissions": {
                    "canCreateAgents": False,
                    "canCreateSkills": False,
                    "canAssignTasks": False,
                },
                "tempAdapterSafe": True,
                "tempRuntimeSafe": True,
                "chiefGatewaySafe": None,
                "chiefHasApiKey": None,
                "chiefGatewayKeyHash": None,
            },
            {
                "id": "66666666-6666-4666-8666-666666666666",
                "name": "Future task-scoped worker",
                "role": "general",
                "status": "idle",
                "reportsTo": CHIEF_ID,
                "hasNixBootstrap": False,
                "marker": None,
                "budgetMonthlyCents": 0,
                "permissions": {},
                "tempAdapterSafe": None,
                "tempRuntimeSafe": None,
                "chiefGatewaySafe": None,
                "chiefHasApiKey": None,
                "chiefGatewayKeyHash": None,
            },
        ],
        "keys": [
            {
                "id": KEY_ID,
                "agentId": CHIEF_ID,
                "revoked": False,
                "scopeKind": "standard",
                "responsibleUserId": BOARD_USER_ID,
                "keyHash": "a" * 64,
            }
        ],
    }
    return metadata, snapshot


def expect_rejected(mutator, message: str) -> None:
    metadata, snapshot = safe_fixture()
    mutator(metadata, snapshot)
    try:
        checker.validate_topology(metadata, snapshot, BOARD_USER_ID)
    except checker.TopologyError as exc:
        assert message in str(exc)
    else:
        raise AssertionError(f"unsafe topology unexpectedly accepted: {message}")


def main() -> None:
    metadata, snapshot = safe_fixture()
    checker.validate_topology(metadata, snapshot, BOARD_USER_ID)

    expect_rejected(
        lambda _metadata, value: value["agents"][0]["permissions"].update(
            {"canCreateAgents": True}
        ),
        "claimed Chief permissions",
    )
    expect_rejected(
        lambda _metadata, value: value["agents"][0].update(
            {"chiefGatewayKeyHash": "e" * 64}
        ),
        "gateway key does not match",
    )
    expect_rejected(
        lambda _metadata, value: value["agents"].append(
            {
                "id": "77777777-7777-4777-8777-777777777777",
                "role": "ceo",
                "reportsTo": None,
            }
        ),
        "sole root CEO",
    )
    expect_rejected(
        lambda _metadata, value: value["agents"][1].update({"tempAdapterSafe": False}),
        "not inert and subordinate",
    )
    expect_rejected(
        lambda _metadata, value: value["agents"][2].update(
            {"hasNixBootstrap": True, "marker": {"kind": "unexpected"}}
        ),
        "marker is not unique",
    )
    expect_rejected(
        lambda _metadata, value: value["keys"].append(
            {
                "id": "88888888-8888-4888-8888-888888888888",
                "agentId": CHIEF_ID,
                "revoked": False,
                "scopeKind": "standard",
                "responsibleUserId": BOARD_USER_ID,
                "keyHash": "a" * 64,
            }
        ),
        "exactly one active API key",
    )
    expect_rejected(
        lambda _metadata, value: value["keys"][0].update(
            {"responsibleUserId": "different-user"}
        ),
        "ownership/scope",
    )
    expect_rejected(
        lambda _metadata, value: value["keys"][0].update({"keyHash": "c" * 64}),
        "credential does not match",
    )
    expect_rejected(
        lambda _metadata, value: value["keys"].append(
            {
                "id": "99999999-9999-4999-8999-999999999999",
                "agentId": TEMP_ID,
                "revoked": False,
                "scopeKind": "standard",
                "responsibleUserId": BOARD_USER_ID,
                "keyHash": "b" * 64,
            }
        ),
        "temporary bootstrap manager has an active API key",
    )

    with tempfile.TemporaryDirectory(prefix="nix-chief-topology-") as directory:
        profile = pathlib.Path(directory)
        token = "fixture-credential"
        (profile / ".env").write_text(
            f"PAPERCLIP_API_KEY={token}\n"
            f"PAPERCLIP_COMPANY_ID={COMPANY_ID}\n"
            f"PAPERCLIP_AGENT_ID={CHIEF_ID}\n",
            encoding="utf-8",
        )
        (profile / ".paperclip-claim-receipt.json").write_text(
            json.dumps(metadata["receipt"]), encoding="utf-8"
        )
        (profile / ".env").chmod(0o600)
        (profile / ".paperclip-claim-receipt.json").chmod(0o600)
        fixture_gid = (profile / ".env").lstat().st_gid
        read = checker.read_claim_metadata(
            profile, expected_uid=os.geteuid(), expected_gid=fixture_gid
        )
        rendered = json.dumps(read)
        assert read["credentialSha256"] != token
        assert read["companyId"] == metadata["companyId"]
        assert read["agentId"] == metadata["agentId"]
        assert read["receipt"] == metadata["receipt"]
        assert token not in rendered

        stage = profile / "mcp-tokens/nix-os-paperclip-claim-stage.json"
        stage.parent.mkdir()
        stage.write_text("{}", encoding="utf-8")
        try:
            checker.read_claim_metadata(
                profile, expected_uid=os.geteuid(), expected_gid=fixture_gid
            )
        except checker.TopologyError as exc:
            assert "staged claim" in str(exc)
        else:
            raise AssertionError("staged claim unexpectedly passed topology metadata inspection")

        stage.unlink()
        dangling = profile / "mcp-tokens/nix-os-paperclip-claim-stage.json"
        dangling.symlink_to(profile / "missing-stage-target")
        try:
            checker.read_claim_metadata(
                profile, expected_uid=os.geteuid(), expected_gid=fixture_gid
            )
        except checker.TopologyError as exc:
            assert "staged claim" in str(exc)
        else:
            raise AssertionError("dangling staged-claim symlink unexpectedly passed inspection")
        dangling.unlink()

        env_path = profile / ".env"
        real_env = profile / ".env.real"
        env_path.rename(real_env)
        env_path.symlink_to(real_env)
        try:
            checker.read_claim_metadata(
                profile, expected_uid=os.geteuid(), expected_gid=fixture_gid
            )
        except checker.TopologyError as exc:
            assert "mode-0600 regular file" in str(exc)
        else:
            raise AssertionError("symlinked credential file unexpectedly passed inspection")

    print("Paperclip Chief topology safety tests passed.")


if __name__ == "__main__":
    main()
