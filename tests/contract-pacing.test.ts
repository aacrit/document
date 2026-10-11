// The contract runner stays under the zone's rate rule (30 requests per 10 s
// per IP) and tells the zone's block apart from a product failure (issue #12).
// Everything runs on a fake clock and a fake network: sleeping advances time.
import { describe, expect, it } from "vitest";
import { BLOCK_WAIT_MS, PACE_LIMIT, PACE_WINDOW_MS, ZONE_BLOCKED, createPacer, runContract, zoneBlock } from "../scripts/contract.mjs";

function clock() {
  let t = 0;
  return {
    now: () => t,
    sleep: async (ms: number) => {
      t += Math.max(0, ms);
    },
  };
}

/** The most requests any window of `windowMs` holds. */
function busiestWindow(times: number[], windowMs = PACE_WINDOW_MS): number {
  const sorted = [...times].sort((a, b) => a - b);
  let best = 0;
  for (let i = 0, j = 0; i < sorted.length; i++) {
    while (sorted[i] - sorted[j] >= windowMs) j++;
    best = Math.max(best, i - j + 1);
  }
  return best;
}

const PROD = "https://document.voidvision.org";
const BURST = "https://document.aacrit.workers.dev";
const BLOCK_PAGE = '<!DOCTYPE html><html><head><title>Attention Required! | Cloudflare</title></head><body><div class="cf-error-details"><h1>Error 1015</h1><p>You are being rate limited</p></div></body></html>';

function fakeNet(c: ReturnType<typeof clock>, answer: (url: URL, n: number) => Response) {
  const log: { host: string; path: string; t: number; range?: string }[] = [];
  const counts = new Map<string, number>();
  const fetch = async (input: string | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const key = url.host + url.pathname;
    counts.set(key, (counts.get(key) ?? 0) + 1);
    const headers = new Headers(init?.headers);
    log.push({ host: url.host, path: url.pathname, t: c.now(), range: headers.get("range") ?? undefined });
    return answer(url, counts.get(key)!);
  };
  return { fetch, log };
}

const ok = (url: URL) =>
  url.pathname === "/healthz"
    ? new Response(JSON.stringify({ ok: true, build: "release/x" }), { status: 200, headers: { "content-type": "application/json" } })
    : new Response("<html>void document</html>", { status: 200, headers: { "x-frame-options": "DENY", "content-type": "text/html" } });

describe("the pacer", () => {
  it(`lets at most ${PACE_LIMIT} requests to one host into any ${PACE_WINDOW_MS / 1000} s, and waits rather than drops`, async () => {
    const c = clock();
    const pacer = createPacer({ now: c.now, sleep: c.sleep });
    const times: number[] = [];
    for (let i = 0; i < 45; i++) {
      await pacer.take("document.voidvision.org");
      times.push(c.now());
    }
    expect(times).toHaveLength(45);
    expect(busiestWindow(times)).toBe(PACE_LIMIT);
    // 45 requests at 20 per 10 s: the 41st waits for the second window to roll.
    expect(c.now()).toBe(2 * PACE_WINDOW_MS);
  });

  it("counts each host on its own, and paces only the hosts it is told to", async () => {
    const c = clock();
    const pacer = createPacer({ now: c.now, sleep: c.sleep, pace: (h) => h !== "localhost:8787" });
    for (let i = 0; i < PACE_LIMIT; i++) await pacer.take("a.example");
    for (let i = 0; i < PACE_LIMIT; i++) await pacer.take("b.example");
    for (let i = 0; i < 100; i++) await pacer.take("localhost:8787");
    expect(c.now()).toBe(0);
    await pacer.take("a.example");
    expect(c.now()).toBe(PACE_WINDOW_MS);
  });
});

