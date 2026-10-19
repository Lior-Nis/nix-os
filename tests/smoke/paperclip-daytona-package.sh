#!/usr/bin/env bash
set -euo pipefail

package='@paperclipai/plugin-daytona@2026.916.1'
expected_integrity='sha512-rJOMUxFCEpXgaZ5gaD9OdSVNmg+5h9Gm77M/0mTD8MVVFgEw7yltrB7mzT0Ff09qb6lGkZgpVWkG7Glot/+g5A=='
test_dir=$(mktemp -d /tmp/nix-daytona-package.XXXXXX)
trap 'rm -rf "$test_dir"' EXIT

pack_json=$(npm pack --ignore-scripts --json --pack-destination "$test_dir" "$package")
filename=$(jq -er 'if length == 1 then .[0].filename else error("unexpected pack result") end' <<<"$pack_json")
integrity=$(jq -er 'if length == 1 then .[0].integrity else error("unexpected pack result") end' <<<"$pack_json")
[[ "$integrity" == "$expected_integrity" ]]

tar -xzf "$test_dir/$filename" -C "$test_dir"
node --input-type=module - "$test_dir/package" <<'JS'
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const root = process.argv[2];
const pkg = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8"));
if (pkg.name !== "@paperclipai/plugin-daytona" || pkg.version !== "2026.916.1") throw new Error("package identity drift");
if (pkg.dependencies?.["@daytonaio/sdk"] !== "0.203.0") throw new Error("Daytona SDK pin drift");
if (pkg.dependencies?.["@paperclipai/plugin-sdk"] !== "2026.916.1") throw new Error("plugin SDK pin drift");
if (pkg.paperclipPlugin?.manifest !== "./dist/manifest.js" || pkg.paperclipPlugin?.worker !== "./dist/worker.js") throw new Error("plugin entrypoint drift");
const manifest = (await import(pathToFileURL(path.join(root, "dist/manifest.js")))).default;
const driver = manifest.environmentDrivers?.find((candidate) => candidate.driverKey === "daytona");
if (manifest.id !== "paperclip.daytona-sandbox-provider" || manifest.version !== "0.1.7") throw new Error("manifest identity drift");
if (JSON.stringify(manifest.capabilities) !== JSON.stringify(["environment.drivers.register"])) throw new Error("manifest capability drift");
if (driver?.kind !== "sandbox_provider" || driver?.configSchema?.properties?.apiKey?.format !== "secret-ref") throw new Error("Daytona driver contract drift");
if (driver?.configSchema?.properties?.reuseLease?.default !== false) throw new Error("lease default drift");
if (!driver?.configSchema?.properties?.runnerLifecycleMode?.enum?.includes("per_turn")) throw new Error("runner lifecycle contract drift");
const source = fs.readFileSync(path.join(root, "dist/plugin.js"), "utf8");
for (const marker of [
  "sandbox.getPreviewLink(params.port)",
  'url.protocol = "wss:"',
  'name: "X-Daytona-Preview-Token"',
  "await sandbox.delete(toTimeoutSeconds(config.timeoutMs), true)",
]) {
  if (!source.includes(marker)) throw new Error(`reviewed Daytona source contract drift: ${marker}`);
}
JS

printf 'Pinned Paperclip Daytona package integrity and manifest tests passed.\n'
