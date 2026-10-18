"""The Run, the full take: the bench's constants and the design's clock (stdlib only: MuJoCo, Blender and pytest all
import it).

Everything is in title seconds (t = f / 24 for the design's 24 fps frame numbers), so one simulation and one camera
serve the 24 fps master and the 30000/1001 master alike. World frame: x runs downhill along the bench (the marbles
travel +x), y across it (the camera stands on the -y side), z up; the bench top is z = 0, metres throughout.

The founder's 7-second pan guide (2026-10-17) caps the camera at 11 px a frame horizontally and 6 vertically at
1080p24, so the camera can cross about 0.1 m/s at its highest and a few centimetres a second near the bench. The
marbles' average speed has to match what the camera can follow, so the bench is laid at the scale the camera can
honestly cross in one take (about 2.5 m from the disc to the felt, not the design's 7.2 m), and the run's speed is set
by the bench's fall and each surface's rolling resistance (the design's "tuned in Proof 1" knobs), never by a ramp.
"""

from __future__ import annotations

FPS = 24
NTSC = (30000, 1001)
G = 9.81
R = 0.008                                   # clay marble radius (16 mm)
RHO_CLAY = 1900.0
MASS = RHO_CLAY * 4.0 / 3.0 * 3.141592653589793 * R ** 3

# the bench's fall (along +x), and the latch's own steeper fall by the disc (founder, latch re-proof)
FALL_DEG = 0.3
LOWER_FALL_DEG = 0.5                         # the bench's lower half, from Ino on: the stations take energy, the fall gives it back
PIRI_FALL_DEG = 0.8                          # the design's fall, from Piri Reis's edge to the galley: the run gathers for the type
LATCH_FALL_DEG = 2.5
LATCH_ZONE_X = 0.0                          # the steeper fall ends at the disc's centre line

# rolling resistance as a ratio (MuJoCo's rolling friction is this times R, a length), per surface
RR = {"oak": 0.004, "papyrus": 0.0098, "vellum": 0.0050, "parchment": 0.0035, "leaf": 0.006, "washi": 0.0082,
      "tape": 0.0065, "card": 0.0065, "page": 0.0065, "chart": 0.0065, "felt": 0.035, "brass": 0.001, "bronze": 0.001}

