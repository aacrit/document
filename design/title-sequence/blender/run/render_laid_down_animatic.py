"""Laid Down: the 480p animatic of the whole title for one film's record (spec rev 3, section 8), under the machine rules.

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/render_laid_down_animatic.py \
        [--record C20-METAR-0851] [--engine D:/document-worktrees/render-509fa56] [--samples 32] [--chunk 90]
        [--assemble-only]

1. The plan: laid_down.render_plan, every run of identical frames (holds, the stillness, the pose hold) rendered once
   and repeated (spec section 9; the scene is deterministic: fixed seed, no animated noise).
2. The renders: 854x480, adaptive 24-32 spp, no denoiser, the shot's fixed exposure (exposure.json, metered on the
   pile at f708 for the stills). Chunks of --chunk frames, one Blender process each, under HEAVY.lock (D: not dirty,
   C: and D: over 10 GB; waits while a live process holds it; released in a finally after every chunk, so the
   coordinator's renders can go between chunks). A frame already on disk is not rendered again.
3. The lockup: 180 frames of studio.engine.motion.lockup_card_frame from an engine checkout that has it (as the v5d
   proof), after the shot's 1032 frames, joined by a cut.
4. The sound: foley_laid_down (its room tone under the whole title and the lockup) plus the music director's theme
   for the film (theme-laid-down/, its sha256 checked against SHA256SUMS) at unity; Foley-only if the theme is absent.
5. The master: H.264 + AAC at 30000/1001 under 15 MB, a frame sheet, and animatic.json with the checks.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.io import wavfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import laid_down as L  # noqa: E402
import render_laid_down_stills as RS  # noqa: E402

ROOT = Path("D:/document-media/title-sequence/laid-down")
OUT = ROOT / "animatic"
THEME = Path("D:/document-media/title-sequence/theme-laid-down")
RES = (854, 480)
LOCKUP_S = 6.0
MAX_MB = 15.0


def arg(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def blender_chunk(frames, outdir, record, ev, samples):
    cmd = [RS.BLENDER, "-b", "-noaudio", "--factory-startup", "--python", str(HERE / "scene_laid_down.py"), "--",
           "--frame", str(frames[0]), "--frames", ",".join(str(f) for f in frames), "--outdir", str(outdir),
           "--res", f"{RES[0]}x{RES[1]}", "--samples", str(samples), "--min_samples", str(max(24, samples - 8)),
           "--threshold", "0.02", "--exposure", f"{ev:.6f}", "--record", record, "--out", str(outdir)]
    env = dict(__import__("os").environ, TEMP=str(ROOT / "tmp"), TMP=str(ROOT / "tmp"))
    RS.take_lock(f"Laid Down animatic {record} f{frames[0]}-f{frames[-1]} ({len(frames)} frames)")
    try:
        t0 = time.time()
        p = subprocess.run(cmd, capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    finally:
        RS.drop_lock()
    log = outdir.parent / f"chunk-{frames[0]:05d}.log"
    log.write_text(p.stdout + "\n" + p.stderr, encoding="utf-8")
    info = next((json.loads(ln[9:]) for ln in p.stdout.splitlines() if ln.startswith("LD-STILL ")), None)
    if p.returncode != 0 or info is None:
        raise SystemExit(f"blender failed ({p.returncode}); log in {log}")
    info["wall_s"] = round(time.time() - t0, 1)
    return info


def lockup(engine, n, outdir):
    sys.path.insert(0, str(engine))
    from studio.engine import motion as M
    outdir.mkdir(parents=True, exist_ok=True)
    fonts = M.Fonts()
    for k in range(n):
        p = outdir / f"{k:05d}.png"
        if not p.exists():
            M.lockup_card_frame(Image.new("RGB", RES, (0, 0, 0)), k / L.FPS, start=0.0, end=LOCKUP_S,
                                fonts=fonts).convert("RGB").save(p)
    return {"engine": str(engine), "frames": n}


def theme_for(record):
    w = THEME / f"laid-down-theme-{record}.wav"
    if not w.exists():
        return None, None
    sums = dict(ln.split(" *")[::-1] for ln in (THEME / "SHA256SUMS").read_text(encoding="utf-8").split("\n") if " *" in ln)
    got = hashlib.sha256(w.read_bytes()).hexdigest()
    if sums.get(w.name) != got:
        raise SystemExit(f"{w} does not match SHA256SUMS")
    return w, got


TRUE_PEAK_MAX_DBTP = -1.5


def true_peak_dbtp(x):
    from scipy.signal import resample_poly
    return 20 * math.log10(float(np.max(np.abs(resample_poly(x, 4, 1)))) + 1e-20)


def mix(record, foley_wav, out_wav, events):
    """The Foley (its room tone in it) plus the theme at unity, the theme ducked only around the chart's slide
    (foley_laid_down.THEME_DUCK; its notes untouched). The ducked theme is also written beside the mix (24-bit-in-32,
    as delivered) for measure_laid_down. Refused, not trimmed, if the mix's true peak passes TRUE_PEAK_MAX_DBTP."""
    import foley_laid_down as FL
    sr, f = wavfile.read(foley_wav)
    f = f[:, 0].astype(np.float64) / 32768
    w, sha = theme_for(record)
    rep = {"foley": str(foley_wav), "theme": None}
    x = f
    if w is not None:
        sr2, t = wavfile.read(w)
        assert sr2 == sr
        t = t.astype(np.float64) / (2 ** 31 if t.dtype == np.int32 else 32768)
        t = t if t.ndim == 1 else t.mean(1)
        g, duck = FL.theme_duck(len(t), events, sr)
        t = t * g
        dd = OUT / "theme-ducked"
        dd.mkdir(parents=True, exist_ok=True)
        wavfile.write(dd / w.name, sr, np.clip(np.round(t * 2 ** 31), -2 ** 31, 2 ** 31 - 1).astype(np.int32))
        n = max(len(f), len(t))
        x = np.zeros(n)
        x[:len(f)] += f
        x[:len(t)] += t
        rep["theme"] = {"file": str(w), "sha256": sha, "dur_s": round(len(t) / sr, 3), "gain": "unity",
                        "duck": duck, "ducked_copy": str(dd / w.name)}
    rep["mix_peak_dbfs"] = round(20 * math.log10(np.abs(x).max() + 1e-20), 2)
    rep["mix_true_peak_dbtp"] = round(true_peak_dbtp(x), 2)
    rep["foley_true_peak_dbtp"] = round(true_peak_dbtp(f), 2)
    if rep["mix_true_peak_dbtp"] > TRUE_PEAK_MAX_DBTP:
        raise SystemExit(f"mix true peak {rep['mix_true_peak_dbtp']} dBTP over {TRUE_PEAK_MAX_DBTP}")
    wavfile.write(out_wav, sr, (np.clip(np.stack([x, x], 1), -1, 1) * 32767).astype(np.int16))
    return rep


