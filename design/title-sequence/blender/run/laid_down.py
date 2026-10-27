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

The lie: a sheet slides as a rigid plate on the highest point its footprint covers, and over the same 0.25 s, as the
air escapes, it lies down onto the pile point by point (as still_v5.paper lays its dealt papers: each point on what is
under it, the paper bridging a few millimetres). A pile of rigid plates each resting on the highest point beneath it
climbs to 10 mm in six sheets and floats every edge 5 to 10 mm (measured in the bake); paper does not.
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
# Rev 3: five sheets, S2 to S6 (ids kept from rev 2). The papyrus (S1) is out: the scan T-02a is not "part 1" but the
# whole recto (T-02b is its verso: their fragment outlines match mirrored, IoU 0.84 against 0.38 unmirrored), and the
# Museo Egizio record (Cat. 1879) gives the papyrus as 2820 x 410 mm, 2.38-2.82 m at true scale, over the 1.6 m limit.
SHEETS = BEATS["sheets"]
ALL_SHEETS = SHEETS
BY_ID = {s["id"]: s for s in SHEETS}
FLOORS = BEATS["checks"]
RECORDS = BEATS["records"]
for _k, _r in RECORDS.items():
    _r.setdefault("id", "R")
    _r["record"] = _k
LIFT_MAX = 0.004                         # rev 2: min(4 mm, 2 mm per m/s of the release speed)
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


def lie_at(s, t):
    """How far a paper sheet has lain down onto the pile from its rigid sliding lie (0 sliding, 1 at rest): the air
    under it escapes over the same 0.25 s as the corner's settle. The Atlas boards stay rigid (always 0)."""
    if is_board(s) or t <= s["stop_s"]:
        return 0.0
    k = (t - s["stop_s"]) / SETTLE_S
    return 1.0 if k >= 1.0 - 1e-9 else k * k


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


# ------------------------------------------------------------------------------------------------ the Foley's events
# Spec section 6: each slide starts off frame and is heard 0.1-0.3 s before it is seen; then the edge flick as the
# leading edge rides onto the sheet below, and one soft settle tap as the lifted corner comes down.

LEAD_S = 0.2                             # the unseen push begins this long before the leading edge enters the frame


def push_start_s(s):
    """When the sheet starts to move (heard): the push that brings it to its release speed, never seen."""
    return s["enter_s"] - LEAD_S


def audio_speed(s, t):
    """The sheet's speed as the Foley hears it: rising linearly under the unseen push to its release speed, then the
    slide's own linear fall to zero (speed_at)."""
    t0, tr = push_start_s(s), release_s(s)
    if t < t0:
        return 0.0
    if t < tr:
        return s["v_release_m_s"] * (t - t0) / (tr - t0)
    return speed_at(s, t)


def edge_crossing_s(s, dt=1 / 240):
    """The first instant the sliding sheet's footprint meets a sheet already at rest (the edge flick); None if it only
    ever slides on oak."""
    under = [e for e in SHEETS if e["stop_s"] < release_s(s)]
    if not under:
        return None
    rest = [footprint(e, e["stop_s"]) for e in under]
    t = release_s(s)
    while t < s["stop_s"]:
        fp = footprint(s, t)
        if any(_sat(fp, r) for r in rest):
            return t
        t += dt
    return None


def settle_tap_s(s):
    """The settle: the lifted corner lands 0.25 s after the stop; the Atlas boards' trailing edge drops in 0.1 s."""
    return s["stop_s"] + (BOARD_SETTLE_S if is_board(s) else SETTLE_S)


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
    """The eye (table coordinates) and the frame's roll (degrees): fixed at 2.00 m (rev 2) over P until the record enters,
    then the one descent onto the record's resting pose (its window filling the frame), held from the pose frame."""
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


def topmost_cover(frame, record=None, nx=1440, ny=810, sheets=None):
    """What the fixed frame shows at a frame, as fractions of its area: each sheet's visible share (the latest-laid on
    top; footprints as rectangles, Piri Reis's torn outline taken as its rectangle) and the bare oak's. The default
    raster is the spec generator's (1440 x 810). sheets: the sheets in play (default: SHEETS, S1 dropped)."""
    import numpy as np
    t = t_of(frame)
    order = [s for s in (SHEETS if sheets is None else sheets) if visible_at(s, t)]
    if record:
        r = RECORDS[record]
        if visible_at(r, t):
            order.append(r)
    fw, fh = FRAME_M[0] / 2, FRAME_M[1] / 2
    x = -fw + (np.arange(nx) + 0.5) / nx * 2 * fw
    y = -fh + (np.arange(ny) + 0.5) / ny * 2 * fh
    X, Y = np.meshgrid(x, y)
    top = np.full(X.shape, -1, np.int16)
    for k, s in enumerate(order):
        cx, cy = centre_at(s, t)
        p = math.radians(psi_at(s, t))
        u = (X - cx) * math.cos(p) + (Y - cy) * math.sin(p)
        v = -(X - cx) * math.sin(p) + (Y - cy) * math.cos(p)
        top[(np.abs(u) <= s["size_m"][0] / 2) & (np.abs(v) <= s["size_m"][1] / 2)] = k
    n = top.size
    out = {"oak": float((top == -1).sum()) / n}
    for k, s in enumerate(order):
        out[s["id"]] = float((top == k).sum()) / n
    return out


def own_area_fraction(s):
    """A sheet's own area as a fraction of the frame's."""
    return s["size_m"][0] * s["size_m"][1] / (FRAME_M[0] * FRAME_M[1])


def cover_floors(sheets=None):
    """The spec's floors (checks) at every stop frame: every earlier sheet keeps at least 8% of the frame, or, for a sheet
    under 13% of the frame, 60% of its own area; oak keeps 4% at the last stop. Returns rows of
    (stop frame, sheet, visible fraction, floor, kind, ok)."""
    sheets = SHEETS if sheets is None else sheets
    rows = []
    floor = FLOORS["min_visible_fraction_per_earlier_sheet"]
    for k, s in enumerate(sheets):
        f = s["stop_frame"]
        c = topmost_cover(f, sheets=sheets)
        for e in sheets[:k]:
            vis = c.get(e["id"], 0.0)
            own = own_area_fraction(e)
            if own < 0.13:
                rows.append((f, e["id"], vis, 0.60 * own, "60% of own area", vis >= 0.60 * own))
            else:
                rows.append((f, e["id"], vis, floor, "8% of frame", vis >= floor))
    last = sheets[-1]["stop_frame"]
    oak = topmost_cover(last, sheets=sheets)["oak"]
    rows.append((last, "oak", oak, 0.04, "4% of frame", oak >= 0.04))
    return rows


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
