"""Laid Down: the final masters, one per film's record (the founder chose Laid Down, 2026-10-26). One heavy job.

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/final_laid_down.py \
        --engine D:/document-worktrees/render-f6f51c0 [--plan-only] [--chunk 30] [--cpu-only]

Settings as the final v5c/v5d masters: 2560x1440, Cycles OptiX, 512 spp (the minimum: adaptive sampling never stops a
pixel short of it; threshold 0.02), motion blur (180 degrees), NO denoiser, Lanczos to a 1920x1080 ProRes 422 HQ
master at 30000/1001. The shot's fixed exposure is the brightest-channel meter of the stills (exposure.json: the
chart's paper nearest the lamp at 0.85, spec rev 3 section 5), carried in the light: the lamp's power and the indirect
clamp scaled by 2^EV, the view at Standard, look None, exposure 0, so the record's flat-hold emission is exactly 1.0
and the frames are the stills' pixels; the declared view (exposure 0) is then the render's own, for A7 like for like.

1. The renders (laid_down.final_plan): the master opens on its own black (frames 0-11, drawn); the shared shot is
   rendered once as Real World's (C20-METAR-0851), each run of identical frames once; S-130 and S-16928 re-render only
   the frames whose state differs (their record in play, the descent onto their own pose). Chunks of --chunk frames,
   one Blender process each, under HEAVY.lock (D: not dirty, C: and D: over 10 GB, a live holder waited on, a dead
   one cleared, the lock released after every chunk with a pause so a queued job can take it). Every rendered frame's
   view is read back from Blender.
2. Per record (CPU): the ProRes master and an H.264 preview; no channel may clip (checked on every rendered frame); A7
   and the pose edges through the declared view (studio.engine.titles at --engine) at the pose's first frame, its
   middle and the last; the sound (the record's theme mix, ducked around the chart's slide as the animatic, + its
   Foley with the balance + the room tone at -72 dBFS) muxed at 29.97 into the -sound master for the shot's length,
   the full 40.434 s mix kept beside it; the document.view/1 sidecar from Blender's read-back.
3. title-items-laid-down.json beside the masters and TS-ld-<record> items in the masters ledger (backed up first;
   the v1, v5c and v5d entries untouched), view_transform declared.
"""

from __future__ import annotations

import argparse
import copy
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
from scipy.io import wavfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import laid_down as L  # noqa: E402
import render_laid_down_stills as RS  # noqa: E402

ROOT = Path("D:/document-media/title-sequence/laid-down")
OUT = ROOT / "masters"
THEME = Path("D:/document-media/title-sequence/theme-laid-down")
LEDGER = Path("C:/Users/aacri/document-work/title-sequence/masters-ledger.json")
ITEMS_V5C = Path("D:/document-media/title-sequence/run/masters/final-v5c/title-items-v5c.json")
FPS_S, FPS = "30000/1001", L.FPS
FINAL = {"res": "2560x1440", "samples": 512, "min_samples": 512, "threshold": 0.02}
LOCKUP_S = 6.0
TRUE_PEAK_MAX_DBTP = -1.5
VIEW = {"name": "Standard", "look": "None", "exposure": 0.0}
PAUSE_S = 15                                   # after releasing the lock: a queued job (the RW release encode) goes


def log(msg, **kv):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}" + (" " + json.dumps(kv, default=str) if kv else "")
    print(line, flush=True)
    with (OUT / "final-laid-down.log").open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def light_ev():
    return float(json.loads((ROOT / "exposure.json").read_text(encoding="utf-8"))["ev"])


def jobs(plan):
    out = [("shared", L.RW, OUT / "frames-2560", plan["shared"])]
    for r, f in plan["films"].items():
        if f["tail"]:
            out.append(("tail", r, OUT / r / "tail-2560", f["tail"]))
    return out


