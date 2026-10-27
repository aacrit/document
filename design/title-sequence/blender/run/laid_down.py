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
not lift: their trailing edge rides 1 mm up and comes down over the same 0.25 s as the air under them escapes
(a rigid board trapping air settles no faster than paper; the spec's acceptance list puts every settle tap 0.25 s
after its stop, and the theme's landing harp sits 70 ms from a 0.1 s drop).

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
BOARD_LIFT, BOARD_SETTLE_S = 0.001, 0.25
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


def edge_crossings(s, dt=1 / 240):
    """Each sheet at rest the sliding sheet's footprint (turning as it slides) comes to lie over: (id, kind, t). kind
    "edge flick": its leading edge rides onto that sheet at t (one flick); "over at release": it already lies over it
    when it leaves the unseen hand (no flick). Sorted by time; [] for a sheet that only slides on oak."""
    out = []
    t0 = release_s(s)
    for e in SHEETS:
        if e["stop_s"] >= t0:
            continue
        rest = footprint(e, e["stop_s"])
        t = t0
        while t < s["stop_s"]:
            if _sat(footprint(s, t), rest):
                out.append((e["id"], "over at release" if t == t0 else "edge flick", t))
                break
            t += dt
    return sorted(out, key=lambda c: c[2])


def edge_flicks_s(s):
    return [t for _, kind, t in edge_crossings(s) if kind == "edge flick"]


def solved_foley_events():
    """The Foley's solved event times, in the music director's foley-events-computed.json shape (release, enter, stop,
    tap, crossings) plus the time each slide is first heard: the authority the score is guarded against."""
    out = {}
    for s in SHEETS + list(RECORDS.values()):
        k = s["id"] if s["id"] != "R" else s["record"]
        out[k] = {"heard_s": round(push_start_s(s), 3), "release_s": round(release_s(s), 3), "enter_s": s["enter_s"],
                  "stop_s": s["stop_s"], "tap_s": round(settle_tap_s(s), 3),
                  "crossings": [[u, kind, round(t, 3)] for u, kind, t in edge_crossings(s)]}
    return out


def settle_tap_s(s):
    """The settle: the lifted corner (the Atlas boards' trailing edge) lands 0.25 s after the stop."""
    return s["stop_s"] + (BOARD_SETTLE_S if is_board(s) else SETTLE_S)


def frame_state(frame, record):
    """Everything a rendered frame depends on, at the shutter's open, middle and close (180 degrees: frame -+ 0.25):
    each sheet's and the record's visibility, centre, turn, lift and lie, the camera, the flat-hold. Two frames with
    the same state render the same pixels (the scene is deterministic: a fixed seed, no animated noise)."""
    out = []
    r = RECORDS[record]
    for df in (-0.25, 0.0, 0.25):
        t = t_of(frame + df)
        for s in SHEETS + [r]:
            if not visible_at(s, t_of(frame)):          # hidden (before its release): its pose touches no pixel
                out.append((False,))
                continue
            c = centre_at(s, t)
            out.append((True, round(c[0], 7), round(c[1], 7), round(psi_at(s, t), 6),
                        round(lift_at(s, t), 7), round(lie_at(s, t), 6)))
        eye, roll = camera_at(record, frame + df)
        out.append(tuple(round(v, 7) for v in eye) + (round(roll, 6),))
    out.append(round(hold_mix(frame), 6) if visible_at(r, t_of(frame)) else 0.0)
    return tuple(out)


def render_plan(record):
    """Spec section 9, rendered once: each run of identical frames renders its first and repeats it.
    Returns {"render": the frames to render, "source_of": for every frame, the rendered frame it shows}."""
    src, prev, cur = [], None, None
    for f in range(FRAMES):
        st = frame_state(f, record)
        if st != prev:
            cur = f
        src.append(cur)
        prev = st
    return {"render": sorted(set(src)), "source_of": src}


RW = "C20-METAR-0851"                        # the shared shot is rendered as Real World's (spec: shared prefix 0-827)


def final_plan():
    """The final's renders (spec section 9): the master opens on its own black (frames 0-11, drawn, not rendered); the
    shared shot is RW's render_plan; another record re-renders only the frames whose state differs from RW's (its
    record in play, the descent onto its own pose), each run of identical frames once. Per record, every master
    frame's source: ["black", None], ["shared", the RW render], or ["tail", that record's render]."""
    b0, b1 = BEATS["black"]["frames"]
    rw = render_plan(RW)["source_of"]
    films, shared = {}, set()
    for rec in RECORDS:
        own = render_plan(rec)["source_of"]
        src, tail = [], set()
        for f in range(FRAMES):
            if b0 <= f <= b1:
                src.append(["black", None])
            elif rec == RW or frame_state(f, rec) == frame_state(f, RW):
                src.append(["shared", rw[f]])
                shared.add(rw[f])
            else:
                src.append(["tail", own[f]])
                tail.add(own[f])
        films[rec] = {"source": src, "tail": sorted(tail)}
    return {"shared": sorted(shared), "films": films}


def record_frame_cover(record, frame, record_z=0.0, nx=192, ny=108):
    """The share of the picture the record covers at a frame (the record at its pose then, the camera's eye and roll),
    as the master's ``record_frames`` counts it."""
    r = RECORDS[record]
    t = t_of(frame)
    if not visible_at(r, t):
        return 0.0
    eye, roll = camera_at(record, frame, record_z)
    h = eye[2] - record_z
    fw, fh = SENSOR_MM / LENS_MM * h / 2, SENSOR_MM / LENS_MM * h * 9 / 16 / 2
    q = math.radians(roll)
    cx, cy = centre_at(r, t)
    p = math.radians(psi_at(r, t))
    W, H = r["size_m"]
    n = 0
    for j in range(ny):
        b = -fh + (j + 0.5) / ny * 2 * fh
        for i in range(nx):
            a = -fw + (i + 0.5) / nx * 2 * fw
            x = eye[0] - P[0] + a * math.cos(q) - b * math.sin(q)
            y = eye[1] - P[1] + a * math.sin(q) + b * math.cos(q)
            u = (x - cx) * math.cos(p) + (y - cy) * math.sin(p)
            v = -(x - cx) * math.sin(p) + (y - cy) * math.cos(p)
            n += abs(u) <= W / 2 and abs(v) <= H / 2
    return n / (nx * ny)


def record_from(record, record_z=0.0):
    """The first frame the record covers half the picture (the master's record_frames start)."""
    for f in range(DESCENT[0], FRAMES):
        if record_frame_cover(record, f, record_z) >= 0.5:
            return f
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


def camera_at(record, frame, record_z=0.0):
    """The eye (table coordinates) and the frame's roll (degrees): fixed at 2.00 m (rev 2) over P until the record enters,
    then the one descent onto the record's resting pose (its window filling the frame), held from the pose frame.
    record_z: the height of the record's face where it lies on the pile (the bake's face_low_mm, its lowest point); the
    pose eye is window / 0.72 over it, so the window fills the frame with every point of the face at or above that
    height overflowing it slightly (a draped face is not flat: over its median a lower edge would show a rim)."""
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
    # window width / 0.72 exactly (the beats round it to the millimetre, which would open a hairline rim)
    to = (P[0] + cx, P[1] + cy, record_z + r["window_width_m"] * LENS_MM / SENSOR_MM)
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
