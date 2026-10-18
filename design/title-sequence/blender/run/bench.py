"""The Run, v4: one dining table, its plan and the design's clock (stdlib only: MuJoCo, Blender and pytest all import
it). Design: reports/briefs/document-title-run-v4-design.md (founder-approved 2026-10-18: the wide at the end only,
tails of 252/264/276 frames, a 2.2 x 1.0 m oak table with breadboard ends).

Table coordinates, metres: the origin is the table top's near-left corner, x along the table's length (the fall line,
toward the record: time), y across it (the camera side is y = 0), z up from the top. Everything is in title seconds
(t = f / 24 for the design's 24 fps frame numbers), so one simulation and one camera serve both masters.

Physics, measured before this plan was laid (work/v4proto): on a uniform 1.0 degree fall a free marble crossing the slope
at 72 degrees curls downhill within about 0.3 m. The legs of the serpentine are therefore carried by the sheets' own
cockle, laid as parallel troughs (paper cockles in waves along its grain) running with each leg, 1.5 to 4 mm deep at
0.15 to 0.3 m (the design's cockle range). The U-turns are the named curls and lifts. Nothing is a wall or a ramp.
"""

from __future__ import annotations

import math

FPS = 24
NTSC = (30000, 1001)
G = 9.81
R = 0.008                                   # clay marble radius (16 mm)
RHO_CLAY = 1900.0
MASS = RHO_CLAY * 4.0 / 3.0 * math.pi * R ** 3
# the galley's pair: clear glass marbles of the same 16 mm (founder, 2026-10-18: the clay lead is the obvious
# protagonist; the two it sets going are visibly a different real material). Steel bearing balls (7850 kg/m3) were
# tried: four times the clay's mass, the falling sorts cannot push them off the lip (sim, f300-f520). Glass at its real
# density (2500 kg/m3) keeps the release.
RHO_PAIR = 2500.0
PAIR_MATERIAL = "glass"
MASS_PAIR = RHO_PAIR * 4.0 / 3.0 * math.pi * R ** 3

# ------------------------------------------------------------------------------------------------ the table

TABLE = {"size": (2.2, 1.0), "top": 0.04, "boards": 4, "board_w": 0.25, "chamfer": 0.003, "breadboard": 0.07,
         "height": 0.75}
FALL_DEG = 0.85                             # the one tuning knob: the floor out of level along +x, nothing shimmed
                                            # (founder 2026-10-18: slower, by physics: from 1.0 toward 0.8)
FALL_RANGE = (0.8, 1.3)

# rolling resistance as a ratio (MuJoCo's rolling friction is this times R), per surface (M1's coefficients)
RR = {"oak": 0.004, "papyrus": 0.0078, "vellum": 0.0052, "parchment": 0.0050, "leaf": 0.006, "washi": 0.0070,
      "tape": 0.0065, "card": 0.0065, "page": 0.0065, "chart": 0.0065, "felt": 0.035, "brass": 0.001, "bronze": 0.001,
      "film": 0.006}

# ------------------------------------------------------------------------------------------------ the latch

# The approved latch (re-proof, founder 2026-10-17) is kept in its own local frame exactly: disc at the local origin,
# the marble released from local (-0.031, 0), the papyrus's edge at local x 0.2305, the camera, lamp and card offsets.
# The local frame is turned so the released marble's own path (local -10.5 degrees as v4's stiffer contact kicks it;
# the proof's softer contact gave -6.5, latch-bake.json) heads
# -53 degrees on the table, and the disc is set at LATCH["disc"]. The 2.5 degree zone runs along the release heading
# to the papyrus's edge, as in the approved proof (the design's 0.12 m would change the approved frames f121-167).
LATCH = {"disc": (0.37, 0.92), "heading_deg": -53.0, "path_local_deg": -10.5, "fall_deg": 2.5, "zone_len": 0.262,
         "start_local": (-0.031, 0.0), "papyrus_local_x": 0.2305}
