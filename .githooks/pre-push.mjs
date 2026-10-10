#!/usr/bin/env node
// Scans only the commits about to be pushed for secret-shaped lines. Reads
// the standard pre-push stdin protocol: "<local ref> <local sha> <remote
// ref> <remote sha>" per line.

import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { scanPatchText } from "../scripts/secret-patterns.mjs";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const ZERO_SHA = "0000000000000000000000000000000000000000";

function readStdin() {
  try {
    return readFileSync(0, "utf8");
  } catch {
    return "";
  }
}

function git(args) {
  return execFileSync("git", args, { cwd: repoRoot, encoding: "utf8", maxBuffer: 1024 * 1024 * 256 });
}

export function parsePrePushLines(input) {
  return input
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => {
      const [localRef, localSha, remoteRef, remoteSha] = l.split(/\s+/);
      return { localRef, localSha, remoteRef, remoteSha };
    });
}

function main() {
  const lines = parsePrePushLines(readStdin());
  const violations = [];

  for (const { localSha, remoteSha } of lines) {
    if (!localSha || localSha === ZERO_SHA) continue; // branch deletion, nothing to scan

    const range = !remoteSha || remoteSha === ZERO_SHA ? localSha : `${remoteSha}..${localSha}`;
    let text;
    try {
      text = git(["log", "-p", range]);
    } catch {
      continue; // e.g. remoteSha not known locally; scan-history covers full history separately
    }
    violations.push(...scanPatchText(text));
  }

  if (violations.length > 0) {
    console.error("pre-push: blocked, possible secret(s) in commits being pushed\n" + violations.map((v) => `  - ${v}`).join("\n"));
    console.error("\nIf any of these is real, rotate it before pushing. Never force-push over it as a fix.");
    process.exit(1);
  }
}

main();
