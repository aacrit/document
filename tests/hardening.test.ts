// The template's security and free-tier baseline, ported from Rollbook's
// Proof review (doctrine L-24, L-26, L-27). Each block fails without its
// fix. Ceilings run on real SQLite (tests/helpers/sqlite-d1.ts), so the
// conditional upsert is proven on the SQL engine, not a string-matching mock.

import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parse as parseYaml } from "yaml";
import { describe, expect, it } from "vitest";
import { handle, handleEvent, handleFeedback, type Env } from "../worker/src/index";
import { COUNT_UNDER_CEILING_SQL, incrementUnderCeiling } from "../worker/src/events";
import {
  ACCOUNT_D1_WRITES_PER_DAY,
  CLIENT_EVENTS,
  RATE_LIMITER_ERROR_DAILY_CEILING,
  worstCaseDailyWrites,
} from "../worker/src/config";
import { clientKey, limiterFor, type RateLimiter } from "../worker/src/guard";
import { API_CSP } from "../worker/src/headers";
import { PAGE_CSP_HEADER, headersFile } from "../scripts/lib/csp.mjs";
import { createSqliteD1 } from "./helpers/sqlite-d1";
import { createMockAssets, createMockD1 } from "./helpers/mock-d1";
import { IDLE_SCENARIOS, runIdleScenario, simulateRetention } from "./helpers/retention-sim";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DAY = "2026-09-25";
const ORIGIN = "https://product.example";

