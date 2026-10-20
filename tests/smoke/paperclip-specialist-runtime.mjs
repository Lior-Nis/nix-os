import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createHash, createHmac, timingSafeEqual } from "node:crypto";
import { closeSync, openSync } from "node:fs";
import { chmod, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
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
const vendoredOpenCodeDriver = await readFile(
  `${appRoot}/server/dist/vendor/paperclip-runner/drivers/opencode/opencode-server-driver.js`, "utf8",
);
const openCodeProxy = await readFile(
  `${appRoot}/packages/paperclip-runner/dist/cli/opencode-app-server-proxy.cjs`, "utf8",
);
const vendoredOpenCodeProxy = await readFile(
  `${appRoot}/server/dist/vendor/paperclip-runner/cli/opencode-app-server-proxy.cjs`, "utf8",
);
const runnerTransport = await readFile(
  `${appRoot}/packages/paperclip-runner/dist/live/runnerd-codex-transport.js`, "utf8",
);
const vendoredRunnerTransport = await readFile(
  `${appRoot}/server/dist/vendor/paperclip-runner/live/runnerd-codex-transport.js`, "utf8",
);
assert.ok(nativeExecutor.includes('"OPENCODE_API_KEY"'));
for (const source of [runnerTransport, vendoredRunnerTransport]) {
  assert.ok(source.includes(
    "const opencodeApiKey = source?.OPENCODE_API_KEY;",
  ));
  assert.ok(source.includes(
    "if (opencodeApiKey !== undefined) candidate.OPENROUTER_API_KEY = opencodeApiKey;",
  ));
  assert.ok(source.includes("delete candidate.OPENCODE_API_KEY;"));
  assert.ok(source.includes("nix_runner_provider_credential_conflict"));
}
for (const source of [openCodeDriver, vendoredOpenCodeDriver]) {
  assert.ok(source.includes(
    "options: { apiKey: input.options.environment?.OPENROUTER_API_KEY }",
  ));
  assert.ok(!source.includes("environment?.OPENAI_API_KEY"));
  assert.ok(!source.includes("environment?.OPENCODE_API_KEY"));
  assert.ok(source.includes("OPENROUTER_API_KEY|authorization"));
  assert.ok(source.includes("tools: { question: false }"));
  assert.ok(source.includes('question: "deny"'));
  assert.ok(source.includes("nix_opencode_native_question_denied"));
}
for (const source of [openCodeProxy, vendoredOpenCodeProxy]) {
  assert.ok(source.includes(
    "options: { apiKey: input2.options.environment?.OPENROUTER_API_KEY }",
  ));
  assert.ok(!source.includes("environment?.OPENAI_API_KEY"));
  assert.ok(!source.includes("environment?.OPENCODE_API_KEY"));
  assert.ok(source.includes("OPENROUTER_API_KEY|authorization"));
  assert.ok(source.includes("tools: { question: false }"));
  assert.ok(source.includes('question: "deny"'));
  assert.ok(source.includes("nix_opencode_native_question_denied"));
}

// Exercise the production transport sanitizer before spawnRunner. Paperclip
// stores the native OpenCode name, while the exact Rust runnerd accepts only
// its existing OpenRouter name. Only that child alias may survive both gates.
const controllerCanary = "nix-controller-alias-canary-493ea0f2";
const inheritedServerAlias = process.env.OPENROUTER_API_KEY;
const inheritedServerOpenCode = process.env.OPENCODE_API_KEY;
let runnerLaunch;
const { spawnRunner } = await import(
  `${appRoot}/packages/paperclip-runner/dist/control-plane/durable-prp-control-plane.js`
);
const { createCapabilityRunnerdProviderEnvironment } = await import(
  `${appRoot}/packages/paperclip-runner/dist/live/runnerd-codex-transport.js`
);
const providerEnvironmentInput = {
  provider: "opencode",
  identity: {
    runnerInstanceId: "runner-alias-fixture",
    environmentLeaseId: "environment-alias-fixture",
    runId,
    normalizedSessionId: "alias-fixture",
    turnId: "turn-alias-fixture",
    itemId: "item-alias-fixture",
  },
  codexHome: "/tmp/nix-runner-alias-home",
  runtimeContextPath: "/tmp/nix-runner-alias-context.json",
  hasRuntimeContext: false,
};
delete process.env.OPENROUTER_API_KEY;
delete process.env.OPENCODE_API_KEY;
const providerEnvironment = createCapabilityRunnerdProviderEnvironment({
  ...providerEnvironmentInput,
  options: {
    provider: "opencode",
    stateDirectory: "/tmp/nix-runner-alias-state",
    opencodePermissionMode: "deny",
    environment: {
      PATH: process.env.PATH,
      OPENCODE_API_KEY: controllerCanary,
      NIX_UNRELATED_SECRET: "must-not-cross",
    },
  },
});
assert.equal(providerEnvironment.OPENROUTER_API_KEY, controllerCanary);
assert.equal(providerEnvironment.OPENCODE_API_KEY, undefined);
assert.equal(providerEnvironment.NIX_UNRELATED_SECRET, undefined);
spawnRunner({
  connectUrl: "ws://127.0.0.1:1/runner",
  stateDirectory: "/tmp/nix-runner-alias-state",
  identity: providerEnvironmentInput.identity,
  ticket: "test-only-runner-ticket",
  maxOutboxBytes: 1024 * 1024,
  p0ReserveBytes: 1024,
  runnerVersion: "test-only",
  runnerDigest: `sha256:${"0".repeat(64)}`,
  environment: providerEnvironment,
  processLauncher(spec) {
    runnerLaunch = spec;
    return {
      child: { exitCode: null, signalCode: null, kill: () => true },
      completion: Promise.resolve({ code: 0, signal: null }),
    };
  },
});
assert.equal(runnerLaunch?.environment?.OPENROUTER_API_KEY, controllerCanary);
assert.equal(runnerLaunch?.environment?.OPENCODE_API_KEY, undefined);
assert.equal(runnerLaunch?.environment?.NIX_UNRELATED_SECRET, undefined);
const conflictingAliasCanary = "nix-conflicting-alias-canary-ea861809";
assert.throws(
  () => createCapabilityRunnerdProviderEnvironment({
    ...providerEnvironmentInput,
    options: {
      provider: "opencode",
      stateDirectory: "/tmp/nix-runner-conflict-state",
      environment: {
        OPENCODE_API_KEY: controllerCanary,
        OPENROUTER_API_KEY: conflictingAliasCanary,
      },
    },
  }),
  (error) => error?.message === "nix_runner_provider_credential_conflict"
    && !error.message.includes(controllerCanary)
    && !error.message.includes(conflictingAliasCanary),
);
if (inheritedServerAlias === undefined) delete process.env.OPENROUTER_API_KEY;
else process.env.OPENROUTER_API_KEY = inheritedServerAlias;
if (inheritedServerOpenCode === undefined) delete process.env.OPENCODE_API_KEY;
else process.env.OPENCODE_API_KEY = inheritedServerOpenCode;

// Execute the same self-contained CJS proxy selected by the remote provider-pack.
// The fake provider emits the runner-supported compatibility alias to stderr:
// the proxy must bind it into opencode.json while redacting diagnostics/trace.
const proxyFixtureRoot = await mkdtemp(path.join(os.tmpdir(), "nix-opencode-proxy-"));
const proxyRuntime = path.join(proxyFixtureRoot, "runtime");
const proxyWorkspace = path.join(proxyFixtureRoot, "workspace");
const proxyExecutable = path.join(proxyFixtureRoot, "opencode-fixture");
const proxyTrace = path.join(proxyFixtureRoot, "provider-trace.jsonl");
const providerCanary = "nix-provider-canary-92b75e17";
await mkdir(proxyWorkspace);
await writeFile(
  proxyExecutable,
  '#!/bin/sh\nprintf "provider diagnostic %s\\n" "$OPENROUTER_API_KEY" >&2\nexit 1\n',
);
await chmod(proxyExecutable, 0o755);
const providerFd = openSync(proxyExecutable, "r");
let proxyStderr = "";
let proxyStdout = "";
const proxy = spawn(
  process.execPath,
  [
    `${appRoot}/packages/paperclip-runner/dist/cli/opencode-app-server-proxy.cjs`,
    "--paperclip-trusted-opencode-executable",
    "/proc/self/fd/3",
  ],
  {
    env: {
      PATH: process.env.PATH,
      PAPERCLIP_OPENCODE_RUNTIME_DIR: proxyRuntime,
      PAPERCLIP_NORMALIZED_SESSION_ID: "credential-canary",
      PAPERCLIP_PROVIDER_TRACE_PATH: proxyTrace,
      OPENROUTER_API_KEY: providerCanary,
    },
    stdio: ["pipe", "pipe", "pipe", providerFd],
  },
);
proxy.stdout.setEncoding("utf8");
proxy.stderr.setEncoding("utf8");
proxy.stdout.on("data", (chunk) => { proxyStdout += chunk; });
proxy.stderr.on("data", (chunk) => { proxyStderr += chunk; });
proxy.stdin.write(`${JSON.stringify({
  id: "credential-canary",
  method: "thread/start",
  params: {
    cwd: proxyWorkspace,
    model: "opencode-go/gpt-5.6-luna",
    baseInstructions: "Exercise generated provider configuration only.",
  },
})}\n`);
const generatedConfigPath = path.join(
  proxyRuntime, "credential-canary", "config", "opencode", "opencode.json",
);
let generatedConfig;
for (let attempt = 0; attempt < 100; attempt += 1) {
  try {
    generatedConfig = JSON.parse(await readFile(generatedConfigPath, "utf8"));
    break;
  } catch {
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
}
for (let attempt = 0; attempt < 100 && !proxyStderr.includes("[REDACTED]"); attempt += 1) {
  await new Promise((resolve) => setTimeout(resolve, 25));
}
proxy.kill("SIGTERM");
await new Promise((resolve) => {
  if (proxy.exitCode !== null || proxy.signalCode !== null) resolve();
  else proxy.once("exit", resolve);
});
closeSync(providerFd);
if (generatedConfig?.provider?.["opencode-go"]?.options?.apiKey !== providerCanary) {
  throw new Error("executed OpenCode proxy did not bind the projected provider credential");
}
if (proxyStdout.includes(providerCanary) || proxyStderr.includes(providerCanary)) {
  throw new Error("executed OpenCode proxy emitted the provider credential");
}
if (!proxyStderr.includes("[REDACTED]")) {
  throw new Error("executed OpenCode proxy did not redact the provider diagnostic");
}
const proxyTraceContents = await readFile(proxyTrace, "utf8").catch(() => "");
if (proxyTraceContents.includes(providerCanary)) {
  throw new Error("executed OpenCode proxy trace retained the provider credential");
}
await rm(proxyFixtureRoot, { recursive: true, force: true });

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
