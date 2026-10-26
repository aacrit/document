"""The Run v5c: one film's master from the shared prefix and its own re-rendered frames (one heavy job, HEAVY.lock).

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/tail_v5c.py --record S-130

The RW 29.97 render (final-v5c/frames-2560, final_v5c.py) is the shared prefix. A film re-renders only the frames that
differ from it: every frame that sees its record or the RW record (the opening wide, the end; the record is now dead
matte), every frame of the move down onto its record when its pose differs from RW's, and every frame whose exposure
eases onto the record. The rest are the RW frames as rendered. Per film, under final-v5c/<record>/:

1. exposure.json: the RW meter, eased (shot_v5c.ease_exposure, <= 1 stop/s) to POSE_EV at the pose.
2. tail-2560/ (PNG, AgX, as the prefix) and tail-exr/ (the same frames scene-linear, half float), Cycles at the
   prefix's own sampling (512 spp, 0.02, final_v5c's choice), motion blur on, no denoiser.
3. the 29.97 ProRes master (a Lanczos downscale to 1920x1080, as final_v5c) and an H.264 preview.
4. A7 on the master itself (studio.engine.titles: record_difference, pose_edge_difference), at the frames the lint
   reads: where the pose rests, the middle of the rest and the last frame, against the declared window.
5. the Foley (foley_v5c.py, the room at -72 dBFS, no music) muxed into the -sound master, and tail-report.json with
   the title item the film's ledger declares.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))
import channel_v5c as C  # noqa: E402
import render_still_v5 as RL  # noqa: E402  (the lock, the machine checks)
import shot_v5c as SH  # noqa: E402

BLENDER = "D:/document-media/tools/blender-4.4.3-windows-x64/blender.exe"
VENV_PY = "D:/document-media/tools/run-venv/Scripts/python.exe"
MEDIA = Path("D:/document-media/title-sequence/run")
BASE = MEDIA / "masters" / "final-v5c"
RW = "C20-METAR-0851"
FPS_S, FPS = "30000/1001", 30000 / 1001
# The exposure at the pose, in stops (AgX, as the whole shot): measured on a 2560x1440 render of each pose frame,
# swept offline from its scene-linear EXR with the engine's own A7 (work/v5c/a7full-*, 2026-10-26). RW keeps the
# metered +1.0 (its type reads 233 against the scan's 229; A7 0.96 there). A white page needs its paper at the scan's
# white: +3.75 (S-130, paper 254.5 of 255) and +3.25 (S-16928, 253.7), each the A7 minimum under AgX.
POSE_EV = {RW: None, "S-130": 3.75, "S-16928": 3.25}
SAMPLING = {"samples": 512, "threshold": 0.02, "min_samples": 64}     # the prefix's own (final-v5c-report.json)
LOG = None
TITLE_RECORDS = json.loads((HERE.parent / "title.json").read_text(encoding="utf-8"))["records"]


def log(msg, **kv):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}" + (" " + json.dumps(kv, default=str) if kv else "")
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def runs(frames):
    """Sorted frame numbers as contiguous (first, last) runs."""
    fs = sorted(set(frames))
    out = []
    for f in fs:
        if out and f == out[-1][1] + 1:
            out[-1][1] = f
        else:
            out.append([f, f])
    return [tuple(r) for r in out]


def plan(rec, bake, rest_s, meter):
    """What this film renders: its frames, the frames to redo, the exposure, the pose."""
    fr = SH.shot(bake, FPS, rest_s, rec)
    fr_rw = SH.shot(bake, FPS, rest_s, RW)
    z = C.felt_top() + C.ITEMS["record"]["h"]
    n = len(fr)
    k_from = next(i for i, f in enumerate(fr) if f["end"] >= 1.0)
    seen = SH.rect_seen(fr, C.record_rect(rec), z) > 0
    seen_rw = SH.rect_seen(fr_rw, C.record_rect(RW), z) > 0
    redo = {f for f in range(n) if seen[f] or seen_rw[f]}
    moved = [f for f in range(n) if not (np.array_equal(fr[f]["eye"], fr_rw[f]["eye"])
                                         and np.array_equal(fr[f]["tgt"], fr_rw[f]["tgt"]))]
    redo |= set(moved)
    delta = 0.0 if POSE_EV[rec] is None else POSE_EV[rec] - meter[k_from]
    ev, f_ev = SH.ease_exposure(meter, k_from, delta, FPS)
    redo |= set(range(f_ev, n)) if delta else set()
    cover = SH.rect_cover(fr, C.record_rect(rec), z)
    r0 = int(next(i for i in range(n) if i >= SH.tail_from(fr) and cover[i] >= 0.5))
    return {"n": n, "k_from": k_from, "redo": sorted(redo), "runs": runs(redo), "ev": ev, "ev_from": f_ev,
            "delta": delta, "record_from": r0, "moved_from": moved[0] if moved else None}


def blender(args, tag, out_dir):
    env = dict(os.environ, TEMP=str(MEDIA / "tmp"), TMP=str(MEDIA / "tmp"))
    for k in range(4):
        ram, c = RL.free_gb()
        while ram < 6 or c < 6:
            log("machine short; waiting", ram_gb=round(ram, 1), c_gb=round(c, 1))
            time.sleep(60)
            ram, c = RL.free_gb()
        t0 = time.time()
        p = subprocess.run([BLENDER, "-b", "--factory-startup", "--python", str(HERE / "scene_v5c.py"), "--"] + args,
                           capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
        (out_dir.parent / f"blender-{tag}.log").write_text(p.stdout[-200000:] + "\n" + p.stderr[-50000:], encoding="utf-8")
        if p.returncode == 0 and any(ln.startswith("V5C-DONE ") for ln in p.stdout.splitlines()):
            return round(time.time() - t0, 1)
        log(f"blender {tag} failed (attempt {k + 1})", code=p.returncode, tail=p.stderr[-300:])
        for f in out_dir.glob("*.png"):
            if f.stat().st_size == 0:
                f.unlink()
    raise SystemExit(f"blender {tag} failed 4 times")


def frame_path(f, redo, tail_dir):
    return (tail_dir if f in redo else BASE / "frames-2560") / f"{f:05d}.png"


def encode(n, redo, tail_dir, master, preview):
    """The master: every frame from the film's tail or the shared prefix, piped as RGB, Lanczos to 1920x1080."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "2560x1440", "-framerate",
           FPS_S, "-i", "-", "-vf", "scale=1920:1080:flags=lanczos", "-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt",
           "yuv422p10le", "-r", FPS_S, str(master)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for f in range(n):
        p.stdin.write(np.asarray(Image.open(frame_path(f, redo, tail_dir)).convert("RGB")).tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise SystemExit("ffmpeg master failed")
    kbps = int(30 * 8 * 1024 * 0.92 / (n / FPS))
    for _ in range(3):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(master), "-c:v", "libx264", "-preset", "slow",
                        "-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.3)}k", "-bufsize", f"{kbps * 2}k", "-pix_fmt",
                        "yuv420p", "-r", FPS_S, "-movflags", "+faststart", str(preview)], check=True)
        if preview.stat().st_size <= 30 * 1024 * 1024:
            break
        kbps = int(kbps * 0.85)