LATCH["rot_deg"] = LATCH["heading_deg"] - LATCH["path_local_deg"]


def latch_to_table(p):
    """A point in the approved latch's local frame (disc at the origin) to table coordinates."""
    a = math.radians(LATCH["rot_deg"])
    x, y = p[0], p[1]
    return (LATCH["disc"][0] + x * math.cos(a) - y * math.sin(a), LATCH["disc"][1] + x * math.sin(a) + y * math.cos(a))


def heading_vec(deg):
    return (math.cos(math.radians(deg)), math.sin(math.radians(deg)))


# The tablet cannot lie where the plan drew it (x 0.02-0.32, y 0.63-0.93): the approved camera stands there, 4.6 cm
# above its top, and the tablet would hide the disc. It lies at the near-left corner instead, behind the camera,
# out of the latch's frame. The Atlas's first board takes the rest of that corner, so the tablet sits square to the
# table's end and overhangs it by 5 cm (a sixth of its length; its weight is on the oak). It is in the wide.
TABLET = {"ledger": "T-01", "size": (0.31, 0.305, 0.05), "centre": (0.105, 0.1545), "psi": 0.0}

# ------------------------------------------------------------------------------------------------ the sheets

# Each sheet at its real size: W along its image's width (local u, turned psi from +x), H along its height (local v).
# t: thickness (m). layer: the order it was set down (1 first, lowest). date: for the roof-tile check. cockle: parallel
# troughs {amp, lam, deg (the troughs' direction on the table), through (a table point on a trough's floor)}.
# edges: named curls and lifts {edge: "-v"|"+v"|"-u"|"+u", crest, run} (crest m, over run m); corners: lifts (m).
# The release line as the v4 simulation measures it (sim/v4 probe, f136-f146): the papyrus is laid on it, its head
# where the approved proof had it (local x 0.2305 from the disc along the latch's own axis).
LATCH["release_line"] = {"through": (0.429, 0.774), "deg": -51.0}
_HD = heading_vec(LATCH["release_line"]["deg"])
_START = latch_to_table(LATCH["start_local"])
_PAP_L = 0.60
_ax = heading_vec(LATCH["rot_deg"])
_P0 = LATCH["release_line"]["through"]
# the point on the release line at local x 0.2305 from the disc: (P0 + s HD - disc) . ax = 0.2305
_s = (LATCH["papyrus_local_x"] - ((_P0[0] - LATCH["disc"][0]) * _ax[0] + (_P0[1] - LATCH["disc"][1]) * _ax[1])) /     (_HD[0] * _ax[0] + _HD[1] * _ax[1])
_PAP_HEAD = (_P0[0] + _s * _HD[0], _P0[1] + _s * _HD[1])
_PAP_C = (_PAP_HEAD[0] + _PAP_L / 2 * _HD[0], _PAP_HEAD[1] + _PAP_L / 2 * _HD[1])

HINGE = {"lo": (0.920, 0.110), "deg": -66.0, "len": 0.688, "gap": 0.0015, "depth": 0.0015, "half_w": 0.025}
_HV = heading_vec(HINGE["deg"])
HINGE["hi"] = (HINGE["lo"][0] - HINGE["len"] * _HV[0], HINGE["lo"][1] - HINGE["len"] * _HV[1])
_HMID = ((HINGE["lo"][0] + HINGE["hi"][0]) / 2, (HINGE["lo"][1] + HINGE["hi"][1]) / 2)
_N2 = (-_HV[1], _HV[0]) if -_HV[1] > 0 else (_HV[1], -_HV[0])         # the board-2 side (+x)
_ATLAS_W, _ATLAS_H = 0.50, 0.50 * 3800 / 2760