def blender_chunk(frames, outdir, record, ev, tag):
    vs = outdir.parent / f"view-{tag}-{frames[0]:05d}.blender.json"
    cmd = [RS.BLENDER, "-b", "-noaudio", "--factory-startup", "--python", str(HERE / "scene_laid_down.py"), "--",
           "--frame", str(frames[0]), "--frames", ",".join(str(f) for f in frames), "--outdir", str(outdir),
           "--res", FINAL["res"], "--samples", str(FINAL["samples"]), "--min_samples", str(FINAL["min_samples"]),
           "--threshold", str(FINAL["threshold"]), "--exposure", "0.0", "--light_ev", f"{ev:.7f}",
           "--record", record, "--depth", "8", "--vs", str(vs), "--out", str(outdir)]
    env = dict(os.environ, TEMP=str(ROOT / "tmp"), TMP=str(ROOT / "tmp"))
    RS.take_lock(f"Laid Down final {tag} {record} f{frames[0]}-f{frames[-1]} ({len(frames)} frames, 2560x1440 512 spp)",
                 log=log)
    try:
        t0 = time.time()
        p = subprocess.run(cmd, capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    finally:
        RS.drop_lock()
    lg = outdir.parent / f"blender-{tag}-{frames[0]:05d}.log"
    lg.write_text(p.stdout[-300000:] + "\n" + p.stderr[-50000:], encoding="utf-8")
    info = next((json.loads(ln[9:]) for ln in p.stdout.splitlines() if ln.startswith("LD-STILL ")), None)
    if p.returncode != 0 or info is None:
        for f in outdir.glob("*.png"):
            if f.stat().st_size == 0:
                f.unlink()
        raise SystemExit(f"blender failed ({p.returncode}); log in {lg}")
    if info["denoise"] or "no denoiser" not in info["renderer"]:
        raise SystemExit(f"a denoiser in {lg}")
    return round(time.time() - t0, 1), info


def render_all(plan, ev, chunk):
    rep = []
    for tag, rec, d, frames in jobs(plan):
        d.mkdir(parents=True, exist_ok=True)
        todo = [f for f in frames if not (d / f"{f:05d}.png").exists()]
        for i in range(0, len(todo), chunk):
            free = RS.preflight()
            part = todo[i:i + chunk]
            wall, info = blender_chunk(part, d, rec, ev, tag)
            rep.append({"job": tag, "record": rec, "from": part[0], "to": part[-1], "n": len(part), "wall_s": wall,
                        "s_per_frame": round(wall / len(part), 1), "renderer": info["renderer"], "free_gb": free})
            log("chunk", **rep[-1])
            time.sleep(PAUSE_S)
    return rep


def black_frame():
    p = OUT / "black-2560.png"
    if not p.exists():
        Image.new("RGB", (2560, 1440), (0, 0, 0)).save(p)
    return p


def frame_files(plan, rec):
    out = []
    for kind, g in plan["films"][rec]["source"]:
        out.append(black_frame() if kind == "black" else
                   (OUT / "frames-2560" if kind == "shared" else OUT / rec / "tail-2560") / f"{g:05d}.png")
    return out


def encode(files, master, preview):
    """The master: every frame piped as RGB, Lanczos to 1920x1080 ProRes 422 HQ at 30000/1001 (final_v5c's), and an
    H.264 preview under 30 MB."""
    p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "2560x1440",
                          "-framerate", FPS_S, "-i", "-", "-vf", "scale=1920:1080:flags=lanczos", "-c:v", "prores_ks",
                          "-profile:v", "3", "-pix_fmt", "yuv422p10le", "-r", FPS_S, str(master)],
                         stdin=subprocess.PIPE)
    last, buf = None, None
    for fp in files:
        if fp != last:
            buf, last = np.asarray(Image.open(fp).convert("RGB"), np.uint8).tobytes(), fp
        p.stdin.write(buf)
    p.stdin.close()
    if p.wait() != 0:
        raise SystemExit("ffmpeg master failed")
    kbps = int(30 * 8 * 1024 * 0.92 / (len(files) / FPS))
    for _ in range(3):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(master), "-c:v", "libx264", "-preset", "slow",
                        "-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.3)}k", "-bufsize", f"{kbps * 2}k", "-pix_fmt",
                        "yuv420p", "-r", FPS_S, "-movflags", "+faststart", str(preview)], check=True)
        if preview.stat().st_size <= 30 * 1024 * 1024:
            break
        kbps = int(kbps * 0.85)


