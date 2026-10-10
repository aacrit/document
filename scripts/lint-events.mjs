#!/usr/bin/env node
// The success event is what the kill criteria count, so it must be the
// product's own core action, named for it. Fails the gate when:
//   - contract.yaml's success_event is missing, still the template
//     placeholder, or a generic name ("success", "page_view", feedback);
//   - it is not in events.allowed, or it is server-only;
//   - CHARTER.md's "Kill criteria" section does not name it in backticks;
//   - nothing in web/src or worker/src sends it: a reportCoreSuccess() call,
//     or the name as a string literal, outside comments and the wrapper's own definition
//     and outside config.ts. An unused wrapper sends nothing.
// Rollbook shipped with success_event: success, fired only by the feedback
// form, so its kill-criteria count measured feedback, not the product.

import { readFileSync, existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parse as parseYaml } from "yaml";
import { walk } from "./lib/walk.mjs";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

export const PLACEHOLDER = "<core_success_event>";
const GENERIC = new Set(["success", "page_view", "pageview", "feedback", "feedback_received", "feedback_sent", "rate_limiter_error"]);

const WRAPPER_DEFINITION = /(?:export\s+)?(?:async\s+)?function\s+reportCoreSuccess\s*\([^)]*\)[^{]*\{[\s\S]*?\n\}/g;

/** Removes the reportCoreSuccess wrapper's own definition, so its body is not mistaken for a sender. */
export function stripWrapper(text) {
  return text.replace(WRAPPER_DEFINITION, "");
}

/**
 * Removes block, line and HTML comments, so "TODO: call reportCoreSuccess()"
 * is not mistaken for a call. A `//` right after a colon or a quote (a URL
 * in a string) is kept.
 */
export function stripComments(text) {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/<!--[\s\S]*?-->/g, "")
    .replace(/(^|[^:"'`\\])\/\/.*$/gm, "$1");
}

function escapeRegExp(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * True when some code actually sends the success event: a call to
 * reportCoreSuccess( outside its definition, or the event name as a string
 * literal ("...", '...' or a template literal) outside the wrapper.
 */
export function hasCallSite(name, sources) {
  const literal = new RegExp(`["'\`]${escapeRegExp(name)}["'\`]`);
  return Object.values(sources).some((text) => {
    const rest = stripWrapper(stripComments(text));
    return /\breportCoreSuccess\s*\(/.test(rest) || literal.test(rest);
  });
}

/** The "## Kill criteria" section of CHARTER.md, up to the next heading. */
export function killCriteriaSection(charterText) {
  const m = /^##\s+Kill criteria\s*$([\s\S]*?)(?=^##\s|(?![\s\S]))/m.exec(charterText);
  return m ? m[1] : null;
}

/**
 * Pure check. `contract` is parsed contract.yaml, `charterText` is
 * CHARTER.md, `sources` maps a relative path to its text (web/src and
 * worker/src, config.ts excluded). Returns a list of violations.
 */
export function checkSuccessEvent({ contract, charterText, sources }) {
  const v = [];
  const name = contract?.success_event;
  const allowed = contract?.events?.allowed ?? [];
  const serverOnly = contract?.events?.server_only ?? [];

  if (typeof name !== "string" || name.trim() === "") {
    return ["contract.yaml has no success_event: name the product's core success event"];
  }
  if (name === PLACEHOLDER || /[<>]/.test(name)) {
    v.push(`contract.yaml success_event is still the template placeholder "${name}": rename it to the product's core action (the /brief skill's charter step), in contract.yaml, worker/src/config.ts, CHARTER.md and web/src/main.ts`);
  } else if (GENERIC.has(name.toLowerCase())) {
    v.push(`contract.yaml success_event "${name}" is generic: kill criteria must count the product's core action, not "${name}"`);
  }
  if (!allowed.includes(name)) v.push(`success_event "${name}" is not in contract.yaml events.allowed`);
  if (serverOnly.includes(name)) v.push(`success_event "${name}" is server-only; the core action must be countable where it happens`);

  const kill = killCriteriaSection(charterText ?? "");
  if (kill === null) v.push('CHARTER.md has no "## Kill criteria" section');
  else if (!kill.includes(`\`${name}\``)) v.push(`CHARTER.md's kill criteria never name \`${name}\`: the success event must be what they count`);

  if (!hasCallSite(name, sources ?? {})) {
    v.push(
      `nothing in web/src or worker/src sends "${name}": call reportCoreSuccess() where the core action completes, or send the name outside that wrapper (the wrapper's definition alone and config.ts do not count)`,
    );
  }
  return v;
}

function readSources() {
  const out = {};
  for (const dir of ["web/src", "worker/src"]) {
    const abs = path.join(repoRoot, dir);
    if (!existsSync(abs)) continue;
    for (const file of walk(abs, new Set(["node_modules"]))) {
      if (!/\.(ts|tsx|js|jsx|mjs|vue|svelte)$/.test(file)) continue;
      const rel = path.relative(repoRoot, file).replace(/\\/g, "/");
      if (rel === "worker/src/config.ts") continue;
      out[rel] = readFileSync(file, "utf8");
    }
  }
  return out;
}

function main() {
  const contract = parseYaml(readFileSync(path.join(repoRoot, "contract.yaml"), "utf8"));
  const charterPath = path.join(repoRoot, "CHARTER.md");
  const charterText = existsSync(charterPath) ? readFileSync(charterPath, "utf8") : "";
  const violations = checkSuccessEvent({ contract, charterText, sources: readSources() });
  if (violations.length > 0) {
    console.error("lint-events: violations found\n" + violations.map((x) => `  - ${x}`).join("\n"));
    process.exit(1);
  }
  console.log(`lint-events: success_event "${contract.success_event}" is named, allowed, counted by the kill criteria and sent`);
}

const isMain = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) main();