SHEETS = {
    "papyrus": {"ledger": "T-02a", "tex": "T-02a_keyed", "alpha": True, "date": -1153, "surface": "papyrus",
                "size": (_PAP_L, _PAP_L * 1481 / 8192), "centre": _PAP_C, "psi": LATCH["release_line"]["deg"], "t": 0.00025,
                "drape": 0.040,                      # stiff: it bridges a step like a beam, over about 10 cm
                "backing": True,                     # the fragments are mounted on a backing (plain, the scan's margin colour)
                "layer": 10,  # dried papyrus cups across its width: its cockle is one trough, 3 mm deep, crest to crest across the strip
                "cockle": {"amp": 0.003, "lam": _PAP_L * 1481 / 8192, "deg": LATCH["release_line"]["deg"], "through": _PAP_C},
                "edges": [{"edge": "+u", "crest": 0.002, "run": 0.03}], "corners": {}},
    "atlas1": {"ledger": "T-03", "tex": "T-03_board1", "date": 1375, "surface": "vellum", "board": 0.0010,
               "size": (_ATLAS_W, _ATLAS_H), "psi": math.degrees(math.atan2(_N2[1], _N2[0])), "t": 0.0012,
               "centre": (_HMID[0] - (_ATLAS_W + HINGE["gap"]) / 2 * _N2[0], _HMID[1] - (_ATLAS_W + HINGE["gap"]) / 2 * _N2[1]),
               "layer": 8, "cockle": None, "edges": [], "corners": {}},
    "atlas2": {"ledger": "T-03", "tex": "T-03_board2", "date": 1375, "surface": "vellum", "board": 0.0010,
               "size": (_ATLAS_W, _ATLAS_H), "psi": math.degrees(math.atan2(_N2[1], _N2[0])), "t": 0.0012,
               "centre": (_HMID[0] + (_ATLAS_W + HINGE["gap"]) / 2 * _N2[0], _HMID[1] + (_ATLAS_W + HINGE["gap"]) / 2 * _N2[1]),
               "layer": 4, "cockle": None, "edges": [], "corners": {}},
    "piri": {"ledger": "T-04", "tex": "T-04_keyed", "alpha": True, "date": 1513, "surface": "parchment",
             "size": (0.65, 0.65 * 2619 / 1964), "centre": (1.130, 0.4555), "psi": 180.0, "t": 0.0003, "layer": 6, "cockle_clear_hinge": 0.05,
             "drape": 0.015,                         # parchment: stiffer than paper; the hinge dip survives under it
             "cockle": {"amp": 0.0035, "lam": 0.20, "deg": 72.0, "through": (0.935, 0.060)},
             # turned 180 degrees: the fragment's diagonal cut lies at the far right, its near edge is the straight top
             # of the map (image +v is now the table's near side)
             "edges": [{"edge": "+v", "crest": 0.015, "run": 0.05}], "corners": {"+u-v": 0.004, "-u-v": 0.004}},
    "leaf": {"ledger": "T-06", "tex": "T-06_leaf", "date": 1455, "surface": "leaf", "size": (0.30, 0.42),
             "centre": (1.160, 0.620), "psi": 60.0 - 90.0, "t": 0.00015, "layer": 7,
             "cockle": {"amp": 0.0005, "lam": 0.15, "deg": 60.0, "through": (1.10, 0.50)}, "edges": [], "corners": {}},
    "ino": {"ledger": "T-08", "tex": "T-08_sheet", "date": 1821, "surface": "washi", "size": (1.0, 1.0 * 4740 / 8192),
            "centre": (1.175, 0.633), "psi": -8.0, "t": 0.00008, "layer": 3,
            "cockle": {"amp": 0.0015, "lam": 0.25, "deg": -76.0, "through": (1.37, 0.85)},
            "crease": {"from": (1.37, 0.85), "to": (1.49, 0.44), "depth": 0.003, "half_w": 0.03},
            "edges": [{"edge": "+v", "crest": 0.010, "run": 0.04}], "corners": {}},
    "page": {"ledger": "T-18", "tex": "T-18_page", "date": 1921, "surface": "page", "size": (0.216, 0.216 * 4429 / 3104),
             "centre": (1.530, 0.175), "psi": 0.0, "t": 0.0001, "layer": 2,
             "cockle": {"amp": 0.002, "lam": 0.18, "deg": -70.0, "through": (1.46, 0.30)}, "edges": [],
             "corners": {"+u-v": 0.005}},
    "chart": {"ledger": "T-20", "tex": "T-20_chart", "date": 1931, "surface": "chart", "size": (1.0, 1.0 * 5529 / 8192),
              "centre": (1.435, 0.500), "psi": 90.0, "t": 0.00012, "layer": 1,
              "cockle": {"amp": 0.003, "lam": 0.20, "deg": 70.0, "through": (1.58, 0.06)},
              "edges": [{"edge": "-u", "crest": 0.020, "run": 0.06, "taper": (0.020, 0.006)}], "corners": {}},
    # psi 90: -u is the near side; the roll is 20 mm at its x-far end (U3) and 6 mm at its x-near end, under Piri Reis
}

