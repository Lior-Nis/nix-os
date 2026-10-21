import { randomUUID } from "node:crypto";
import { createServer } from "node:http";

import { eq } from "/app/server/node_modules/drizzle-orm/index.js";
import {
  activityLog,
  closeRegisteredClients,
  createDb,
  heartbeatRuns,
  issueThreadInteractions,
  issues,
} from "/app/packages/db/src/index.ts";
import { PaperclipRunnerToolAuthority } from "/app/server/dist/services/native-runtime/paperclip-runner-tool-authority.js";

const [companyId, projectId, chiefAgentId, productAgentId, growthAgentId] = process.argv.slice(2);
if (![companyId, projectId, chiefAgentId, productAgentId, growthAgentId].every(Boolean)) {
  throw new Error("usage: authority-fixture COMPANY PROJECT CHIEF PRODUCT GROWTH");
}

const databaseUrl = process.env.DATABASE_URL;
if (!databaseUrl) throw new Error("DATABASE_URL is required");

const db = createDb(databaseUrl);
const parentIssueId = randomUUID();
const productRunId = randomUUID();
const recoveryRunId = randomUUID();
const chiefIssueId = randomUUID();
const chiefRunId = randomUUID();
let committedBeforeWake = false;
let delegatedWake = null;
let mockHermes = null;

