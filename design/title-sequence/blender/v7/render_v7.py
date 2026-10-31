"""Title v7 "The Record Stands": the driver (run-venv Python), under the machine rules.

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/v7/render_v7.py <step> [opts]

Steps:
  plan       the gate (globe scan and records) and plan.json (every frame's camera, boards, flat-hold, dust)
  smoke      a few frames at 427x240, 32 spp (the scene builds; timing)
  meter      the fixed exposure at the Atlas read (f170), written to work/exposure.json
  still      the day-1 still: the Atlas read at 2560x1440 (--samples, default 1024) to review/day1-still-f170.png
  frames     the 480p review frames (854x480, --samples, default 256, adaptive, no denoiser), in chunks of --chunk
  assemble   lockup, marks, Foley, theme (when it is there), mix, encode, frame sheet, acceptance.json

Every Blender run: D: not dirty, C: and D: over 10 GB (machine_v6.heavy) and D: left over 12 GB after the step's own
estimated output (the coordinator's rule, 2026-10-31); HEAVY.lock taken atomically with this process's pid, waited on
while a live pid holds it, released in a finally (only if still ours); the process tree capped at 8 GB committed.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "run"))
import plan_v7 as P  # noqa: E402

BLENDER = "D:/document-media/tools/blender-4.4.3-windows-x64/blender.exe"
ROOT = Path("D:/document-media/title-sequence/v7")
WORK = ROOT / "work"
REVIEW = ROOT / "review"
FRAMES_DIR = ROOT / "frames-480"
TMP = ROOT / "tmp"
D_FLOOR_GB = 12.0
LEDGER_DIR = HERE.parent.parent
LOG = WORK / "render-log.jsonl"


def arg(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def log(event, **kv):
    WORK.mkdir(parents=True, exist_ok=True)
    rec = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event, **kv}
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    print(json.dumps(rec, default=str), flush=True)


def d_free_gb() -> float:
    return shutil.disk_usage("D:/").free / 2 ** 30


def d_guard(need_gb: float, step: str):
    """Refuse a step that would leave D: at or under D_FLOOR_GB."""
    free = d_free_gb()
    if free - need_gb <= D_FLOOR_GB:
        log("refused: D: floor", step=step, free_gb=round(free, 2), need_gb=need_gb, floor_gb=D_FLOOR_GB)
        raise SystemExit(f"refused: {step} needs ~{need_gb} GB; D: has {free:.1f} GB free (floor {D_FLOOR_GB} GB)")
    return round(free, 2)


# ------------------------------------------------------------------------------------------------ the gate


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def gate() -> dict:
    """The globe: run-scan-ledger item 'globe' with gate pass and every file's sha256 as pinned. The records: each
    texture's bytes as tex-manifest pins them, from a ledger item (sha256 pinned, ai false) or a film record."""
    led = json.loads((LEDGER_DIR / "run-scan-ledger.json").read_text(encoding="utf-8"))
    g = next(i for i in led["items"] if i["id"] == "globe")
    bad = [f["path"] for f in g["files"] if sha256(Path(f["path"])) != f["sha256"]]
    out = {"globe": {"gate": g.get("gate"), "ai": g.get("ai"), "licence": g.get("licence"), "files": len(g["files"]),
                     "sha_mismatch": bad, "pass": g.get("gate") == "pass" and not g.get("ai") and not bad}}
    man = json.loads(Path("D:/document-media/title-sequence/tex-manifest.json").read_text(encoding="utf-8"))
    items, recs = {}, {}
    for f in ("assets-ledger.json", "chart-assets-ledger.json"):
        L = json.loads((LEDGER_DIR / f).read_text(encoding="utf-8"))
        items.update({i["id"]: i for i in L.get("items", [])})
        recs.update(L.get("records", {}))
    for rid, r in P.RECORDS.items():
        for t in r["tex"]:
            e = man[t]
            src = e["from"]
            it = items.get(src)
            ok_src = (it is not None and bool(it.get("sha256")) and it.get("ai") is False) or \
                     (src in recs and bool(recs[src].get("sha256") or recs[src].get("rows")))
            ok_bytes = sha256(Path(e["tex"]["file"])) == e["tex"]["sha256"]
            out[t] = {"from": src, "class": e.get("class"), "licence": (it or {}).get("licence"),
                      "kind": "ledger item" if it else "film record", "bytes_pinned": ok_bytes,
                      "pass": ok_src and ok_bytes}
    out["pass"] = all(v["pass"] for v in out.values() if isinstance(v, dict))
    return out


# ------------------------------------------------------------------------------------------------ the plan


def _basis(cam):
    r, u, f = P.cam_basis(cam)
    return [list(r), list(u), list(-f)]          # Blender camera: x right, y up, z back


