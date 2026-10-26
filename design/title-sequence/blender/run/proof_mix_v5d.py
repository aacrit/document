"""The Run v5d proof, finished for review: the 36.403 s shot, then the 6 s series lockup card, with the title theme, the
corrected Foley (its slow leather lifted) and the room tone (CPU only; no lock).

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/proof_mix_v5d.py \
        --engine D:/document-worktrees/render-509fa56

- The lockup: studio.engine.motion.lockup_card_frame from an engine checkout that has it (A40 lockup card, BRAND-KIT
  15: the words whole from the first frame, the logomark's corners close on DRIFT from the cut, the ember over its
  last tenth), 180 frames at 29.97 at 854x480, after frame 1090. The ember's timing is reported against the theme's
  37.27 s (compose_v5d.EMBER_S).
- The Foley: foley_v5c on the corrected timing (sim/v5d), with the leather bed raised by LEATHER_LIFT_DB (the music
  director: v5c's leather sat 12.6 dB under the oak and L7/L8 were lost under the theme; the target is the Foley at
  least about +6 dB over the music at p10 in 400 Hz - 2.5 kHz). The Foley stops at the cut; the room tone runs on
  under the lockup (the theme carries none there).
- The mix: theme at unity + Foley at unity (its room tone extended to 42.403 s), as the music director's check mix.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, "D:/document-media/house-room/tools")

OUT = Path("D:/document-media/title-sequence/run/proofs/v5d")
THEME = Path("D:/document-media/title-sequence/theme-v5d/the-run-theme-v5d.wav")
FPS_S, FPS = "30000/1001", 30000 / 1001
SHOT_FRAMES = 1091
LOCKUP_S = 6.0
THEME_EMBER_S = SHOT_FRAMES / FPS + 0.87            # compose_v5d.EMBER_S
MAX_MB = 15.0


def lockup_frames(engine, n, size, out_dir):
    sys.path.insert(0, str(engine))
    from studio.engine import motion as M
    out_dir.mkdir(parents=True, exist_ok=True)
    fonts = M.Fonts()
    for k in range(n):
        t = k / FPS
        img = M.lockup_card_frame(Image.new("RGB", size, (0, 0, 0)), t, start=0.0, end=LOCKUP_S, fonts=fonts)
        img.convert("RGB").save(out_dir / f"{k:05d}.png")
    # the ember: alpha = (DRIFT progress - 0.9) / 0.1; when it first shows, when it is whole
    ts = np.arange(0, LOCKUP_S, 0.001)
    p = np.array([min(max(M.DRIFT.progress(t), 0.0), 1.0) for t in ts])
    first = float(ts[np.argmax(p > 0.9)]) if (p > 0.9).any() else None
    p99 = float(ts[np.argmax(p >= 0.99)]) if (p >= 0.99).any() else None
    whole = float(ts[np.argmax(p >= 0.9999)]) if (p >= 0.9999).any() else None
    cut = SHOT_FRAMES / FPS
    return {"engine": str(engine), "frames": n, "drift": {"k": M.DRIFT.k, "c": M.DRIFT.c, "m": M.DRIFT.m},
            "ember_first_visible_s": None if first is None else round(cut + first, 3),
            "drift_progress_0p99_s": None if p99 is None else round(cut + p99, 3),
            "ember_whole_s": None if whole is None else round(cut + whole, 3),
            "theme_ember_s": round(THEME_EMBER_S, 3),
            "matches_theme": p99 is not None and abs(cut + p99 - THEME_EMBER_S) <= 1.5 / FPS}


def foley(lift_db, timing, room_tone=True):
    import foley_v5c as FV
    base = dict(FV.ZONE)
    g, lp = base["leather"]
    FV.ZONE["leather"] = (g * 10 ** (lift_db / 20), lp)
    try:
        mix, rep = FV.build("C20-METAR-0851", timing, room_tone)
    finally:
        FV.ZONE.clear()
        FV.ZONE.update(base)
    rep["leather_lift_db"] = lift_db
    return mix, rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True, help="a checkout whose studio.engine.motion has lockup_card_frame")
    ap.add_argument("--lift", type=float, default=None, help="leather lift in dB (default: searched)")
    a = ap.parse_args()
    import clean as CL
    import foley as FO
    from scipy.io import wavfile
    timing = Path("D:/document-media/title-sequence/run/sim/v5d")
    report = json.loads((OUT / "proof-report.json").read_text(encoding="utf-8")) if (OUT / "proof-report.json").exists() \
        else {}
    # 1. the leather lift: the smallest whole dB that clears the theme by +6 dB at p10 on the leather (measured with
    # the music director's own audibility measure)
    sys.path.insert(0, "C:/Users/aacri/document-work/series-title")
    import measure_v5d as MV
    theme = MV.load48(THEME)
    tl = json.loads(Path(MV.C.TIMELINE).read_text(encoding="utf-8"))
    evs = [(float(e["t"]), e["event"]) for e in tl["events"] if "contact impulse marble|oak" not in e["event"]]

    def audit(mix):
        y = mix if FO.SR == MV.RATE else MV.S.resample(mix, int(round(len(mix) * MV.RATE / FO.SR)))
        return MV.foley_audibility(theme, y, evs)

    lifts = [a.lift] if a.lift is not None else [0, 3, 6, 8, 10, 12]
    tried = []
    for lift in lifts:
        mix, frep = foley(lift, timing)
        au = audit(mix)
        tried.append({"lift_db": lift, "leather_p10_db": au["per_surface"]["leather"]["p10_db"],
                      "oak_p10_db": au["per_surface"]["oak"]["p10_db"], "all_p10_db": au["p10_db"]})
        if au["per_surface"]["leather"]["p10_db"] >= 6.0:
            break
    stem = OUT / "v5d-foley-lifted.wav"
    st = np.stack([mix, mix], 1)
    wavfile.write(stem, FO.SR, (np.clip(st, -1, 1) * 32767).astype(np.int16))
    (OUT / "v5d-foley-lifted.foley-report.json").write_text(json.dumps(frep, indent=1), encoding="utf-8")
    report["foley_lift"] = {"tried": tried, "chosen_db": lift, "stem": str(stem), "foley": frep}
    # 2. the mix: 42.403 s; the Foley (with its room) to the cut, the room alone under the lockup, the theme at unity
    sr = FO.SR
    n_all = int(round((SHOT_FRAMES / FPS + LOCKUP_S) * sr))
    th = theme if MV.RATE == sr else MV.S.resample(theme, int(round(len(theme) * sr / MV.RATE)))
    th = np.pad(th, (0, max(0, n_all - len(th))))[:n_all]
    room = CL.room_bed(n_all, "the-run-v5d-proof")
    dry = np.zeros(n_all)
    fol_no_room, _ = foley(lift, timing, room_tone=False)
    dry[:len(fol_no_room)] = fol_no_room[:n_all]
    out = th + dry + room
    peak = float(np.abs(out).max())
    wav = OUT / "v5d-proof-mix.wav"
    wavfile.write(wav, sr, (np.clip(np.stack([out, out], 1), -1, 1) * 32767).astype(np.int16))
    report["mix"] = {"wav": str(wav), "duration_s": round(n_all / sr, 3), "peak_dbfs": round(20 * math.log10(peak), 2),
                     "theme": str(THEME), "foley_gain": 1.0, "theme_gain": 1.0,
                     "room": "clean.room_bed -72 dBFS under the whole 42.403 s"}
    # 3. the lockup frames and the video: the 1091 proof frames, then 180 lockup frames
    n_lock = int(round(LOCKUP_S * FPS))
    ldir = OUT / "lockup-480"
    report["lockup"] = lockup_frames(Path(a.engine), n_lock, (854, 480), ldir)
    lst = OUT / "frames-all.txt"
    lines = [f"file '{(OUT / 'frames-480' / f'{f:05d}.png').as_posix()}'" for f in range(SHOT_FRAMES)]
    lines += [f"file '{(ldir / f'{k:05d}.png').as_posix()}'" for k in range(n_lock)]
    lst.write_text("\n".join(f"{ln}\nduration {1 / FPS:.9f}" for ln in lines) + "\n", encoding="utf-8")
    mp4 = OUT / "v5d-proof-480p.mp4"
    total_s = (SHOT_FRAMES + n_lock) / FPS
    kbps = int(MAX_MB * 8 * 1024 * 0.90 / total_s) - 192
    for _ in range(4):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-i", str(wav), "-map", "0:v:0", "-map", "1:a:0", "-vf", f"fps={FPS_S}", "-c:v", "libx264",
                        "-preset", "slow", "-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.3)}k",
                        "-bufsize", f"{kbps * 2}k", "-pix_fmt", "yuv420p", "-r", FPS_S, "-frames:v",
                        str(SHOT_FRAMES + n_lock), "-c:a", "aac", "-b:a", "192k", "-t", f"{total_s:.6f}",
                        "-movflags", "+faststart", str(mp4)], check=True)
        if mp4.stat().st_size <= MAX_MB * 2 ** 20:
            break
        kbps = int(kbps * 0.85)
    probe = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_entries",
                            "stream=codec_type,nb_read_frames,r_frame_rate,duration", "-of", "json", str(mp4)],
                           capture_output=True, text=True, check=True)
    report["proof"] = {"path": str(mp4), "mb": round(mp4.stat().st_size / 2 ** 20, 2), "video_kbps": kbps,
                       "ffprobe": json.loads(probe.stdout)["streams"]}
    # 4. the sidecar (the shot's frames read back; the lockup is a card: no view transform, exposure 0)
    import proof_v5d as P
    ev = json.loads((OUT / "exposure.json").read_text(encoding="utf-8"))["ev"]
    sc, dv, rb = P.sidecar(mp4, ev, SHOT_FRAMES, OUT / "view-settings-480.blender.json")
    report["view_sidecar"] = {"path": str(sc), "blender_read_back_frames": rb, "frames": len(dv["exposure"]),
                              "display": {k: dv.get(k) for k in ("display_device", "gamma", "use_curve_mapping")},
                              "defaults_assumed": dv.get("defaults_assumed"),
                              "covers": "the shot's 1091 frames; the lockup card after them is drawn, not rendered"}
    (OUT / "proof-report.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("foley_lift", "mix", "lockup", "proof", "view_sidecar")}, default=str,
                     indent=1)[:6000])


if __name__ == "__main__":
    main()
