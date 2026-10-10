#!/usr/bin/env node
// Runs the served-page contract (contract.yaml) against a live URL. Used by
// `npm run contract`, by CI's verify-production.yml, and by the /release and
// /launch skills. No dependencies beyond Node and the `yaml` package.

import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parse as parseYaml } from "yaml";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_CONTRACT_PATH = path.join(__dirname, "..", "contract.yaml");

export function parseArgs(argv) {
  const args = { url: undefined, contractPath: DEFAULT_CONTRACT_PATH };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--url") {
      args.url = argv[++i];
    } else if (arg === "--contract") {
      args.contractPath = argv[++i];
    }
  }
  return args;
}

export function loadContract(contractPath) {
  const text = readFileSync(contractPath, "utf8");
  const contract = parseYaml(text);
  if (!contract || !Array.isArray(contract.checks)) {
    throw new Error(`${contractPath} has no \`checks\` list`);
  }
  return contract;
}

/**
 * Whether a base URL is a local dev server (wrangler dev, a test server).
 * Checks tagged `requires: deployed` need the real Cloudflare runtime (the
 * rate-limit binding counts only there), so they are skipped against one,
 * reported as skipped rather than passed or failed.
 */
export function isLocalUrl(baseUrl) {
  const host = new URL(baseUrl).hostname;
  return host === "localhost" || host === "127.0.0.1" || host === "[::1]" || host === "::1" || host.endsWith(".localhost");
}

function joinUrl(base, checkPath) {
  return new URL(checkPath, base).toString();
}

async function runCheck(check, baseUrl) {
  const target = joinUrl(baseUrl, check.path ?? "/");
  const label = check.name ?? `${check.type} ${check.path ?? "/"}`;

  if (check.requires === "deployed" && isLocalUrl(baseUrl)) {
    return { label, pass: true, skipped: true, detail: "skipped: needs deployed runtime" };
  }

  // A burst right after the other checks can trip the zone's WAF rule
  // (30 requests per 10 s per IP, counted across every non-/assets path),
  // whose 429 is not the Worker's. Waiting out its window first keeps the
  // burst measuring the Worker's own limit.
  if (check.pause_before_seconds) {
    await new Promise((resolve) => setTimeout(resolve, check.pause_before_seconds * 1000));
  }

  try {
    if (check.type === "burst") {
      // `count` requests back to back; passes when at least
      // one answers `expect_status` (a rate limit that actually bites).
      // With `expect_error`, that answer must also be the Worker's own JSON
      // body `{ "error": <expect_error> }`: a WAF block page (Cloudflare's
      // "Error 1015") is a 429 too, and must not pass for the Worker's
      // limit. Retry-After alone is not trusted for the same reason.
      // With `concurrency`, they go in waves of that many at once: the
      // Workers rate-limit binding counts permissively and is eventually
      // consistent, so a sequential probe at a few requests a second may
      // never trip it even though a real burst does.
      const statuses = [];
      let matched = false;
      const one = async () => {
        const r = await fetch(target, { cache: "no-store" });
        const text = await r.text();
        statuses.push(r.status);
        if (r.status !== check.expect_status) return;
        if (check.expect_error === undefined) {
          matched = true;
          return;
        }
        try {
          if (JSON.parse(text)?.error === check.expect_error) matched = true;
        } catch {
          // Not the Worker's JSON (a WAF or proxy page): does not count.
        }
      };
      const wave = Math.max(1, check.concurrency ?? 1);
      for (let sent = 0; sent < check.count; sent += wave) {
        await Promise.all(Array.from({ length: Math.min(wave, check.count - sent) }, one));
      }
      const want = check.expect_error === undefined ? `${check.expect_status}` : `${check.expect_status} with {"error":"${check.expect_error}"}`;
      return { label, pass: matched, detail: matched ? undefined : `no ${want} in ${check.count} requests (got ${[...new Set(statuses)].join(", ")})` };
    }

    const response = await fetch(target);

    switch (check.type) {
      case "status": {
        const pass = response.status === check.expect;
        return { label, pass, detail: pass ? undefined : `expected ${check.expect}, got ${response.status}` };
      }
      case "contains": {
        const body = await response.text();
        const pass = body.includes(check.text);
        return { label, pass, detail: pass ? undefined : `"${check.text}" not found at ${target}` };
      }
      case "meta": {
        const body = await response.text();
        const re = new RegExp(`<meta[^>]*name=["']${check.meta_name}["'][^>]*content=["']([^"']*)["']`, "i");
        const match = body.match(re);
        const pass = Boolean(match && match[1] && match[1].length > 0);
        return { label, pass, detail: pass ? undefined : `no non-empty <meta name="${check.meta_name}"> at ${target}` };
      }
      case "json": {
        const data = await response.json();
        const actual = data?.[check.field];
        const pass = actual === check.expect;
        return { label, pass, detail: pass ? undefined : `expected ${check.field}=${check.expect}, got ${actual}` };
      }
      case "forbidden": {
        const body = await response.text();
        const found = (check.strings ?? []).filter((s) => body.includes(s));
        const pass = found.length === 0;
        return { label, pass, detail: pass ? undefined : `found forbidden string(s): ${found.join(", ")}` };
      }
      case "header": {
        // A response header, matched exactly (`expect`) or by
        // substring (`contains`). Header names are case-insensitive.
        const actual = response.headers.get(check.header);
        const pass =
          actual !== null &&
          (check.expect === undefined || actual === check.expect) &&
          (check.contains === undefined || actual.includes(check.contains));
        const want = check.expect !== undefined ? `"${check.expect}"` : `containing "${check.contains}"`;
        return { label, pass, detail: pass ? undefined : `${check.header}: expected ${want}, got ${actual === null ? "no header" : `"${actual}"`}` };
      }
      default:
        return { label, pass: false, detail: `unknown check type "${check.type}"` };
    }
  } catch (err) {
    return { label, pass: false, detail: `request to ${target} failed: ${err.message ?? err}` };
  }
}

export async function runContract(contract, baseUrl) {
  const results = [];
  for (const check of contract.checks) {
    results.push(await runCheck(check, baseUrl));
  }
  return results;
}

async function main() {
  const { url, contractPath } = parseArgs(process.argv.slice(2));
  const contract = loadContract(contractPath);
  const baseUrl = url ?? contract.url;
  if (!baseUrl) {
    console.error("No URL: pass --url or set `url` in contract.yaml");
    process.exit(1);
  }

  const results = await runContract(contract, baseUrl);
  const passed = results.filter((r) => r.pass && !r.skipped).length;
  const skipped = results.filter((r) => r.skipped).length;
  const ran = results.length - skipped;

  for (const r of results) {
    console.log(`${r.skipped ? "SKIP" : r.pass ? "PASS" : "FAIL"}  ${r.label}${r.detail ? ` - ${r.detail}` : ""}`);
  }
  console.log(`\n${passed}/${ran} checks passed against ${baseUrl}${skipped ? `; ${skipped} skipped: needs deployed runtime` : ""}`);

  if (passed !== ran) {
    process.exit(1);
  }
}

const isMain = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  main().catch((err) => {
    console.error(err);
    process.exit(1);
  });
}