# Smaller paper, on the sheets (drawn and collided as thin layers of the same heightfield)
SMALL = {
    "tape": {"ledger": "T-09", "tex": "T-09_tape", "w": 0.012, "t": 0.00008, "on": "ino", "surface": "tape"},
    "card": {"size": (0.187, 0.0826), "t": 0.000178, "on": "ino", "surface": "card", "corner_lift": 0.003},
    "strip": {"ledger": "T-16", "w": 0.035, "len": 0.30, "t": 0.00014, "perf": (0.0028, 0.00198, 0.00475),
              "on": "page", "surface": "film", "bow": 0.002},
}

# the roof-tile order is time order (older over newer), with the exceptions the path needs: the Atlas's second board
# (1375) lies under the Gutenberg leaf (c. 1455) and Piri Reis (1513). The U1 return
# climbs the parchment's drape back over board 2's end (design section 2: "board 2 under Piri Reis"; with board 2 on
# top its 3 mm end would be a wall across the return). Pairs are (over, under).
ROOF_EXCEPTIONS = {("piri", "atlas2"), ("leaf", "atlas2")}

# U-turn banks: the named edges, read by relief.py and checked in the event log
BANKS = {"U1": {"sheet": "piri", "edge": "+v", "crest": 0.015, "run": 0.050, "in": -72.0, "out": 72.0},
         "U2": {"sheet": "ino", "edge": "+v", "crest": 0.010, "run": 0.040, "in": 60.0, "out": -76.0},
         "U3": {"sheet": "chart", "edge": "-u", "crest": 0.020, "run": 0.060, "in": -70.0, "out": 70.0}}

# props, at their plan positions (the simulation places rims and entries by roll-out within the design's tolerances)
DISC = {"A": 0.0225, "T": 0.003}
HINGE_GAP = HINGE["gap"]
KHIPU = {"cord_r": 0.0011, "knot_r": 0.0024, "knots": 7, "span": ((0.93, 0.18), (0.98, 0.40)), "cord_deg_to_leg": 30.0}
# 36-pt 8-to-em spaces, half extents (1.59 x 12.7 x 20.3 mm): blank sorts as the approved galley, thinner, so the row
# falls to the strike of a marble at 0.15 m/s (the approved proof's 4-to-em spaces needed about 0.23; the legs of the
# labyrinth hold 0.17 to 0.20; measured, work/galleytest)
QUAD = (0.000794, 0.00635, 0.01015)
# the galley on its line (as the roll-out lays it); a loaded brass galley presses the papers under it flat: no cockle
# within half_w of its line, fading over 3 cm (relief.py)
GALLEY = {"from": (1.07, 0.44), "to": (1.24, 0.67), "mouth_deg_to_leg": 12.0, "on": "leaf", "mouth_widen": 0.004,
          "press_half_w": 0.06}
REEL_REG = {"r": 0.032, "h": 0.012, "hub_r": 0.006, "hub_h": 0.012, "mass": 0.012, "damp": 2.0e-6, "fric": 1.5e-6,
            "at": (1.52, 0.40)}