def build_plan() -> dict:
    import globe_v7 as G
    meas = json.loads((HERE / "globe-measure.json").read_text(encoding="utf-8"))
    consts = {"frames": P.FRAMES, "fps_num": P.FPS_NUM, "fps_den": P.FPS_DEN, "cut": P.CUT, "R": P.R,
              "ball_centre_native": meas["centre_native"], "ball_radius_native": meas["radius_native"],
              "R_geo_to_native": P.registration().tolist(), "lens_mm": P.LENS_MM, "sensor_mm": P.SENSOR_MM,
              "card_t": P.CARD_T, "rod_r": P.ROD_R, "shutter_deg": 180.0, "constant_frames": [P.CUT - 1],
              "lamp": {"offset_cam": [0.9, 1.2, 0.3], "kelvin": 3400, "white_balance_k": 4300, "shade_d_m": 0.26,
                       "spot_deg": 62.0, "spot_blend": 0.55, "power_w": 220.0},
              "haze": {"box_m": 9.0, "density": 0.018, "anisotropy": 0.45},
              "dust": {"count": 400, "box_m": 4.0, "radius_m": 0.0012, "drift_m_s": 0.02, "seed": 7,
                       "min_dist_m": 0.35}}
    boards = []
    for b in P.BOARDS:
        P0, H, U, W = P.hinge_basis(b)
        w = P.RECORDS[b["id"]]["size"][0]
        ends = [P0 - W * (w / 2 + 0.02), P0 + W * (w / 2 + 0.02)]
        feet = []
        for x in (-(w / 2 - 0.03), w / 2 - 0.03):
            top = P0 + W * x
            feet.append([list(top), list(P.unit(top) * (P.R - 0.004))])
        pans = P.panels(b["id"], b["rise"] + 200)
        boards.append({"id": b["id"], "tail": bool(b.get("tail")),
                       "panels": [{"tex": p["tex"], "hw": float(np.linalg.norm(p["ex"])),
                                   "hh": float(np.linalg.norm(p["ey"]))} for p in pans],
                       "hinge": {"rod_a": list(ends[0]), "rod_b": list(ends[1]), "feet": feet}})
    frames = []
    for f in range(P.FRAMES):
        cam = P.camera_at(f)
        row = {"cam": {"E": list(cam["E"]), "focus": cam["focus"], "fstop": cam["fstop"]},
               "panels": {}, "show": {}, "hold_mix": P.hold_mix(f), "dust_scale": P.dust_scale(f),
               "haze": P.haze_scale(f)}
        bx = _basis(cam)
        row["cam"].update({"x": bx[0], "y": bx[1], "z": bx[2]})
        for b in P.BOARDS:
            row["show"][b["id"]] = P.in_shot(b, f)
            st = []
            for p in P.panels(b["id"], f):
                x = P.unit(p["ex"])
                y = P.unit(p["ey"])
                st.append({"c": list(p["centre"]), "x": list(x), "y": list(y), "z": list(np.cross(x, y))})
            row["panels"][b["id"]] = st
        frames.append(row)
    plan = {"consts": consts, "boards": boards, "frames": frames, "departures": P.DEPARTURES,
            "globe_texture": str(G.SPHERE_TEX)}
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "plan.json").write_text(json.dumps(plan, default=float), encoding="utf-8")
    return plan


# ------------------------------------------------------------------------------------------------ Blender under the lock


NEXT = Path("C:/Users/aacri/document-work/HEAVY.next")
SLOT = {"held": False}


def _next_is_ours():
    try:
        return f"pid={os.getpid()}" in NEXT.read_text(encoding="utf-8")
    except OSError:
        return False


