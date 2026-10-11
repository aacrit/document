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
import { BALANCE_FALLBACK_SLUG, loadRegistry, marqueeFilm, publishedTracks, trackLabel } from "./lib/films.mjs";

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
  if (contract.films) {
    const registry = loadRegistry(path.resolve(path.dirname(contractPath), contract.films.registry ?? "films.json"));
    contract.checks = expandFilmChecks(contract, registry);
  } else if (contract.checks.some((c) => c && c.expand)) {
    throw new Error(`${contractPath}: checks say expand: films but there is no films block`);
  }
  for (const check of contract.checks) {
    const problem = whenDeclaredProblem(check);
    if (problem) throw new Error(`${contractPath}: ${check.name ?? check.type}: ${problem}`);
  }
  return contract;
}

// ---- Film checks, once per registered film --------------------------------------------------

const FOR = ["live", "in_production", "marquee"];
const IF = ["poster", "declares_balance"];
const EACH = ["caption", "related"];
const VARS = ["slug", "title", "shows", "lang", "label", "href", "poster"];

/** Fills {name} in every string of a check; a name the film does not give is a contract error. */
function fillCheck(value, vars, where) {
  if (typeof value === "string") {
    return value.replace(/\{([a-z_]+)\}/g, (all, key) => {
      if (!VARS.includes(key)) throw new Error(`${where}: unknown placeholder {${key}}`);
      if (vars[key] === undefined || vars[key] === null) throw new Error(`${where}: {${key}} has no value for this film`);
      return String(vars[key]);
    });
  }
  if (Array.isArray(value)) return value.map((v) => fillCheck(v, vars, where));
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, fillCheck(v, vars, where)]));
  return value;
}

/**
 * The contract's checks with `expand: films` replaced by the films block's
 * checks, once per film in films.json (in registry order): `for` picks the
 * films (live by default; coming; marquee, the home page's film), `each`
 * repeats a check per published caption track or related link, and `if:
 * poster` keeps it only for a film that names a poster. A coming film gets
 * only the checks written for it, so its media is never required.
 */
export function expandFilmChecks(contract, registry) {
  const templates = contract.films?.checks;
  if (!Array.isArray(templates)) throw new Error("contract.yaml: films.checks must be a list");
  const markers = contract.checks.filter((c) => c && c.expand);
  if (markers.length !== 1 || markers[0].expand !== "films") throw new Error("contract.yaml: checks must say `expand: films` exactly once");
  const marquee = marqueeFilm(registry);
  const out = [];
  for (const film of registry.films) {
    for (const t of templates) {
      const { for: forList = ["live"], each, if: cond, ...check } = t;
      const where = `films.checks ${t.name ?? t.type}`;
      if (!Array.isArray(forList) || forList.some((f) => !FOR.includes(f))) throw new Error(`${where}: for must list ${FOR.join(", ")}`);
      if (each !== undefined && !EACH.includes(each)) throw new Error(`${where}: each must be ${EACH.join(" or ")}`);
      if (cond !== undefined && !IF.includes(cond)) throw new Error(`${where}: if must be ${IF.join(" or ")}`);
      const applies = forList.includes(film.status) || (forList.includes("marquee") && film === marquee);
      if (!applies) continue;
      if (cond === "poster" && !film.poster) continue;
      // Only the pilot's live file may lack a balance block (its figures are the site's fallback); every other live film declares one.
      if (cond === "declares_balance" && film.slug === BALANCE_FALLBACK_SLUG && film.balance_fallback === true) continue;
      const base = { slug: film.slug, title: film.title, shows: film.shows, poster: film.poster };
      const rows =
        each === "caption"
          ? publishedTracks(film).map((c) => ({ ...base, lang: c.lang, label: trackLabel(c) }))
          : each === "related"
            ? (film.related ?? []).map((r) => ({ ...base, href: r.href }))
            : [base];
      for (const vars of rows) out.push({ ...fillCheck(check, vars, where), film: film.slug });
    }
  }
  return contract.checks.flatMap((c) => (c && c.expand ? out : [c]));
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
export const NOT_DECLARED = "n/a (not declared)";

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
  const { unpaced, ...rest } = init;
  const headers = { "user-agent": USER_AGENT, ...(rest.headers ?? {}) };
  const host = new URL(url).host;
  const once = async () => {
    // Every request a check makes counts toward the zone's window, byte ranges included; a deliberate burst does not.
    if (!unpaced) await runtime.pacer.take(host);
    return runtime.fetch(url, { ...rest, headers });
  };
  let response;
  try {
    response = await once();
  } catch (err) {
    if (!retryMs) throw err;
    await runtime.sleep(retryMs);
    response = await once();
  }
  // A burst expects 429s and reads them itself; anything else answered by the zone's block page is not the product's answer.
  if (!unpaced) {
    const block = await zoneBlock(response);
    if (block) throw new ZoneBlockedError(String(url), response.status, block);
  }
  return response;
}

