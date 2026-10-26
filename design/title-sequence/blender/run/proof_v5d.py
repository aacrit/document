"""The Run v5d: the 480p proof of the whole shot, for the founder's review (one heavy job, behind HEAVY.lock).

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/proof_v5d.py

Not the final. Writes D:/document-media/title-sequence/run/proofs/v5d/:
1. the camera's exposure, metered as v5c's final was (final_v5c: 480x270, 24 spp, every 6th frame, centre-weighted,
   eased 0.6 s, slewed 1 stop/s, clamped 3 stops) through the v5d camera;
2. the whole shot at 854x480 through scene_v5c.py --cam v5d (layout L0, AgX, look None, the one constant lamp, the
   metered exposure keyed per frame, motion blur on), Cycles adaptive sampling at a proof's low spp, NO denoiser,
   the view read back per frame (--vs); and a probe of 8 frames spread over the shot at the final's own settings
   (2560x1440, 512 spp, 0.02, min 64) to measure what the final would cost;
3. v5d-proof-480p.mp4: H.264 at 29.97 (<= 15 MB) muxed with the corrected Foley and the room tone
   (foley_v5c.py --timing sim/v5d), its view sidecar v5d-proof-480p.view.json (document.view/1), the frame sheet of
   every beat at 480p (v5d-frame-sheet-480p.png), the checker's results and proof-report.json.
The lock: waits while HEAVY.lock names a live pid; a lock whose pid is dead is stale and cleared; taken atomically
(purpose, pid, started) and released in a finally.
"""

from __future__ import annotations

import ctypes
import datetime as dt
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import channel_v5c as C  # noqa: E402
import check_v5d as K  # noqa: E402
import shot_v5c as SH  # noqa: E402
import shot_v5d as SD  # noqa: E402

BLENDER = "D:/document-media/tools/blender-4.4.3-windows-x64/blender.exe"
VENV_PY = "D:/document-media/tools/run-venv/Scripts/python.exe"
MEDIA = Path("D:/document-media/title-sequence/run")
OUT = MEDIA / "proofs" / "v5d"
LOCK = Path("C:/Users/aacri/document-work/HEAVY.lock")
FPS_S, FPS = "30000/1001", 30000 / 1001
REC = "C20-METAR-0851"
PROOF = {"res": "854x480", "samples": 128, "threshold": 0.05, "min_samples": 16}
FINAL = {"res": "2560x1440", "samples": 512, "threshold": 0.02, "min_samples": 64}      # tail_v5c.SAMPLING
PROBE_STEP = 149                                      # frames 0, 149, ..., 1043: 8 frames across every posture
MAX_MB = 15.0
# The pose's exposure, carried over from v5c (the A7 calibration). v5c's meter was taken before the record went dead
# matte (872e788), so its pose value is not what a re-meter reads (the v5d meter, same pose camera: +1.76): C20's
# A7 0.39 was measured at v5c's keyed +1.005 at k_from 1061, and S-130 / S-16928 at tail_v5c.POSE_EV. Each film's
# exposure eases onto its value at <= 1 stop/s (shot_v5c.ease_exposure) and holds it, as tail_v5c does.
POSE_EV_V5D = {"C20-METAR-0851": 1.005, "S-130": 3.75, "S-16928": 3.25}
LOG = OUT / "proof-v5d.log"


def log(msg, **kv):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}" + (" " + json.dumps(kv, default=str) if kv else "")
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


# ------------------------------------------------------------------------------------------------ the machine


def pid_alive(pid):
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))      # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = ctypes.c_ulong()
    ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(h)
    return bool(ok) and code.value == 259                               # STILL_ACTIVE


def parse_lock(text):
    """HEAVY.lock in either form the house writes: key=value lines (purpose, pid, started) or JSON."""
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


def take_lock(purpose):
    while True:
        if LOCK.exists():
            try:
                held = parse_lock(LOCK.read_text(encoding="utf-8"))
            except OSError:
                held = {}
            pid = held.get("pid")
            if pid and str(pid).isdigit() and not pid_alive(int(pid)):
                log("HEAVY.lock names a dead pid: stale, cleared", held=held)
                LOCK.unlink(missing_ok=True)
            else:
                log("HEAVY.lock held; waiting", held=held)
                time.sleep(30)
            continue
        try:
            fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"purpose={purpose}\npid={os.getpid()}\nstarted={dt.datetime.now().isoformat()}\n")
        log("HEAVY.lock taken", purpose=purpose, pid=os.getpid())
        return


