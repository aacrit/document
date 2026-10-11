// The contract's media checks: the served film and poster are the bytes the
// film's sources.json records, and the recorded web encode runs as long as
// the film within a frame (scripts/contract.mjs sha256_matches, duration_matches).
import { createHash } from "node:crypto";
import { createServer, type Server } from "node:http";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parse as parseYaml } from "yaml";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { loadContract, runContract, whenDeclaredProblem } from "../scripts/contract.mjs";

const FILM = Buffer.from("not really a film, but bytes");
const POSTER = Buffer.from("not really a jpeg");
const TRAILER = Buffer.from("not really a trailer");
const sha = (b: Buffer) => createHash("sha256").update(b).digest("hex");

let sources: Record<string, unknown> = {};
let server: Server;
let base = "";

beforeAll(async () => {
  server = createServer((req, res) => {
    if (req.url === "/m/sources.json") {
      res.writeHead(200, { "content-type": "application/json" });
      return res.end(JSON.stringify(sources));
    }
    const ranged = req.url === "/m/film.mp4" ? FILM : req.url === "/m/trailer.mp4" ? TRAILER : null;
    if (ranged) {
      // Byte ranges as R2 serves them: bytes=a-b and bytes=-n.
      const m = /^bytes=(\d*)-(\d*)$/.exec(String(req.headers.range ?? ""));
      if (m) {
        const start = m[1] ? Number(m[1]) : ranged.length - Number(m[2]);
        const end = m[1] && m[2] ? Number(m[2]) : ranged.length - 1;
        res.writeHead(206, { "content-range": `bytes ${start}-${end}/${ranged.length}`, "content-length": end - start + 1 });
        return res.end(ranged.subarray(start, end + 1));
      }
      res.writeHead(200, { "content-length": ranged.length });
      return res.end(ranged);
    }
    if (req.url === "/m/poster.jpg") return res.end(POSTER);
    res.writeHead(404);
    res.end();
  });
  await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
  const a = server.address();
  base = `http://127.0.0.1:${typeof a === "object" && a ? a.port : 0}`;
});
afterAll(() => server.close());

const checks = [
  { name: "film", type: "sha256_matches", path: "/m/film.mp4", sources: "/m/sources.json", field: "web.film_sha256" },
  { name: "duration", type: "sources_duration_consistent", path: "/m/sources.json", sources: "/m/sources.json", field: "web.film_duration_s" },
  { name: "poster", type: "sha256_matches", path: "/m/poster.jpg", sources: "/m/sources.json", field: "poster.sha256" },
];
const run = async () => Object.fromEntries((await runContract({ checks }, base)).map((r: { label: string; pass: boolean }) => [r.label, r.pass]));

