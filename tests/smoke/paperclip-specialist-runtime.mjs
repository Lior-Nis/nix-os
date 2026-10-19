import assert from "node:assert/strict";
import { createHash, createHmac, timingSafeEqual } from "node:crypto";
import { chmod, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import vm from "node:vm";

const appRoot = process.env.PAPERCLIP_APP_ROOT ?? "/app";
const specialist = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const peer = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const chief = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const issueId = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
const interactionId = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee";
const runId = "ffffffff-ffff-4fff-8fff-ffffffffffff";
const founder = "lior-user";
const telegramId = "123456789";
const relaySecret = "test-only-founder-relay-secret-32-bytes";

Object.assign(process.env, {
  NIX_PAPERCLIP_SPECIALIST_AGENT_IDS: `${specialist},${peer}`,
  NIX_PAPERCLIP_FOUNDER_USER_ID: founder,
  PAPERCLIP_LIOR_USER_ID: founder,
  NIX_CHIEF_AGENT_ID: chief,
  NIX_LIOR_TELEGRAM_USER_ID: telegramId,
  NIX_LIOR_TELEGRAM_CHAT_ID: telegramId,
  NIX_FOUNDER_RELAY_SECRET: relaySecret,
});

const authorityPath = `${appRoot}/server/dist/services/native-runtime/paperclip-runner-tool-authority.js`;
const { PaperclipRunnerToolAuthority } = await import(authorityPath);
const authority = new PaperclipRunnerToolAuthority({}, {
  companyId: "11111111-1111-4111-8111-111111111111",
  agentId: specialist,
  runId,
  issueId,
  workMode: "standard",
  workspaceRoot: "/workspace",
  executionTargetKind: "local",
  apiToolsEnabled: true,
});
const nonAllowlistedRunner = new PaperclipRunnerToolAuthority({}, {
  companyId: "11111111-1111-4111-8111-111111111111",
  agentId: chief,
  runId,
  issueId,
  workMode: "standard",
  workspaceRoot: "/workspace",
  executionTargetKind: "local",
  apiToolsEnabled: true,
});

const restrictedOperations = [
    "create_task", "get_task_context", "get_task_history", "list_agents",
    "list_document_revisions", "list_documents", "read_document",
    "register_deliverable", "report_progress", "request_human_input",
    "write_document",
].sort();
assert.deepEqual(authority.definitions().map(({ name }) => name).sort(), restrictedOperations);
assert.deepEqual(
  nonAllowlistedRunner.definitions().map(({ name }) => name).sort(),
  restrictedOperations,
);
for (const hidden of [
  "search_api", "call_api", "search_tasks", "get_agent", "create_project",
  "list_projects", "list_approvals", "connections_search",
]) {
  await assert.rejects(
    authority.execute({ tool: hidden, arguments: {} }),
    /paperclip_runner_tool_not_advertised/,
  );
  await assert.rejects(
    nonAllowlistedRunner.execute({ tool: hidden, arguments: {} }),
    /paperclip_runner_tool_not_advertised/,
  );
}

const authoritySource = await readFile(authorityPath, "utf8");
for (const required of [
  "nix_specialist_child_scope_denied",
  "nix_specialist_child_dependency_denied",
  "dependency.projectId !== context.issue.projectId",
  "NIX_SPECIALIST_AGENT_IDS.has(assigneeAgentId)",
  "nix_specialist_interaction_kind_denied",
  "NIX_SPECIALIST_ALLOWED_INTERACTIONS.has(kind)",
  'continuationPolicy: "wake_assignee"',
  'resolverPolicy: "human_only"',
  "addresseeUserId: NIX_FOUNDER_USER_ID",
]) assert.ok(authoritySource.includes(required), required);

const nativeExecutor = await readFile(
  `${appRoot}/server/dist/services/native-runtime/native-session-executor.js`, "utf8",
);
const openCodeDriver = await readFile(
  `${appRoot}/packages/paperclip-runner/dist/drivers/opencode/opencode-server-driver.js`, "utf8",
);
assert.ok(nativeExecutor.includes('"OPENCODE_API_KEY"'));
assert.ok(openCodeDriver.includes("environment?.OPENCODE_API_KEY"));
assert.ok(openCodeDriver.includes("OPENROUTER_API_KEY|OPENCODE_API_KEY|authorization"));
assert.ok(openCodeDriver.includes("tools: { question: false }"));
assert.ok(openCodeDriver.includes('question: "deny"'));
assert.ok(openCodeDriver.includes("nix_opencode_native_question_denied"));

// Exercise the exact patched SSH adapter. The fake ssh binary executes only
// its final remote-command argument locally, which proves the adapter retains
// sh -c's argv[0] and positional arguments without requiring a network daemon.
const fakeSshDir = await mkdtemp(path.join(os.tmpdir(), "nix-fake-ssh-"));
const fakeSsh = path.join(fakeSshDir, "ssh");
await writeFile(fakeSsh, '#!/bin/sh\nfor value do remote=$value; done\nexec sh -c "$remote"\n');
await chmod(fakeSsh, 0o755);
const originalPath = process.env.PATH;
process.env.PATH = `${fakeSshDir}:${originalPath}`;
try {
  const { createSshCommandManagedRuntimeRunner } = await import(
    `${appRoot}/packages/adapter-utils/src/ssh.ts`
  );
  const sshRunner = createSshCommandManagedRuntimeRunner({
    spec: {
      host: "fixture.invalid",
      port: 22,
      username: "worker",
      remoteCwd: "/tmp",
      remoteWorkspacePath: "/tmp",
      privateKey: null,
      knownHosts: null,
      strictHostKeyChecking: false,
    },
  });
  const result = await sshRunner.execute({
    command: "sh",
    args: ["-c", 'set -eu; printf "%s|%s|%s" "$0" "$1" "$2"', "launch", "alpha", "beta"],
    env: { NIX_POSITIONAL_TEST: "present" },
  });
  assert.equal(result.exitCode, 0, result.stderr);
  assert.equal(result.stdout, "launch|alpha|beta");
} finally {
  process.env.PATH = originalPath;
  await rm(fakeSshDir, { recursive: true, force: true });
}

const logRedaction = await import(
  `${appRoot}/server/dist/middleware/http-log-redaction.js`
);
assert.ok(
  logRedaction.HTTP_LOG_REDACT_PATHS.includes(
    'req.headers["x-nix-founder-relay-signature"]',
  ),
);

// Exercise the exact verifier bytes loaded by the server, with a tiny query
// adapter. This catches HMAC, founder/specialist binding, and replay behavior
// without replacing the implementation with a test copy.
const issuesPath = `${appRoot}/server/dist/routes/issues.js`;
const issuesSource = await readFile(issuesPath, "utf8");
const relayStart = issuesSource.indexOf("const NIX_RELAY_UUID");
const relayEnd = issuesSource.indexOf("const updateIssueRouteSchema", relayStart);
assert.ok(relayStart >= 0 && relayEnd > relayStart);
const relayProgram = `${issuesSource.slice(relayStart, relayEnd)}\nthis.verifyRelay = verifyNixFounderRelay;`;

function makeDb({ status = "pending", receipt = null, continuationPolicy = "wake_assignee" } = {}) {
  return {
    select(fields) {
      let rows;
      if (Object.hasOwn(fields, "status")) {
        rows = [{
          id: interactionId, issueId,
          companyId: "11111111-1111-4111-8111-111111111111",
          status, kind: "ask_user_questions", continuationPolicy,
          effectiveResolverPolicy: "human_only",
          addresseeUserId: founder, sourceRunId: runId,
          resolvedByUserId: status === "answered" ? founder : null,
        }];
      } else if (Object.hasOwn(fields, "agentId")) {
        rows = [{ agentId: specialist,
          companyId: "11111111-1111-4111-8111-111111111111", issueId }];
      } else if (Object.hasOwn(fields, "details")) {
        rows = receipt ? [{ details: receipt }] : [];
      } else {
        throw new Error("unexpected relay query");
      }
      const query = {
        from() { return this; }, where() { return this; }, orderBy() { return this; },
        limit() { return Promise.resolve(rows); },
      };
      return query;
    },
  };
}

const context = {
  process, Buffer, Date, createHash, createHmac, timingSafeEqual,
  forbidden: (message) => new Error(message),
  getActorInfo: (req) => req.actorInfo,
  and: (...values) => values, eq: (...values) => values, desc: (value) => value,
  sql: (strings, ...values) => ({ strings, values }),
  issueThreadInteractions: new Proxy({}, { get: (_target, key) => String(key) }),
  heartbeatRuns: new Proxy({}, { get: (_target, key) => String(key) }),
  activityLog: new Proxy({}, { get: (_target, key) => String(key) }),
};
vm.runInNewContext(relayProgram, context);

const answers = [{ questionId: "q1", optionIds: ["yes"] }];
const body = { answers };
const canonicalBody = '{"answers":[{"optionIds":["yes"],"questionId":"q1"}]}';
const bodyDigest = createHash("sha256").update(canonicalBody).digest("hex");
const idempotencyKey = "telegram:42";
const sourceMessageId = "42";

function request(overrides = {}) {
  const timestamp = String(Math.floor(Date.now() / 1000));
  const path = `/api/issues/${issueId}/interactions/${interactionId}/respond`;
  const canonical = ["v1", timestamp, "POST", path, bodyDigest, "telegram", "dm",
    telegramId, telegramId, sourceMessageId, idempotencyKey].join("\n");
  const headers = {
    "x-nix-founder-relay-version": "1",
    "x-nix-founder-relay-timestamp": timestamp,
    "x-nix-founder-relay-idempotency-key": idempotencyKey,
    "x-nix-founder-relay-platform": "telegram",
    "x-nix-founder-relay-chat-type": "dm",
    "x-nix-founder-relay-user-id": telegramId,
    "x-nix-founder-relay-chat-id": telegramId,
    "x-nix-founder-relay-message-id": sourceMessageId,
    "x-nix-founder-relay-signature": `v1=${createHmac("sha256", relaySecret).update(canonical).digest("hex")}`,
    ...overrides,
  };
  return {
    body, originalUrl: path,
    actorInfo: { actorType: "agent", actorId: chief, agentId: chief },
    get(name) { return headers[name.toLowerCase()]; },
  };
}

const issue = {
  id: issueId, companyId: "11111111-1111-4111-8111-111111111111",
  assigneeAgentId: specialist,
};
const first = await context.verifyRelay({ req: request(), db: makeDb(), issue, interactionId });
assert.equal(first.replayed, false);
assert.equal(first.bodyDigest, bodyDigest);
assert.equal(first.originAgentId, specialist);
await assert.rejects(
  context.verifyRelay({
    req: request({ "x-nix-founder-relay-signature": `v1=${"0".repeat(64)}` }),
    db: makeDb(), issue, interactionId,
  }),
  /Founder relay attestation is invalid/,
);
await assert.rejects(
  context.verifyRelay({
    req: request(), db: makeDb({ continuationPolicy: "none" }), issue, interactionId,
  }),
  /Founder relay attestation is invalid/,
);

const persisted = {
  interactionId,
  nixFounderRelayReservation: {
    version: 1, interactionId, issueId, resolverUserId: founder,
    sourceMessageId, idempotencyKey, originAgentId: specialist,
    requestBodySha256: bodyDigest,
  },
};
const replay = await context.verifyRelay({
  req: request(), db: makeDb({ status: "answered", receipt: persisted }), issue, interactionId,
});
assert.equal(replay.replayed, true);
await assert.rejects(
  context.verifyRelay({
    req: request(), db: makeDb({ status: "answered", receipt: {
      ...persisted,
      nixFounderRelayReservation: {
        ...persisted.nixFounderRelayReservation,
        requestBodySha256: "0".repeat(64),
      },
    } }), issue, interactionId,
  }),
  /Founder relay attestation is invalid/,
);

for (const routeContract of [
  "if (founderRelay?.replayed)",
  'action: "issue.founder_relay_reserved"',
  "beforeResolveInTransaction: async (tx)",
  '.for("update").limit(1)',
  "await tx.insert(activityLog).values",
  "nixFounderRelayRequestBodySha256: founderRelay.bodyDigest",
  'resumedAgentId: null, continuationStatus: "pending"',
  'error: "nix_founder_relay_continuation_pending"',
  "contextSnapshot: heartbeatRuns.contextSnapshot",
  "targetRun?.agentId === input.originAgentId && targetIssueId === input.issueId",
  "res.json({ ...current, nixFounderRelay })",
]) assert.ok(issuesSource.includes(routeContract), routeContract);

console.log("paperclip specialist runtime behavior: ok");
