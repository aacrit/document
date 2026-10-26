"""Laid Down, the series title: the beats and the closed-form slides (stdlib only; pytest, the bake and Blender import it).

Spec: design/title-sequence/blender/run/laid-down-spec.md (Fable, 2026-10-26; founder: "try Laid Down first"), with its
machine-readable beats in laid-down-beats.json beside it. The JSON is the source; this module only evaluates it.

Pile coordinates: metres from the pile centre P on the v5c table (channel_v5c.TABLE, 3.0 x 1.7 m), +x to the frame's
right (along the table's length), +y to the frame's top (toward the back wall), z up from the bare oak top. psi is a
sheet's long side (its image's width, local u) from +x, in degrees.

The slide (spec section 4): a rigid plate released off the frame slides to rest under Coulomb friction, a = mu_eff g.
With tau the time left to the stop, the distance left is a tau^2 / 2 and the speed a tau, so v falls linearly to zero
and nothing eases after the stop. The turn shares the quadratic: psi = psi_land - delta (tau / t_visible)^2, so the spin
and the translation stop at the same instant (Farkas, Bartels, Unger and Wolf 2003) and psi is psi_land - delta at entry.

The trailing corner (spec section 4, read as the air film it describes): lifted min(3 mm, 2 mm per m/s of the release
speed) while the sheet slides on the air it drags, then down to its resting lie over 0.25 s after the stop, falling (a
quadratic in time, so it lands with speed: the settle tap). The spec's literal "2 mm x v" would be zero at the stop and
leave nothing to settle; the release speed (1.6 to 1.9 m/s) puts every paper sheet at the 3 mm cap. The Atlas boards do
not lift: their trailing edge rides 1 mm up and drops in 0.1 s.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
BEATS = json.loads((HERE / "laid-down-beats.json").read_text(encoding="utf-8"))

G = 9.81
FPS_NUM, FPS_DEN = 30000, 1001
FPS = FPS_NUM / FPS_DEN
FRAMES = BEATS["frames"]
TABLE = {"size": tuple(BEATS["table"]["size_m"])}
P = tuple(BEATS["table"]["pile_centre_m"])
CAM = BEATS["camera"]
LENS_MM, SENSOR_MM = CAM["lens_mm"], CAM["sensor_mm"]
EYE_Z = CAM["fixed"]["eye_m"][2]
FRAME_M = (SENSOR_MM / LENS_MM * EYE_Z, SENSOR_MM / LENS_MM * EYE_Z * 9 / 16)
SHEETS = BEATS["sheets"]
BY_ID = {s["id"]: s for s in SHEETS}
RECORDS = BEATS["records"]
for _k, _r in RECORDS.items():
    _r.setdefault("id", "R")
    _r["record"] = _k
LIFT_MAX = 0.003
LIFT_PER_V = 0.002                       # m per m/s
SETTLE_S = 0.25
BOARD_LIFT, BOARD_SETTLE_S = 0.001, 0.1
DESCENT = tuple(CAM["descent"]["frames"])


def t_of(frame: float) -> float:
    return frame * FPS_DEN / FPS_NUM


def frame_of(t: float) -> float:
    return t * FPS_NUM / FPS_DEN


def decel(s) -> float:
    return s["mu_eff"] * G


def t_release_to_stop(s) -> float:
    return s["v_release_m_s"] / decel(s)


def release_s(s) -> float:
    return s["stop_s"] - t_release_to_stop(s)


def _dir(s):
    (x0, y0), (x1, y1) = s["release_centre_m"], s["land_centre_m"]
    d = math.hypot(x1 - x0, y1 - y0)
    return (x1 - x0) / d, (y1 - y0) / d


def _tau(s, t):
    """Time left to the stop, clamped to the slide (0 after the stop, the full slide before the release)."""
    return min(max(s["stop_s"] - t, 0.0), t_release_to_stop(s))


def centre_at(s, t):
    tau = _tau(s, t)
    if tau == 0.0:
        return tuple(s["land_centre_m"])
    left = 0.5 * decel(s) * tau * tau
    dx, dy = _dir(s)
    return (s["land_centre_m"][0] - dx * left, s["land_centre_m"][1] - dy * left)


def speed_at(s, t):
    if t < release_s(s):
        return 0.0
    return decel(s) * _tau(s, t)


def psi_at(s, t):
    tau = _tau(s, t)
    if tau == 0.0:
        return s["land_psi_deg"]
    return s["land_psi_deg"] - s["turn_delta_deg"] * (tau / s["t_visible_s"]) ** 2


def is_board(s) -> bool:
    return s.get("id") == "S2"


def lift_at(s, t):
    """The trailing corner's lift (m) over the sheet's resting lie (the Atlas boards: the trailing edge's)."""
    if t < release_s(s):
        return 0.0
    held, settle = (BOARD_LIFT, BOARD_SETTLE_S) if is_board(s) else \
        (min(LIFT_MAX, LIFT_PER_V * s["v_release_m_s"]), SETTLE_S)
    if t <= s["stop_s"]:
        return held
    k = (t - s["stop_s"]) / settle
    return 0.0 if k >= 1.0 - 1e-9 else held * (1.0 - k * k)


def visible_at(s, t) -> bool:
    """A sheet exists from its release (the push before it is never seen, and never placed)."""
    return t >= release_s(s) - 0.5 / FPS


def corners(cx, cy, W, H, psi_deg):
    p = math.radians(psi_deg)
    c, n = math.cos(p), math.sin(p)
    return [(cx + u * c - v * n, cy + u * n + v * c) for u, v in ((-W / 2, -H / 2), (W / 2, -H / 2), (W / 2, H / 2),
                                                                   (-W / 2, H / 2))]


def footprint(s, t):
    x, y = centre_at(s, t)
    W, H = s["size_m"]
    return corners(x, y, W, H, psi_at(s, t))


def frame_poly():
    fw, fh = FRAME_M[0] / 2, FRAME_M[1] / 2
    return [(-fw, -fh), (fw, -fh), (fw, fh), (-fw, fh)]


def _sat(a, b) -> bool:
    for poly in (a, b):
        for i in range(len(poly)):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % len(poly)]
            ax, ay = y2 - y1, x1 - x2
            pa = [ax * x + ay * y for x, y in a]
            pb = [ax * x + ay * y for x, y in b]
            if max(pa) <= min(pb) or max(pb) <= min(pa):
                return False
    return True


