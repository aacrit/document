// The contract's media checks: the served film and poster are the bytes the
// film's sources.json records, and the recorded web encode runs as long as
// the film within a frame (scripts/contract.mjs sha256_matches, duration_matches).
import { createHash } from "node:crypto";
import { createServer, type Server } from "node:http";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parse as parseYaml } from "yaml";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { runContract } from "../scripts/contract.mjs";

const FILM = Buffer.from("not really a film, but bytes");
const POSTER = Buffer.from("not really a jpeg");
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
    if (req.url === "/m/film.mp4") return res.end(FILM);
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
  { name: "duration", type: "duration_matches", path: "/m/sources.json", sources: "/m/sources.json", field: "web.film_duration_s" },
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
    const media = c.checks.filter((x: { type: string }) => x.type === "sha256_matches" || x.type === "duration_matches");
    expect(media.map((x: { field: string }) => x.field).sort()).toEqual(["poster.sha256", "web.film_duration_s", "web.film_sha256"]);
    for (const x of media) expect(x.requires).toBe("deployed");
  });
});
