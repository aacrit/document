"""Title v7: the analytic acceptance checks on the plan (no render): A1, A2, A3, A4, A5, A6, B1, B2, B3, C4, plus
the scan's gap-filled patches (kept out of the reads) and the camera's clearances.

    python design/title-sequence/blender/v7/checks_v7.py [--json out.json]

Each frame casts a 48 x 27 ray grid; a ray hits the ball or a board's panel. Image speeds are the 480p displacement of
each hit point from frame f to f + 1 (the scene's motion included: rising boards move). FILL at 1080p (spec: CoC < 2
px at 1080p defines in focus).
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import plan_v7 as P  # noqa: E402

GAP_BAND_DEG = 2.6          # the horizon ring's gap fill: |native lat + 0.4| under this (register crops)
GAP_STRIPE_DEG = 2.2        # the meridian ring's gap fill: within this of the ring plane
RING_NORMAL_NATIVE = np.array([-0.4026734850360063, -0.9152121288740642, 0.015518492541481813])


def tex_density(bid, k=0):
    """Source px per mm on a board's panel."""
    px_w = {"T-03": 2760, "T-08": 8192, "T-20": 8192, "C20-METAR-0851": 3840}[bid]
    w = P.RECORDS[bid]["size"][0] / (2 if P.RECORDS[bid].get("diptych") else 1)
    return px_w / (w * 1000)


def scene_panels(frame):
    out = []
    for b in P.BOARDS:
        if P.in_shot(b, frame):
            for p in P.panels(b["id"], frame):
                out.append((b["id"], p))
    return out


def hit(cam, d, frame):
    """For rays d from the eye: distance, what (-1 miss, 0 ball, k+1 panel k), and the hit points."""
    E = cam["E"]
    t = P.sphere_hit(E, d)
    what = np.where(np.isfinite(t), 0, -1)
    pans = scene_panels(frame)
    for k, (bid, p) in enumerate(pans):
        n = P.unit(np.cross(p["ex"], p["ey"]))
        den = d @ n
        ok = np.abs(den) > 1e-9
        tp = np.where(ok, ((p["centre"] - E) @ n) / np.where(ok, den, 1), np.inf)
        X = E + d * tp[:, None]
        a = ((X - p["centre"]) @ p["ex"]) / (p["ex"] @ p["ex"])
        b = ((X - p["centre"]) @ p["ey"]) / (p["ey"] @ p["ey"])
        inside = ok & (tp > 0) & (np.abs(a) <= 1) & (np.abs(b) <= 1) & (tp < t)
        t = np.where(inside, tp, t)
        what = np.where(inside, k + 1, what)
    X = E + d * np.where(np.isfinite(t), t, 0)[:, None]
    return t, what, X, pans


def panel_motion(X, what, pans, frame):
    """Hit points carried to frame + 1: ball points stay; panel points move with their panel."""
    Y = X.copy()
    nxt = scene_panels(frame + 1)
    for k, (bid, p) in enumerate(pans):
        m = what == k + 1
        if not m.any():
            continue
        q = next((q for (b2, q) in nxt if b2 == bid and q["tex"] == p["tex"]), None)
        if q is None:
            continue
        a = ((X[m] - p["centre"]) @ p["ex"]) / (p["ex"] @ p["ex"])
        b = ((X[m] - p["centre"]) @ p["ey"]) / (p["ey"] @ p["ey"])
        Y[m] = q["centre"] + a[:, None] * q["ex"] + b[:, None] * q["ey"]
    return Y


def gap_fill(X):
    Rg = P.registration()
    d = P.unit(X) @ Rg.T
    lat_n = np.degrees(np.arcsin(np.clip(d[:, 2], -1, 1)))
    band = np.abs(lat_n + 0.4) < GAP_BAND_DEG
    stripe = np.abs(np.degrees(np.arcsin(np.clip(d @ RING_NORMAL_NATIVE, -1, 1)))) < GAP_STRIPE_DEG
    return band | stripe


