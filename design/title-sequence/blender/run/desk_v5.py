"""The Run v5: the collector's desk as a real working desk, one lamp, and the camera language (stdlib only).

Design: design/title-sequence/blender/run/v5-design.md. v5 is a fresh look at LAYOUT, LIGHT and CAMERA; the tuned
v4.1 chain is reused (coordinator, 2026-10-25): the latch, the papyrus, the Atlas's hinge, Piri Reis's curl (U1), the
khipu, the leaf, the nested weights' glance and the run along the back of the desk into the felt keep the poses
`bench.py` and the v4.1 roll-out gave them (sim/v4, b83cfc4). Everything the lead never touches is re-laid here so the
desk reads as one person's work: things squared to the desk or to the thing they rest on, each with a reason to be
where it is, records in date order left to right along the fall.

Desk coordinates as bench.py: metres, origin at the top's near-left corner, x along the length (the 0.95 degree fall,
toward the record), y away from the camera side (the sitter's side is y = 0; the back edge, y = 1.0, stands 0.40 m
from the wall), z up from the top.
"""

from __future__ import annotations

import math

import bench as B

DESK = {"size": B.TABLE["size"], "top": B.TABLE["top"], "height": B.TABLE["height"], "wall_gap": 0.40}
EPS = 0.002

# ------------------------------------------------------------------------------------------------ the lead's path

# The v4.1 roll-out (sim/v4 run-bake.json and the C20-METAR-0851 tail), sampled every 0.25 s: (t s, x, y). The design's
# path; the physics step re-bakes it with the galley strike and the coin row in (v5-design.md, "Hand-offs").
LEAD_V41 = [
    (4.9, 0.338, 0.93), (5.15, 0.339, 0.918), (5.4, 0.353, 0.895), (5.65, 0.381, 0.861), (5.9, 0.422, 0.815),
    (6.15, 0.475, 0.757), (6.4, 0.52, 0.702), (6.65, 0.536, 0.642), (6.9, 0.557, 0.587), (7.15, 0.607, 0.553),
    (7.4, 0.661, 0.521), (7.65, 0.693, 0.47), (7.9, 0.712, 0.407), (8.15, 0.75, 0.358), (8.4, 0.807, 0.323),
    (8.65, 0.853, 0.277), (8.9, 0.885, 0.229), (9.15, 0.907, 0.183), (9.4, 0.922, 0.133), (9.65, 0.934, 0.076),
    (9.9, 0.945, 0.083), (10.15, 0.957, 0.138), (10.4, 0.981, 0.18), (10.65, 1.004, 0.221), (10.9, 1.014, 0.267),
    (11.15, 1.019, 0.316), (11.4, 1.028, 0.364), (11.65, 1.048, 0.409), (11.9, 1.076, 0.448), (12.15, 1.114, 0.483),
    (12.4, 1.16, 0.515), (12.65, 1.211, 0.547), (12.9, 1.269, 0.562), (13.15, 1.313, 0.596), (13.4, 1.313, 0.659),
    (13.65, 1.301, 0.726), (13.9, 1.3, 0.787), (14.15, 1.319, 0.801), (14.4, 1.343, 0.803), (14.65, 1.373, 0.806),
    (14.9, 1.408, 0.808), (15.15, 1.448, 0.81), (15.4, 1.494, 0.812), (15.65, 1.546, 0.814), (15.9, 1.603, 0.815),
    (16.16, 1.667, 0.817), (16.41, 1.735, 0.819), (16.66, 1.809, 0.821), (16.91, 1.852, 0.821), (17.41, 1.869, 0.821),
    (17.91, 1.907, 0.821), (18.41, 1.968, 0.821), (19.41, 1.932, 0.821), (20.41, 1.976, 0.821), (22.16, 1.976, 0.821),
]
LINE_Y = 0.821                              # the run along the back after the weights' glance (v4.1, measured)
LEAD_STOP = (1.976, 0.821)

# ------------------------------------------------------------------------------------------------ the desk, zone by zone