REEL_FILM = {"r": 0.045, "h": 0.010, "hub_r": 0.008, "hub_h": 0.012, "mass": 0.022, "damp": 3.0e-6, "fric": 2.0e-6,
             "at": (1.46, 0.18)}
# a local steeper fall (within the fall's range), the table's own sag under the galley (founder 2026-10-18: if the
# slower run starves the galley's strike, a slightly steeper local approach): (centre, radius, fall degrees along +x)
FALL_ZONES = [{"name": "galley", "centre": (1.15, 0.50), "r": 0.16, "deg": 1.3}]
IMPACT_MIN = 0.45                           # the reels' glance: impact parameter (in units of R + r) at least this
PLATEN = {"r": 0.020, "len": 0.30, "from": (1.60, 0.10), "to": (1.76, 0.35), "pinned": True}
# The lattice is 0.80 x 0.74 m of sticks (the keyed photograph is lattice edge to edge) and cannot lie in the plan's
# x 1.58-1.82: it would cover Ino's crease and the felt. It lies turned 90 degrees in the far corner, overhanging the
# far edge by 0.30 m and the end by 0.08 m (its centre of mass well on the table), its near ribs at y 0.50 over the
# chart's end and the oak: the marbles tick along those near ribs on their way to the brass.
STICK = {"ledger": "T-19", "tex": "T-19_keyed", "size": (0.80, 0.80 * 7602 / 8192), "raise": 0.008, "rib_h": 0.005,
         "centre": (1.910, 0.900), "psi": 90.0, "entry_tol": 0.05}
BRASS = {"A": 0.025, "T": 0.0015, "rho": 8500.0, "lean_deg": 3.3, "C_HZ": 24.0 * (0.0225 / 0.025) ** 0.5,
         "alpha_land_deg": 5.7, "at": (1.86, 0.45)}

# ------------------------------------------------------------------------------------------------ the dark, the felt

DARK_X0 = 1.92                              # past the brass disc: the prefix keeps x > DARK_X0 black (the lamp's mask)
OAK_PER_YEAR = 0.001                        # m of bare oak per year after 1931, from DARK_X0
FELT = (0.30, 0.70)                         # nominal; it runs to FELT_X1, y 0.15-0.85
FELT_X1 = 2.19
FELT_Y = (0.06, 0.46)                       # below the lattice (the plan's y 0.15-0.85 lies under it)
FELT_T = 0.0012
RECORD_T = 0.00012

# ------------------------------------------------------------------------------------------------ the clock

# design frames at 24 fps (section 4); the bake replaces them, the prefix's length and the brass are fixed
DESIGN = {
    "lamp_up": 36, "slap": 120, "release": 121, "papyrus_edge": 167, "fold": 196, "vellum": 240, "hinge": 252,
    "off_boards": 330, "U1": (336, 348), "knots": (372, 404), "quad1": 432, "row_end": 456, "stop": 458,
    "pair": (460, 463), "leaf_exit": (492, 495), "U2": (516, 528), "tape": 552, "reel_reg": (576, 610), "card": 600,
    "off_ino": 640, "reel_film": (654, 700), "perfs": (664, 676), "U3": (700, 712), "platen": 724, "ribs": (744, 800),
    "off_chart": (850, 856), "brass_hit": 866, "brass_slap": 926, "prefix_end": 935,
}
BRASS_TOL = 12                              # f866 and f926, each within 12 frames, after tuning the fall only
PREFIX_FRAMES = 936                         # f0..f935, 39.0 s

