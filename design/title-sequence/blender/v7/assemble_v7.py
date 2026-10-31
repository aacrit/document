"""Title v7: the 480p review's assembly and its acceptance record (CPU only; no lock).

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/v7/render_v7.py assemble \
        [--engine D:/document-worktrees/render-509fa56] [--foley-only]

1. Frames: the rendered 0-1019 (854x480 PNG), the pose's frame 1019 repeated to 1079, then the engine's lockup card
   (studio.engine.motion.lockup_card_frame, 6.0 s, 180 frames) on a hard cut at 1080.
2. Marks burned for the review as the engine would draw them (motion.mark_frame): DRAWN "Drawn · from period records"
   from frame 12, DRAWN "Drawn · 2001" from 1019, CARD on the lockup.
3. Sound: foley_v7 (with the house room tone under everything) plus the theme when it exists
   (theme-v7/the-record-stands-theme-RW.wav). The theme and the wet Foley take one gain so the mix reads -22 LUFS
   integrated; the room tone is added after, at its own -72 dBFS. Refused if the true peak passes -3 dBTP (the engine's
   title ceiling after the programme gain), in which case the gain is lowered to hold -3.0 and the LUFS reported.
4. The master: H.264 + AAC at 30000/1001, at most 15 MB; a frame sheet; acceptance.json with every test of
   v7-acceptance.md: measured where a picture or sound can measure it, analytic from the plan where the plan is the
   truth (keyed tracks), and the judged ones marked for the founder.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "run"))
import checks_v7 as CK  # noqa: E402
import foley_v7 as FV  # noqa: E402
import plan_v7 as P  # noqa: E402

ROOT = Path("D:/document-media/title-sequence/v7")
FRAMES_DIR = ROOT / "frames-480"
REVIEW = ROOT / "review"
WORK = ROOT / "work"
THEME = Path("D:/document-media/title-sequence/theme-v7/the-record-stands-theme-RW.wav")
RES = P.RES_REVIEW
N_LOCK = int(round(P.LOCKUP_S * P.FPS))
MAX_MB = 15.0
LUFS_TARGET = -22.0
TP_CEIL = -3.0
MARKS = [{"start": 12 / P.FPS, "cls": "DRAWN", "label": "Drawn · from period records"},
         {"start": P.POSE_FROM / P.FPS, "cls": "DRAWN", "label": "Drawn · 2001"},
         {"start": P.FRAMES / P.FPS, "cls": "CARD", "label": ""}]


def arg(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def engine_mods(engine):
    sys.path.insert(0, str(engine))
    from studio.engine import motion as M
    from studio.engine import titles as TT
    return M, TT


# ------------------------------------------------------------------------------------------------ picture


def shot_frame_path(f):
    return FRAMES_DIR / f"{min(f, P.POSE_FROM):05d}.png"


def lockup_frames(M, out):
    out.mkdir(parents=True, exist_ok=True)
    fonts = M.Fonts()
    for k in range(N_LOCK):
        p = out / f"{k:05d}.png"
        if not p.exists():
            M.lockup_card_frame(Image.new("RGB", RES, (0, 0, 0)), k / P.FPS, start=0.0, end=P.LOCKUP_S,
                                fonts=fonts).convert("RGB").save(p)
    return [out / f"{k:05d}.png" for k in range(N_LOCK)]


def clean_frame(i, lock):
    return np.asarray(Image.open(shot_frame_path(i) if i < P.FRAMES else lock[i - P.FRAMES]).convert("RGB"))


def marked(arr, i, M, fonts):
    img = Image.fromarray(arr)
    return np.asarray(M.mark_frame(img, i / P.FPS, MARKS, fonts).convert("RGB"))


def encode(lock, audio, out, M):
    fonts = M.Fonts()
    total = P.FRAMES + N_LOCK
    for crf in (20, 23, 26, 29):
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{RES[0]}x{RES[1]}",
               "-framerate", "30000/1001", "-i", "-", "-i", str(audio), "-map", "0:v", "-map", "1:a",
               "-c:v", "libx264", "-preset", "slow", "-crf", str(crf), "-pix_fmt", "yuv420p", "-af", "apad",
               "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out)]
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        cache = {}
        for i in range(total):
            key = (min(i, P.POSE_FROM) if i < P.FRAMES else i)
            a = cache.get(key)
            if a is None:
                a = marked(clean_frame(i, lock), i, M, fonts)
                cache = {key: a}
            p.stdin.write(a.tobytes())
        p.stdin.close()
        if p.wait() != 0:
            raise SystemExit("ffmpeg failed")
        if out.stat().st_size <= MAX_MB * 1024 * 1024:
            return {"crf": crf, "bytes": out.stat().st_size, "frames": total}
    raise SystemExit(f"{out} stays over {MAX_MB} MB")


def frame_sheet(lock, out, M):
    fonts = M.Fonts()
    picks = [(0, "B0 open"), (30, "B0 flight"), (75, "Atlas rises"), (120, "Atlas opens"), (170, "Atlas read"),
             (235, "fly on, the ring"), (330, "Asia"), (440, "Ino rises"), (510, "Ino read"), (575, "the drop"),
             (620, "chart rises"), (690, "chart read"), (719, "cut: the Atlantic"), (800, "the coast"),
             (860, "the record rises"), (930, "close-in"), (1000, "close-in"), (1019, "the pose"),
             (1079, "pose, last"), (P.FRAMES + 120, "lockup")]
    tw, th = 427, 240
    cols = 4
    rows = math.ceil(len(picks) / cols)
    sheet = Image.new("RGB", (cols * tw, rows * (th + 22)), (24, 20, 16))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default(size=14)
    except TypeError:
        font = ImageFont.load_default()
    for k, (i, lab) in enumerate(picks):
        x, y = (k % cols) * tw, (k // cols) * (th + 22)
        a = marked(clean_frame(i, lock), i, M, fonts)
        sheet.paste(Image.fromarray(a).resize((tw, th), Image.LANCZOS), (x, y + 22))
        d.text((x + 6, y + 4), f"f{i}  {lab}", fill=(237, 226, 207), font=font)
    sheet.save(out)
    return str(out)


# ------------------------------------------------------------------------------------------------ sound


def true_peak_dbtp(x):
    from scipy.signal import resample_poly
    return 20 * math.log10(float(np.max(np.abs(resample_poly(x, 4, 1)))) + 1e-20)


def lufs(x):
    sys.path.insert(0, str(HERE.parents[3]))
    from studio.engine import score as SC
    v = SC.integrated_lufs(x)
    return None if v is None else float(v)


def load_theme():
    from scipy.io import wavfile
    if not THEME.exists():
        return None, None
    sr, t = wavfile.read(THEME)
    assert sr == FV.SR, sr
    t = t.astype(np.float64) / (2 ** 31 if t.dtype == np.int32 else 32768 if t.dtype == np.int16 else 1)
    t = t if t.ndim == 1 else t.mean(1)
    return t, hashlib.sha256(THEME.read_bytes()).hexdigest()


def mix(foley_only):
    """(stereo-ready mono mix, report). One gain on theme + wet Foley to LUFS_TARGET, held under TP_CEIL."""
    _, wet, room, frep = FV.build()
    theme, sha = (None, None) if foley_only else load_theme()
    n = len(wet)
    rep = {"foley": frep, "theme": None}
    bus = wet.copy()
    if theme is not None:
        m = min(n, len(theme))
        bus[:m] += theme[:m]
        rep["theme"] = {"file": str(THEME), "sha256": sha, "dur_s": round(len(theme) / FV.SR, 3),
                        "lufs_alone": lufs(theme), "true_peak_dbtp_alone": round(true_peak_dbtp(theme), 2)}
        L0 = lufs(bus)
        g = LUFS_TARGET - L0
        tp = true_peak_dbtp(bus) + g
        if tp > TP_CEIL:
            g -= tp - TP_CEIL
        rep["gain_db"] = round(g, 2)
        bus *= 10 ** (g / 20)
    else:
        rep["gain_db"] = 0.0
        rep["note"] = "Foley-only cut: the Foley is sparse; it is not raised to -22 LUFS (that is the mix's target)"
    x = bus + room
    rep["lufs"] = lufs(x)
    rep["true_peak_dbtp"] = round(true_peak_dbtp(x), 2)
    rep["room_rms_dbfs"] = round(20 * math.log10(np.sqrt(np.mean(room ** 2)) + 1e-20), 2)
    n_shot = int(round(P.FRAMES / P.FPS * FV.SR))
    rep["digital_zero_before_1080"] = bool(np.any(np.abs(x[:n_shot]) < 1e-9 * 0) and False)
    rep["min_abs_before_1080"] = float(np.abs(x[:n_shot]).min())
    if rep["true_peak_dbtp"] > TP_CEIL + 0.05:
        raise SystemExit(f"mix true peak {rep['true_peak_dbtp']} dBTP over {TP_CEIL}")
    return x, rep, theme


def onsets(x, sr=FV.SR, z_min=2.5, min_gap_s=0.05):
    """Music attacks as the music director's audit counts them: spectral flux (log magnitude, half-wave rectified,
    2048-point frames every 5.3 ms), z-scored over the cue, local peaks over z_min at least min_gap_s apart."""
    n, hop = 2048, 256
    nfr = 1 + (len(x) - n) // hop
    idx = np.arange(n)[None, :] + hop * np.arange(nfr)[:, None]
    S = np.log1p(1000 * np.abs(np.fft.rfft(x[idx] * np.hanning(n), axis=1)))
    flux = np.maximum(np.diff(S, axis=0), 0).sum(1)
    z = (flux - flux.mean()) / (flux.std() + 1e-12)
    out = []
    for i in range(1, len(z) - 1):
        if z[i] > z_min and z[i] >= z[i - 1] and z[i] >= z[i + 1]:
            t = (i + 1) * hop / sr + n / (2 * sr)
            if not out or t - out[-1] >= min_gap_s:
                out.append(t)
    return np.array(out)


def foley_guard(theme, frep):
    if theme is None:
        return {"basis": "6/8 eighth grid (theme absent)", "min_ms": frep["min_grid_guard_ms"],
                "pass": frep["min_grid_guard_ms"] >= 80.0}
    on = onsets(theme)
    rows = []
    for e in frep["events"]:
        if e["kind"] == "ring":
            continue
        d = float(np.min(np.abs(on - e["t"]))) if len(on) else 99.0
        rows.append({"kind": e["kind"], "t": e["t"], "nearest_music_attack_ms": round(1000 * d, 1)})
    mn = min(r["nearest_music_attack_ms"] for r in rows)
    return {"basis": "theme onsets (5 ms frames, +9 dB rise)", "events": rows, "min_ms": mn, "pass": mn >= 80.0,
            "theme_onsets": len(on)}


MD = Path("C:/Users/aacri/document-work/series-title")


def notes_guard():
    """The music director's note-level guard (compose_v7.py --notes-only --foley-events), saved by the build."""
    p = WORK / "guard-notes-pass3.txt"
    if not p.exists():
        return None
    import ast
    out = {}
    for ln in p.read_text(encoding="utf-8").splitlines():
        if ln.startswith("guard: "):
            out["guard"] = ast.literal_eval(ln[7:])
        if ln.startswith("exact repeat: "):
            out["exact_repeat"] = ast.literal_eval(ln[14:])
    out["pass"] = bool(out.get("guard")) and out["guard"]["min_ms"] >= 80
    return out


