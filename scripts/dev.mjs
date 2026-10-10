#!/usr/bin/env node
// Runs the Vite dev server and `wrangler dev` side by side, cross-platform,
// without adding a `concurrently`-style dependency. Ctrl-C stops both.

import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { resolveBinPath } from "./lib/run-bin.mjs";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const webDir = path.join(repoRoot, "web");

const children = [
  spawn(process.execPath, [resolveBinPath("vite", "vite")], { cwd: webDir, stdio: "inherit", shell: false }),
  spawn(process.execPath, [resolveBinPath("wrangler", "wrangler"), "dev"], { cwd: repoRoot, stdio: "inherit", shell: false }),
];

let shuttingDown = false;
function shutdown(code) {
  if (shuttingDown) return;
  shuttingDown = true;
  for (const child of children) {
    if (!child.killed) child.kill();
  }
  process.exitCode = code ?? 0;
}

for (const child of children) {
  child.on("exit", (code) => shutdown(code ?? 0));
  child.on("error", (err) => {
    console.error(err);
    shutdown(1);
  });
}

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));
