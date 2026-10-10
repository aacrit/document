#!/usr/bin/env node
// Enforces Ink & Momentum's token discipline: design/tokens.css is the only
// file allowed to define a color literal, and UI copy never uses an em dash.

import { readFileSync, existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { walk } from "./lib/walk.mjs";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const TOKENS_FILE = path.join("design", "tokens.css").replace(/\\/g, "/");

const HEX_COLOR = /#(?:[0-9a-fA-F]{3,4}){1,2}\b/;
const FUNC_COLOR = /\b(?:rgb|rgba|hsl|hsla)\(/;
const EM_DASH = /—/;

const SCAN_DIRS = ["web", "worker", "design"];
const SCAN_EXTENSIONS = [".css", ".ts", ".tsx", ".html"];
const SKIP_DIR_NAMES = new Set(["node_modules", "dist", ".wrangler"]);

export function checkColorLine(relPath, line) {
  if (relPath === TOKENS_FILE) return null;
  if (HEX_COLOR.test(line) || FUNC_COLOR.test(line)) {
    return `${relPath}: color literal outside design/tokens.css - "${line.trim()}"`;
  }
  return null;
}

export function checkEmDashLine(relPath, line) {
  const isUiCopyFile = relPath.endsWith(".html") || relPath.startsWith("web/src/");
  if (!isUiCopyFile) return null;
  if (EM_DASH.test(line)) {
    return `${relPath}: em dash in UI copy - "${line.trim()}"`;
  }
  return null;
}

function main() {
  const violations = [];

  for (const dir of SCAN_DIRS) {
    const abs = path.join(repoRoot, dir);
    if (!existsSync(abs)) continue;
    for (const file of walk(abs, SKIP_DIR_NAMES)) {
      if (!SCAN_EXTENSIONS.includes(path.extname(file))) continue;
      const relPath = path.relative(repoRoot, file).replace(/\\/g, "/");
      const text = readFileSync(file, "utf8");
      text.split("\n").forEach((line, i) => {
        const colorProblem = checkColorLine(relPath, line);
        if (colorProblem) violations.push(`${colorProblem} (line ${i + 1})`);
        const dashProblem = checkEmDashLine(relPath, line);
        if (dashProblem) violations.push(`${dashProblem} (line ${i + 1})`);
      });
    }
  }

  if (violations.length > 0) {
    console.error("lint-design: violations found\n" + violations.map((v) => `  - ${v}`).join("\n"));
    process.exit(1);
  }
  console.log("lint-design: no stray color literals or em dashes");
}

main();