function post(pathname: string, body: unknown, headers: Record<string, string> = {}): Request {
  return new Request(`${ORIGIN}${pathname}`, {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

function get(pathname: string, headers: Record<string, string> = {}): Request {
  return new Request(`${ORIGIN}${pathname}`, { headers });
}

async function sqliteEnv(overrides: Partial<Env> = {}) {
  const d1 = await createSqliteD1();
  const env: Env = { DB: d1.db, ASSETS: createMockAssets({ "": "<!doctype html><title>Home</title>" }), ...overrides };
  const changes = () => d1.query<{ n: number }>("SELECT total_changes() AS n")[0].n;
  const count = (name: string) => d1.query<{ count: number }>("SELECT count FROM event_counts WHERE name = ?", name)[0]?.count ?? 0;
  return { env, d1, changes, count };
}

const mockEnv = (overrides: Partial<Env> = {}): Env => ({ DB: createMockD1().db, ASSETS: createMockAssets(), ...overrides });

/** wrangler.jsonc without its // comments (no string value in it contains " //"). */
function wranglerConfig(): Record<string, any> {
  const text = readFileSync(path.join(root, "wrangler.jsonc"), "utf8")
    .split(/\r?\n/)
    .map((line) => line.replace(/^\s*\/\/.*$/, "").replace(/\s\/\/ .*$/, ""))
    .join("\n");
  return JSON.parse(text);
}

/** A fake Workers Rate Limiting binding: `limit` allowed calls per key, and a record of every key it saw. */
function fakeLimiter(limit: number): RateLimiter & { keys: string[] } {
  const seen = new Map<string, number>();
  const keys: string[] = [];
  return {
    keys,
    async limit({ key }) {
      keys.push(key);
      const n = (seen.get(key) ?? 0) + 1;
      seen.set(key, n);
      return { success: n <= limit };
    },
  };
}

// ---- Nothing is written past a ceiling --------------------------------------

describe("daily ceilings: the counter upsert writes nothing past its ceiling (real SQLite)", () => {
  it("returns no row and changes nothing once the count reaches the ceiling", async () => {
    const { d1, changes, count } = await sqliteEnv();
    expect(await incrementUnderCeiling(d1.db, DAY, "page_view", 2)).toBe(1);
    expect(await incrementUnderCeiling(d1.db, DAY, "page_view", 2)).toBe(2);
    const before = changes();
    expect(await incrementUnderCeiling(d1.db, DAY, "page_view", 2)).toBeNull();
    expect(await incrementUnderCeiling(d1.db, DAY, "page_view", 2)).toBeNull();
    expect(changes()).toBe(before);
    expect(count("page_view")).toBe(2);
    expect(COUNT_UNDER_CEILING_SQL).toMatch(/DO UPDATE SET count = count \+ 1 WHERE event_counts\.count < \? RETURNING count/);
  });

  it("/e past EVENT_DAILY_CEILING: 204 and no write", async () => {
    const { env, changes, count } = await sqliteEnv({ EVENT_DAILY_CEILING: "1" });
    expect((await handleEvent(post("/e", { name: "page_view" }), env)).status).toBe(202);
    const before = changes();
    expect((await handleEvent(post("/e", { name: "page_view" }), env)).status).toBe(204);
    expect(changes()).toBe(before);
    expect(count("page_view")).toBe(1);
  });

  it("/feedback past FEEDBACK_DAILY_CEILING: 429, nothing stored, nothing written", async () => {
    const { env, changes, d1 } = await sqliteEnv({ FEEDBACK_DAILY_CEILING: "2" });
    expect((await handleFeedback(post("/feedback", { text: "one", page: "/" }), env)).status).toBe(202);
    expect((await handleFeedback(post("/feedback", { text: "two", page: "/" }), env)).status).toBe(202);
    const before = changes();
    const third = await handleFeedback(post("/feedback", { text: "three", page: "/" }), env);
    expect(third.status).toBe(429);
    expect(await third.json()).toEqual({ error: "daily_ceiling_reached" });
    expect(changes()).toBe(before);
    expect(d1.query("SELECT text FROM feedback")).toHaveLength(2);
  });

  it("purges feedback older than 90 days before every insert, so the table stays bounded without /e", async () => {
    const { env, d1 } = await sqliteEnv();
    d1.query("INSERT INTO feedback (text, page, ts) VALUES ('old', '/', ?) RETURNING id", Date.now() - 91 * 86_400_000);
    expect((await handleFeedback(post("/feedback", { text: "new" }), env)).status).toBe(202);
    expect(d1.query<{ text: string }>("SELECT text FROM feedback").map((r) => r.text)).toEqual(["new"]);
  });
});

// ---- Feedback retention: 90 days on days the site is used; idle backlogs clear ----

describe("feedback retention under a burst at the ceiling (real SQLite, simulated days)", () => {
  it("with a visit every day, no feedback is ever older than 90 days plus less than one day", async () => {
    const days = await simulateRetention({ visitOn: () => true, lastDay: 100 });
    expect(Math.max(...days.map((d) => d.oldestAgeDays))).toBeLessThan(91);
  });

  for (const scenario of IDLE_SCENARIOS) {
    it(`${scenario.name}: deletion falls behind, then catches up once visits are daily`, async () => {
      const r = await runIdleScenario(scenario);
      // It fell behind: expired rows were waiting when daily visits resumed.
      expect(r.backlog).toBeGreaterThan(0);
      expect(r.days[scenario.dailyFrom - 1].oldestAgeDays).toBeGreaterThan(91);
      // Catch-up: each visited day removes at least a ceiling's worth, or all of it.
      for (let day = scenario.dailyFrom; day < r.days.length; day++) {
        const before = r.days[day - 1].expired;
        expect(r.days[day].expired, `day ${day}`).toBeLessThanOrEqual(Math.max(0, before - 100));
      }
      // ...and reaches zero, after which the daily guarantee holds again.
      expect(r.clearedWithinVisitedDays).toBeLessThan(Infinity);
      for (const d of r.days.slice(scenario.dailyFrom + r.clearedWithinVisitedDays)) expect(d.oldestAgeDays, `day ${d.day}`).toBeLessThan(91);
    }, 120_000);
  }
});

// ---- This product's share of the account's D1 writes -------------------------

describe("the account's D1 writes: every ceiling together stays within this product's stated share", () => {
  const budget = parseYaml(readFileSync(path.join(root, "budget.yaml"), "utf8")) as {
    quotas: { name: string; ceiling: number; worst_case_rows?: number; worst_case_max_share?: number }[];
  };
  const row = budget.quotas.find((q) => q.name === "d1_rows_written_per_day")!;
  const fromWrangler = () => {
    const vars = wranglerConfig().vars as Record<string, string>;
    return worstCaseDailyWrites({ event: Number(vars.EVENT_DAILY_CEILING), feedback: Number(vars.FEEDBACK_DAILY_CEILING) });
  };

  it("budget.yaml states the worst case exactly as wrangler.jsonc's ceilings give it", () => {
    const { total, lines } = fromWrangler();
    expect(lines.every((l) => Number.isFinite(l.rows) && l.rows > 0)).toBe(true);
    expect(row.ceiling).toBe(ACCOUNT_D1_WRITES_PER_DAY);
    expect(row.worst_case_rows).toBe(total);
  });

  it("the worst case is at most budget.yaml's share of the account, and that share is small", () => {
    const { total } = fromWrangler();
    expect(row.worst_case_max_share).toBeGreaterThan(0);
    expect(row.worst_case_max_share).toBeLessThanOrEqual(0.15);
    expect(total).toBeLessThanOrEqual(row.worst_case_max_share! * ACCOUNT_D1_WRITES_PER_DAY);
  });

  it("the old 50,000-per-name ceiling would not fit (the test above bites)", () => {
    expect(worstCaseDailyWrites({ event: 50_000, feedback: 100 }).total).toBeGreaterThan(row.worst_case_max_share! * ACCOUNT_D1_WRITES_PER_DAY);
  });

  it("each counted request writes no more rows than the budget assumes (real SQLite; row changes)", async () => {
    const { env, changes, d1 } = await sqliteEnv();
    const measure = async (fn: () => Promise<unknown>) => {
      const before = changes();
      await fn();
      return changes() - before;
    };
    for (let i = 0; i < 30; i++) d1.query("INSERT INTO feedback (text, page, ts) VALUES ('old', '/', ?) RETURNING id", i);
    // Feedback with more than a purge batch waiting: counter + 10 deletes + insert.
    expect(await measure(() => handleFeedback(post("/feedback", { text: "hi" }), env))).toBeLessThanOrEqual(1 + 10 + 1);
    // The first /e of the day: counter + one purge batch of at most 2 x the feedback ceiling (200).
    expect(await measure(() => handleEvent(post("/e", { name: CLIENT_EVENTS[0] }), env))).toBeLessThanOrEqual(1 + 200);
    // A later /e: the counter only.
    expect(await measure(() => handleEvent(post("/e", { name: CLIENT_EVENTS[0] }), env))).toBe(1);
  });
});

// ---- Per-client rate limit -----------------------------------------------------

describe("per-client rate limit (Workers Rate Limiting binding)", () => {
  it("every request that reaches the Worker counts against RL_API", () => {
    for (const [m, p] of [["POST", "/e"], ["POST", "/feedback"], ["GET", "/healthz"], ["GET", "/api/x"], ["GET", "/no-such-path"]]) {
      expect(limiterFor(m, p)).toBe("RL_API");
    }
  });

  it("refuses a client over its limit with 429 and Retry-After, keyed on CF-Connecting-IP, and counts clients apart", async () => {
    const RL_API = fakeLimiter(1);
    const { env, d1 } = await sqliteEnv({ RL_API });
    const ip = (a: string) => ({ "cf-connecting-ip": a });
    expect((await handle(post("/e", { name: "page_view" }, ip("203.0.113.7")), env)).status).toBe(202);
    const limited = await handle(post("/e", { name: "page_view" }, ip("203.0.113.7")), env);
    expect(limited.status).toBe(429);
    expect(limited.headers.get("retry-after")).toBe("10");
    expect(await limited.json()).toEqual({ error: "rate_limited" });
    expect((await handle(post("/e", { name: "page_view" }, ip("198.51.100.2")), env)).status).toBe(202);
    expect(RL_API.keys).toEqual(["203.0.113.7", "203.0.113.7", "198.51.100.2"]);
    // The IP never reaches D1.
    const dump = JSON.stringify([d1.query("SELECT * FROM event_counts"), d1.query("SELECT * FROM feedback")]);
    expect(dump).not.toContain("203.0.113");
    expect(dump).not.toContain("198.51.100");
  });

  it("limits every Worker path: /e, /feedback, /healthz and unmatched paths", async () => {
    const env = mockEnv({ RL_API: fakeLimiter(0) });
    expect((await handle(post("/e", { name: "page_view" }), env)).status).toBe(429);
    expect((await handle(post("/feedback", { text: "x" }), env)).status).toBe(429);
    expect((await handle(get("/healthz"), env)).status).toBe(429);
    expect((await handle(get("/no-such-path"), env)).status).toBe(429);
  });

  it("fails open when the binding is missing or throws, and counts the failure as rate_limiter_error (capped, no address)", async () => {
    expect((await handle(post("/e", { name: "page_view" }), mockEnv())).status).toBe(202);
    const broken: RateLimiter = { limit: async () => { throw new Error("binding down"); } };
    const { env, count, d1 } = await sqliteEnv({ RL_API: broken });
    for (let i = 0; i < RATE_LIMITER_ERROR_DAILY_CEILING + 5; i++) {
      expect((await handle(post("/e", { name: "page_view" }, { "cf-connecting-ip": "203.0.113.9" }), env)).status).toBe(202);
    }
    expect(count("rate_limiter_error")).toBe(RATE_LIMITER_ERROR_DAILY_CEILING);
    expect(JSON.stringify(d1.query("SELECT * FROM event_counts"))).not.toContain("203.0.113.9");
  });

  it("wrangler.jsonc declares RL_API with an allowed period and a namespace id /brief assigns", () => {
    const rl = (wranglerConfig().ratelimits as { name: string; namespace_id: string; simple: { limit: number; period: number } }[]).find((r) => r.name === "RL_API");
    expect(rl).toBeDefined();
    expect([10, 60]).toContain(rl!.simple.period);
    expect(rl!.simple.limit).toBe(20);
    expect(rl!.namespace_id).toMatch(/^(\d+|__RL_NAMESPACE_ID__)$/);
  });
});

describe("rate-limit keys: IPv4 whole, IPv6 by its /64", () => {
  it("normalizes IPv6 compression and keys on the first four hextets", () => {
    expect(clientKey("2001:db8::1")).toBe("2001:db8:0:0::/64");
    expect(clientKey("2001:DB8:0:0:8:800:200C:417A")).toBe("2001:db8:0:0::/64");
    expect(clientKey("2001:db8:aaaa:bbbb::1")).toBe(clientKey("2001:db8:aaaa:bbbb:ffff:ffff:ffff:ffff"));
    expect(clientKey("2001:db8:aaaa:bbbc::1")).not.toBe(clientKey("2001:db8:aaaa:bbbb::1"));
    expect(clientKey("fe80::1%eth0")).toBe("fe80:0:0:0::/64");
  });

  it("keys IPv4 and IPv4-mapped IPv6 on the full IPv4 address", () => {
    expect(clientKey("203.0.113.7")).toBe("203.0.113.7");
    expect(clientKey("::ffff:203.0.113.7")).toBe("203.0.113.7");
    expect(clientKey("::FFFF:cb00:7107")).toBe("203.0.113.7");
    expect(clientKey(null)).toBe("no-ip");
  });

  it("the Worker hands the binding the /64, never the full IPv6 address", async () => {
    const RL_API = fakeLimiter(5);
    await handle(post("/e", { name: "page_view" }, { "cf-connecting-ip": "2001:db8:1:2:3:4:5:6" }), mockEnv({ RL_API }));
    expect(RL_API.keys).toEqual(["2001:db8:1:2::/64"]);
  });
});

// ---- Cross-site simple POSTs ---------------------------------------------------

describe("POSTs: JSON only, and never from another site", () => {
  it("refuses a non-JSON body with 415 (text/plain, form posts, none)", async () => {
    for (const type of ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x"]) {
      expect((await handle(post("/e", { name: "page_view" }, { "content-type": type }), mockEnv())).status, type).toBe(415);
    }
    const none = new Request(`${ORIGIN}/feedback`, { method: "POST", body: new Uint8Array([123, 125]) });
    expect((await handle(none, mockEnv())).status).toBe(415);
    expect((await handle(post("/e", { name: "page_view" }, { "content-type": "application/json; charset=utf-8" }), mockEnv())).status).toBe(202);
  });

  it("refuses Sec-Fetch-Site cross-site or same-site, and an Origin that is not this site", async () => {
    for (const headers of [
      { "sec-fetch-site": "cross-site" },
      { "sec-fetch-site": "same-site" },
      { origin: "https://evil.example" },
      { origin: "https://other.product.example" },
      { origin: "null" },
    ]) {
      expect((await handle(post("/e", { name: "page_view" }, headers), mockEnv())).status, JSON.stringify(headers)).toBe(403);
    }
  });

  it("accepts this site's own pages, trusts Sec-Fetch-Site: same-origin behind a rewritten dev URL, and allows header-less tools", async () => {
    expect((await handle(post("/e", { name: "page_view" }, { origin: ORIGIN, "sec-fetch-site": "same-origin" }), mockEnv())).status).toBe(202);
    expect((await handle(post("/e", { name: "page_view" }, { origin: "http://127.0.0.1:8787", "sec-fetch-site": "same-origin" }), mockEnv())).status).toBe(202);
    expect((await handle(post("/e", { name: "page_view" }), mockEnv())).status).toBe(202);
  });

  it("the page sends /e and /feedback as fetch with application/json, never sendBeacon", () => {
    const src = readFileSync(path.join(root, "web", "src", "main.ts"), "utf8");
    expect(src).not.toMatch(/navigator\.sendBeacon\(/);
    const posts = [...src.matchAll(/method: "POST",\s*headers: \{([^}]*)\}/g)];
    expect(posts.length).toBeGreaterThanOrEqual(2);
    for (const m of posts) expect(m[1]).toContain('"content-type": "application/json"');
  });
});

// ---- Security headers on every response ----------------------------------------

describe("security headers", () => {
  function expectBaseHeaders(res: Response, label: string) {
    expect(res.headers.get("x-frame-options"), label).toBe("DENY");
    expect(res.headers.get("x-content-type-options"), label).toBe("nosniff");
    expect(res.headers.get("referrer-policy"), label).toBe("no-referrer");
    expect(res.headers.get("content-security-policy") ?? "", label).toContain("frame-ancestors 'none'");
  }

  it("every Worker response carries them: JSON, errors, 415, 403, 429 and the static fallthrough", async () => {
    const cases: [string, Request, Env][] = [
      ["healthz", get("/healthz"), mockEnv()],
      ["event", post("/e", { name: "page_view" }), mockEnv()],
      ["400", post("/e", { name: "nope" }), mockEnv()],
      ["415", post("/e", "x", { "content-type": "text/plain" }), mockEnv()],
      ["403", post("/e", { name: "page_view" }, { origin: "https://evil.example" }), mockEnv()],
      ["429", post("/e", { name: "page_view" }), mockEnv({ RL_API: fakeLimiter(0) })],
      ["fallthrough", get("/nothing-here"), mockEnv()],
    ];
    for (const [label, req, env] of cases) expectBaseHeaders(await handle(req, env), label);
  });

  it("the API gets default-src 'none'; a page from the fallthrough gets the page policy", async () => {
    expect((await handle(get("/healthz"), mockEnv())).headers.get("content-security-policy")).toBe(API_CSP);
    const env = mockEnv({ ASSETS: createMockAssets({ "page.html": "<!doctype html>" }) });
    expect((await handle(get("/page.html"), env)).headers.get("content-security-policy")).toBe(PAGE_CSP_HEADER);
  });

  it("dist/_headers gives static assets the same set, with the page policy, and the build writes it", () => {
    const file = headersFile();
    expect(file.split("\n")[0]).toBe("/*");
    expect(file).toContain("  X-Frame-Options: DENY\n");
    expect(file).toContain("  X-Content-Type-Options: nosniff\n");
    expect(file).toContain("  Referrer-Policy: no-referrer\n");
    expect(file).toContain(`  Content-Security-Policy: ${PAGE_CSP_HEADER}\n`);
    expect(readFileSync(path.join(root, "scripts", "build.mjs"), "utf8")).toMatch(/writeFileSync\(path\.join\(distDir, "_headers"\), headersFile\(\)\)/);
    // The gate runs the build, so its CSP check actually blocks a merge.
    expect(readFileSync(path.join(root, "scripts", "gate.mjs"), "utf8")).toMatch(/label: "build", run: \(\) => runNode\("scripts\/build\.mjs"\)/);
  });
});

// ---- wrangler.jsonc ----------------------------------------------------------------

/** Workers Static Assets' run_worker_first glob: `*` matches any run of characters, "/" included. */
function matchesRule(rule: string, pathname: string): boolean {
  const re = new RegExp(`^${rule.split("*").map((p) => p.replace(/[.+?^${}()|[\]\\]/g, "\\$&")).join(".*")}$`);
  return re.test(pathname);
}

describe("wrangler.jsonc", () => {
  it("runs the Worker first only on its own routes, so static assets cost no invocation", () => {
    const rules = wranglerConfig().assets.run_worker_first;
    expect(Array.isArray(rules)).toBe(true);
    const workerFirst = (p: string) => (rules as string[]).some((r) => matchesRule(r, p));
    for (const p of ["/e", "/feedback", "/healthz", "/api/anything"]) expect(workerFirst(p), p).toBe(true);
    for (const p of ["/", "/privacy.html", "/privacy", "/assets/index.js", "/assets/inter.woff2", "/build-tag.txt"]) expect(workerFirst(p), p).toBe(false);
  });

  it("keeps Worker logs but turns invocation logs off and redacts query strings", () => {
    const o = wranglerConfig().observability;
    expect(o.logs.invocation_logs).toBe(false);
    expect(o.logs.enabled).toBe(true);
    expect(o.redact_query_string).toBe(true);
    expect(o.traces?.enabled ?? false).toBe(false);
  });

  it("has no AI binding and no LLM cap unless a product adds the LLM add-on (worker/src/llm.ts)", () => {
    const c = wranglerConfig();
    let hasLlm = true;
    try {
      readFileSync(path.join(root, "worker", "src", "llm.ts"));
    } catch {
      hasLlm = false;
    }
    if (!hasLlm) {
      expect(c.ai).toBeUndefined();
      expect(JSON.stringify(c)).not.toMatch(/LLM/);
    }
  });
});