def drop_lock():
    try:
        if LOCK.exists() and str(parse_lock(LOCK.read_text(encoding="utf-8")).get("pid")) == str(os.getpid()):
            LOCK.unlink()
            log("HEAVY.lock released")
    except OSError as e:
        log("HEAVY.lock release failed", error=str(e))


def free_gb():
    class MS(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong), ("a", ctypes.c_ulonglong), ("b", ctypes.c_ulonglong),
                    ("c", ctypes.c_ulonglong), ("d", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong)]
    m = MS()
    m.dwLength = ctypes.sizeof(MS)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return {"ram": m.ullAvailPhys / 2 ** 30, "c": shutil.disk_usage("C:/").free / 2 ** 30,
            "d": shutil.disk_usage("D:/").free / 2 ** 30}


def preflight():
    dirty = subprocess.run(["fsutil", "dirty", "query", "D:"], capture_output=True, text=True).stdout.strip()
    g = free_gb()
    log("preflight", fsutil=dirty, **{k: round(v, 1) for k, v in g.items()})
    if "NOT Dirty" not in dirty:
        raise SystemExit(f"D: is not clean ({dirty}): no heavy writes")
    if g["c"] < 10 or g["d"] < 10 or g["ram"] < 6:
        raise SystemExit(f"machine short: {g}")


def blender(args, tag):
    env = dict(os.environ, TEMP=str(MEDIA / "tmp"), TMP=str(MEDIA / "tmp"))
    t0 = time.time()
    p = subprocess.run([BLENDER, "-b", "--factory-startup", "--python", str(HERE / "scene_v5c.py"), "--", "--cam", "v5d",
                        "--record", REC] + args, capture_output=True, text=True, env=env, encoding="utf-8",
                       errors="replace")
    wall = time.time() - t0
    (OUT / f"blender-{tag}.log").write_text(p.stdout[-200000:] + "\n" + p.stderr[-50000:], encoding="utf-8")
    build = [json.loads(ln[10:]) for ln in p.stdout.splitlines() if ln.startswith("V5C-BUILD ")]
    jeton = [ln for ln in p.stdout.splitlines() if ln.startswith("jeton (L0)")]
    if p.returncode != 0 or not any(ln.startswith("V5C-DONE ") for ln in p.stdout.splitlines()):
        raise SystemExit(f"blender {tag} failed ({p.returncode}): {p.stderr[-600:]}")
    return {"wall_s": round(wall, 1), "build_s": (build[0] if build else {}).get("build_s"),
            "renderer": (build[0] if build else {}).get("renderer"), "jeton": jeton[:1]}


# ------------------------------------------------------------------------------------------------ the pieces


def meter(n, k_from):
    import final_v5c as FV
    mdir = OUT / "meter"
    mdir.mkdir(parents=True, exist_ok=True)
    have = sorted(p for p in mdir.glob("*.png") if p.stat().st_size > 0)
    r = {"wall_s": 0.0, "reused": len(have)} if len(have) == len(range(0, n, 6)) else blender(["--fps", FPS_S, "--frames", f"0:{n - 1}", "--res", "480x270", "--samples", "24", "--threshold", "0.05",
                 "--min_samples", "8", "--step", "6", "--blur", "0", "--exposure", "0.0", "--out", str(mdir)], "meter")
    samples = sorted((int(p.stem), FV.meter_value(p)) for p in mdir.glob("*.png") if p.stat().st_size > 0)
    metered = FV.exposure_curve(samples, n, FPS)
    delta = POSE_EV_V5D[REC] - metered[k_from]
    ev, f_ev = SH.ease_exposure(metered, k_from, delta, FPS)
    ev = [round(float(v), 4) for v in ev]
    (OUT / "exposure.json").write_text(json.dumps({"ev": ev, "metered_ev": metered, "meter": samples,
                                                   "target": FV.TARGET, "ease_s": 0.6, "slew_stops_s": 1.0,
                                                   "camera": "v5d", "pose_ev": POSE_EV_V5D[REC], "k_from": k_from,
                                                   "pose_delta": round(delta, 4), "eased_from": f_ev}),
                                      encoding="utf-8")
    r = dict(r, pose_ev=POSE_EV_V5D[REC], metered_at_pose=metered[k_from], eased_from=f_ev)
    return ev, r


