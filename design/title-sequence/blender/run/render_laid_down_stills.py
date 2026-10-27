"""Laid Down: render the lit stills for the founder's judgement under the machine rules (D: venv; one heavy job).

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/render_laid_down_stills.py \
        [--smoke] [--frames 708,54] [--samples 1024] [--min_samples 512] [--threshold 0.005]

Before anything: D: must not be dirty (`fsutil dirty query D:`) and C: and D: must each have more than 10 GB free.
For each still: wait while HEAVY.lock is held by a live process (the coordinator's renders go first; a lock held by a
dead pid is cleared), write this job's purpose and pid into it, run Blender (-noaudio), and release the lock in a
finally, so another job can take it between stills. The first frame (708 in rev 3, the pile complete) runs with the
meter: its exposure puts the brightest paper's brightest channel at 0.85; the others (--frames, default 708,54) take
that exposure, since it is fixed for the shot; it is also written to exposure.json for the animatic. Writes D:/document-media/title-sequence/laid-down/stills/
laid-down-f<frame>.png (1920x1080, 16-bit), a 50% JPG of each under 2 MB, and stills.json.
--smoke: the same frames at 480x270, 16 spp, to D:/document-media/title-sequence/laid-down/smoke/.
"""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
BLENDER = "D:/document-media/tools/blender-4.4.3-windows-x64/blender.exe"
LOCK = Path("C:/Users/aacri/document-work/HEAVY.lock")
ROOT = Path("D:/document-media/title-sequence/laid-down")
JPG_MAX = 2 * 1024 * 1024
MIN_FREE_GB = 10.0


def arg(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def pid_alive(pid):
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
    if not h:
        return False
    code = ctypes.c_ulong()
    ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(h)
    return code.value == 259


def preflight():
    q = subprocess.run(["fsutil", "dirty", "query", "D:"], capture_output=True, text=True)
    if q.returncode != 0 or "NOT Dirty" not in q.stdout:
        raise SystemExit(f"refused: D: dirty bit query: {q.stdout.strip() or q.stderr.strip()}")
    free = {d: shutil.disk_usage(f"{d}:/").free / 2 ** 30 for d in ("C", "D")}
    if min(free.values()) <= MIN_FREE_GB:
        raise SystemExit(f"refused: free disk {free} (each must be above {MIN_FREE_GB} GB)")
    return free


def parse_lock(text):
    """HEAVY.lock in either form the house writes: JSON, or key=value lines (purpose, pid, started)."""
    try:
        d = json.loads(text)
        if isinstance(d, dict):
            return d
    except ValueError:
        pass
    out = {}
    for ln in text.splitlines():
        if "=" in ln:
            k, v = ln.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def read_lock():
    try:
        return parse_lock(LOCK.read_text(encoding="utf-8"))
    except OSError:
        return {}


def take_lock(job, log=print):
    """Wait while a live process holds HEAVY.lock (a lock whose pid is dead is cleared; one with no readable pid is
    waited on, never broken), then write this job's purpose and pid into it."""
    while LOCK.exists():
        held = read_lock()
        pid = held.get("pid")
        if pid and str(pid).isdigit() and not pid_alive(int(pid)):
            log(f"HEAVY.lock held by dead pid {pid}: cleared")
            LOCK.unlink(missing_ok=True)
            break
        log(f"HEAVY.lock held by {held}; waiting")
        time.sleep(30)
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(json.dumps({"group": "title: Laid Down (t/laid-down)", "job": job, "purpose": job,
                                "pid": os.getpid(), "started": time.strftime("%Y-%m-%dT%H:%M:%S")}), encoding="utf-8")


def drop_lock():
    try:
        if LOCK.exists() and str(read_lock().get("pid")) == str(os.getpid()):
            LOCK.unlink()
    except OSError:
        pass


def blender(frame, out, res, samples, min_samples, threshold, exposure=0.0, meter=False):
    cmd = [BLENDER, "-b", "-noaudio", "--factory-startup", "--python", str(HERE / "scene_laid_down.py"), "--",
           "--frame", str(frame), "--res", res, "--samples", str(samples), "--min_samples", str(min_samples),
           "--threshold", str(threshold), "--exposure", f"{exposure:.4f}", "--out", str(out),
           "--meter", "1" if meter else "0", "--record", "C20-METAR-0851"]
    env = dict(os.environ, TEMP=str(ROOT / "tmp"), TMP=str(ROOT / "tmp"))
    (ROOT / "tmp").mkdir(parents=True, exist_ok=True)
    take_lock(f"Laid Down still f{frame} {res} {samples} spp")
    try:
        t0 = time.time()
        p = subprocess.run(cmd, capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    finally:
        drop_lock()
    log = out.with_suffix(".log")
    log.write_text(p.stdout + "\n" + p.stderr, encoding="utf-8")
    info = None
    for ln in p.stdout.splitlines():
        if ln.startswith("LD-STILL "):
            info = json.loads(ln[9:])
    if p.returncode != 0 or info is None:
        raise SystemExit(f"blender failed ({p.returncode}); log in {log}")
    info["wall_s"] = round(time.time() - t0, 1)
    return info


def half_jpg(png):
    """A 50% JPG under 2 MB (Lanczos, a classical resample), quality stepped down only if it must be."""
    im = Image.open(png).convert("RGB")
    small = im.resize((im.width // 2, im.height // 2), Image.LANCZOS)
    jp = png.with_name(png.stem + "-50.jpg")
    for q in (92, 88, 84, 80, 75):
        small.save(jp, quality=q, subsampling=0 if q >= 88 else 2, optimize=True)
        if jp.stat().st_size < JPG_MAX:
            return jp, q
    raise SystemExit(f"{jp} stays over 2 MB")


def main():
    free = preflight()
    smoke = "--smoke" in sys.argv
    out = ROOT / ("smoke" if smoke else "stills")
    out.mkdir(parents=True, exist_ok=True)
    res = "480x270" if smoke else "1920x1080"
    spp = 16 if smoke else int(arg("--samples", "1024"))
    mn = 16 if smoke else int(arg("--min_samples", "512"))
    th = 0.05 if smoke else float(arg("--threshold", "0.005"))
    rec = {"free_gb": free, "stills": []}
    # rev 3: the pile complete (f708) carries the meter; the opening, the Atlas nearly at rest (f54)
    frames = [int(f) for f in arg("--frames", "708,54").split(",")]
    a = blender(frames[0], out / f"laid-down-f{frames[0]:04d}.png", res, spp, mn, th, meter=True)
    rec["stills"].append(a)
    ev = a["exposure"]
    for f in frames[1:]:
        rec["stills"].append(blender(f, out / f"laid-down-f{f:04d}.png", res, spp, mn, th, exposure=ev))
    for s in rec["stills"]:
        jp, q = half_jpg(Path(s["out"]))
        s["jpg"], s["jpg_quality"], s["jpg_bytes"] = str(jp), q, jp.stat().st_size
    (out / "stills.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    if not smoke:
        (ROOT / "exposure.json").write_text(json.dumps({"ev": ev, "metered_on_frame": frames[0], "meter": a.get("meter"),
                                                        "rule": "max(R,G,B) 99.5th percentile at 0.85 of white"},
                                                       indent=1), encoding="utf-8")
    for s in rec["stills"]:
        print(f"f{s['frame']}: {s['out']} render {s['render_s']} s (wall {s['wall_s']} s), EV {s['exposure']:+.3f}, "
              f"jpg {s['jpg_bytes'] / 1e6:.2f} MB q{s['jpg_quality']}")


if __name__ == "__main__":
    main()
