import { randomUUID } from "node:crypto";

import { eq } from "/app/server/node_modules/drizzle-orm/index.js";
import {
  activityLog,
  closeRegisteredClients,
  createDb,
  heartbeatRuns,
  issueThreadInteractions,
  issues,
} from "/app/packages/db/src/index.ts";
import { PaperclipRunnerToolAuthority } from "/app/server/src/services/native-runtime/paperclip-runner-tool-authority.ts";

const [companyId, projectId, chiefAgentId, productAgentId, growthAgentId] = process.argv.slice(2);
if (![companyId, projectId, chiefAgentId, productAgentId, growthAgentId].every(Boolean)) {
  throw new Error("usage: authority-fixture COMPANY PROJECT CHIEF PRODUCT GROWTH");
}

const databaseUrl = process.env.DATABASE_URL;
if (!databaseUrl) throw new Error("DATABASE_URL is required");

const db = createDb(databaseUrl);
const parentIssueId = randomUUID();
const productRunId = randomUUID();
const chiefIssueId = randomUUID();
const chiefRunId = randomUUID();
let committedBeforeWake = false;
let delegatedWake = null;

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
        required: true,
        options: [
          { id: "alpha", label: "Alpha" },
          { id: "beta", label: "Beta" },
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

  await db
    .update(heartbeatRuns)
    .set({ status: "succeeded", finishedAt: new Date() })
    .where(eq(heartbeatRuns.id, productRunId));
  await db
    .update(issues)
    .set({ executionRunId: null })
    .where(eq(issues.id, parentIssueId));

  process.stdout.write(JSON.stringify({
    childId,
    parentIssueId,
    productRunId,
    chiefIssueId,
    chiefRunId,
    interactionId,
    committedBeforeWake,
  }));
} finally {
  await closeRegisteredClients(databaseUrl);
}
