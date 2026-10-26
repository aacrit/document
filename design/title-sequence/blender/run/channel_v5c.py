"""The Run v5c: a carved channel across a collector's table (numpy only; pure functions, no I/O).

Spec: Agentique reports/briefs/document-title-v5-fable-plan.md (founder approved all eight recommendations, 2026-10-25).
This module is the single source of the geometry the plan image, the MuJoCo heightfield and the Blender scene all read.

Table frame: metres, origin at the top's near-left corner (the launch corner), x along the 3.0 m length, y away from
the camera side (y = 0 is the near long edge), z up from the oak top (z = 0).

Where the build departs from the plan's numbers (each forced by the plan's own geometry; see PLAN_NOTES):
- the run is 7.99 m, not 10.3 m: three reaches on a 3.0 m top with 0.365 m turns cannot be 2.7 m each;
- the fall is not "45 mm inside the slab": a 16 mm marble at the floor of a groove deeper than about 18 mm is hidden
  from the follow camera. The launch energy comes from a carved oak release block (riser) at the launch corner, and the
  groove floor goes from 8 mm to at most 18 mm below the top over the whole run;
- the reaches are 0.7305 m apart (turn radius 0.36525 m) so the Admiralty chart's 0.675 m width fits between grooves;
- the felt well's floor follows the groove's end depth (the 3 mm lip is kept), so the well is deeper than 6 mm.
"""

from __future__ import annotations

import math

import numpy as np

G = 9.81
R = 0.008                                  # the clay marble, 16 mm (plan section 8)
RHO_CLAY = 1900.0
MASS = RHO_CLAY * 4.0 / 3.0 * math.pi * R ** 3
K_ROLL = 5.0 / 7.0                         # a solid sphere rolling: a = (5/7) g (sin(theta) - Crr)

TABLE = {"size": (3.0, 1.7), "top": 0.070, "height": 0.76, "boards": 7, "trestle_inset": 0.32}
CELL = 0.0015                              # the heightfield's cell (plan section 7)

# ------------------------------------------------------------------------------------------------ the channel's plan

REACH_Y = (0.120, 0.8505, 1.581)           # on heightfield grid lines (0.0015 m): 80, 567 and 1054 cells
R_TURN = (REACH_Y[1] - REACH_Y[0]) / 2     # 0.36525 m
TURN_EDGE = 0.30                           # the turns' outer edge stays 0.30 m from each short edge (plan section 2)
TURN1_C = (TABLE["size"][0] - TURN_EDGE - R_TURN, (REACH_Y[0] + REACH_Y[1]) / 2)
TURN2_C = (TURN_EDGE + R_TURN, (REACH_Y[1] + REACH_Y[2]) / 2)
X_START = 0.080                            # the marble's start, held by the latch disc on the release block
WELL = {"x": (2.430, 2.950), "y": (1.250, 1.670), "felt_t": 0.003, "lip": 0.003}
LIP_X = WELL["x"][0]

SEGMENTS = [
    {"kind": "line", "name": "reach 1", "p0": (X_START, REACH_Y[0]), "p1": (TURN1_C[0], REACH_Y[0])},
    {"kind": "arc", "name": "turn 1", "c": TURN1_C, "a0": -math.pi / 2, "a1": math.pi / 2},     # left turn (ccw)
    {"kind": "line", "name": "reach 2", "p0": (TURN1_C[0], REACH_Y[1]), "p1": (TURN2_C[0], REACH_Y[1])},
    {"kind": "arc", "name": "turn 2", "c": TURN2_C, "a0": -math.pi / 2, "a1": -3 * math.pi / 2},  # right turn (cw)
    {"kind": "line", "name": "reach 3", "p0": (TURN2_C[0], REACH_Y[2]), "p1": (LIP_X, REACH_Y[2])},
]


def _seg_len(sg):
    if sg["kind"] == "line":
        return math.dist(sg["p0"], sg["p1"])
    return abs(sg["a1"] - sg["a0"]) * R_TURN


