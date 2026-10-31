"""Title v7 "The Record Stands": the shot as numbers (pure numpy, no bpy, no I/O but the committed registration).

Fable's spec (reports/briefs/title-v7: v7-concept.md, v7-beats.json) with the day-1 measurements in place of the design
values (each departure is named where it is made and listed in DEPARTURES):

- World frame = the globe frame ("geo"): the ball's centre at the origin, z the polar axis (north), x through modern
  longitude 0. The scan is registered to it by registration-fit.json (Kabsch on five capes, register_v7.py).
- The globe's diameter D comes from the measured texel density (globe_v7.texel_density: 0.487 px/mm at 4 m, the
  design assumed 0.96), by the spec's diameter rule (lower density shrinks the globe): D = 4.0 * 0.487 / 0.96.
- Boards are hinged on a brass rod on two feet; a board lies on the ball (its far edge touching) and rises about the
  rod to 60 degrees from the tangent plane (leaning back 30 degrees), face toward the arriving camera.
- The camera: keys of (eye, target, up hint, f-stop) interpolated by PCHIP (monotone, no overshoot) with eye and
  target in spherical coordinates, so a flight follows the ball; reads and the close-in are exact board geometry.

Every frame index is a 30000/1001 frame of the 1080-frame shot; the lockup follows on a cut at 1080.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent

FPS_NUM, FPS_DEN = 30000, 1001
FPS = FPS_NUM / FPS_DEN
FRAMES = 1080
LOCKUP_S = 6.0
BAR_STARTS = [0, 60, 120, 180, 240, 300, 360, 420, 480, 539, 599, 659, 719, 779, 839, 899, 959, 1019]
CUT = 719
POSE_FROM = 1019
RAMP_FROM = 1007

# ------------------------------------------------------------------------------------------------ measured world
DENSITY_AT_4M = 0.4874              # px/mm, register/native.json (median over the sphere; the UV uses 18% of 8192^2)
DESIGN_DENSITY = 0.96
D = round(4.0 * DENSITY_AT_4M / DESIGN_DENSITY, 3)    # 2.031 m
R = D / 2
DENSITY = DENSITY_AT_4M * 4.0 / D   # px/mm at D (0.96 by construction)
RING_LON = 22.14                    # the meridian ring's plane, measured (register: ring normal in geo); left where it is

# camera and image
LENS_MM, SENSOR_MM = 35.0, 36.0
RES_REVIEW = (854, 480)
RES_1080 = (1920, 1080)
FILL_CAP = 1.6
COC_PX_1080 = 2.0
FSTOP = {"fly": 5.6, "read": 4.0, "close_in": 2.8, "pose": 4.0}
READ_D = 1.35
POSE_D_FOR_WIDTH = SENSOR_MM / LENS_MM      # frame width per metre of distance (1.0286)

# boards
LEAN_UP_DEG = 60.0
HINGE_H = 0.05                      # the rod's axis above the ball (two brass feet)
HINGE_H_RECORD = 0.22               # the film's record stands higher, so the ball under it falls out of focus in the close-in
ROD_R = 0.003
CARD_T = 0.002
RISE_FRAMES = 46
ZETA, OMEGA = 0.75, 4.75            # damped second order: ~2.7 deg overshoot on an 80 deg rise, peak near 1.0 s

DEPARTURES = [
    "D: measured texel density 0.487 px/mm at 4 m (the sphere is a 5120-triangle icosphere using 18% of its 8192^2 "
    "texture), so by the spec's diameter rule D = 2.031 m; the sheet rule (<= 0.18 D) is not kept: boards keep the "
    "spec's 0.70 m (0.50 m record) so the reads hold 50% of the frame width (B1) with FILL (B2) at the reads",
    "camera distances (read 1.35 m, pose 0.486 m) are kept; flight altitudes scale with D (alt / R as specified)",
    "the Atlas stands at 36N 13E, not 20E: the scan's meridian-ring gap fill (a blurred stripe along 22E) would sit "
    "under the read; the ring is left at its scanned meridian (22.1E), over its own stripe, so it stands behind the "
    "Atlas and is crossed on the fly-on (about f235), not swept under at f30",
    "the hinge is at the board's near edge (the edge toward the arriving camera) so the face rises toward the camera "
    "and leans back 30 degrees; a board lies on the ball before its rise (far edge touching), so its rise starts "
    "below 0 degrees (the angle is measured from the tangent plane at the hinge)",
    "relief: the boards carry a luminance bump, not the Laid Down plates.npz relief",
]

# ------------------------------------------------------------------------------------------------ geometry helpers


def unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def geo_dir(lat, lon):
    la, lo = math.radians(lat), math.radians(lon)
    return np.array([math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)])


def local_frame(lat, lon):
    """(up, north, east) at a place."""
    U = geo_dir(lat, lon)
    E = np.array([-math.sin(math.radians(lon)), math.cos(math.radians(lon)), 0.0])
    N = np.cross(U, E)
    return U, N, E


def heading_dir(lat, lon, bearing):
    _, N, E = local_frame(lat, lon)
    b = math.radians(bearing)
    return math.cos(b) * N + math.sin(b) * E


def sph(p):
    """(r, lat, lon) of a world point."""
    r = float(np.linalg.norm(p))
    return r, math.degrees(math.asin(max(-1.0, min(1.0, p[2] / r)))), math.degrees(math.atan2(p[1], p[0]))


def from_sph(r, lat, lon):
    return r * geo_dir(lat, lon)


def smoothstep(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


@lru_cache(maxsize=1)
def registration() -> np.ndarray:
    """R_geo_to_native (3x3)."""
    return np.array(json.loads((HERE / "registration-fit.json").read_text(encoding="utf-8"))["R"])


# ------------------------------------------------------------------------------------------------ the records

RECORDS = {
    "T-03": {"tex": ["T-03_board1", "T-03_board2"], "date": 1375, "size": (0.70, 0.48), "diptych": True},
    "T-08": {"tex": ["T-08_sheet"], "date": 1821, "size": (0.70, 0.41)},
    "T-20": {"tex": ["T-20_chart"], "date": 1931, "size": (0.70, 0.47)},
    "C20-METAR-0851": {"tex": ["R-C20-METAR-0851"], "date": 2001, "size": (0.50, 0.28125), "label": "Drawn · 2001",
                       "window": [0.0, 0.0, 1.0, 1.0], "film": "real-world"},
}

BOARDS = [
    {"id": "T-03", "place": (36.0, 13.0), "face_bearing": 270.0, "rise": 60, "open": (106, 134),
     "read": (135, 209), "drift_bearing": 180.0},
    {"id": "T-08", "place": (36.0, 138.0), "face_bearing": 270.0, "rise": 420, "read": (466, 553),
     "drift_bearing": 180.0},
    {"id": "T-20", "place": (8.0, 168.0), "face_bearing": 313.0, "rise": 599, "read": (646, 718),
     "drift_bearing": 223.0},
    {"id": "C20-METAR-0851", "place": (40.71, -74.01), "face_bearing": 80.0, "rise": 839, "read": (839, 898),
     "drift_bearing": 170.0, "tail": True},
]


def board(bid):
    return next(b for b in BOARDS if b["id"] == bid)


def in_shot(b, frame) -> bool:
    """Prefix boards exist only before the cut; the film's record only after it."""
    return (frame >= CUT) if b.get("tail") else (frame < CUT)