try {
  await db.insert(issues).values({
    id: parentIssueId,
    companyId,
    projectId,
    title: "Product authority delegation fixture",
    description: "Exercise the real task-scoped delegation authority.",
    status: "in_progress",
    workMode: "standard",
    assigneeAgentId: productAgentId,
  });
  await db.insert(heartbeatRuns).values({
    id: productRunId,
    companyId,
    agentId: productAgentId,
    status: "running",
    runtimeMode: "native",
    nativeIssueId: parentIssueId,
    invocationSource: "assignment",
    triggerDetail: "system",
    contextSnapshot: { issueId: parentIssueId },
  });
  await db
    .update(issues)
    .set({ executionRunId: productRunId })
    .where(eq(issues.id, parentIssueId));

  // A durable Chief-origin source run models the Paperclip attribution written
  // by the bounded Hermes lane. It is terminal so the founder answer can
  // enqueue the continuation through the normal server route.
  await db.insert(issues).values({
    id: chiefIssueId,
    companyId,
    projectId,
    title: "Chief founder-decision fixture",
    description: "Exercise immutable Chief-origin founder relay ownership.",
    status: "in_progress",
    workMode: "standard",
    assigneeAgentId: chiefAgentId,
    createdByAgentId: chiefAgentId,
  });
  await db.insert(heartbeatRuns).values({
    id: chiefRunId,
    companyId,
    agentId: chiefAgentId,
    status: "succeeded",
    runtimeMode: "native",
    nativeIssueId: chiefIssueId,
    invocationSource: "assignment",
    triggerDetail: "system",
    contextSnapshot: { issueId: chiefIssueId, source: "hermes.paperclip_mcp" },
    finishedAt: new Date(),
  });

  const authority = new PaperclipRunnerToolAuthority(db, {
    companyId,
    issueId: parentIssueId,
    runId: productRunId,
    agentId: productAgentId,
    workMode: "standard",
    enqueueWakeup: async (agentId, options) => {
      const [child] = await db
        .select()
        .from(issues)
        .where(eq(issues.parentId, parentIssueId));
      if (!child) throw new Error("delegated child was not committed before wake handoff");
      const childActivity = await db
        .select()
        .from(activityLog)
        .where(eq(activityLog.entityId, child.id));
      if (!childActivity.some((entry) => entry.action === "issue.created")) {
        throw new Error("delegation activity was not committed before wake handoff");
      }
      committedBeforeWake = true;
      delegatedWake = { agentId, options };
      return null;
    },
  });

  const result = await authority.execute({
    tool: "create_task",
    callId: "delegate-growth-child",
    arguments: {
      idempotencyKey: "delegate-growth-child",
      projectId,
      title: "Growth delegated execution fixture",
      description: "Execute this child in a fresh task-scoped Growth context.",
      assigneeActorId: growthAgentId,
    },
  });
  const childId = result?.task?.id;
  if (typeof childId !== "string") throw new Error("authority did not return a child task");

  const [child] = await db.select().from(issues).where(eq(issues.id, childId));
  const childActivity = await db
    .select()
    .from(activityLog)
    .where(eq(activityLog.entityId, childId));
  const created = childActivity.filter((entry) => entry.action === "issue.created");
  if (
    !child ||
    child.parentId !== parentIssueId ||
    child.projectId !== projectId ||
    child.assigneeAgentId !== growthAgentId ||
    child.createdByAgentId !== productAgentId ||
    child.originRunId !== productRunId ||
    child.status !== "todo"
  ) {
    throw new Error("delegated child authority or project boundary mismatch");
  }
  if (
    created.length !== 1 ||
    created[0].actorType !== "agent" ||
    created[0].actorId !== productAgentId ||
    created[0].agentId !== productAgentId ||
    created[0].runId !== productRunId ||
    created[0].details?.source !== "paperclip_runner_protocol"
  ) {
    throw new Error("delegated child attribution mismatch");
  }
  if (
    result.disposition !== "applied" ||
    result.scheduledWakeIds?.length !== 1 ||
    !committedBeforeWake ||
    delegatedWake?.agentId !== growthAgentId ||
    delegatedWake?.options?.source !== "assignment" ||
    delegatedWake?.options?.reason !== "issue_assigned" ||
    delegatedWake?.options?.requestedByActorType !== "agent" ||
    delegatedWake?.options?.requestedByActorId !== productAgentId ||
    delegatedWake?.options?.payload?.issueId !== childId ||
    delegatedWake?.options?.payload?.parentIssueId !== parentIssueId ||
    delegatedWake?.options?.contextSnapshot?.source !== "paperclip_runner.create_task"
  ) {
    throw new Error("delegated wake authority mismatch");
  }

  const founderQuestion = {
    idempotencyKey: "product-founder-question",
    interactionKind: "questions",
    title: "Choose the lean launch direction",
    prompt: "Choose the launch direction before Product continues.",
    continuationPolicy: "wake_assignee",
    payload: {
      questions: [{
        id: "direction",
        prompt: "Which direction should Product take?",
        selectionMode: "single",
        helpText: "Prefer the smallest reversible launch that validates demand.",
        allowOther: true,
        options: [
          { id: "alpha", label: "Alpha", description: "Ship the narrow validation first." },
          { id: "beta", label: "Beta", description: "Describe a different direction.", freeText: true },
        ],
      }],
    },
  };
  const firstQuestion = await authority.execute({
    tool: "request_human_input",
    callId: "product-founder-question-first",
    arguments: founderQuestion,
  });
  const replayedQuestion = await authority.execute({
    tool: "request_human_input",
    callId: "product-founder-question-replay",
    arguments: founderQuestion,
  });
  const interactionId = firstQuestion?.interaction?.id;
  if (
    typeof interactionId !== "string" ||
    replayedQuestion?.interaction?.id !== interactionId ||
    firstQuestion?.specialistQuestionDelivery?.disposition !== "failed_not_sent" ||
    replayedQuestion?.specialistQuestionDelivery?.disposition !== "failed_not_sent"
  ) {
    throw new Error("specialist founder-question replay did not remain recoverable");
  }
  const interactions = await db
    .select()
    .from(issueThreadInteractions)
    .where(eq(issueThreadInteractions.id, interactionId));
  const deliveries = (await db
    .select()
    .from(activityLog)
    .where(eq(activityLog.entityId, interactionId)))
    .filter((entry) => entry.action === "issue.specialist_question_delivery");
  if (
    interactions.length !== 1 ||
    interactions[0].kind !== "ask_user_questions" ||
    interactions[0].status !== "pending" ||
    interactions[0].sourceRunId !== productRunId ||
    interactions[0].requestedResolverPolicy !== "human_only" ||
    interactions[0].effectiveResolverPolicy !== "human_only" ||
    interactions[0].addresseeUserId !== process.env.NIX_PAPERCLIP_FOUNDER_USER_ID ||
    deliveries.length !== 1 ||
    deliveries[0].details?.disposition !== "failed_not_sent" ||
    deliveries[0].details?.attemptCount !== 2 ||
    deliveries[0].details?.requestId !== `paperclip-specialist-question:${interactionId}`
  ) {
    throw new Error("specialist founder-question authority or delivery receipt mismatch");
  }
  await db.update(activityLog).set({
    details: {
      ...deliveries[0].details,
      disposition: "pending",
    },
  }).where(eq(activityLog.id, deliveries[0].id));
  const crashReplay = await authority.execute({
    tool: "request_human_input",
    callId: "product-founder-question-crash-replay",
    arguments: founderQuestion,
  });
  const [crashDisposition] = await db
    .select()
    .from(activityLog)
    .where(eq(activityLog.id, deliveries[0].id));
  if (
    crashReplay?.interaction?.id !== interactionId ||
    crashReplay?.specialistQuestionDelivery?.disposition !== "unknown" ||
    crashDisposition?.details?.disposition !== "unknown" ||
    crashDisposition?.details?.attemptCount !== 2
  ) {
    throw new Error("post-reservation crash was replayed instead of becoming unknown");
  }

  // Remove the delivery ledger row to model an interaction committed before
  // specialist Telegram delivery existed. A later run must recover that exact
  // interaction rather than create another one.
  await db.delete(activityLog).where(eq(activityLog.id, deliveries[0].id));

  await db
    .update(heartbeatRuns)
    .set({ status: "succeeded", finishedAt: new Date() })
    .where(eq(heartbeatRuns.id, productRunId));
  await db
    .update(issues)
    .set({ executionRunId: null })
    .where(eq(issues.id, parentIssueId));

  await db.insert(heartbeatRuns).values({
    id: recoveryRunId,
    companyId,
    agentId: productAgentId,
    status: "running",
    runtimeMode: "native",
    nativeIssueId: parentIssueId,
    invocationSource: "assignment",
    triggerDetail: "system",
    contextSnapshot: { issueId: parentIssueId },
  });
  await db
    .update(issues)
    .set({ executionRunId: recoveryRunId })
    .where(eq(issues.id, parentIssueId));

  const deliveryRequests = [];
  mockHermes = createServer((request, response) => {
    const chunks = [];
    request.on("data", (chunk) => chunks.push(chunk));
    request.on("end", () => {
      const body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      const requestId = request.headers["x-request-id"];
      const marker = typeof body.message === "string"
        ? body.message.match(/\[case:([a-z0-9-]+)\]/)?.[1] ?? "recovery"
        : "invalid";
      deliveryRequests.push({ marker, body, requestId });
      if (marker === "reset") {
        request.socket.destroy();
        return;
      }
      if (marker === "timeout") {
        const timer = setTimeout(() => response.destroy(), 3500);
        response.on("close", () => clearTimeout(timer));
        return;
      }
      if (marker === "502") {
        response.writeHead(502, { "content-type": "application/json" });
        response.end(JSON.stringify({ status: "failed" }));
        return;
      }
      if (marker === "malformed") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end("{");
        return;
      }
      if (marker === "duplicate") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ status: "duplicate", delivery_id: requestId }));
        return;
      }
      const deliver = () => {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ status: "delivered", delivery_id: requestId }));
      };
      if (marker === "concurrent") setTimeout(deliver, 200);
      else deliver();
    });
  });
  await new Promise((resolve, reject) => {
    mockHermes.once("error", reject);
    mockHermes.listen(8644, "0.0.0.0", resolve);
  });

  const recoveryAuthority = new PaperclipRunnerToolAuthority(db, {
    companyId,
    issueId: parentIssueId,
    runId: recoveryRunId,
    agentId: productAgentId,
    workMode: "standard",
  });
  const recoveredQuestion = await recoveryAuthority.execute({
    tool: "request_human_input",
    callId: "product-founder-question-cross-run-recovery",
    arguments: founderQuestion,
  });
  const recoveredRows = await db
    .select()
    .from(issueThreadInteractions)
    .where(eq(issueThreadInteractions.idempotencyKey, founderQuestion.idempotencyKey));
  const recoveryMessage = deliveryRequests.find((entry) => entry.marker === "recovery")?.body?.message;
  if (
    recoveredQuestion?.interaction?.id !== interactionId ||
    recoveredQuestion?.interaction?.sourceRunId !== productRunId ||
    recoveredQuestion?.specialistQuestionDelivery?.disposition !== "delivered" ||
    recoveredRows.length !== 1 ||
    typeof recoveryMessage !== "string" ||
    !recoveryMessage.includes("Request: Choose the launch direction before Product continues.") ||
    !recoveryMessage.includes("Prefer the smallest reversible launch") ||
    !recoveryMessage.includes("Ship the narrow validation first.") ||
    !recoveryMessage.includes("Beta (add your own text)") ||
    !recoveryMessage.includes("Describe a different direction.") ||
    !recoveryMessage.includes("Other (write your own answer)") ||
    recoveryMessage.includes("(required)")
  ) {
    throw new Error("cross-run pre-patch interaction recovery or faithful rendering failed");
  }

  const caseQuestion = (name) => ({
    idempotencyKey: `delivery-${name}`,
    interactionKind: "questions",
    title: `[case:${name}] Delivery classification`,
    prompt: `Classify ${name} delivery.`,
    continuationPolicy: "wake_assignee",
    payload: {
      questions: [{
        id: `question-${name}`,
        prompt: `Choose for ${name}.`,
        selectionMode: "single",
        options: [{ id: "yes", label: "Yes" }],
      }],
    },
  });
  const executeCase = (name, suffix = "first") => recoveryAuthority.execute({
    tool: "request_human_input",
    callId: `delivery-${name}-${suffix}`,
    arguments: caseQuestion(name),
  });
  const countRequests = (name) => deliveryRequests.filter((entry) => entry.marker === name).length;

  const delivered = await executeCase("delivered");
  const deliveredReplay = await executeCase("delivered", "replay");
  const restartedAuthority = new PaperclipRunnerToolAuthority(db, {
    companyId, issueId: parentIssueId, runId: recoveryRunId,
    agentId: productAgentId, workMode: "standard",
  });
  const restartReplay = await restartedAuthority.execute({
    tool: "request_human_input",
    callId: "delivery-delivered-restart",
    arguments: caseQuestion("delivered"),
  });
  if (
    delivered?.specialistQuestionDelivery?.disposition !== "delivered" ||
    deliveredReplay?.specialistQuestionDelivery?.disposition !== "delivered" ||
    restartReplay?.specialistQuestionDelivery?.disposition !== "delivered" ||
    countRequests("delivered") !== 1
  ) throw new Error("delivered/restart ledger classification failed");

  const longPrompt = `Preserve this complete decision context: ${"x".repeat(1160)}`;
  const longPromptQuestion = caseQuestion("long-prompt");
  const initialLongPromptResult = await recoveryAuthority.execute({
    tool: "request_human_input",
    callId: "delivery-long-prompt-initial",
    arguments: longPromptQuestion,
  });
  const longPromptInteractionId = initialLongPromptResult?.interaction?.id;
  const [storedLongPrompt] = await db.select().from(issueThreadInteractions)
    .where(eq(issueThreadInteractions.id, longPromptInteractionId));
  const [recoveryRun] = await db.select().from(heartbeatRuns)
    .where(eq(heartbeatRuns.id, recoveryRunId));
  const resultJson = structuredClone(recoveryRun.resultJson);
  const longPromptReceipt = resultJson.semanticToolReceipts[longPromptQuestion.idempotencyKey];
  const longPayload = { ...storedLongPrompt.payload, prompt: longPrompt };
  longPromptReceipt.result.interaction = {
    ...longPromptReceipt.result.interaction,
    summary: longPrompt,
    payload: longPayload,
  };
  await db.update(issueThreadInteractions).set({
    summary: longPrompt,
    payload: longPayload,
  }).where(eq(issueThreadInteractions.id, longPromptInteractionId));
  await db.update(heartbeatRuns).set({ resultJson })
    .where(eq(heartbeatRuns.id, recoveryRunId));
  await db.delete(activityLog).where(eq(activityLog.entityId, longPromptInteractionId));
  const longPromptResult = await recoveryAuthority.execute({
    tool: "request_human_input",
    callId: "delivery-long-prompt-recovery",
    arguments: longPromptQuestion,
  });
  const longPromptMessage = deliveryRequests
    .filter((entry) => entry.marker === "long-prompt").at(-1)?.body?.message;
  if (
    longPromptResult?.specialistQuestionDelivery?.disposition !== "delivered" ||
    typeof longPromptMessage !== "string" ||
    !longPromptMessage.includes(`Request: ${longPrompt}`) ||
    countRequests("long-prompt") !== 2
  ) throw new Error("valid long specialist prompt was rejected or truncated");

  for (const name of ["502", "malformed", "duplicate", "reset", "timeout"]) {
    const first = await executeCase(name);
    const replay = await executeCase(name, "replay");
    if (
      first?.specialistQuestionDelivery?.disposition !== "unknown" ||
      replay?.specialistQuestionDelivery?.disposition !== "unknown" ||
      countRequests(name) !== 1
    ) throw new Error(`${name} delivery was retried or misclassified`);
  }

  const concurrentResults = await Promise.all([
    executeCase("concurrent", "one"),
    executeCase("concurrent", "two"),
  ]);
  const concurrentDispositions = concurrentResults
    .map((entry) => entry?.specialistQuestionDelivery?.disposition).sort();
  if (
    countRequests("concurrent") !== 1 ||
    concurrentDispositions.join(",") !== "delivered,unknown"
  ) throw new Error("concurrent delivery reservation did not prevent a duplicate send");

  const oversize = caseQuestion("oversize");
  oversize.payload.questions[0].prompt = "x".repeat(3800);
  const oversizeResult = await recoveryAuthority.execute({
    tool: "request_human_input",
    callId: "delivery-oversize",
    arguments: oversize,
  });
  const oversizeId = oversizeResult?.interaction?.id;
  const oversizeLedger = (await db.select().from(activityLog)
    .where(eq(activityLog.entityId, oversizeId)))
    .find((entry) => entry.action === "issue.specialist_question_delivery");
  if (
    oversizeResult?.specialistQuestionDelivery?.disposition !== "failed" ||
    oversizeLedger?.details?.disposition !== "failed" ||
    oversizeLedger?.details?.failure !== "message_invalid_or_oversize" ||
    countRequests("oversize") !== 0
  ) throw new Error("oversize specialist question was truncated or sent");

  process.stdout.write(JSON.stringify({
    childId,
    parentIssueId,
    productRunId,
    recoveryRunId,
    chiefIssueId,
    chiefRunId,
    interactionId,
    committedBeforeWake,
  }));
} finally {
  if (mockHermes) await new Promise((resolve) => mockHermes.close(resolve));
  await closeRegisteredClients(databaseUrl);
}
