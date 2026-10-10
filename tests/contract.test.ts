import { createServer, type Server } from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { isLocalUrl, loadContract, runContract } from "../scripts/contract.mjs";

let server: Server;
let baseUrl: string;

const GOOD_HOME = `<!doctype html><html><head><meta name="build" content="abc123"></head><body>Demo Product</body></html>`;
const BAD_HOME = `<!doctype html><html><head></head><body>Demo Product TODO fix this</body></html>`;

let currentHome = GOOD_HOME;
let currentFrameHeader = "DENY";

beforeAll(async () => {
  server = createServer((req, res) => {
    if (req.url === "/waf") {
      // A WAF-style block: 429 with Cloudflare's HTML page and a Retry-After.
      res.writeHead(429, { "content-type": "text/html", "retry-after": "10" });
      res.end("<html><title>Error 1015</title>You are being rate limited</html>");
      return;
    }
    if (req.url === "/worker-limited") {
      res.writeHead(429, { "content-type": "application/json", "retry-after": "10" });
      res.end(JSON.stringify({ error: "rate_limited" }));
      return;
    }
    if (req.url === "/healthz") {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ ok: true, build: "abc123" }));
      return;
    }
    res.writeHead(200, { "content-type": "text/html", "x-frame-options": currentFrameHeader });
    res.end(currentHome);
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (address && typeof address === "object") {
    baseUrl = `http://127.0.0.1:${address.port}`;
  } else {
    throw new Error("failed to determine test server address");
  }
});

afterAll(() => {
  server.close();
});

const contract = {
  checks: [
    { name: "status", type: "status", path: "/", expect: 200 },
    { name: "contains", type: "contains", path: "/", text: "Demo Product" },
    { name: "meta", type: "meta", path: "/", meta_name: "build" },
    { name: "healthz status", type: "status", path: "/healthz", expect: 200 },
    { name: "healthz ok", type: "json", path: "/healthz", field: "ok", expect: true },
    { name: "forbidden", type: "forbidden", path: "/", strings: ["undefined", "NaN", "lorem", "TODO"] },
    { name: "header exact", type: "header", path: "/", header: "X-Frame-Options", expect: "DENY" },
    { name: "header contains", type: "header", path: "/", header: "content-type", contains: "text/html" },
  ],
};

describe("contract runner", () => {
  it("passes every check against a healthy page", async () => {
    currentHome = GOOD_HOME;
    const results = await runContract(contract, baseUrl);
    expect(results.filter((r) => !r.pass)).toEqual([]);
  });

  it("fails the forbidden-string check when a placeholder leaks onto the page", async () => {
    currentHome = BAD_HOME;
    const results = await runContract(contract, baseUrl);
    expect(results.find((r) => r.label === "forbidden")?.pass).toBe(false);
    currentHome = GOOD_HOME;
  });

  it("fails a header check when the header is wrong or missing", async () => {
    currentFrameHeader = "SAMEORIGIN";
    const results = await runContract(contract, baseUrl);
    const exact = results.find((r) => r.label === "header exact");
    expect(exact?.pass).toBe(false);
    expect(exact?.detail).toContain('expected "DENY", got "SAMEORIGIN"');
    const missing = await runContract({ checks: [{ name: "m", type: "header", path: "/", header: "referrer-policy", expect: "no-referrer" }] }, baseUrl);
    expect(missing[0].pass).toBe(false);
    currentFrameHeader = "DENY";
  });
});

describe("contract runner: deployed-only burst checks", () => {
  it("skips a requires: deployed check against a local URL, reported as skipped, not failed", async () => {
    const results = await runContract({ checks: [{ name: "burst", type: "burst", path: "/", count: 3, expect_status: 429, requires: "deployed" }] }, baseUrl);
    expect(results[0]).toMatchObject({ pass: true, skipped: true, detail: "skipped: needs deployed runtime" });
  });

  it("isLocalUrl knows local dev hosts from deployed ones", () => {
    expect(isLocalUrl("http://127.0.0.1:8787")).toBe(true);
    expect(isLocalUrl("http://localhost:5173")).toBe(true);
    expect(isLocalUrl("https://product.voidvision.org")).toBe(false);
    expect(isLocalUrl("https://preview.product.workers.dev")).toBe(false);
  });

  it("a WAF-style 429 (HTML 1015 page) does not pass a check that expects the Worker's rate_limited body", async () => {
    const check = { name: "burst", type: "burst", path: "/waf", count: 3, expect_status: 429, expect_error: "rate_limited" };
    const [waf] = await runContract({ checks: [check] }, baseUrl);
    expect(waf.pass).toBe(false);
    expect(waf.detail).toContain('no 429 with {"error":"rate_limited"} in 3 requests');
    const [worker] = await runContract({ checks: [{ ...check, path: "/worker-limited" }] }, baseUrl);
    expect(worker.pass).toBe(true);
  });

  it("a burst check with concurrency sends every request, in waves", async () => {
    const results = await runContract({ checks: [{ name: "burst", type: "burst", path: "/", count: 7, concurrency: 3, expect_status: 429 }] }, baseUrl);
    expect(results[0]!.pass).toBe(false);
    expect(results[0]!.detail).toContain("in 7 requests");
  });

  it("a burst check fails when no request is refused", async () => {
    const results = await runContract({ checks: [{ name: "burst", type: "burst", path: "/", count: 3, expect_status: 429 }] }, baseUrl);
    expect(results[0].pass).toBe(false);
    expect(results[0].detail).toContain("no 429 in 3 requests");
  });

  it("pause_before_seconds waits before the check runs", async () => {
    const started = Date.now();
    await runContract({ checks: [{ name: "p", type: "status", path: "/", expect: 200, pause_before_seconds: 0.2 }] }, baseUrl);
    expect(Date.now() - started).toBeGreaterThanOrEqual(180);
  });

  it("contract.yaml's burst check is deployed-only, waits out the WAF window, and requires the Worker's body", () => {
    const file = fileURLToPath(new URL("../contract.yaml", import.meta.url));
    const burst = loadContract(path.resolve(file)).checks.find((c: { type: string }) => c.type === "burst");
    expect(burst).toMatchObject({ expect_status: 429, expect_error: "rate_limited", requires: "deployed" });
    expect(burst.pause_before_seconds).toBeGreaterThan(10);
    expect(burst.count).toBeGreaterThan(20);
  });
});