def frame_stats(frame, nx=48, ny=27):
    cam = P.camera_at(frame)
    cam1 = P.camera_at(frame + 1) if frame + 1 < P.FRAMES else cam
    d, xs, ys = P.rays(cam, P.RES_REVIEW, nx, ny)
    t, what, X, pans = hit(cam, d, frame)
    seen = what >= 0
    st = {"f": frame, "hit_frac": float(seen.mean()), "ball_frac": float((what == 0).mean())}
    # image speed (480p)
    if frame + 1 < P.FRAMES and frame + 1 != P.CUT and seen.any():
        Y = panel_motion(X[seen], what[seen], pans, frame)
        p0, z0 = P.project(X[seen], cam)
        p1, z1 = P.project(Y, cam1)
        sp = np.linalg.norm(p1 - p0, axis=1)
        ok = (z0 > 0) & (z1 > 0)
        ball = what[seen] == 0
        st["speed_max"] = float(sp[ok].max()) if ok.any() else 0.0
        st["speed_med"] = float(np.median(sp[ok])) if ok.any() else 0.0
        st["pan_max"] = float(sp[ok & ball].max()) if (ok & ball).any() else 0.0
    # FILL (1080p)
    coc = P.coc_px(t[seen], cam["focus"], cam["fstop"])
    dens = np.array([P.DENSITY if w == 0 else tex_density(pans[w - 1][0]) for w in what[seen]])
    fill = P.fill_at(t[seen], dens)
    focus = coc < P.COC_PX_1080
    st["fill_max_in_focus"] = float(fill[focus].max()) if focus.any() else 0.0
    ball_focus = focus & (what[seen] == 0)
    st["ball_fill_max_in_focus"] = float(fill[ball_focus].max()) if ball_focus.any() else 0.0
    # the limb: a ball ray next to a miss ray
    g = (what == 0).reshape(ny, nx)
    m = (what == -1).reshape(ny, nx)
    st["limb"] = bool(((g[:, :-1] & m[:, 1:]) | (m[:, :-1] & g[:, 1:])).any() or
                      ((g[:-1, :] & m[1:, :]) | (m[:-1, :] & g[1:, :])).any())
    st["board_in_frame"] = bool((what > 0).any())
    st["boards_seen"] = sorted({pans[w - 1][0] for w in what[seen] if w > 0})
    gf = gap_fill(X[what == 0]) if (what == 0).any() else np.zeros(0, bool)
    st["gapfill_frac"] = float(gf.mean()) if len(gf) else 0.0
    st["eye_alt"] = float(np.linalg.norm(cam["E"]) - P.R)
    near = [float(np.min(np.linalg.norm(P.corners(p) - cam["E"], axis=1))) for _, p in pans]
    st["eye_to_board_min"] = min(near) if near else None
    return st


def read_stats(bid):
    """B1 on the read window: board width fraction, centre, squareness, over each frame of the read."""
    b = P.board(bid)
    a, z = b["read"]
    rows = []
    for f in range(a, z + 1):
        cam = P.camera_at(f)
        pts = np.vstack([P.corners(p) for p in P.panels(bid, f)])
        px, _ = P.project(pts, cam)
        wfrac = (px[:, 0].max() - px[:, 0].min()) / P.RES_REVIEW[0]
        cx = (px[:, 0].max() + px[:, 0].min()) / 2 / P.RES_REVIEW[0]
        cy = (px[:, 1].max() + px[:, 1].min()) / 2 / P.RES_REVIEW[1]
        c, u, n, W = P.board_centre_up(bid)
        sq = math.degrees(math.acos(min(1.0, abs(float(P.unit(cam["E"] - c) @ n)))))
        rows.append({"f": f, "width_frac": wfrac, "cx": cx, "cy": cy, "square_deg": sq})
    good = [r for r in rows if r["width_frac"] >= 0.5 and 0.2 <= r["cx"] <= 0.8 and 0.2 <= r["cy"] <= 0.8
            and r["square_deg"] <= 12]
    return {"frames": len(rows), "good_frames": len(good), "good_s": len(good) / P.FPS,
            "width_min": min(r["width_frac"] for r in rows), "square_max": max(r["square_deg"] for r in rows),
            "cx_range": [min(r["cx"] for r in rows), max(r["cx"] for r in rows)],
            "cy_range": [min(r["cy"] for r in rows), max(r["cy"] for r in rows)],
            "pass": len(good) / P.FPS >= 2.4}


def rise_stats():
    out = {}
    for b in P.BOARDS:
        f0 = b["rise"]
        ang = [P.rise_angle(b["id"], f0 + k / 4) for k in range(4 * (P.RISE_FRAMES + 4))]
        over = max(ang) - P.LEAN_UP_DEG
        end = next(f for f in range(f0, f0 + 80) if all(abs(P.rise_angle(b["id"], g) - P.LEAN_UP_DEG) < 1e-6
                                                         for g in range(f, f + 5)))
        out[b["id"]] = {"start": f0, "frames": end - f0, "overshoot_deg": round(over, 2),
                        "rest_deg": round(P.rest_angle(b["id"]), 2),
                        "on_bar": f0 in P.BAR_STARTS,
                        "pass": f0 in P.BAR_STARTS and 44 <= end - f0 <= 48 and 1.0 <= over <= 3.0}
    starts = [b["rise"] for b in P.BOARDS if not b.get("tail")]
    gaps = [round((starts[i + 1] - starts[i]) / P.FPS, 2) for i in range(len(starts) - 1)]
    return {"rises": out, "prefix_gaps_s": gaps, "A6_pass": gaps == [12.0, 6.0] or
            all(abs(g - e) <= 1 / P.FPS + 1e-9 for g, e in zip(gaps, [12.0, 6.0]))}


