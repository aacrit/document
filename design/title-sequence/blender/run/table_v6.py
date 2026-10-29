"""Title v6 (The Run with the instruments): the table, the fall, the roof-tiled records and the preview-1 checks
(numpy and scipy; pure functions, no I/O). The MuJoCo bake (sim_v6.py), the bake plot and, from day 5, the scene read
this module, so the picture and the physics stand on the same ground.

Spec: Agentique reports/briefs/title-v6/v6-spec.md and v6-beats.json (Fable, 2026-10-26).

Table frame: v5d's (channel_v5c): metres, origin at the top's near-left corner, x along the 3.0 m length, y away from
the camera side, z up from the oak top. The well (x 2.43-2.95, y 1.25-1.67, felt top 23.9 mm down) and the record are
v5d's, unchanged, so the A7 calibration carries.

The fall is the table out of level: gravity tilted FALL_DEG along the path heading (nothing carved). The two sags are
the top's own warp, as a height field: the near-left corner stands 1.4 mm proud so the first 0.15 m falls at 1.0
degree, and everything uphill of the lip's last 0.30 m stands 5.5 mm proud of the well's level so that stretch falls
at 1.5 degrees along the path. The warp is zero on and past the lip line: the well and the record keep v5d's level.

Where the build departs from the spec's estimates (each forced by its own numbers; the report repeats them):
- the start is the beats' (0.20, 0.22) and the lip v5d's x = 2.43, so the path is 2.48 m straight to the lip, not
  2.62; the sheets lie at their real sizes in date order, Ino at s 1.80-2.30 over the chart's top panel for its last
  0.20 m (the path meets the chart's square at s 2.10);
- the chart lies squared to the well (its downhill edge is the lip, as the spec says), so the path crosses it on the
  diagonal;
- the weights stand on the path's right so the glance turns the ball left (+y), as section 3.4 requires; the
  globe's foot on its left (3.5 turns it right). "Piri's left corner" is read in the parchment's own frame.
- the globe's foot is a turned wooden foot (the museum record), not iron.
- the sheets are flat plates of their real thickness: Laid Down's cockle (to 1.8 degree slopes) and proud edges
  would steer a ball rolling at a 0.45 degree fall, which v4.1 showed fails (U2, U3). The scene must lay the same
  flat plates.
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np

import bench as B
import channel_v5c as C

G = 9.81
FPS = 30000 / 1001
FRAMES = 1080
DURATION = FRAMES / FPS
T_RELEASE = 12 / FPS                       # the latch opens at f12 (spec section 3.1)

R = 0.015                                  # the clay ball, 30 mm
RHO_CLAY = 1900.0
MASS = RHO_CLAY * 4.0 / 3.0 * math.pi * R ** 3    # 26.9 g (the spec's 27 g)
K_ROLL = 5.0 / 7.0

TABLE = dict(C.TABLE)
CELL = 0.0015
WELL = dict(C.WELL)
FELT_TOP = C.felt_top()                    # -0.0239: the felt's top under the table top (v5d)
LIP_X = WELL["x"][0]
RECORD_RECT = C.record_rect("C20-METAR-0851")     # every film's record starts at x 2.690 (C.RECORD_X0)
REST_GAP = 0.007                           # the ball's surface 7 mm short of the record's near edge
REST_TARGET = (RECORD_RECT[0] - REST_GAP - R, (RECORD_RECT[2] + RECORD_RECT[3]) / 2)

# ------------------------------------------------------------------------------------------------ the path

HEADING_DEG = 26.0
START = (0.20, 0.22)                       # the ball in the latch's cup (v6-beats path.start_m)
U = np.array([math.cos(math.radians(HEADING_DEG)), math.sin(math.radians(HEADING_DEG))])
N = np.array([-U[1], U[0]])                # left of the heading (+y side)
S_LIP = (LIP_X - START[0]) / U[0]          # 2.481 m


def point(s):
    s = np.asarray(s, float)
    return START[0] + s * U[0], START[1] + s * U[1]


def along(x, y):
    return (np.asarray(x, float) - START[0]) * U[0] + (np.asarray(y, float) - START[1]) * U[1]


def across(x, y):
    return (np.asarray(x, float) - START[0]) * N[0] + (np.asarray(y, float) - START[1]) * N[1]


# ------------------------------------------------------------------------------------------------ the fall

FALL_DEG = 0.45                            # tuned to the measured mu_r (sim_v6 --tune); see FALL_TUNED
SAGS = [{"name": "latch sag", "deg": 1.0, "len": 0.15, "where": "board 1, the first 0.15 m after the latch"},
        {"name": "chart sag", "deg": 1.5, "len": 0.30, "where": "the chart's last 0.30 m before the lip"}]
SAG_EASE = 0.02                            # each sag eases in and out over 2 cm (no kink)


def _ramp(d, length, ease=SAG_EASE):
    """The integral of a slope that is 1 over [0, length] (eased over `ease` at each end) and 0 outside, from d to
    +inf, so the height above the zone's far end: smooth, monotone, `length` at d <= 0."""
    d = np.asarray(d, float)
    xs = np.linspace(-ease, length + ease, 801)
    w = np.clip((xs + ease) / (2 * ease), 0, 1)
    w = np.minimum(w, np.clip((length + ease - xs) / (2 * ease), 0, 1))
    w = w * w * (3 - 2 * w)
    w *= length / np.trapezoid(w, xs)
    cum = np.concatenate([[0.0], np.cumsum(0.5 * (w[1:] + w[:-1]) * np.diff(xs))])
    tail = cum[-1] - cum                    # integral from xs to the end
    return np.interp(d, xs, tail, left=cum[-1], right=0.0)