_S0 = []
_acc = 0.0
for _sg in SEGMENTS:
    _S0.append(_acc)
    _sg["s0"] = _acc
    _sg["len"] = _seg_len(_sg)
    _acc += _sg["len"]
LENGTH = _acc


def seg_at(s):
    for sg in SEGMENTS:
        if s <= sg["s0"] + sg["len"] + 1e-12:
            return sg
    return SEGMENTS[-1]


def point(s):
    """The centreline at arc length s: (x, y, heading radians)."""
    sg = seg_at(min(max(s, 0.0), LENGTH))
    t = s - sg["s0"]
    if sg["kind"] == "line":
        (x0, y0), (x1, y1) = sg["p0"], sg["p1"]
        h = math.atan2(y1 - y0, x1 - x0)
        return x0 + t * math.cos(h), y0 + t * math.sin(h), h
    sgn = 1.0 if sg["a1"] > sg["a0"] else -1.0
    a = sg["a0"] + sgn * t / R_TURN
    cx, cy = sg["c"]
    return cx + R_TURN * math.cos(a), cy + R_TURN * math.sin(a), a + sgn * math.pi / 2


def project(X, Y):
    """Every point's nearest centreline station: (s, u, seg index). u is the signed offset to the LEFT of the heading;
    points whose projection falls outside every segment get u = inf (a small spherical cup end at s < 0 is handled by
    the caller through s)."""
    X = np.asarray(X, float)
    Y = np.asarray(Y, float)
    best_u = np.full(X.shape, np.inf)
    best_s = np.zeros(X.shape)
    best_k = np.full(X.shape, -1, int)
    for k, sg in enumerate(SEGMENTS):
        if sg["kind"] == "line":
            (x0, y0), (x1, y1) = sg["p0"], sg["p1"]
            L = sg["len"]
            dx, dy = (x1 - x0) / L, (y1 - y0) / L
            t = (X - x0) * dx + (Y - y0) * dy
            u = -(X - x0) * dy + (Y - y0) * dx
            lo = -0.02 if k == 0 else 0.0                   # the cup's round end behind the start
            ok = (t >= lo) & (t <= L)
            s = sg["s0"] + t
        else:
            cx, cy = sg["c"]
            dxx, dyy = X - cx, Y - cy
            r = np.hypot(dxx, dyy)
            a = np.arctan2(dyy, dxx)
            sgn = 1.0 if sg["a1"] > sg["a0"] else -1.0
            # angle travelled from a0 in the direction of travel, wrapped to [0, 2 pi)
            da = np.mod(sgn * (a - sg["a0"]), 2 * math.pi)
            ok = da <= abs(sg["a1"] - sg["a0"]) + 1e-12
            s = sg["s0"] + da * R_TURN
            u = (R_TURN - r) if sgn > 0 else (r - R_TURN)    # left of heading: toward the centre on a left turn
        better = ok & (np.abs(u) < np.abs(best_u))
        best_u = np.where(better, u, best_u)
        best_s = np.where(better, s, best_s)
        best_k = np.where(better, k, best_k)
    return best_s, best_u, best_k


# ------------------------------------------------------------------------------------------------ the fall (slope schedule)

# The release block: the marble rests against the latch's bronze disc on a 3 degree cup floor; released, it runs down a
# 25 degree ramp cut in the block (smoothly in and out, so it never meets a kink) to the groove floor 8 mm under the top.
LAUNCH = {"cup_deg": 3.0, "cup_len": 0.012, "rise": 0.010, "deg": 25.0, "hold": 0.0, "fall": 0.025}
FLOOR_START = -0.008                       # the groove floor at the foot of the ramp: a cove 8 mm deep (plan section 2)
DEPTH_MAX = 0.021                          # deepest floor under the top: the marble crown 5 mm under it at the lip
COVE_R = 0.013                             # core-box radius in the straights (24-26 mm groove; plan section 7: 13 mm)
COVE_R_TURN = 0.016                        # the turns widen to 32 mm
BANK_TAN = 0.19                            # the turns' bank: inside edge about 3 mm lower over the 16 mm half width
BLEND = 0.06                               # half length of the straight-to-bank transitions at each turn's ends