# per film: the record, its class label, the years crossed in the dark, and the tail's windows at 24 fps:
# (find, descend, close, dissolve, tour)
FILMS = {
    "S-130": {"film": "Not a Free Agent", "label": "Archive · 1947", "cls": "ARCHIVE", "year": 1947,
              "tail": (72, 72, 24, 24, 60), "tex": "R-S-130", "width_m": 0.30, "img": (1284, 1987)},
    "S-16928": {"film": "The Next Village", "label": "Archive · 1976", "cls": "ARCHIVE", "year": 1976,
                "tail": (84, 72, 24, 24, 60), "tex": "R-S-16928", "width_m": 0.42, "img": (2874, 1686)},
    "C20-METAR-0851": {"film": "Real World", "label": "Drawn · 2001", "cls": "DRAWN", "year": 2001,
                       "tail": (96, 72, 24, 24, 60), "tex": "R-C20-METAR-0851", "width_m": 0.20, "img": (3840, 2160)},
}
LOCKUP_FRAMES = 120


def record_size(rec):
    """The record's (along x, along y) size on the table: laid across, its shorter side along x."""
    F = FILMS[rec]
    w, h = F["width_m"], F["width_m"] * F["img"][1] / F["img"][0]
    return (min(w, h), max(w, h)), (w < h)        # (size, upright: the image's width runs along x)


def felt_x0(rec):
    return DARK_X0 + OAK_PER_YEAR * (FILMS[rec]["year"] - 1931)


def t_of(frame: float, fps: float = FPS) -> float:
    return frame / fps


def tail_frames(rec: str) -> int:
    return sum(FILMS[rec]["tail"])


def total_frames(rec: str) -> int:
    return PREFIX_FRAMES + tail_frames(rec) + LOCKUP_FRAMES


def fps_value(fps) -> float:
    if isinstance(fps, (tuple, list)):
        return fps[0] / fps[1]
    return float(fps)


def frames_at(seconds: float, fps) -> int:
    """The number of whole frames of a span of seconds at a rate (24 or 30000/1001): the frame count of a master."""
    return int(math.floor(seconds * fps_value(fps) + 1e-6))


# ------------------------------------------------------------------------------------------------ geometry helpers


def corners(cx, cy, W, H, psi_deg):
    """The four table corners of a W x H rectangle centred at (cx, cy), its u axis turned psi from +x: (-u-v), (+u-v),
    (+u+v), (-u+v)."""
    p = math.radians(psi_deg)
    cu, su = math.cos(p), math.sin(p)
    return [(cx + u * cu - v * su, cy + u * su + v * cu) for u, v in ((-W / 2, -H / 2), (W / 2, -H / 2),
                                                                         (W / 2, H / 2), (-W / 2, H / 2))]


def sheet_corners(name):
    s = SHEETS[name]
    return corners(s["centre"][0], s["centre"][1], s["size"][0], s["size"][1], s["psi"])


def to_local(name, x, y):
    s = SHEETS[name]
    p = math.radians(s["psi"])
    dx, dy = x - s["centre"][0], y - s["centre"][1]
    return dx * math.cos(p) + dy * math.sin(p), -dx * math.sin(p) + dy * math.cos(p)


def footprints():
    """Every object's table footprint as a polygon, for the plan's checks."""
    out = {n: sheet_corners(n) for n in SHEETS}
    t = TABLET
    out["tablet"] = corners(t["centre"][0], t["centre"][1], t["size"][0], t["size"][1], t["psi"])
    out["stick"] = corners(STICK["centre"][0], STICK["centre"][1], STICK["size"][0], STICK["size"][1], STICK["psi"])
    out["felt"] = [(FELT_X1 - FELT[0], FELT_Y[0]), (FELT_X1, FELT_Y[0]), (FELT_X1, FELT_Y[1]), (FELT_X1 - FELT[0], FELT_Y[1])]
    a, d = DISC["A"], LATCH["disc"]
    out["disc"] = [(d[0] - a, d[1] - a), (d[0] + a, d[1] - a), (d[0] + a, d[1] + a), (d[0] - a, d[1] + a)]
    b = BRASS["at"]
    out["brass"] = [(b[0] - 0.003, b[1] - 0.025), (b[0] + 0.003, b[1] - 0.025), (b[0] + 0.003, b[1] + 0.025),
                    (b[0] - 0.003, b[1] + 0.025)]
    return out


