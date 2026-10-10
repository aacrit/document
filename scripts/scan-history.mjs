#!/usr/bin/env node
// `npm run scan-history`: scans the full `git log -p` for secret-shaped
// lines that ever entered history, even if later removed (removal is not
// rotation - see the root Agentique CLAUDE.md rule 3).

import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { scanPatchText } from "./secret-patterns.mjs";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function main() {
  let text;
  try {
    text = execFileSync("git", ["log", "-p", "--all"], {
      cwd: repoRoot,
      encoding: "utf8",
      maxBuffer: 1024 * 1024 * 512,
    });
  } catch (err) {
    console.error(`scan-history: could not read git log (${err.message})`);
    process.exit(1);
  }

  const violations = scanPatchText(text);
  if (violations.length > 0) {
    console.error("scan-history: possible secrets found in history\n" + violations.map((v) => `  - ${v}`).join("\n"));
    console.error("\nIf any of these is real, rotate it now. History rewriting does not undo exposure.");
    process.exit(1);
  }
  console.log("scan-history: no secret-shaped lines found in git history");
}

main();