# ------------------------------------------------------------------------------------------------ board kinematics


def hinge_basis(b):
    """Hinge point (on the rod's axis), H (toward the camera, horizontal), U (up at the place), W (along the rod,
    image right as seen from the camera)."""
    lat, lon = b["place"]
    U = geo_dir(lat, lon)
    H = heading_dir(lat, lon, b["face_bearing"])
    W = np.cross(U, H)          # u x n at 60 deg points this way too; image right from the camera
    return (R + (HINGE_H_RECORD if b.get("tail") else HINGE_H)) * U, H, U, W


def board_dirs(b, theta_deg):
    """u (hinge to top edge) and n (face normal) at rise angle theta (from the tangent plane at the hinge)."""
    _, H, U, W = hinge_basis(b)
    t = math.radians(theta_deg)
    u = -math.cos(t) * H + math.sin(t) * U
    n = math.sin(t) * H + math.cos(t) * U
    return u, n, W


@lru_cache(maxsize=None)
def rest_angle(bid) -> float:
    """The angle at which the board's top edge touches the ball (it lies on the ball before its rise). The film's
    record, on its taller stand, rests level (0 degrees) on the stand like a lectern's lid."""
    b = board(bid)
    if b.get("tail"):
        return 0.0
    h = RECORDS[bid]["size"][1]
    P0, *_ = hinge_basis(b)
    lo, hi = -89.0, 10.0
    for _ in range(60):
        mid = (lo + hi) / 2
        u, n, _ = board_dirs(b, mid)
        top = P0 + h * u - n * (CARD_T / 2)
        if np.linalg.norm(top) < R + 0.0005:
            lo = mid
        else:
            hi = mid
    return hi


