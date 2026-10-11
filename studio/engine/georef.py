"""void document: georeferencing an archive map sheet (R5b, GRAMMAR A32).

A period sheet carries its own coordinates: the graticule printed at its
neatline. A sheet's ledger item may state a ``georef`` block: control points
read off that graticule (sheet pixel <-> longitude, latitude), the projection
as the sheet states it, the fit, and the fit's residual in sheet pixels. This
module fits it, measures the residual and converts between the two spaces, so
a mark drawn over the sheet lands where its cited coordinates say, and never
claims more precision than the fit and its source allow (``overlays.py``).

    georef = {
      "projection": {"name": "tm", "lon0": 75.75, "lat0": 32.5, "spheroid": "everest1830"},
      "stated": "Transverse Mercator projection (printed in the margin)",
      "fit": "tm",                      # "affine" (on longitude, latitude) | "tm" | "polyconic"
      "control": [{"px": [x, y], "lonlat": [lon, lat], "from": "neatline corner 75°00'E 33°00'N"}, ...],
      "rmse_px": 0.62, "max_px": 1.3,   # recorded; the engine recomputes both and refuses a stale record
      "m_per_px": 37.6,                 # metres per sheet pixel at the sheet's centre (recorded, recomputed)
      "neatline": [75.0, 32.0, 76.5, 33.0],   # the map face: lon0, lat0, lon1, lat1
      "drawn_precision_m": 200,         # how finely the sheet itself draws a boundary
      "verified_by": "..."
    }

Pure functions of their inputs: no clock, no randomness, no file access.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

GEOREF_MIN_POINTS = 4          # A32: at least four control points from the printed graticule
GEOREF_MAX_RMSE_PX = 2.0       # A32: the fit's residual at sheet scale, root mean square
RECORD_TOL_PX = 0.05           # a recorded residual this far from the recomputed one is a stale record
FITS = ("affine", "tm", "polyconic")
# (semi-major axis in metres, inverse flattening); the sphere has no flattening
SPHEROIDS = {
    "everest1830": (6377276.345, 300.8017),
    "wgs84": (6378137.0, 298.257223563),
    "clarke1866": (6378206.4, 294.978698214),
    "sphere": (6371000.0, math.inf),
}
EARTH_R = 6371008.8            # mean radius, for the local metre scale of a pixel


class GeorefError(ValueError):
    """A georef block that cannot be fitted as written."""


def _ellipsoid(name: str) -> tuple[float, float]:
    if name not in SPHEROIDS:
        raise GeorefError(f"unknown spheroid {name!r}; one of {sorted(SPHEROIDS)}")
    a, rf = SPHEROIDS[name]
    f = 0.0 if math.isinf(rf) else 1.0 / rf
    return a, f * (2.0 - f)


def _meridian_arc(phi: float, a: float, e2: float) -> float:
    e4, e6 = e2 * e2, e2 * e2 * e2
    return a * ((1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
                - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * phi)
                + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * phi)
                - (35 * e6 / 3072) * math.sin(6 * phi))


def tm_forward(lon: float, lat: float, lon0: float, lat0: float = 0.0, spheroid: str = "wgs84") -> tuple[float, float]:
    """Transverse Mercator, scale 1 on the central meridian (Snyder 1987, 8-9
    to 8-10). Metres east and north of (lon0, lat0)."""
    a, e2 = _ellipsoid(spheroid)
    ep2 = e2 / (1.0 - e2) if e2 < 1 else 0.0
    phi, lam = math.radians(lat), math.radians(lon - lon0)
    n = a / math.sqrt(1.0 - e2 * math.sin(phi) ** 2)
    t = math.tan(phi) ** 2
    c = ep2 * math.cos(phi) ** 2
    A = lam * math.cos(phi)
    x = n * (A + (1 - t + c) * A ** 3 / 6 + (5 - 18 * t + t * t + 72 * c - 58 * ep2) * A ** 5 / 120)
    y = (_meridian_arc(phi, a, e2) - _meridian_arc(math.radians(lat0), a, e2)
         + n * math.tan(phi) * (A * A / 2 + (5 - t + 9 * c + 4 * c * c) * A ** 4 / 24
                                + (61 - 58 * t + t * t + 600 * c - 330 * ep2) * A ** 6 / 720))
    return x, y


def polyconic_forward(lon: float, lat: float, lon0: float, lat0: float = 0.0, spheroid: str = "everest1830") -> tuple[float, float]:
    """American polyconic (Snyder 1987, 18-1 to 18-3), the Survey of India's
    series projection. Metres east and north of (lon0, lat0)."""
    a, e2 = _ellipsoid(spheroid)
    phi, lam = math.radians(lat), math.radians(lon - lon0)
    m0 = _meridian_arc(math.radians(lat0), a, e2)
    if abs(phi) < 1e-12:
        return a * lam, -m0
    n = a / math.sqrt(1.0 - e2 * math.sin(phi) ** 2)
    e = lam * math.sin(phi)
    cot = 1.0 / math.tan(phi)
    return n * cot * math.sin(e), _meridian_arc(phi, a, e2) - m0 + n * cot * (1.0 - math.cos(e))


@dataclass(frozen=True)
class Fit:
    """A fitted georef: an affine from projected coordinates to sheet pixels."""

    fit: str
    proj: dict
    A: tuple            # 2x3 affine, row-major: px = A @ [u, v, 1]
    residuals: tuple    # px distance per control point
    rmse_px: float
    max_px: float
    m_per_px: float
    centre: tuple       # lon, lat of the control points' centroid

    def project(self, lon: float, lat: float) -> tuple[float, float]:
        return project(self.fit, self.proj, lon, lat)

    def to_px(self, lon: float, lat: float) -> tuple[float, float]:
        u, v = self.project(lon, lat)
        a = self.A
        return a[0] * u + a[1] * v + a[2], a[3] * u + a[4] * v + a[5]

    def to_lonlat(self, x: float, y: float) -> tuple[float, float]:
        """Inverse by Newton on the forward map (closed-form inverses of every
        projection are not needed: the forward map is smooth on a sheet)."""
        lon, lat = self.centre
        for _ in range(30):
            px, py = self.to_px(lon, lat)
            dx, dy = x - px, y - py
            if dx * dx + dy * dy < 1e-14:
                break
            h = 1e-6
            ax, ay = self.to_px(lon + h, lat)
            bx, by = self.to_px(lon, lat + h)
            j = np.array([[(ax - px) / h, (bx - px) / h], [(ay - py) / h, (by - py) / h]])
            d = np.linalg.solve(j, np.array([dx, dy]))
            lon, lat = lon + float(d[0]), lat + float(d[1])
        return lon, lat


def project(fit: str, proj: dict, lon: float, lat: float) -> tuple[float, float]:
    if fit == "affine":
        return lon, lat
    lon0 = float(proj.get("lon0", 0.0))
    lat0 = float(proj.get("lat0", 0.0))
    sph = proj.get("spheroid", "wgs84")
    if fit == "tm":
        return tm_forward(lon, lat, lon0, lat0, sph)
    if fit == "polyconic":
        return polyconic_forward(lon, lat, lon0, lat0, sph)
    raise GeorefError(f"unknown fit {fit!r}; one of {FITS}")


def local_m_per_px(f: Fit, lon: float, lat: float) -> float:
    """Metres per sheet pixel at (lon, lat): the square root of the area a
    pixel covers, on a sphere of the mean radius (better than 0.5% on a sheet)."""
    h = 0.01
    x0, y0 = f.to_px(lon, lat)
    x1, y1 = f.to_px(lon + h, lat)
    x2, y2 = f.to_px(lon, lat + h)
    area_px = abs((x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0))
    area_m = (EARTH_R * math.radians(h) * math.cos(math.radians(lat))) * (EARTH_R * math.radians(h))
    return math.sqrt(area_m / area_px)


def fit(georef: dict) -> Fit:
    """Least-squares affine from the projected control points to their pixels."""
    if not isinstance(georef, dict):
        raise GeorefError("no georef")
    kind = georef.get("fit")
    if kind not in FITS:
        raise GeorefError(f"fit is {kind!r}; one of {FITS}")
    proj = georef.get("projection") or {}
    if kind != "affine" and proj.get("name") != kind:
        raise GeorefError(f"fit {kind!r} needs projection.name {kind!r} (got {proj.get('name')!r})")
    ctl = georef.get("control") or []
    if len(ctl) < 3:
        raise GeorefError(f"{len(ctl)} control points; an affine needs at least 3")
    uv, px = [], []
    for c in ctl:
        lon, lat = (float(v) for v in c["lonlat"])
        uv.append(project(kind, proj, lon, lat))
        px.append([float(v) for v in c["px"]])
    uv_a, px_a = np.array(uv, dtype=float), np.array(px, dtype=float)
    # centre the projected coordinates so the solve is well conditioned (metres are large numbers)
    mu = uv_a.mean(0)
    M = np.column_stack([uv_a - mu, np.ones(len(uv_a))])
    sol, *_ = np.linalg.lstsq(M, px_a, rcond=None)
    a, b, c0 = sol[0, 0], sol[1, 0], sol[2, 0] - sol[0, 0] * mu[0] - sol[1, 0] * mu[1]
    d, e, f0 = sol[0, 1], sol[1, 1], sol[2, 1] - sol[0, 1] * mu[0] - sol[1, 1] * mu[1]
    A = (float(a), float(b), float(c0), float(d), float(e), float(f0))
    pred = np.column_stack([uv_a @ np.array([a, b]) + c0, uv_a @ np.array([d, e]) + f0])
    res = np.sqrt(((pred - px_a) ** 2).sum(1))
    lons = [float(c["lonlat"][0]) for c in ctl]
    lats = [float(c["lonlat"][1]) for c in ctl]
    centre = (sum(lons) / len(lons), sum(lats) / len(lats))
    out = Fit(kind, dict(proj), A, tuple(float(r) for r in res), float(np.sqrt((res ** 2).mean())), float(res.max()),
              0.0, centre)
    return Fit(out.fit, out.proj, out.A, out.residuals, out.rmse_px, out.max_px, local_m_per_px(out, *centre), centre)


def problems(georef) -> list[str]:
    """Why a sheet may not carry a mark (A32, lint overlay-georef): no georef,
    fewer than four control points, a point without its graticule reading,
    a fit that cannot be made, a residual over budget, or a recorded residual
    or scale the fit does not reproduce. Empty when the georef is good."""
    if not georef:
        return ["the sheet has no georef: it is shown plain and may carry no mark"]
    out = []
    ctl = georef.get("control") or []
    if len(ctl) < GEOREF_MIN_POINTS:
        out.append(f"{len(ctl)} control points; at least {GEOREF_MIN_POINTS} from the printed graticule")
    for i, c in enumerate(ctl):
        if not str(c.get("from") or "").strip():
            out.append(f"control point {i} does not say what it was read from")
        if len(c.get("px") or []) != 2 or len(c.get("lonlat") or []) != 2:
            out.append(f"control point {i} needs px [x, y] and lonlat [lon, lat]")
    if out:
        return out
    try:
        f = fit(georef)
    except (GeorefError, KeyError, ValueError, np.linalg.LinAlgError) as e:
        return [f"the georef cannot be fitted: {e}"]
    if f.rmse_px > GEOREF_MAX_RMSE_PX:
        out.append(f"residual {f.rmse_px:.2f} px rms over the budget of {GEOREF_MAX_RMSE_PX} px")
    rec = georef.get("rmse_px")
    if not isinstance(rec, (int, float)) or abs(float(rec) - f.rmse_px) > RECORD_TOL_PX:
        out.append(f"recorded rmse_px {rec!r} is not the fit's {f.rmse_px:.3f}: record it again")
    mpp = georef.get("m_per_px")
    if not isinstance(mpp, (int, float)) or abs(float(mpp) - f.m_per_px) > 0.01 * f.m_per_px:
        out.append(f"recorded m_per_px {mpp!r} is not the fit's {f.m_per_px:.2f}: record it again")
    nl = georef.get("neatline")
    if not (isinstance(nl, list) and len(nl) == 4 and nl[0] < nl[2] and nl[1] < nl[3]):
        out.append("neatline [lon0, lat0, lon1, lat1] of the map face is missing")
    dp = georef.get("drawn_precision_m")
    if not isinstance(dp, (int, float)) or dp <= 0:
        out.append("drawn_precision_m (how finely the sheet draws a line, in metres) is missing")
    return out


def record(georef: dict) -> dict:
    """The georef with its measured residual and scale written in, rounded as
    the ledger records them (a builder's helper; the lint recomputes both)."""
    f = fit(georef)
    out = dict(georef)
    out["rmse_px"] = round(f.rmse_px, 3)
    out["max_px"] = round(f.max_px, 3)
    out["m_per_px"] = round(f.m_per_px, 2)
    return out
