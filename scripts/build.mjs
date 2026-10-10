#!/usr/bin/env node
// Builds web/ to dist/ (matching wrangler.jsonc's assets.directory) and
// stamps the build with a tag: the current release/* tag if HEAD is exactly
// on one, else a short sha, else "dev". The tag lands in two places static
// assets can serve without the Worker needing to parse anything at request
// time: dist/build-tag.txt (read by the /healthz handler via env.ASSETS) and
// the <meta name="build"> placeholder in dist/*.html. It also injects the
// CSP meta into every page and writes dist/_headers (scripts/lib/csp.mjs).

import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { runBin } from "./lib/run-bin.mjs";
import { cspViolations, headersFile, injectCsp } from "./lib/csp.mjs";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const webDir = path.join(repoRoot, "web");
const distDir = path.join(repoRoot, "dist");

export function computeBuildTag(cwd = repoRoot, run = execFileSync) {
  const quiet = { cwd, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] };
  try {
    return run("git", ["describe", "--tags", "--exact-match"], quiet).trim();
  } catch {
    // Not on an exact tag; fall through.
  }
  try {
    return run("git", ["rev-parse", "--short", "HEAD"], quiet).trim();
  } catch {
    return "dev";
  }
}

export function stampHtml(text, tag) {
  return text.replaceAll("__BUILD__", tag);
}

function main() {
  const result = runBin("vite", "vite", ["build"], { cwd: webDir });
  if (result.error || result.status !== 0) {
    console.error("build: vite build failed");
    process.exit(result.status ?? 1);
  }

  const tag = computeBuildTag();
  writeFileSync(path.join(distDir, "build-tag.txt"), `${tag}\n`);

  // Every page in dist/, at any depth, gets the one policy.
  const htmlFiles = readdirSync(distDir, { recursive: true, encoding: "utf8" }).filter((f) => f.endsWith(".html"));
  for (const file of htmlFiles) {
    const full = path.join(distDir, file);
    const stamped = injectCsp(stampHtml(readFileSync(full, "utf8"), tag));
    // The page must work under its own policy: fail the build rather than
    // ship markup the CSP would block.
    const violations = cspViolations(stamped);
    if (violations.length) {
      console.error(`build: dist/${file} breaks its Content-Security-Policy: ${violations.join(", ")}`);
      process.exit(1);
    }
    writeFileSync(full, stamped);
  }

  // Static assets skip the Worker (wrangler.jsonc's assets.run_worker_first
  // lists only the Worker's routes), so the headers a <meta> cannot carry
  // (frame-ancestors, X-Frame-Options, nosniff, Referrer-Policy) reach them
  // through Workers Static Assets' _headers file, which it reads and never
  // serves.
  writeFileSync(path.join(distDir, "_headers"), headersFile());

  console.log(`build: stamped dist/ with build tag "${tag}"`);
}

main();