# reach slopes (degrees) and the two carved steps (3 mm each, at most 15 degrees: plan section 2)
SLOPE_DEG = {"reach 1": 0.046, "turn 1": 0.060, "reach 2": 0.046, "turn 2": 0.060, "reach 3": 0.046}
STEP_DEG, STEP_DROP = 15.0, 0.003


def _x_to_s(reach, x):
    sg = [g for g in SEGMENTS if g["name"] == reach][0]
    return sg["s0"] + abs(x - sg["p0"][0])


# the steps: one on reach 2 beside the Gutenberg leaf, one on reach 3 beside the Admiralty chart (plan section 2)
STEPS = [{"name": "step 1 (the leaf)", "s": _x_to_s("reach 2", 1.36)},
         {"name": "step 2 (the chart)", "s": _x_to_s("reach 3", 1.93)}]

# Leather let flush into the floor: the friction zones, each beside the artifact the marble is passing (plan section 2)
LEATHER = [
    {"name": "L1 tablet", "reach": "reach 1", "x": (0.30, 0.48)},
    {"name": "L2 papyrus", "reach": "reach 1", "x": (0.74, 0.92)},
    {"name": "L3 Atlas", "reach": "reach 1", "x": (1.78, 1.96)},
    {"name": "L4 galley", "reach": "reach 2", "x": (1.50, 1.72)},
    {"name": "L5 Piri Reis", "reach": "reach 2", "x": (0.97, 1.19)},
    {"name": "L6 Piri's roll", "reach": "reach 3", "x": (1.05, 1.30)},
    {"name": "L7 Ino", "reach": "reach 3", "x": (1.55, 1.80)},
    {"name": "L8 before the felt", "reach": "reach 3", "x": (2.03, 2.43)},
]
for _l in LEATHER:
    a, b = (_x_to_s(_l["reach"], x) for x in _l["x"])
    _l["s"] = (min(a, b), max(a, b))
LEATHER_HALF_W = 0.006                     # visible leather across the cove floor (the marble rides its centre)
LEATHER_T = 0.002
LEATHER_BELOW = 0.00005                    # a hair below the oak: the marble rolls down onto it (plan section 2)

# rolling resistance (Crr = rolling length / R), the physics knobs (MuJoCo condim 6 rolling friction = Crr * R)
CRR = {"oak": 0.0008, "leather": 0.0045, "felt": 0.060}
# measured (sim_v5c against this clock, 2026-10-25): MuJoCo's soft contacts on the facets cost about this much more
# rolling resistance than the ideal law; the design clock adds it so the design and the proof agree
SIM_EXTRA_CRR = 0.00055


