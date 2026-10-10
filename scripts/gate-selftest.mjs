#!/usr/bin/env node
// A gate can never pass with 0 tests. Reads vitest's JSON reporter output
// (written by `npm test` to .vitest-report.json) and fails if it is missing
// or reports zero executed tests.

import { readFileSync, existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const REPORT_PATH = path.join(repoRoot, ".vitest-report.json");

export function countExecutedTests(report) {
  if (typeof report?.numTotalTests === "number") return report.numTotalTests;
  // Fall back to summing per-file assertionResults, in case the reporter
  // shape changes across vitest versions.
  if (Array.isArray(report?.testResults)) {
    return report.testResults.reduce((sum, f) => sum + (f.assertionResults?.length ?? 0), 0);
  }
  return 0;
}

function main() {
  if (!existsSync(REPORT_PATH)) {
    console.error(`gate-selftest: ${REPORT_PATH} not found - run \`npm test\` before the gate`);
    process.exit(1);
  }
  const report = JSON.parse(readFileSync(REPORT_PATH, "utf8"));
  const total = countExecutedTests(report);
  if (total <= 0) {
    console.error("gate-selftest: vitest reported 0 executed tests - a gate cannot pass on 0 tests");
    process.exit(1);
  }
  console.log(`gate-selftest: vitest executed ${total} test(s)`);
}

main();