def poly_hits_frame(poly) -> bool:
    return _sat(poly, frame_poly())


def first_frame_in_frame(s):
    """The first frame whose time puts any of the sheet's footprint inside the frame (its leading edge entering)."""
    f = int(math.floor(frame_of(release_s(s))))
    while f < FRAMES:
        if poly_hits_frame(footprint(s, t_of(f))):
            return f
        f += 1
    return None


def hold_mix(frame):
    fh = RECORDS[next(iter(RECORDS))]["flat_hold"]
    a, b = fh["ramp_from_frame"], fh["one_from_frame"]
    if frame <= a:
        return 0.0
    if frame >= b:
        return 1.0
    return (frame - a) / (b - a)


def _smooth(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * t * (t * (6 * t - 15) + 10)         # shot_v5c._smooth, as the spec names it


def camera_at(record, frame):
    """The eye (table coordinates) and the frame's roll (degrees): fixed at 1.30 m over P until the record enters,
    then the one descent onto the record's resting pose (its window filling the frame), held from 1019."""
    r = RECORDS[record]
    fixed = (P[0], P[1], EYE_Z)
    f0, f1 = DESCENT
    if frame <= f0:
        return fixed, 0.0
    k = _smooth((frame - f0) / (f1 - f0))
    W, H = r["size_m"]
    u0, v0, u1, v1 = r["record_window"]
    # the window's centre in the record's own frame (rows from its top, +v), turned to its resting psi
    wu, wv = (u0 + u1) / 2 * W - W / 2, H / 2 - (v0 + v1) / 2 * H
    p = math.radians(r["land_psi_deg"])
    cx = r["land_centre_m"][0] + wu * math.cos(p) - wv * math.sin(p)
    cy = r["land_centre_m"][1] + wu * math.sin(p) + wv * math.cos(p)
    to = (P[0] + cx, P[1] + cy, r["pose_eye_height_m"])
    eye = tuple(a + (b - a) * k for a, b in zip(fixed, to))
    return eye, r["land_psi_deg"] * k


# ------------------------------------------------------------------------------------------------ what the frame shows


def topmost_cover(frame, record=None, nx=192, ny=108):
    """What the fixed frame shows at a frame, as fractions of its area: each sheet's visible share (the latest-laid on
    top; footprints as rectangles, Piri Reis's torn outline taken as its rectangle) and the bare oak's."""
    t = t_of(frame)
    order = [s for s in SHEETS if visible_at(s, t)]
    if record:
        r = RECORDS[record]
        if visible_at(r, t):
            order.append(r)
    fw, fh = FRAME_M[0] / 2, FRAME_M[1] / 2
    count = {s["id"]: 0 for s in order}
    count["oak"] = 0
    poses = [(s, centre_at(s, t), math.radians(psi_at(s, t))) for s in order]
    for j in range(ny):
        y = -fh + (j + 0.5) / ny * 2 * fh
        for i in range(nx):
            x = -fw + (i + 0.5) / nx * 2 * fw
            top = "oak"
            for s, (cx, cy), p in poses:
                dx, dy = x - cx, y - cy
                u = dx * math.cos(p) + dy * math.sin(p)
                v = -dx * math.sin(p) + dy * math.cos(p)
                if abs(u) <= s["size_m"][0] / 2 and abs(v) <= s["size_m"][1] / 2:
                    top = s["id"]
            count[top] += 1
    n = nx * ny
    return {k: v / n for k, v in count.items()}


def solved_table():
    """The evidence table the spec asks for: per sheet and record, entry point, v_entry, t_visible, delta, stop frame."""
    rows = []
    for s in SHEETS + list(RECORDS.values()):
        rows.append({"id": s["id"] if s["id"] != "R" else f"R {s['record']}", "release_frame": round(frame_of(release_s(s)), 2),
                     "release_centre_m": [round(c, 4) for c in centre_at(s, release_s(s))],
                     "first_frame_in_frame": first_frame_in_frame(s), "v_entry_m_s": s["v_entry_m_s"],
                     "t_visible_s": s["t_visible_s"], "turn_delta_deg": s["turn_delta_deg"],
                     "stop_frame": s["stop_frame"], "stop_frame_exact": round(frame_of(s["stop_s"]), 2)})
    return rows