def clipping(plan):
    """Every rendered frame's brightest channel: none may clip (255)."""
    out = {}
    dirs = [("shared", OUT / "frames-2560", plan["shared"])] + \
        [(r, OUT / r / "tail-2560", f["tail"]) for r, f in plan["films"].items()]
    for tag, d, frames in dirs:
        worst = (0, None)
        n255 = 0
        for f in frames:
            a = np.asarray(Image.open(d / f"{f:05d}.png").convert("RGB"))
            m = int(a.max())
            n255 += int((a == 255).any(-1).sum())
            worst = max(worst, (m, f))
        out[tag] = {"frames": len(frames), "max_channel": worst[0], "at_frame": worst[1], "pixels_at_255": n255}
    return out


def sound(rec, n, path_mov_audio, path_full):
    """The record's theme mix (its sha256 checked), ducked around the chart's slide as in the animatic, + its Foley with
    the balance and the room tone (foley_laid_down), at unity; refused over TRUE_PEAK_MAX_DBTP."""
    import hashlib

    import foley_laid_down as FL
    import render_laid_down_animatic as RA
    fol, frep = FL.build(rec, LOCKUP_S)
    w = THEME / f"laid-down-theme-{rec}.wav"
    sums = dict(ln.split(" *")[::-1] for ln in (THEME / "SHA256SUMS").read_text(encoding="utf-8").split("\n") if " *" in ln)
    sha = hashlib.sha256(w.read_bytes()).hexdigest()
    if sums.get(w.name) != sha:
        raise SystemExit(f"{w} does not match SHA256SUMS")
    sr, t = wavfile.read(w)
    if sr != FL.SR:
        raise SystemExit(f"the theme is {sr} Hz, the Foley {FL.SR}")
    t = t.astype(np.float64) / (2 ** 31 if t.dtype == np.int32 else 32768.0)
    t = t.mean(1) if t.ndim > 1 else t
    g, duck = FL.theme_duck(len(t), frep["events"], sr)
    n_all = max(len(t), len(fol))
    mix = np.zeros(n_all)
    mix[:len(t)] += t * g
    mix[:len(fol)] += fol
    tp = RA.true_peak_dbtp(mix)
    if tp > TRUE_PEAK_MAX_DBTP:
        raise SystemExit(f"{rec}: mix true peak {tp:.2f} dBTP over {TRUE_PEAK_MAX_DBTP}")
    st = (np.clip(np.stack([mix, mix], 1), -1, 1) * 32767).astype(np.int16)
    wavfile.write(path_full, sr, st)
    n_shot = int(round(n / FPS * sr))
    wavfile.write(path_mov_audio, sr, st[:n_shot])
    a, b = int((frep["events"][-2]["settle_tap_s"] + 1.5) * sr), int((frep["events"][-1]["heard_s"] - 0.1) * sr)
    room = 20 * math.log10(float(np.sqrt(np.mean(fol[a:b] ** 2))) + 1e-20)
    return {"theme": str(w), "theme_sha256": sha, "theme_gain": 1.0, "theme_duck": duck, "foley_gain": 1.0,
            "room": "clean.room_bed -72 dBFS RMS (in the Foley)", "room_measured_dbfs": round(room, 1),
            "true_peak_dbtp": round(tp, 2), "full_s": round(n_all / sr, 3), "master_s": round(n_shot / sr, 3),
            "foley_events": frep["events"]}


