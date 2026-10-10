// The privacy page states what the product actually does (doctrine L-26).
// Each claim checked here is paired with the code or config that makes it
// true, so changing one without the other fails. When a product adds a
// surface that collects or sends anything, it adds the claim to
// web/privacy.html and its pairing here in the same change.

import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { CSP } from "../scripts/lib/csp.mjs";
import { RETENTION_DAYS } from "../worker/src/config";
import { IDLE_SCENARIOS, runIdleScenario } from "./helpers/retention-sim";
import { parse as parseYaml } from "yaml";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (f: string) => readFileSync(path.join(root, f), "utf8");
const text = read("web/privacy.html").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
const workerFiles = () => readdirSync(path.join(root, "worker/src")).filter((f) => f.endsWith(".ts"));

describe("web/privacy.html, claim by claim", () => {
  it("no anonymous id, cookie or local storage: no client or Worker code sets one", () => {
    expect(text).toContain("There is no anonymous id, no cookie, no local storage, and no third-party analytics script");
    for (const dir of ["web/src", "worker/src"]) {
      for (const f of readdirSync(path.join(root, dir)).filter((x) => x.endsWith(".ts"))) {
        expect(read(`${dir}/${f}`), f).not.toMatch(/\b(localStorage|sessionStorage|indexedDB)\.|document\.cookie|set-cookie/i);
      }
    }
    for (const page of readdirSync(path.join(root, "web")).filter((p) => p.endsWith(".html"))) {
      expect(read(`web/${page}`), page).not.toMatch(/googletagmanager|google-analytics|cloudflareinsights|plausible|posthog/i);
    }
  });

  it("counts as daily totals: /e takes exactly one field and only increments a day count", () => {
    expect(text).toContain("counts how many times a small set of named events happen each day");
    expect(read("worker/src/index.ts")).toContain('keys.length !== 1 || keys[0] !== "name"');
    expect(read("migrations/0001_events.sql")).toMatch(/CREATE TABLE IF NOT EXISTS event_counts \(\s*day TEXT NOT NULL,\s*name TEXT NOT NULL,\s*count INTEGER/);
  });

  it("feedback is the text, the page and the arrival time: the feedback table holds exactly that", () => {
    expect(text).toContain("the server stores them with the time the message arrived");
    const cols = read("migrations/0001_events.sql").match(/CREATE TABLE IF NOT EXISTS feedback \(([\s\S]*?)\);/)![1];
    expect(cols.split(",").map((c) => c.trim().split(/\s+/)[0])).toEqual(["id", "text", "page", "ts"]);
  });

  it("nothing is loaded from another company: the CSP allows this origin only", () => {
    expect(text).toContain("nothing is loaded from another company");
    expect(CSP).not.toMatch(/https?:/);
  });

  it("the IP is used for the rate limit only, IPv6 by its network part, and only the guard reads it", () => {
    expect(text).toContain("for an IPv6 address, only its network part");
    expect(text).toContain("Cloudflare keeps a short-lived count in memory");
    const guard = read("worker/src/guard.ts");
    expect(guard).toContain('request.headers.get("cf-connecting-ip")');
    expect(guard).toContain("::/64");
    for (const f of workerFiles().filter((x) => x !== "guard.ts")) {
      expect(read(`worker/src/${f}`), f).not.toMatch(/cf-connecting-ip|x-forwarded-for|x-real-ip/i);
    }
  });

  it("per-request logs are off and the product's code logs nothing: wrangler.jsonc, and no console call in the Worker", () => {
    expect(text).toContain("Cloudflare's per-request logs are turned off for this site");
    expect(read("wrangler.jsonc")).toMatch(/"invocation_logs": false/);
    expect(read("wrangler.jsonc")).toMatch(/"redact_query_string": true/);
    for (const f of workerFiles()) expect(read(`worker/src/${f}`), f).not.toMatch(/console\./);
  });

  it("deleted automatically in batches on days the site is used: the daily purge and the purge before each insert both exist", () => {
    const index = read("worker/src/index.ts");
    expect(index).toMatch(/if \(count === 1\) \{\s*await purgeOldFeedback\(env\.DB, now, dailyPurgeLimit\(env\)\);/);
    expect(index).toMatch(/await purgeOldFeedback\(env\.DB, now, FEEDBACK_PURGE_ON_INSERT\);\s*await env\.DB\.prepare\("INSERT INTO feedback/);
  });

  it("the one request log is the WAF's: the page names its threshold and what it records, matching contract.yaml's zone_waf_rule", () => {
    expect(text).toContain("keeps no log of ordinary requests");
    expect(text).toContain("one IP address sends more than 30 requests to voidvision.org sites in 10 seconds, Cloudflare's firewall blocks it for 10 seconds");
    expect(text).toContain("the IP address, the page asked for and the browser's user agent");
    const rule = parseYaml(read("contract.yaml")).zone_waf_rule;
    expect(rule).toMatchObject({ requests: 30, period_seconds: 10, action: "block", mitigation_timeout_seconds: 10 });
    expect(rule.logs_blocked_requests).toEqual(["ip", "path", "user_agent"]);
  });

  it("feedback is deleted after 90 days on days the site is used; after unvisited stretches deletion falls behind and catches up (SQLite simulations)", async () => {
    expect(text).toContain(`Feedback text is kept for ${RETENTION_DAYS} days, then deleted automatically in batches on days the site is used.`);
    expect(text).toContain("If the site goes unvisited for a while, deletion falls behind and catches up once visits resume.");
    expect(text).not.toMatch(/within a day|plus one|as many days/);
    // Paired with the behavior: in every visit pattern the backlog exists
    // (falls behind), then shrinks to zero once visits are daily (catches up).
    for (const scenario of IDLE_SCENARIOS) {
      const r = await runIdleScenario(scenario);
      expect(r.backlog, scenario.name).toBeGreaterThan(0);
      expect(r.clearedWithinVisitedDays, scenario.name).toBeLessThan(Infinity);
    }
  }, 240_000);

  it("the restore window is 7 days: D1 Time Travel on the Workers free plan (30 days is the paid plan)", () => {
    // developers.cloudflare.com/d1/platform/limits: Time Travel is 7 days on
    // Workers Free and 30 on Workers Paid. This product runs on the free tier.
    expect(text).toContain("any moment in the last 7 days");
    expect(text).not.toMatch(/30 days/);
  });
});