def a7_master(master, rec, frames):
    from studio.engine import titles as TT
    man = json.loads(Path("D:/document-media/title-sequence/chart/tex-manifest.json").read_text(encoding="utf-8"))
    scan = man[C.RECORDS[rec]["tex"]]["tex"]["file"]
    win = list(C.record_window(rec))
    out = {"window": win, "by_frame": {}}
    for k in frames:
        arr = TT.read_frame("ffmpeg", str(master), k, fps=FPS)
        out["by_frame"][k] = {"a7": round(TT.record_difference(arr, scan, win), 3),
                              "edge_strips": round(TT.pose_edge_difference(arr, scan, win), 2)}
    out["a7"] = max(v["a7"] for v in out["by_frame"].values())
    out["edge_strips"] = max(v["edge_strips"] for v in out["by_frame"].values())
    out["pass"] = out["a7"] <= TT.RECORD_LIMIT and out["edge_strips"] <= TT.POSE_EDGE_LIMIT
    return out


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main(argv=None):
    global LOG
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", required=True, choices=sorted(C.RECORDS))
    ap.add_argument("--plan-only", action="store_true")
    a = ap.parse_args(argv)
    rec = a.record
    out = BASE / rec
    out.mkdir(parents=True, exist_ok=True)
    LOG = out / "tail.log"
    rep_sim = json.loads((MEDIA / "sim" / "v5c" / "run-timing.json").read_text(encoding="utf-8"))
    bake = json.loads((MEDIA / "sim" / "v5c" / "run-bake.json").read_text(encoding="utf-8"))
    meter = json.loads((BASE / "exposure.json").read_text(encoding="utf-8"))["ev"]
    P = plan(rec, bake, rep_sim["rest_sim_s"], meter)
    log("plan", record=rec, frames=P["n"], redo=len(P["redo"]), runs=P["runs"], k_from=P["k_from"],
        ev_from=P["ev_from"], delta=round(P["delta"], 3), record_from=P["record_from"])
    if a.plan_only:
        return P
    expo = out / "exposure.json"
    expo.write_text(json.dumps({"ev": P["ev"], "base": str(BASE / "exposure.json"), "pose_ev": POSE_EV[rec],
                                "eased_from": P["ev_from"], "k_from": P["k_from"]}), encoding="utf-8")
    tail_dir, exr_dir = out / "tail-2560", out / "tail-exr"
    tail_dir.mkdir(exist_ok=True)
    exr_dir.mkdir(exist_ok=True)
    RL.take_lock(f"The Run v5c tail {rec} ({len(P['redo'])} frames)")
    try:
        for _pass in range(2):                 # a PNG that does not decode is deleted and rendered again
            for f in P["redo"]:
                p = tail_dir / f"{f:05d}.png"
                if p.exists():
                    try:
                        Image.open(p).load()
                    except Exception as e:
                        log("unreadable frame removed", frame=f, error=str(e)[:80])
                        p.unlink()
            render_runs(P, tail_dir, exr_dir, expo, rec)
    finally:
        RL.drop_lock()
    missing = [f for f in P["redo"] if not (tail_dir / f"{f:05d}.png").exists()]
    if missing:
        raise SystemExit(f"missing tail frames {missing[:10]}")
    return finish(P, rec, out, tail_dir)