describe("media checks", () => {
  it("pass when the served bytes and durations are the ones sources.json records", async () => {
    sources = { fps: 24, duration_s: 100, web: { film_sha256: sha(FILM), film_duration_s: 100.03 }, poster: { sha256: sha(POSTER) } };
    expect(await run()).toEqual({ film: true, duration: true, poster: true });
  });

  it("fail on other bytes, a missing record, or an encode more than a frame off", async () => {
    sources = { fps: 24, duration_s: 100, web: { film_sha256: sha(POSTER), film_duration_s: 100.1 }, poster: {} };
    expect(await run()).toEqual({ film: false, duration: false, poster: false });
  });

  it("are in contract.yaml for the pilot, deployed only", () => {
    const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
    const c = parseYaml(readFileSync(path.join(root, "contract.yaml"), "utf8"));
    const media = c.checks.filter((x: { type: string }) => x.type === "sha256_matches" || x.type === "sources_duration_consistent");
    expect(media.map((x: { field: string }) => x.field).sort()).toEqual(["poster.sha256", "trailer.sha256", "web.film_duration_s", "web.film_sha256"]);
    // The trailer is optional: checked only when sources.json declares one, never required by status alone.
    expect(media.find((x: { field: string }) => x.field === "trailer.sha256").when_declared).toBe("trailer");
    // Undeclared, the trailer path must answer 404: no stale trailer stays public.
    expect(media.find((x: { field: string }) => x.field === "trailer.sha256").undeclared_status).toBe(404);
    expect(c.checks.some((x: { type: string; path?: string }) => x.type === "status" && String(x.path).endsWith("trailer.mp4"))).toBe(false);
    for (const x of media) expect(x.requires).toBe("deployed");
    // The film is checked by two byte ranges, never downloaded whole by the scheduled run.
    expect(media.find((x: { field: string }) => x.field === "web.film_sha256").max_bytes).toBe(1048576);
  });

  it("with max_bytes, compare a large file by size and its first and last bytes, via byte ranges", async () => {
    const n = 8;
    const edge = (b: Buffer) => ({ film_sha256_size: b.length, film_sha256_head: sha(b.subarray(0, n)), film_sha256_tail: sha(b.subarray(b.length - n)) });
    const ranged = [{ name: "film", type: "sha256_matches", path: "/m/film.mp4", sources: "/m/sources.json", field: "web.film_sha256", max_bytes: n }];
    sources = { fps: 24, duration_s: 100, web: { film_sha256: "not-checked-this-way", ...edge(FILM) } };
    const ok = await runContract({ checks: ranged }, base);
    expect(ok[0].pass, ok[0].detail).toBe(true);
    sources = { fps: 24, duration_s: 100, web: { film_sha256: sha(FILM), ...edge(POSTER) } };
    expect((await runContract({ checks: ranged }, base))[0].pass).toBe(false);
  });

  it("check a trailer only when sources.json declares one: n/a without, its bytes with", async () => {
    const trailer = [{ name: "trailer", type: "sha256_matches", path: "/m/trailer.mp4", sources: "/m/sources.json", field: "trailer.sha256", when_declared: "trailer" }];
    sources = { fps: 24, duration_s: 100 };
    const none = (await runContract({ checks: trailer }, base))[0];
    expect([none.pass, none.undeclared]).toEqual([true, true]);
    sources = { fps: 24, duration_s: 100, trailer: { sha256: sha(TRAILER) } };
    const ok = (await runContract({ checks: trailer }, base))[0];
    expect([ok.pass, ok.undeclared]).toEqual([true, undefined]);
    sources = { fps: 24, duration_s: 100, trailer: { sha256: sha(FILM) } };
    expect((await runContract({ checks: trailer }, base))[0].pass).toBe(false);
    // Declared but not served fails; a sources.json that cannot be read fails rather than passes as undeclared.
    const missing = [{ ...trailer[0], path: "/m/nothing.mp4" }];
    sources = { fps: 24, duration_s: 100, trailer: { sha256: sha(TRAILER) } };
    expect((await runContract({ checks: missing }, base))[0].pass).toBe(false);
    const unread = [{ ...trailer[0], sources: "/m/none.json" }];
    expect((await runContract({ checks: unread }, base))[0].pass).toBe(false);
  });

  it("with undeclared_status, an undeclared trailer must not be served: a 404 passes, a stale file fails", async () => {
    sources = { fps: 24, duration_s: 100 };
    const gone = [{ name: "t", type: "sha256_matches", path: "/m/nothing.mp4", sources: "/m/sources.json", field: "trailer.sha256", when_declared: "trailer", undeclared_status: 404 }];
    const ok = (await runContract({ checks: gone }, base))[0];
    expect([ok.pass, ok.undeclared]).toEqual([true, undefined]);
    const stale = [{ ...gone[0], path: "/m/trailer.mp4" }];
    const bad = (await runContract({ checks: stale }, base))[0];
    expect(bad.pass).toBe(false);
    expect(bad.detail).toMatch(/answered 200, expected 404/);
  });

  it("with max_bytes smaller than the trailer, compare a declared trailer by its size and first and last bytes", async () => {
    const n = 6;
    expect(TRAILER.length).toBeGreaterThan(n);
    const edge = (b: Buffer) => ({ sha256_size: b.length, sha256_head: sha(b.subarray(0, n)), sha256_tail: sha(b.subarray(b.length - n)) });
    const t = [{ name: "t", type: "sha256_matches", path: "/m/trailer.mp4", sources: "/m/sources.json", field: "trailer.sha256", when_declared: "trailer", max_bytes: n }];
    sources = { fps: 24, duration_s: 100, trailer: { sha256: sha(TRAILER), ...edge(TRAILER) } };
    const ok = (await runContract({ checks: t }, base))[0];
    expect(ok.pass, ok.detail).toBe(true);
    sources = { fps: 24, duration_s: 100, trailer: { sha256: sha(TRAILER), ...edge(FILM) } };
    expect((await runContract({ checks: t }, base))[0].pass).toBe(false);
  });

  it("refuse when_declared anywhere but on a hash of the declared record", async () => {
    expect(whenDeclaredProblem({ type: "sha256_matches", field: "trailer.sha256", when_declared: "trailer", sources: "/s" })).toBeNull();
    expect(whenDeclaredProblem({ type: "status", field: "trailer.sha256", when_declared: "trailer", sources: "/s" })).toMatch(/only allowed on sha256_matches/);
    expect(whenDeclaredProblem({ type: "sha256_matches", field: "poster.sha256", when_declared: "trailer", sources: "/s" })).toMatch(/not inside/);
    expect(whenDeclaredProblem({ type: "sha256_matches", field: "trailers.sha256", when_declared: "trailer", sources: "/s" })).toMatch(/not inside/);
    const bad = [{ name: "b", type: "status", path: "/m/trailer.mp4", expect: 200, sources: "/m/sources.json", field: "trailer.sha256", when_declared: "trailer" }];
    sources = { fps: 24, duration_s: 100, trailer: { sha256: sha(TRAILER) } };
    const r = (await runContract({ checks: bad }, base))[0];
    expect([r.pass, r.detail]).toEqual([false, "contract error: when_declared is only allowed on sha256_matches, not status"]);
    const dir = mkdtempSync(path.join(os.tmpdir(), "contract-"));
    const file = path.join(dir, "c.yaml");
    writeFileSync(file, "checks:\n  - name: b\n    type: status\n    path: /x\n    when_declared: trailer\n    field: trailer.sha256\n    sources: /s\n");
    expect(() => loadContract(file)).toThrow(/when_declared is only allowed/);
  });
});
