// scripts/release-film.mjs: the post-render release runs its steps in order,
// uploads to the film's folder in R2 with --remote and sources.json last, and
// a dry run is plain data that never runs a command.
import { describe, expect, it } from "vitest";
import { BUCKET, MAX_PUT_BYTES, PACKET_ROOT, UPLOAD_ORDER, commandLine, videoKbps, webEncodeArgs, dirtyVerdict, driveOf, driveProblems, parseArgs, planRelease } from "../scripts/release-film.mjs";

type Step = { id: string; label: string; exe?: string; args?: string[]; check?: string; tolerate?: RegExp };

const tools = { python: "py", ffmpeg: "ffmpeg", wrangler: { exe: "node", pre: ["wrangler.js"] }, ledgers: { slug: "partition-of-india", ledger: "L.json", media: "stills" }, poster: "stills/S-020.jpg" };
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

  it("prints a command line a person can paste", () => {
    expect(commandLine({ exe: "ffmpeg", args: ["-i", "a b.mp4", "-vf", "scale=1280:720"] })).toBe('ffmpeg -i "a b.mp4" -vf scale=1280:720');
  });
});
