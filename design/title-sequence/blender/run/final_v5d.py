"""The Run v5d: the final (the founder approved proof 2 as rendered, 2026-10-26). One heavy job behind HEAVY.lock.

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/final_v5d.py \
        --engine D:/document-worktrees/render-509fa56 [--plan-only]

Settings as the final v5c: 2560x1440, Cycles OptiX, adaptive 512 spp, noise threshold 0.02, min 64, motion blur, NO
denoiser; AgX, look None; the one constant lamp; the camera's own exposure metered as v5c's (480x270, 24 spp, every
6th frame, centre-weighted, eased 0.6 s, slewed 1 stop/s) through the v5d camera (scene_v5c.py --cam v5d, layout L0,
transparent bounces 64), each film eased onto its calibrated pose exposure (proof_v5d.POSE_EV_V5D).

1. The meter, then the shared shot, 1091 frames as C20-METAR-0851 (RW) with the view read back on every frame (--vs).
2. Each film: the frames that differ from RW's (any record in frame, the move onto its own pose, its exposure's
   ease) re-rendered into <record>/tail-2560 (+ scene-linear EXR), read back; RW's master is the shared shot itself.
3. Each film: the 1920x1080 ProRes 422 HQ master (Lanczos), A7 and the pose edges through the declared view
   (studio.engine.titles at --engine) at frames 1061, 1075 and 1090; the sound (the title theme at unity, the
   corrected Foley with its leather lifted 9 dB, the room tone) muxed at 29.97 into the -sound master; its
   document.view/1 sidecar from the read-back; the theme's whole 42.403 s mix (shot + lockup) kept beside it.
4. title-items-v5d.json beside the masters and TS-v5d-<record> entries in the masters ledger, view_transform declared.
--plan-only: the dry check (what renders, disk, time, the machine) with no lock and no render.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from scipy.io import wavfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import channel_v5c as C  # noqa: E402
import check_v5d as K  # noqa: E402
import proof_v5d as P  # noqa: E402
import shot_v5c as SH  # noqa: E402
import shot_v5d as SD  # noqa: E402
import tail_v5c as T  # noqa: E402
import view_settings_v5c as VS  # noqa: E402

MEDIA = Path("D:/document-media/title-sequence/run")
OUT = MEDIA / "masters" / "final-v5d"
THEME = Path("D:/document-media/title-sequence/theme-v5d/the-run-theme-v5d.wav")
LEDGER = Path("C:/Users/aacri/document-work/title-sequence/masters-ledger.json")
ITEMS_V5C = MEDIA / "masters" / "final-v5c" / "title-items-v5c.json"
FPS_S, FPS = "30000/1001", 30000 / 1001
RW = "C20-METAR-0851"
FINAL = {"res": "2560x1440", "samples": 512, "threshold": 0.02, "min_samples": 64}
LIFT_DB = 9.0
S_PER_FRAME = 8.22                           # proof 2's probe at these settings (8 frames over the shot)
BYTES = {"png": 4.8e9 / 1091, "exr": 3.0e9 / 230, "mov": 1.03e9}     # measured on the v5c final


def log(msg, **kv):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}" + (" " + json.dumps(kv, default=str) if kv else "")
    print(line, flush=True)
    with (OUT / "final-v5d.log").open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def blender(args, tag, rec):
    """scene_v5c.py --cam v5d for one film; Blender's done marker may share a line with its own output."""
    import os
    env = dict(os.environ, TEMP=str(MEDIA / "tmp"), TMP=str(MEDIA / "tmp"))
    for k in range(3):
        t0 = time.time()
        p = subprocess.run([P.BLENDER, "-b", "--factory-startup", "--python", str(HERE / "scene_v5c.py"), "--", "--cam",
                            "v5d", "--record", rec] + args, capture_output=True, text=True, env=env, encoding="utf-8",
                           errors="replace")
        (OUT / f"blender-{tag}.log").write_text(p.stdout[-400000:] + "\n" + p.stderr[-50000:], encoding="utf-8")
        if p.returncode == 0 and "V5C-DONE " in p.stdout:
            return round(time.time() - t0, 1)
        log(f"blender {tag} failed (attempt {k + 1})", code=p.returncode, tail=p.stderr[-300:])
        out_dir = Path(args[args.index("--out") + 1])
        for f in out_dir.glob("*.png"):
            if f.stat().st_size == 0:
                f.unlink()
    raise SystemExit(f"blender {tag} failed 3 times")