def breaths(ev):
    """The metered EV over each of the plan's camera rests (the plan: a breath that swells past about 0.7 stop gets its
    aim tilted down 3 degrees)."""
    out = {}
    for name, (a, b) in {"turn 1": (252, 305), "turn 2": (566, 656), "the Ino": (815, 830), "the lip": (926, 941),
                         "the pose": (1061, 1090)}.items():
        seg = ev[a:b + 1]
        out[name] = {"frames": [a, b], "ev": [round(min(seg), 3), round(max(seg), 3)],
                     "swing_stops": round(max(seg) - min(seg), 3)}
    return out


def tiles(spec):
    """The frame sheet: one frame per beat (its middle; a rack's hold where the beat carries one; the ending twice: the
    move and the pose)."""
    pick = {"B4": 194, "B7": 446, "B9": 518, "B10": 614, "B11": 751, "B12": 823}
    out = []
    for b in spec["beats"]:
        if b["id"] == "B15":
            out += [("B15", 976, b), ("B15", 1075, b)]
        else:
            out.append((b["id"], pick.get(b["id"], (b["frames"][0] + b["frames"][1]) // 2), b))
    return out


def frame_sheet(fdir, spec, path):
    T = tiles(spec)
    w, h, lab, cols = 854, 480, 34, 3
    rows = math.ceil(len(T) / cols)
    sheet = Image.new("RGB", (cols * w, rows * (h + lab)), (24, 20, 16))
    dr = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default(size=18)
    except TypeError:
        font = ImageFont.load_default()
    for i, (bid, f, b) in enumerate(T):
        x, y = (i % cols) * w, (i // cols) * (h + lab)
        with Image.open(fdir / f"{f:05d}.png") as im:
            sheet.paste(im.convert("RGB"), (x, y + lab))
        reads = "; ".join(b["reads"])
        text = f"{bid}  frame {f}  {f / FPS:5.2f} s   {reads}"
        while dr.textlength(text, font=font) > w - 16 and len(text) > 20:
            text = text[:-2]
        dr.text((x + 8, y + 7), text, fill=(237, 226, 207), font=font)
    sheet.save(path, optimize=True)
    return [{"beat": bid, "frame": f} for bid, f, _ in T]


def encode(fdir, wav, path, n):
    """H.264 at 29.97 from the PNGs, muxed with the Foley (the room tone is in it), at most MAX_MB."""
    kbps = int(MAX_MB * 8 * 1024 * 0.90 / (n / FPS)) - 192
    for _ in range(4):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", FPS_S, "-i", str(fdir / "%05d.png"),
                        "-i", str(wav), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "slow",
                        "-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.3)}k", "-bufsize", f"{kbps * 2}k",
                        "-pix_fmt", "yuv420p", "-r", FPS_S, "-c:a", "aac", "-b:a", "192k", "-shortest",
                        "-movflags", "+faststart", str(path)], check=True)
        if path.stat().st_size <= MAX_MB * 2 ** 20:
            return kbps
        kbps = int(kbps * 0.85)
    raise SystemExit(f"{path} is over {MAX_MB} MB")


def per_film_frames(bake, rest_s, ev):
    """What the final's per-film tails would re-render (tail_v5c.plan's rule on the v5d camera): the frames that see
    any film's record, the frames whose pose differs from RW's, and the frames whose exposure eases onto the pose."""
    import tail_v5c as T
    z = C.felt_top() + C.ITEMS["record"]["h"]
    rw = SD.shot(bake, FPS, rest_s, T.RW)
    seen_any = np.zeros(len(rw), bool)
    shots = {r: (rw if r == T.RW else SD.shot(bake, FPS, rest_s, r)) for r in C.RECORDS}
    for r, fr in shots.items():
        seen_any |= SH.rect_seen(fr, C.record_rect(r), z) > 0
    out = {}
    for r, fr in shots.items():
        k_from = next(i for i, f in enumerate(fr) if f["end"] >= 1.0)
        redo = {f for f in range(len(fr)) if seen_any[f]}
        redo |= {f for f in range(len(fr)) if not (np.array_equal(fr[f]["eye"], rw[f]["eye"])
                                                    and np.array_equal(fr[f]["tgt"], rw[f]["tgt"]))}
        if r != REC:                                   # a film whose pose exposure differs from the proof's
            _, f_ev = SH.ease_exposure(ev, k_from, POSE_EV_V5D[r] - ev[k_from], FPS)
            redo |= set(range(f_ev, len(fr)))
        out[r] = {"frames": len(redo), "runs": T.runs(redo)}
    return out


def sidecar(path, ev, n, vs_path):
    import view_settings_v5c as VS
    dump = json.loads(Path(vs_path).read_text(encoding="utf-8"))
    dumps = {d["frame"]: d for d in dump["frames"]}
    fr = VS.frames(n, set(range(n)), ev, ev, dumps)
    doc = {"master": path.name, "master_sha256": VS.sha256(path), "frames": fr}
    dv = VS.document_view(doc, VS.display_of([dump], all(f["recorded"] == "blender" for f in fr)))
    dv["renderer"] = "Blender 4.4.3"
    out = path.parent / VS.view_sidecar_name(path)
    out.write_text(json.dumps(dv, indent=1), encoding="utf-8")
    return out, dv, sum(1 for f in fr if f["recorded"] == "blender")


def render():
    OUT.mkdir(parents=True, exist_ok=True)
    rep_sim = json.loads((MEDIA / "sim" / "v5c" / "run-timing.json").read_text(encoding="utf-8"))
    bake = json.loads((MEDIA / "sim" / "v5c" / "run-bake.json").read_text(encoding="utf-8"))
    rest = rep_sim["rest_sim_s"]
    frames = SD.shot(bake, FPS, rest, REC)
    n = len(frames)
    spec, keys = SD.load_keys()
    chk = K.check(frames, keys, K.marble_speed(bake, n))
    (OUT / "v5d-check.json").write_text(json.dumps(chk, indent=1), encoding="utf-8")
    log("check", passed=chk["pass"], racks=[(r["sheet"], r["blur_ratio"], r["pass"]) for r in chk["racks"]])
    if not chk["pass"]:
        raise SystemExit("the shot fails its checks: nothing rendered")
    report = {"frames": n, "fps": FPS_S, "record": REC, "check": "v5d-check.json", "proof_sampling": PROOF,
              "denoise": False}
    preflight()
    take_lock(f"The Run v5d 480p proof (meter, {n} frames at 854x480, an 8-frame final-cost probe)")
    try:
        ev, r = meter(n, next(i for i, f in enumerate(frames) if f["end"] >= 1.0))
        report["meter"] = {"wall_s": r["wall_s"], "ev_range": [min(ev), max(ev)], "breaths": breaths(ev)}
        log("meter done", **report["meter"])
        fdir = OUT / "frames-480"
        fdir.mkdir(exist_ok=True)
        vs = OUT / "view-settings-480.blender.json"
        r = blender(["--fps", FPS_S, "--frames", f"0:{n - 1}", "--res", PROOF["res"], "--samples", str(PROOF["samples"]),
                     "--threshold", str(PROOF["threshold"]), "--min_samples", str(PROOF["min_samples"]), "--blur", "1",
                     "--expo", str(OUT / "exposure.json"), "--out", str(fdir), "--vs", str(vs)], "proof")
        done = sorted(p for p in fdir.glob("*.png") if p.stat().st_size > 0)
        spf = (r["wall_s"] - (r["build_s"] or 0)) / max(len(done), 1)
        report["proof_render"] = {**r, "frames": len(done), "s_per_frame": round(spf, 3),
                                  "minutes": round(r["wall_s"] / 60, 1)}
        log("proof render done", **report["proof_render"])
        if len(done) < n:
            raise SystemExit(f"only {len(done)} of {n} proof frames")
        pdir = OUT / "probe-1440"
        pdir.mkdir(exist_ok=True)
        r = blender(["--fps", FPS_S, "--frames", f"0:{n - 1}", "--step", str(PROBE_STEP), "--res", FINAL["res"],
                     "--samples", str(FINAL["samples"]), "--threshold", str(FINAL["threshold"]), "--min_samples",
                     str(FINAL["min_samples"]), "--blur", "1", "--expo", str(OUT / "exposure.json"), "--out", str(pdir)],
                    "probe")
        probe = sorted(p for p in pdir.glob("*.png") if p.stat().st_size > 0)
        report["final_probe"] = {**r, "frames": [int(p.stem) for p in probe], "sampling": FINAL,
                                 "s_per_frame": round((r["wall_s"] - (r["build_s"] or 0)) / max(len(probe), 1), 2)}
        log("final probe done", **report["final_probe"])
    finally:
        drop_lock()
    (OUT / "proof-render.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    return report


def finish():
    """CPU only: the Foley, the mux, the sidecar, the sheet, the cost (after render())."""
    rep_sim = json.loads((MEDIA / "sim" / "v5c" / "run-timing.json").read_text(encoding="utf-8"))
    bake = json.loads((MEDIA / "sim" / "v5c" / "run-bake.json").read_text(encoding="utf-8"))
    rest = rep_sim["rest_sim_s"]
    spec, _ = SD.load_keys()
    report = json.loads((OUT / "proof-render.json").read_text(encoding="utf-8"))
    n = report["frames"]
    ev = json.loads((OUT / "exposure.json").read_text(encoding="utf-8"))["ev"]
    fdir, vs = OUT / "frames-480", OUT / "view-settings-480.blender.json"
    wav = OUT / "v5d-foley.wav"
    subprocess.run([VENV_PY, str(HERE / "foley_v5c.py"), "--record", REC, "--timing", str(MEDIA / "sim" / "v5d"),
                    "--out", str(wav)], check=True, capture_output=True)
    report["foley"] = json.loads(wav.with_suffix(".foley-report.json").read_text(encoding="utf-8"))
    mp4 = OUT / "v5d-proof-480p.mp4"
    kbps = encode(fdir, wav, mp4, n)
    report["proof"] = {"path": str(mp4), "mb": round(mp4.stat().st_size / 2 ** 20, 2), "video_kbps": kbps}
    sc, dv, rb = sidecar(mp4, ev, n, vs)
    report["view_sidecar"] = {"path": str(sc), "blender_read_back_frames": rb,
                              "display": {k: dv.get(k) for k in ("display_device", "gamma", "use_curve_mapping")},
                              "defaults_assumed": dv.get("defaults_assumed")}
    sheet = OUT / "v5d-frame-sheet-480p.png"
    report["frame_sheet"] = {"path": str(sheet), "tiles": frame_sheet(fdir, spec, sheet)}
    pf = per_film_frames(bake, rest, ev)
    spf_final = report["final_probe"]["s_per_frame"]
    prefix_h = n * spf_final / 3600
    tails_h = sum(v["frames"] for v in pf.values()) * spf_final / 3600
    report["final_cost_estimate"] = {
        "s_per_frame_1440p_512spp_probe": spf_final, "prefix_h": round(prefix_h, 2), "per_film_frames": pf,
        "tails_h": round(tails_h, 2), "meter_s": report["meter"]["wall_s"],
        "total_h": round(prefix_h + tails_h + report["meter"]["wall_s"] / 3600, 2),
        "basis": f"{len(report['final_probe']['frames'])} frames at the final's settings spread over the shot "
                 f"(every {PROBE_STEP}th), wall minus build, times the prefix's {n} frames and each film's tail"}
    (OUT / "proof-report.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    log("proof done", proof=report["proof"], sheet=str(sheet), cost=report["final_cost_estimate"]["total_h"])


if __name__ == "__main__":
    phase = sys.argv[sys.argv.index("--phase") + 1] if "--phase" in sys.argv else "all"
    if phase in ("render", "all"):
        render()
    if phase in ("finish", "all"):
        finish()