describe("a full contract run against the production host", () => {
  // 39 checks as the real contract has them: pages, headers, media byte ranges, and the burst last.
  const checks = [
    ...Array.from({ length: 30 }, (_, i) => ({ name: `page ${i}`, type: "status", path: `/p${i}`, expect: 200 })),
    ...Array.from({ length: 4 }, (_, i) => ({ name: `header ${i}`, type: "header", path: "/", header: "x-frame-options", expect: "DENY" })),
    { name: "healthz", type: "json", path: "/healthz", field: "ok", expect: true },
    ...Array.from({ length: 3 }, (_, i) => ({ name: `forbidden ${i}`, type: "forbidden", path: "/", strings: ["TODO"] })),
    { name: "burst", type: "burst", path: "/healthz", count: 40, concurrency: 20, expect_status: 429, expect_error: "rate_limited", pause_before_seconds: 11 },
  ];
  const contract = { burst_zone: "voidvision.org", burst_host: BURST, checks };

  it("never sends more than the limit to production in any window; byte ranges count; the burst is exempt and goes to burst_host", async () => {
    const c = clock();
    const net = fakeNet(c, (url, n) => {
      if (url.host === "document.aacrit.workers.dev" && url.pathname === "/healthz" && n > 1) {
        return new Response(JSON.stringify({ error: "rate_limited" }), { status: 429, headers: { "content-type": "application/json" } });
      }
      return ok(url);
    });
    const results = await runContract(contract, PROD, { fetch: net.fetch, sleep: c.sleep, pacer: createPacer({ now: c.now, sleep: c.sleep }) });
    expect(results.every((r: { pass: boolean }) => r.pass), JSON.stringify(results.filter((r: { pass: boolean }) => !r.pass))).toBe(true);
    const prod = net.log.filter((x) => x.host === "document.voidvision.org").map((x) => x.t);
    expect(prod.length).toBeGreaterThan(PACE_LIMIT);
    expect(busiestWindow(prod)).toBeLessThanOrEqual(PACE_LIMIT);
    // The burst's own requests went out back to back, unpaced, to the workers.dev host.
    const burst = net.log.filter((x) => x.host === "document.aacrit.workers.dev" && x.path === "/healthz").map((x) => x.t);
    expect(burst.length).toBeGreaterThan(PACE_LIMIT);
  });

  it("byte-range requests are paced like any other", async () => {
    const c = clock();
    const big = new Uint8Array(64);
    const net = fakeNet(c, (url) => {
      if (url.pathname === "/m/sources.json") return new Response(JSON.stringify({ web: { film_sha256: "x", film_sha256_size: 64, film_sha256_head: "h", film_sha256_tail: "t" } }));
      return new Response(big, { status: 200, headers: { "content-length": "64" } });
    });
    const film = { name: "film", type: "sha256_matches", path: "/m/film.mp4", sources: "/m/sources.json", field: "web.film_sha256", max_bytes: 8 };
    // Answering 200 to a range fails the check, but every one of its requests is still counted and paced.
    await runContract({ checks: Array.from({ length: 8 }, () => film) }, PROD, { fetch: net.fetch, sleep: c.sleep, pacer: createPacer({ now: c.now, sleep: c.sleep }) });
    expect(net.log.some((x) => x.range)).toBe(true);
    expect(busiestWindow(net.log.map((x) => x.t))).toBeLessThanOrEqual(PACE_LIMIT);
  });
});

describe("the zone's block is reported as the zone's", () => {
  it("knows Cloudflare's block page from the Worker's own refusal", async () => {
    expect(await zoneBlock(new Response(BLOCK_PAGE, { status: 429 }))).toBe("a Cloudflare block page");
    expect(await zoneBlock(new Response(BLOCK_PAGE, { status: 403 }))).toBe("a Cloudflare block page");
    expect(await zoneBlock(new Response("", { status: 429 }))).toBe("429 with no Worker body");
    expect(await zoneBlock(new Response(JSON.stringify({ error: "rate_limited" }), { status: 429 }))).toBeNull();
    expect(await zoneBlock(new Response("forbidden by the app", { status: 403 }))).toBeNull();
    expect(await zoneBlock(new Response("ok", { status: 200 }))).toBeNull();
  });

  it("waits out the window once and passes when the retry is answered by the product", async () => {
    const c = clock();
    const net = fakeNet(c, (url, n) => (n === 1 ? new Response(BLOCK_PAGE, { status: 429, headers: { "x-frame-options": "SAMEORIGIN", "content-type": "text/html" } }) : ok(url)));
    const before = c.now();
    const [r] = await runContract({ checks: [{ name: "frame", type: "header", path: "/", header: "x-frame-options", expect: "DENY" }] }, PROD, {
      fetch: net.fetch,
      sleep: c.sleep,
      pacer: createPacer({ now: c.now, sleep: c.sleep }),
    });
    expect(r.pass).toBe(true);
    expect(c.now() - before).toBe(BLOCK_WAIT_MS);
    expect(net.log).toHaveLength(2);
  });

  it("blocked twice, fails as rate-limited by the zone, never as the product's headers", async () => {
    const c = clock();
    const net = fakeNet(c, () => new Response(BLOCK_PAGE, { status: 429, headers: { "x-frame-options": "SAMEORIGIN", "content-type": "text/html" } }));
    const [r] = await runContract({ checks: [{ name: "frame", type: "header", path: "/", header: "x-frame-options", expect: "DENY" }] }, PROD, {
      fetch: net.fetch,
      sleep: c.sleep,
      pacer: createPacer({ now: c.now, sleep: c.sleep }),
    });
    expect(r.pass).toBe(false);
    expect(r.zoneBlocked).toBe(true);
    expect(r.detail).toContain(ZONE_BLOCKED);
    expect(r.detail).not.toMatch(/expected "DENY"/);
    expect(net.log).toHaveLength(2);
  });

  it("a block met while reading a sources.json for a declared-record check is the zone's too", async () => {
    const c = clock();
    const net = fakeNet(c, () => new Response(BLOCK_PAGE, { status: 429 }));
    const [r] = await runContract(
      { checks: [{ name: "trailer", type: "sha256_matches", path: "/m/trailer.mp4", sources: "/m/sources.json", field: "trailer.sha256", when_declared: "trailer", undeclared_status: 404 }] },
      PROD,
      { fetch: net.fetch, sleep: c.sleep, pacer: createPacer({ now: c.now, sleep: c.sleep }) },
    );
    expect([r.pass, r.zoneBlocked]).toEqual([false, true]);
  });
});
