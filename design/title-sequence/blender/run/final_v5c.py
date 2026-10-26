"""The Run v5c: the final, as one detached job (runs in the D: venv; one heavy job at a time behind HEAVY.lock).

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/final_v5c.py \
        [--fps 30000/1001] [--profile final_hq] [--record C20-METAR-0851] [--deadline 07:30]

1. The camera's exposure, metered outside Blender: a low-sample pass of every 6th frame, centre-weighted on the frame
   (the marble is framed at its centre), eased (0.6 s) and slewed at most one stop a second, keyed per frame.
2. A probe of the first 20 frames at the profile's settings; the measured seconds a frame set the ETA. If the whole shot
   would not finish by the deadline, the sampling is lowered (512 spp at 0.02, then 256 at 0.03) and the choice logged;
   the probe frames are then re-rendered with the rest so the grain is one grain.
3. The whole shot at 2560x1440 (Cycles, adaptive sampling, NO denoiser), resumable frame by frame.
4. A classical Lanczos downscale to 1920x1080, the 29.97 master (ProRes 422 HQ) and an H.264 preview of at most 30 MB.
5. A7 on the last frame against the record's own image (the record's pose: the whole 16:9 sheet).
Everything goes to D:/document-media/title-sequence/run/masters/final-v5c/, the log to final-v5c.log there.
"""

from __future__ import annotations

import argparse
import datetime as dt
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
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[3]))
import render_still_v5 as RL  # noqa: E402  (the lock, the machine checks)

BLENDER = "D:/document-media/tools/blender-4.4.3-windows-x64/blender.exe"
MEDIA = Path("D:/document-media/title-sequence/run")
TITLE = HERE.parent / "title.json"
TARGET = 0.11
LOG = None


def log(msg, **kv):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}" + (" " + json.dumps(kv, default=str) if kv else "")
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def machine_ok():
    ram, c = RL.free_gb()
    return ram >= 6 and c >= 6, {"ram_gb": round(ram, 1), "c_gb": round(c, 1)}


def blender(args, tag, retries=3):
    env = dict(os.environ, TEMP=str(MEDIA / "tmp"), TMP=str(MEDIA / "tmp"))
    for k in range(retries):
        ok, m = machine_ok()
        while not ok:
            log("machine short; waiting", **m)
            time.sleep(60)
            ok, m = machine_ok()
        t0 = time.time()
        p = subprocess.run([BLENDER, "-b", "--factory-startup", "--python", str(HERE / "scene_v5c.py"), "--"] + args,
                           capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
        (OUT / f"blender-{tag}.log").write_text(p.stdout[-200000:] + "\n" + p.stderr[-50000:], encoding="utf-8")
        build = [json.loads(ln[10:]) for ln in p.stdout.splitlines() if ln.startswith("V5C-BUILD ")]
        if p.returncode == 0 and any(ln.startswith("V5C-DONE ") for ln in p.stdout.splitlines()):
            return {"wall_s": round(time.time() - t0, 1), "build": build[0] if build else None}
        log(f"blender {tag} failed (attempt {k + 1})", code=p.returncode, tail=p.stderr[-400:])
        out_dir = Path(args[args.index("--out") + 1])
        for f in out_dir.glob("*.png"):
            if f.stat().st_size == 0:
                f.unlink()                    # a placeholder left by the crash: render it again
    raise SystemExit(f"blender {tag} failed {retries} times")


def lin(png):
    a = np.asarray(Image.open(png).convert("RGB"), np.float32) / 255.0
    return np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)


def meter_value(png):
    L = lin(png)
    Y = 0.2126 * L[..., 0] + 0.7152 * L[..., 1] + 0.0722 * L[..., 2]
    h, w = Y.shape
    yy, xx = np.mgrid[0:h, 0:w]
    wgt = np.exp(-(((xx - w / 2) / (0.30 * w)) ** 2 + ((yy - h / 2) / (0.30 * h)) ** 2))
    return float((Y * wgt).sum() / wgt.sum())


