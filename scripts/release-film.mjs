#!/usr/bin/env node
// The post-render release of one film: from a finished master to its files in
// R2, in order, stopping at the first failure.
//
//   a. sources.json beside the master   python -m studio.engine.render <film dir> --out <render dir> --sources-only
//   b. the 720p web encode               ffmpeg -> <packet>/film.mp4 (and trailer.mp4, only with --trailer)
//   c. the poster and the packet         ffmpeg (still -> poster.jpg), python -m studio.engine.publish
//   d. the captions                      captions-en.vtt, written by publish (studio/engine/captions.py); checked here
//   e. the upload                        wrangler r2 object put document-media/<slug>/<file> --remote, sources.json last
//   f. the hashes                        sha256 of every file, checked against what sources.json records
//
//   node scripts/release-film.mjs <render dir>/master.mp4 [--dry-run] [--trailer <trailer master.mp4>]
//       [--film-dir <dir with screenplay.json>] [--poster-id S-020] [--out <packet dir>] [--no-upload]
//
// The trailer is optional. Without --trailer, sources.json declares none, the
// site hides its Trailer button, and the contract reports the trailer n/a.
// The packet defaults to D:/document-media/web-packet/<slug> (C: sits at its
// 10 GB floor). D: is exFAT and once had bitmap corruption, so before any
// write the script runs `fsutil dirty query` on every drive it writes to
// (the packet and the render folder) and refuses if one is dirty or the query
// fails.
//
// --dry-run prints every command and runs none. The site reads sources.json
// to decide whether the film it serves is the cut it describes
// (web/src/film-data.ts durationsAgree), so sources.json goes up last: until
// then the page keeps its previous record. Production pages only change at
// /release; this script only replaces media.

import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, statSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { resolveBinPath } from "./lib/run-bin.mjs";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

export const BUCKET = "document-media";
/** Where the web packet goes unless --out says otherwise (C: is at its 10 GB floor). */
export const PACKET_ROOT = "D:/document-media/web-packet";
/** wrangler r2 object put refuses a file over 300 MiB (its MAX_UPLOAD_SIZE_BYTES). */
export const MAX_PUT_BYTES = 300 * 1024 * 1024;
/** Uploaded in this order: the media first, sources.json last (see above). */
export const UPLOAD_ORDER = ["film.mp4", "poster.jpg", "trailer.mp4", "captions-en.vtt", "sources.json"];
/** What wrangler or R2 may say when a deleted key was never there. */
export const MISSING_KEY = /does not exist|NoSuchKey|not found/i;
const TYPES = { mp4: "video/mp4", jpg: "image/jpeg", vtt: "text/vtt", json: "application/json" };

// The web encode: 1280x720, 24 fps, H.264 high, AAC 128k, faststart. CRF 22
// sets the quality; -maxrate (with a VBV buffer of twice that) caps the rate,
// derived from the input's duration so the file stays under 85% of the 300 MiB
// put limit: (0.85 x 300 MiB x 8 / duration - 128 kbit/s audio) x 0.98 for the
// container, never above 2,500 kbit/s. A 1,205 s film gets about 1,600 kbit/s
// (about 255 MiB at the cap; stills and cards come in far lower).
export const AUDIO_BPS = 128000;
export const PUT_MARGIN = 0.85;
export const MAX_VIDEO_KBPS = 2500;
export const MIN_VIDEO_KBPS = 400;

/** The video rate cap for an input of `durationS` seconds, in kbit/s; throws when even the floor would not fit. */
export function videoKbps(durationS) {
  if (!(durationS > 0)) throw new Error(`cannot derive a rate cap from a duration of ${durationS}`);
  const kbps = Math.floor((((PUT_MARGIN * MAX_PUT_BYTES * 8) / durationS - AUDIO_BPS) * 0.98) / 1000);
  if (kbps < MIN_VIDEO_KBPS) throw new Error(`${durationS} s is too long for one ${MAX_PUT_BYTES / 2 ** 20} MiB put at ${MIN_VIDEO_KBPS} kbit/s or more`);
  return Math.min(MAX_VIDEO_KBPS, kbps);
}

