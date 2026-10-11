#!/usr/bin/env node
// Transplanted from aacrit/dial scripts/contract.mjs (2026-10-03): adds burst_host for hosts under the zone WAF, host_suffix checks, a named User-Agent and fetch retries. Agentique template follow-up.
// Runs the served-page contract (contract.yaml) against a live URL. Used by
// `npm run contract`, by CI's verify-production.yml, and by the /release and
// /launch skills. No dependencies beyond Node and the `yaml` package.

import { createHash } from "node:crypto";
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

/** The runner's words for a check that does not apply to this host. The /release skill matches them exactly. */
export const NOT_APPLICABLE = "n/a (production host only)";

/** Whether `baseUrl`'s host is `suffix` or one of its subdomains. */
export function onHost(baseUrl, suffix) {
  const host = new URL(baseUrl).hostname.toLowerCase();
  const s = String(suffix).toLowerCase().replace(/^\./, "");
  return host === s || host.endsWith(`.${s}`);
}

function joinUrl(base, checkPath) {
  return new URL(checkPath, base).toString();
}

/**
 * Every request names itself. Node's fetch sends no browser headers at all,
 * and a scripted client with a bare "node" User-Agent is exactly what a
 * zone's bot rules are written to challenge; a named one can be told apart
 * in Security Events and allowed on purpose.
 */
export const USER_AGENT = "document-contract/1 (+https://document.voidvision.org/privacy)";

/**
 * Why a fetch failed below HTTP, in words: undici's "fetch failed" hides
 * the reason (DNS, refused, reset, TLS) in `cause`, and without it a red
 * production check cannot be told apart from a missing DNS record.
 */
export function describeFetchError(err) {
  const msg = err?.message ?? String(err);
  const cause = err?.cause;
  if (!cause) return msg;
  const code = cause.code ?? cause.errno;
  const detail = cause.message && cause.message !== msg ? cause.message : "";
  return [msg, code, detail].filter(Boolean).join(": ");
}

/**
 * fetch, with this runner's User-Agent, retried once after `retryMs` when
 * the request fails below HTTP (a DNS or connection blip on a shared CI
 * runner). An HTTP answer, whatever its status, is never retried.
 */
export async function contractFetch(url, init = {}, retryMs = 2000) {
  const headers = { "user-agent": USER_AGENT, ...(init.headers ?? {}) };
  try {
    return await fetch(url, { ...init, headers });
  } catch (err) {
    if (!retryMs) throw err;
    await new Promise((resolve) => setTimeout(resolve, retryMs));
    return fetch(url, { ...init, headers });
  }
}