SETTLE_DEG = 2.2                    # the one settle (spec: overshoot 1-3 degrees)


def zeta_for(span_deg: float, overshoot_deg: float = SETTLE_DEG) -> float:
    """The damping ratio whose step response overshoots a rise of span_deg by overshoot_deg."""
    lr = math.log(overshoot_deg / span_deg)
    return -lr / math.sqrt(math.pi ** 2 + lr ** 2)


def rise_shape(t: float, zeta: float = ZETA, omega: float = OMEGA) -> float:
    """Unit step response of the damped hinge, tapered to exactly 1 at RISE_FRAMES."""
    T = RISE_FRAMES / FPS
    if t <= 0:
        return 0.0
    if t >= T:
        return 1.0
    wd = omega * math.sqrt(1 - zeta ** 2)
    s = 1 - math.exp(-zeta * omega * t) * (math.cos(wd * t) + zeta * omega / wd * math.sin(wd * t))
    taper = 1 - smoothstep((t - 0.75 * T) / (0.25 * T))
    return 1 + (s - 1) * taper


def rise_angle(bid, frame: float) -> float:
    """Keyed, analytic: from lying on the ball to 60 degrees, one settle of SETTLE_DEG (no simulation)."""
    b = board(bid)
    a0 = rest_angle(bid)
    span = LEAN_UP_DEG - a0
    return a0 + span * rise_shape((frame - b["rise"]) / FPS, zeta_for(span))


def open_angle(frame: float) -> float:
    """The Atlas diptych: board 1 swings about the spine from closed (0) to open (180), keyed ease in-out."""
    a, z = board("T-03")["open"]
    return 180.0 * smoothstep((frame - a) / (z - a))


def panels(bid, frame: float) -> list[dict]:
    """Each panel (a card) as {tex, centre, ex (half-width vector, image +u), ey (half-height vector), normal}."""
    b = board(bid)
    P0, _, _, W = hinge_basis(b)
    th = rise_angle(bid, frame)
    u, n, W = board_dirs(b, th)
    w, h = RECORDS[bid]["size"]
    base = P0 + u * 0.0
    if not RECORDS[bid].get("diptych"):
        c = base + u * (h / 2) + n * (ROD_R + CARD_T / 2)
        return [{"tex": RECORDS[bid]["tex"][0], "centre": c, "ex": W * (w / 2), "ey": u * (h / 2), "normal": n}]
    half = w / 2
    off = n * (ROD_R + CARD_T / 2)
    # board 2 fixed on the right half; board 1 swings about the spine (w = 0) from over board 2 to the left half
    c2 = base + u * (h / 2) + W * (half / 2) + off
    phi = math.radians(open_angle(frame))
    gap = n * (CARD_T + 0.0005)
    d = math.cos(phi) * W + math.sin(phi) * n
    nrm1 = math.sin(phi) * W - math.cos(phi) * n
    c1 = base + u * (h / 2) + off + gap + d * (half / 2)
    # board 1's image runs from its free edge (image left when open) to the spine (image right): ex points to the spine
    return [{"tex": RECORDS[bid]["tex"][0], "centre": c1, "ex": -d * (half / 2), "ey": u * (h / 2), "normal": nrm1},
            {"tex": RECORDS[bid]["tex"][1], "centre": c2, "ex": W * (half / 2), "ey": u * (h / 2), "normal": n}]


def board_centre_up(bid, theta=LEAN_UP_DEG):
    """The risen board's centre (open, whole board) and its u, n, W."""
    b = board(bid)
    P0, *_ = hinge_basis(b)
    u, n, W = board_dirs(b, theta)
    h = RECORDS[bid]["size"][1]
    return P0 + u * (h / 2) + n * (ROD_R + CARD_T / 2), u, n, W