# overhangs the plan names: Atlas board 1's near corner over the near edge, the stick chart over the far edge
OVERHANGS = {"atlas1": {"y0": 0.11}, "stick": {"y1": 0.32, "x1": 0.10}, "tablet": {"x0": 0.06}}
# props are set down on the sheets, never under them: the roof-tile check is for the sheets
PROPS = {"tablet", "stick", "felt", "disc", "brass"}


def overlap(poly_a, poly_b) -> bool:
    """Separating-axis test for two convex polygons."""
    for poly in (poly_a, poly_b):
        n = len(poly)
        for i in range(n):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % n]
            ax, ay = y2 - y1, x1 - x2
            pa = [ax * x + ay * y for x, y in poly_a]
            pb = [ax * x + ay * y for x, y in poly_b]
            if max(pa) <= min(pb) or max(pb) <= min(pa):
                return False
    return True


# ------------------------------------------------------------------------------------------------ the plan

PLAN = [
    {"beat": "1 latch", "object": "disc", "centre": LATCH["disc"], "psi": None, "heading_in": 0.0, "heading_out": -53.0,
     "cause": "the bronze disc's rim (approved)"},
    {"beat": "2 papyrus", "object": "papyrus", "centre": SHEETS["papyrus"]["centre"], "psi": SHEETS["papyrus"]["psi"],
     "heading_in": -53.0, "heading_out": -53.0, "cause": "the papyrus's fold relief"},
    {"beat": "3 atlas", "object": "atlas", "centre": _HMID, "psi": HINGE["deg"], "heading_in": -53.0, "heading_out": -72.0,
     "cause": "the Atlas hinge (a 1.5 mm valley between 3 mm boards)"},
    {"beat": "U1", "object": "piri", "centre": SHEETS["piri"]["centre"], "psi": 0.0, "heading_in": -72.0, "heading_out": 72.0,
     "cause": "Piri Reis's parchment curl"},
    {"beat": "4 cord", "object": "khipu", "centre": ((KHIPU["span"][0][0] + KHIPU["span"][1][0]) / 2,
                                                     (KHIPU["span"][0][1] + KHIPU["span"][1][1]) / 2), "psi": None,
     "heading_in": 72.0, "heading_out": 72.0, "cause": "the knots (ticks, no turn)"},
    {"beat": "5 galley", "object": "galley", "centre": SHEETS["leaf"]["centre"], "psi": 60.0, "heading_in": 72.0,
     "heading_out": 60.0, "cause": "the galley's brass walls (a 12 degree channel)"},
    {"beat": "U2", "object": "ino", "centre": SHEETS["ino"]["centre"], "psi": -8.0, "heading_in": 60.0, "heading_out": -76.0,
     "cause": "Ino's lifted fold edge"},
    {"beat": "6 survey, wire, count", "object": "reel_reg", "centre": REEL_REG["at"], "psi": None, "heading_in": -76.0,
     "heading_out": -88.0, "cause": "the register reel's rim (a glance that spins it)"},
    {"beat": "7 reel, type", "object": "reel_film", "centre": REEL_FILM["at"], "psi": None, "heading_in": -88.0,
     "heading_out": -70.0, "cause": "the Lumiere reel's rim"},
    {"beat": "U3", "object": "chart", "centre": SHEETS["chart"]["centre"], "psi": 90.0, "heading_in": -70.0, "heading_out": 70.0,
     "cause": "the chart's rolled edge"},
    {"beat": "8 swell", "object": "stick", "centre": STICK["centre"], "psi": STICK["psi"], "heading_in": 70.0, "heading_out": 5.0,
     "cause": "the platen, then the ribs"},
    {"beat": "9 exhaust", "object": "brass", "centre": BRASS["at"], "psi": None, "heading_in": 5.0, "heading_out": 5.0,
     "cause": "the disc"},
    {"beat": "dark", "object": "felt", "centre": (FELT_X1 - FELT[0] / 2, sum(FELT_Y) / 2), "psi": None, "heading_in": 0.0,
     "heading_out": 0.0, "cause": "the felt, then the record's edge"},
]