// ---- Pacing under the zone's rate rule ----------------------------------------------------
//
// The zone's WAF rule (contract.yaml zone_waf_rule: 30 requests per 10 s per
// IP, every path but /assets/*) blocks a client that asks faster, with its
// own 429 page, for the rest of the window. The full contract makes more
// than 30 requests, so the runner paces itself: at most PACE_LIMIT requests
// to one host in any PACE_WINDOW_MS. A sliding window, not a refilling
// bucket: a bucket can let a full refill land beside a burst and pass 30 in
// one window; a sliding log never lets more than the limit into any window.

export const PACE_LIMIT = 20;
export const PACE_WINDOW_MS = 10_000;
/** After a block: the zone's window plus its 10 s mitigation, and a second of slack. */
export const BLOCK_WAIT_MS = 11_000;
export const ZONE_BLOCKED = "rate-limited by the zone, not a product failure";

/** At most `limit` requests to one host in any `windowMs`, on an injectable clock. */
export function createPacer({ limit = PACE_LIMIT, windowMs = PACE_WINDOW_MS, now = () => Date.now(), sleep = realSleep, pace = () => true } = {}) {
  const sent = new Map();
  return {
    sent,
    async take(host) {
      if (!pace(host)) return;
      const log = sent.get(host) ?? [];
      sent.set(host, log);
      for (;;) {
        const t = now();
        while (log.length && log[0] <= t - windowMs) log.shift();
        if (log.length < limit) {
          log.push(t);
          return;
        }
        await sleep(log[0] + windowMs - t);
      }
    },
  };
}

function realSleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, Math.max(0, ms)));
}

const isLocalHost = (host) => isLocalUrl(`http://${host}`);
const defaultRuntime = () => ({
  fetch: (...a) => fetch(...a),
  sleep: realSleep,
  pacer: createPacer({ pace: (host) => !isLocalHost(host) }),
  blockWaitMs: BLOCK_WAIT_MS,
});
let runtime = defaultRuntime();

export class ZoneBlockedError extends Error {
  constructor(url, status, why) {
    super(`${ZONE_BLOCKED}: ${url} answered ${status} (${why})`);
    this.status = status;
  }
}

// Cloudflare's own block and challenge pages, never anything the Worker writes.
const BLOCK_MARKERS = [/error 1015/i, /you are being rate limited/i, /attention required!? \| cloudflare/i, /cf-error-details/i, /cdn-cgi\/challenge-platform/i, /sorry, you have been blocked/i];

/**
 * Why a response is the zone's block rather than the product's answer, or
 * null. A 429 is the zone's unless it is the Worker's own JSON refusal
 * ({"error":"rate_limited"}, which a non-burst check never provokes but is
 * reported as itself); a 403 or 503 is the zone's when its body is a
 * Cloudflare block page.
 */
