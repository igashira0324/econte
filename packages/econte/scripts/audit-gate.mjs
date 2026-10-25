#!/usr/bin/env node
// Gate for `npm audit --omit=dev --json` output: fail on any high or critical
// advisory against a runtime dependency, except those listed in ACCEPTED.
// Each accepted advisory names its mitigation and the work that removes it
// (see SECURITY.md and .oss-scanner/findings.json).
//
// Usage: npm audit --omit=dev --json > npm-audit.json || true
//        node scripts/audit-gate.mjs npm-audit.json

import { readFileSync } from "node:fs";

const ACCEPTED = new Map([
  [
    "GHSA-mrhx-c7xc-m3w5",
    "zod < 4.6.6 exhausts memory on oversized collections; validateStoryboard() checks the " +
      "array bounds before zod parses anything (ECO-0007). Removed by the zod 4 migration.",
  ],
]);

const reportPath = process.argv[2];
if (!reportPath) {
  console.error("usage: node scripts/audit-gate.mjs <npm-audit.json>");
  process.exit(2);
}

// Tolerate a UTF-8 BOM (Windows PowerShell 5.1's Out-File writes one).
const text = readFileSync(reportPath, "utf-8");
const report = JSON.parse(text.charCodeAt(0) === 0xfeff ? text.slice(1) : text);
if (report.error) {
  console.error(`npm audit failed: ${report.error.summary ?? JSON.stringify(report.error)}`);
  process.exit(1);
}

const blocking = [];
for (const [name, vulnerability] of Object.entries(report.vulnerabilities ?? {})) {
  for (const via of vulnerability.via) {
    if (typeof via !== "object" || !["high", "critical"].includes(via.severity)) continue;
    const id = String(via.url ?? "").split("/").pop();
    if (ACCEPTED.has(id)) {
      console.log(`accepted ${id} (${name}): ${ACCEPTED.get(id)}`);
    } else {
      blocking.push(`${via.severity} ${id} (${name}): ${via.title}`);
    }
  }
}

if (blocking.length > 0) {
  console.error(`${blocking.length} blocking advisory(ies):`);
  for (const line of blocking) console.error(`  ${line}`);
  process.exit(1);
}
console.log("npm audit gate: no blocking high or critical runtime advisories");
