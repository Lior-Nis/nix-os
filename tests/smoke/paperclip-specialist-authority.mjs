import { randomUUID } from "node:crypto";

import { eq } from "/app/server/node_modules/drizzle-orm/index.js";
import {
  activityLog,
  closeRegisteredClients,
  createDb,
  heartbeatRuns,
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
    committedBeforeWake,
  }));
} finally {
  await closeRegisteredClients(databaseUrl);
}