# Each item: kind ("record" | "object" | "tool" | "surface"), its footprint (centre, size along its own u, v, psi from
# +x), its height, its date (records only, for the time order), what it rests on, whether the v4.1 chain fixes it, and
# why a person would have put it there. Sizes are real. "fixed" items keep bench.py's or the roll-out's pose exactly.

def _sheet(name, why, **kw):
    s = B.SHEETS[name]
    d = {"kind": "record", "ledger": s["ledger"], "centre": tuple(s["centre"]), "size": tuple(s["size"]),
         "psi": float(s["psi"]), "h": s["t"], "date": s["date"], "on": "oak", "fixed": True, "why": why}
    d.update(kw)
    return d


ITEMS = {
    # -- the spread being compared (centre-left): fixed by the chain
    "papyrus": _sheet("papyrus", "the Turin map on its linen mount, laid along the open Atlas's left board to compare "
                      "the oldest survey with the portolan; the latch's run lands on it", on="atlas1"),
    "atlas1": _sheet("atlas1", "the Catalan Atlas facsimile lies OPEN, two boards on their hinge, turned toward the "
                     "sitter's left hand the way a big book is read; its near corner rides over the edge"),
    "atlas2": _sheet("atlas2", "the Atlas's right board, under Piri Reis: the two portolans are being compared"),
    "piri": _sheet("piri", "Piri Reis laid over the Atlas's right board, its straight edge to the sitter; the "
                   "parchment remembers being rolled, so its near edge curls (U1)", on="atlas2"),
    "leaf": _sheet("leaf", "the Gutenberg leaf on Piri Reis, the galley of type set on it as a weight and to compare "
                   "the sorts with the printed page", on="piri"),
    # -- tools the work uses, on the spread
    "galley": {"kind": "tool", "centre": (1.113, 0.512), "size": (0.245, 0.09), "psi": 58.0, "h": 0.008, "on": "leaf",
               "fixed": False, "mouth": (1.062, 0.430), "why": "a brass galley of blank sorts, standing on the leaf as a"
               " weight, its open mouth toward the sitter; moved 12 cm onto the lead's line so the lead strikes the row and"
               " the glass pair leaves the lip (the approved galley proof)"},
    "khipu": {"kind": "record", "ledger": "khipu", "centre": (0.99, 0.30), "size": (0.30, 0.012), "psi": 66.0,
              "h": 0.005, "date": 1500, "on": "piri", "fixed": True, "why": "a pendant cord laid out straight on the "
              "parchment to count its knots (as v4.1)"},
    "weights": {"kind": "object", "scan": "weights", "centre": (1.294, 0.841), "size": (0.07, 0.07), "psi": 0.0,
                "h": 0.045, "on": "piri", "fixed": True, "why": "the Krakow nested weights hold Piri Reis's far corner"
                " flat, as a reader weights a curling parchment; next to the coin tray because they weigh coins (the"
                " lead's glance off them sends it along the back of the desk, v4.1 f335)"},
    # -- the oldest record, put away squared at the near-left corner
    "tablet": {"kind": "record", "ledger": "T-01", "centre": (0.165, 0.1625), "size": (0.31, 0.305), "psi": 0.0,
               "h": 0.05, "date": -2040, "on": "oak", "fixed": False, "rests_on_corner": "atlas1",
               "why": "the Umma tablet, the heaviest and oldest thing, squared in the near-left corner within reach; "
               "its far-right corner rests on the Atlas board's overhang (0.4 degree tilt)"},
    "disc": {"kind": "tool", "centre": B.LATCH["disc"], "size": (0.045, 0.045), "psi": 0.0, "h": 0.003, "on": "oak",
             "fixed": True, "why": "the bronze disc of the approved latch"},
    # -- the coin corner, at the back under the lamp: the tray on the lead's line, the weights at its left end
    "tray": {"kind": "tool", "centre": (1.635, 0.835), "size": (0.33, 0.13), "psi": 0.0, "h": 0.016, "on": "oak",
             "fixed": False, "groove_y": LINE_Y, "groove": {"w": 0.020, "depth": 0.006, "x": (1.47, 1.80)},
             "why": "an oak coin tray squared to the back edge, its long groove (open at both ends, as sorting trays"
             " are) along the desk; the coins stand in it on edge to be photographed one by one"},
    # -- the late papers, squared and dealt left to right in date order on bare oak (the next things to read)
    "ino": {"kind": "record", "ledger": "T-08", "centre": (1.615, 0.37), "size": (0.50, 0.289), "psi": 90.0,
            "h": 0.00032, "date": 1821, "on": "oak", "fixed": False, "fold": (2, 2), "panel": (1, 0),
            "why": "Ino's survey sheet folded in quarters as it is stored, squared on the oak"},
    "tape": {"kind": "record", "ledger": "T-09", "centre": (1.53, 0.37), "size": (0.42, 0.012), "psi": 90.0,
             "h": 0.00008, "date": 1844, "on": "ino", "fixed": False, "why": "a length of Morse tape laid along the "
             "folded sheet's left panel"},
    "strip": {"kind": "record", "ledger": "T-16", "centre": (1.745, 0.40), "size": (0.30, 0.035), "psi": 90.0,
              "h": 0.00014, "date": 1895, "on": "ino", "fixed": False, "why": "a short length of 35 mm film along"
              " the sheet's right edge, where the page overlaps it"},
    "card": {"kind": "record", "ledger": "card", "centre": (1.66, 0.12), "size": (0.187, 0.0826), "psi": 0.0,
             "h": 0.000178, "date": 1890, "on": "ino", "fixed": False, "why": "a blank Hollerith card squared on the"
             " folded sheet's near end (moved off the lead's line: the v4.1 bake logs no lead|card contact)"},
    "page": {"kind": "record", "ledger": "T-18", "centre": (1.86, 0.49), "size": (0.216, 0.308), "psi": 0.0,
             "h": 0.0001, "date": 1921, "on": "ino", "fixed": False, "why": "the typed page dealt on top of the sheet's"
             " right edge (newer over older)"},
    "chart": {"kind": "record", "ledger": "T-20", "centre": (2.025, 0.48), "size": (0.333, 0.338), "psi": 90.0,
              "h": 0.00072, "date": 1931, "on": "page", "fixed": False, "fold": (3, 2), "panel": (0, 0),
              "why": "Admiralty chart 983 folded in six as charts are carried, last in the row, at the right end"},
    # -- the reading place: the felt pad under the lamp, the film's record on it
    "felt": {"kind": "surface", "centre": (2.05, 0.83), "size": (0.28, 0.30), "psi": 0.0, "h": B.FELT_T, "on": "oak",
             "fixed": False, "why": "a black felt pad under the lamp, where a new document is laid to be read"},
    "record": {"kind": "record", "ledger": "R-C20-METAR-0851", "centre": (2.08, 0.8645), "size": (0.20, 0.1125),
               "psi": 0.0, "h": B.RECORD_T, "date": 2001, "on": "felt", "fixed": True, "why": "the film's record on the "
               "felt, its near-left edge where the lead comes to rest (v4.1 tail, x0 1.98)"},
    # -- the globe, the right hand's corner
    "globe": {"kind": "object", "scan": "globe", "centre": (2.0, 0.17), "size": (0.24, 0.24), "psi": 0.0,
              "h": 0.45, "on": "oak", "fixed": False, "why": "the Doppelmayr table globe in the near-right corner, in"
              " reach of the right hand; it is still turning slowly when the shot begins (bearing friction)"},
}