def exposures(metered, shots):
    """Each film's per-frame EV: the meter eased onto its calibrated pose value (at most 1 stop/s), and where it starts."""
    out = {}
    for rec, fr in shots.items():
        k_from = next(i for i, f in enumerate(fr) if f["end"] >= 1.0)
        ev, f_ev = SH.ease_exposure(metered, k_from, P.POSE_EV_V5D[rec] - metered[k_from], FPS)
        out[rec] = {"ev": [round(float(v), 4) for v in ev], "eased_from": f_ev, "k_from": k_from}
    return out


def plan(bake, rest, metered=None):
    shots = {r: SD.shot(bake, FPS, rest, r) for r in C.RECORDS}
    n = len(shots[RW])
    z = C.felt_top() + C.ITEMS["record"]["h"]
    seen_any = np.zeros(n, bool)
    for r, fr in shots.items():
        seen_any |= SH.rect_seen(fr, C.record_rect(r), z) > 0
    ex = exposures(metered, shots) if metered is not None else None
    films = {}
    for r, fr in shots.items():
        if r == RW:
            redo = set()                     # RW's master is the shared shot (rendered as RW, dead-matte record)
        else:
            redo = {f for f in range(n) if seen_any[f]}
            redo |= {f for f in range(n) if not (np.array_equal(fr[f]["eye"], shots[RW][f]["eye"])
                                                  and np.array_equal(fr[f]["tgt"], shots[RW][f]["tgt"]))}
            if ex is not None:
                redo |= set(range(ex[r]["eased_from"], n))
                redo |= {f for f in range(n) if abs(ex[r]["ev"][f] - ex[RW]["ev"][f]) > 1e-9}
        k_from = next(i for i, f in enumerate(fr) if f["end"] >= 1.0)
        cover = SH.rect_cover(fr, C.record_rect(r), z)
        r0 = int(next(i for i in range(n) if i >= SH.tail_from(fr) and cover[i] >= 0.5))
        films[r] = {"redo": sorted(redo), "runs": T.runs(redo), "k_from": k_from, "record_from": r0}
    return shots, films, n


def sound(n, path_mov_audio, path_full):
    """The theme at unity + the corrected Foley (leather +9 dB, no room) + the room tone under the whole theme."""
    import clean as CL
    import foley as FO
    import proof_mix_v5d as PM
    timing = MEDIA / "sim" / "v5d"
    dry, frep = PM.foley(LIFT_DB, timing, room_tone=False)
    sr0, th = wavfile.read(THEME)
    if sr0 != FO.SR:
        raise SystemExit(f"the theme is {sr0} Hz, the Foley {FO.SR}")
    th = th.astype(np.float64) / (32768.0 if th.dtype == np.int16 else 2 ** 31 if th.dtype == np.int32 else 1.0)
    th = th.mean(axis=1) if th.ndim > 1 else th
    n_all = int(round((n / FPS + PM.LOCKUP_S) * FO.SR))
    th = np.pad(th, (0, max(0, n_all - len(th))))[:n_all]
    mix = th + np.pad(dry, (0, max(0, n_all - len(dry))))[:n_all] + CL.room_bed(n_all, "the-run-v5d")
    st = np.clip(np.stack([mix, mix], 1), -1, 1)
    wavfile.write(path_full, FO.SR, (st * 32767).astype(np.int16))
    n_shot = int(round(n / FPS * FO.SR))
    wavfile.write(path_mov_audio, FO.SR, (st[:n_shot] * 32767).astype(np.int16))
    return {"theme": str(THEME), "theme_gain": 1.0, "foley_gain": 1.0, "leather_lift_db": LIFT_DB,
            "room": "clean.room_bed -72 dBFS", "peak_dbfs": round(20 * math.log10(float(np.abs(mix).max())), 2),
            "full_s": round(n_all / FO.SR, 3), "master_s": round(n_shot / FO.SR, 3), "foley": frep}


def load_dumps(paths):
    docs, dumps = [], {}
    for p in paths:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        docs.append(d)
        for fr in d["frames"]:
            if not fr.get("skipped_existing"):
                dumps[fr["frame"]] = fr
    return docs, dumps