def warp(x, y):
    """The top's warp (m) above the plane the fall tilts: zero on and past the lip line."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    k1 = math.tan(math.radians(SAGS[0]["deg"])) - math.tan(math.radians(FALL_DEG))
    k2 = math.tan(math.radians(SAGS[1]["deg"])) - math.tan(math.radians(FALL_DEG))
    s = along(x, y)
    z = k1 * _ramp(s, SAGS[0]["len"])
    # the chart sag: a function of the distance to the lip line measured along the path, so the well stays level
    w = (LIP_X - x) / U[0]
    return z + k2 * _sag2(w)


def _sag2(w):
    """Height above the lip's level of a point w metres uphill of the lip line (along the path) for a unit slope
    excess over the last SAGS[1]['len']: 0 at and past the lip, rising over the zone, constant uphill of it."""
    L = SAGS[1]["len"]
    return L - _ramp(w, L)


def gravity_vec(fall_deg=None):
    th = math.radians(FALL_DEG if fall_deg is None else fall_deg)
    return np.array([G * math.sin(th) * U[0], G * math.sin(th) * U[1], -G * math.cos(th)])


# ------------------------------------------------------------------------------------------------ the records

# Top of the pile first. s: along the path (aligned sheets), n: across it (left positive). t: thickness on the path
# (folded sheets count their layers). drape: how far the sheet bends over an edge beneath it (paper) or bridges it
# (the boards). layer: the order set down (the chart first). mu: the surface the ball rolls on (table_v6.MU_R).
HINGE_GAP = 0.0015
_B1 = (-0.03, 0.47)
SHEETS = [
    {"name": "atlas1", "ledger": "T-03", "date": 1375, "surface": "vellum", "s": _B1, "n": (-0.245, 0.443),
     "t": 0.0012, "drape": 0.060, "layer": 6, "what": "Catalan Atlas board 1 (vellum on board)"},
    {"name": "atlas2", "ledger": "T-03", "date": 1375, "surface": "vellum",
     "s": (_B1[1] + HINGE_GAP, _B1[1] + HINGE_GAP + 0.50), "n": (-0.245, 0.443), "t": 0.0012, "drape": 0.060,
     "layer": 6, "what": "Catalan Atlas board 2"},
    {"name": "leaf", "ledger": "T-06", "date": 1455, "surface": "leaf", "s": (0.92, 1.22), "n": (-0.27, 0.15),
     "t": 0.00015, "drape": 0.015, "layer": 5, "what": "Gutenberg leaf; the galley on its left margin"},
    {"name": "piri", "ledger": "T-04", "date": 1513, "surface": "parchment", "s": (1.17, 1.82), "n": (-0.43, 0.43),
     "t": 0.0003, "drape": 0.015, "layer": 4, "what": "Piri Reis (keyed fragment, 0.65 x 0.87)"},
    {"name": "ino", "ledger": "T-08", "date": 1821, "surface": "washi", "s": (1.80, 2.30), "n": (-0.29, 0.29),
     "t": 0.00016, "drape": 0.015, "layer": 3, "what": "Ino sheet 6, folded in half (crease away from the path)"},
    {"name": "chart", "ledger": "T-20", "date": 1931, "surface": "chart", "rect": (LIP_X - 0.34, LIP_X, 1.12, 1.46),
     "t": 0.00072, "drape": 0.015, "layer": 2, "what": "Admiralty 983 folded in six, squared to the well"},
]
BY_NAME = {s["name"]: s for s in SHEETS}


def footprint(name):
    """(contains(x, y) -> bool array, corners) of a sheet's footprint."""
    sh = BY_NAME[name]
    if "rect" in sh:
        x0, x1, y0, y1 = sh["rect"]
        return (lambda x, y: (x >= x0) & (x <= x1) & (y >= y0) & (y <= y1)), [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    s0, s1 = sh["s"]
    n0, n1 = sh["n"]

    def inside(x, y):
        s, n = along(x, y), across(x, y)
        return (s >= s0) & (s <= s1) & (n >= n0) & (n <= n1)
    cs = [(s0, n0), (s1, n0), (s1, n1), (s0, n1)]
    return inside, [(START[0] + a * U[0] + b * N[0], START[1] + a * U[1] + b * N[1]) for a, b in cs]


def path_span(name, ds=0.0005):
    """(s0, s1): where the nominal path runs over the sheet's footprint (whatever lies on top of it)."""
    ss = np.arange(-0.05, S_LIP + 1e-9, ds)
    inside, _ = footprint(name)
    m = inside(*point(ss))
    return (float(ss[m].min()), float(ss[m].max())) if m.any() else None


# ------------------------------------------------------------------------------------------------ the ground


@lru_cache(maxsize=4)
def stack_grid(cell=CELL):
    """The top of the table and every sheet on a cell grid over the whole table: (xs, ys, warp, {name: top or NaN},
    top-of-everything). Sheets are laid from the bottom of the pile up; each rests on what is under it and drapes over
    an edge beneath it (max of the surface under it and that surface smoothed over the sheet's drape) plus its
    thickness. The well is cut to the felt's floor."""
    from scipy.ndimage import gaussian_filter
    W, H = TABLE["size"]
    xs = np.arange(int(round(W / cell)) + 1) * cell
    ys = np.arange(int(round(H / cell)) + 1) * cell
    X, Y = np.meshgrid(xs, ys)
    wz = warp(X, Y)
    cur = wz.copy()
    tops = {}
    # one layer at a time, every sheet of a layer laid on the same ground (the Atlas's two boards lie side by side:
    # board 2 must not drape over board 1)
    for layer in sorted({s["layer"] for s in SHEETS}):
        nxt = cur.copy()
        for sh in [s for s in SHEETS if s["layer"] == layer]:
            inside, _ = footprint(sh["name"])
            m = inside(X, Y)
            sm = gaussian_filter(cur, sh["drape"] / cell / 2.0, mode="nearest")
            top = np.maximum(cur, sm) + sh["t"]
            tops[sh["name"]] = np.where(m, top, np.nan)
            nxt = np.where(m, top, nxt)
        cur = nxt
    return xs, ys, wz, tops, cur


def sample(grid, xs, ys, x, y):
    """Bilinear sample of a cell grid (NaN-aware: NaN where any neighbour is NaN)."""
    fi = (np.asarray(x, float) - xs[0]) / (xs[1] - xs[0])
    fj = (np.asarray(y, float) - ys[0]) / (ys[1] - ys[0])
    i0 = np.clip(np.floor(fi).astype(int), 0, len(xs) - 2)
    j0 = np.clip(np.floor(fj).astype(int), 0, len(ys) - 2)
    ti, tj = np.clip(fi - i0, 0, 1), np.clip(fj - j0, 0, 1)
    a = grid
    return (a[j0, i0] * (1 - ti) * (1 - tj) + a[j0, i0 + 1] * ti * (1 - tj) + a[j0 + 1, i0] * (1 - ti) * tj +
            a[j0 + 1, i0 + 1] * ti * tj)


def top_sheet(x, y):
    """The name of the uppermost sheet over each point, 'oak' where none is, 'well' inside the well."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    out = np.full(np.broadcast(x, y).shape, "oak", dtype=object)
    for sh in sorted(SHEETS, key=lambda s: s["layer"]):
        inside, _ = footprint(sh["name"])
        out = np.where(inside(x, y), sh["name"], out)
    inw = (x > WELL["x"][0]) & (x < WELL["x"][1]) & (y > WELL["y"][0]) & (y < WELL["y"][1])
    return np.where(inw, "well", out)


def ground_profile(ss, cell=CELL):
    """Along the path: the ground z, the warp, the top sheet, and the ball centre's height above the ground's plane
    (the envelope a 30 mm ball rides: it bridges a gap narrower than its contact)."""
    xs, ys, wz, tops, cur = stack_grid(cell)
    ss = np.asarray(ss, float)
    x, y = point(ss)
    z = sample(cur, xs, ys, x, y)
    wv = sample(wz, xs, ys, x, y)
    ds = float(np.median(np.diff(ss))) if len(ss) > 1 else cell
    k = int(math.ceil(R / ds))
    zc = np.full(len(ss), -np.inf)
    for j in range(-k, k + 1):
        d = j * ds
        if abs(d) > R:
            continue
        zz = np.roll(z, -j)
        if j > 0:
            zz[-j:] = z[-1]
        elif j < 0:
            zz[:-j] = z[0]
        zc = np.maximum(zc, zz + math.sqrt(R * R - d * d) - R)
    return {"s": ss, "x": x, "y": y, "z": z, "warp": wv, "zc": zc, "sheet": top_sheet(x, y)}


def rises(s, z, h_min=1e-5):
    """Every stretch where z climbs (a rise of more than h_min), with its height and length."""
    s, z = np.asarray(s), np.asarray(z)
    out, i, n = [], 0, len(z)
    while i < n - 1:
        if z[i + 1] > z[i] + 1e-9:
            j = i
            while j < n - 1 and z[j + 1] >= z[j] - 1e-9:
                j += 1
            h = z[j] - z[i]
            if h > h_min:
                out.append({"s": float(s[i]), "h": float(h), "len": float(s[j] - s[i])})
            i = j
        i += 1
    return out


def down_steps(s, z, sheets=None):
    """Each change of the top sheet along the path, with the step in the ground across it (+ up, - down)."""
    if sheets is None:
        x, y = point(s)
        sheets = top_sheet(x, y)
    out = []
    for i in range(1, len(s)):
        if sheets[i] != sheets[i - 1]:
            a, b = max(0, i - 4), min(len(s) - 1, i + 4)
            out.append({"s": float(s[i]), "from": str(sheets[i - 1]), "onto": str(sheets[i]),
                        "dz": float(z[b] - z[a])})
    return out


def v_stall(h):
    """The least speed at which a rolling solid sphere climbs an up-step of height h (sqrt(10/7 g h))."""
    return math.sqrt(10.0 / 7.0 * G * h) if h > 0 else 0.0


# ------------------------------------------------------------------------------------------------ rolling resistance

# mu_r is the rolling-resistance coefficient (resisting force over normal load; MuJoCo's rolling friction is mu_r * R).
# bench.RR holds M1's coefficients for the 16 mm marble. For a hard sphere rolling on a viscoelastic surface the
# hysteresis loss gives mu_r = (3 alpha / 16)(a / R) with the Hertz contact radius a = (3 W R / 4 E*)^(1/3)
# (Tabor 1955, "The mechanism of rolling friction II", Proc. R. Soc. A 229); with the load W growing as R^3 for one
# clay, mu_r grows as R^(1/3). The 30 mm targets are bench.RR times (15/8)^(1/3) = 1.233. They are then MEASURED in
# MuJoCo (murr_v6.py: the 30 mm ball rolled on each paper's plate with the bake's own contact settings, its
# deceleration read) and MuJoCo's rolling coefficient calibrated until the measurement equals the target.
R16 = 0.008
TABOR = (R / R16) ** (1.0 / 3.0)
MU_R_TARGET = {"vellum": B.RR["vellum"] * TABOR, "leaf": B.RR["leaf"] * TABOR, "parchment": B.RR["parchment"] * TABOR,
               "washi": B.RR["washi"] * TABOR, "chart": B.RR["chart"] * TABOR, "oak": B.RR["oak"] * TABOR}
FELT_MU_R = (0.03, 0.06)                    # the felt is the stop's knob (spec section 3.7)


def mu_of(surface_by_s, mu):
    def f(s):
        return mu[surface_by_s(s)]
    return f


def roll_1d(fall_deg, mu_fn, v0, s_end, slope=None, s0=0.0, dt=0.001, t_max=120.0, losses=()):
    """A solid sphere rolling along the path: dv/dt = 5/7 g (sin(fall + slope(s)) - mu_r(s)) with slope(s) the local
    extra fall (radians, from the warp and the plates), and speed losses `losses` [(s, kept fraction)] at glances."""
    th = math.radians(fall_deg)
    s, v, t = s0, v0, 0.0
    ts, ss, vs = [0.0], [s0], [v0]
    pend = sorted(losses)
    stopped = False
    while s < s_end and t < t_max:
        a = K_ROLL * G * (math.sin(th + (slope(s) if slope else 0.0)) - mu_fn(s))
        v += a * dt
        if v <= 0:
            stopped = True
            v = 0.0
            break
        s += v * dt
        t += dt
        while pend and s >= pend[0][0]:
            v *= pend.pop(0)[1]
        ts.append(t)
        ss.append(s)
        vs.append(v)
    return {"t": np.array(ts), "s": np.array(ss), "v": np.array(vs), "stopped": stopped, "t_end": t}


# ------------------------------------------------------------------------------------------------ the contacts

# The seven designed contacts (spec section 3). Geom names: the ball is "ball"; everything else is named by what it is.
DESIGNED = {1: "the latch", 2: "edge ticks", 3: "the galley glance (sort 1)", 4: "the weights glance",
            5: "the globe-foot glance", 6: "close passes (no contact)", 7: "the drop onto the felt"}
SHEET_GEOMS = {s["name"] for s in SHEETS}


def contact_class(pair: str):
    """The designed contact (1-7) a ball contact belongs to, None for a stray, 'row' for the sorts' own contacts."""
    a, b = pair.split("|")
    if "ball" not in (a, b):
        if any(p.startswith("sort") or p.startswith("galley") for p in (a, b)):
            return "row"
        return "other"
    o = b if a == "ball" else a
    if o.startswith("latch"):
        return 1
    if o in SHEET_GEOMS:
        return 2
    if o == "sort1":
        return 3
    if o.startswith("weights"):
        return 4
    if o.startswith("globe"):
        return 5
    if o == "felt":
        return 7
    return None


def turn_deg(v_before, v_after):
    """Signed heading change, degrees, left (+y side of the motion) positive."""
    a = math.atan2(v_before[1], v_before[0])
    b = math.atan2(v_after[1], v_after[0])
    return math.degrees((b - a + math.pi) % (2 * math.pi) - math.pi)


# ------------------------------------------------------------------------------------------------ preview 1

ACCEPT = {"rest_mm": (7.0, 5.0), "centre_line_mm": 5.0, "roll_s": (20.0, 24.0), "v_min": 0.10, "margin": 0.15,
          "sorts": 12, "speed_kept": 0.90, "turn_weights_deg": (20.0, 30.0), "turn_globe_deg": (-25.0, -15.0),
          "gap_m": 0.001, "budget_after_rest_s": 5.0}


def check_rest(xy):
    short = (RECORD_RECT[0] - (xy[0] + R)) * 1000
    off = (xy[1] - REST_TARGET[1]) * 1000
    want, tol = ACCEPT["rest_mm"]
    return {"short_mm": short, "off_centre_mm": off,
            "pass": abs(short - want) <= tol and abs(off) <= ACCEPT["centre_line_mm"]}


def check_budget(t_rest):
    """The whole shot fits 1080 frames: rest, then the descent and the pose (5 s, the pose held 1 s) before f1080."""
    end = t_rest + ACCEPT["budget_after_rest_s"]
    return {"t_rest": t_rest, "end_s": end, "frames_s": DURATION, "slack_s": DURATION - end, "pass": end <= DURATION}