def readbacks():
    """{(job dir, frame): Blender's read-back} from every chunk's view-*.blender.json, and the display read-backs."""
    out, docs = {}, []
    for p in sorted(OUT.rglob("view-*.blender.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        docs.append(d)
        for fr in d["frames"]:
            out[(p.parent.name, fr["frame"])] = fr
    return out, docs


def sidecar(rec, plan, smov, ev):
    import view_settings_v5c as VS
    rb, docs = readbacks()
    lamp_w = round(L.BEATS["lamp"]["power_w"] * 2 ** ev, 6)
    frames = []
    for f, (kind, g) in enumerate(plan["films"][rec]["source"]):
        if kind == "black":
            frames.append({"frame": f, "view_transform": VIEW["name"], "look": VIEW["look"], "exposure": 0.0,
                           "recorded": "drawn"})
            continue
        key = ("masters" if kind == "shared" else rec, g)
        d = rb.get(key)
        if d is None:
            raise SystemExit(f"{rec}: frame {f} (rendered as {kind} {g}) has no Blender read-back")
        if (d["view_transform"], d["look"], d["exposure"]) != (VIEW["name"], VIEW["look"], VIEW["exposure"]) or \
                abs(d["lamp_w"] - lamp_w) > 1e-3:
            raise SystemExit(f"{rec}: frame {f}'s read-back {d} is not the declared view {VIEW} at lamp {lamp_w} W")
        frames.append({"frame": f, "view_transform": d["view_transform"], "look": d["look"], "exposure": d["exposure"],
                       "recorded": "blender", "rendered_as": [kind, g]})
    doc = {"record": rec, "master": smov.name, "master_sha256": VS.sha256(smov), "frames": frames,
           "recorded": {"blender": "read back from the scene as Blender evaluated it at the frame that was rendered "
                                   "(scene_laid_down.py --vs); a repeated hold frame carries its rendered frame's",
                        "drawn": "the opening black (frames 0-11, A40: the master opens from its own black), drawn, "
                                 "not rendered: no view applies; the shot's view is stated"},
           "light": {"lamp_w": lamp_w, "light_ev": ev, "basis": "the shot's exposure is in the lamp (90 W x 2^EV) and "
                     "the indirect clamp, not in the view, so the view exposure is 0 on every frame"}}
    (smov.parent / "view-settings.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
    dv = VS.document_view(doc, VS.display_of(docs, True))
    dv["recorded"] = {"exposure": f"per frame, see view-settings.json: {sum(x['recorded'] == 'blender' for x in frames)} "
                                  f"read back from Blender, {sum(x['recorded'] == 'drawn' for x in frames)} drawn black",
                      "view_transform_look": "read back from Blender on every rendered frame",
                      "display": "read back from Blender by every render that made the master's frames"}
    (smov.parent / VS.view_sidecar_name(smov)).write_text(json.dumps(dv, indent=1), encoding="utf-8")
    return dv, VS.view_sidecar_name(smov)


def a7(master, rec, frames, engine):
    import tail_v5c as T
    sys.path.insert(0, str(Path(engine).resolve()))
    for k in [m for m in sys.modules if m == "studio" or m.startswith("studio.")]:
        del sys.modules[k]
    from studio.engine import titles as TT
    if not str(Path(TT.__file__).resolve()).startswith(str(Path(engine).resolve())):
        raise SystemExit(f"studio.engine.titles is {TT.__file__}, not {engine}'s")
    out = T.a7_master(master, rec, frames, VIEW)
    out["engine"] = str(Path(TT.__file__).resolve())
    return out


def item_for(rec, smov, a7r, sidecar_name, n, items_v5c, rec_from, snd):
    base = copy.deepcopy(items_v5c["films"][rec]["item"])
    r = L.RECORDS[rec]
    pose = r["record_pose"]["from_frame"]
    base.update({
        "series": "void document · As It Was", "id": f"TS-ld-{rec}",
        "file": f"../laid-down/masters/{rec}/{smov.name}", "frames": n, "denoise": False, "burned": False,
        "record_frames": [rec_from, n - 1],
        "record_pose": {"window": [round(v, 6) for v in r["record_window"]], "from_frame": pose},
        "marks": [{"frame": L.BEATS["marks"][0]["frame"], "cls": "DRAWN", "label": "Drawn · from period records"},
                  {"frame": pose, "cls": r["cls"], "label": r["label"]}],
        "renderer": f"Blender 4.4.3 Cycles (OptiX), {FINAL['samples']} spp (adaptive sampling with a {FINAL['min_samples']}"
                    f" spp minimum), noise threshold {FINAL['threshold']}, no denoiser",
        "bytes": smov.stat().st_size, "sha256": RS_sha(smov), "version": "laid-down", "date": time.strftime("%Y-%m-%d"),
        "title": f"void document · As It Was, series titles Laid Down, record {rec} ({items_v5c['films'][rec].get('film', '')})",
        "generator": "Blender 4.4.3 Cycles (scene_laid_down.py; closed-form Coulomb slides laid_down.py on Fable's "
                     "beats, spec rev 3; bake_laid_down.py), final_laid_down.py; Foley foley_laid_down.py; theme "
                     "the music director's laid-down mix",
        "codec": "ProRes 422 HQ (yuv422p10le), PCM s16le: the Laid Down theme (ducked 4 dB around the chart's slide), "
                 "the Foley and the room at -72 dBFS",
        "a7": a7r["a7"], "a7_edge_strips": a7r["edge_strips"],
        "view_transform": {"name": VIEW["name"], "look": VIEW["look"], "sidecar": sidecar_name,
                           "basis": "the render's own view settings, read back from Blender on every rendered frame, "
                                    "in the sidecar beside the master (document.view/1): Standard, look None, exposure "
                                    "0 on every frame (the shot's exposure is in the lamp)"},
        "a7_basis": "A7 like for like (studio.engine.titles at origin/main f6f51c0, ocio backend): the scan through the "
                    f"sidecar's Standard, look None and exposure 0 at each of frames {', '.join(str(k) for k in a7r['by_frame'])}; "
                    "worst frame",
        "content_basis": base.get("content_basis", "").replace("the machine's materials end with",
                                                               "the pile's sheets end with"),
        "sound": {k: v for k, v in snd.items() if k != "foley_events"}})
    base.pop("provenance_note", None)
    return base


def RS_sha(p):
    import view_settings_v5c as VS
    return VS.sha256(p)


def slot_for(asset, n):
    return [{"id": "TS1", "kind": "title_sequence", "asset": asset, "dur": round(n / FPS, 3), "mark": "DRAWN",
             "transition_in": {"type": "cut"}},
            {"id": "TS1b", "kind": "card", "card": "lockup", "dur": LOCKUP_S, "transition_in": {"type": "cut"},
             "mark": "CARD", "text": ["void document · As It Was"],
             "why": "the lockup card, the last 6 s of the title slot (as the film builders hold it)"}]


def finish(plan, ev, engine):
    items_v5c = json.loads(ITEMS_V5C.read_text(encoding="utf-8"))
    n = L.FRAMES
    report = {"clipping": clipping(plan), "films": {}}
    if any(v["max_channel"] >= 255 for v in report["clipping"].values()):
        raise SystemExit(f"a channel clips: {report['clipping']}")
    log("clipping", **report["clipping"])
    items = {"_note": items_v5c["_note"], "films": {}}
    for rec in L.RECORDS:
        d = OUT / rec
        d.mkdir(parents=True, exist_ok=True)
        stem = f"laid-down-{rec}-2997"
        master, preview = d / f"{stem}.mov", d / f"{stem}-preview.mp4"
        encode(frame_files(plan, rec), master, preview)
        pose = L.RECORDS[rec]["record_pose"]["from_frame"]
        a7r = a7(master, rec, [pose, (pose + n - 1) // 2, n - 1], engine)
        log("a7", record=rec, a7=a7r["a7"], edges=a7r["edge_strips"], passed=a7r["pass"], by_frame=a7r["by_frame"])
        if not a7r["pass"]:
            raise SystemExit(f"{rec}: A7 fails {a7r}")
        wav, full = d / f"{stem}.sound.wav", d / f"laid-down-{rec}-theme-full-40434ms.wav"
        snd = sound(rec, n, wav, full)
        smov = d / f"{stem}-sound.mov"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(master), "-i", str(wav), "-map", "0:v:0",
                        "-map", "1:a:0", "-c:v", "copy", "-c:a", "pcm_s16le", "-shortest", str(smov)], check=True)
        dv, sc_name = sidecar(rec, plan, smov, ev)
        rec_from = L.record_from(rec)
        item = item_for(rec, smov, a7r, sc_name, n, items_v5c, rec_from, snd)
        items["films"][rec] = {"film": items_v5c["films"][rec].get("film"), "item": item,
                               "slot": slot_for(item["id"], n), "theme_full_mix": str(full)}
        report["films"][rec] = {"a7": a7r, "master": str(master), "sound_master": str(smov), "preview": str(preview),
                                "sidecar": str(d / sc_name), "tail_frames": len(plan["films"][rec]["tail"]),
                                "true_peak_dbtp": snd["true_peak_dbtp"], "room_dbfs": snd["room_measured_dbfs"]}
    (OUT / "title-items-laid-down.json").write_text(json.dumps(items, indent=1, ensure_ascii=False), encoding="utf-8")
    led = json.loads(LEDGER.read_text(encoding="utf-8"))
    backup = LEDGER.with_name(f"masters-ledger.pre-laid-down-{time.strftime('%Y%m%d-%H%M%S')}.json")
    shutil.copy2(LEDGER, backup)
    keep = [i for i in led["items"] if not str(i.get("id", "")).startswith("TS-ld-")]
    led["items"] = keep + [items["films"][r]["item"] for r in L.RECORDS]
    LEDGER.write_text(json.dumps(led, indent=1, ensure_ascii=False), encoding="utf-8")
    report["ledger"] = {"path": str(LEDGER), "backup": str(backup), "added": [f"TS-ld-{r}" for r in L.RECORDS],
                        "kept": [i.get("id") for i in keep]}
    return report


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True)
    ap.add_argument("--plan-only", action="store_true")
    ap.add_argument("--cpu-only", action="store_true", help="the masters from frames already rendered")
    ap.add_argument("--chunk", type=int, default=30)
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    plan = L.final_plan()
    ev = light_ev()
    est = {"shared": len(plan["shared"]), "tails": {r: len(f["tail"]) for r, f in plan["films"].items()},
           "renders": len(plan["shared"]) + sum(len(f["tail"]) for f in plan["films"].values()),
           "light_ev": ev, "lamp_w": round(L.BEATS["lamp"]["power_w"] * 2 ** ev, 4), "sampling": FINAL}
    (OUT / "final-plan.json").write_text(json.dumps({"estimate": est, "plan": plan}, indent=1), encoding="utf-8")
    if a.plan_only:
        dirty = subprocess.run(["fsutil", "dirty", "query", "D:"], capture_output=True, text=True).stdout.strip()
        est["machine"] = {"fsutil": dirty, "free_gb": {k: round(shutil.disk_usage(f"{k}:/").free / 2 ** 30, 1)
                                                       for k in ("C", "D")},
                          "lock": RS.read_lock() if RS.LOCK.exists() else None}
        print(json.dumps(est, indent=1, default=str))
        return est
    log("final laid down start", **est)
    report = {"estimate": est, "denoise": False}
    if not a.cpu_only:
        t0 = time.time()
        report["chunks"] = render_all(plan, ev, a.chunk)
        report["render_wall_s"] = round(time.time() - t0, 1)
    report.update(finish(plan, ev, a.engine))
    (OUT / "final-laid-down-report.json").write_text(json.dumps(report, indent=1, default=str, ensure_ascii=False),
                                                     encoding="utf-8")
    log("final laid down done", a7={r: (v["a7"]["a7"], v["a7"]["edge_strips"], v["a7"]["pass"])
                                    for r, v in report["films"].items()})


if __name__ == "__main__":
    main()