def corners(p):
    c, ex, ey = p["centre"], p["ex"], p["ey"]
    return np.array([c - ex - ey, c + ex - ey, c + ex + ey, c - ex + ey])


# ------------------------------------------------------------------------------------------------ camera


def orbit(lat, lon, bearing, elev_deg, dist, th=0.0):
    """A flight pose: the target on the ball at (lat, lon) (th above it), the camera `dist` back from it along
    `bearing` reversed, `elev_deg` above the target's tangent plane."""
    T = (R + th) * geo_dir(lat, lon)
    U = geo_dir(lat, lon)
    Hd = heading_dir(lat, lon, bearing)
    e = math.radians(elev_deg)
    E = T + dist * (-math.cos(e) * Hd + math.sin(e) * U)
    return E, T


def read_key(bid, frame, lateral, dist=READ_D):
    """On the risen board's normal at `dist`, translated `lateral` metres along the rod (eye and target together,
    so the read drifts: never static, the board kept square)."""
    c, u, n, W = board_centre_up(bid)
    return {"f": frame, "E": c + n * dist + W * lateral, "T": c + W * lateral, "up": u, "fstop": FSTOP["read"],
            "kind": "read"}


def fly_key(frame, lat, lon, bearing, elev, dist, th=0.0, fstop=FSTOP["fly"]):
    E, T = orbit(lat, lon, bearing, elev, dist, th)
    return {"f": frame, "E": E, "T": T, "up": unit(E), "fstop": fstop, "kind": "fly"}


DRIFT = 0.04 / FPS                  # m per frame, lateral, on every read
TAIL_DRIFT = 0.06                   # the record's hold (838-898) drifts 6 cm; the close-in takes it back to centre
READ_PUSH = 0.04                    # each prefix read also pushes in 4 cm (1.35 to 1.31 m): flow at the edges, width 50 to 52%


def _read_pair(bid):
    b = board(bid)
    a, z = b["read"]
    half = DRIFT * (z - a) / 2
    sgn = 1.0 if np.dot(board_centre_up(bid)[3], heading_dir(*b["place"], b["drift_bearing"])) >= 0 else -1.0
    return [read_key(bid, a, -sgn * half), read_key(bid, z, sgn * half, READ_D - READ_PUSH)]


def _arrive(bid, frame, behind=0.05):
    """The arrive key: on the normal, `behind` metres further back along the drift, so the drift continues the
    arrival's lateral motion (no reversal, no stop at the read's first frame)."""
    b = board(bid)
    half = DRIFT * (b["read"][1] - b["read"][0]) / 2
    sgn = 1.0 if np.dot(board_centre_up(bid)[3], heading_dir(*b["place"], b["drift_bearing"])) >= 0 else -1.0
    return dict(read_key(bid, frame, -sgn * (half + behind)), kind="arrive")


DROP_KEYS = [(580, 28.0, 151.0, 116.0, 34.0, 1.85), (606, 14.0, 163.5, 132.0, 33.0, 1.80)]


@lru_cache(maxsize=1)
def keys_prefix():
    k = [fly_key(0, 37.0, -24.0, 90.0, 36.0, 1.95),
         fly_key(40, 36.6, -9.0, 90.0, 34.0, 1.80)]
    k += [_arrive("T-03", 100)]
    k += _read_pair("T-03")
    k += [fly_key(260, 39.0, 44.0, 84.0, 33.0, 2.05),
          fly_key(300, 39.0, 66.0, 86.0, 36.0, 2.35),
          fly_key(360, 37.5, 96.0, 88.0, 34.0, 2.05),
          fly_key(400, 36.5, 118.0, 90.0, 32.0, 1.80)]
    k += [_arrive("T-08", 450)]
    k += _read_pair("T-08")
    k += [fly_key(*a) for a in DROP_KEYS]
    k += [_arrive("T-20", 640)]
    k += _read_pair("T-20")
    return k


