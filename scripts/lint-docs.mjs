#!/usr/bin/env node
// CLAUDE.md hygiene (rule 7) and charter parity: the number of top-level HTML
// pages under web/ must not exceed the number of charter rows, and the
// workflow count must not exceed the count CHARTER.md declares.

import { readFileSync, readdirSync, existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const MAX_CLAUDE_MD_LINES = 150;
const CHANGELOG_WORDS = ["no longer", "RETIRED", "STALE", "OBSOLETE"];
const BACKTICK_PATH = /`([^`\s]+\/[^`\s]*|[^`\s]+\.[A-Za-z0-9]+)`/g;

export function checkLineCount(text, max = MAX_CLAUDE_MD_LINES) {
  const lines = text.split("\n").length;
  return lines <= max ? null : `CLAUDE.md has ${lines} lines, over the ${max}-line cap`;
}

export function checkChangelogWords(text) {
  const violations = [];
  for (const word of CHANGELOG_WORDS) {
    const re = new RegExp(word, word === word.toUpperCase() ? "g" : "gi");
    if (re.test(text)) violations.push(`CLAUDE.md uses changelog language: "${word}"`);
  }
  return violations;
}

export function extractBacktickPaths(text) {
  const paths = new Set();
  for (const match of text.matchAll(BACKTICK_PATH)) {
    const candidate = match[1];
    // Skip things that are clearly not paths: URLs, bare words, code identifiers.
    if (/^https?:\/\//.test(candidate)) continue;
    if (!candidate.includes("/") && !candidate.includes(".")) continue;
    if (candidate.includes("<") || candidate.includes(">")) continue;
    paths.add(candidate);
  }
  return [...paths];
}

export function checkPathsExist(paths, root, existsFn = existsSync) {
  const violations = [];
  for (const p of paths) {
    const clean = p.replace(/^\.\//, "").replace(/^\//, "");
    if (!existsFn(path.join(root, clean))) {
      violations.push(`CLAUDE.md references \`${p}\`, which does not exist`);
    }
  }
  return violations;
}

function countTopLevelHtmlPages(webDir) {
  if (!existsSync(webDir)) return 0;
  return readdirSync(webDir).filter((f) => f.endsWith(".html")).length;
}

function countWorkflows(workflowsDir) {
  if (!existsSync(workflowsDir)) return 0;
  return readdirSync(workflowsDir).filter((f) => f.endsWith(".yml") || f.endsWith(".yaml")).length;
}

function declaredCounts(charterText) {
  const chartRows = charterText
    .split("\n")
    .filter((l) => l.trim().startsWith("|") && !l.includes("---") && !/\|\s*Surface\s*\|/i.test(l)).length;
  const workflowMatch = charterText.match(/Workflows:\s*(\d+)/);
  return {
    chartRows,
    declaredWorkflows: workflowMatch ? Number(workflowMatch[1]) : null,
  };
}

function main() {
  const violations = [];

  const claudeMdPath = path.join(repoRoot, "CLAUDE.md");
  const claudeMd = readFileSync(claudeMdPath, "utf8");

  const lineViolation = checkLineCount(claudeMd);
  if (lineViolation) violations.push(lineViolation);
  violations.push(...checkChangelogWords(claudeMd));

  const paths = extractBacktickPaths(claudeMd);
  violations.push(...checkPathsExist(paths, repoRoot));

  const charterPath = path.join(repoRoot, "CHARTER.md");
  if (existsSync(charterPath)) {
    const charterText = readFileSync(charterPath, "utf8");
    const { chartRows, declaredWorkflows } = declaredCounts(charterText);
    const htmlPages = countTopLevelHtmlPages(path.join(repoRoot, "web"));
    const workflows = countWorkflows(path.join(repoRoot, ".github", "workflows"));

    if (htmlPages > chartRows) {
      violations.push(`web/ has ${htmlPages} top-level HTML page(s) but CHARTER.md declares only ${chartRows} row(s)`);
    }
    if (declaredWorkflows === null) {
      violations.push('CHARTER.md is missing a "Workflows: <n>" line');
    } else if (workflows > declaredWorkflows) {
      violations.push(`.github/workflows/ has ${workflows} workflow(s) but CHARTER.md declares ${declaredWorkflows}`);
    }
  } else {
    violations.push("CHARTER.md is missing");
  }

  if (violations.length > 0) {
    console.error("lint-docs: violations found\n" + violations.map((v) => `  - ${v}`).join("\n"));
    process.exit(1);
  }
  console.log("lint-docs: CLAUDE.md and charter parity OK");
}

main();