/** The encode arguments for an input of `durationS` seconds (null in a dry run before the file exists). */
export function webEncodeArgs(durationS) {
  const rate = durationS === null ? "<derived from duration>" : `${videoKbps(durationS)}k`;
  const buf = durationS === null ? "<twice the rate>" : `${2 * videoKbps(durationS)}k`;
  return [
    "-map", "0:v:0", "-map", "0:a:0",
    "-vf", "scale=1280:720:flags=lanczos,format=yuv420p",
    "-c:v", "libx264", "-preset", "slow", "-crf", "22", "-maxrate", rate, "-bufsize", buf,
    "-profile:v", "high", "-level:v", "4.0", "-r", "24", "-g", "48",
    "-c:a", "aac", "-b:a", `${AUDIO_BPS / 1000}k`, "-ar", "48000",
    "-movflags", "+faststart",
  ];
}

/** An input's duration in seconds by ffprobe (beside DOCUMENT_FFMPEG, else on PATH), or null when it cannot be read. */
export function probeDuration(file, ffmpeg = process.env.DOCUMENT_FFMPEG || "ffmpeg") {
  if (!existsSync(file)) return null;
  const probe = path.join(path.dirname(ffmpeg), path.basename(ffmpeg).replace(/ffmpeg/i, "ffprobe"));
  const r = spawnSync(probe, ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", file], { encoding: "utf8", shell: false });
  const d = Number(String(r.stdout ?? "").trim());
  return r.status === 0 && d > 0 ? d : null;
}

export function parseArgs(argv) {
  const o = { master: null, dryRun: false, upload: true, trailer: null, filmDir: null, posterId: "S-020", out: null, slug: null, threads: 4 };
  const value = (i, flag) => {
    if (i + 1 >= argv.length) throw new Error(`${flag} needs a value`);
    return argv[i + 1];
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--dry-run") o.dryRun = true;
    else if (a === "--no-upload") o.upload = false;
    else if (a === "--trailer") o.trailer = value(i++, a);
    else if (a === "--film-dir") o.filmDir = value(i++, a);
    else if (a === "--poster-id") o.posterId = value(i++, a);
    else if (a === "--out") o.out = value(i++, a);
    else if (a === "--slug") o.slug = value(i++, a);
    else if (a === "--threads") o.threads = Number(value(i++, a));
    else if (a.startsWith("--")) throw new Error(`unknown option ${a}`);
    else if (!o.master) o.master = a;
    else throw new Error(`unexpected argument ${a}`);
  }
  if (!o.master) throw new Error("usage: node scripts/release-film.mjs <render dir>/master.mp4 [--dry-run] [--trailer <file>] [--film-dir <dir>] [--poster-id S-020] [--out <dir>] [--no-upload]");
  if (!Number.isInteger(o.threads) || o.threads < 1 || o.threads > 8) throw new Error("--threads must be 1 to 8 (the machine governor)");
  return o;
}

/** The studio's Python, as the gate finds it: DOCUMENT_PYTHON, else the venv in ~/document-work, else python on PATH. */
export function studioPython(env = process.env) {
  if (env.DOCUMENT_PYTHON) return env.DOCUMENT_PYTHON;
  const venv = path.join(os.homedir(), "document-work", ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
  if (existsSync(venv)) return venv;
  return process.platform === "win32" ? "python" : "python3";
}

/**
 * The screenplay's stills ledger and its media folder, which publish.py and the
 * poster step need. Read from <film dir>/screenplay.json when it exists.
 */
export function readLedgers(filmDir) {
  const file = path.join(filmDir, "screenplay.json");
  if (!existsSync(file)) return null;
  const play = JSON.parse(readFileSync(file, "utf8"));
  const stills = play?.ledgers?.stills;
  if (!stills?.path) return null;
  // A screenplay may name its ledger and media relative to its own folder (The Next Village does);
  // every step runs from the repo root, so resolve them against the film folder here.
  const ledger = path.resolve(filmDir, stills.path);
  const media = path.resolve(filmDir, stills.media ?? path.dirname(stills.path));
  return { slug: play.slug ?? null, ledger, media };
}

/** The poster still's file in the stills ledger. */
export function posterSource(ledgers, posterId) {
  if (!ledgers || !existsSync(ledgers.ledger)) return null;
  const data = JSON.parse(readFileSync(ledgers.ledger, "utf8"));
  const items = Array.isArray(data) ? data : (data.items ?? []);
  const item = items.find((x) => x && x.id === posterId);
  return item?.file ? path.join(ledgers.media, item.file) : null;
}

/** Every step of the release, in order, as plain data: { id, label, exe, args, cwd } or { id, label, check }. */
export function planRelease(o, { python = studioPython(), ffmpeg = process.env.DOCUMENT_FFMPEG || "ffmpeg", wrangler = null, ledgers, poster, durations = {} } = {}) {
  const master = path.resolve(o.master);
  const renderDir = path.dirname(master);
  const filmDir = path.resolve(o.filmDir ?? path.join(os.homedir(), "document-work", "episode-v2"));
  const slug = o.slug ?? ledgers?.slug ?? "partition-of-india";
  const out = path.resolve(o.out ?? path.join(PACKET_ROOT, slug));
  const ledgerPath = ledgers?.ledger ?? "<stills ledger: screenplay.json ledgers.stills.path>";
  const stillPath = poster ?? `<${o.posterId} from the stills ledger>`;
  const wr = wrangler ?? { exe: process.execPath, pre: [resolveBinPath("wrangler", "wrangler")] };
  const at = (f) => path.join(out, f);
  const steps = [];

  steps.push({ id: "a", label: "sources.json beside the master (--sources-only)", exe: python, cwd: repoRoot,
    args: ["-m", "studio.engine.render", filmDir, "--out", renderDir, "--sources-only"] });
  const encode = (input, file, d) => ({ exe: ffmpeg, cwd: repoRoot, args: ["-v", "error", "-y", "-i", input, ...webEncodeArgs(d ?? null), "-threads", String(o.threads), at(file)] });
  steps.push({ id: "b", label: "the 720p web encode of the film", ...encode(master, "film.mp4", durations.film) });
  if (o.trailer) steps.push({ id: "b", label: "the 720p web encode of the trailer", ...encode(path.resolve(o.trailer), "trailer.mp4", durations.trailer) });
  steps.push({ id: "c", label: `the poster (${o.posterId}, 1920 wide)`, exe: ffmpeg, cwd: repoRoot,
    args: ["-v", "error", "-y", "-i", stillPath, "-vf", "scale=1920:-1:flags=lanczos", "-q:v", "3", at("poster.jpg")] });
  steps.push({ id: "c", label: "the web packet (publish.py: sources.json with web and poster, captions)", exe: python, cwd: repoRoot,
    args: ["-m", "studio.engine.publish", renderDir, "--film", at("film.mp4"), "--poster", at("poster.jpg"),
      "--poster-id", o.posterId, "--stills-ledger", ledgerPath, "--out", out, "--screenplay", path.join(filmDir, "screenplay.json"), ...(o.trailer ? ["--trailer", at("trailer.mp4")] : [])] });
  steps.push({ id: "d", label: "the captions (captions-en.vtt, written by publish from the render's screenplay)", check: "captions", file: at("captions-en.vtt") });
  const files = UPLOAD_ORDER.filter((f) => f !== "trailer.mp4" || o.trailer);
  steps.push({ id: "e", label: "every file under the put limit", check: "sizes", files: files.map(at) });
  // Every hash is checked against sources.json before the first put, so nothing goes up that the record does not describe.
  steps.push({ id: "e", label: "every file hashes to what sources.json records", check: "hashes", files: files.map(at), sources: at("sources.json"), slug });
  if (o.upload) {
    // Without a trailer, one left from an earlier release must not stay public (the contract expects a 404 then).
    // R2 deletes a missing key without error; a "does not exist" answer is tolerated as well.
    if (!o.trailer) {
      steps.push({ id: "e", label: "delete any earlier trailer.mp4 (none is declared)", exe: wr.exe, cwd: repoRoot, tolerate: MISSING_KEY,
        args: [...wr.pre, "r2", "object", "delete", `${BUCKET}/${slug}/trailer.mp4`, "--remote"] });
    }
    for (const f of files) {
      steps.push({ id: "e", label: `upload ${f}`, exe: wr.exe, cwd: repoRoot,
        args: [...wr.pre, "r2", "object", "put", `${BUCKET}/${slug}/${f}`, "--file", at(f), "--content-type", TYPES[f.split(".").pop()], "--remote"] });
    }
  }
  steps.push({ id: "f", label: "hashes", check: "hashes", files: files.map(at), sources: at("sources.json"), slug });
  return { steps, out, renderDir, filmDir, slug, files };
}

/** The drive letter a path is on ("D:"), or null off Windows or on a UNC path. */
export function driveOf(p, platform = process.platform) {
  if (platform !== "win32") return null;
  const m = /^([a-z]):/i.exec(path.win32.resolve(p));
  return m ? `${m[1].toUpperCase()}:` : null;
}

/** Only a query that ran and says "is NOT Dirty" clears a volume; a dirty volume or a failed query refuses. */
export function dirtyVerdict(status, stdout) {
  if (status !== 0) return { ok: false, why: `fsutil dirty query failed (exit ${status})` };
  if (/is NOT Dirty/i.test(stdout)) return { ok: true };
  if (/is Dirty/i.test(stdout)) return { ok: false, why: "the volume is dirty: run chkdsk (founder's call) before writing to it" };
  return { ok: false, why: `fsutil dirty query said something else: ${stdout.trim()}` };
}

/** The exFAT guard: every drive the release writes to that is D: must be clean. Returns the problems. */
export function driveProblems(paths, run = (drive) => spawnSync("fsutil", ["dirty", "query", drive], { encoding: "utf8", shell: false })) {
  const drives = [...new Set(paths.map((p) => driveOf(p)).filter((d) => d === "D:"))];
  const problems = [];
  for (const d of drives) {
    const r = run(d);
    const v = dirtyVerdict(r.error ? -1 : r.status, String(r.stdout ?? ""));
    if (!v.ok) problems.push(`refusing to write to ${d}: ${v.why}`);
  }
  return problems;
}

const quote = (s) => (/^[\w@%+=:,./\\-]+$/.test(s) ? s : `"${String(s).replace(/"/g, '\\"')}"`);
export const commandLine = (step) => [step.exe, ...step.args].map(quote).join(" ");

export function sha256(file) {
  return createHash("sha256").update(readFileSync(file)).digest("hex");
}

function runCheck(step) {
  if (step.check === "captions") {
    const text = existsSync(step.file) ? readFileSync(step.file, "utf8") : "";
    const cues = (text.match(/ --> /g) ?? []).length;
    if (!text.startsWith("WEBVTT") || cues === 0) throw new Error(`${step.file} is not a WebVTT file with cues`);
    console.log(`  ${cues} cues`);
  } else if (step.check === "sizes") {
    for (const f of step.files) {
      if (!existsSync(f)) throw new Error(`${f} is missing`);
      const size = statSync(f).size;
      if (size > MAX_PUT_BYTES) throw new Error(`${path.basename(f)} is ${(size / 2 ** 20).toFixed(1)} MiB, over wrangler's 300 MiB put limit: encode it smaller`);
      console.log(`  ${path.basename(f)} ${(size / 2 ** 20).toFixed(1)} MiB`);
    }
  } else if (step.check === "hashes") {
    const doc = JSON.parse(readFileSync(step.sources, "utf8"));
    const want = { "film.mp4": doc.web?.film_sha256, "poster.jpg": doc.poster?.sha256, "trailer.mp4": doc.trailer?.sha256 };
    for (const f of step.files) {
      const name = path.basename(f);
      const got = sha256(f);
      const tie = want[name] ? (want[name] === got ? "  = sources.json" : `  != sources.json ${want[name]}`) : "";
      console.log(`  ${got}  ${BUCKET}/${step.slug}/${name}${tie}`);
      if (want[name] && want[name] !== got) throw new Error(`${name} does not hash to what sources.json records`);
      if (name === "trailer.mp4" && !want[name]) throw new Error("trailer.mp4 is in the packet but sources.json declares no trailer");
    }
    console.log(`  film ${doc.web?.film_duration_s} s, master ${doc.master_sha256}`);
  }
}

function main() {
  let o;
  try {
    o = parseArgs(process.argv.slice(2));
  } catch (e) {
    console.error(`release-film: ${e.message}`);
    process.exit(2);
  }
  const filmDir = path.resolve(o.filmDir ?? path.join(os.homedir(), "document-work", "episode-v2"));
  const ledgers = readLedgers(filmDir);
  const poster = posterSource(ledgers, o.posterId);
  const durations = { film: probeDuration(o.master), trailer: o.trailer ? probeDuration(o.trailer) : null };
  const plan = planRelease(o, { ledgers, poster, durations });

  if (!o.dryRun) {
    const problems = [];
    if (path.basename(o.master) !== "master.mp4") problems.push(`${o.master} is not named master.mp4 (--sources-only reads <render dir>/master.mp4)`);
    if (!existsSync(o.master)) problems.push(`${o.master} does not exist`);
    if (!ledgers) problems.push(`${filmDir} has no screenplay.json naming its stills ledger`);
    if (!poster || !existsSync(poster)) problems.push(`the poster still ${o.posterId} was not found in the stills ledger`);
    if (o.trailer && !existsSync(o.trailer)) problems.push(`${o.trailer} does not exist`);
    if (existsSync(o.master) && durations.film === null) problems.push(`ffprobe could not read the duration of ${o.master} (the rate cap is derived from it)`);
    if (o.trailer && existsSync(o.trailer) && durations.trailer === null) problems.push(`ffprobe could not read the duration of ${o.trailer}`);
    problems.push(...driveProblems([plan.out, plan.renderDir]));
    if (problems.length) {
      for (const p of problems) console.error(`release-film: ${p}`);
      process.exit(2);
    }
    mkdirSync(plan.out, { recursive: true });
  }

  console.log(`release-film: ${o.dryRun ? "DRY RUN, nothing is run" : "releasing"} ${plan.slug} from ${plan.renderDir}`);
  console.log(`release-film: packet ${plan.out}; upload ${o.upload ? plan.files.join(", ") : "skipped (--no-upload)"}`);
  if (!o.trailer) console.log("release-film: no --trailer: no trailer is declared or uploaded, any earlier one is deleted; the site shows none");
  if (o.dryRun) for (const d of [...new Set([plan.out, plan.renderDir].map((x) => driveOf(x)).filter((x) => x === "D:"))]) console.log(`release-film: a real run first checks: fsutil dirty query ${d}`);
  for (const step of plan.steps) {
    console.log(`\n[${step.id}] ${step.label}`);
    if (step.check) {
      if (o.dryRun) {
        console.log(`  check: ${step.check}${step.file ? ` ${step.file}` : ""}`);
        continue;
      }
      try {
        runCheck(step);
      } catch (e) {
        console.error(`release-film: FAILED at [${step.id}] ${step.label}: ${e.message}`);
        process.exit(1);
      }
      continue;
    }
    console.log(`  ${commandLine(step)}`);
    if (o.dryRun) continue;
    const r = spawnSync(step.exe, step.args, { cwd: step.cwd, stdio: step.tolerate ? "pipe" : "inherit", shell: false, encoding: "utf8" });
    if (step.tolerate) {
      const said = `${r.stdout ?? ""}${r.stderr ?? ""}`;
      process.stdout.write(said);
      if (!r.error && r.status !== 0 && step.tolerate.test(said)) continue;
    }
    if (r.error || r.status !== 0) {
      console.error(`release-film: FAILED at [${step.id}] ${step.label} (${r.error ? r.error.message : `exit ${r.status}`})`);
      process.exit(r.status || 1);
    }
  }
  console.log(o.dryRun ? "\nrelease-film: dry run complete" : `\nrelease-film: done. Next: /release, then npm run contract -- --url https://document.voidvision.org`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