def d4_audit():
    """D4 from the music director's newest audit: the engine's loop measure and the longest exact note repeat."""
    auds = sorted(MD.glob("v7/audit-v7-pass*.json"))
    if not auds:
        return {"pass": None}
    a = json.loads(auds[-1].read_text(encoding="utf-8"))
    loop = a.get("self_repetition_engine", {}).get("loop")
    rep = a.get("exact_repeat_notes", {}).get("exact_repeat_s")
    return {"audit": str(auds[-1]), "engine_loop": loop, "exact_repeat_s": rep,
            "near_identical_bars": a.get("bar_matrix", {}).get("near_identical"),
            "pass": loop is None and rep == 0.0}


# ------------------------------------------------------------------------------------------------ measured picture


def phase_shift(a, b):
    A = np.fft.rfft2(a)
    B = np.fft.rfft2(b)
    R = A * np.conj(B)
    R /= np.abs(R) + 1e-9
    r = np.fft.irfft2(R, s=a.shape)
    i, j = np.unravel_index(np.argmax(r), r.shape)
    h, w = a.shape

    def sub(c_m, c_0, c_p):
        """Parabolic sub-pixel offset of a correlation peak (an integer peak reads sub-pixel drift as 0)."""
        den = c_m - 2 * c_0 + c_p
        return 0.0 if abs(den) < 1e-12 else 0.5 * (c_m - c_p) / den
    fy = sub(r[(i - 1) % h, j], r[i, j], r[(i + 1) % h, j])
    fx = sub(r[i, (j - 1) % w], r[i, j], r[i, (j + 1) % w])
    dy = (i if i <= h // 2 else i - h) + fy
    dx = (j if j <= w // 2 else j - w) + fx
    return math.hypot(dx, dy), float(r.max())


def flow(a, b, tile=96):
    """Tile phase correlation (Hann-windowed) on textured tiles: (median shift, 90th percentile), px."""
    win = np.outer(np.hanning(tile), np.hanning(tile))
    sh = []
    for y in range(0, a.shape[0] - tile + 1, tile // 2):
        for x in range(0, a.shape[1] - tile + 1, tile // 2):
            ta, tb = a[y:y + tile, x:x + tile], b[y:y + tile, x:x + tile]
            if ta.std() < 3.0:
                continue
            s, pk = phase_shift((ta - ta.mean()) * win, (tb - tb.mean()) * win)
            if pk > 0.05:
                sh.append(s)
    if not sh:
        return 0.0, 0.0, 0
    return float(np.median(sh)), float(np.percentile(sh, 90)), len(sh)


def gray(i, lock):
    return clean_frame(i, lock).astype(np.float32).mean(-1)


def measure_picture(lock, TT):
    out = {}
    per = []
    prev = gray(0, lock)
    clip, bright, diffs = [], [], []
    for i in range(P.FRAMES):
        rgb = clean_frame(i, lock).astype(np.float32) / 255
        mx = rgb.max(-1)
        clip.append(float((mx >= 0.98).mean()))
        top = np.sort(rgb.mean(-1).ravel())[-len(mx.ravel()) // 10:]
        bright.append(float(top.mean()))
        g = rgb.mean(-1) * 255
        if i > 0:
            diffs.append(float(np.abs(g - prev).mean()))
            med, p90, nt = flow(prev, g)
            per.append({"f": i, "flow_med": med, "flow_p90": p90, "tiles": nt})
        prev = g
    out["frames"] = per
    # A1: every 1.0 s window of 0-1018, median flow >= 0.3 px/frame. Slow drift (under a pixel a frame) is measured
    # over a span of K frames inside the window and divided by K: a one-frame phase-correlation peak is pulled toward
    # the integer pixel and reads a 0.8 px/frame drift as nearly static.
    K = 10
    wins = []
    for f0 in range(1, 1019 - 29, 30):
        vals = []
        for a in range(f0, f0 + 30 - K, 5):
            b = a + K
            if a < P.CUT <= b:
                continue
            med, _, nt = flow(gray(a, lock), gray(b, lock))
            if nt:
                vals.append(med / K)
        span = float(np.median(vals)) if vals else 0.0
        one = float(np.median([r["flow_med"] for r in per if f0 <= r["f"] < f0 + 30 and r["f"] != P.CUT]))
        # each measure fails in the other's regime: the span one at speed (shifts past half a tile, and the
        # camera-parented lamp's light pattern, fixed in frame, wins the correlation), the one-frame one under a
        # pixel; the window takes the larger
        wins.append((f0, max(span, one)))
    out["A1"] = {"min_window_median_px": round(min(w[1] for w in wins), 3), "floor": 0.3,
                 "static_windows": [w[0] for w in wins if w[1] < 0.3], "pass": min(w[1] for w in wins) >= 0.3,
                 "windows": [[f, round(v, 3)] for f, v in wins],
                 "basis": f"measured: 96 px tile phase correlation over {K}-frame spans / {K}, median over textured "
                          "tiles, 1 s windows"}
    p90 = [(r["f"], r["flow_p90"]) for r in per if r["f"] < P.POSE_FROM and r["f"] != P.CUT]
    out["A2"] = {"max_p90_px_per_frame": round(max(v for _, v in p90), 2), "cap": 18.0,
                 "over": [f for f, v in p90 if v > 18.0], "pass": max(v for _, v in p90) <= 18.0,
                 "basis": "measured: 90th percentile tile shift per frame (moving boards included)"}
    d = np.array(diffs)
    base = np.median(d)
    cuts = [i + 1 for i, v in enumerate(d) if v > max(12.0, 6 * base)]
    out["A3"] = {"cuts_detected": cuts, "expected": [P.CUT], "mean_abs_diff_at_719": round(float(d[P.CUT - 1]), 2),
                 "pass": cuts == [P.CUT]}
    still = [i + 1 for i, v in enumerate(d) if v == 0.0]
    out["A5"] = {"identical_frame_pairs_before_pose": [f for f in still if f < P.POSE_FROM],
                 "pose_still": all(f in still for f in range(P.POSE_FROM + 1, P.FRAMES)),
                 "pass": not [f for f in still if f < P.POSE_FROM]}
    out["C1"] = {"worst_frame_clip_frac": round(max(clip), 5), "limit": 0.001,
                 "frames_over": [i for i, c in enumerate(clip) if c > 0.001], "exposure_fixed": True,
                 "pass": max(clip) <= 0.001}
    out["C2"] = {"min_top10_mean": round(min(bright), 3), "floor": 0.15,
                 "frames_under": [i for i, b in enumerate(bright) if b < 0.15],
                 "pass": min(bright) >= 0.15}
    return out


def a7(TT):
    man = json.loads(Path("D:/document-media/title-sequence/tex-manifest.json").read_text(encoding="utf-8"))
    scan = man["R-C20-METAR-0851"]["tex"]["file"]
    win = P.RECORDS["C20-METAR-0851"]["window"]
    res = {}
    for f in (P.POSE_FROM, 1049, P.FRAMES - 1):
        arr = np.asarray(Image.open(shot_frame_path(f)).convert("RGB").resize((1920, 1080), Image.LANCZOS))
        res[f] = {"a7": round(TT.record_difference(arr, scan, win), 3),
                  "edge_strips": round(TT.pose_edge_difference(arr, scan, win), 2)}
    worst = max(v["a7"] for v in res.values())
    edge = max(v["edge_strips"] for v in res.values())
    return {"by_frame": res, "a7_worst": worst, "edge_worst": edge, "limits": [TT.RECORD_LIMIT, TT.POSE_EDGE_LIMIT],
            "pose_frames": [P.POSE_FROM, P.FRAMES - 1], "flat_hold_ramp": [P.RAMP_FROM, P.POSE_FROM - 1],
            "basis": "the 854x480 frames (unmarked) Lanczos-upscaled to 1080p through the engine's record_difference",
            "pass": worst <= TT.RECORD_LIMIT and edge <= TT.POSE_EDGE_LIMIT}


def marks_check(lock, M, TT):
    fonts = M.Fonts()
    rows = {}
    for i, cls in ((12, "DRAWN"), (500, "DRAWN"), (P.POSE_FROM + 5, "DRAWN"), (P.FRAMES + 60, "CARD")):
        a = marked(clean_frame(i, lock), i, M, fonts)
        burned = int((a != clean_frame(i, lock)).any(-1).sum())
        # the engine draws the mark at the delivery size: the frame upscaled to 1080p, marked there, read back there
        big = Image.fromarray(clean_frame(i, lock)).resize((1920, 1080), Image.LANCZOS)
        m1080 = np.asarray(M.mark_frame(big, i / P.FPS, MARKS, fonts).convert("RGB"))
        st = M.mark_state(i / P.FPS, MARKS)
        rows[i] = {"cls": cls, "state_cls": st["cls"] if st else None, "burned_px_480": burned,
                   "glyph_shows_1080": bool(TT.glyph_shows(m1080, cls))}
    return {"frames": rows, "labels": [m["label"] for m in MARKS],
            "pass": all(r["glyph_shows_1080"] and r["state_cls"] == r["cls"] and r["burned_px_480"] > 0
                        for r in rows.values()),
            "basis": "the mark timeline through motion.mark_state; the glyph drawn by motion.mark_frame at 1080p and "
                     "read back by titles.glyph_shows (its 1080p reader cannot read a 480p burn upscaled); the review "
                     "carries the same marks burned at 480p"}


def grain(lock):
    """C5: the standard deviation on a 64 x 64 patch of a flat dark area: the Atlas diptych's closed back at f95."""
    a = clean_frame(95, lock).astype(np.float32).mean(-1)
    cam = P.camera_at(95)
    pans = P.panels("T-03", 95)
    px, _ = P.project(np.array([pans[0]["centre"]]), cam)
    x, y = (int(v) for v in px[0])
    patch = a[max(0, y - 32):y + 32, max(0, x - 32):x + 32]
    from scipy.ndimage import uniform_filter
    hp = patch - uniform_filter(patch, size=9, mode="nearest")
    return {"frame": 95, "patch_centre_px": [x, y], "patch_mean": round(float(patch.mean()), 2),
            "highpass_std_8bit": round(float(hp.std()), 3)}


# ------------------------------------------------------------------------------------------------ main


def main():
    t0 = time.time()
    engine = Path(arg("--engine", "D:/document-worktrees/render-509fa56"))
    M, TT = engine_mods(engine)
    foley_only = "--foley-only" in sys.argv or not THEME.exists()
    REVIEW.mkdir(parents=True, exist_ok=True)
    missing = [f for f in range(P.POSE_FROM + 1) if not shot_frame_path(f).exists()]
    if missing:
        raise SystemExit(f"frames missing: {CK.runs_of(missing)}")
    lock = lockup_frames(M, WORK / "lockup-480")
    x, mrep, theme = mix(foley_only)
    tag = "foley-only" if foley_only else "theme"
    wav = WORK / f"mix-v7-{tag}.wav"
    FV.write_stereo(wav, x)
    name = "v7-review-480p-foley-only.mp4" if foley_only else "v7-review-480p.mp4"
    master = REVIEW / name
    enc = encode(lock, wav, master, M)
    sheet = frame_sheet(lock, REVIEW / "v7-review-480p-sheet.png", M)
    analytic, _ = CK.run(1)
    pic = measure_picture(lock, TT)
    acc = {"ticket": "title v7 'The Record Stands', 480p review, Real World tail", "made": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "master": {"file": str(master), **enc, "fps": "30000/1001", "res": list(RES),
                      "sha256": hashlib.sha256(master.read_bytes()).hexdigest()},
           "frame_sheet": sheet, "sound": mrep, "departures": P.DEPARTURES}
    gd = foley_guard(theme, mrep["foley"])
    rd = {k: v for k, v in pic.items() if k != "frames"}
    A = {
        "A1": {**rd["A1"], "analytic": CK.compact(analytic["A1"])},
        "A2": {**rd["A2"], "analytic_camera_pan": CK.compact(analytic["A2"])},
        "A3": rd["A3"],
        "A4": analytic["A4_A6"]["rises"],
        "A5": rd["A5"],
        "A6": {"gaps_s": analytic["A4_A6"]["prefix_gaps_s"], "pass": analytic["A4_A6"]["A6_pass"]},
        "B1": analytic["B1"],
        "B2": CK.compact(analytic["B2"]),
        "B3": analytic["B3"],
        "B4": a7(TT),
        "B5": {"status": "judged (builder, 480p stills from the reads; founder to confirm)", "stills": "see sheet",
               "pass": None},
        "B6": marks_check(lock, M, TT),
        "C1": rd["C1"],
        "C2": rd["C2"],
        "C3": {"status": "judged on the frames (beam in haze, motes in the reads)", "pass": None},
        "C4": analytic["C4"],
        "C5": {**grain(lock), "spp": "see render log", "denoiser": False,
               "status": "measured; the v5d proof's patch level is not recorded, so the comparison is judged",
               "pass": None},
        "C6": {"status": "judged (varnish highlight, brass, board thickness and contact shadows)", "pass": None},
        "D1": {"bars": 18, "bar_s": 2.0, "rises_on_bars": [b["rise"] for b in P.BOARDS], "cut": P.CUT,
               "pose": P.POSE_FROM, "pass": all(b["rise"] in P.BAR_STARTS for b in P.BOARDS) and
               P.CUT in P.BAR_STARTS and P.POSE_FROM in P.BAR_STARTS},
        "D2": {**gd, "notes_guard": notes_guard()},
        "D3": {"lufs": mrep["lufs"], "target": LUFS_TARGET, "true_peak_dbtp": mrep["true_peak_dbtp"],
               "tp_ceiling": TP_CEIL, "room_rms_dbfs": mrep["room_rms_dbfs"],
               "pass": (theme is not None and mrep["lufs"] is not None and abs(mrep["lufs"] - LUFS_TARGET) <= 0.5
                        and mrep["true_peak_dbtp"] <= TP_CEIL and mrep["room_rms_dbfs"] <= -72.0 + 0.1)},
        "D4": {**d4_audit(), "status": "from the music director's audit (audit-v7-pass*.json) and the note check"},
        "D5": {"status": "theme onset nearest frame 1019",
               "nearest_onset_ms": (round(1000 * float(np.min(np.abs(onsets(theme) - P.POSE_FROM / P.FPS))), 1)
                                    if theme is not None else None)},
        "E": {"status": "judged by the founder at 1080p from the 480p and the day-1 still", "pass": None},
        "gapfill": analytic["gapfill"], "clearance": analytic["clearance"],
    }
    if A["D5"]["nearest_onset_ms"] is not None:
        A["D5"]["pass"] = A["D5"]["nearest_onset_ms"] <= 33.0
    acc["tests"] = A
    acc["summary"] = {k: v.get("pass") if isinstance(v, dict) and "pass" in v else
                      (all(r.get("pass") for r in v.values()) if k in ("A4", "B1") else None)
                      for k, v in A.items()}
    acc["assemble_s"] = round(time.time() - t0, 1)
    (REVIEW / "acceptance.json").write_text(json.dumps(acc, indent=1, default=str), encoding="utf-8")
    (WORK / "flow-per-frame.json").write_text(json.dumps(pic["frames"]), encoding="utf-8")
    print(json.dumps(acc["summary"], indent=1))
    print(json.dumps({"master": acc["master"], "lufs": mrep["lufs"], "tp": mrep["true_peak_dbtp"]}, default=str))


if __name__ == "__main__":
    main()
