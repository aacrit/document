// scripts/release-film.mjs: the post-render release runs its steps in order,
// uploads to the film's folder in R2 with --remote and sources.json last, and
// a dry run is plain data that never runs a command.
import { describe, expect, it } from "vitest";
import { BUCKET, MAX_PUT_BYTES, PACKET_ROOT, UPLOAD_ORDER, captionReview, commandLine, uploadsCaptions, gopFrames, rateProblems, videoKbps, webEncodeArgs, dirtyVerdict, driveOf, driveProblems, parseArgs, planRelease, readLedgers, posterSource } from "../scripts/release-film.mjs";
import { mkdtempSync, readFileSync, writeFileSync as wfs, mkdirSync as mkd } from "node:fs";
import { tmpdir } from "node:os";
import { join as pjoin } from "node:path";

type Step = { id: string; label: string; exe?: string; args?: string[]; check?: string; tolerate?: RegExp };

const tools = { python: "py", ffmpeg: "ffmpeg", wrangler: { exe: "node", pre: ["wrangler.js"] }, ledgers: { slug: "partition-of-india", ledger: "L.json", media: "stills" }, poster: "stills/S-020.jpg", captionsReview: "reviewed" };
const plan = (argv: string[], durations = { film: 1205, trailer: 120 }) => planRelease(parseArgs(argv), { ...tools, durations }) as { steps: Step[]; files: string[]; slug: string };

