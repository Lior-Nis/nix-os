import assert from "node:assert/strict";
import crypto from "node:crypto";

import { execute } from "/app/packages/adapters/hermes/dist/gateway/server/index.js";

const required = (name) => {
  const value = process.env[name]?.trim();
  assert(value, `missing ${name}`);
  return value;
};

const apiBaseUrl = required("HERMES_API_BASE_URL").replace(/\/+$/, "");
const apiKey = required("HERMES_API_KEY");
const companyId = required("PAPERCLIP_COMPANY_ID");
const agentId = required("PAPERCLIP_AGENT_ID");
const paperclipRunId = required("PAPERCLIP_RUN_ID");
const issueId = required("PAPERCLIP_ISSUE_ID");
const expectedHermesRunId = process.env.EXPECT_HERMES_RUN_ID?.trim() || null;
const forcePoll = process.env.FORCE_POLL === "1";
const expectConflict = process.env.EXPECT_CONFLICT === "1";
const expectedSession = `paperclip:company:${companyId}:agent:${agentId}:issue:${issueId}`;
const realFetch = globalThis.fetch.bind(globalThis);
const counts = { create: 0, events: 0, status: 0 };

globalThis.fetch = async (input, init) => {
  const url = String(input);
  if (url.endsWith("/v1/runs")) counts.create += 1;
  if (url.endsWith("/events")) {
    counts.events += 1;
    if (forcePoll) {
      return new Response(JSON.stringify({ error: "forced_event_fallback" }), {
        status: 503,
        headers: { "content-type": "application/json" },
      });
    }
  } else if (/\/v1\/runs\/run_[0-9a-f]{32}$/.test(url)) {
    counts.status += 1;
  }
  return realFetch(input, init);
};

const config = {
  apiBaseUrl,
  apiKey,
  paperclipApiUrl: "http://paperclip.invalid",
  sessionKeyStrategy: "issue",
  dangerouslyAllowInsecureRemoteHttp: true,
  timeoutSec: 45,
  pollIntervalMs: 250,
  eventReconnectMs: 250,
};
const logs = [];
let dispatches = 0;
let metadata = null;
const result = await execute({
  runId: paperclipRunId,
  agent: {
    id: agentId,
    companyId,
    name: "Chief of Staff",
    adapterType: "hermes_gateway",
    adapterConfig: config,
  },
  runtime: {
    sessionId: null,
    sessionParams: null,
    sessionDisplayId: null,
    taskKey: null,
  },
  config,
  context: {
    issueId,
    wakeReason: "manual",
    paperclipWake: {
      issue: {
        id: issueId,
        identifier: "NIX-SMOKE",
        title: "Pinned gateway adapter smoke",
        description: "Provider-free admission probe; do not claim task completion.",
      },
    },
  },
  onLog: async (stream, text) => logs.push(`${stream}:${text}`),
  onMeta: async (value) => { metadata = value; },
  onDispatch: () => { dispatches += 1; },
});

assert.equal(dispatches, 1, "adapter did not cross its dispatch boundary exactly once");
assert.equal(counts.create, 1, "adapter did not make exactly one Runs API admission request");
assert.equal(metadata?.adapterType, "hermes_gateway");
assert.equal(metadata?.command, "POST /v1/runs");
assert.equal(metadata?.context?.runId, paperclipRunId);
const combinedLogs = logs.join("");
assert(!combinedLogs.includes(apiKey), "adapter logs exposed its API credential");
assert(!combinedLogs.includes(expectedSession), "adapter logs exposed its raw session key");

if (expectConflict) {
  assert.equal(result.exitCode, 1);
  assert.equal(result.errorCode, "hermes_gateway_protocol_error");
  assert.equal(result.errorMeta?.status, 409);
  process.stdout.write(`${JSON.stringify({ kind: "conflict", counts })}\n`);
  process.exit(0);
}

assert.equal(result.exitCode, 1, "provider-free run unexpectedly completed");
assert.equal(result.errorCode, "hermes_gateway_run_failed");
assert.equal(result.timedOut, false);
assert.match(result.sessionParams?.hermesRunId || "", /^run_[0-9a-f]{32}$/);
assert.equal(result.sessionParams?.strategy, "issue");
assert.equal(result.sessionParams?.hermesSessionId, undefined, "raw session escaped through session params");
assert(!String(result.sessionId || "").includes(expectedSession), "raw session escaped through result sessionId");
assert(!String(result.sessionDisplayId || "").includes(expectedSession), "raw session escaped through display ID");
assert(expectedHermesRunId === null || result.sessionParams.hermesRunId === expectedHermesRunId,
  "durable replay returned a different Hermes run ID");
assert(counts.events > 0, "adapter never attempted the supported event stream");
if (forcePoll) assert(counts.status > 0, "adapter did not fall back to status polling");

const statusResponse = await realFetch(
  `${apiBaseUrl}/v1/runs/${encodeURIComponent(result.sessionParams.hermesRunId)}`,
  { headers: { Authorization: `Bearer ${apiKey}` } },
);
assert.equal(statusResponse.status, 200);
const status = await statusResponse.json();
assert.equal(status.run_id, result.sessionParams.hermesRunId);
assert.equal(status.session_id, expectedSession, "Hermes did not retain the adapter-derived issue session");
assert.equal(status.status, "failed", "missing provider credential was not a visible terminal failure");

process.stdout.write(`${JSON.stringify({
  kind: "provider_failure_admitted",
  hermesRunId: result.sessionParams.hermesRunId,
  sessionDigest: crypto.createHash("sha256").update(status.session_id).digest("hex"),
  counts,
})}\n`);