@__import__("contextlib").contextmanager
def gpu_slot(purpose, poll_s=2.0):
    """The coordinator's next-slot protocol (2026-10-31): HEAVY.next names this process ("owner=title-v7
    pid=<winpid>") while it waits, so the other builders yield; the lock itself is unchanged (machine_v6's rules:
    D: clean, disks and RAM checked, the process tree capped at 8 GB, a dead pid's lock cleared, a live one never
    overwritten, taken atomically with this pid, released only if still ours). HEAVY.next is deleted the moment the
    lock is taken."""
    import machine_v6 as MV
    MV.check_disks()
    if MV.free_ram_gb() < MV.MIN_FREE_RAM_GB:
        raise SystemExit(f"refused: free RAM {MV.free_ram_gb():.1f} GB")
    MV.cap_memory()
    NEXT.write_text(f"owner=title-v7 pid={os.getpid()}\n", encoding="utf-8")
    try:
        while True:
            if MV.LOCK.exists():
                try:
                    held = MV.parse_lock(MV.LOCK.read_text(encoding="utf-8"))
                except OSError:
                    held = {}
                pid = held.get("pid")
                if pid is not None and str(pid).isdigit() and not MV.pid_alive(int(pid)):
                    log("stale lock cleared", pid=pid)
                    MV.LOCK.unlink(missing_ok=True)
                else:
                    time.sleep(poll_s)
                continue
            try:
                fd = os.open(str(MV.LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(MV.lock_text(f"title v7 (t/title-v7): {purpose}", os.getpid()))
            break
    finally:
        if _next_is_ours():
            NEXT.unlink(missing_ok=True)
    log("lock taken", purpose=purpose, pid=os.getpid())
    SLOT["held"] = True
    try:
        yield
    finally:
        SLOT["held"] = False
        try:
            if MV.LOCK.exists() and str(MV.parse_lock(MV.LOCK.read_text(encoding="utf-8")).get("pid")) == str(os.getpid()):
                MV.LOCK.unlink()
                log("lock released", pid=os.getpid())
        except OSError as e:
            log("lock release failed", error=str(e))


def blender(purpose, extra, need_gb, log_name, plan_path=None):
    d_guard(need_gb, purpose)
    TMP.mkdir(parents=True, exist_ok=True)
    cmd = [BLENDER, "-b", "-noaudio", "--factory-startup", "--python", str(HERE / "scene_v7.py"), "--",
           "--plan", str(plan_path or (WORK / "plan.json"))] + extra
    env = dict(os.environ, TEMP=str(TMP), TMP=str(TMP))
    ctx = __import__("contextlib").nullcontext() if SLOT["held"] else gpu_slot(purpose)
    with ctx:
        t0 = time.time()
        p = subprocess.run(cmd, capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
        wall = round(time.time() - t0, 1)
    lp = WORK / log_name
    lp.write_text(p.stdout + "\n" + p.stderr, encoding="utf-8")
    done = next((json.loads(ln[8:]) for ln in p.stdout.splitlines() if ln.startswith("V7-DONE ")), None)
    meter = next((json.loads(ln[9:]) for ln in p.stdout.splitlines() if ln.startswith("V7-METER ")), None)
    if p.returncode != 0 or done is None:
        log("blender failed", purpose=purpose, rc=p.returncode, log=str(lp))
        raise SystemExit(f"blender failed ({p.returncode}); log in {lp}")
    done["wall_s"] = wall
    done["meter"] = meter
    return done


def exposure() -> float:
    return json.loads((WORK / "exposure.json").read_text(encoding="utf-8"))["ev"]


def step_smoke():
    out = WORK / "smoke"
    out.mkdir(parents=True, exist_ok=True)
    fr = arg("--frames", "30,120,170,300,500,680,780,870,960,1030")
    ev = float(arg("--ev", "0.0"))
    info = blender("smoke", ["--frames", fr, "--outdir", str(out), "--res", arg("--res", "427x240"),
                             "--samples", arg("--samples", "32"), "--min_samples", "16", "--threshold", "0.05",
                             "--exposure", f"{ev:.5f}"] + (["--haze", arg("--haze", "")] if "--haze" in sys.argv
                                                           else []),
                   0.2, "smoke.log")
    log("smoke", **{k: info[k] for k in ("frames_rendered", "build_s", "s", "wall_s")})


def step_meter():
    out = WORK / "meter"
    out.mkdir(parents=True, exist_ok=True)
    # Departure: the spec meters on the Atlas read (f170); the 1931 chart's white paper (f690) then clips (C1, 13%
    # of its read's pixels). The one fixed exposure is metered on both reads and the brighter sets it.
    info = blender("meter at the Atlas and chart reads (f170, f690)", ["--meter", "170,690", "--outdir", str(out)],
                   0.1, "meter.log")
    m = info["meter"]
    (WORK / "exposure.json").write_text(json.dumps({**m, "rule": "max(R,G,B) p99.5 to 0.85 display on the brighter "
                                                    "of the Atlas read (f170) and the chart read (f690)"},
                                                   indent=1), encoding="utf-8")
    log("meter", **m)


def step_still():
    REVIEW.mkdir(parents=True, exist_ok=True)
    out = REVIEW / "day1-still-f170.png"
    f = arg("--frame", "170")
    info = blender(f"day-1 still f{f} 2560x1440", ["--frames", f, "--still", str(out), "--res",
                                                   arg("--res", "2560x1440"), "--samples", arg("--samples", "1024"),
                                                   "--min_samples", "256", "--threshold", "0.005",
                                                   "--exposure", f"{exposure():.5f}", "--outdir", str(WORK)],
                   0.1, "still.log")
    log("still", out=str(out), **{k: info[k] for k in ("frames_rendered", "s", "wall_s", "samples")})


def step_globe_still():
    """Fable's abandon test, as a picture: the bare globe (no board) at the read distance, 1.35 m from the ball over
    the central Mediterranean (36N 15E), 35 degrees down, under the camera's own lamp; 2560x1440."""
    plan = json.loads((WORK / "plan.json").read_text(encoding="utf-8"))
    f = 170
    E, T = P.orbit(36.0, 15.0, 90.0, 35.0, P.READ_D)
    cam = {"E": E, "T": T, "up": P.unit(E), "fstop": 5.6}
    cam["focus"] = float(np.linalg.norm(T - E))
    bx = _basis(cam)
    plan["frames"][f]["cam"] = {"E": list(E), "focus": cam["focus"], "fstop": 5.6, "x": bx[0], "y": bx[1], "z": bx[2]}
    for k in plan["frames"][f]["show"]:
        plan["frames"][f]["show"][k] = False
    alt = P.camera_at(f)
    gp = WORK / "plan-globe-still.json"
    gp.write_text(json.dumps(plan, default=float), encoding="utf-8")
    out = REVIEW / "day1-globe-1.35m.png"
    fill = P.fill_at(P.READ_D, P.DENSITY)
    info = blender("day-1 globe still at 1.35 m, 2560x1440",
                   ["--frames", str(f), "--still", str(out), "--res", "2560x1440", "--samples",
                    arg("--samples", "1024"), "--min_samples", "256", "--threshold", "0.005",
                   "--exposure", f"{exposure():.5f}", "--outdir", str(TMP)], 0.1, "globe-still.log",
                   plan_path=gp)
    log("globe still", out=str(out), fill_1080=round(fill, 3), fill_1440=round(fill * 2560 / 1920, 3),
        **{k: info[k] for k in ("frames_rendered", "s", "wall_s", "samples")})
    del alt


def unique_frames():
    """Every frame but the pose's repeats: 1019-1079 is one still (camera, scene and dust fixed; dust gone)."""
    return list(range(0, P.POSE_FROM + 1))


def step_frames():
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    samples = arg("--samples", "256")
    chunk = int(arg("--chunk", "60"))
    ev = exposure()
    todo = [f for f in unique_frames() if not (FRAMES_DIR / f"{f:05d}.png").exists()]
    if "--only" in sys.argv:
        a, z = (int(v) for v in arg("--only", "0-0").split("-"))
        todo = [f for f in todo if a <= f <= z]
    log("frames start", todo=len(todo), samples=samples, ev=ev, d_free_gb=round(d_free_gb(), 2))
    for i in range(0, len(todo), chunk):
        part = todo[i:i + chunk]
        info = blender(f"480p review f{part[0]}-f{part[-1]} ({len(part)} frames, {samples} spp)",
                       ["--frames", ",".join(map(str, part)), "--outdir", str(FRAMES_DIR), "--res", "854x480",
                        "--samples", samples, "--min_samples", "64", "--threshold", "0.02",
                        "--exposure", f"{ev:.5f}"], 0.6 * len(part) / 1000 + 0.2, f"chunk-{part[0]:05d}.log")
        rt = [t for _, t in info["frames_rendered"]]
        log("chunk", first=part[0], last=part[-1], n=len(part), wall_s=info["wall_s"], build_s=info["build_s"],
            render_s=round(sum(rt), 1), s_per_frame=round(sum(rt) / max(1, len(rt)), 2),
            d_free_gb=round(d_free_gb(), 2))


def main():
    step = sys.argv[1]
    if step == "plan":
        g = gate()
        (WORK / "gate.json").parent.mkdir(parents=True, exist_ok=True)
        (WORK / "gate.json").write_text(json.dumps(g, indent=1), encoding="utf-8")
        if not g["pass"]:
            raise SystemExit(f"gate failed: {json.dumps(g)}")
        build_plan()
        log("plan", gate=g["pass"], frames=P.FRAMES)
    elif step == "smoke":
        step_smoke()
    elif step == "meter":
        step_meter()
    elif step == "still":
        step_still()
    elif step == "frames":
        step_frames()
    elif step == "all":
        # one lock hold for every GPU job of the review, in order: meter, the 480p frames, the day-1 still
        with gpu_slot("480p review: meter, frames, day-1 still"):
            if not (WORK / "exposure.json").exists():
                step_meter()
            step_frames()
            if not (REVIEW / "day1-still-f170.png").exists():
                step_still()
            if not (REVIEW / "day1-globe-1.35m.png").exists():
                step_globe_still()
    elif step == "globe-still":
        step_globe_still()
    elif step == "assemble":
        import assemble_v7 as AS
        AS.main()
    else:
        raise SystemExit(f"unknown step {step}")


if __name__ == "__main__":
    main()
