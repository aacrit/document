// scripts/release-film.mjs: the post-render release runs its steps in order,
// uploads to the film's folder in R2 with --remote and sources.json last, and
// a dry run is plain data that never runs a command.
import { describe, expect, it } from "vitest";
import { BUCKET, UPLOAD_ORDER, WEB_ENCODE, commandLine, parseArgs, planRelease } from "../scripts/release-film.mjs";

type Step = { id: string; label: string; exe?: string; args?: string[]; check?: string };

const tools = { python: "py", ffmpeg: "ffmpeg", wrangler: { exe: "node", pre: ["wrangler.js"] }, ledgers: { slug: "partition-of-india", ledger: "L.json", media: "stills" }, poster: "stills/S-020.jpg" };
const plan = (argv: string[]) => planRelease(parseArgs(argv), tools) as { steps: Step[]; files: string[]; slug: string };

describe("release-film", () => {
  it("runs sources-only, the web encode, the poster and packet, the captions check, the upload and the hashes, in that order", () => {
    const { steps } = plan(["r/master.mp4", "--trailer", "t/master.mp4"]);
    expect(steps.map((s) => s.id)).toEqual(["a", "b", "b", "c", "c", "d", "e", "e", "e", "e", "e", "e", "f"]);
    expect(steps[0].args).toEqual(expect.arrayContaining(["-m", "studio.engine.render", "--sources-only"]));
    expect(steps[1].args).toEqual(expect.arrayContaining(WEB_ENCODE));
    expect(steps[1].args?.join(" ")).toContain("scale=1280:720");
    expect(steps[4].args).toEqual(expect.arrayContaining(["-m", "studio.engine.publish", "--poster-id", "S-020", "--stills-ledger", "L.json"]));
    expect(steps[5].check).toBe("captions");
  });

  it("puts every file into document-media/<slug>/ with --remote, the media first and sources.json last", () => {
    const { steps } = plan(["r/master.mp4", "--trailer", "t/master.mp4"]);
    const puts = steps.filter((s) => s.args?.includes("put"));
    expect(puts.map((s) => s.args?.[s.args.indexOf("put") + 1])).toEqual(UPLOAD_ORDER.map((f: string) => `${BUCKET}/partition-of-india/${f}`));
    for (const p of puts) expect(p.args).toContain("--remote");
    expect(puts[puts.length - 1].label).toBe("upload sources.json");
  });

  it("uploads no trailer without --trailer, and nothing with --no-upload", () => {
    expect(plan(["r/master.mp4"]).files).not.toContain(expect.stringMatching(/trailer/));
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