# the coin row standing in the tray's groove (gated real scans only: two Roman coins and the Krakow jeton). Each scan
# is used twice, the second time turned over (decision for the founder: v5-design.md).
COIN_ROW = [("FS-coin-dupondius-octavian", 0.029), ("FS-coin-sesterce-trajan", 0.034), ("jeton", 0.028),
            ("FS-coin-dupondius-octavian", 0.029), ("FS-coin-sesterce-trajan", 0.034), ("jeton", 0.028)]
COIN_X0, COIN_PITCH = 1.52, 0.018

# on the wall behind the desk, out of the chain: the stick chart is 0.80 m across and hangs where such charts hang
WALL = {"stick": {"ledger": "T-19", "x": (1.30, 2.10), "z": (0.25, 0.99), "why": "the Marshall Islands stick chart"
                  " hangs on the wall above the back edge (it would cover a third of the desk)"}}

# out of v5 (not real scans, staged, or clutter): the two reels, the platen, the standing brass disc, the gold
OUT = {"reel_reg": "no scan; off the path in v4.1 (impact 3.0, never touched)",
       "reel_film": "no scan; off the path in v4.1",
       "platen": "no scan; not in the v4.1 chain",
       "brass": "a blank brass disc standing on edge is staged; the last coin of the row falls off the groove's end and"
                " spins down on the oak instead (the same Moffatt whir and slap, from a real coin)",
       "gold": "no real scan (founder ruling)"}