def render_runs(P, tail_dir, exr_dir, expo, rec):
    for f0, f1 in P["runs"]:
        if all((tail_dir / f"{f:05d}.png").exists() and (tail_dir / f"{f:05d}.png").stat().st_size > 0
               for f in range(f0, f1 + 1)):
            continue
        wall = blender(["--fps", FPS_S, "--frames", f"{f0}:{f1}", "--res", "2560x1440", "--samples",
                        str(SAMPLING["samples"]), "--threshold", str(SAMPLING["threshold"]), "--min_samples",
                        str(SAMPLING["min_samples"]), "--blur", "1", "--expo", str(expo), "--record", rec,
                        "--out", str(tail_dir), "--exr", str(exr_dir)], f"{f0}-{f1}", tail_dir)
        log("rendered", run=[f0, f1], wall_s=wall, s_per_frame=round(wall / (f1 - f0 + 1), 1))


def finish(P, rec, out, tail_dir):
    master = out / f"the-run-v5c-{rec}-2997.mov"
    preview = out / f"the-run-v5c-{rec}-2997-preview.mp4"
    encode(P["n"], set(P["redo"]), tail_dir, master, preview)
    last = P["n"] - 1
    a7 = a7_master(master, rec, sorted({P["k_from"], (P["k_from"] + last) // 2, last}))
    log("a7", **a7)
    wav = out / f"the-run-v5c-{rec}-2997.foley.wav"
    subprocess.run([VENV_PY, str(HERE / "foley_v5c.py"), "--record", rec, "--out", str(wav)], check=True)
    sound = out / f"the-run-v5c-{rec}-2997-sound.mov"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(master), "-i", str(wav), "-map", "0:v:0", "-map",
                    "1:a:0", "-c:v", "copy", "-c:a", "pcm_s16le", "-shortest", str(sound)], check=True)
    r = C.RECORDS[rec]
    item = {"id": f"TS-v5c-{rec}", "file": sound.name, "record": rec, "fps": FPS_S, "width": 1920, "height": 1080,
            "frames": P["n"], "denoise": False, "burned": False,
            "record_frames": [P["record_from"], last],
            "record_pose": {"window": [round(v, 6) for v in C.record_window(rec)], "from_frame": P["k_from"]},
            "marks": [{"frame": 0, "cls": "DRAWN", "label": "Drawn · from period records"},
                      {"frame": P["record_from"], "cls": r["cls"], "label": TITLE_RECORDS[rec]["label"]}],
            "renderer": f"Blender 4.4.3 Cycles (OptiX), adaptive sampling {SAMPLING['samples']} spp, noise threshold "
                        f"{SAMPLING['threshold']}, no denoiser", "bytes": sound.stat().st_size, "sha256": sha256(sound)}
    report = {"record": rec, "plan": {k: v for k, v in P.items() if k not in ("ev", "redo")}, "a7": a7,
              "master": str(master), "sound_master": str(sound), "preview": str(preview), "foley": str(wav),
              "runtime_s": round(P["n"] / FPS, 3), "item": item}
    (out / "tail-report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    log("tail done", a7=a7["a7"], edges=a7["edge_strips"], passed=a7["pass"], master=str(sound))
    return report


if __name__ == "__main__":
    main()