def item_for(rec, sound_mov, a7, view, film, n, items_v5c):
    base = copy.deepcopy(items_v5c["films"][rec]["item"])
    r = C.RECORDS[rec]
    base.update({
        "series": "void document · As It Was", "id": f"TS-v5d-{rec}",
        "file": f"../run/masters/final-v5d/{rec}/{sound_mov.name}", "frames": n, "denoise": False, "burned": False,
        "record_frames": [film["record_from"], n - 1],
        "record_pose": {"window": [round(v, 6) for v in C.record_window(rec)], "from_frame": film["k_from"]},
        "marks": [{"frame": 0, "cls": "DRAWN", "label": "Drawn · from period records"},
                  {"frame": film["record_from"], "cls": r["cls"], "label": T.TITLE_RECORDS[rec]["label"]}],
        "renderer": f"Blender 4.4.3 Cycles (OptiX), adaptive sampling {FINAL['samples']} spp, noise threshold "
                    f"{FINAL['threshold']}, no denoiser",
        "bytes": sound_mov.stat().st_size, "sha256": VS.sha256(sound_mov), "version": "v5d",
        "date": time.strftime("%Y-%m-%d"),
        "title": f"void document · As It Was, series titles v5d (The Run), record {rec} "
                 f"({items_v5c['films'][rec].get('film', '')})",
        "generator": "Blender 4.4.3 Cycles (scene_v5c.py --cam v5d, shot_v5d.py on Fable's keys, MuJoCo bake "
                     "sim_v5c.py), final_v5d.py; Foley foley_v5c.py on timing_v5d.py's events; theme v5d",
        "codec": "ProRes 422 HQ (yuv422p10le), PCM s16le: the title theme v5d, the Foley (leather +9 dB) and the room "
                 "at -72 dBFS",
        "a7": a7["a7"], "a7_edge_strips": a7["edge_strips"],
        "view_transform": {"name": view["name"], "look": view["look"], "sidecar": VS.view_sidecar_name(sound_mov), "basis": view["basis"]},
        "a7_basis": "A7 like for like (studio.engine.titles at the --engine checkout, ocio backend): the scan through "
                    "the sidecar's AgX, look None and exposure at each of frames "
                    f"{', '.join(str(k) for k in a7['by_frame'])}; worst frame"})
    return base