# the grounds in time order, each a sheet lying on the bench, the older one's downhill edge over the next (roof tiles).
# level: the top of the sheet where the marble rolls (m); each edge steps down. size: the sheet's real size (m), its
# length along x and its width along y; tex: the pinned manifest image; u_axis: the bench axis the image's width runs
# along. The papyrus is stepped up onto from bare oak (the latch's approved 0.25 mm edge).
GROUNDS = {
    # size: (W along the image's width, H along its height), metres at real scale; psi: the preferred angle (deg)
    # of the image's width from +x on the bench; under: how far (m, along the path) it lies under the sheet before
    "papyrus": {"ledger": "T-02a", "tex": "T-02a_keyed", "surface": "papyrus", "level": 0.00025,
                "size": (0.60, 0.60 * 1481 / 8192), "psi": 0.0, "alpha": True},
    "atlas": {"ledger": "T-03", "tex": ("T-03_board1", "T-03_board2"), "surface": "vellum", "level": 0.00021,
              "size": (0.50, 0.50 * 3800 / 2760), "psi": -14.0, "under": 0.03},
    "piri": {"ledger": "T-04", "tex": "T-04_keyed", "surface": "parchment", "level": 0.00017,
             "size": (0.65, 0.65 * 2619 / 1964), "psi": 9.0, "alpha": True, "under": 0.04},
    "leaf": {"ledger": "T-06", "tex": "T-06_leaf", "surface": "leaf", "level": 0.00014,
             "size": (0.30, 0.42), "psi": 90.0, "under": 0.04},
    "ino": {"ledger": "T-08", "tex": "T-08_sheet", "surface": "washi", "level": 0.00011,
            "size": (1.0, 1.0 * 4740 / 8192), "psi": -6.0, "under": 0.04},
    "page": {"ledger": "T-18", "tex": "T-18_page", "surface": "page", "level": 0.00007,
             "size": (0.216, 0.216 * 4429 / 3104), "psi": 62.0, "under": 0.03},
    "chart": {"ledger": "T-20", "tex": "T-20_chart", "surface": "chart", "level": 0.00004,
              "size": (1.0, 1.0 * 5529 / 8192), "psi": 4.0, "under": 0.04},
}
HINGE_GAP = 0.0015                          # the Catalan Atlas's two leaves meet with a 1.5 mm valley between boards
TAPE = {"w": 0.012, "len": 0.012 * 8192 / 351, "t": 0.00008}        # Morse's tape (T-09), on Ino, in its valley
CARD = {"len": 0.0826, "w": 0.187, "t": 0.000178, "level": 0.00009}   # a blank Hollerith card, 7 3/8 x 3 1/4 in, 0.007 in, across the path
STRIP = {"w": 0.035, "len": 0.30, "t": 0.00014, "perf": (0.0028, 0.00198, 0.00475)}   # 35 mm: perf w, h, pitch
PLATEN = {"r": 0.020, "len": 0.30}          # the Underwood's platen, a free roller lying beside the path (pinned)
STICK = {"ledger": "T-19", "tex": "T-19_keyed", "size": (0.80, 0.80 * 7602 / 8192), "raise": 0.008, "rib_h": 0.005}
KHIPU = {"cord_r": 0.0011, "knot_r": 0.0024, "knots": 7}
QUAD = (0.00127, 0.00635, 0.01015)          # 36-pt 5-to-em thin space, half extents (2.54 x 12.7 x 20.3 mm)
REEL_REG = {"r": 0.032, "h": 0.012, "mass": 0.012, "damp": 2.0e-6, "fric": 1.5e-6}    # the register's paper reel
REEL_FILM = {"r": 0.045, "h": 0.010, "mass": 0.022, "damp": 3.0e-6, "fric": 2.0e-6}   # the Lumiere spool
BRASS = {"A": 0.025, "T": 0.0015, "rho": 8500.0, "lean_deg": 3.0, "C_HZ": 24.0 * (0.0225 / 0.025) ** 0.5,
         "alpha_land_deg": 5.7}

# the design's event clock (frames at 24 fps): the bake places each station where the lead marble is at its frame
DESIGN = {
    "lamp_up": 36, "slap": 120, "release": 121, "papyrus_edge": 167, "papyrus_fold": 204, "vellum_edge": 239,
    "hinge": 312, "piri_edge": 383, "knots": [396, 399, 414, 426, 429, 432, 435], "leaf_edge": 448,
    "quad1": 462, "ino_folds": [540, 552, 570], "tape": 600, "reel_reg": 618, "card": 656, "page_edge": 672,
    "reel_film": 690, "strip": 700, "platen": 740, "chart_edge": 776, "lattice": 792, "oak_edge": 860,
    "brass_hit": 866, "brass_slap": 926, "prefix_end": 935,
}
PREFIX_FRAMES = 936                         # f0..f935, 39.0 s

# per film: the record, its class label, the tail's windows (approach, close, dissolve, tour) at 24 fps, and the
# years crossed in the dark between the 1931 chart and the record (the oak and felt widths grow with them)
FILMS = {
    "S-130": {"film": "Not a Free Agent", "label": "Archive · 1947", "cls": "ARCHIVE", "year": 1947,
              "tail": (72, 48, 24, 72), "tex": "R-S-130", "width_m": 0.30},
    "S-16928": {"film": "The Next Village", "label": "Archive · 1976", "cls": "ARCHIVE", "year": 1976,
                "tail": (84, 48, 24, 72), "tex": "R-S-16928", "width_m": 0.42},
    "C20-METAR-0851": {"film": "Real World", "label": "Drawn · 2001", "cls": "DRAWN", "year": 2001,
                       "tail": (96, 48, 24, 72), "tex": "R-C20-METAR-0851", "width_m": 0.20},
}
LOCKUP_FRAMES = 120
OAK_PER_YEAR = 0.0015                       # m of bare oak per year after 1931 (the felt begins further on, later)
FELT_LEN = 1.2
FELT_T = 0.0012
RECORD_T = 0.00012


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
    import math
    return int(math.floor(seconds * fps_value(fps) + 1e-6))