describe("release-film", () => {
  it("runs sources-only, the web encode, the poster and packet, the captions check, the upload and the hashes, in that order", () => {
    const { steps } = plan(["r/master.mp4", "--trailer", "t/master.mp4"]);
    expect(steps.map((s) => s.id)).toEqual(["a", "b", "b", "c", "c", "d", "e", "e", "e", "e", "e", "e", "e", "f"]);
    expect(steps[0].args).toEqual(expect.arrayContaining(["-m", "studio.engine.render", "--sources-only"]));
    expect(steps[1].args).toEqual(expect.arrayContaining(webEncodeArgs(1205)));
    expect(steps[2].args).toEqual(expect.arrayContaining(["-maxrate", `${videoKbps(120)}k`]));
    expect(steps[1].args?.join(" ")).toContain("scale=1280:720");
    expect(steps[4].args).toEqual(expect.arrayContaining(["-m", "studio.engine.publish", "--poster-id", "S-020", "--stills-ledger", "L.json"]));
    // publish reads the screenplay the render used from the film folder, not the render folder (release 2026-10-10: it refused without it)
    const args = steps[4].args ?? [];
    expect(args[args.indexOf("--screenplay") + 1].replace(/\\/g, "/")).toMatch(/\/screenplay\.json$/);
    expect(steps[5].check).toBe("captions");
  });

  it("checks every hash against sources.json before the first put", () => {
    const { steps } = plan(["r/master.mp4", "--trailer", "t/master.mp4"]);
    const hashes = steps.findIndex((s) => s.check === "hashes");
    const firstWrite = steps.findIndex((s) => s.args?.includes("put") || s.args?.includes("delete"));
    expect(hashes).toBeGreaterThan(-1);
    expect(hashes).toBeLessThan(firstWrite);
  });

  it("derives the rate cap from the duration, so the 720p file stays under the put limit with margin", () => {
    for (const d of [60, 600, 1205, 1800, 3600]) {
      const kbps = videoKbps(d);
      const worst = ((kbps * 1000 + 128000) * d) / 8 + 2 * kbps * 1000 / 8;   // the cap's average plus one full VBV buffer
      expect(worst, `${d} s`).toBeLessThan(0.9 * MAX_PUT_BYTES);
    }
    expect(videoKbps(60)).toBe(2500);
    expect(videoKbps(1205)).toBeGreaterThan(1500);
    expect(() => videoKbps(20000)).toThrow(/too long/);
    expect(() => videoKbps(0)).toThrow();
    expect(webEncodeArgs(null).join(" ")).toContain("<derived from duration>");
  });

  it("without --trailer, deletes any earlier trailer before the uploads and tolerates a missing key; with one, deletes nothing", () => {
    const { steps } = plan(["r/master.mp4"]);
    const del = steps.find((s) => s.args?.includes("delete"));
    expect(del?.args).toEqual(expect.arrayContaining([`${BUCKET}/partition-of-india/trailer.mp4`, "--remote"]));
    expect(del?.tolerate?.test("The specified key does not exist.")).toBe(true);
    expect(del?.tolerate?.test("Authentication error")).toBe(false);
    expect(steps.indexOf(del!)).toBeLessThan(steps.findIndex((s) => s.args?.includes("put")));
    expect(plan(["r/master.mp4", "--trailer", "t/master.mp4"]).steps.some((s) => s.args?.includes("delete"))).toBe(false);
    expect(plan(["r/master.mp4", "--no-upload"]).steps.some((s) => s.args?.includes("delete"))).toBe(false);
  });

  it("puts every file into document-media/<slug>/ with --remote, the media first and sources.json last", () => {
    const { steps } = plan(["r/master.mp4", "--trailer", "t/master.mp4"]);
    const puts = steps.filter((s) => s.args?.includes("put"));
    expect(puts.map((s) => s.args?.[s.args.indexOf("put") + 1])).toEqual(UPLOAD_ORDER.map((f: string) => `${BUCKET}/partition-of-india/${f}`));
    for (const p of puts) expect(p.args).toContain("--remote");
    expect(puts[puts.length - 1].label).toBe("upload sources.json");
  });

  it("declares and uploads a trailer only with --trailer", () => {
    const without = plan(["r/master.mp4"]);
    expect(without.files.some((f) => /trailer/.test(f))).toBe(false);
    // Only the delete of an earlier trailer names one: nothing encodes, declares or uploads a trailer.
    expect(without.steps.filter((s) => s.args?.some((a) => /trailer/.test(a))).map((s) => s.args?.[s.args.indexOf("object") + 1])).toEqual(["delete"]);
    const withT = plan(["r/master.mp4", "--trailer", "t/master.mp4"]);
    const publish = withT.steps.find((s) => s.args?.includes("studio.engine.publish"));
    expect(publish?.args?.[publish.args.indexOf("--trailer") + 1]).toMatch(/trailer\.mp4$/);
    expect(withT.files.some((f) => /trailer\.mp4$/.test(f))).toBe(true);
  });

  it("puts the packet under D:/document-media/web-packet/<slug> unless --out says otherwise", () => {
    expect(PACKET_ROOT).toBe("D:/document-media/web-packet");
    const norm = (x: string) => x.split("\\").join("/");
    expect(norm((planRelease(parseArgs(["r/master.mp4"]), tools) as { out: string }).out).endsWith("document-media/web-packet/partition-of-india")).toBe(true);
    expect(norm((planRelease(parseArgs(["r/master.mp4", "--out", "elsewhere/p"]), tools) as { out: string }).out).endsWith("elsewhere/p")).toBe(true);
  });

  it("refuses to write to D: when it is dirty or the query fails, and writes when it is clean", () => {
    expect(dirtyVerdict(0, "Volume - D: is NOT Dirty").ok).toBe(true);
    expect(dirtyVerdict(0, "Volume - D: is Dirty").ok).toBe(false);
    expect(dirtyVerdict(1, "Error:  Access is denied.").ok).toBe(false);
    expect(dirtyVerdict(0, "").ok).toBe(false);
    expect(driveOf("D:/document-media/x", "win32")).toBe("D:");
    expect(driveOf("/tmp/x", "linux")).toBeNull();
    if (process.platform === "win32") {
      const clean = () => ({ status: 0, stdout: "Volume - D: is NOT Dirty" });
      const dirty = () => ({ status: 0, stdout: "Volume - D: is Dirty" });
      const failed = () => ({ status: null, error: new Error("spawn fsutil ENOENT"), stdout: "" });
      expect(driveProblems(["D:/p", "D:/r"], clean)).toEqual([]);
      expect(driveProblems(["D:/p"], dirty)[0]).toMatch(/refusing to write to D:.*dirty/);
      expect(driveProblems(["D:/p"], failed)[0]).toMatch(/refusing to write to D:.*failed/);
      let asked = 0;
      expect(driveProblems(["C:/p"], () => (asked++, dirty()))).toEqual([]);
      expect(asked).toBe(0);
    }
  });

  it("uploads nothing with --no-upload", () => {
    expect(plan(["r/master.mp4", "--no-upload"]).steps.some((s) => s.args?.includes("put"))).toBe(false);
  });

  it("refuses a missing master, an unknown option, and more threads than the machine governor allows", () => {
    expect(() => parseArgs([])).toThrow(/usage/);
    expect(() => parseArgs(["m.mp4", "--upload-now"])).toThrow(/unknown option/);
    expect(() => parseArgs(["m.mp4", "--threads", "16"])).toThrow(/1 to 8/);
    expect(parseArgs(["m.mp4", "--dry-run"]).dryRun).toBe(true);
  });

  it("encodes the web file at the master's own rate, never re-timed (GRAMMAR A44), with a 2 s GOP", () => {
    const at = (args: string[], flag: string) => args[args.indexOf(flag) + 1];
    expect([at(webEncodeArgs(1205), "-r"), at(webEncodeArgs(1205), "-g")]).toEqual(["24", "48"]);
    expect([at(webEncodeArgs(1205, "24/1"), "-r"), at(webEncodeArgs(1205, "24/1"), "-g")]).toEqual(["24", "48"]);
    expect([at(webEncodeArgs(1205, "30000/1001"), "-r"), at(webEncodeArgs(1205, "30000/1001"), "-g")]).toEqual(["30000/1001", "60"]);
    expect(gopFrames("30000/1001")).toBe(60);
    expect(() => webEncodeArgs(1205, "25/1")).toThrow(/A44/);
    const steps = planRelease(parseArgs(["r/master.mp4"]), { ...tools, durations: { film: 1205, trailer: null }, rates: { film: "30000/1001" } }).steps as Step[];
    expect(steps[1].args).toEqual(expect.arrayContaining(["-r", "30000/1001", "-g", "60"]));
    expect(webEncodeArgs(null, null).join(" ")).toContain("<the master's rate>");
  });

  it("refuses a film or trailer whose rate cannot be read or is not a master rate, never taking it as 24", () => {
    const all = () => true;
    const o = parseArgs(["r/master.mp4", "--trailer", "t/master.mp4"]);
    expect(rateProblems(o, { film: "30000/1001", trailer: "24/1" }, all)).toEqual([]);
    expect(rateProblems(o, { film: "30000/1001", trailer: null }, all)).toEqual([expect.stringMatching(/t\/master\.mp4's frame rate.*trailer/)]);
    expect(rateProblems(o, { film: null, trailer: "24/1" }, all)).toEqual([expect.stringMatching(/r\/master\.mp4's frame rate.*film/)]);
    expect(rateProblems(o, { film: "25/1", trailer: "24/1" }, all)).toEqual([expect.stringMatching(/25\/1 fps, not 24 or 30000\/1001/)]);
    expect(rateProblems(parseArgs(["r/master.mp4"]), { film: "24/1", trailer: null }, all)).toEqual([]);
    expect(rateProblems(o, { film: null, trailer: null }, () => false)).toEqual([]);   // a missing file is refused elsewhere
  });

  it("uploads the English captions only once films.json has them in review or reviewed, never while they are planned", () => {
    const planFor = (review: string | null | undefined) =>
      planRelease(parseArgs(["r/master.mp4"]), { ...tools, durations: { film: 1205, trailer: 120 }, captionsReview: review }) as { steps: Step[]; files: string[] };
    const puts = (review: string | null | undefined) =>
      planFor(review).steps.filter((s) => s.args?.includes("put")).map((s) => s.args?.[s.args.indexOf("put") + 1]);
    for (const review of ["reviewed", "in_review"]) expect(puts(review), review).toContain(`${BUCKET}/partition-of-india/captions-en.vtt`);
    for (const review of ["planned", null, undefined]) {
      expect(puts(review), String(review)).toEqual([`${BUCKET}/partition-of-india/film.mp4`, `${BUCKET}/partition-of-india/poster.jpg`, `${BUCKET}/partition-of-india/sources.json`]);
      expect(planFor(review).files.some((f) => /captions/.test(f)), String(review)).toBe(false);
      // publish still writes the track, and the plan still checks it is a WebVTT file with cues.
      expect(planFor(review).steps.some((s) => s.check === "captions")).toBe(true);
    }
    // undefined is a film films.json does not list: nothing says its captions were read, so none go up.
    expect(uploadsCaptions(undefined)).toBe(false);
    expect(uploadsCaptions("reviewed")).toBe(true);
    expect(uploadsCaptions("in_review")).toBe(true);
    expect(uploadsCaptions("planned")).toBe(false);
    expect(uploadsCaptions(null)).toBe(false);
  });

  it("reads a film's English caption review from films.json: planned, missing, or the film unlisted", () => {
    const reg = { films: [
      { slug: "a", languages: { captions: [{ lang: "en", review: "planned" }] } },
      { slug: "b", languages: { captions: [{ lang: "hi", review: "reviewed" }] } },
      { slug: "c", languages: { captions: [{ lang: "en", review: "reviewed" }] } },
    ] };
    expect(captionReview(reg, "a")).toBe("planned");
    expect(captionReview(reg, "b")).toBeNull();
    expect(captionReview(reg, "c")).toBe("reviewed");
    expect(captionReview(reg, "z")).toBeUndefined();
    // As shipped: Real World's are planned, so its release puts no captions up.
    const shipped = JSON.parse(readFileSync(new URL("../films.json", import.meta.url), "utf8"));
    expect(captionReview(shipped, "real-world")).toBe("planned");
    expect(captionReview(shipped, "partition-of-india")).toBe("reviewed");
    expect(captionReview(shipped, "smallpox-eradication")).toBe("in_review");
  });

  it("prints a command line a person can paste", () => {
    expect(commandLine({ exe: "ffmpeg", args: ["-i", "a b.mp4", "-vf", "scale=1280:720"] })).toBe('ffmpeg -i "a b.mp4" -vf scale=1280:720');
  });
});

describe("the film's ledgers", () => {
  it("resolve a screenplay's relative ledger and media paths against the film folder, not the repo", () => {
    const dir = mkdtempSync(pjoin(tmpdir(), "film-"));
    mkd(pjoin(dir, "stills"));
    wfs(pjoin(dir, "screenplay.json"), JSON.stringify({ slug: "x-film", ledgers: { stills: { path: "stills-ledger.json", media: "stills" } } }));
    wfs(pjoin(dir, "stills-ledger.json"), JSON.stringify({ items: [{ id: "S-1", file: "S-1.jpg" }] }));
    const l = readLedgers(dir)!;
    expect(l.ledger).toBe(pjoin(dir, "stills-ledger.json"));
    expect(l.media).toBe(pjoin(dir, "stills"));
    expect(posterSource(l, "S-1")).toBe(pjoin(dir, "stills", "S-1.jpg"));
  });
});
