#!/usr/bin/env node
// Fails on any tracked file over 5 MB, and on generated/committed paths that
// should never be in git (rule 8 in the root Agentique CLAUDE.md).

import { execFileSync } from "node:child_process";
import { statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const MAX_FILE_BYTES = 5 * 1024 * 1024;

const FORBIDDEN_PATTERNS = [
  /^dist\//,
  /^\.wrangler\//,
  /(^|\/)node_modules\//,
  /\.tsbuildinfo$/,
  /(^|\/)cloudflare-env\.d\.ts$/,
  /\.(png|jpe?g|gif|webp|mp4|mov|mp3|wav|zip|sqlite3?|db)$/i,
];

export function checkFiles(files, statFn = statSync) {
  const violations = [];
  for (const file of files) {
    if (!file) continue;
    for (const pattern of FORBIDDEN_PATTERNS) {
      if (pattern.test(file)) {
        violations.push(`${file}: matches forbidden generated/binary path pattern ${pattern}`);
      }
    }
    try {
      const size = statFn(file).size;
      if (size > MAX_FILE_BYTES) {
        violations.push(`${file}: ${(size / (1024 * 1024)).toFixed(2)} MB exceeds the 5 MB limit`);
      }
    } catch {
      // File tracked but missing on disk (e.g. deleted-but-staged); nothing to size-check.
    }
  }
  return violations;
}

function listTrackedFiles(repoRoot) {
  const out = execFileSync("git", ["ls-files"], { cwd: repoRoot, encoding: "utf8" });
  return out.split("\n").filter(Boolean);
}

function main() {
  const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  const files = listTrackedFiles(repoRoot).map((f) => f.replace(/\\/g, "/"));
  const violations = checkFiles(files, (f) => statSync(path.join(repoRoot, f)));

  if (violations.length > 0) {
    console.error("lint-size: violations found\n" + violations.map((v) => `  - ${v}`).join("\n"));
    process.exit(1);
  }
  console.log(`lint-size: ${files.length} tracked files OK`);
}

main();