@lru_cache(maxsize=1)
def keys_tail():
    lat, lon = BOARDS[3]["place"]
    k = [fly_key(CUT, 42.5, -49.0, 262.0, 34.0, 1.85),
         fly_key(780, 41.5, -60.0, 261.0, 32.0, 1.65)]
    k += [dict(read_key("C20-METAR-0851", 838, 0.0), kind="arrive")]
    a, z = board("C20-METAR-0851")["read"]
    k += [read_key("C20-METAR-0851", 868, -TAIL_DRIFT / 2), read_key("C20-METAR-0851", 898, -TAIL_DRIFT)]
    return k


def _pchip_slopes(h, d):
    """Fritsch-Carlson slopes (scipy's PchipInterpolator scheme): weighted harmonic mean inside, 0 at a sign
    change; the ends by the shape-preserving three-point formula."""
    n = len(d) + 1
    m = np.zeros((n,) + d.shape[1:])
    if n == 2:
        m[0] = m[1] = d[0]
        return m
    w1 = (2 * h[1:] + h[:-1]).reshape((-1,) + (1,) * (d.ndim - 1))
    w2 = (h[1:] + 2 * h[:-1]).reshape((-1,) + (1,) * (d.ndim - 1))
    same = (np.sign(d[:-1]) == np.sign(d[1:])) & (d[:-1] != 0) & (d[1:] != 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        hm = (w1 + w2) / (w1 / d[:-1] + w2 / d[1:])
    m[1:-1] = np.where(same, hm, 0.0)

    def end(h0, h1, d0, d1):
        s = ((2 * h0 + h1) * d0 - h0 * d1) / (h0 + h1)
        s = np.where(np.sign(s) != np.sign(d0), 0.0, s)
        return np.where((np.sign(d0) != np.sign(d1)) & (np.abs(s) > np.abs(3 * d0)), 3 * d0, s)
    m[0] = end(h[0], h[1], d[0], d[1])
    m[-1] = end(h[-1], h[-2], d[-1], d[-2])
    return m


def _pchip(x, y, xi):
    """Monotone piecewise cubic Hermite interpolation along axis 0 (numpy only: CI has no scipy)."""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    xi = np.atleast_1d(np.asarray(xi, float))
    h = np.diff(x)
    sh = (-1,) + (1,) * (y.ndim - 1)
    d = np.diff(y, axis=0) / h.reshape(sh)
    m = _pchip_slopes(h, d)
    k = np.clip(np.searchsorted(x, xi, side="right") - 1, 0, len(x) - 2)
    t = ((xi - x[k]) / h[k]).reshape(sh)
    hk = h[k].reshape(sh)
    h00, h10, h01, h11 = 2 * t ** 3 - 3 * t ** 2 + 1, t ** 3 - 2 * t ** 2 + t, -2 * t ** 3 + 3 * t ** 2, t ** 3 - t ** 2
    return h00 * y[k] + h10 * hk * m[k] + h01 * y[k + 1] + h11 * hk * m[k + 1]


def _interp_keys(keys, frames):
    f = [k["f"] for k in keys]
    Es = np.array([sph(k["E"]) for k in keys])
    Ts = np.array([sph(k["T"]) for k in keys])
    for S in (Es, Ts):
        S[:, 2] = np.degrees(np.unwrap(np.radians(S[:, 2])))
    E = _pchip(f, Es, frames)
    T = _pchip(f, Ts, frames)
    up = _pchip(f, np.array([k["up"] for k in keys]), frames)
    fs = _pchip(f, np.array([k["fstop"] for k in keys]), frames)
    out = []
    for i in range(len(frames)):
        out.append({"E": from_sph(*E[i]), "T": from_sph(*T[i]), "up": unit(up[i]), "fstop": float(fs[i])})
    return out


@lru_cache(maxsize=None)
def camera_at(frame: float) -> dict:
    """{E, T, up, fstop, focus} at a (possibly fractional) frame."""
    frame = float(frame)
    if frame < CUT:
        cam = _interp_keys(keys_prefix(), np.array([min(frame, 718.0)]))[0]
    elif frame <= 898:
        cam = _interp_keys(keys_tail(), np.array([frame]))[0]
    else:
        c, u, n, W = board_centre_up("C20-METAR-0851")
        s = smoothstep((frame - 898) / (1018 - 898))
        d = READ_D + (pose_distance() - READ_D) * s
        lat = -TAIL_DRIFT * (1 - s)
        cam = {"E": c + n * d + W * lat, "T": c + W * lat, "up": u,
               "fstop": FSTOP["close_in"] if frame < POSE_FROM else FSTOP["pose"]}
        if frame < POSE_FROM:
            cam["fstop"] = FSTOP["read"] + (FSTOP["close_in"] - FSTOP["read"]) * smoothstep((frame - 898) / 40)
    cam["focus"] = float(np.linalg.norm(cam["T"] - cam["E"]))
    return cam


def pose_distance() -> float:
    """The distance at which the record's board width fills the frame width exactly."""
    return RECORDS["C20-METAR-0851"]["size"][0] / POSE_D_FOR_WIDTH


def cam_basis(cam):
    f = unit(cam["T"] - cam["E"])
    r = unit(np.cross(f, cam["up"]))
    u = np.cross(r, f)
    return r, u, f


def project(P, cam, res=RES_REVIEW):
    """World points (n,3) -> pixel (n,2) and depth (n,)."""
    r, u, f = cam_basis(cam)
    v = np.atleast_2d(P) - cam["E"]
    z = v @ f
    fpx = res[0] * LENS_MM / SENSOR_MM
    x = res[0] / 2 + fpx * (v @ r) / z
    y = res[1] / 2 - fpx * (v @ u) / z
    return np.stack([x, y], 1), z


def rays(cam, res, nx=48, ny=27):
    r, u, f = cam_basis(cam)
    fpx = res[0] * LENS_MM / SENSOR_MM
    xs = (np.arange(nx) + 0.5) / nx * res[0]
    ys = (np.arange(ny) + 0.5) / ny * res[1]
    X, Y = np.meshgrid(xs, ys)
    d = f[None, :] + ((X.ravel() - res[0] / 2) / fpx)[:, None] * r[None, :] - \
        ((Y.ravel() - res[1] / 2) / fpx)[:, None] * u[None, :]
    return unit(d), X.ravel(), Y.ravel()


def sphere_hit(E, d, radius=None):
    """Distance along unit rays d from E to the ball (inf on a miss)."""
    radius = R if radius is None else radius
    b = d @ E
    c = E @ E - radius ** 2
    disc = b * b - c
    t = -b - np.sqrt(np.maximum(disc, 0))
    return np.where((disc > 0) & (t > 0), t, np.inf)


def coc_px(dist, focus, fstop, res=RES_1080):
    """Circle of confusion diameter in output px (thin lens)."""
    f = LENS_MM / 1000
    A = f / fstop
    coc_m = A * f * np.abs(dist - focus) / (dist * (focus - f))
    return coc_m / (SENSOR_MM / 1000) * res[0]


def fill_at(dist, density_px_per_mm, res=RES_1080):
    """Output px per source px for a surface at `dist` (seen square on) with the given source density."""
    fpx = res[0] * LENS_MM / SENSOR_MM
    return fpx / (dist * 1000) / density_px_per_mm


# ------------------------------------------------------------------------------------------------ the flat-hold


def hold_mix(frame: float) -> float:
    """0 (lit paper) to 1 (the scan's own values) over RAMP_FROM..POSE_FROM-1, 1 from the pose."""
    if frame >= POSE_FROM:
        return 1.0
    return smoothstep((frame - RAMP_FROM + 1) / (POSE_FROM - RAMP_FROM))


def dust_scale(frame: float) -> float:
    """Dust settles out before the pose (nothing new under the pose): full to 989, gone by 1018."""
    return 1.0 - smoothstep((frame - 989) / (1018 - 989))


# ------------------------------------------------------------------------------------------------ Foley events


def foley_events() -> list[dict]:
    ev = []
    for b in BOARDS:
        s = b["rise"] / FPS
        ev.append({"t": s + 0.15, "what": "hinge", "board": b["id"]})
        ev.append({"t": s + RISE_FRAMES / FPS, "what": "settle", "board": b["id"]})
    a, z = board("T-03")["open"]
    ev.append({"t": a / FPS + 0.12, "what": "boards open", "board": "T-03"})
    ev.append({"t": z / FPS, "what": "boards open settle", "board": "T-03"})
    return sorted(ev, key=lambda e: e["t"])