def _smooth(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


def launch_len():
    L = LAUNCH
    return L["cup_len"] + L["rise"] + L["hold"] + L["fall"]


def slope_deg(s):
    """The floor's downward slope (degrees) at arc length s (vectorised)."""
    s = np.asarray(s, float)
    L = LAUNCH
    th = np.zeros(s.shape)
    for sg in SEGMENTS:
        m = (s >= sg["s0"]) & (s <= sg["s0"] + sg["len"])
        th = np.where(m, SLOPE_DEG[sg["name"]], th)
    th = np.where(s > LENGTH, SLOPE_DEG["reach 3"], th)
    # the launch: cup, rise to 25 degrees, hold, ease down to the reach's slope
    a = L["cup_len"]
    b = a + L["rise"]
    c = b + L["hold"]
    d = c + L["fall"]
    r1 = SLOPE_DEG["reach 1"]
    th = np.where(s < a, L["cup_deg"], th)
    th = np.where((s >= a) & (s < b), L["cup_deg"] + (L["deg"] - L["cup_deg"]) * _smooth((s - a) / L["rise"]), th)
    th = np.where((s >= b) & (s < c), L["deg"], th)
    th = np.where((s >= c) & (s < d), r1 + (L["deg"] - r1) * (1 - _smooth((s - c) / L["fall"])), th)
    # the steps: a smooth rise to the step angle and back, sized to drop exactly STEP_DROP
    for st in STEPS:
        e = 0.005                                       # ease in and out over 5 mm
        hold = max(0.0, (STEP_DROP - 2 * e * 0.5 * math.tan(math.radians(STEP_DEG))) / math.tan(math.radians(STEP_DEG)))
        s0 = st["s"] - (hold / 2 + e)
        u = s - s0
        bump = np.where((u >= 0) & (u < e), _smooth(u / e), 0.0)
        bump = np.where((u >= e) & (u < e + hold), 1.0, bump)
        bump = np.where((u >= e + hold) & (u < 2 * e + hold), 1 - _smooth((u - e - hold) / e), bump)
        th = np.maximum(th, bump * STEP_DEG)
    return th


_DS = 0.00025
BLOCK: dict = {}


def rebuild():
    """Integrate the slope schedule into the floor table (call again after changing a knob)."""
    global _SS, _ZF, LAUNCH_DROP, BLOCK_H
    _SS = np.arange(-0.02, LENGTH + 0.6 + _DS, _DS)
    tan = np.tan(np.radians(slope_deg(np.clip(_SS, 0, None))))
    tan[_SS < 0] = 0.0
    drop = np.concatenate([[0.0], np.cumsum(0.5 * (tan[1:] + tan[:-1]) * _DS)])
    i0 = int(np.searchsorted(_SS, 0.0))
    LAUNCH_DROP = float(drop[int(np.searchsorted(_SS, launch_len()))] - drop[i0])
    BLOCK_H = LAUNCH_DROP + FLOOR_START + 0.008      # the release block's top: its cove is 8 mm deep at the cup
    _ZF = (BLOCK_H - 0.008) - (drop - drop[i0])
    BLOCK.update({"x": (X_START - 0.030, X_START + launch_len() - 0.010),
                  "y": (REACH_Y[0] - 0.035, REACH_Y[0] + 0.035), "h": BLOCK_H})


rebuild()


def floor_z(s):
    """The groove floor's height (m, top = 0) at arc length s, along the centreline (vectorised)."""
    return np.interp(np.asarray(s, float), _SS, _ZF)


def end_depth():
    return float(-floor_z(LENGTH))


def felt_top():
    return -end_depth() - WELL["lip"]


def _turn_weight(s):
    """0 in the straights, 1 inside a turn, smoothly blended over +-BLEND around each junction."""
    s = np.asarray(s, float)
    w = np.zeros(s.shape)
    for sg in SEGMENTS:
        if sg["kind"] != "arc":
            continue
        a, b = sg["s0"], sg["s0"] + sg["len"]
        w = np.maximum(w, _smooth((s - (a - BLEND)) / (2 * BLEND)) * (1 - _smooth((s - (b - BLEND)) / (2 * BLEND))))
    return w


def _outward_sign(k):
    """+1 if the left of the heading is outward on segment k (a right turn), -1 on a left turn, 0 on a line."""
    k = np.asarray(k)
    out = np.zeros(k.shape)
    for i, sg in enumerate(SEGMENTS):
        if sg["kind"] == "arc":
            out = np.where(k == i, -1.0 if sg["a1"] > sg["a0"] else 1.0, out)
    return out


def _bank_sign_at(s):
    s = np.asarray(s, float)
    out = np.zeros(s.shape)
    for sg in SEGMENTS:
        if sg["kind"] == "arc":
            near = (s > sg["s0"] - 2 * BLEND) & (s < sg["s0"] + sg["len"] + 2 * BLEND)
            out = np.where(near, -1.0 if sg["a1"] > sg["a0"] else 1.0, out)
    return out


def groove_z(s, u):
    """The carved surface at (s, u), or +inf where the cutter never reached (the top stands). The cove: a round bottom
    of radius Rc, vertical walls above z_f + Rc (a core-box bit plunged deeper than its radius), tilted by the bank in
    the turns (outward up)."""
    s = np.asarray(s, float)
    u = np.asarray(u, float)
    w = _turn_weight(s)
    rc = COVE_R + (COVE_R_TURN - COVE_R) * w
    tb = BANK_TAN * w * _bank_sign_at(s)                # times u: positive u (left) is outward on a right turn
    # the cup's round end behind the start: the distance from the start point
    ue = np.where(s < 0, np.hypot(u, s), u)
    inside = np.abs(ue) < rc
    c = rc - np.sqrt(np.clip(rc * rc - ue * ue, 0, None))
    z = floor_z(np.clip(s, 0, None)) + c + tb * ue
    return np.where(inside & (s <= LENGTH + 1e-9), z, np.inf)


def top_z(X, Y):
    """The uncut top: 0, or the release block's top over its footprint, or the well's floor (under the felt)."""
    X = np.asarray(X, float)
    Y = np.asarray(Y, float)
    z = np.zeros(np.broadcast(X, Y).shape)
    bx, by = BLOCK["x"], BLOCK["y"]
    z = np.where((X >= bx[0]) & (X <= bx[1]) & (Y >= by[0]) & (Y <= by[1]), BLOCK["h"], z)
    wx, wy = WELL["x"], WELL["y"]
    z = np.where((X >= wx[0]) & (X <= wx[1]) & (Y >= wy[0]) & (Y <= wy[1]), felt_top() - WELL["felt_t"], z)
    return z


def height(X, Y):
    """The carved top (m) at table points: the physics heightfield and the render mesh both sample this."""
    s, u, k = project(X, Y)
    gz = groove_z(s, np.where(np.isfinite(u), u, 1.0))
    return np.minimum(top_z(X, Y), gz)


def on_leather(s, u=None):
    s = np.asarray(s, float)
    m = np.zeros(s.shape, bool)
    for lz in LEATHER:
        m |= (s >= lz["s"][0]) & (s <= lz["s"][1])
    if u is not None:
        m &= np.abs(np.asarray(u, float)) <= LEATHER_HALF_W
    return m


def groove_half_width(s):
    """Where the cut meets the top (or block), for keep-out checks."""
    s = np.asarray(s, float)
    us = np.linspace(-0.03, 0.03, 601)
    out = []
    for si in np.atleast_1d(s):
        z = groove_z(np.full(us.shape, si), us)
        topz = BLOCK["h"] if si < launch_len() - 0.01 else 0.0
        cut = us[z < topz - 1e-9]
        out.append(float(np.max(np.abs(cut))) if cut.size else 0.0)
    return np.array(out)


# ------------------------------------------------------------------------------------------------ 1D model (design tuning)


def crr_at(s):
    s = np.asarray(s, float)
    return np.where(on_leather(s), CRR["leather"], np.where(s > LENGTH, CRR["felt"], CRR["oak"]))


def roll_1d(dt=0.0005, t_max=60.0, crr=None, extra=None):
    """A rolling sphere along the centreline under the slope schedule and the rolling resistance: the design's clock.
    Ignores the bank's climb and contact losses (the MuJoCo run is the truth). Returns times, s, v and the rest."""
    crr = dict(crr or CRR)
    extra = SIM_EXTRA_CRR if extra is None else extra
    crr["oak"] += extra
    crr["leather"] += extra
    s, v, t = 0.0, 0.0, 0.0
    ts, ss, vs = [0.0], [0.0], [0.0]
    lip_done = False
    grid = np.arange(0.0, LENGTH + 0.5, _DS)
    sin_t = np.sin(np.radians(slope_deg(grid))).tolist()
    c_t = np.where(on_leather(grid), crr["leather"], crr["oak"]).tolist()
    n = len(grid) - 1
    while t < t_max:
        i = min(int(s / _DS), n)
        c = crr["felt"] if s > LENGTH else c_t[i]
        a = K_ROLL * G * ((0.0 if s > LENGTH else sin_t[i]) - (c if v > 1e-6 else 0.0))
        if v <= 1e-6 and a <= K_ROLL * G * c:
            break                                   # static: the slope cannot overcome rolling resistance
        if s > LENGTH and not lip_done:
            v = math.sqrt(v * v + 2 * K_ROLL * G * WELL["lip"])
            lip_done = True
        if v <= 1e-6 and a <= 0:
            break
        v = max(0.0, v + a * dt)
        s += v * dt
        t += dt
        if len(ts) == 0 or t - ts[-1] >= 0.02:
            ts.append(t)
            ss.append(s)
            vs.append(v)
    return {"t": np.array(ts), "s": np.array(ss), "v": np.array(vs), "t_rest": t, "s_rest": s}


# ------------------------------------------------------------------------------------------------ the artifacts

# Each: footprint rectangle (x0, x1, y0, y1), height, what it lies on, the record's date where it is one. Real sizes.
ITEMS = {
    "block": {"kind": "carving", "rect": (*BLOCK["x"], *BLOCK["y"]), "h": BLOCK_H, "on": "oak",
              "why": "the release block glued to the top at the launch corner: the cup, the latch disc, the 25 degree ramp"},
    "tablet": {"kind": "record", "beside": "reach 1", "ledger": "T-01", "date": -2040, "rect": (0.065, 0.375, 0.2575, 0.5625), "h": 0.050,
               "on": "oak", "why": "the Umma tablet at the launch corner, square to the edge, 0.14 m from the groove"},
    "papyrus": {"kind": "record", "beside": "reach 1", "ledger": "T-02a", "date": -1153, "rect": (0.50, 1.10, 0.232, 0.3405),
                "h": 0.00025, "on": "oak", "why": "the Turin papyrus along reach 1, 0.10 m off the groove"},
    "coin dupondius": {"kind": "object", "scan": "FS-coin-dupondius-octavian", "dia": 0.029, "at": (0.525, 0.286),
                       "on": "papyrus", "why": "a Roman coin weighting the papyrus's left end"},
    "coin sestertius": {"kind": "object", "scan": "FS-coin-sesterce-trajan", "dia": 0.034, "at": (1.072, 0.287),
                        "on": "papyrus", "why": "the sestertius weighting its right end"},
    "leaf": {"kind": "record", "beside": "reach 2", "ledger": "T-06", "date": 1455, "rect": (1.20, 1.50, 0.392, 0.812), "h": 0.00015,
             "on": "oak", "why": "the Gutenberg leaf beside reach 2's first step"},
    "galley": {"kind": "tool", "rect": (1.525, 1.615, 0.52, 0.765), "h": 0.012, "on": "oak",
               "why": "the brass galley of blank sorts set down beside the leaf"},
    "folder": {"kind": "object", "rect": (1.665, 2.365, 0.225, 0.745), "h": 0.012, "on": "oak",
               "why": "the Atlas's folder, closed, the second board inside it: a thickness, not a picture"},
    "atlas": {"kind": "record", "beside": "reach 1", "ledger": "T-03", "date": 1375, "rect": (1.672, 2.360, 0.235, 0.735), "h": 0.0012,
              "on": "folder", "why": "one board of the Catalan Atlas on its folder at the end of reach 1; the marble "
                                    "banks past its corners in turn 1"},
    "globe": {"kind": "object", "scan": "globe", "at": (0.140, 1.2158), "rect": (0.02, 0.26, 1.0958, 1.3358), "h": 0.45,
              "on": "oak", "why": "the Doppelmayr globe on its stand in the far-left margin at turn 2"},
    "piri": {"kind": "record", "beside": "reach 2", "ledger": "T-04", "date": 1513, "rect": (0.73, 1.38, 0.905, 1.455), "h": 0.0003,
             "on": "oak", "roll": {"axis": "x", "at": 1.455, "r": 0.011}, "open": 0.55,
             "why": "Piri Reis unrolled 0.55 m, its open edge to reach 2, the rest rolled at the far side"},
    "weights": {"kind": "object", "scan": "weights", "at": (0.800, 1.400), "dia": 0.07, "h": 0.045, "on": "piri",
                "upright_rx_deg": -90.0, "why": "the nested weights holding Piri Reis open by its roll"},
    "ino": {"kind": "record", "beside": "reach 3", "ledger": "T-08", "date": 1821, "rect": (1.455, 1.905, 0.926, 1.505), "h": 0.00008,
            "on": "oak", "roll": {"axis": "y", "at": 1.905, "r": 0.014}, "open": 0.45,
            "why": "Ino's sheet unrolled 0.45 m beside reach 3, the rest rolled at its right"},
    "admiralty": {"kind": "record", "beside": "reach 3", "ledger": "T-20", "date": 1931, "rect": (1.965, 2.365, 0.878, 1.553),
                  "h": 0.00012, "on": "oak", "roll": {"axis": "y", "at": 2.365, "r": 0.016}, "open": 0.40,
                  "why": "Admiralty chart 983 open by reach 3's step, the rest rolled at its right"},
    "jeton": {"kind": "object", "scan": "jeton", "dia": 0.028, "at": (2.000, 1.515), "on": "admiralty",
              "why": "the Krakow jeton on the chart's open corner (the plan's brass disc has no gated scan)"},
    "felt": {"kind": "surface", "rect": (*WELL["x"], *WELL["y"]), "h": WELL["felt_t"], "on": "well",
             "why": "the felt well at the far corner of reach 3: the marble stops here"},
    "record": {"kind": "record", "ledger": "R-C20-METAR-0851", "date": 2001, "rect": (2.690, 2.890, 1.345, 1.4575),
               "h": 0.00012, "on": "felt", "why": "the film's record on the felt, 0.26 m from the lip"},
}
# the stick chart is 0.80 x 0.74 m: it fits no band between grooves, so it hangs on the wall behind the far edge
WALL_Y = TABLE["size"][1] + 0.45
WALL_ITEMS = {"stick": {"ledger": "T-19", "x": (1.10, 1.90), "z": (0.30, 1.04), "size": (0.80, 0.7424)}}

PLANNED_OVERLAPS = {("coin dupondius", "papyrus"), ("coin sestertius", "papyrus"), ("atlas", "folder"),
                    ("weights", "piri"), ("jeton", "admiralty"), ("felt", "record")}


def rect_of(name):
    it = ITEMS[name]
    if "rect" in it:
        return it["rect"]
    x, y = it["at"]
    r = it["dia"] / 2
    return (x - r, x + r, y - r, y + r)


# ------------------------------------------------------------------------------------------------ the lamp and the camera

# One wall-arm lamp off the far long side (plan section 5), its 0.26 m shade 1.40 m over the top, aimed across the table
LAMP = {"pos": (1.55, 2.02, 1.40), "aim": (1.50, 0.45, 0.0), "shade_d": 0.26, "power_w": 150.0, "kelvin": 3400.0,
        "spread_deg": 120.0, "white_balance_k": 4300.0}
ROOM = {"wall_y": WALL_Y, "ceiling_z": 3.0 - TABLE["height"], "side_x": (-3.2, 4.8), "near_y": -3.4,
        "plaster_albedo": 0.42, "floor_albedo": 0.06}

LENS_MM, SENSOR_W = 50.0, 36.0
SENSOR_H = SENSOR_W * 9 / 16
FOLLOW = {"D": 0.45, "elev": 26.0, "az_from_heading": 155.0, "fstop": 4.0, "omega": 3.2, "lead_ahead": 0.09}
CLOSE = {"D": 0.16, "elev": 16.0, "fstop": 2.8}
OPEN = {"height": 1.60, "descend_s": 3.0, "fstop": 8.0}
T_RELEASE = 0.0                             # title seconds: the shot opens as the marble is let go (no scripted latch)
RUNTIME = {"open": 3.0, "arrive": 5.0, "target": 36.0, "min": 34.0, "max": 40.0}


def lamp_falloff_stops(x, y, ref=None):
    """Irradiance at (x, y) against the record's centre, in stops (inverse square and cosine to the top)."""
    ref = ref or ((ITEMS["record"]["rect"][0] + ITEMS["record"]["rect"][1]) / 2,
                  (ITEMS["record"]["rect"][2] + ITEMS["record"]["rect"][3]) / 2)
    lx, ly, lz = LAMP["pos"]

    def e(px, py):
        d2 = (lx - px) ** 2 + (ly - py) ** 2 + lz ** 2
        return lz / math.sqrt(d2) / d2

    return math.log2(e(x, y) / e(*ref))


def project_px(eye, target, pts, width=1920):
    """Pinhole projection of table points into a 16:9 frame from eye looking at target (up = +z)."""
    eye, target = np.asarray(eye, float), np.asarray(target, float)
    f = target - eye
    f /= np.linalg.norm(f)
    r = np.cross(f, [0, 0, 1.0])
    r /= np.linalg.norm(r)
    up = np.cross(r, f)
    P = np.asarray(pts, float) - eye
    zc = P @ f
    xs = (P @ r) / zc * LENS_MM / SENSOR_W
    ys = (P @ up) / zc * LENS_MM / SENSOR_W
    h = width * 9 / 16
    return np.stack([width / 2 + xs * width, h / 2 - ys * width], 1), zc


def opening_eye():
    """The opening wide (plan section 4, founder: oblique from 1.6 m, descending over 3 s): the eye 1.6 m over the top,
    back from the launch corner along the table's diagonal, at the nearest distance from which the whole groove and the
    well fit the 50 mm frame with a 4% margin. Aimed at the groove's centroid."""
    ss = np.linspace(0, LENGTH, 200)
    pts = np.array([[*point(s)[:2], 0.0] for s in ss] + [[WELL["x"][1], WELL["y"][1], 0], [WELL["x"][1], WELL["y"][0], 0]])
    tgt = np.array([pts[:, 0].mean(), pts[:, 1].mean(), 0.0])
    d = np.array([1.0, 0.62])
    d /= np.linalg.norm(d)
    for back in np.arange(0.2, 6.0, 0.02):
        eye = np.array([0.15 - back * d[0], 0.12 - back * d[1], OPEN["height"]])
        px, zc = project_px(eye, tgt, pts)
        if (zc > 0).all() and (px[:, 0] > 0.04 * 1920).all() and (px[:, 0] < 0.96 * 1920).all() and \
                (px[:, 1] > 0.04 * 1080).all() and (px[:, 1] < 0.96 * 1080).all():
            return eye, tgt
    raise ValueError("no opening eye fits the run")


def marble_px(distance_m, width_px=1920):
    return 2 * R * LENS_MM / (SENSOR_W * distance_m) * width_px


PLAN_NOTES = [
    "run length 7.99 m (the plan's 10.3 m does not fit three reaches and two 0.365 m turns on a 3.0 m top)",
    "launch energy from a carved oak release block (riser) at the launch corner; the groove floor runs 8 to <=18 mm "
    "under the top so the marble stays visible (the plan's 45 mm fall inside the slab would hide it)",
    "reaches 0.7305 m apart (turn radius 0.365 m), so the 0.675 m Admiralty chart fits between grooves",
    "the felt well's floor follows the groove's end depth (3 mm lip kept): about 21 mm deep, not 6 mm",
    "the stick chart (0.80 x 0.74 m) fits no band; it hangs on the wall behind the far edge",
    "the plan's brass disc has no gated scan: the jeton weights the Admiralty chart's corner",
]