def runs_of(fr):
    """[1,2,3,7] -> '1-3,7'."""
    fr = sorted(fr)
    out, i = [], 0
    while i < len(fr):
        j = i
        while j + 1 < len(fr) and fr[j + 1] == fr[j] + 1:
            j += 1
        out.append(f"{fr[i]}" if i == j else f"{fr[i]}-{fr[j]}")
        i = j + 1
    return ",".join(out)


def compact(obj):
    if isinstance(obj, dict):
        return {k: compact(v) for k, v in obj.items()}
    if isinstance(obj, list) and obj and all(isinstance(v, int) for v in obj) and len(obj) > 4:
        return runs_of(obj)
    return obj


def run(step=1):
    stats = [frame_stats(f) for f in range(0, P.FRAMES, step)]
    S = {s["f"]: s for s in stats}
    res = {"frames": len(stats)}
    sp = [s.get("pan_max", 0) for s in stats if s["f"] < P.POSE_FROM]
    res["A2"] = {"max_px_per_frame_480p": round(max(sp), 2), "cap": 18.0,
                 "over": [s["f"] for s in stats if s.get("pan_max", 0) > 18.0], "pass": max(sp) <= 18.0,
                 "basis": "camera pan: the ball's points (static scene); boards' own motion reported apart",
                 "board_motion_max": round(max(s.get("speed_max", 0) for s in stats if s["f"] < P.POSE_FROM), 2)}
    wins = []
    for f0 in range(0, P.POSE_FROM - 29, 30):
        med = float(np.median([S[f].get("speed_med", 0) for f in range(f0, f0 + 30) if f in S]))
        wins.append((f0, med))
    res["A1"] = {"min_window_median_px": round(min(w[1] for w in wins), 3), "floor": 0.3,
                 "static": [w[0] for w in wins if w[1] < 0.3], "pass": min(w[1] for w in wins) >= 0.3,
                 "basis": "median image speed of the hit grid (analytic flow); the measured flow is in measure_v7"}
    fl = [(s["f"], s["fill_max_in_focus"]) for s in stats]
    res["B2"] = {"max": round(max(v for _, v in fl), 3), "cap": P.FILL_CAP,
                 "over": [f for f, v in fl if v > P.FILL_CAP], "ball_max": round(max(s["ball_fill_max_in_focus"]
                                                                                    for s in stats), 3),
                 "pass": max(v for _, v in fl) <= P.FILL_CAP}
    flights = [s for s in stats if s["f"] < P.CUT and not s["board_in_frame"]] + \
              [s for s in stats if P.CUT <= s["f"] < 839]
    res["C4"] = {"limb_frac_flight": round(sum(s["limb"] for s in flights) / max(1, len(flights)), 3),
                 "pass": sum(s["limb"] for s in flights) / max(1, len(flights)) >= 0.8}
    res["B1"] = {bid: read_stats(bid) for bid in ("T-03", "T-08", "T-20")}
    res["B3"] = {"record_before_cut": [s["f"] for s in stats if s["f"] < P.CUT and "C20-METAR-0851" in s["boards_seen"]],
                 "prefix_after_cut": [s["f"] for s in stats if s["f"] >= P.CUT and
                                      any(b != "C20-METAR-0851" for b in s["boards_seen"])]}
    res["B3"]["pass"] = not res["B3"]["record_before_cut"] and not res["B3"]["prefix_after_cut"]
    res["A4_A6"] = rise_stats()
    res["A3"] = {"cut_frames": [P.CUT], "on_bar": P.CUT in P.BAR_STARTS, "pass": P.CUT in P.BAR_STARTS}
    reads = set()
    for b in P.BOARDS:
        reads |= set(range(b["read"][0], b["read"][1] + 1))
    res["gapfill"] = {"read_max_frac": round(max(S[f]["gapfill_frac"] for f in reads if f in S), 4),
                      "frames_over_1pct": [f for f in sorted(reads) if f in S and S[f]["gapfill_frac"] > 0.01]}
    res["clearance"] = {"eye_alt_min": round(min(s["eye_alt"] for s in stats), 3),
                        "eye_to_board_min_before_close_in": round(min(s["eye_to_board_min"] for s in stats
                                                                      if s["eye_to_board_min"] is not None
                                                                      and s["f"] < 899), 3)}
    return res, stats


if __name__ == "__main__":
    step = int(sys.argv[sys.argv.index("--step") + 1]) if "--step" in sys.argv else 1
    res, stats = run(step)
    res = compact(res)
    print(json.dumps(res, indent=1, default=str))
    if "--json" in sys.argv:
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(
            json.dumps({"summary": res, "frames": stats}, indent=1, default=str), encoding="utf-8")
