#!/usr/bin/env python3
"""Install Nix's fail-closed specialist boundary in the pinned Paperclip image.

Paperclip v2026.916.1 ships the native runner surface needed by Slice 3, but
its default tool catalog is company-wide and its runner allowlist does not
propagate the selected ``OPENCODE_API_KEY`` credential. Its OpenCode driver
also does not bind or redact that credential, stores ephemeral HOME data in the
checkpointed session root, and its SSH command runner drops the positional
arguments required by the native runner's ``sh -c`` launch contract. This
installer changes only those pinned source and compiled files.
Every input and output is hash locked; an unknown image or partial patch
refuses startup.

The bounded authority applies to every ``paperclip_runner`` session.  The
configured specialist IDs narrow only peer discovery, child assignment, and
the founder-decision relay; allowlist drift cannot restore the upstream broad
runner catalog.

The provider-pack helpers bind the remotely copied OpenCode runtime to this
same patch set.  An absent/stale marker causes an explicit rebuild.  Once a
marker matches, any manifest or artifact drift fails closed instead of being
silently replaced.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Callable


PINNED_PAPERCLIP_REVISION = "d554c4789ed3930f8a53ac9fdf6503b3187097da"
PROVIDER_PACK_MARKER = ".nix-specialist-patch.json"


def _replace_once(source: str, old: str, new: str, *, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(
            f"Paperclip specialist patch refused: expected one {label} anchor, found {count}"
        )
    return source.replace(old, new, 1)


def _replace_count(
    source: str, old: str, new: str, *, count: int, label: str
) -> str:
    actual = source.count(old)
    if actual != count:
        raise RuntimeError(
            f"Paperclip specialist patch refused: expected {count} {label} anchors, found {actual}"
        )
    return source.replace(old, new)


def _replace_once_in_region(
    source: str,
    start: str,
    end: str,
    old: str,
    new: str,
    *,
    label: str,
) -> str:
    start_index = source.find(start)
    end_index = source.find(end, start_index + len(start))
    if start_index < 0 or end_index < 0:
        raise RuntimeError(
            f"Paperclip specialist patch refused: {label} region missing"
        )
    segment = source[start_index:end_index]
    patched = _replace_once(segment, old, new, label=label)
    return source[:start_index] + patched + source[end_index:]


SPECIALIST_TS = '''
const NIX_SPECIALIST_ALLOWED_OPERATIONS = new Set([
  "get_task_context", "get_task_history",
  "list_documents", "read_document", "list_document_revisions", "write_document",
  "list_agents", "report_progress", "request_human_input", "create_task", "register_deliverable",
]);
const NIX_SPECIALIST_ALLOWED_INTERACTIONS = new Set(["ask_user_questions"]);
const NIX_CANONICAL_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function nixSpecialistAgentIds(): Set<string> {
  const raw = process.env.NIX_PAPERCLIP_SPECIALIST_AGENT_IDS?.trim() ?? "";
  if (!raw) return new Set();
  const ids = raw.split(",").map((value) => value.trim());
  if (ids.some((value) => !NIX_CANONICAL_UUID.test(value)) || new Set(ids).size !== ids.length) {
    throw new Error("nix_specialist_agent_ids_invalid");
  }
  return new Set(ids);
}

const NIX_SPECIALIST_AGENT_IDS = nixSpecialistAgentIds();
const NIX_FOUNDER_USER_ID = process.env.NIX_PAPERCLIP_FOUNDER_USER_ID?.trim() ?? "";
if (!/^[A-Za-z0-9_-]{1,128}$/.test(NIX_FOUNDER_USER_ID)) {
  throw new Error("nix_specialist_founder_user_id_invalid");
}

'''

SPECIALIST_JS = '''
const NIX_SPECIALIST_ALLOWED_OPERATIONS = new Set([
    "get_task_context", "get_task_history",
    "list_documents", "read_document", "list_document_revisions", "write_document",
    "list_agents", "report_progress", "request_human_input", "create_task", "register_deliverable",
]);
const NIX_SPECIALIST_ALLOWED_INTERACTIONS = new Set(["ask_user_questions"]);
const NIX_CANONICAL_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
function nixSpecialistAgentIds() {
    const raw = process.env.NIX_PAPERCLIP_SPECIALIST_AGENT_IDS?.trim() ?? "";
    if (!raw)
        return new Set();
    const ids = raw.split(",").map((value) => value.trim());
    if (ids.some((value) => !NIX_CANONICAL_UUID.test(value)) || new Set(ids).size !== ids.length) {
        throw new Error("nix_specialist_agent_ids_invalid");
    }
    return new Set(ids);
}
const NIX_SPECIALIST_AGENT_IDS = nixSpecialistAgentIds();
const NIX_FOUNDER_USER_ID = process.env.NIX_PAPERCLIP_FOUNDER_USER_ID?.trim() ?? "";
if (!/^[A-Za-z0-9_-]{1,128}$/.test(NIX_FOUNDER_USER_ID)) {
    throw new Error("nix_specialist_founder_user_id_invalid");
}
'''


def patch_tool_authority_ts(source: str) -> str:
    source = _replace_once(
        source,
        "]);\n\n"
        "type Binding = {\n",
        "]);\n" + SPECIALIST_TS + "\ntype Binding = {\n",
        label="TypeScript specialist policy insertion",
    )
    source = _replace_once(
        source,
        "    // Keep the provider session's direct tool catalog stable across ordinary\n",
        "    return definitions.filter((definition) =>\n"
        "      NIX_SPECIALIST_ALLOWED_OPERATIONS.has(String(definition.name)));\n"
        "    // Keep the provider session's direct tool catalog stable across ordinary\n",
        label="TypeScript specialist advertised-tool gate",
    )
    source = _replace_once(
        source,
        "  }): Promise<unknown> {\n"
        "    if (isConnectorTool(call.tool)) {\n",
        "  }): Promise<unknown> {\n"
        "    if (!NIX_SPECIALIST_ALLOWED_OPERATIONS.has(call.tool)) {\n"
        "      throw new Error(\"paperclip_runner_tool_not_advertised\");\n"
        "    }\n"
        "    if (isConnectorTool(call.tool)) {\n",
        label="TypeScript specialist execution gate",
    )
    source = _replace_once(
        source,
        "      || [\"paused\", \"terminated\", \"pending_approval\", \"error\"].includes(row.actor.status)\n",
        "      || Boolean(row.issue.conversationAgentId)\n"
        "      || [\"paused\", \"terminated\", \"pending_approval\", \"error\"].includes(row.actor.status)\n",
        label="TypeScript read binding conversation gate",
    )
    source = _replace_once(
        source,
        "    const assignee = await agentService(this.db).getById(assigneeAgentId);\n",
        "    if (!NIX_SPECIALIST_AGENT_IDS.has(assigneeAgentId)) {\n"
        "      throw new Error(\"nix_specialist_assignee_denied\");\n"
        "    }\n"
        "    const assignee = await agentService(this.db).getById(assigneeAgentId);\n",
        label="TypeScript child assignee gate",
    )
    source = _replace_once(
        source,
        "      const conversation = Boolean(context.issue.conversationAgentId);\n"
        "      const existingChild = await tx.select().from(issues).where(and(\n",
        "      const conversation = Boolean(context.issue.conversationAgentId);\n"
        "      if (conversation || !context.issue.projectId\n"
        "        || nullableProviderId(input.projectId) !== context.issue.projectId\n"
        "        || !NIX_SPECIALIST_AGENT_IDS.has(assigneeAgentId)\n"
        "      ) throw new Error(\"nix_specialist_child_scope_denied\");\n"
        "      const uniqueDependencyIds = [...new Set(blockedByIssueIds)];\n"
        "      if (uniqueDependencyIds.length !== blockedByIssueIds.length) {\n"
        "        throw new Error(\"nix_specialist_child_dependency_denied\");\n"
        "      }\n"
        "      for (const dependencyId of uniqueDependencyIds) {\n"
        "        const [dependency] = await tx.select({\n"
        "          projectId: issues.projectId, conversationAgentId: issues.conversationAgentId,\n"
        "        }).from(issues).where(and(\n"
        "          eq(issues.id, dependencyId), eq(issues.companyId, this.binding.companyId),\n"
        "        )).limit(1);\n"
        "        if (!dependency || dependency.projectId !== context.issue.projectId\n"
        "          || Boolean(dependency.conversationAgentId)) {\n"
        "          throw new Error(\"nix_specialist_child_dependency_denied\");\n"
        "        }\n"
        "      }\n"
        "      const existingChild = await tx.select().from(issues).where(and(\n",
        label="TypeScript child project gate",
    )
    source = _replace_once(
        source,
        '    if (!kind) throw new Error("paperclip_runner_interaction_kind_invalid");\n',
        '    if (!kind) throw new Error("paperclip_runner_interaction_kind_invalid");\n'
        '    if (!NIX_SPECIALIST_ALLOWED_INTERACTIONS.has(kind)) {\n'
        '      throw new Error("nix_specialist_interaction_kind_denied");\n'
        '    }\n',
        label="TypeScript specialist question-only gate",
    )
    source = _replace_once(
        source,
        "      || context.actor.companyId !== this.binding.companyId\n"
        "      || [\"paused\", \"terminated\", \"pending_approval\", \"error\"].includes(context.actor.status)\n",
        "      || context.actor.companyId !== this.binding.companyId\n"
        "      || Boolean(context.issue.conversationAgentId)\n"
        "      || [\"paused\", \"terminated\", \"pending_approval\", \"error\"].includes(context.actor.status)\n",
        label="TypeScript mutation binding conversation gate",
    )
    source = _replace_once(
        source,
        '      case "list_agents":\n'
        '        return { actors: (await agentService(this.db).list(this.binding.companyId)).map(redactedActor) };\n',
        '      case "list_agents": {\n'
        '        const actors = await agentService(this.db).list(this.binding.companyId);\n'
        '        return { actors: actors.filter((actor) => NIX_SPECIALIST_AGENT_IDS.has(actor.id)).map((actor) => ({\n'
        '          id: actor.id, name: actor.name, role: actor.role, title: actor.title, status: actor.status,\n'
        '        })) };\n'
        '      }\n',
        label="TypeScript specialist directory projection",
    )
    source = _replace_once(
        source,
        "          continuationPolicy: requiredString(input.continuationPolicy),\n"
        "          payload: {\n",
        "          continuationPolicy: \"wake_assignee\" as const,\n"
        "          resolverPolicy: \"human_only\" as const,\n"
        "          addresseeUserId: NIX_FOUNDER_USER_ID,\n"
        "          payload: {\n",
        label="TypeScript human-only founder routing",
    )
    return source


def patch_tool_authority_js(source: str) -> str:
    source = _replace_once(
        source,
        "]);\nfunction record(value) {\n",
        "]);\n" + SPECIALIST_JS + "function record(value) {\n",
        label="JavaScript specialist policy insertion",
    )
    source = _replace_once(
        source,
        "        // Keep the provider session's direct tool catalog stable across ordinary\n",
        "        return definitions.filter((definition) => NIX_SPECIALIST_ALLOWED_OPERATIONS.has(String(definition.name)));\n"
        "        // Keep the provider session's direct tool catalog stable across ordinary\n",
        label="JavaScript specialist advertised-tool gate",
    )
    source = _replace_once(
        source,
        "    async execute(call) {\n"
        "        if (isConnectorTool(call.tool)) {\n",
        "    async execute(call) {\n"
        "        if (!NIX_SPECIALIST_ALLOWED_OPERATIONS.has(call.tool)) {\n"
        "            throw new Error(\"paperclip_runner_tool_not_advertised\");\n"
        "        }\n"
        "        if (isConnectorTool(call.tool)) {\n",
        label="JavaScript specialist execution gate",
    )
    source = _replace_once(
        source,
        '            || ["paused", "terminated", "pending_approval", "error"].includes(row.actor.status)) {\n',
        '            || Boolean(row.issue.conversationAgentId)\n'
        '            || ["paused", "terminated", "pending_approval", "error"].includes(row.actor.status)) {\n',
        label="JavaScript read binding conversation gate",
    )
    source = _replace_once(
        source,
        "        const assignee = await agentService(this.db).getById(assigneeAgentId);\n",
        "        if (!NIX_SPECIALIST_AGENT_IDS.has(assigneeAgentId)) {\n"
        "            throw new Error(\"nix_specialist_assignee_denied\");\n"
        "        }\n"
        "        const assignee = await agentService(this.db).getById(assigneeAgentId);\n",
        label="JavaScript child assignee gate",
    )
    source = _replace_once(
        source,
        "            const conversation = Boolean(context.issue.conversationAgentId);\n"
        "            const existingChild = await tx.select().from(issues).where(and(",
        "            const conversation = Boolean(context.issue.conversationAgentId);\n"
        "            if (conversation || !context.issue.projectId\n"
        "                || nullableProviderId(input.projectId) !== context.issue.projectId\n"
        "                || !NIX_SPECIALIST_AGENT_IDS.has(assigneeAgentId))\n"
        "                throw new Error(\"nix_specialist_child_scope_denied\");\n"
        "            const uniqueDependencyIds = [...new Set(blockedByIssueIds)];\n"
        "            if (uniqueDependencyIds.length !== blockedByIssueIds.length)\n"
        "                throw new Error(\"nix_specialist_child_dependency_denied\");\n"
        "            for (const dependencyId of uniqueDependencyIds) {\n"
        "                const [dependency] = await tx.select({\n"
        "                    projectId: issues.projectId, conversationAgentId: issues.conversationAgentId,\n"
        "                }).from(issues).where(and(eq(issues.id, dependencyId), eq(issues.companyId, this.binding.companyId))).limit(1);\n"
        "                if (!dependency || dependency.projectId !== context.issue.projectId\n"
        "                    || Boolean(dependency.conversationAgentId))\n"
        "                    throw new Error(\"nix_specialist_child_dependency_denied\");\n"
        "            }\n"
        "            const existingChild = await tx.select().from(issues).where(and(",
        label="JavaScript child project gate",
    )
    source = _replace_once(
        source,
        '        if (!kind)\n'
        '            throw new Error("paperclip_runner_interaction_kind_invalid");\n',
        '        if (!kind)\n'
        '            throw new Error("paperclip_runner_interaction_kind_invalid");\n'
        '        if (!NIX_SPECIALIST_ALLOWED_INTERACTIONS.has(kind)) {\n'
        '            throw new Error("nix_specialist_interaction_kind_denied");\n'
        '        }\n',
        label="JavaScript specialist question-only gate",
    )
    source = _replace_once(
        source,
        "            || context.actor.companyId !== this.binding.companyId\n"
        '            || ["paused", "terminated", "pending_approval", "error"].includes(context.actor.status)) {\n',
        "            || context.actor.companyId !== this.binding.companyId\n"
        "            || Boolean(context.issue.conversationAgentId)\n"
        '            || ["paused", "terminated", "pending_approval", "error"].includes(context.actor.status)) {\n',
        label="JavaScript mutation binding conversation gate",
    )
    source = _replace_once(
        source,
        '            case "list_agents":\n'
        '                return { actors: (await agentService(this.db).list(this.binding.companyId)).map(redactedActor) };\n',
        '            case "list_agents": {\n'
        '                const actors = await agentService(this.db).list(this.binding.companyId);\n'
        '                return { actors: actors.filter((actor) => NIX_SPECIALIST_AGENT_IDS.has(actor.id)).map((actor) => ({\n'
        '                        id: actor.id, name: actor.name, role: actor.role, title: actor.title, status: actor.status,\n'
        '                    })) };\n'
        '            }\n',
        label="JavaScript specialist directory projection",
    )
    source = _replace_once(
        source,
        "                continuationPolicy: requiredString(input.continuationPolicy),\n"
        "                payload: {\n",
        "                continuationPolicy: \"wake_assignee\",\n"
        "                resolverPolicy: \"human_only\",\n"
        "                addresseeUserId: NIX_FOUNDER_USER_ID,\n"
        "                payload: {\n",
        label="JavaScript human-only founder routing",
    )
    return source


def patch_native_environment(source: str) -> str:
    return _replace_once(
        source,
        '  "CODEX_HOME",\n' if '  "CODEX_HOME",\n' in source else '    "CODEX_HOME",\n',
        ('  "CODEX_HOME",\n  "OPENCODE_API_KEY",\n'
         if '  "CODEX_HOME",\n' in source
         else '    "CODEX_HOME",\n    "OPENCODE_API_KEY",\n'),
        label="OpenCode provider host credential allowlist",
    )


def patch_runner_provider_environment(source: str) -> str:
    # The pinned Rust runnerd accepts OPENROUTER_API_KEY but filters the
    # OpenCode-native OPENCODE_API_KEY name before launching its provider.
    # Alias before the OpenCode transport sanitizer, which is the first
    # production boundary that sees the resolved run environment.
    anchor = (
        "  const candidate = { ...process.env, ...source };\n"
        if "  const candidate = { ...process.env, ...source };\n" in source
        else "    const candidate = { ...process.env, ...source };\n"
    )
    indent = anchor[: len(anchor) - len(anchor.lstrip())]
    return _replace_once(
        source,
        anchor,
        anchor
        + f'{indent}const opencodeApiKey = source?.OPENCODE_API_KEY;\n'
        f'{indent}const openrouterApiKey = candidate.OPENROUTER_API_KEY;\n'
        f'{indent}if (opencodeApiKey !== undefined && openrouterApiKey !== undefined && opencodeApiKey !== openrouterApiKey) {{\n'
        f'{indent}  throw new Error("nix_runner_provider_credential_conflict");\n'
        f'{indent}}}\n'
        f'{indent}if (opencodeApiKey !== undefined) candidate.OPENROUTER_API_KEY = opencodeApiKey;\n'
        f'{indent}delete candidate.OPENCODE_API_KEY;\n',
        label="OpenCode runner provider credential compatibility alias",
    )


def patch_http_log_redaction(source: str) -> str:
    needle = 'req.headers["x-telegram-bot-api-secret-token"]'
    matching_lines = [line for line in source.splitlines(keepends=True) if needle in line]
    if len(matching_lines) != 1:
        raise RuntimeError(
            "Paperclip specialist patch refused: founder relay log-redaction anchor missing"
        )
    line = matching_lines[0]
    indent = line[: len(line) - len(line.lstrip())]
    return _replace_once(
        source,
        line,
        line + indent + '\'req.headers["x-nix-founder-relay-signature"]\',\n',
        label="founder relay signature log redaction",
    )


def patch_opencode_driver(source: str) -> str:
    typescript_source = "  #acceptQuestion(properties: Record<string, unknown>): void {\n" in source
    if typescript_source:
        source = _replace_once(
            source,
            "  mkdtemp,\n  readFile,\n",
            "  mkdtemp,\n  readdir,\n  readFile,\n",
            label="OpenCode TypeScript readdir import",
        )
        source = _replace_once(
            source,
            'import { createServer } from "node:net";\n',
            'import { createServer } from "node:net";\nimport { tmpdir } from "node:os";\n',
            label="OpenCode TypeScript tmpdir import",
        )
        source = _replace_once(
            source,
            '  const isolatedHome = await mkdtemp(join(input.root, "home-"));\n',
            '  const legacyHomes = (await readdir(input.root, { withFileTypes: true }))\n'
            '    .filter((entry) => entry.name.startsWith("home-"));\n'
            '  await Promise.all(legacyHomes.map((entry) =>\n'
            '    rm(join(input.root, entry.name), { recursive: true, force: true })));\n'
            '  const isolatedHome = await mkdtemp(join(tmpdir(), "paperclip-opencode-home-"));\n',
            label="OpenCode TypeScript checkpoint-safe HOME",
        )
    else:
        source = _replace_once(
            source,
            "import { chmod, mkdir, mkdtemp, readFile, rm, writeFile, } from \"node:fs/promises\";\n",
            "import { chmod, mkdir, mkdtemp, readdir, readFile, rm, writeFile, } from \"node:fs/promises\";\n",
            label="OpenCode JavaScript readdir import",
        )
        source = _replace_once(
            source,
            'import { createServer } from "node:net";\n',
            'import { createServer } from "node:net";\nimport { tmpdir } from "node:os";\n',
            label="OpenCode JavaScript tmpdir import",
        )
        source = _replace_once(
            source,
            '    const isolatedHome = await mkdtemp(join(input.root, "home-"));\n',
            '    const legacyHomes = (await readdir(input.root, { withFileTypes: true }))\n'
            '        .filter((entry) => entry.name.startsWith("home-"));\n'
            '    await Promise.all(legacyHomes.map((entry) =>\n'
            '        rm(join(input.root, entry.name), { recursive: true, force: true })));\n'
            '    const isolatedHome = await mkdtemp(join(tmpdir(), "paperclip-opencode-home-"));\n',
            label="OpenCode JavaScript checkpoint-safe HOME",
        )
    provider_anchor = (
        "      [modelProvider!]: {\n        models: {\n"
        if typescript_source
        else "            [modelProvider]: {\n                models: {\n"
    )
    provider_replacement = (
        "      [modelProvider!]: {\n"
        "        options: { apiKey: input.options.environment?.OPENROUTER_API_KEY },\n"
        "        models: {\n"
        if typescript_source
        else "            [modelProvider]: {\n"
        "                options: { apiKey: input.options.environment?.OPENROUTER_API_KEY },\n"
        "                models: {\n"
    )
    source = _replace_once(
        source,
        provider_anchor,
        provider_replacement,
        label="OpenCode provider credential binding",
    )
    source = _replace_once(
        source,
        "          tools: { question: true },\n",
        "          tools: { question: false },\n",
        label="OpenCode turn question disable",
    )
    config_question_anchor = (
        "    tools: {\n      question: true,\n    },\n"
        if typescript_source
        else "        tools: {\n            question: true,\n        },\n"
    )
    source = _replace_once(
        source,
        config_question_anchor,
        config_question_anchor.replace("question: true", "question: false"),
        label="OpenCode configuration question disable",
    )
    permission_question_anchor = (
        '      question: "allow",\n'
        if typescript_source
        else '            question: "allow",\n'
    )
    source = _replace_once(
        source,
        permission_question_anchor,
        permission_question_anchor.replace('"allow"', '"deny"'),
        label="OpenCode question permission denial",
    )
    question_signature = (
        "  #acceptQuestion(properties: Record<string, unknown>): void {\n"
        if typescript_source
        else "  #acceptQuestion(properties) {\n"
    )
    source = _replace_once(
        source,
        question_signature,
        question_signature + '    throw new Error("nix_opencode_native_question_denied");\n',
        label="OpenCode native question fail-closed gate",
    )
    return source


def patch_opencode_proxy_bundle(source: str) -> str:
    """Patch the self-contained proxy artifact executed by remote workers."""

    commonjs_bundle = 'var import_promises3 = require("node:fs/promises");\n' in source
    if commonjs_bundle:
        source = _replace_once(
            source,
            'var import_promises3 = require("node:fs/promises");\n',
            'var import_promises3 = require("node:fs/promises");\n'
            'var import_node_os = require("node:os");\n',
            label="bundled CommonJS tmpdir import",
        )
        source = _replace_once(
            source,
            '  const isolatedHome = await (0, import_promises3.mkdtemp)((0, import_node_path3.join)(input2.root, "home-"));\n',
            '  const legacyHomes = (await (0, import_promises3.readdir)(input2.root, { withFileTypes: true }))\n'
            '    .filter((entry) => entry.name.startsWith("home-"));\n'
            '  await Promise.all(legacyHomes.map((entry) =>\n'
            '    (0, import_promises3.rm)((0, import_node_path3.join)(input2.root, entry.name), { recursive: true, force: true })));\n'
            '  const isolatedHome = await (0, import_promises3.mkdtemp)((0, import_node_path3.join)((0, import_node_os.tmpdir)(), "paperclip-opencode-home-"));\n',
            label="bundled CommonJS checkpoint-safe HOME",
        )
    else:
        source = _replace_once(
            source,
            "  mkdtemp,\n  readFile,\n",
            "  mkdtemp,\n  readdir as readdir2,\n  readFile,\n",
            label="bundled ESM readdir import",
        )
        source = _replace_once(
            source,
            'import { createServer as createServer2 } from "node:net";\n',
            'import { createServer as createServer2 } from "node:net";\n'
            'import { tmpdir } from "node:os";\n',
            label="bundled ESM tmpdir import",
        )
        source = _replace_once(
            source,
            '  const isolatedHome = await mkdtemp(join2(input2.root, "home-"));\n',
            '  const legacyHomes = (await readdir2(input2.root, { withFileTypes: true }))\n'
            '    .filter((entry) => entry.name.startsWith("home-"));\n'
            '  await Promise.all(legacyHomes.map((entry) =>\n'
            '    rm2(join2(input2.root, entry.name), { recursive: true, force: true })));\n'
            '  const isolatedHome = await mkdtemp(join2(tmpdir(), "paperclip-opencode-home-"));\n',
            label="bundled ESM checkpoint-safe HOME",
        )

    source = _replace_once(
        source,
        "      [modelProvider]: {\n        models: {\n",
        "      [modelProvider]: {\n"
        "        options: { apiKey: input2.options.environment?.OPENROUTER_API_KEY },\n"
        "        models: {\n",
        label="bundled OpenCode provider credential binding",
    )
    source = _replace_once(
        source,
        "          tools: { question: true },\n",
        "          tools: { question: false },\n",
        label="bundled OpenCode turn question disable",
    )
    source = _replace_once(
        source,
        "    tools: {\n      question: true\n    },\n",
        "    tools: {\n      question: false\n    },\n",
        label="bundled OpenCode configuration question disable",
    )
    source = _replace_once(
        source,
        '      question: "allow",\n',
        '      question: "deny",\n',
        label="bundled OpenCode question permission denial",
    )
    source = _replace_once(
        source,
        "  #acceptQuestion(properties) {\n",
        "  #acceptQuestion(properties) {\n"
        '    throw new Error("nix_opencode_native_question_denied");\n',
        label="bundled OpenCode native question fail-closed gate",
    )
    return source


FOUNDER_RELAY_TS = r'''
const NIX_RELAY_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const NIX_RELAY_INTEGER = /^(?:0|[1-9][0-9]{0,19})$/;
const NIX_RELAY_SPECIALIST_AGENT_IDS = new Set(
  (process.env.NIX_PAPERCLIP_SPECIALIST_AGENT_IDS ?? "")
    .split(",").map((value) => value.trim()).filter(Boolean),
);
const NIX_RELAY_FOUNDER_USER_ID = process.env.PAPERCLIP_LIOR_USER_ID?.trim() ?? "";
const NIX_RELAY_CHIEF_AGENT_ID = process.env.NIX_CHIEF_AGENT_ID?.trim() ?? "";
const NIX_RELAY_TELEGRAM_USER_ID = process.env.NIX_LIOR_TELEGRAM_USER_ID?.trim() ?? "";
const NIX_RELAY_TELEGRAM_CHAT_ID = process.env.NIX_LIOR_TELEGRAM_CHAT_ID?.trim() ?? "";
const NIX_RELAY_SECRET = process.env.NIX_FOUNDER_RELAY_SECRET ?? "";
if (NIX_RELAY_SPECIALIST_AGENT_IDS.size > 0 && (
  [...NIX_RELAY_SPECIALIST_AGENT_IDS].some((value) => !NIX_RELAY_UUID.test(value))
  || !/^[A-Za-z0-9_-]{1,128}$/.test(NIX_RELAY_FOUNDER_USER_ID)
  || !NIX_RELAY_UUID.test(NIX_RELAY_CHIEF_AGENT_ID)
  || !NIX_RELAY_INTEGER.test(NIX_RELAY_TELEGRAM_USER_ID)
  || !NIX_RELAY_INTEGER.test(NIX_RELAY_TELEGRAM_CHAT_ID)
  || NIX_RELAY_SECRET.length < 32
)) throw new Error("nix_founder_relay_configuration_invalid");

function nixRelayCanonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(nixRelayCanonicalJson).join(",")}]`;
  if (value && typeof value === "object") {
    const object = value as Record<string, unknown>;
    return `{${Object.keys(object).sort().map((key) =>
      `${JSON.stringify(key)}:${nixRelayCanonicalJson(object[key])}`).join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

async function verifyNixFounderRelay(input: {
  req: Request;
  db: Db;
  issue: { id: string; companyId: string; assigneeAgentId?: string | null };
  interactionId: string;
}) {
  const signature = input.req.get("X-Nix-Founder-Relay-Signature")?.trim() ?? "";
  const version = input.req.get("X-Nix-Founder-Relay-Version")?.trim() ?? "";
  if (!signature && !version) return null;
  const deny = (): never => { throw forbidden("Founder relay attestation is invalid"); };
  const actor = getActorInfo(input.req);
  if (NIX_RELAY_SPECIALIST_AGENT_IDS.size === 0 || actor.actorType !== "agent"
    || actor.agentId !== NIX_RELAY_CHIEF_AGENT_ID || actor.actorId !== NIX_RELAY_CHIEF_AGENT_ID
    || version !== "1") deny();
  const timestamp = input.req.get("X-Nix-Founder-Relay-Timestamp")?.trim() ?? "";
  const idempotencyKey = input.req.get("X-Nix-Founder-Relay-Idempotency-Key")?.trim() ?? "";
  const platform = input.req.get("X-Nix-Founder-Relay-Platform")?.trim() ?? "";
  const chatType = input.req.get("X-Nix-Founder-Relay-Chat-Type")?.trim() ?? "";
  const userId = input.req.get("X-Nix-Founder-Relay-User-Id")?.trim() ?? "";
  const chatId = input.req.get("X-Nix-Founder-Relay-Chat-Id")?.trim() ?? "";
  const messageId = input.req.get("X-Nix-Founder-Relay-Message-Id")?.trim() ?? "";
  if (!/^[0-9]{10}$/.test(timestamp) || Math.abs(Math.floor(Date.now() / 1000) - Number(timestamp)) > 120
    || !/^[A-Za-z0-9._:-]{1,240}$/.test(idempotencyKey)
    || platform !== "telegram" || chatType !== "dm"
    || userId !== NIX_RELAY_TELEGRAM_USER_ID || chatId !== NIX_RELAY_TELEGRAM_CHAT_ID
    || !NIX_RELAY_INTEGER.test(messageId)
    || !/^v1=[0-9a-f]{64}$/.test(signature)
    || !input.req.body || typeof input.req.body !== "object" || Array.isArray(input.req.body)
    || Object.keys(input.req.body).some((key) => key !== "answers")) deny();
  const path = `/api/issues/${input.issue.id}/interactions/${input.interactionId}/respond`;
  if (input.req.originalUrl.split("?", 1)[0] !== path) deny();
  const bodyDigest = createHash("sha256")
    .update(nixRelayCanonicalJson(input.req.body)).digest("hex");
  const canonical = ["v1", timestamp, "POST", path, bodyDigest, platform, chatType,
    userId, chatId, messageId, idempotencyKey].join("\n");
  const expected = createHmac("sha256", NIX_RELAY_SECRET).update(canonical).digest();
  const supplied = Buffer.from(signature.slice(3), "hex");
  if (supplied.length !== expected.length || !timingSafeEqual(supplied, expected)) deny();

  const [interaction] = await input.db.select({
    id: issueThreadInteractions.id, issueId: issueThreadInteractions.issueId,
    companyId: issueThreadInteractions.companyId, status: issueThreadInteractions.status,
    kind: issueThreadInteractions.kind, continuationPolicy: issueThreadInteractions.continuationPolicy,
    effectiveResolverPolicy: issueThreadInteractions.effectiveResolverPolicy,
    addresseeUserId: issueThreadInteractions.addresseeUserId,
    sourceRunId: issueThreadInteractions.sourceRunId,
    resolvedByUserId: issueThreadInteractions.resolvedByUserId,
  }).from(issueThreadInteractions).where(and(
    eq(issueThreadInteractions.id, input.interactionId),
    eq(issueThreadInteractions.issueId, input.issue.id),
    eq(issueThreadInteractions.companyId, input.issue.companyId),
  )).limit(1);
  const sourceRunId: string | null = typeof interaction?.sourceRunId === "string"
    && NIX_RELAY_UUID.test(interaction.sourceRunId) ? interaction.sourceRunId : null;
  if (!interaction || !["pending", "answered"].includes(interaction.status)
    || interaction.kind !== "ask_user_questions"
    || interaction.continuationPolicy !== "wake_assignee"
    || interaction.effectiveResolverPolicy !== "human_only"
    || interaction.addresseeUserId !== NIX_RELAY_FOUNDER_USER_ID || !sourceRunId
    || !input.issue.assigneeAgentId) deny();
  const verifiedSourceRunId: string = sourceRunId!;
  const [sourceRun] = await input.db.select({
    agentId: heartbeatRuns.agentId, companyId: heartbeatRuns.companyId,
    issueId: heartbeatRuns.nativeIssueId,
  }).from(heartbeatRuns).where(and(
    eq(heartbeatRuns.id, verifiedSourceRunId),
    eq(heartbeatRuns.companyId, input.issue.companyId),
    eq(heartbeatRuns.nativeIssueId, input.issue.id),
  )).limit(1);
  if (!sourceRun || sourceRun.agentId !== input.issue.assigneeAgentId
    || (sourceRun.agentId !== NIX_RELAY_CHIEF_AGENT_ID
      && !NIX_RELAY_SPECIALIST_AGENT_IDS.has(sourceRun.agentId))) deny();
  const priorRelayReservations = await input.db.select({
    details: activityLog.details,
  }).from(activityLog).where(and(
    eq(activityLog.companyId, input.issue.companyId),
    eq(activityLog.entityType, "issue"),
    eq(activityLog.entityId, input.issue.id),
    eq(activityLog.action, "issue.founder_relay_reserved"),
    sql`${activityLog.details}->>'interactionId' = ${interaction.id}`,
  )).orderBy(desc(activityLog.createdAt), desc(activityLog.id)).limit(10);
  const reservationExists = priorRelayReservations.some(({ details }) => {
      if (!details || typeof details !== "object" || Array.isArray(details)) return false;
      const activityDetails = details as Record<string, unknown>;
      const receipt = activityDetails.nixFounderRelayReservation;
      if (!receipt || typeof receipt !== "object" || Array.isArray(receipt)) return false;
      const relay = receipt as Record<string, unknown>;
      return relay.version === 1
        && relay.interactionId === interaction.id && relay.issueId === input.issue.id
        && relay.resolverUserId === NIX_RELAY_FOUNDER_USER_ID
        && relay.sourceMessageId === messageId && relay.idempotencyKey === idempotencyKey
        && relay.originAgentId === sourceRun.agentId
        && relay.requestBodySha256 === bodyDigest;
  });
  if (priorRelayReservations.length > 0 && !reservationExists) deny();
  const replayed = interaction.status === "answered";
  if (replayed && (
    interaction.resolvedByUserId !== NIX_RELAY_FOUNDER_USER_ID || !reservationExists
  )) deny();
  return {
    resolverUserId: NIX_RELAY_FOUNDER_USER_ID,
    sourceMessageId: messageId,
    idempotencyKey,
    originAgentId: sourceRun.agentId,
    bodyDigest,
    replayed,
    reservationExists,
  };
}

async function deliverNixFounderRelayContinuation(input: {
  db: Db;
  deliveries: ReturnType<typeof questionResponseDeliveryService>;
  interactionId: string;
  companyId: string;
  issueId: string;
  originAgentId: string;
}): Promise<boolean> {
  const outcome = await input.deliveries.deliver(input.interactionId).catch((err) => {
    logger.warn({ err, companyId: input.companyId, issueId: input.issueId,
      interactionId: input.interactionId },
    "synchronous founder response delivery failed; durable outbox will retry");
    return null;
  });
  if (!outcome?.targetRunId
    || !["delivered", "fallback_queued"].includes(outcome.status)) return false;
  const [targetRun] = await input.db.select({
    agentId: heartbeatRuns.agentId, nativeIssueId: heartbeatRuns.nativeIssueId,
    contextSnapshot: heartbeatRuns.contextSnapshot,
  })
    .from(heartbeatRuns).where(and(
      eq(heartbeatRuns.id, outcome.targetRunId),
      eq(heartbeatRuns.companyId, input.companyId),
    )).limit(1);
  const targetContext = targetRun?.contextSnapshot;
  const targetRecord = targetContext && typeof targetContext === "object"
    && !Array.isArray(targetContext)
    ? targetContext as Record<string, unknown> : null;
  const targetIssueId = targetRun?.nativeIssueId
    ?? (typeof targetRecord?.issueId === "string" ? targetRecord.issueId
      : typeof targetRecord?.taskId === "string" ? targetRecord.taskId : null);
  return targetRun?.agentId === input.originAgentId && targetIssueId === input.issueId;
}
'''

FOUNDER_RELAY_JS = FOUNDER_RELAY_TS.replace(
    "function nixRelayCanonicalJson(value: unknown): string {", "function nixRelayCanonicalJson(value) {"
).replace(
    "    const object = value as Record<string, unknown>;", "    const object = value;"
).replace(
    "const deny = (): never =>", "const deny = () =>"
).replace(
    "  const sourceRunId: string | null =", "  const sourceRunId ="
).replace(
    "  const verifiedSourceRunId: string = sourceRunId!;", "  const verifiedSourceRunId = sourceRunId;"
).replace(
    "      const activityDetails = details as Record<string, unknown>;", "      const activityDetails = details;"
).replace(
    "      const relay = receipt as Record<string, unknown>;", "      const relay = receipt;"
).replace(
    "    ? targetContext as Record<string, unknown> : null;",
    "    ? targetContext : null;",
)
# The route's compiled JavaScript has no TypeScript-only helper parameter block.
FOUNDER_RELAY_JS = re.sub(
    r"async function verifyNixFounderRelay\(input: \{\n(?:.*\n){4}\}\) \{",
    "async function verifyNixFounderRelay(input) {",
    FOUNDER_RELAY_JS,
)
FOUNDER_RELAY_JS = re.sub(
    r"async function deliverNixFounderRelayContinuation\(input: \{\n(?:.*\n){6}\}\): Promise<boolean> \{",
    "async function deliverNixFounderRelayContinuation(input) {",
    FOUNDER_RELAY_JS,
)


FOUNDER_DELIVERY_TS = r'''
const NIX_FOUNDER_DELIVERY_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const NIX_FOUNDER_DELIVERY_SPECIALIST_IDS = new Set(
  (process.env.NIX_PAPERCLIP_SPECIALIST_AGENT_IDS ?? "")
    .split(",").map((value) => value.trim()).filter(Boolean),
);
const NIX_FOUNDER_DELIVERY_CHIEF_ID = process.env.NIX_CHIEF_AGENT_ID?.trim() ?? "";
const NIX_FOUNDER_DELIVERY_USER_ID = process.env.PAPERCLIP_LIOR_USER_ID?.trim() ?? "";

function nixFounderDeliveryOrigin(
  interaction: QuestionInteractionRow,
  sourceRun: typeof heartbeatRuns.$inferSelect | null,
): string | null {
  if (!sourceRun || !NIX_FOUNDER_DELIVERY_UUID.test(sourceRun.agentId)
    || !NIX_FOUNDER_DELIVERY_UUID.test(NIX_FOUNDER_DELIVERY_CHIEF_ID)
    || NIX_FOUNDER_DELIVERY_SPECIALIST_IDS.size === 0
    || [...NIX_FOUNDER_DELIVERY_SPECIALIST_IDS].some(
      (value) => !NIX_FOUNDER_DELIVERY_UUID.test(value))
    || !/^[A-Za-z0-9_-]{1,128}$/.test(NIX_FOUNDER_DELIVERY_USER_ID)
    || interaction.kind !== "ask_user_questions"
    || interaction.continuationPolicy !== "wake_assignee"
    || interaction.effectiveResolverPolicy !== "human_only"
    || interaction.addresseeUserId !== NIX_FOUNDER_DELIVERY_USER_ID
    || interaction.resolvedByUserId !== NIX_FOUNDER_DELIVERY_USER_ID
    || interaction.sourceRunId !== sourceRun.id
    || sourceRun.companyId !== interaction.companyId
    || issueIdFromRun(sourceRun) !== interaction.issueId
    || (sourceRun.agentId !== NIX_FOUNDER_DELIVERY_CHIEF_ID
      && !NIX_FOUNDER_DELIVERY_SPECIALIST_IDS.has(sourceRun.agentId))) return null;
  return sourceRun.agentId;
}
'''

FOUNDER_DELIVERY_JS = FOUNDER_DELIVERY_TS.replace(
    "function nixFounderDeliveryOrigin(\n"
    "  interaction: QuestionInteractionRow,\n"
    "  sourceRun: typeof heartbeatRuns.$inferSelect | null,\n"
    "): string | null {",
    "function nixFounderDeliveryOrigin(interaction, sourceRun) {",
)


def patch_question_response_delivery_ts(source: str) -> str:
    source = _replace_once(
        source,
        "type QuestionInteractionRow = typeof issueThreadInteractions.$inferSelect;\n",
        "type QuestionInteractionRow = typeof issueThreadInteractions.$inferSelect;\n"
        + FOUNDER_DELIVERY_TS,
        label="TypeScript immutable founder delivery origin",
    )
    source = _replace_once(
        source,
        "    const assigneeAgentId = issue.assigneeAgentId;\n",
        "    const nixFounderOriginAgentId = nixFounderDeliveryOrigin(interaction, sourceRun);\n"
        "    if (nixFounderOriginAgentId\n"
        "      && issue.assigneeAgentId !== nixFounderOriginAgentId) {\n"
        "      await releaseForRetry(claimed, \"nix_founder_origin_assignment_changed\",\n"
        "        { bounded: false });\n"
        "      return null;\n"
        "    }\n"
        "    const assigneeAgentId = nixFounderOriginAgentId ?? issue.assigneeAgentId;\n",
        label="TypeScript immutable founder delivery target",
    )
    source = _replace_once(
        source,
        "      const coalesced = Boolean(\n"
        "        eligibleQueuedSuccessor && targetRun?.id === eligibleQueuedSuccessor.id,\n"
        "      );\n"
        "      return recordTerminal({\n",
        "      const coalesced = Boolean(\n"
        "        eligibleQueuedSuccessor && targetRun?.id === eligibleQueuedSuccessor.id,\n"
        "      );\n"
        "      const nixFounderWakeAgentId = targetRun?.agentId\n"
        "        ?? durableWake?.request.agentId ?? existingWake?.request.agentId ?? null;\n"
        "      if (nixFounderOriginAgentId && (\n"
        "        !targetRun || nixFounderWakeAgentId !== nixFounderOriginAgentId\n"
        "      )) {\n"
        "        await releaseForRetry(claimed, \"nix_founder_continuation_pending\",\n"
        "          { bounded: false });\n"
        "        return null;\n"
        "      }\n"
        "      return recordTerminal({\n",
        label="TypeScript founder delivery acknowledgement",
    )
    return source


def patch_question_response_delivery_js(source: str) -> str:
    source = _replace_once(
        source,
        'const DELIVERY_CLAIM_STALE_MS = 30_000;\n',
        'const DELIVERY_CLAIM_STALE_MS = 30_000;\n' + FOUNDER_DELIVERY_JS,
        label="JavaScript immutable founder delivery origin",
    )
    source = _replace_once(
        source,
        "        const assigneeAgentId = issue.assigneeAgentId;\n",
        "        const nixFounderOriginAgentId = nixFounderDeliveryOrigin(interaction, sourceRun);\n"
        "        if (nixFounderOriginAgentId && issue.assigneeAgentId !== nixFounderOriginAgentId) {\n"
        "            await releaseForRetry(claimed, \"nix_founder_origin_assignment_changed\", { bounded: false });\n"
        "            return null;\n"
        "        }\n"
        "        const assigneeAgentId = nixFounderOriginAgentId ?? issue.assigneeAgentId;\n",
        label="JavaScript immutable founder delivery target",
    )
    source = _replace_once(
        source,
        "            const coalesced = Boolean(eligibleQueuedSuccessor && targetRun?.id === eligibleQueuedSuccessor.id);\n"
        "            return recordTerminal({\n",
        "            const coalesced = Boolean(eligibleQueuedSuccessor && targetRun?.id === eligibleQueuedSuccessor.id);\n"
        "            const nixFounderWakeAgentId = targetRun?.agentId\n"
        "                ?? durableWake?.request.agentId ?? existingWake?.request.agentId ?? null;\n"
        "            if (nixFounderOriginAgentId && (!targetRun || nixFounderWakeAgentId !== nixFounderOriginAgentId)) {\n"
        "                await releaseForRetry(claimed, \"nix_founder_continuation_pending\", { bounded: false });\n"
        "                return null;\n"
        "            }\n"
        "            return recordTerminal({\n",
        label="JavaScript founder delivery acknowledgement",
    )
    return source


def patch_issues_route_ts(source: str) -> str:
    source = _replace_once(
        source,
        'import { createHash, randomUUID } from "node:crypto";\n',
        'import { createHash, createHmac, randomUUID, timingSafeEqual } from "node:crypto";\n',
        label="TypeScript founder relay crypto import",
    )
    source = _replace_once(
        source,
        "const MAX_ISSUE_COMMENT_LIMIT = 500;\n",
        "const MAX_ISSUE_COMMENT_LIMIT = 500;\n" + FOUNDER_RELAY_TS,
        label="TypeScript founder relay verifier",
    )
    source = _replace_once(
        source,
        "      const authorizedResolution =\n"
        "        await getIssueThreadInteractionResolutionAuthorization(\n"
        "          req,\n"
        "          res,\n"
        "          issue,\n"
        "          interactionId,\n"
        "        );\n"
        "      if (!authorizedResolution) return;\n"
        "      const { interactionSvc, current, resolutionAuthorization } =\n"
        "        authorizedResolution;\n\n"
        "      const actor = getActorInfo(req);\n",
        "      const founderRelay = await verifyNixFounderRelay({ req, db, issue, interactionId });\n"
        "      const authorizedResolution = founderRelay ? null\n"
        "        : await getIssueThreadInteractionResolutionAuthorization(req, res, issue, interactionId);\n"
        "      const ordinaryAuthorization = authorizedResolution || null;\n"
        "      if (!founderRelay && !ordinaryAuthorization) return;\n"
        "      const interactionSvc = founderRelay ? issueThreadInteractionService(db)\n"
        "        : ordinaryAuthorization!.interactionSvc;\n"
        "      const current = founderRelay ? await interactionSvc.getForIssue(issue, interactionId)\n"
        "        : ordinaryAuthorization!.current;\n"
        "      const [nixFounderSourceRun] = typeof current.sourceRunId === \"string\"\n"
        "        && NIX_RELAY_UUID.test(current.sourceRunId)\n"
        "        ? await db.select({ agentId: heartbeatRuns.agentId }).from(heartbeatRuns).where(and(\n"
        "            eq(heartbeatRuns.id, current.sourceRunId),\n"
        "            eq(heartbeatRuns.companyId, issue.companyId),\n"
        "            eq(heartbeatRuns.nativeIssueId, issue.id),\n"
        "          )).limit(1) : [];\n"
        "      const nixFounderInteraction = current.kind === \"ask_user_questions\"\n"
        "        && current.continuationPolicy === \"wake_assignee\"\n"
        "        && current.effectiveResolverPolicy === \"human_only\"\n"
        "        && current.addresseeUserId === NIX_RELAY_FOUNDER_USER_ID\n"
        "        && typeof current.sourceRunId === \"string\" && NIX_RELAY_UUID.test(current.sourceRunId)\n"
        "        && (nixFounderSourceRun?.agentId === NIX_RELAY_CHIEF_AGENT_ID\n"
        "          || NIX_RELAY_SPECIALIST_AGENT_IDS.has(nixFounderSourceRun?.agentId ?? \"\"));\n"
        "      if (!founderRelay && nixFounderInteraction) {\n"
        "        res.status(403).json({ error: \"nix_founder_relay_required\" });\n"
        "        return;\n"
        "      }\n"
        "      const resolutionAuthorization = founderRelay\n"
        "        ? { resolverPolicyRestriction: null, decision: { reason: \"nix_founder_relay\" } }\n"
        "        : ordinaryAuthorization!.resolutionAuthorization;\n\n"
        "      const actor = getActorInfo(req);\n"
        "      const resolutionActor = founderRelay ? {\n"
        "        actorType: \"user\" as const, actorId: founderRelay.resolverUserId,\n"
        "        agentId: null, runId: null, agentApiKeyId: null,\n"
        "      } : actor;\n"
        "      const nixFounderRelay = founderRelay ? {\n"
        "        version: 1 as const, verified: true as const, interactionId: current.id,\n"
        "        issueId: issue.id, resolverUserId: founderRelay.resolverUserId,\n"
        "        sourceMessageId: founderRelay.sourceMessageId,\n"
        "        idempotencyKey: founderRelay.idempotencyKey,\n"
        "        originAgentId: founderRelay.originAgentId,\n"
        "        resumedAgentId: founderRelay.originAgentId, replayed: founderRelay.replayed,\n"
        "      } : null;\n"
        "      if (founderRelay?.replayed) {\n"
        "        if (current.kind === \"ask_user_questions\") {\n"
        "          validateNativeQuestionResponseInput(current, req.body);\n"
        "        }\n"
        "        const delivered = await deliverNixFounderRelayContinuation({ db,\n"
        "          deliveries: questionResponseDeliveries, interactionId: current.id,\n"
        "          companyId: issue.companyId, issueId: issue.id,\n"
        "          originAgentId: founderRelay.originAgentId });\n"
        "        if (!delivered) {\n"
        "          res.status(503).json({ error: \"nix_founder_relay_continuation_pending\" });\n"
        "          return;\n"
        "        }\n"
        "        res.json({ ...current, nixFounderRelay });\n"
        "        return;\n"
        "      }\n",
        label="TypeScript founder relay authorization path",
    )
    source = _replace_once(
        source,
        "          agentId: actor.agentId,\n"
        "          runId: actor.runId,\n"
        "          userId: actor.actorType === \"user\" ? actor.actorId : null,\n"
        "          resolverPolicyRestriction:\n"
        "            resolutionAuthorization.resolverPolicyRestriction,\n"
        "        },\n"
        "      );\n\n"
        "      await logActivity(db, {\n"
        "        companyId: issue.companyId,\n"
        "        actorType: actor.actorType,\n"
        "        actorId: actor.actorId,\n"
        "        agentId: actor.agentId,\n"
        "        runId: actor.runId,\n"
        "        agentApiKeyId: actor.agentApiKeyId,\n"
        "        action: \"issue.thread_interaction_answered\",\n",
        "          agentId: resolutionActor.agentId,\n"
        "          runId: resolutionActor.runId,\n"
        "          userId: resolutionActor.actorType === \"user\" ? resolutionActor.actorId : null,\n"
        "          resolverPolicyRestriction:\n"
        "            resolutionAuthorization.resolverPolicyRestriction,\n"
        "        },\n"
        "        founderRelay ? { beforeResolveInTransaction: async (tx) => {\n"
        "          const [lockedIssue] = await tx.select({\n"
        "            companyId: issueRows.companyId, assigneeAgentId: issueRows.assigneeAgentId,\n"
        "          }).from(issueRows).where(and(\n"
        "            eq(issueRows.id, issue.id), eq(issueRows.companyId, issue.companyId),\n"
        "          )).for(\"update\").limit(1);\n"
        "          if (!lockedIssue || lockedIssue.assigneeAgentId !== founderRelay.originAgentId)\n"
        "            throw forbidden(\"Founder relay origin assignment changed\");\n"
        "          if (founderRelay.reservationExists) return;\n"
        "          await tx.insert(activityLog).values({\n"
        "            companyId: issue.companyId, actorType: actor.actorType, actorId: actor.actorId,\n"
        "            agentId: actor.agentId, runId: actor.runId,\n"
        "            action: \"issue.founder_relay_reserved\", entityType: \"issue\", entityId: issue.id,\n"
        "            details: { interactionId: current.id, nixFounderRelayReservation: {\n"
        "              version: 1, interactionId: current.id, issueId: issue.id,\n"
        "              resolverUserId: founderRelay.resolverUserId,\n"
        "              sourceMessageId: founderRelay.sourceMessageId,\n"
        "              idempotencyKey: founderRelay.idempotencyKey,\n"
        "              originAgentId: founderRelay.originAgentId,\n"
        "              requestBodySha256: founderRelay.bodyDigest,\n"
        "            } },\n"
        "          });\n"
        "        } } : {},\n"
        "      );\n"
        "      await logActivity(db, {\n"
        "        companyId: issue.companyId,\n"
        "        actorType: resolutionActor.actorType,\n"
        "        actorId: resolutionActor.actorId,\n"
        "        agentId: resolutionActor.agentId,\n"
        "        runId: resolutionActor.runId,\n"
        "        agentApiKeyId: resolutionActor.agentApiKeyId,\n"
        "        action: \"issue.thread_interaction_answered\",\n",
        label="TypeScript founder relay resolution actor",
    )
    source = _replace_once_in_region(
        source,
        '    "/issues/:id/interactions/:interactionId/respond",\n',
        '    "/issues/:id/interactions/:interactionId/verdicts",\n',
        "          resolutionActorKind: actor.actorType,\n"
        "          requestedResolverPolicy: interaction.requestedResolverPolicy,\n",
        "          resolutionActorKind: resolutionActor.actorType,\n"
        "          ...(nixFounderRelay ? { nixFounderRelay: { ...nixFounderRelay,\n"
        "              resumedAgentId: null, continuationStatus: \"pending\" },\n"
        "            nixFounderRelayRequestBodySha256: founderRelay!.bodyDigest } : {}),\n"
        "          requestedResolverPolicy: interaction.requestedResolverPolicy,\n",
        label="TypeScript founder relay activity receipt",
    )
    source = _replace_once(
        source,
        "      await questionResponseDeliveries.deliver(interaction.id).catch((err) => {\n"
        "        logger.warn(\n"
        "          {\n"
        "            err,\n"
        "            companyId: issue.companyId,\n"
        "            issueId: issue.id,\n"
        "            interactionId: interaction.id,\n"
        "          },\n"
        "          \"synchronous question response delivery failed; durable outbox will retry\",\n"
        "        );\n"
        "      });\n\n"
        "      res.json(interaction);\n"
        "    },\n"
        "  );\n\n"
        "  router.post(\n"
        "    \"/issues/:id/interactions/:interactionId/verdicts\",\n",
        "      if (nixFounderRelay) {\n"
        "        const delivered = await deliverNixFounderRelayContinuation({ db,\n"
        "          deliveries: questionResponseDeliveries, interactionId: interaction.id,\n"
        "          companyId: issue.companyId, issueId: issue.id,\n"
        "          originAgentId: founderRelay!.originAgentId });\n"
        "        if (!delivered) {\n"
        "          res.status(503).json({ error: \"nix_founder_relay_continuation_pending\" });\n"
        "          return;\n"
        "        }\n"
        "      } else {\n"
        "        await questionResponseDeliveries.deliver(interaction.id).catch((err) => {\n"
        "          logger.warn({ err, companyId: issue.companyId, issueId: issue.id,\n"
        "            interactionId: interaction.id },\n"
        "          \"synchronous question response delivery failed; durable outbox will retry\");\n"
        "        });\n"
        "      }\n"
        "      res.json(nixFounderRelay ? { ...interaction, nixFounderRelay } : interaction);\n"
        "    },\n"
        "  );\n\n"
        "  router.post(\n"
        "    \"/issues/:id/interactions/:interactionId/verdicts\",\n",
        label="TypeScript founder relay response receipt",
    )
    return source


def patch_issues_route_js(source: str) -> str:
    source = _replace_once(
        source,
        'import { createHash, randomUUID } from "node:crypto";\n',
        'import { createHash, createHmac, randomUUID, timingSafeEqual } from "node:crypto";\n',
        label="JavaScript founder relay crypto import",
    )
    source = _replace_once(
        source,
        "const MAX_ISSUE_COMMENT_LIMIT = 500;\n",
        "const MAX_ISSUE_COMMENT_LIMIT = 500;\n" + FOUNDER_RELAY_JS,
        label="JavaScript founder relay verifier",
    )
    source = _replace_once(
        source,
        "        const authorizedResolution = await getIssueThreadInteractionResolutionAuthorization(req, res, issue, interactionId);\n"
        "        if (!authorizedResolution)\n"
        "            return;\n"
        "        const { interactionSvc, current, resolutionAuthorization } = authorizedResolution;\n"
        "        const actor = getActorInfo(req);\n",
        "        const founderRelay = await verifyNixFounderRelay({ req, db, issue, interactionId });\n"
        "        const authorizedResolution = founderRelay ? null\n"
        "            : await getIssueThreadInteractionResolutionAuthorization(req, res, issue, interactionId);\n"
        "        if (!founderRelay && !authorizedResolution)\n"
        "            return;\n"
        "        const interactionSvc = founderRelay ? issueThreadInteractionService(db) : authorizedResolution.interactionSvc;\n"
        "        const current = founderRelay ? await interactionSvc.getForIssue(issue, interactionId) : authorizedResolution.current;\n"
        "        const [nixFounderSourceRun] = typeof current.sourceRunId === \"string\"\n"
        "            && NIX_RELAY_UUID.test(current.sourceRunId)\n"
        "            ? await db.select({ agentId: heartbeatRuns.agentId }).from(heartbeatRuns).where(and(\n"
        "                eq(heartbeatRuns.id, current.sourceRunId),\n"
        "                eq(heartbeatRuns.companyId, issue.companyId),\n"
        "                eq(heartbeatRuns.nativeIssueId, issue.id),\n"
        "            )).limit(1) : [];\n"
        "        const nixFounderInteraction = current.kind === \"ask_user_questions\"\n"
        "            && current.continuationPolicy === \"wake_assignee\"\n"
        "            && current.effectiveResolverPolicy === \"human_only\"\n"
        "            && current.addresseeUserId === NIX_RELAY_FOUNDER_USER_ID\n"
        "            && typeof current.sourceRunId === \"string\" && NIX_RELAY_UUID.test(current.sourceRunId)\n"
        "            && (nixFounderSourceRun?.agentId === NIX_RELAY_CHIEF_AGENT_ID\n"
        "                || NIX_RELAY_SPECIALIST_AGENT_IDS.has(nixFounderSourceRun?.agentId ?? \"\"));\n"
        "        if (!founderRelay && nixFounderInteraction) {\n"
        "            res.status(403).json({ error: \"nix_founder_relay_required\" });\n"
        "            return;\n"
        "        }\n"
        "        const resolutionAuthorization = founderRelay\n"
        "            ? { resolverPolicyRestriction: null, decision: { reason: \"nix_founder_relay\" } }\n"
        "            : authorizedResolution.resolutionAuthorization;\n"
        "        const actor = getActorInfo(req);\n"
        "        const resolutionActor = founderRelay\n"
        "            ? { actorType: \"user\", actorId: founderRelay.resolverUserId, agentId: null, runId: null, agentApiKeyId: null }\n"
        "            : actor;\n"
        "        const nixFounderRelay = founderRelay ? {\n"
        "            version: 1, verified: true, interactionId: current.id, issueId: issue.id,\n"
        "            resolverUserId: founderRelay.resolverUserId, sourceMessageId: founderRelay.sourceMessageId,\n"
        "            idempotencyKey: founderRelay.idempotencyKey, originAgentId: founderRelay.originAgentId,\n"
        "            resumedAgentId: founderRelay.originAgentId, replayed: founderRelay.replayed,\n"
        "        } : null;\n"
        "        if (founderRelay?.replayed) {\n"
        "            if (current.kind === \"ask_user_questions\") {\n"
        "                validateNativeQuestionResponseInput(current, req.body);\n"
        "            }\n"
        "            const delivered = await deliverNixFounderRelayContinuation({ db,\n"
        "                deliveries: questionResponseDeliveries, interactionId: current.id,\n"
        "                companyId: issue.companyId, issueId: issue.id,\n"
        "                originAgentId: founderRelay.originAgentId });\n"
        "            if (!delivered) {\n"
        "                res.status(503).json({ error: \"nix_founder_relay_continuation_pending\" });\n"
        "                return;\n"
        "            }\n"
        "            res.json({ ...current, nixFounderRelay });\n"
        "            return;\n"
        "        }\n",
        label="JavaScript founder relay authorization path",
    )
    source = _replace_once(
        source,
        "            agentId: actor.agentId,\n"
        "            runId: actor.runId,\n"
        "            userId: actor.actorType === \"user\" ? actor.actorId : null,\n"
        "            resolverPolicyRestriction: resolutionAuthorization.resolverPolicyRestriction,\n"
        "        });\n"
        "        await logActivity(db, {\n"
        "            companyId: issue.companyId,\n"
        "            actorType: actor.actorType,\n"
        "            actorId: actor.actorId,\n"
        "            agentId: actor.agentId,\n"
        "            runId: actor.runId,\n"
        "            agentApiKeyId: actor.agentApiKeyId,\n"
        "            action: \"issue.thread_interaction_answered\",\n",
        "            agentId: resolutionActor.agentId,\n"
        "            runId: resolutionActor.runId,\n"
        "            userId: resolutionActor.actorType === \"user\" ? resolutionActor.actorId : null,\n"
        "            resolverPolicyRestriction: resolutionAuthorization.resolverPolicyRestriction,\n"
        "        }, founderRelay ? { beforeResolveInTransaction: async (tx) => {\n"
        "            const [lockedIssue] = await tx.select({\n"
        "                companyId: issueRows.companyId, assigneeAgentId: issueRows.assigneeAgentId,\n"
        "            }).from(issueRows).where(and(\n"
        "                eq(issueRows.id, issue.id), eq(issueRows.companyId, issue.companyId),\n"
        "            )).for(\"update\").limit(1);\n"
        "            if (!lockedIssue || lockedIssue.assigneeAgentId !== founderRelay.originAgentId)\n"
        "                throw forbidden(\"Founder relay origin assignment changed\");\n"
        "            if (founderRelay.reservationExists) return;\n"
        "            await tx.insert(activityLog).values({\n"
        "                companyId: issue.companyId, actorType: actor.actorType, actorId: actor.actorId,\n"
        "                agentId: actor.agentId, runId: actor.runId,\n"
        "                action: \"issue.founder_relay_reserved\", entityType: \"issue\", entityId: issue.id,\n"
        "                details: { interactionId: current.id, nixFounderRelayReservation: {\n"
        "                    version: 1, interactionId: current.id, issueId: issue.id,\n"
        "                    resolverUserId: founderRelay.resolverUserId, sourceMessageId: founderRelay.sourceMessageId,\n"
        "                    idempotencyKey: founderRelay.idempotencyKey, originAgentId: founderRelay.originAgentId,\n"
        "                    requestBodySha256: founderRelay.bodyDigest,\n"
        "                } },\n"
        "            });\n"
        "        } } : {});\n"
        "        await logActivity(db, {\n"
        "            companyId: issue.companyId,\n"
        "            actorType: resolutionActor.actorType,\n"
        "            actorId: resolutionActor.actorId,\n"
        "            agentId: resolutionActor.agentId,\n"
        "            runId: resolutionActor.runId,\n"
        "            agentApiKeyId: resolutionActor.agentApiKeyId,\n"
        "            action: \"issue.thread_interaction_answered\",\n",
        label="JavaScript founder relay resolution actor",
    )
    source = _replace_once_in_region(
        source,
        'router.post("/issues/:id/interactions/:interactionId/respond"',
        'router.post("/issues/:id/interactions/:interactionId/verdicts"',
        "                resolutionActorKind: actor.actorType,\n"
        "                requestedResolverPolicy: interaction.requestedResolverPolicy,\n",
        "                resolutionActorKind: resolutionActor.actorType,\n"
        "                ...(nixFounderRelay ? { nixFounderRelay: { ...nixFounderRelay,\n"
        "                        resumedAgentId: null, continuationStatus: \"pending\" },\n"
        "                    nixFounderRelayRequestBodySha256: founderRelay.bodyDigest } : {}),\n"
        "                requestedResolverPolicy: interaction.requestedResolverPolicy,\n",
        label="JavaScript founder relay activity receipt",
    )
    source = _replace_once(
        source,
        "        await questionResponseDeliveries.deliver(interaction.id).catch((err) => {\n"
        "            logger.warn({\n"
        "                err,\n"
        "                companyId: issue.companyId,\n"
        "                issueId: issue.id,\n"
        "                interactionId: interaction.id,\n"
        "            }, \"synchronous question response delivery failed; durable outbox will retry\");\n"
        "        });\n"
        "        res.json(interaction);\n"
        "    });\n"
        "    router.post(\"/issues/:id/interactions/:interactionId/verdicts\",",
        "        if (nixFounderRelay) {\n"
        "            const delivered = await deliverNixFounderRelayContinuation({ db,\n"
        "                deliveries: questionResponseDeliveries, interactionId: interaction.id,\n"
        "                companyId: issue.companyId, issueId: issue.id, originAgentId: founderRelay.originAgentId });\n"
        "            if (!delivered) {\n"
        "                res.status(503).json({ error: \"nix_founder_relay_continuation_pending\" });\n"
        "                return;\n"
        "            }\n"
        "        }\n"
        "        else {\n"
        "            await questionResponseDeliveries.deliver(interaction.id).catch((err) => {\n"
        "                logger.warn({ err, companyId: issue.companyId, issueId: issue.id, interactionId: interaction.id },\n"
        "                    \"synchronous question response delivery failed; durable outbox will retry\");\n"
        "            });\n"
        "        }\n"
        "        res.json(nixFounderRelay ? { ...interaction, nixFounderRelay } : interaction);\n"
        "    });\n"
        "    router.post(\"/issues/:id/interactions/:interactionId/verdicts\",",
        label="JavaScript founder relay response receipt",
    )
    return source


def patch_ssh_command_args(source: str) -> str:
    """Preserve positional arguments for the pinned SSH ``sh -c`` runner."""

    return _replace_once(
        source,
        '''      const commandScript = command === "sh" || command === "bash"
        ? (args[0] === "-c" || args[0] === "-lc") && typeof args[1] === "string"
          ? `${exportPrefix}${args[1]}`
          : `${envPrefix}exec ${[shellQuote(command), ...args.map((arg) => shellQuote(arg))].join(" ")}`
        : `${envPrefix}exec ${[shellQuote(command), ...args.map((arg) => shellQuote(arg))].join(" ")}`;''',
        '''      const commandScript = command === "sh" || command === "bash"
        ? (args[0] === "-c" || args[0] === "-lc") && typeof args[1] === "string"
          ? args.length > 2
            ? `${exportPrefix}exec ${[shellQuote(command), ...args.map((arg) => shellQuote(arg))].join(" ")}`
            : `${exportPrefix}${args[1]}`
          : `${envPrefix}exec ${[shellQuote(command), ...args.map((arg) => shellQuote(arg))].join(" ")}`
        : `${envPrefix}exec ${[shellQuote(command), ...args.map((arg) => shellQuote(arg))].join(" ")}`;''',
        label="SSH sh -c positional arguments",
    )


@dataclass(frozen=True)
class PatchSpec:
    relative_path: str
    original_sha256: str
    patched_sha256: str
    transform: Callable[[str], str]


PATCH_SPECS = (
    PatchSpec(
        "packages/adapter-utils/src/ssh.ts",
        "e7bbe4a33135be2fc937be9c88572fc561ba615956e1331e48299a35df4243f4",
        "975db449ee560a7615f87026a509f423808750e10ee8eaafca0e83de030214b6",
        patch_ssh_command_args,
    ),
    PatchSpec(
        "server/src/middleware/http-log-redaction.ts",
        "482c2eb0a6cadb611b3959a477859d8d2a4aa9aaf1ee39fbc343b40ca61b3252",
        "6734aece61cf27b69b6e106c30fdb29e4e8b982ac04acf4a93233074f37073ca",
        patch_http_log_redaction,
    ),
    PatchSpec(
        "server/dist/middleware/http-log-redaction.js",
        "fe92173ffc42bd5c96029c50e88a22586501d467621a68a42b128cef83a2d7f5",
        "14eb7351fc9f935e7930a5163550723fc4c03bc51e6f355c337591cf25809229",
        patch_http_log_redaction,
    ),
    PatchSpec(
        "server/src/routes/issues.ts",
        "d0ebe08935312cced77b16be1b5dac9638618f7852df61c7dcef8ee8edc45e0b",
        "2e43306fe58937bce0ac20d8053602dd7bcb05a18c37c8e2d8c7de907e02e909",
        patch_issues_route_ts,
    ),
    PatchSpec(
        "server/dist/routes/issues.js",
        "2eeb8cf28f9e5a577405e9fd8811fe4ab2e408cbafeda23de31d58ff966151cf",
        "abf63a24ff421b09e21cd0a4ed7e2e40bbc921a3dc723af730762946a8101f3b",
        patch_issues_route_js,
    ),
    PatchSpec(
        "server/src/services/question-response-delivery.ts",
        "b7a1d80d0f0a95f22604a89265c672459270c9f569104434ff02b49e0500d8a6",
        "ed1f60264bb341d41b7028703422144cea45e787c6ebb8b9f57baa0e05b2f403",
        patch_question_response_delivery_ts,
    ),
    PatchSpec(
        "server/dist/services/question-response-delivery.js",
        "4d92d4f8a05e1c7da5b8de009e1fb521deaa2cbd5d98f95bb187a87e145d9ad7",
        "baafd5b2a0f4653db74d3cd1effb7d06391384117e57cf31ef3fcf8abae58579",
        patch_question_response_delivery_js,
    ),
    PatchSpec(
        "server/src/services/native-runtime/native-session-executor.ts",
        "6764f835495330a93aece9f3cda9c700c52eccefd0177d92718f5e36f2feae60",
        "3b6b5ce4e04c47779d832955ddaa423a3e35d0407efaa7050f3988d3588d45c0",
        patch_native_environment,
    ),
    PatchSpec(
        "server/dist/services/native-runtime/native-session-executor.js",
        "5dc6952fcbc9bb320b6cbbe5e390aee3067837d6f90e9d37bae5406086cc95ec",
        "1a2439cbffc5bef7f448cb253d2d19845cd58abaa006015e44509cd5820b02de",
        patch_native_environment,
    ),
    PatchSpec(
        "packages/paperclip-runner/src/live/runnerd-codex-transport.ts",
        "f96149a30fe98fff575bcad7139b90474fde6483c178939facf861dcc33198ed",
        "bf2606d9a670926af7c0449bbda25aedfec4a8a11019b1bf07fcb5733f81e480",
        patch_runner_provider_environment,
    ),
    PatchSpec(
        "packages/paperclip-runner/dist/live/runnerd-codex-transport.js",
        "8de15bc9aae1bff722cb958509f0e06d1f122ce86170bcd8d589164b0724d5a4",
        "36edc8751afbddac6cce3988b14eb3767abc9f6db63159f61e01426fee4c35b0",
        patch_runner_provider_environment,
    ),
    PatchSpec(
        "server/dist/vendor/paperclip-runner/live/runnerd-codex-transport.js",
        "8de15bc9aae1bff722cb958509f0e06d1f122ce86170bcd8d589164b0724d5a4",
        "36edc8751afbddac6cce3988b14eb3767abc9f6db63159f61e01426fee4c35b0",
        patch_runner_provider_environment,
    ),
    PatchSpec(
        "server/src/services/native-runtime/paperclip-runner-tool-authority.ts",
        "cefbd145437dbeec08ff6844847c0b8cd273d356c06c0dc8c411d9337f7c9a65",
        "4dcb6276a0239d24fd5dc57adad3a2eda22acab81e179bcb433bfd5e3e06f177",
        patch_tool_authority_ts,
    ),
    PatchSpec(
        "server/dist/services/native-runtime/paperclip-runner-tool-authority.js",
        "5088550417a9412bb7ad8a819ca4e59f1867027a1900dc832d27c655736b340e",
        "3f201813577c4da6672ee0c7313f7042c3a614860b57992658f90e97eb464df4",
        patch_tool_authority_js,
    ),
    PatchSpec(
        "packages/paperclip-runner/src/drivers/opencode/opencode-server-driver.ts",
        "44fd45efa24b5c0a55f4f2a8bf23e18b5ed03b73709185226953bcd3b709eb95",
        "9b14933a6774e95bc683dc716d20c135098d5b1e4ddc553c18ebfde61e5aa1ec",
        patch_opencode_driver,
    ),
    PatchSpec(
        "packages/paperclip-runner/dist/drivers/opencode/opencode-server-driver.js",
        "3e17333514ecc354b277f75dc1f43a84c7563a67f4f69bf5335f16d9d1860a38",
        "0220547cec722ad1197a769935f8180fdcf7939e5df7b373d7b7664e2b9775cb",
        patch_opencode_driver,
    ),
    PatchSpec(
        "server/dist/vendor/paperclip-runner/drivers/opencode/opencode-server-driver.js",
        "3e17333514ecc354b277f75dc1f43a84c7563a67f4f69bf5335f16d9d1860a38",
        "0220547cec722ad1197a769935f8180fdcf7939e5df7b373d7b7664e2b9775cb",
        patch_opencode_driver,
    ),
    PatchSpec(
        "packages/paperclip-runner/dist/cli/opencode-app-server-proxy.cjs",
        "515fa5d26c44c6d0a1df09497297405e726dd068917f525869aac72ea7a1ce0e",
        "9c20ec6d59e99682b8a2122cd5f699ff5e013d4c03c71c7388f6d78b74b8793d",
        patch_opencode_proxy_bundle,
    ),
    PatchSpec(
        "packages/paperclip-runner/dist/cli/opencode-app-server-proxy.js",
        "de49baf75b3bbeae46312cb2e47100506c5e9bf8c2a6a941e46c1358e3e6847e",
        "1f21a0d2564ed8c5d0838f3acf03eb4d738a014c7fe0d06bb496f92ba4541a01",
        patch_opencode_proxy_bundle,
    ),
    PatchSpec(
        "server/dist/vendor/paperclip-runner/cli/opencode-app-server-proxy.cjs",
        "515fa5d26c44c6d0a1df09497297405e726dd068917f525869aac72ea7a1ce0e",
        "9c20ec6d59e99682b8a2122cd5f699ff5e013d4c03c71c7388f6d78b74b8793d",
        patch_opencode_proxy_bundle,
    ),
    PatchSpec(
        "server/dist/vendor/paperclip-runner/cli/opencode-app-server-proxy.js",
        "de49baf75b3bbeae46312cb2e47100506c5e9bf8c2a6a941e46c1358e3e6847e",
        "1f21a0d2564ed8c5d0838f3acf03eb4d738a014c7fe0d06bb496f92ba4541a01",
        patch_opencode_proxy_bundle,
    ),
)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write(path: Path, data: bytes, mode: int) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def patch_set_id(specs: tuple[PatchSpec, ...] = PATCH_SPECS) -> str:
    payload = "\n".join(
        [PINNED_PAPERCLIP_REVISION]
        + [f"{spec.relative_path}:{spec.patched_sha256}" for spec in specs]
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def verify_patch(root: Path, specs: tuple[PatchSpec, ...] = PATCH_SPECS) -> None:
    for spec in specs:
        path = root / spec.relative_path
        if not path.is_file() or _digest(path.read_bytes()) != spec.patched_sha256:
            raise RuntimeError(
                f"Paperclip specialist patch verification failed at {spec.relative_path}"
            )


def apply_patch(root: Path, specs: tuple[PatchSpec, ...] = PATCH_SPECS) -> None:
    pending: list[tuple[Path, bytes, int]] = []
    for spec in specs:
        path = root / spec.relative_path
        original = path.read_bytes()
        current_digest = _digest(original)
        if current_digest == spec.patched_sha256:
            continue
        if current_digest != spec.original_sha256:
            raise RuntimeError(
                f"Paperclip specialist patch refused: unsupported source at {spec.relative_path}"
            )
        patched = spec.transform(original.decode("utf-8")).encode("utf-8")
        if _digest(patched) != spec.patched_sha256:
            raise RuntimeError(
                f"Paperclip specialist patch refused: output mismatch at {spec.relative_path}"
            )
        pending.append((path, patched, path.stat().st_mode & 0o777))
    for path, data, mode in pending:
        _atomic_write(path, data, mode)
    verify_patch(root, specs)


def _canonical_json(value: object) -> str:
    if isinstance(value, list):
        return "[" + ",".join(_canonical_json(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(
            json.dumps(key, separators=(",", ":")) + ":" + _canonical_json(value[key])
            for key in sorted(value)
        ) + "}"
    return json.dumps(value, separators=(",", ":"))


def _sha256_prefixed(path: Path) -> str:
    return "sha256:" + _digest(path.read_bytes())


def _sha256_tree(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.is_dir():
        raise RuntimeError("Paperclip specialist provider pack verification failed: dist missing")

    def visit(directory: Path, prefix: str = "") -> None:
        for entry in sorted(directory.iterdir(), key=lambda path: path.name):
            relative = f"{prefix}/{entry.name}" if prefix else entry.name
            if entry.is_symlink():
                digest.update(f"symlink\0{relative}\0{os.readlink(entry)}\n".encode())
            elif entry.is_dir():
                digest.update(f"directory\0{relative}\n".encode())
                visit(entry, relative)
            elif entry.is_file():
                digest.update(
                    f"file\0{relative}\0{_sha256_prefixed(entry)}\n".encode()
                )
            else:
                raise RuntimeError(
                    "Paperclip specialist provider pack verification failed: unsupported entry"
                )

    visit(root)
    return "sha256:" + digest.hexdigest()


def _read_manifest(provider_pack: Path) -> dict[str, object]:
    try:
        data = json.loads((provider_pack / "provider-pack.json").read_text())
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            "Paperclip specialist provider pack verification failed: manifest unreadable"
        ) from exc
    if not isinstance(data, dict):
        raise RuntimeError(
            "Paperclip specialist provider pack verification failed: manifest invalid"
        )
    return data


def verify_provider_pack_payload(provider_pack: Path) -> str:
    manifest = _read_manifest(provider_pack)
    payload = manifest.get("payload")
    if manifest.get("schema") != "paperclip-runner/remote-provider-pack/v1" or not isinstance(payload, dict):
        raise RuntimeError(
            "Paperclip specialist provider pack verification failed: manifest schema mismatch"
        )
    expected_digest = "sha256:" + hashlib.sha256(
        _canonical_json(payload).encode()
    ).hexdigest()
    if manifest.get("digest") != expected_digest:
        raise RuntimeError(
            "Paperclip specialist provider pack verification failed: manifest digest mismatch"
        )
    if payload.get("runnerSourceRevision") != PINNED_PAPERCLIP_REVISION:
        raise RuntimeError(
            "Paperclip specialist provider pack verification failed: source revision mismatch"
        )
    if payload.get("distDigest") != _sha256_tree(provider_pack / "dist"):
        raise RuntimeError(
            "Paperclip specialist provider pack verification failed: dist digest mismatch"
        )
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict):
        raise RuntimeError(
            "Paperclip specialist provider pack verification failed: artifacts missing"
        )
    for artifact in artifacts.values():
        if not isinstance(artifact, dict):
            raise RuntimeError(
                "Paperclip specialist provider pack verification failed: artifact invalid"
            )
        path = artifact.get("path")
        expected = artifact.get("sha256")
        if not isinstance(path, str) or path.startswith("/") or ".." in Path(path).parts:
            raise RuntimeError(
                "Paperclip specialist provider pack verification failed: artifact path invalid"
            )
        candidate = provider_pack / path
        if not candidate.is_file() or not isinstance(expected, str) or _sha256_prefixed(candidate) != expected:
            raise RuntimeError(
                "Paperclip specialist provider pack verification failed: artifact digest mismatch"
            )
    driver = provider_pack / "dist/drivers/opencode/opencode-server-driver.js"
    expected_driver = next(
        spec.patched_sha256 for spec in PATCH_SPECS
        if spec.relative_path.endswith("dist/drivers/opencode/opencode-server-driver.js")
    )
    if not driver.is_file() or _digest(driver.read_bytes()) != expected_driver:
        raise RuntimeError(
            "Paperclip specialist provider pack verification failed: OpenCode driver mismatch"
        )
    proxy = provider_pack / "dist/cli/opencode-app-server-proxy.cjs"
    expected_proxy = next(
        spec.patched_sha256 for spec in PATCH_SPECS
        if spec.relative_path == "packages/paperclip-runner/dist/cli/opencode-app-server-proxy.cjs"
    )
    if not proxy.is_file() or _digest(proxy.read_bytes()) != expected_proxy:
        raise RuntimeError(
            "Paperclip specialist provider pack verification failed: OpenCode proxy mismatch"
        )
    return expected_digest


def marker_matches(provider_pack: Path) -> bool:
    try:
        marker = json.loads((provider_pack / PROVIDER_PACK_MARKER).read_text())
    except (OSError, ValueError):
        return False
    return marker == {
        "schema": "nix/paperclip-specialist-patch/v1",
        "patchSetId": patch_set_id(),
    }


def stamp_provider_pack(provider_pack: Path) -> None:
    verify_provider_pack_payload(provider_pack)
    marker = {
        "schema": "nix/paperclip-specialist-patch/v1",
        "patchSetId": patch_set_id(),
    }
    _atomic_write(
        provider_pack / PROVIDER_PACK_MARKER,
        (json.dumps(marker, sort_keys=True, separators=(",", ":")) + "\n").encode(),
        0o600,
    )


def verify_provider_pack(provider_pack: Path) -> None:
    if not marker_matches(provider_pack):
        raise RuntimeError(
            "Paperclip specialist provider pack verification failed: patch marker mismatch"
        )
    verify_provider_pack_payload(provider_pack)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/app"))
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--provider-pack", type=Path)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--marker-matches", action="store_true")
    actions.add_argument("--stamp-provider-pack", action="store_true")
    actions.add_argument("--verify-provider-pack", action="store_true")
    args = parser.parse_args()

    if args.marker_matches or args.stamp_provider_pack or args.verify_provider_pack:
        if args.provider_pack is None:
            parser.error("--provider-pack is required for provider-pack actions")
        if args.marker_matches:
            return 0 if marker_matches(args.provider_pack) else 1
        if args.stamp_provider_pack:
            stamp_provider_pack(args.provider_pack)
        else:
            verify_provider_pack(args.provider_pack)
        return 0

    if args.verify:
        verify_patch(args.root)
    else:
        apply_patch(args.root)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        raise SystemExit(str(exc))