def slot_for(slot_v5c, asset, n):
    """The title slot as the film builders now hold it: TS1 (the shot, 36.403 s) then TS1b (the 6 s lockup), joined
    by cuts. TS1r (v5c's 14.6 s hold of the record) is gone."""
    ts1 = dict(next(s for s in slot_v5c if s["id"] == "TS1"), asset=asset, dur=round(n / FPS, 3),
               transition_in={"type": "cut"})
    ts1b = {"id": "TS1b", "kind": "card", "card": "lockup", "dur": 6.0, "transition_in": {"type": "cut"},
            "mark": "CARD", "text": ["void document · As It Was"],
            "why": "the lockup card, the last 6 s of the title slot (as the film builders hold it)"}
    return [ts1, ts1b]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True)
    ap.add_argument("--plan-only", action="store_true")
    a = ap.parse_args(argv)
    sys.path.insert(0, str(Path(a.engine).resolve()))
    OUT.mkdir(parents=True, exist_ok=True)
    rep_sim = json.loads((MEDIA / "sim" / "v5c" / "run-timing.json").read_text(encoding="utf-8"))
    bake = json.loads((MEDIA / "sim" / "v5c" / "run-bake.json").read_text(encoding="utf-8"))
    rest = rep_sim["rest_sim_s"]
    proof_meter = json.loads((MEDIA / "proofs" / "v5d" / "exposure.json").read_text(encoding="utf-8"))["metered_ev"]
    shots, films, n = plan(bake, rest, proof_meter)
    _, keys = SD.load_keys()
    chk = K.check(shots[RW], keys, K.marble_speed(bake, n))
    tail_frames = sum(len(f["redo"]) for f in films.values())
    est = {"prefix_frames": n, "tail_frames": {r: len(f["redo"]) for r, f in films.items()},
           "hours": round((n + tail_frames) * S_PER_FRAME / 3600 + 0.05, 2),
           "disk_gb": round((n * BYTES["png"] + tail_frames * (BYTES["png"] + BYTES["exr"]) + 6 * BYTES["mov"]) / 1e9, 1),
           "check": {"pass": chk["pass"], "specified": chk["pass_specified"]},
           "runs": {r: f["runs"] for r, f in films.items()}}
    import importlib
    eng = importlib.import_module("studio.engine.titles")
    import inspect
    est["engine"] = {"path": str(Path(eng.__file__)), "view_param": "view" in inspect.signature(eng.record_difference).parameters}
    if a.plan_only:
        dirty = subprocess.run(["fsutil", "dirty", "query", "D:"], capture_output=True, text=True).stdout.strip()
        g = P.free_gb()
        est["machine"] = {"fsutil": dirty, **{k: round(v, 1) for k, v in g.items()},
                          "lock": P.parse_lock(P.LOCK.read_text(encoding="utf-8")) if P.LOCK.exists() else None,
                          "theme": THEME.exists(), "ledger": LEDGER.exists(), "items_v5c": ITEMS_V5C.exists()}
        print(json.dumps(est, indent=1, default=str))
        return est
    if not chk["pass"]:
        raise SystemExit("the shot fails its checks")
    if not est["engine"]["view_param"]:
        raise SystemExit(f"{a.engine}'s studio.engine.titles cannot compare through a view transform (A40)")
    P.OUT = OUT                               # proof_v5d's lock and preflight log into this run's folder
    P.LOG = OUT / "final-v5d.log"
    P.preflight()
    if P.free_gb()["d"] < est["disk_gb"] + 10:
        raise SystemExit(f"D: needs {est['disk_gb']} GB plus 10 GB free")
    log("final v5d start", **{k: v for k, v in est.items() if k != "runs"})
    P.take_lock(f"The Run v5d final (2560x1440 512 spp: {n} shared frames, tails {est['tail_frames']})")
    report = {"estimate": est, "sampling": FINAL, "denoise": False, "films": {}}
    try:
        # 1. the meter
        mdir = OUT / "meter"
        mdir.mkdir(exist_ok=True)
        import final_v5c as FV
        if len([p for p in mdir.glob("*.png") if p.stat().st_size > 0]) < len(range(0, n, 6)):
            wall = blender(["--fps", FPS_S, "--frames", f"0:{n - 1}", "--res", "480x270", "--samples", "24",
                            "--threshold", "0.05", "--min_samples", "8", "--step", "6", "--blur", "0", "--exposure",
                            "0.0", "--out", str(mdir)], "meter", RW)
            report["meter_wall_s"] = wall
        samples = sorted((int(p.stem), FV.meter_value(p)) for p in mdir.glob("*.png") if p.stat().st_size > 0)
        metered = FV.exposure_curve(samples, n, FPS)
        shots, films, n = plan(bake, rest, metered)
        ex = exposures(metered, shots)
        for r, e in ex.items():
            d = OUT / r
            d.mkdir(exist_ok=True)
            (d / "exposure.json").write_text(json.dumps({"ev": e["ev"], "metered_ev": metered, "meter": samples,
                                                         "pose_ev": P.POSE_EV_V5D[r], "k_from": e["k_from"],
                                                         "eased_from": e["eased_from"]}), encoding="utf-8")
        report["meter"] = {"ev_range": [min(metered), max(metered)], "breaths": P.breaths(ex[RW]["ev"])}
        log("meter done", **report["meter"])
        # 2. the shared shot (RW)
        fdir = OUT / "frames-2560"
        fdir.mkdir(exist_ok=True)
        common = ["--fps", FPS_S, "--res", FINAL["res"], "--samples", str(FINAL["samples"]), "--threshold",
                  str(FINAL["threshold"]), "--min_samples", str(FINAL["min_samples"]), "--blur", "1"]
        wall = blender(common + ["--frames", f"0:{n - 1}", "--expo", str(OUT / RW / "exposure.json"), "--out", str(fdir),
                                 "--vs", str(OUT / "view-settings-shared.blender.json")], "shared", RW)
        report["shared_wall_s"] = wall
        log("shared shot done", wall_s=wall, s_per_frame=round(wall / n, 2))
        # 3. the tails
        for r, f in films.items():
            if not f["redo"]:
                continue
            tdir, xdir = OUT / r / "tail-2560", OUT / r / "tail-exr"
            tdir.mkdir(exist_ok=True)
            xdir.mkdir(exist_ok=True)
            for f0, f1 in f["runs"]:
                wall = blender(common + ["--frames", f"{f0}:{f1}", "--expo", str(OUT / r / "exposure.json"), "--out",
                                         str(tdir), "--exr", str(xdir), "--vs",
                                         str(OUT / r / f"view-settings-{f0}-{f1}.blender.json")], f"{r}-{f0}-{f1}", r)
                log("tail run", record=r, run=[f0, f1], wall_s=wall)
    finally:
        P.drop_lock()
    # 4. CPU: masters, A7, sound, sidecars, items
    items_v5c = json.loads(ITEMS_V5C.read_text(encoding="utf-8"))
    T.BASE = OUT                              # tail_v5c.frame_path reads the shared frames from here
    items = {"_note": items_v5c["_note"], "films": {}}
    for r, f in films.items():
        d = OUT / r
        redo = set(f["redo"])
        master, preview = d / f"the-run-v5d-{r}-2997.mov", d / f"the-run-v5d-{r}-2997-preview.mp4"
        T.encode(n, redo, d / "tail-2560", master, preview)
        ev = json.loads((d / "exposure.json").read_text(encoding="utf-8"))["ev"]
        view = T.view_transform(ev, f["k_from"], r)
        last = n - 1
        a7 = T.a7_master(master, r, sorted({f["k_from"], (f["k_from"] + last) // 2, last}), view)
        log("a7", record=r, a7=a7["a7"], edges=a7["edge_strips"], passed=a7["pass"], by_frame=a7["by_frame"])
        wav, full = d / f"the-run-v5d-{r}-2997.sound.wav", d / f"the-run-v5d-{r}-theme-full-42403ms.wav"
        snd = sound(n, wav, full)
        smov = d / f"the-run-v5d-{r}-2997-sound.mov"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(master), "-i", str(wav), "-map", "0:v:0",
                        "-map", "1:a:0", "-c:v", "copy", "-c:a", "pcm_s16le", "-shortest", str(smov)], check=True)
        docs, dumps = load_dumps([OUT / "view-settings-shared.blender.json"]
                                 + sorted(d.glob("view-settings-*.blender.json")))
        fr = VS.frames(n, set(range(n)), ev, ev, dumps)
        if any(x["recorded"] != "blender" for x in fr):
            raise SystemExit(f"{r}: frames without a Blender read-back: "
                             f"{[x['frame'] for x in fr if x['recorded'] != 'blender'][:10]}")
        doc = {"record": r, "master": smov.name, "master_sha256": VS.sha256(smov), "frames": fr, "recorded": VS.LEGEND,
               "sources": {"shared": str(OUT / RW / "exposure.json"), "tail": str(d / "exposure.json"),
                           "tail_frames": len(redo), "blender_read_back": n}}
        (d / "view-settings.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
        dv = VS.document_view(doc, VS.display_of(docs, True))
        (d / (smov.stem + ".view.json")).write_text(json.dumps(dv, indent=1), encoding="utf-8")
        pose = fr[f["k_from"]]
        if (pose["view_transform"], pose["look"], pose["exposure"]) != (view["name"], view["look"], view["exposure"]):
            raise SystemExit(f"{r}: the declared view {view} is not the pose frame's read-back {pose}")
        item = item_for(r, smov, a7, view, f, n, items_v5c)
        slot = slot_for(items_v5c["films"][r]["slot"], item["id"], n)
        items["films"][r] = {"film": items_v5c["films"][r].get("film"), "item": item, "slot": slot,
                             "sound": {k: v for k, v in snd.items() if k != "foley"}, "theme_full_mix": str(full)}
        report["films"][r] = {"a7": a7, "master": str(master), "sound_master": str(smov), "preview": str(preview),
                              "sidecar": str(d / (smov.stem + ".view.json")), "tail_frames": len(redo),
                              "display": {k: dv.get(k) for k in VS.DISPLAY_KEYS}}
    (OUT / "title-items-v5d.json").write_text(json.dumps(items, indent=1, ensure_ascii=False), encoding="utf-8")
    led = json.loads(LEDGER.read_text(encoding="utf-8"))
    shutil.copy2(LEDGER, LEDGER.with_name(f"masters-ledger.pre-v5d-{time.strftime('%Y%m%d-%H%M%S')}.json"))
    keep = [i for i in led["items"] if not str(i.get("id", "")).startswith("TS-v5d-")]
    led["items"] = keep + [items["films"][r]["item"] for r in films]
    LEDGER.write_text(json.dumps(led, indent=1, ensure_ascii=False), encoding="utf-8")
    report["ledger"] = {"path": str(LEDGER), "added": [f"TS-v5d-{r}" for r in films]}
    (OUT / "final-v5d-report.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    log("final v5d done", a7={r: (v["a7"]["a7"], v["a7"]["edge_strips"], v["a7"]["pass"]) for r, v in
                              report["films"].items()})


if __name__ == "__main__":
    main()