export async function zoneBlock(response) {
  if (![429, 403, 503].includes(response.status)) return null;
  let text = "";
  try {
    text = await response.clone().text();
  } catch {
    // Unreadable: judge by status alone.
  }
  if (response.status === 429) {
    try {
      if (JSON.parse(text)?.error === "rate_limited") return null;
    } catch {
      // Not the Worker's JSON.
    }
    return BLOCK_MARKERS.some((m) => m.test(text)) ? "a Cloudflare block page" : "429 with no Worker body";
  }
  return BLOCK_MARKERS.some((m) => m.test(text)) ? "a Cloudflare block page" : null;
}

/**
 * `when_declared` only makes sense on a hash check of the declared record itself: the check's
 * `field` must sit inside it ("trailer" with "trailer.sha256"). Anything else is a contract error.
 */
export function whenDeclaredProblem(check) {
  if (!check.when_declared) return null;
  if (check.type !== "sha256_matches") return `contract error: when_declared is only allowed on sha256_matches, not ${check.type}`;
  if (!String(check.field ?? "").startsWith(`${check.when_declared}.`)) {
    return `contract error: field ${check.field} is not inside when_declared ${check.when_declared}`;
  }
  if (!check.sources) return "contract error: when_declared needs sources";
  return null;
}

/**
 * What is wrong with a web app manifest, by what Chrome needs to install it
 * (a name, a start_url, a display mode, a 192 and a 512 px PNG icon) and
 * what this product requires on top (an id and a scope, maskable icons at
 * both sizes, theme and background colours, no orientation lock). Empty
 * when nothing is.
 */