def frame_list(src, lock_dir):
    """The master's frames in order: the opening black (spec: frames 0-11, the master opens from its own black, A40;
    the picture arrives at frame 12 with the Atlas already sliding), then each of the shot's frames as its rendered
    source (holds repeat it), then the lockup's 180."""
    n_lock = int(round(LOCKUP_S * L.FPS))
    black = OUT / "black-480.png"
    if not black.exists():
        Image.new("RGB", RES, (0, 0, 0)).save(black)
    b0, b1 = L.BEATS["black"]["frames"]
    return [black if b0 <= f <= b1 else OUT / "frames" / f"{src[f]:05d}.png" for f in range(L.FRAMES)] + \
        [lock_dir / f"{k:05d}.png" for k in range(n_lock)]


def encode(src, lock_dir, audio, out):
    """Every frame piped to ffmpeg as raw RGB at exactly 30000/1001 (the concat demuxer's durations cannot be exact
    fractions), with the mix, H.264 + AAC, under MAX_MB."""
    frames = frame_list(src, lock_dir)
    for crf in (18, 20, 22, 24, 26):
        p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s",
                              f"{RES[0]}x{RES[1]}", "-framerate", "30000/1001", "-i", "-", "-i", str(audio),
                              "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "slow", "-crf", str(crf),
                              # the picture sets the length (1212 frames, 40.440 s); the mix (40.434 s) is padded
                              "-pix_fmt", "yuv420p", "-af", "apad", "-c:a", "aac", "-b:a", "192k", "-shortest",
                              "-movflags",
                              "+faststart", str(out)], stdin=subprocess.PIPE)
        cache = {}
        for fp in frames:
            if fp not in cache:
                cache = {fp: np.asarray(Image.open(fp).convert("RGB"), np.uint8).tobytes()}
            p.stdin.write(cache[fp])
        p.stdin.close()
        if p.wait() != 0:
            raise SystemExit("ffmpeg failed")
        if out.stat().st_size <= MAX_MB * 1024 * 1024:
            return {"crf": crf, "bytes": out.stat().st_size, "frames": len(frames)}
    raise SystemExit(f"{out} stays over {MAX_MB} MB")


