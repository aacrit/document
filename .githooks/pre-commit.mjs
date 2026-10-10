#!/usr/bin/env node
// Blocks a commit that stages a credential-shaped path, a secret-shaped
// added line, an over-size file, or an over-size commit. Wired in via
// core.hooksPath=.githooks (set at Spark time) and the tiny `pre-commit` shim.

import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { isBlockedCredentialPath, findSecretMatches } from "../scripts/secret-patterns.mjs";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const MAX_FILE_BYTES = 5 * 1024 * 1024;
const MAX_COMMIT_BYTES = 20 * 1024 * 1024;

function git(args) {
  return execFileSync("git", args, { cwd: repoRoot, encoding: "utf8" });
}

function stagedFiles() {
  return git(["diff", "--cached", "--name-only", "--diff-filter=ACM"])
    .split("\n")
    .filter(Boolean);
}

function blobSize(file) {
  const lsFiles = git(["ls-files", "-s", "--", file]).trim();
  if (!lsFiles) return 0;
  const sha = lsFiles.split(/\s+/)[1];
  return Number(git(["cat-file", "-s", sha]).trim());
}

function addedLines(file) {
  let diff;
  try {
    diff = git(["diff", "--cached", "-U0", "--", file]);
  } catch {
    return [];
  }
  return diff
    .split("\n")
    .filter((line) => line.startsWith("+") && !line.startsWith("+++"))
    .map((line) => line.slice(1));
}

export function checkStaged(files, { getBlobSize = blobSize, getAddedLines = addedLines } = {}) {
  const violations = [];
  let totalBytes = 0;

  for (const file of files) {
    if (isBlockedCredentialPath(file)) {
      violations.push(`${file}: credential-shaped path is never tracked`);
      continue;
    }

    const size = getBlobSize(file);
    totalBytes += size;
    if (size > MAX_FILE_BYTES) {
      violations.push(`${file}: ${(size / (1024 * 1024)).toFixed(2)} MB exceeds the 5 MB per-file limit`);
    }

    for (const line of getAddedLines(file)) {
      const hits = findSecretMatches(line);
      if (hits.length > 0) {
        violations.push(`${file}: added line looks like a secret (${hits.join(", ")}) - rotate it, never re-commit it`);
      }
    }
  }

  if (totalBytes > MAX_COMMIT_BYTES) {
    violations.push(`staged changes total ${(totalBytes / (1024 * 1024)).toFixed(2)} MB, over the 20 MB per-commit limit`);
  }

  return violations;
}

function main() {
  const files = stagedFiles();
  const violations = checkStaged(files);
  if (violations.length > 0) {
    console.error("pre-commit: blocked\n" + violations.map((v) => `  - ${v}`).join("\n"));
    console.error("\nIf a secret was exposed, rotate it. Never replace it in place.");
    process.exit(1);
  }
}

main();
