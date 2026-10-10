#!/usr/bin/env node
// Runs every gate step in order and stops at the first failure. This is the
// only thing CI (`gate.yml`) and the /ship skill's verifier run.

import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { runBin } from "./lib/run-bin.mjs";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function runNode(relativeScript) {
  return spawnSync(process.execPath, [path.join(repoRoot, relativeScript)], {
    cwd: repoRoot,
    stdio: "inherit",
    shell: false,
  });
}

const STEPS = [
  { label: "typecheck (web)", run: () => runBin("typescript", "tsc", ["-p", "web/tsconfig.json", "--noEmit"], { cwd: repoRoot }) },
  { label: "typecheck (worker)", run: () => runBin("typescript", "tsc", ["-p", "worker/tsconfig.json", "--noEmit"], { cwd: repoRoot }) },
  // The build is a gate step: it injects the CSP and fails on any page that
  // breaks it, and writes dist/_headers (R-33).
  { label: "build", run: () => runNode("scripts/build.mjs") },
  {
    label: "test",
    run: () =>
      runBin("vitest", "vitest", ["run", "--reporter=default", "--reporter=json", "--outputFile=.vitest-report.json"], {
        cwd: repoRoot,
      }),
  },
  { label: "lint-size", run: () => runNode("scripts/lint-size.mjs") },
  { label: "lint-workflows", run: () => runNode("scripts/lint-workflows.mjs") },
  { label: "lint-design", run: () => runNode("scripts/lint-design.mjs") },
  { label: "lint-docs", run: () => runNode("scripts/lint-docs.mjs") },
  { label: "lint-events", run: () => runNode("scripts/lint-events.mjs") },
  { label: "gate-selftest", run: () => runNode("scripts/gate-selftest.mjs") },
];

for (const step of STEPS) {
  console.log(`\n=== gate: ${step.label} ===`);
  const result = step.run();
  if (result.error) {
    console.error(`gate: failed to run "${step.label}": ${result.error.message}`);
    process.exit(1);
  }
  if (result.status !== 0) {
    console.error(`\ngate: FAILED at "${step.label}" (exit ${result.status})`);
    process.exit(result.status ?? 1);
  }
}

console.log("\ngate: all steps passed");