async function runCheck(check, baseUrl, originalBase = baseUrl) {
  const target = joinUrl(baseUrl, check.path ?? "/");
  const label = check.name ?? `${check.type} ${check.path ?? "/"}`;

  // A check about the production zone (host_suffix: voidvision.org) does not
  // apply to any other host, a workers.dev preview included: reported as not
  // applicable, never as a skip or a pass (the /release skill matches NOT_APPLICABLE).
  // Judged on the URL the contract was run against, never on a rerouted burst host.
  if (check.host_suffix && !onHost(originalBase, check.host_suffix)) {
    return { label, pass: true, notApplicable: true, detail: NOT_APPLICABLE };
  }

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
      // With `method` and `body`, each request is that POST (a JSON body):
      // an invalid body is refused by validation until the limit bites, so
      // a burst on a write path writes nothing.
      const statuses = [];
      let matched = false;
      const init = check.method
        ? { method: check.method, headers: { "content-type": "application/json" }, body: JSON.stringify(check.body ?? {}) }
        : { cache: "no-store" };
      const one = async () => {
        const r = await contractFetch(target, init, 0);
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
      // With `wave_gap_ms`, a pause between waves: the binding's count settles
      // a moment after the requests that raised it, so back-to-back waves
      // can all pass before it bites; a short gap lets it catch up.
      const wave = Math.max(1, check.concurrency ?? 1);
      for (let sent = 0; sent < check.count; sent += wave) {
        if (sent && check.wave_gap_ms) await new Promise((resolve) => setTimeout(resolve, check.wave_gap_ms));
        await Promise.all(Array.from({ length: Math.min(wave, check.count - sent) }, one));
        if (matched) break;
      }
      const want = check.expect_error === undefined ? `${check.expect_status}` : `${check.expect_status} with {"error":"${check.expect_error}"}`;
      return { label, pass: matched, detail: matched ? undefined : `no ${want} in ${check.count} requests (got ${[...new Set(statuses)].join(", ")})` };
    }

    if (check.type === "redirect") {
      // The same host and path over `scheme` (http), not followed: it must
      // answer `expect` (301) with a Location starting `location_starts_with`.
      const from = new URL(target);
      if (check.scheme) from.protocol = `${check.scheme}:`;
      const r = await contractFetch(from, { redirect: "manual" });
      await r.arrayBuffer();
      const location = r.headers.get("location") ?? "";
      // With `same_url_on_https`, the Location must be exactly the requested URL on https://.
      const sameUrl = new URL(from);
      sameUrl.protocol = "https:";
      sameUrl.port = "";
      const wantLocation = check.same_url_on_https ? sameUrl.toString() : check.location_starts_with;
      const pass =
        r.status === check.expect &&
        (check.location_starts_with === undefined || location.startsWith(check.location_starts_with)) &&
        (!check.same_url_on_https || location === sameUrl.toString());
      return { label, pass, detail: pass ? undefined : `${from} answered ${r.status}${location ? ` to ${location}` : ""}, expected ${check.expect} to ${wantLocation ?? "anywhere"}` };
    }

    const response = await contractFetch(target);

    // `sources` names a JSON file on the site (a film's sources.json) and `field` a dotted path in it.
    const sourcesField = async () => {
      const r = await contractFetch(joinUrl(baseUrl, check.sources));
      if (!r.ok) throw new Error(`${check.sources} answered ${r.status}`);
      const doc = await r.json();
      return { doc, value: String(check.field).split(".").reduce((o, k) => (o == null ? undefined : o[k]), doc) };
    };

    switch (check.type) {
      case "sha256_matches": {
        // The served bytes at `path` hash to what sources.json recorded for them.
        if (!response.ok) return { label, pass: false, detail: `${target} answered ${response.status}` };
        const actual = createHash("sha256").update(Buffer.from(await response.arrayBuffer())).digest("hex");
        const { value } = await sourcesField();
        const pass = typeof value === "string" && value === actual;
        return { label, pass, detail: pass ? undefined : `${check.path} hashes to ${actual}, ${check.sources} records ${value}` };
      }
      case "duration_matches": {
        // A duration recorded in sources.json agrees with the film's own within one frame.
        await response.arrayBuffer();
        const { doc, value } = await sourcesField();
        const fps = Number(doc.fps) || 24;
        const pass = typeof value === "number" && Math.abs(value - Number(doc.duration_s)) <= 1 / fps + 1e-6;
        return { label, pass, detail: pass ? undefined : `${check.field} is ${value}, duration_s is ${doc.duration_s}: more than one frame apart` };
      }
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
      case "each_status": {
        // `path` answers a JSON list of this site's paths; each must answer `expect`.
        const list = await response.json();
        if (!Array.isArray(list) || list.length === 0) return { label, pass: false, detail: `no list of paths at ${target}` };
        const bad = [];
        for (const p of list) {
          const r = await contractFetch(new URL(p, baseUrl));
          await r.arrayBuffer();
          if (r.status !== check.expect) bad.push(`${p} ${r.status}`);
        }
        const pass = bad.length === 0;
        return { label, pass, detail: pass ? undefined : `not ${check.expect}: ${bad.join(", ")}` };
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
    return { label, pass: false, detail: `request to ${target} failed: ${describeFetchError(err)}` };
  }
}

/**
 * Where a burst goes. On a host under the contract's `burst_zone` (the
 * production domain), the zone's WAF blocks a burst before the Worker's own
 * limit can answer, so it goes to `burst_host`, the same deployment's
 * workers.dev address. Any other base (a preview, localhost) is used as is.
 */
export function burstBase(contract, baseUrl) {
  if (contract.burst_zone && contract.burst_host && onHost(baseUrl, contract.burst_zone)) return contract.burst_host;
  return baseUrl;
}

/** The build a deployment serves, from its /healthz, or "" when it does not say. */
async function servedBuild(base) {
  try {
    const r = await contractFetch(joinUrl(base, "/healthz"), { cache: "no-store" });
    const data = await r.json();
    return typeof data?.build === "string" ? data.build : "";
  } catch {
    return "";
  }
}

/**
 * Whether `burstHost` serves the same build as `baseUrl`: a burst sent there
 * proves the production Worker's limit only if it is the production Worker.
 * A mistyped or stale burst_host fails; a gradual deployment mid-split may.
 */
export async function burstHostProblem(baseUrl, burstHost) {
  const [prod, other] = await Promise.all([servedBuild(baseUrl), servedBuild(burstHost)]);
  if (prod && prod === other) return undefined;
  return `burst_host ${burstHost} serves ${other || "no build"}, ${baseUrl} serves ${prod || "no build"}`;
}

export async function runContract(contract, baseUrl) {
  const results = [];
  let hostProblem;
  let hostChecked = false;
  for (let check of contract.checks) {
    const base = check.type === "burst" ? burstBase(contract, baseUrl) : baseUrl;
    let r;
    const notHere = (check.host_suffix && !onHost(baseUrl, check.host_suffix)) || (check.requires === "deployed" && isLocalUrl(baseUrl));
    if (base !== baseUrl && !notHere) {
      if (!hostChecked) {
        // The build check's request to production counts toward the zone's WAF window too:
        // wait out this burst's pause first, so it never reads a 1015 page as "no build".
        if (check.pause_before_seconds) {
          await new Promise((resolve) => setTimeout(resolve, check.pause_before_seconds * 1000));
          check = { ...check, pause_before_seconds: 0 };
        }
        hostProblem = await burstHostProblem(baseUrl, base);
        hostChecked = true;
      }
      const label = check.name ?? `${check.type} ${check.path ?? "/"}`;
      r = hostProblem ? { label, pass: false, detail: hostProblem, buildMismatch: true } : await runCheck(check, base, baseUrl);
      r.rerouted = true;
      // Say where it ran: the summary names the base URL, and this burst did not run there.
      r.detail = `${r.detail ? `${r.detail}; ` : ""}via ${base}`;
    } else {
      r = await runCheck(check, base, baseUrl);
    }
    // A check that waits on someone (a zone setting, a Board ask) says who, in its failure.
    if (!r.pass && check.failure_note) r.detail = `${r.detail ?? "failed"}. ${check.failure_note}`;
    results.push(r);
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
  const passed = results.filter((r) => r.pass && !r.skipped && !r.notApplicable).length;
  const skipped = results.filter((r) => r.skipped).length;
  const notApplicable = results.filter((r) => r.notApplicable).length;
  const ran = results.length - skipped - notApplicable;
  const rerouted = results.filter((r) => r.rerouted).length;
  const buildMatched = !results.some((r) => r.buildMismatch);

  for (const r of results) {
    console.log(`${r.notApplicable ? "N/A " : r.skipped ? "SKIP" : r.pass ? "PASS" : "FAIL"}  ${r.label}${r.detail ? ` - ${r.detail}` : ""}`);
  }
  console.log(
    `\n${passed}/${ran} checks passed against ${baseUrl}${skipped ? `; ${skipped} skipped: needs deployed runtime` : ""}${notApplicable ? `; ${notApplicable} ${NOT_APPLICABLE}` : ""}${rerouted ? `; ${rerouted} burst${rerouted === 1 ? "" : "s"} ran via ${contract.burst_host}${buildMatched ? " (same build)" : " (build did not match)"}` : ""}`,
  );

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
