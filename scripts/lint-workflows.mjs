#!/usr/bin/env node
// Fails on advisory-gate patterns in CI workflows (rule 1) and on skipped
// tests without a short-lived, tracked expiry (rule 14).

import { readFileSync, readdirSync, existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const FORBIDDEN_WORKFLOW_PATTERNS = [/continue-on-error:\s*true/, /\|\|\s*true\b/, /\|\|\s*echo\b/];

const SKIP_PATTERN = /\b(it\.skip|test\.skip|describe\.skip|xit)\s*\(/;
const EXPIRY_PATTERN = /\/\/\s*expires\s+(\d{4}-\d{2}-\d{2})\s+issue\s+#\d+/;
const MAX_EXPIRY_DAYS = 14;

export function checkWorkflowText(filename, text) {
  const violations = [];
  const lines = text.split("\n");
  lines.forEach((line, i) => {
    for (const pattern of FORBIDDEN_WORKFLOW_PATTERNS) {
      if (pattern.test(line)) {
        violations.push(`${filename}:${i + 1}: forbidden pattern ${pattern} - "${line.trim()}"`);
      }
    }
  });
  return violations;
}

export function checkGateJobPresent(text) {
  return /^\s*jobs:\s*$/m.test(text) && /^\s{2}gate:\s*$/m.test(text);
}

export function checkSkippedTestLine(line, now = new Date()) {
  if (!SKIP_PATTERN.test(line)) return null;
  const match = line.match(EXPIRY_PATTERN);
  if (!match) {
    return `skipped test with no "// expires YYYY-MM-DD issue #N" annotation: "${line.trim()}"`;
  }
  const expiry = new Date(`${match[1]}T00:00:00Z`);
  if (Number.isNaN(expiry.getTime())) {
    return `skipped test has an unparseable expiry date: "${line.trim()}"`;
  }
  const daysUntil = (expiry.getTime() - now.getTime()) / (24 * 60 * 60 * 1000);
  if (daysUntil > MAX_EXPIRY_DAYS) {
    return `skipped test expiry is more than ${MAX_EXPIRY_DAYS} days out: "${line.trim()}"`;
  }
  if (daysUntil < 0) {
    return `skipped test expiry has passed, remove the skip or renew it: "${line.trim()}"`;
  }
  return null;
}

function listWorkflowFiles() {
  const dir = path.join(repoRoot, ".github", "workflows");
  if (!existsSync(dir)) return [];
  return readdirSync(dir)
    .filter((f) => f.endsWith(".yml") || f.endsWith(".yaml"))
    .map((f) => path.join(dir, f));
}

function listTestFiles() {
  const dir = path.join(repoRoot, "tests");
  if (!existsSync(dir)) return [];
  return readdirSync(dir)
    .filter((f) => f.endsWith(".test.ts") || f.endsWith(".test.mjs") || f.endsWith(".test.js"))
    .map((f) => path.join(dir, f));
}

function main() {
  const violations = [];

  const workflowFiles = listWorkflowFiles();
  let sawGateJob = false;
  for (const file of workflowFiles) {
    const text = readFileSync(file, "utf8");
    violations.push(...checkWorkflowText(path.relative(repoRoot, file), text));
    if (path.basename(file) === "gate.yml" && checkGateJobPresent(text)) {
      sawGateJob = true;
    }
  }
  const gateFile = workflowFiles.find((f) => path.basename(f) === "gate.yml");
  if (!gateFile) {
    violations.push(".github/workflows/gate.yml is missing");
  } else if (!sawGateJob) {
    violations.push("gate.yml has no job named `gate`");
  }

  for (const file of listTestFiles()) {
    const text = readFileSync(file, "utf8");
    text.split("\n").forEach((line, i) => {
      const problem = checkSkippedTestLine(line);
      if (problem) violations.push(`${path.relative(repoRoot, file)}:${i + 1}: ${problem}`);
    });
  }

  if (violations.length > 0) {
    console.error("lint-workflows: violations found\n" + violations.map((v) => `  - ${v}`).join("\n"));
    process.exit(1);
  }
  console.log(`lint-workflows: ${workflowFiles.length} workflow(s) and test files OK`);
}

main();