def exposure_curve(samples, n, fps, ease_s=0.6, slew=1.0, clamp=3.0):
    """Per-frame EV from metered (frame, value) samples: aim at TARGET, interpolate, ease (a Gaussian of ease_s / 2),
    then limit the change to `slew` stops a second, both ways (a camera's auto-exposure, deterministic)."""
    fs = np.array([f for f, _ in samples], float)
    ev = np.array([math.log2(TARGET / max(v, 1e-6)) for _, v in samples])
    ev = np.clip(ev, -clamp, clamp)
    e = np.interp(np.arange(n), fs, ev)
    sig = ease_s / 2 * fps
    k = np.exp(-0.5 * (np.arange(-int(3 * sig), int(3 * sig) + 1) / sig) ** 2)
    k /= k.sum()
    pad = np.pad(e, (len(k) // 2, len(k) // 2), mode="edge")
    e = np.convolve(pad, k, mode="valid")
    lim = slew / fps
    for i in range(1, n):
        e[i] = min(max(e[i], e[i - 1] - lim), e[i - 1] + lim)
    for i in range(n - 2, -1, -1):
        e[i] = min(max(e[i], e[i + 1] - lim), e[i + 1] + lim)
    return [round(float(x), 4) for x in e]


def a7(png, rec):
    from studio.engine import titles as TT
    man = json.loads(Path("D:/document-media/title-sequence/chart/tex-manifest.json").read_text(encoding="utf-8"))
    path = man[f"R-{rec}"]["tex"]["file"]
    arr = np.asarray(Image.open(png).convert("RGB").resize((1920, 1080), Image.LANCZOS))
    win = [0.0, 0.0, 1.0, 1.0]
    return {"a7": round(float(TT.record_difference(arr, path, win)), 3),
            "edge_strips": round(float(TT.pose_edge_difference(arr, path, win)), 3), "window": win}


def deadline_ts(hhmm):
    now = dt.datetime.now()
    h, m = (int(v) for v in hhmm.split(":"))
    d = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if d <= now:
        d += dt.timedelta(days=1)
    return d.timestamp()


OUT = MEDIA / "masters" / "final-v5c"


def main(argv=None):
    global LOG
    ap = argparse.ArgumentParser()
    ap.add_argument("--fps", default="30000/1001")
    ap.add_argument("--profile", default="final_hq")
    ap.add_argument("--record", default="C20-METAR-0851")
    ap.add_argument("--deadline", default="07:30")
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    LOG = OUT / "final-v5c.log"
    num, den = (int(v) for v in a.fps.split("/")) if "/" in a.fps else (int(float(a.fps)), 1)
    fps = num / den
    prof = json.loads(TITLE.read_text(encoding="utf-8"))["render"][a.profile]
    assert prof.get("use_denoising", False) is False, "no denoiser (founder ruling)"
    rep_sim = json.loads((MEDIA / "sim" / "v5c" / "run-timing.json").read_text(encoding="utf-8"))
    n = int(math.ceil((rep_sim["rest_sim_s"] + 5.0) * fps))
    last = n - 1
    log("final v5c start", pid=os.getpid(), fps=a.fps, profile=a.profile, record=a.record, frames=n,
        runtime_s=round(n / fps, 3), deadline=a.deadline)
    RL.take_lock(f"final v5c {a.record} {a.fps}")
    report = {"fps": a.fps, "frames": n, "record": a.record, "profile": a.profile}
    try:
        common = ["--fps", a.fps, "--frames", f"0:{last}"]
        # 1. the meter
        mdir = OUT / "meter"
        mdir.mkdir(exist_ok=True)
        r = blender(common + ["--res", "480x270", "--samples", "24", "--threshold", "0.05", "--min_samples", "8",
                              "--step", "6", "--blur", "0", "--exposure", "0.0", "--out", str(mdir)], "meter")
        samples = sorted((int(p.stem), meter_value(p)) for p in mdir.glob("*.png") if p.stat().st_size > 0)
        ev = exposure_curve(samples, n, fps)
        expo = OUT / "exposure.json"
        expo.write_text(json.dumps({"ev": ev, "meter": samples, "target": TARGET, "ease_s": 0.6, "slew_stops_s": 1.0}),
                        encoding="utf-8")
        log("meter done", wall_s=r["wall_s"], n=len(samples), ev_range=[min(ev), max(ev)])
        # 2. the probe
        res = "x".join(str(v) for v in prof["res"])
        spp, thr, mn = prof["samples"], prof["noise_threshold"], prof["min_samples"]
        fdir = OUT / "frames-2560"
        fdir.mkdir(exist_ok=True)
        blur = "1" if prof.get("motion_blur", True) else "0"

        def render(f0, f1, spp_, thr_, tag):
            return blender(["--fps", a.fps, "--frames", f"{f0}:{f1}", "--res", res, "--samples", str(spp_), "--threshold",
                            str(thr_), "--min_samples", str(mn), "--blur", blur, "--expo", str(expo), "--out", str(fdir)],
                           tag)

        r = render(0, 19, spp, thr, "probe")
        build_s = (r["build"] or {}).get("build_s", 60.0)
        spf = max((r["wall_s"] - build_s - 15.0) / 20.0, 0.5)
        eta = time.time() + spf * (n - 20) + 120
        log("probe done", s_per_frame=round(spf, 1), eta=time.strftime("%H:%M", time.localtime(eta)), spp=spp, thr=thr)
        choice = {"samples": spp, "threshold": thr, "s_per_frame_probe": round(spf, 1)}
        if eta > deadline_ts(a.deadline):
            for spp2, thr2, scale in ((512, 0.02, 0.45), (256, 0.03, 0.25), (128, 0.05, 0.14)):
                est = time.time() + spf * scale * n + 180
                if est <= deadline_ts(a.deadline) or spp2 == 128:
                    choice = {"samples": spp2, "threshold": thr2, "s_per_frame_probe": round(spf, 1),
                              "estimated_s_per_frame": round(spf * scale, 1),
                              "why": f"the profile ({spp} spp, {thr}) would end at "
                                     f"{time.strftime('%H:%M', time.localtime(eta))}, after the {a.deadline} deadline"}
                    break
            for f in fdir.glob("*.png"):
                f.unlink()
            log("sampling lowered to meet the morning", **choice)
        report["sampling"] = choice
        # 3. the whole shot (resumable: frames already on disk are kept)
        r = render(0, last, choice["samples"], choice["threshold"], "whole")
        done = sorted(p for p in fdir.glob("*.png") if p.stat().st_size > 0)
        log("render done", wall_s=r["wall_s"], frames=len(done))
        if len(done) < n:
            raise SystemExit(f"only {len(done)} of {n} frames")
    finally:
        RL.drop_lock()
    # 4. downscale and the masters (ffmpeg, a classical Lanczos resample)
    src = str(fdir / "%05d.png")
    master = OUT / f"the-run-v5c-{a.record}-2997.mov"
    prev = OUT / f"the-run-v5c-{a.record}-2997-preview.mp4"
    vf = "scale=1920:1080:flags=lanczos"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", a.fps, "-i", src, "-vf", vf, "-c:v", "prores_ks",
                    "-profile:v", "3", "-pix_fmt", "yuv422p10le", "-r", a.fps, str(master)], check=True)
    kbps = int(30 * 8 * 1024 * 0.92 / (n / fps))
    for k in range(3):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", a.fps, "-i", src, "-vf", vf, "-c:v", "libx264",
                        "-preset", "slow", "-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.3)}k", "-bufsize",
                        f"{kbps * 2}k", "-pix_fmt", "yuv420p", "-r", a.fps, "-movflags", "+faststart", str(prev)],
                       check=True)
        if prev.stat().st_size <= 30 * 1024 * 1024:
            break
        kbps = int(kbps * 0.85)
    report.update({"master": str(master), "preview": str(prev), "preview_mb": round(prev.stat().st_size / 2 ** 20, 2),
                   "runtime_s": round(n / fps, 3), "denoise": False,
                   "renderer": f"Blender 4.4.3 Cycles (OptiX), adaptive sampling {choice['samples']} spp, noise threshold "
                               f"{choice['threshold']}, no denoiser"})
    # 5. A7 on the last frame
    try:
        report["a7"] = a7(fdir / f"{last:05d}.png", a.record)
    except Exception as e:  # reported, not hidden
        report["a7"] = {"error": str(e)[:300]}
    (OUT / "final-v5c-report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    log("final v5c done", **report)


if __name__ == "__main__":
    main()
