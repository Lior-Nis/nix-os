#!/usr/bin/env python3
"""Failure and atomic-persistence coverage for the in-profile claim helper."""

from __future__ import annotations

import importlib.util
import os
import pathlib
import stat
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("nix_claim_agent", ROOT / "deploy/hermes/claim-agent.py")
assert spec and spec.loader
claim_agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(claim_agent)


def profile(root: pathlib.Path) -> pathlib.Path:
    root.mkdir()
    (root / "config.yaml").write_text("model: {}\n")
    (root / "SOUL.md").write_text("# Chief\n")
    return root


with tempfile.TemporaryDirectory(prefix="nix-claim-test.") as temporary:
    base = pathlib.Path(temporary)
    good = profile(base / "good")
    claim_agent.profile_preflight(good)

    unsafe = profile(base / "unsafe")
    (unsafe / ".env").write_text("SAFE=value\n")
    (unsafe / ".env").chmod(0o644)
    try:
        claim_agent.profile_preflight(unsafe)
        raise AssertionError("unsafe credential mode unexpectedly passed")
    except claim_agent.ClaimError:
        pass

    state = {
        "id": "11111111-1111-4111-8111-111111111111",
        "companyId": "22222222-2222-4222-8222-222222222222",
        "claimSecret": "claim-secret-fixture",
    }
    original_request = claim_agent.request_json
    original_self = claim_agent.get_self

    preflight_request_count = 0

    def unexpected_request(*_args, **_kwargs):
        global preflight_request_count
        preflight_request_count += 1
        return {}

    claim_agent.request_json = unexpected_request
    try:
        claim_agent.claim(unsafe, state)
        raise AssertionError("unsafe destination unexpectedly reached claim")
    except claim_agent.ClaimError:
        pass
    assert preflight_request_count == 0

    claim_agent.request_json = lambda *_args, **_kwargs: {
        "token": "pcp_fixture_never_logged",
        "agentId": "33333333-3333-4333-8333-333333333333",
    }
    claim_agent.get_self = lambda *_args, **_kwargs: {
        "id": "33333333-3333-4333-8333-333333333333",
        "companyId": state["companyId"],
    }
    result = claim_agent.claim(good, state)
    assert result["agentId"] == "33333333-3333-4333-8333-333333333333"
    assert stat.S_IMODE((good / ".env").stat().st_mode) == 0o600
    assert (good / ".env").stat().st_uid == os.geteuid()
    assert (good / ".env").stat().st_gid == os.getegid()
    assert "PAPERCLIP_API_KEY=pcp_fixture_never_logged" in (good / ".env").read_text()
    assert not list(good.glob(".paperclip-claim-*.pending"))
    assert (good / ".paperclip-claim-receipt.json").is_file()
    assert stat.S_IMODE((good / ".paperclip-claim-receipt.json").stat().st_mode) == 0o600

    stale = profile(base / "stale-telegram")
    stale_env = stale / ".env"
    stale_env.write_text(
        "KEEP=value\n"
        "'TELEGRAM_BOT_TOKEN'=must-not-survive\n"
        "TELEGRAM_ALLOWED_USERS=999\n"
        "TELEGRAM_ALLOW_ALL_USERS=true\n"
        "GATEWAY_ALLOW_ALL_USERS=true\n",
        encoding="utf-8-sig",
    )
    stale_env.chmod(0o600)
    rendered = claim_agent.render_env(
        stale_env,
        "http://paperclip:3100",
        "pcp_render_fixture",
        state["companyId"],
        "55555555-5555-4555-8555-555555555555",
    ).decode()
    assert "KEEP=value" in rendered
    assert not any(key in rendered for key in claim_agent.EXTERNAL_ONLY_KEYS)

    recovered = profile(base / "recovered")
    recovered_env = recovered / ".env"
    recovered_env.write_bytes(claim_agent.render_env(
        recovered_env,
        "http://paperclip:3100",
        "pcp_recovered_fixture_key",
        state["companyId"],
        "44444444-4444-4444-8444-444444444444",
    ))
    recovered_env.chmod(0o600)
    marker = recovered / f'.paperclip-claim-{state["id"]}.pending'
    marker.write_text('{"fixture":true}\n')
    marker.chmod(0o600)
    recovery_request_count = 0

    def recovery_must_not_claim(*_args, **_kwargs):
        global recovery_request_count
        recovery_request_count += 1
        return {}

    claim_agent.request_json = recovery_must_not_claim
    claim_agent.get_self = lambda *_args, **_kwargs: {
        "id": "44444444-4444-4444-8444-444444444444",
        "companyId": state["companyId"],
    }
    recovered_result = claim_agent.claim(recovered, state)
    assert recovered_result == {
        "companyId": state["companyId"],
        "agentId": "44444444-4444-4444-8444-444444444444",
        "recovered": True,
    }
    assert recovery_request_count == 0
    assert recovered_env.read_text().count("PAPERCLIP_API_KEY=pcp_recovered_fixture_key") == 1
    assert not marker.exists()
    recovered_receipt = recovered / ".paperclip-claim-receipt.json"
    assert stat.S_IMODE(recovered_receipt.stat().st_mode) == 0o600
    assert recovered_receipt.stat().st_uid == os.geteuid()
    assert recovered_receipt.stat().st_gid == os.getegid()

    interrupted = profile(base / "interrupted")
    claim_agent.render_env = lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("fixture write failure"))
    try:
        claim_agent.claim(interrupted, state)
        raise AssertionError("post-claim persistence failure unexpectedly passed")
    except claim_agent.ConsumedClaimError:
        pass
    assert list(interrupted.glob(".paperclip-claim-*.pending"))
    assert not (interrupted / ".env").exists()

    claim_agent.request_json = original_request
    claim_agent.get_self = original_self

print("Atomic Paperclip claim preflight/failure tests passed.")