# The glass pair: released at the galley (founder ruling), clear glass at its real density (bench.RHO_PAIR)
PAIR = {"material": B.PAIR_MATERIAL, "from": "galley lip"}

# ------------------------------------------------------------------------------------------------ the one lamp

# One physical lamp, constant for the whole shot: a swing-arm reading lamp on the wall behind the desk's back-right,
# its 0.26 m shade 1.40 m over the top, aimed across the desk; the desk is its pool, the felt and the coin tray at its
# brightest, falling off 1.05 stops to the latch and U1 and 1.7 stops to the near-left corner (lamp_falloff_stops). It
# is the off-axis key: from the back-right at 46-73 degrees over the path, every sheet edge and every ball throws its
# contact shadow toward the sitter's side, which is the side the camera works from. No other emitter: the room's fill is this lamp's own
# light off the plaster wall, the ceiling and the floor (a real room, modelled as plain matte surfaces).
LAMP = {"pos": (1.60, 1.25, 1.40), "aim": (1.25, 0.45, 0.0), "shade_d": 0.26, "power_w": 90.0, "kelvin": 3400.0,
        "spread_deg": 110.0, "white_balance_k": 4300.0}
ROOM = {"wall_y": 1.0 + DESK["wall_gap"], "ceiling_z": 2.45 - DESK["height"], "side_x": (-1.1, 3.3),
        "plaster_albedo": 0.42, "floor_albedo": 0.06, "world": 0.0}


def lamp_elevation_deg(x, y):
    """The key's elevation over the desk at (x, y): what sets the contact shadows' length."""
    lx, ly, lz = LAMP["pos"]
    return math.degrees(math.atan2(lz, math.hypot(lx - x, ly - y)))


def lamp_falloff_stops(x, y, ref=(2.08, 0.8645)):
    """Irradiance at (x, y) against the record's, in stops (inverse square and the cosine to the desk's normal)."""
    lx, ly, lz = LAMP["pos"]

    def e(px, py):
        d2 = (lx - px) ** 2 + (ly - py) ** 2 + lz ** 2
        return lz / math.sqrt(d2) / d2

    return math.log2(e(x, y) / e(*ref))


# ------------------------------------------------------------------------------------------------ the camera language