# ------------------------------------------------------------------------------------------------ v4.1: the collector's desk
# (founder 2026-10-18, approved plan layout/collectors-desk-plan.png). The tuned stretch stands (latch, papyrus, Atlas,
# Piri Reis, khipu, galley on the leaf). After the galley the records lie scattered on bare oak, as a desk mid-work;
# Ino's sheet and the Admiralty chart lie folded as such sheets are kept (their own fold grids), each showing one
# panel of its scan; real objects of the study do the deflecting where a record does not. Sizes are real.
V41 = True
FOLDED = {
    # name: (panels along u, panels along v, the panel shown (iu, iv) from the scan's top-left), the folded size follows
    "ino": (2, 2, (1, 0)),
    "chart": (2, 2, (0, 0)),
}
V41_SHEETS = {
    "ino": {"centre": (1.50, 0.46), "psi": -8.0},          # 0.50 x 0.29 folded; its lifted edge and its crease stand
    "page": {"centre": (1.55, 0.16), "psi": 4.0},
    "chart": {"centre": (1.85, 0.27), "psi": 90.0},        # 0.34 x 0.50 folded; the rolled near edge (U3)
}
TRAY = {"centre": (1.53, 0.84), "size": (0.34, 0.22), "rim_h": 0.018, "rim_t": 0.008, "floor_t": 0.004,
        "wood": "oak", "coins": 9, "coin_gap": 0.011, "note": "the money tray: its rim is a wall (U2); the coin row stands"
        " on edge inside, toppled in sequence when the lead strikes the first"}
COINS = [  # real CC0 scans (Musee Saint-Raymond, Toulouse; Sketchfab), sizes from the museum records
    {"id": "FS-coin-dupondius-octavian", "uid": "48e52062e37d4a6194a36f76f6eb959f", "d": 0.029, "t": 0.0035, "metal": "bronze"},
    {"id": "FS-coin-sesterce-trajan", "uid": "ba652714bc514e3888f94a606985f79e", "d": 0.034, "t": 0.004, "metal": "bronze"},
    {"id": "FS-coin-denier-coelius-caldus", "uid": "1021c13dc0194732bbfe277cd5fb89a7", "d": 0.019, "t": 0.0018, "metal": "silver"},
    {"id": "FS-coin-tetradrachm-alexander", "uid": "8a6b56fedf014ea8a63041b1e4e90016", "d": 0.026, "t": 0.004, "metal": "silver"},
]
JETON = {"uid": "65c81382399942a99ff8daeeb6bd160c", "d": 0.028, "t": 0.0015, "in": "tray"}
SCALE = {"uid": "9c5c67abed6c48459267e5613bcc480f", "pan_centre": (1.53, 0.64), "pan_r": 0.060, "pan_h": 0.012,
         "pan_z": 0.075, "spring_k": 40.0, "note": "Salter scales, late 19th c. (Timespan): the lead rolls up its ramp"
         " (the pan's rim lip at the table, a 4 mm lip), the pan dips under its weight on the spring and tips it on"}
WEIGHTS = {"uid": "999d8e9275d4404ab956e39ce57716a0", "centre": (1.79, 0.56), "r": 0.035, "h": 0.045,
           "note": "a set of nested weights, Krakow, 17th c.: a heavy round wall the file glances toward the brass"}
GLOBE = {"uid": "21f7d2b8d4c743c4a15fe7103460c186", "centre": (2.05, 0.84), "d": 0.30, "stand_h": 0.45,
         "spin0_rad_s": 0.35, "bearing_c": 0.035,
         "note": "Doppelmayr, Nuremberg 1728 (Jagiellonian Univ. Museum): already turning when the shot begins, its"
         " spin decaying by bearing friction, analytic: w(t) = w0 exp(-c t); off the path, never touched"}
SOURCES_NEED_TOKEN = "Sketchfab serves CC0 downloads only to a signed-in account: a free Sketchfab API token is needed"