export function manifestProblems(doc) {
  if (!doc || typeof doc !== "object" || Array.isArray(doc)) return ["not a JSON object"];
  const problems = [];
  for (const field of ["id", "name", "short_name", "start_url", "scope", "display", "background_color", "theme_color"]) {
    if (typeof doc[field] !== "string" || !doc[field]) problems.push(`no ${field}`);
  }
  if (doc.display && !["fullscreen", "standalone", "minimal-ui"].includes(doc.display)) problems.push(`display ${doc.display} cannot install`);
  if ("orientation" in doc) problems.push("an orientation lock (landscape belongs to the player only)");
  const icons = Array.isArray(doc.icons) ? doc.icons : [];
  const has = (size, purpose) =>
    icons.some((i) => i && i.type === "image/png" && String(i.sizes).split(/\s+/).includes(`${size}x${size}`) && String(i.purpose ?? "any").split(/\s+/).includes(purpose));
  for (const size of [192, 512]) {
    for (const purpose of ["any", "maskable"]) if (!has(size, purpose)) problems.push(`no ${size}px ${purpose} PNG icon`);
  }
  return problems;
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

  // `when_declared` (a dotted path in `sources`): the check applies only when the film's sources.json
  // declares that record (an optional trailer). Undeclared, it is reported as not declared, never as a
  // pass; a sources.json that cannot be read fails the check.
  // With `undeclared_status`, an undeclared record is checked too: its path must answer that status
  // (a 404: nothing stale is served when nothing is declared).
  if (check.when_declared) {
    const problem = whenDeclaredProblem(check);
    if (problem) return { label, pass: false, detail: problem };
    try {
      const r = await contractFetch(joinUrl(baseUrl, check.sources));
      if (!r.ok) return { label, pass: false, detail: `${check.sources} answered ${r.status}` };
      const doc = await r.json();
      const rec = String(check.when_declared).split(".").reduce((o, k) => (o == null ? undefined : o[k]), doc);
      if (rec == null) {
        if (check.undeclared_status === undefined) {
          return { label, pass: true, undeclared: true, detail: `${NOT_DECLARED}: ${check.sources} declares no ${check.when_declared}` };
        }
        const res = await contractFetch(target);
        await res.body?.cancel();
        const pass = res.status === check.undeclared_status;
        return {
          label,
          pass,
          detail: `${check.sources} declares no ${check.when_declared}: ${check.path} answered ${res.status}${pass ? "" : `, expected ${check.undeclared_status}`}`,
        };
      }
    } catch (err) {
      if (err instanceof ZoneBlockedError) throw err;
      return { label, pass: false, detail: `${check.sources}: ${err.message}` };
    }
  }

  // A burst right after the other checks can trip the zone's WAF rule
  // (30 requests per 10 s per IP, counted across every non-/assets path),
  // whose 429 is not the Worker's. Waiting out its window first keeps the
  // burst measuring the Worker's own limit.
  if (check.pause_before_seconds) {
    await runtime.sleep(check.pause_before_seconds * 1000);
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
        ? { method: check.method, headers: { "content-type": "application/json" }, body: JSON.stringify(check.body ?? {}), unpaced: true }
        : { cache: "no-store", unpaced: true };
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
        // The served bytes at `path` hash to what sources.json recorded for them. With `max_bytes`, a
        // file larger than that is checked by its size and the hashes of its first and last
        // `max_bytes` bytes (fetched as byte ranges) against `field`'s `_head`/`_tail`/`_size`
        // companions, so a scheduled run never downloads a whole film.
        if (!response.ok) return { label, pass: false, detail: `${target} answered ${response.status}` };
        if (check.max_bytes) {
          const len = Number(response.headers.get("content-length") ?? "NaN");
          if (Number.isFinite(len) && len > check.max_bytes) {
            await response.body?.cancel();
            const n = check.max_bytes;
            const part = async (range) => {
              const r = await contractFetch(target, { headers: { range } });
              if (r.status !== 206) throw new Error(`${check.path} answered ${r.status} to a byte range`);
              return createHash("sha256").update(Buffer.from(await r.arrayBuffer())).digest("hex");
            };
            const { doc } = await sourcesField();
            const base = String(check.field).split(".");
            const rec = base.slice(0, -1).reduce((o, k) => (o == null ? undefined : o[k]), doc) ?? {};
            const key = base[base.length - 1];
            const head = await part(`bytes=0-${n - 1}`);
            const tail = await part(`bytes=-${n}`);
            const pass = rec[`${key}_size`] === len && rec[`${key}_head`] === head && rec[`${key}_tail`] === tail;
            return {
              label,
              pass,
              detail: pass ? undefined : `${check.path}: size ${len}, head ${head.slice(0, 12)}, tail ${tail.slice(0, 12)} do not match ${check.sources}'s ${check.field}_size/_head/_tail`,
            };
          }
        }
        const actual = createHash("sha256").update(Buffer.from(await response.arrayBuffer())).digest("hex");
        const { value } = await sourcesField();
        const pass = typeof value === "string" && value === actual;
        return { label, pass, detail: pass ? undefined : `${check.path} hashes to ${actual}, ${check.sources} records ${value}` };
      }
      case "sources_duration_consistent": {
        // A consistency check inside sources.json: the duration the release step measured on the web
        // encode (publish.py) agrees with the film's duration_s within one frame. It does not measure
        // the served film; sha256_matches ties the served bytes to that record.
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
      case "json_has": {
        // A dotted field of a JSON file is present and not null (a film's sources.json declares its balance).
        if (!response.ok) return { label, pass: false, detail: `${target} answered ${response.status}` };
        const data = await response.json();
        const value = String(check.field).split(".").reduce((o, k) => (o == null ? undefined : o[k]), data);
        const pass = value !== undefined && value !== null && !(Array.isArray(value) && value.length === 0);
        return { label, pass, detail: pass ? undefined : `${check.path} has no ${check.field}` };
      }
      case "app_manifest": {
        // The web app manifest: served as application/manifest+json, and it parses with what an install needs.
        if (!response.ok) return { label, pass: false, detail: `${target} answered ${response.status}` };
        const type = response.headers.get("content-type") ?? "";
        const problems = type.split(";")[0].trim() === "application/manifest+json" ? [] : [`content-type is "${type}"`];
        let doc;
        try {
          doc = JSON.parse(await response.text());
        } catch {
          return { label, pass: false, detail: [...problems, "does not parse as JSON"].join("; ") };
        }
        problems.push(...manifestProblems(doc));
        return { label, pass: problems.length === 0, detail: problems.length ? problems.join("; ") : undefined };
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
    if (err instanceof ZoneBlockedError) throw err;
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

/**
 * Runs one check; when the zone blocks it, waits out the window once and runs
 * it again. Blocked twice, it fails, saying it was the zone and not the
 * product, so a red run never reads as wrong headers or a missing page.
 */
async function runPaced(check, base, originalBase) {
  for (let attempt = 1; ; attempt++) {
    try {
      return await runCheck(check, base, originalBase);
    } catch (err) {
      if (!(err instanceof ZoneBlockedError)) throw err;
      const label = check.name ?? `${check.type} ${check.path ?? "/"}`;
      if (attempt >= 2) return { label, pass: false, zoneBlocked: true, detail: `${err.message}; blocked again after waiting ${runtime.blockWaitMs / 1000} s` };
      await runtime.sleep(runtime.blockWaitMs);
    }
  }
}

/**
 * `options` (tests): fetch, sleep, pacer and blockWaitMs replace the real
 * network, clock and pacing for this run.
 */
export async function runContract(contract, baseUrl, options = {}) {
  runtime = { ...defaultRuntime(), ...options };
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
          await runtime.sleep(check.pause_before_seconds * 1000);
          check = { ...check, pause_before_seconds: 0 };
        }
        hostProblem = await burstHostProblem(baseUrl, base);
        hostChecked = true;
      }
      const label = check.name ?? `${check.type} ${check.path ?? "/"}`;
      r = hostProblem ? { label, pass: false, detail: hostProblem, buildMismatch: true } : await runPaced(check, base, baseUrl);
      r.rerouted = true;
      // Say where it ran: the summary names the base URL, and this burst did not run there.
      r.detail = `${r.detail ? `${r.detail}; ` : ""}via ${base}`;
    } else {
      r = await runPaced(check, base, baseUrl);
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
  const passed = results.filter((r) => r.pass && !r.skipped && !r.notApplicable && !r.undeclared).length;
  const skipped = results.filter((r) => r.skipped).length;
  const notApplicable = results.filter((r) => r.notApplicable).length;
  const undeclared = results.filter((r) => r.undeclared).length;
  const ran = results.length - skipped - notApplicable - undeclared;
  const rerouted = results.filter((r) => r.rerouted).length;
  const buildMatched = !results.some((r) => r.buildMismatch);
  const zoneBlocked = results.filter((r) => r.zoneBlocked).length;

  for (const r of results) {
    console.log(`${r.notApplicable || r.undeclared ? "N/A " : r.skipped ? "SKIP" : r.pass ? "PASS" : "FAIL"}  ${r.label}${r.detail ? ` - ${r.detail}` : ""}`);
  }
  console.log(
    `\n${passed}/${ran} checks passed against ${baseUrl}${skipped ? `; ${skipped} skipped: needs deployed runtime` : ""}${notApplicable ? `; ${notApplicable} ${NOT_APPLICABLE}` : ""}${undeclared ? `; ${undeclared} ${NOT_DECLARED}` : ""}${rerouted ? `; ${rerouted} burst${rerouted === 1 ? "" : "s"} ran via ${contract.burst_host}${buildMatched ? " (same build)" : " (build did not match)"}` : ""}`,
  );

  if (zoneBlocked) console.log(`${zoneBlocked} check${zoneBlocked === 1 ? " was" : "s were"} ${ZONE_BLOCKED}: rerun after the window before reading them as product failures`);

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