def frame_sheet(src, lock_dir, record, out):
    r = L.RECORDS[record]
    picks = [("black", 5)]
    for s in L.SHEETS:
        picks += [(f"{s['id']} enters", s["enter_frame"] + 3), (f"{s['id']} stop", s["stop_frame"])]
    picks += [("stillness", 770), ("record enters", r["enter_frame"] + 4), ("record stop", r["stop_frame"]),
              ("descent", 900), ("descent", 950), ("pose", r["record_pose"]["from_frame"]), ("last", L.FRAMES - 1)]
    tw, th = 427, 240
    cols = 4
    rows = math.ceil((len(picks) + 1) / cols)
    sheet = Image.new("RGB", (cols * tw, rows * (th + 22)), (24, 20, 16))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default(size=14)
    except TypeError:
        font = ImageFont.load_default()
    fl = frame_list(src, lock_dir)
    items = [(lab, fl[f], f) for lab, f in picks + [("picture arrives", L.BEATS["black"]["frames"][1] + 1)]]
    items.append(("lockup", lock_dir / f"{int(LOCKUP_S * L.FPS * 0.9):05d}.png", L.FRAMES + int(LOCKUP_S * L.FPS * 0.9)))
    for i, (lab, p, f) in enumerate(items):
        x, y = (i % cols) * tw, (i // cols) * (th + 22)
        sheet.paste(Image.open(p).convert("RGB").resize((tw, th), Image.LANCZOS), (x, y + 22))
        d.text((x + 6, y + 4), f"f{f}  {lab}", fill=(237, 226, 207), font=font)
    sheet.save(out)
    return str(out)


def checks(plan, record, engine):
    """The acceptance items a picture can show: no channel clips on any frame; the lamp constant (the mean of the static
    camera's frames moves only as sheets arrive); A7 and the edge strips over the pose hold, on the rendered frames."""
    out = {}
    clip = []
    for f in plan["render"]:
        a = np.asarray(Image.open(OUT / "frames" / f"{f:05d}.png").convert("RGB"))
        clip.append((f, int(a.max()), float((a >= 254).any(-1).mean())))
    out["max_channel"] = max(c[1] for c in clip)
    out["frames_with_any_channel_at_254_or_more"] = [c[0] for c in clip if c[2] > 0]
    sys.path.insert(0, str(engine))
    from studio.engine import titles as TT
    r = L.RECORDS[record]
    man = json.loads(Path("D:/document-media/title-sequence/tex-manifest.json").read_text(encoding="utf-8"))
    scan = man[r["tex"].rsplit(".", 1)[0]]["tex"]["file"]
    win = list(r["record_window"])
    a7 = {}
    for f in sorted({r["record_pose"]["from_frame"], 990, 1010, L.FRAMES - 1}):
        img = Image.open(OUT / "frames" / f"{plan['source_of'][f]:05d}.png").convert("RGB").resize((1920, 1080),
                                                                                                  Image.LANCZOS)
        arr = np.asarray(img)
        a7[f] = {"a7": round(TT.record_difference(arr, scan, win), 3),
                 "edge_strips": round(TT.pose_edge_difference(arr, scan, win), 2)}
    out["a7"] = {"by_frame": a7, "worst": max(v["a7"] for v in a7.values()),
                 "edge_worst": max(v["edge_strips"] for v in a7.values()),
                 "limits": [TT.RECORD_LIMIT, TT.POSE_EDGE_LIMIT],
                 "basis": "the 854x480 render upscaled (Lanczos) to 1080p, through the engine's record_difference"}
    out["a7"]["pass"] = out["a7"]["worst"] <= TT.RECORD_LIMIT and out["a7"]["edge_worst"] <= TT.POSE_EDGE_LIMIT
    # the lamp: mean luminance of each hold's frame (the camera fixed; it changes only as sheets arrive)
    out["hold_means"] = {}
    for s in L.SHEETS:
        f = plan["source_of"][s["stop_frame"] + 12]
        a = np.asarray(Image.open(OUT / "frames" / f"{f:05d}.png").convert("L"), np.float32)
        out["hold_means"][s["id"]] = round(float(a.mean()), 2)
    return out


def main():
    record = arg("--record", "C20-METAR-0851")
    engine = Path(arg("--engine", "D:/document-worktrees/render-509fa56"))
    samples = int(arg("--samples", "32"))
    chunk = int(arg("--chunk", "90"))
    frames_dir = OUT / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    ev = json.loads((ROOT / "exposure.json").read_text(encoding="utf-8"))["ev"]
    plan = L.render_plan(record)
    rec = {"record": record, "res": list(RES), "samples": samples, "exposure_ev": ev, "unique": len(plan["render"]),
           "frames": L.FRAMES, "chunks": []}
    if "--assemble-only" not in sys.argv:
        free = RS.preflight()
        rec["free_gb"] = free
        todo = [f for f in plan["render"] if not (frames_dir / f"{f:05d}.png").exists()]
        for i in range(0, len(todo), chunk):
            RS.preflight()
            part = todo[i:i + chunk]
            info = blender_chunk(part, frames_dir, record, ev, samples)
            rec["chunks"].append({"from": part[0], "to": part[-1], "n": len(part), "wall_s": info["wall_s"],
                                  "render_s": info["render_s"], "renderer": info["renderer"], "denoise": info["denoise"]})
            print(f"chunk f{part[0]}-f{part[-1]}: {len(part)} frames in {info['wall_s']} s", flush=True)
    missing = [f for f in plan["render"] if not (frames_dir / f"{f:05d}.png").exists()]
    if missing:
        raise SystemExit(f"frames missing: {missing[:10]}")
    lock_dir = OUT / "lockup-480"
    rec["lockup"] = lockup(engine, int(round(LOCKUP_S * L.FPS)), lock_dir)
    import foley_laid_down as FL
    foley_wav = OUT / f"foley-{record}.wav"
    mixd, frep = FL.build(record, LOCKUP_S)
    FL.write_stereo(foley_wav, mixd)
    foley_wav.with_suffix(".foley-report.json").write_text(json.dumps(frep, indent=1), encoding="utf-8")
    rec["mix"] = mix(record, foley_wav, OUT / f"mix-{record}.wav", frep["events"])
    rec["master"] = encode(plan["source_of"], lock_dir, OUT / f"mix-{record}.wav", OUT / "laid-down-480p.mp4")
    rec["frame_sheet"] = frame_sheet(plan["source_of"], lock_dir, record, OUT / "laid-down-480p-sheet.png")
    rec["checks"] = checks(plan, record, engine)
    (OUT / "animatic.json").write_text(json.dumps(rec, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: rec[k] for k in ("unique", "master", "mix")}, default=str))
    print(json.dumps(rec["checks"], default=str)[:2000])


if __name__ == "__main__":
    main()
