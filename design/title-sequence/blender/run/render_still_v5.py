"""The Run v5: render the two lit stills under the machine rules (runs in the D: venv; one heavy job at a time).

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/render_still_v5.py [--view mid|top|both]

For each view: wait for HEAVY.lock to be free (or held by a dead PID), check free RAM and C: (6 GB each), take the lock,
then (1) a meter pass at 640x360 and exposure 0, metered outside Blender the way the camera's auto-exposure will be
(centre-weighted, on the lead for the follow view, in scene-linear from the sRGB-decoded frame), (2) the still at
2560x1440 with that exposure, Cycles adaptive sampling, no denoiser, (3) a Lanczos downscale to 1920x1080 (a classical
resample). The lock is released after each Blender run. Writes D:/document-media/title-sequence/run/layout/
v5-lit-still.png (mid) and v5-lit-wide.png (top), and their 2560x1440 masters beside them, and a JSON record.
"""

from __future__ import annotations

import ctypes
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
BLENDER = "D:/document-media/tools/blender-4.4.3-windows-x64/blender.exe"
LOCK = Path("C:/Users/aacri/document-work/HEAVY.lock")
OUT = Path("D:/document-media/title-sequence/run/layout")
LOG = OUT / "v5-still-log.jsonl"
NAMES = {"mid": "v5-lit-still", "top": "v5-lit-wide"}
TARGET = 0.11          # the meter's aim: centre-weighted scene-linear mean (a lamplit, low-key frame)
CLAMP = 3.0


def free_gb():
    class MS(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong), ("a", ctypes.c_ulonglong), ("b", ctypes.c_ulonglong),
                    ("c", ctypes.c_ulonglong), ("d", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong)]
    m = MS()
    m.dwLength = ctypes.sizeof(MS)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.ullAvailPhys / 2 ** 30, shutil.disk_usage("C:/").free / 2 ** 30


def pid_alive(pid):
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
    if not h:
        return False
    code = ctypes.c_ulong()
    ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(h)
    return code.value == 259


def take_lock(job):
    while LOCK.exists():
        try:
            held = json.loads(LOCK.read_text(encoding="utf-8"))
        except Exception:
            held = {}
        if held.get("pid") and not pid_alive(held["pid"]):
            print(f"lock held by dead pid {held.get('pid')}: cleared")
            LOCK.unlink()
            break
        print(f"HEAVY.lock held by {held}; waiting")
        time.sleep(20)
    ram, c = free_gb()
    if ram < 6 or c < 6:
        raise SystemExit(f"refused: free RAM {ram:.1f} GB, C: {c:.1f} GB (each must be at least 6)")
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(json.dumps({"group": "WG-4 title", "job": job, "pid": os.getpid(),
                                "started": time.strftime("%Y-%m-%dT%H:%M:%S")}), encoding="utf-8")
    return ram, c


def drop_lock():
    try:
        if LOCK.exists() and json.loads(LOCK.read_text(encoding="utf-8")).get("pid") == os.getpid():
            LOCK.unlink()
    except Exception:
        pass


def blender(view, res, samples, threshold, exposure, out, min_samples=128):
    cmd = [BLENDER, "-b", "--factory-startup", "--python", str(HERE / "still_v5.py"), "--", "--view", view, "--res", res,
           "--samples", str(samples), "--threshold", str(threshold), "--exposure", f"{exposure:.3f}", "--out", str(out),
           "--min_samples", str(min_samples)]
    env = dict(os.environ, TEMP="D:/document-media/title-sequence/run/tmp", TMP="D:/document-media/title-sequence/run/tmp")
    take_lock(f"v5 still {view} {res}")
    try:
        t0 = time.time()
        p = subprocess.run(cmd, capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    finally:
        drop_lock()
    info = None
    for ln in p.stdout.splitlines():
        if ln.startswith("V5-STILL "):
            info = json.loads(ln[9:])
    if p.returncode != 0 or info is None:
        (OUT / f"blender-{view}.log").write_text(p.stdout + "\n" + p.stderr, encoding="utf-8")
        raise SystemExit(f"blender failed ({p.returncode}); log in {OUT / f'blender-{view}.log'}")
    info["wall_s"] = round(time.time() - t0, 1)
    return info


def linear(png):
    a = np.asarray(Image.open(png).convert("RGB"), np.float32) / 255.0
    return np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)


def meter(png, view):
    """Centre-weighted (a Gaussian over the middle of the frame; for the follow view centred where the lead is
    framed) mean of scene-linear luminance, as the camera's auto-exposure will meter."""
    lin = linear(png)
    Y = 0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]
    h, w = Y.shape
    yy, xx = np.mgrid[0:h, 0:w]
    s = 0.30 if view == "mid" else 0.45
    wgt = np.exp(-(((xx - w / 2) / (s * w)) ** 2 + ((yy - h / 2) / (s * h)) ** 2))
    return float((Y * wgt).sum() / wgt.sum())


def main():
    view = sys.argv[sys.argv.index("--view") + 1] if "--view" in sys.argv else "both"
    views = ["mid", "top"] if view == "both" else [view]
    OUT.mkdir(parents=True, exist_ok=True)
    for v in views:
        mp = OUT / f"{NAMES[v]}-meter.png"
        mi = blender(v, "640x360", 64, 0.05, 0.0, mp, min_samples=16)
        m = meter(mp, v)
        ev = max(-CLAMP, min(CLAMP, math.log2(TARGET / max(m, 1e-6))))
        # AgX is not linear at the top: one check pass at the metered exposure, then a small trim
        mc = blender(v, "640x360", 64, 0.05, ev, mp, min_samples=16)
        m2 = meter(mp, v) / (2 ** ev)
        ev = max(-CLAMP, min(CLAMP, math.log2(TARGET / max(m2, 1e-6))))
        mp.unlink(missing_ok=True)
        master = OUT / f"{NAMES[v]}-2560.png"
        info = blender(v, "2560x1440", int(os.environ.get("V5_SAMPLES", "2048")),
                       float(os.environ.get("V5_THRESHOLD", "0.004")), ev, master)
        im = Image.open(master)
        im = im.convert("RGB") if im.mode not in ("RGB", "I;16") else im
        Image.open(master).convert("RGB").resize((1920, 1080), Image.LANCZOS).save(OUT / f"{NAMES[v]}.png")
        rec = {"view": v, "meter": [m, m2], "exposure_ev": ev, "meter_pass_s": [mi["wall_s"], mc["wall_s"]],
               "final": info, "out": str(OUT / f"{NAMES[v]}.png"), "master": str(master)}
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        print(json.dumps({k: rec[k] for k in ("view", "meter", "exposure_ev", "out")}), "final", info["wall_s"], "s")


if __name__ == "__main__":
    main()
