"""The Run v5d: the shot checked frame by frame against Fable's keys and plan (numpy only, no render).

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/check_v5d.py [--out <json>]

1. The marble is in frame on every frame 0-975 (its centre inside the 16:9 frame; the margin is reported).
2. No film's record is in frame on any frame 32-929 (any point of its sheet inside the frustum, no occlusion).
3. The felt well (its mouth at the top) is in frame only inside the plan's windows (0-33, 303-314, 844-850, 863-874,
   885-1090), each end allowed TOL frames.
4. Each rack (the keys' marble -> sheet -> marble runs): the marble's blur at most half its image, its image at least
   90 px, the marble at most 0.30 m/s, the soft span at least 0.5 s from a step or a bank, at most 0.5 s out, 0.5 s
   held and 0.4 s back. And on every frame 0-975, the marble's blur at most half its image.
Blur and size are at 1080p (the thin-lens circle of confusion of the marble's centre).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import channel_v5c as C  # noqa: E402
import shot_v5c as SH  # noqa: E402
import shot_v5d as SD  # noqa: E402

FPS = 30000 / 1001
SIM = Path("D:/document-media/title-sequence/run/sim/v5c")
MARBLE_FRAMES = (0, 975)
RECORD_DARK = (32, 929)
WELL_WINDOWS = [(0, 33), (303, 314), (844, 850), (863, 874), (885, 1090)]
TOL = 2
STEPS = (475, 863)                       # the corrected timeline's steps
BANKS = (228, 354, 550, 681)             # into / out of turn 1 and turn 2
HALF_S = 0.5


def runs(mask):
    out, start = [], None
    for i, m in enumerate(list(mask) + [False]):
        if m and start is None:
            start = i
        elif not m and start is not None:
            out.append((start, i - 1))
            start = None
    return out


def marble_screen(frames):
    out = []
    for fr in frames:
        sx, sy, z = SD.screen_of(fr["eye"], fr["tgt"] - fr["eye"], fr["p"], fr["up"])
        out.append((sx, sy, z))
    return out


RACK_MIN_RATIO = 0.15      # a focus pull that softens the marble past this (of its own image) is a rack


def racks(keys, frames=None):
    """(marble key, first sheet key, last sheet key, marble key) for each rack in the keys: a run of keys focused on a
    sheet's point, between keys on the marble. With frames, a pull that keeps the marble within RACK_MIN_RATIO of its
    image (B6's jeton: the marble at 0.78 m stays sharp beside it) is not a rack."""
    def is_point(k):
        t = k.get("focus_target", "marble")
        return t != "marble" and not t.startswith("split:") and t != "run centroid"
    out = []
    for r in _point_runs(keys, is_point):
        if frames is not None:
            peak = max(frames[f]["marble_blur_px"] / frames[f]["marble_px"] for f in range(r[0]["f"], r[3]["f"] + 1))
            if peak < RACK_MIN_RATIO:
                continue
        out.append(r)
    return out


def focus_pulls(keys, frames):
    """The sheet-point pulls that are not racks (the marble stays sharp), each with the marble's worst blur."""
    rk = {r[1]["f"] for r in racks(keys, frames)}
    out = []
    for r in racks(keys):
        if r[1]["f"] not in rk:
            span = range(r[0]["f"], r[3]["f"] + 1)
            f = max(span, key=lambda i: frames[i]["marble_blur_px"])
            out.append({"sheet": r[1]["focus_target"], "frames": [r[0]["f"], r[3]["f"]], "peak_frame": f,
                        "marble_blur_px": round(frames[f]["marble_blur_px"], 1),
                        "marble_px": round(frames[f]["marble_px"], 1)})
    return out


def _point_runs(keys, is_point):
    out, i = [], 0
    while i < len(keys):
        if is_point(keys[i]):
            j = i
            while j + 1 < len(keys) and is_point(keys[j + 1]):
                j += 1
            out.append((keys[i - 1], keys[i], keys[j], keys[j + 1]))
            i = j + 1
        else:
            i += 1
    return out


VISIBLE_MIN = 0.5           # the share of the marble's camera-facing surface that must clear the carved top


def marble_visible(eye, p, n_pts=48, n_steps=160, reach=0.12):
    """The share of the marble's camera-facing surface the eye sees past the carved top (channel_v5c.height: the
    groove's own walls and the banks). Sheets, rolls and objects are not modelled, so this is an upper bound."""
    eye, p = np.asarray(eye, float), np.asarray(p, float)
    v = eye - p
    v /= np.linalg.norm(v)
    rng = np.random.default_rng(0)
    d = rng.normal(size=(n_pts * 4, 3))
    d /= np.linalg.norm(d, axis=1)[:, None]
    d = d[d @ v > 0.15][:n_pts]                       # points on the hemisphere facing the eye
    pts = p + C.R * d
    seen = 0
    for q in pts:
        ray = eye - q
        L = np.linalg.norm(ray)
        t = np.linspace(0.0015, min(reach, L), n_steps) / L
        P = q + t[:, None] * ray
        if (P[:, 2] >= C.height(P[:, 0], P[:, 1]) - 1e-5).all():
            seen += 1
    return seen / max(len(pts), 1)


def check(frames, keys, speed):
    n = len(frames)
    res = {"frames": n}
    scr = marble_screen(frames)
    # 1. the marble in frame
    a, b = MARBLE_FRAMES
    inside = [abs(sx) <= 0.5 and abs(sy) <= 0.5 and z > 0 for sx, sy, z in scr]
    margin = [min(0.5 - abs(sx), 0.5 - abs(sy)) * 1080 for sx, sy, _ in scr]      # px at 1080p, the tighter side
    out = [f for f in range(a, b + 1) if not inside[f]]
    first_out = next((f for f in range(b + 1, n) if not inside[f]), None)
    res["marble_in_frame"] = {"frames": [a, b], "pass": not out, "out_frames": out[:20],
                              "min_margin_px_1080p": round(min(margin[a:b + 1]), 1),
                              "min_margin_at": int(np.argmin(margin[a:b + 1])) + a, "first_out_after": first_out}
    # 1b. the marble seen past the groove's walls (every 3rd frame, 0-975): reported apart from the frustum check
    vis = {f: marble_visible(frames[f]["eye"], frames[f]["p"]) for f in range(a, b + 1, 3)}
    low = [f for f, s in vis.items() if s < VISIBLE_MIN]
    hid = np.zeros(n, bool)
    for f in low:
        hid[f:min(f + 3, b + 1)] = True                 # each sample stands for its 3 frames
    res["marble_unoccluded"] = {"frames": [a, b], "step": 3, "min_share": VISIBLE_MIN, "pass": not low,
                                "hidden_runs": runs(hid),
                                "hidden_sampled": len(low), "worst": round(min(vis.values()), 2),
                                "note": "ray-cast against the carved top only (sheets and rolls not modelled)"}
    # 2. the records dark
    z = C.felt_top() + C.ITEMS["record"]["h"]
    rec = {}
    for r in C.RECORDS:
        seen = SH.rect_seen(frames, C.record_rect(r), z) > 0
        bad = [f for f in range(RECORD_DARK[0], RECORD_DARK[1] + 1) if seen[f]]
        rec[r] = {"pass": not bad, "seen_in_dark_window": runs([f in set(bad) for f in range(n)]),
                  "seen_runs": runs(seen)}
    res["record_never_in_frame"] = {"frames": list(RECORD_DARK), "pass": all(v["pass"] for v in rec.values()),
                                    "by_record": rec}
    # 3. the well's windows
    well = SH.rect_seen(frames, (*C.WELL["x"], *C.WELL["y"]), 0.0) > 0
    allowed = np.zeros(n, bool)
    for w0, w1 in WELL_WINDOWS:
        allowed[max(w0 - TOL, 0):min(w1 + TOL, n - 1) + 1] = True
    stray = [f for f in range(n) if well[f] and not allowed[f]]
    res["well_windows"] = {"plan": WELL_WINDOWS, "measured": runs(well), "tolerance_frames": TOL,
                           "pass": not stray, "outside_plan": runs([f in set(stray) for f in range(n)])}
    # 4. the racks, and the marble's blur everywhere it is in frame
    ratio = [fr["marble_blur_px"] / fr["marble_px"] for fr in frames]
    over = [f for f in range(a, b + 1) if ratio[f] > 0.5]
    res["blur_ratio_everywhere"] = {"frames": [a, b], "max": round(max(ratio[a:b + 1]), 3),
                                    "at": int(np.argmax(ratio[a:b + 1])) + a, "pass": not over, "over": over[:20]}
    rk = []
    for m0, p0, p1, m1 in racks(keys, frames):
        f0, f1 = m0["f"], m1["f"]
        span = range(f0, f1 + 1)
        peak = max(span, key=lambda f: frames[f]["marble_blur_px"])
        gap = min([abs(s - f0) if s < f0 else abs(s - f1) if s > f1 else 0 for s in STEPS + BANKS])
        row = {"sheet": p0["focus_target"], "soft_frames": [f0, f1], "peak_frame": peak,
               "blur_px": round(frames[peak]["marble_blur_px"], 1), "marble_px": round(frames[peak]["marble_px"], 1),
               "blur_ratio": round(max(ratio[f] for f in span), 3),
               "min_marble_px": round(min(frames[f]["marble_px"] for f in span), 1),
               "max_speed_ms": round(max(speed[f] for f in span), 3),
               "out_s": round((p0["f"] - f0) / FPS, 3), "hold_s": round((p1["f"] - p0["f"]) / FPS, 3),
               "back_s": round((f1 - p1["f"]) / FPS, 3), "gap_to_step_or_bank_s": round(gap / FPS, 3)}
        row["pass"] = (row["blur_ratio"] <= 0.5 and row["min_marble_px"] >= 90 and row["max_speed_ms"] <= 0.30
                       and row["gap_to_step_or_bank_s"] >= HALF_S and row["out_s"] <= 0.5 and row["hold_s"] <= 0.5
                       and row["back_s"] <= 0.4)
        rk.append(row)
    res["racks"] = rk
    res["focus_pulls_not_racks"] = focus_pulls(keys, frames)
    # the marble at the steps and the latch: sharp (the plan: the camera is sharp on the marble at all three)
    res["accents"] = {str(f): round(frames[f]["marble_blur_px"], 1) for f in (0,) + STEPS}
    res["pass_specified"] = all(res[k]["pass"] for k in ("marble_in_frame", "record_never_in_frame", "well_windows",
                                                          "blur_ratio_everywhere")) and all(r["pass"] for r in rk)
    res["pass"] = res["pass_specified"] and res["marble_unoccluded"]["pass"]
    return res


def marble_speed(bake, n):
    tr = np.array(bake["track"])
    return list(np.interp(np.arange(n) / FPS, tr[:, 0], tr[:, 3]))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--record", default="C20-METAR-0851")
    a = ap.parse_args(argv)
    rep = json.loads((SIM / "run-timing.json").read_text(encoding="utf-8"))
    bake = json.loads((SIM / "run-bake.json").read_text(encoding="utf-8"))
    frames = SD.shot(bake, FPS, rep["rest_sim_s"], a.record)
    _, keys = SD.load_keys()
    res = check(frames, keys, marble_speed(bake, len(frames)))
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps({k: (v["pass"] if isinstance(v, dict) and "pass" in v else v) for k, v in res.items()
                      if k != "racks"}))
    for r in res["racks"]:
        print(json.dumps(r))
    print("well measured:", res["well_windows"]["measured"])
    print("records:", {k: v["seen_runs"] for k, v in res["record_never_in_frame"]["by_record"].items()})
    print("marble:", res["marble_in_frame"])
    print("marble seen past the groove:", {k: v for k, v in res["marble_unoccluded"].items() if k != "note"})
    print("blur ratio:", res["blur_ratio_everywhere"])
    return 0 if res["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