# One camera, one 50 mm lens, a real aperture; it is never cut, faded or remapped. The follow rig is a spring
# (critically damped, omega 3.2 rad/s, about 0.45 s of lag) on a target 4 cm ahead of the lead along its velocity, and
# the eye sits at (distance, elevation, azimuth from the lead's heading) that ease between the named poses below. The
# exposure is the camera's own: metered from the rendered frames (centre-weighted on the lead), eased over 0.8 s,
# clamped to +-1.5 stops. Legibility rules, checked per frame: the lead in frame, inside the centre 60%, at least 28 px
# across at 1080p, in focus (the focus distance is the lead's), and the pan under 40 px a frame.
LENS_MM, SENSOR_MM = 50.0, 36.0
FOLLOW = {"D": 0.42, "elev": 34.0, "az_from_heading": 145.0, "fstop": 4.0, "omega": 3.2, "lead_ahead": 0.04}
CLOSE = {"D": 0.16, "elev": 16.0, "fstop": 2.8}
PASSES = [  # (name, t from, t to (v4.1 seconds), pose) close passes: low, the marble large, the background soft
    ("latch", 0.0, 5.6, "approved latch framing, 0.23 m at 25 degrees down, f/4"),
    ("U1 curl", 9.1, 10.6, "low at the near edge, looking along the curl: the lead climbs toward the lens and rolls back"),
    ("galley strike", 11.4, 12.6, "low beside the galley, square to the row: the sorts fall, the glass pair leaves the lip"),
    ("weights glance", 13.6, 14.4, "the lead meets the weights and turns along the back of the desk"),
    ("coin row", 15.0, 17.4, "low along the groove, the coins falling away from the lens one after another"),
    ("record", 18.2, 22.2, "the lead onto the felt and against the record's edge"),
]
END = {"rise_s": 3.0, "wide_height": 3.40, "wide_hold_s": 2.0, "descend_s": 4.5, "pose_hold_s": 1.0}
PX_1080 = 1920


def marble_px(distance_m, width_px=PX_1080):
    """The lead's on-screen diameter at a distance (pinhole)."""
    return 2 * B.R * LENS_MM / (SENSOR_MM * distance_m) * width_px


def runtime_estimate():
    """The clock the design aims at (seconds): the v4.1 roll-out to the lead's rest, plus what the galley strike and the
    coin row cost the lead (measured in the galley proof: about 0.6 s; the row's six coins at about 0.25 s each), plus
    the end (rise to the wide, hold, descend to the record's A7 pose, hold)."""
    rest = 22.2 + 0.6 + 6 * 0.25
    return rest + END["rise_s"] + END["wide_hold_s"] + END["descend_s"] + END["pose_hold_s"]


# ------------------------------------------------------------------------------------------------ geometry and checks


def corners(item):
    c, (W, H), psi = item["centre"], item["size"], item["psi"]
    return B.corners(c[0], c[1], W, H, psi)


def footprints():
    return {n: corners(it) for n, it in ITEMS.items()}


OVERHANGS = {"atlas1": {"y0": 0.10}}       # the open Atlas's near corner (v4.1, tuned)


def overlaps():
    """Pairs of footprints that overlap, as (a, b)."""
    fp = footprints()
    names = list(fp)
    out = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if B.overlap(fp[a], fp[b]):
                out.append((a, b))
    return out


# every overlap must be a resting-on relation the layout names (one item lies on the other), or the tablet's corner
PLANNED = {("papyrus", "atlas1"), ("atlas1", "atlas2"), ("piri", "atlas2"), ("leaf", "piri"), ("leaf", "atlas2"),
           ("galley", "leaf"), ("galley", "piri"), ("khipu", "piri"), ("khipu", "atlas2"), ("weights", "piri"),
           ("tablet", "atlas1"), ("ino", "tape"), ("ino", "strip"), ("ino", "card"), ("ino", "page"),
           ("strip", "page"), ("page", "chart"), ("felt", "record"), ("papyrus", "atlas2"), ("piri", "atlas1"),
           ("galley", "atlas2"), ("weights", "atlas2"),
           ("papyrus", "piri"),             # the papyrus's tail over Piri Reis's corner (bench layers, as v4.1)
           ("galley", "khipu")}             # the cord's last knot ends under the galley's mouth: the physics step
                                            # checks the lead crosses it into the mouth (v5-design.md, hand-offs)


def records_in_date_order():
    """The records' centres along x against their dates: (name, date, x) sorted by date."""
    return sorted(((n, it["date"], it["centre"][0]) for n, it in ITEMS.items() if it["kind"] == "record"),
                  key=lambda r: r[1])
