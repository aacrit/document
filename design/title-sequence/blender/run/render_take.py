"""The Run, the full take: build, render, sound and assemble under the machine governor (runs in the D: venv).

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/render_take.py \
        --record C20-METAR-0851 --fps 24 --calib --tag anim1          # the M1 animatic (640x360, 48 samples)

Every render goes through render_run.render: D: not dirty, 20 GB free, HEAVY.lock and any other Blender, film render,
pytest or Orpheus waited out, the lock named for the job and deleted the moment it ends, OptiX confirmed. The frames
render in chunks; between chunks the lock is released and the driver pauses, so another group waiting on the lock
(WG-2's proofs) takes its turn before the next chunk. Frames go to a fresh folder per tag (render_run skips existing
PNGs, so a reused folder would encode stale frames): D:/document-media/title-sequence/run/frames/<tag>/{prefix,tail-<record>}.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bench as B  # noqa: E402
import render_run as RR  # noqa: E402

MEDIA = RR.MEDIA
CHUNK = 160
PAUSE_S = 45


def build(window, rec, fps, calib, out, res=""):
    args = [RR.BL, "--background", "--factory-startup", "--python", str(HERE / "run_take.py"), "--",
            "--window", window, "--record", rec, "--fps", fps, "--out", str(out).replace("\\", "/")]
    if calib:
        args += ["--calib", "1"]
    if res:
        args += ["--res", res]
    # building the scene is a heavy step too: under the lock, with the machine checked
    while True:
        RR.wait_clear()
        ok, why = RR.machine_ok()
        if ok:
            break
        print(f"waiting on the machine: {why}", flush=True)
        time.sleep(180)
    RR.MY_LOCK.write_text(json.dumps({"group": "WG-4", "job": f"The Run (build {window})", "pid": os.getpid()}), encoding="utf-8")
    try:
        r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=RR.REPO, env=RR.d_env())
    finally:
        RR.MY_LOCK.unlink(missing_ok=True)
    m = re.search(r"^RUN-BUILD (.*)$", r.stdout, re.M)
    if r.returncode != 0 or not m:
        sys.exit(f"build {window} failed:\n{r.stdout[-4000:]}\n{r.stderr[-2000:]}")
    info = json.loads(m.group(1))
    RR.log(event="built", window=window, record=rec, fps=fps, blend=str(out), info=info)
    return info


def render_chunks(blend, out_dir, f0, f1, label):
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = []
    f = f0
    while f <= f1:
        g = min(f + CHUNK - 1, f1)
        todo = [k for k in range(f, g + 1) if not (out_dir / f"{k:04d}.png").exists()]
        if todo:
            if not RR.c_free_ok():
                sys.exit(f"C: is under {RR.C_MIN_GB} GB free before chunk {todo[0]}: stopped (report to the coordinator)")
            times = RR.render(blend, out_dir, list(range(todo[0], g + 1)), f"{label}-{todo[0]}")
            stats.append({"frames": [todo[0], g], "mean_s": round(sum(times) / len(times), 2) if times else None})
            if g < f1:
                time.sleep(PAUSE_S)       # the lock is free: a waiting group takes its turn before the next chunk
        f = g + 1
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", default="C20-METAR-0851")
    ap.add_argument("--fps", default="24")
    ap.add_argument("--calib", action="store_true")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--size", default="")
    ap.add_argument("--skip-prefix", action="store_true")
    ap.add_argument("--res", default="", help="calib resolution, e.g. 854x480 (the 8a animatic)")
    a = ap.parse_args()
    rec, fps = a.record, a.fps
    base = MEDIA / "frames" / a.tag
    blend_dir = MEDIA / "blend" / a.tag
    blend_dir.mkdir(parents=True, exist_ok=True)
    suffix = fps.replace("/", "_")
    pre_dir, tail_dir = base / f"prefix-{suffix}", base / f"tail-{rec}-{suffix}"
    all_stats = {}
    if not a.skip_prefix:
        bp = blend_dir / f"prefix-{suffix}.blend"
        info = build("prefix", rec, fps, a.calib, bp, a.res)
        all_stats["prefix"] = render_chunks(bp, pre_dir, *info["frames"], f"{a.tag}-prefix")
    bt = blend_dir / f"tail-{rec}-{suffix}.blend"
    info = build("tail", rec, fps, a.calib, bt, a.res)
    all_stats["tail"] = render_chunks(bt, tail_dir, *info["frames"], f"{a.tag}-tail")
    snd = MEDIA / "masters" / a.tag
    r = subprocess.run([RR.VPY, str(HERE / "foley_take.py"), "--record", rec, "--out-dir", str(snd)],
                       capture_output=True, text=True, cwd=RR.REPO, env=RR.d_env())
    if r.returncode != 0:
        sys.exit(f"foley failed:\n{r.stdout[-2000:]}\n{r.stderr[-3000:]}")
    RR.log(event="foley", record=rec, report=r.stdout.strip().splitlines()[-1][:1500])
    size = a.size or a.res or ("640x360" if a.calib else "1920x1080")
    mp4 = snd / f"the-run-{a.tag}-{rec}-{suffix}.mp4"
    r = subprocess.run([RR.VPY, str(HERE / "assemble_take.py"), "--record", rec, "--fps", fps, "--size", size,
                        "--prefix", str(pre_dir), "--tail", str(tail_dir), "--audio", str(snd / "title.review-mix.wav"),
                        "--mp4", str(mp4), "--keep", str(base / f"comp-{rec}-{suffix}")],
                       capture_output=True, text=True, cwd=RR.REPO, env=RR.d_env())
    if r.returncode != 0:
        sys.exit(f"assemble failed:\n{r.stdout[-2000:]}\n{r.stderr[-3000:]}")
    RR.log(event="assembled", mp4=str(mp4), stats=all_stats, info=r.stdout.strip().splitlines()[-1][:1500])
    print("DONE", mp4)


if __name__ == "__main__":
    main()
